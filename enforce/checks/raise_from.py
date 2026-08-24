"""The exception chain is never broken silently.

Enforces DIAG-005 (cross-layer re-raise chains explicitly), DIAG-006 (context is
accreted with notes, not by re-wrapping), DIAG-007 (`from None` states a reason)
and DIAG-008 (nothing is swallowed).

The chain is the localization. Without it the outermost frame is all that
survives, and the true origin is gone.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, is_test_path, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Unordered broad-exception set whose each element can swallow otherwise recoverable evidence.
_BROAD = frozenset({"Exception", "BaseException"})


class RaiseFromCheck(ModuleCheck):
    """Rejects a handler that loses what it caught.

    Every layer is examined, since a severed chain hides an origin wherever it
    happens; only test files are exempt.
    """

    ## Invoked as `python -m checks.raise_from`.
    name = "raise_from"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("DIAG-005", "DIAG-006", "DIAG-007", "DIAG-008")

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield findings for every `except` clause in one module.

        The file is read again as text because DIAG-007 turns on whether a
        comment sits beside the raise, and comments never enter the tree.

        @param tree the module's syntax tree
        @param path the file it was parsed from, and re-read from here
        @param _layer the architectural layer, unused -- the chain matters in all
        @return finding elements in handler then failure-predicate order

        @par Effects
        Reads the source file at ``path`` once because adjacent comments are absent from ASTs.
        """
        # Tests may intentionally construct broken exception-chain counterexamples.
        if is_test_path(path):
            # Stop iteration for the explicit test-code exemption.
            return
        # Read source-line elements in order so ``from None`` rationale remains inspectable.
        source = path.read_text(encoding="utf-8").splitlines()
        # Inspect each exception-handler element in deterministic AST walk order.
        for handler in _handlers(tree):
            # Yield all evidence-loss findings in predicate order for this handler.
            yield from self._check_handler(handler, path, source)

    def _check_handler(
        self, handler: ast.ExceptHandler, path: Path, source: list[str]
    ) -> Iterator[Finding]:
        """Report every way one handler can destroy the evidence it was given.

        A bare `raise` is deliberately allowed: it re-raises the original with
        its traceback intact, which is the outcome the rule wants.

        The raise scan descends into nested handlers, which are visited again on
        their own turn, so a raise inside a nested `except` is reported once per
        handler enclosing it. Duplicated evidence, never a missed break.

        @param handler the `except` clause
        @param path the file it was parsed from
        @param source source-line elements in file order for the comment DIAG-007 demands
        @return finding elements for a bare `except`, a body that is only `pass`, a raise
            with no cause, an unexplained `from None`, and a broad catch whose
            single act is to re-wrap
        """
        # Collect caught exception-name elements in authored tuple order.
        caught = _caught_names(handler)

        # A bare handler also catches process-control exceptions and hides intent.
        if handler.type is None:
            # Yield the bare-handler finding at the clause line.
            yield Finding(
                "DIAG-008", path, handler.lineno,
                "bare `except` catches control-flow exceptions too",
                "Name the exception types actually handled.",
            )

        # A single pass statement proves the caught failure is discarded silently.
        if _is_only_pass(handler.body):
            # Yield the silent-swallow finding with caught names in declaration order.
            yield Finding(
                "DIAG-008", path, handler.lineno,
                f"catching {', '.join(caught) or 'everything'} and doing nothing",
                "Handle it, convert it, or use an explicit narrow suppression with a comment.",
            )

        # Inspect each nested syntax-node element in deterministic handler walk order.
        for node in ast.walk(handler):
            # Only raise statements can preserve or sever exception causality.
            if not isinstance(node, ast.Raise):
                # Skip non-raise syntax because it cannot preserve exception causality.
                continue
            # A bare `raise` re-raises and preserves the original traceback. It is
            # correct, and is deliberately not flagged -- see meta/CONFLICTS C4.
            # A bare raise preserves the active exception object and traceback.
            if node.exc is None:
                # Advance because this propagation is the desired chain behavior.
                continue
            # ``from None`` explicitly suppresses the cause and therefore owes rationale.
            if _raises_from_none(node):
                # Absence of any nearby comment leaves the evidence destruction unexplained.
                if not _has_adjacent_comment(source, node.lineno):
                    # Yield the unexplained-suppression finding at the raise statement.
                    yield Finding(
                        "DIAG-007", path, node.lineno,
                        "`raise ... from None` discards the cause with no stated reason",
                        "Add a comment saying why the underlying cause is not useful here.",
                    )
                # Advance because explicit suppression is not also missing ``from`` syntax.
                continue
            # Any other raised expression inside a handler must name an explicit cause.
            if node.cause is None:
                # Yield the implicit-context finding at the raise statement.
                yield Finding(
                    "DIAG-005", path, node.lineno,
                    "raising inside a handler without `from`",
                    "Use `raise X from err` so __cause__ records the origin explicitly.",
                )

        # Broad catch plus sole re-wrap adds context while burying useful exception type.
        if _rewraps_only_to_add_context(handler):
            # Yield the note-preferred finding at the handler boundary.
            yield Finding(
                "DIAG-006", path, handler.lineno,
                "re-wrapping an exception only to add context",
                "Attach a note to the live exception instead; wrapping buries the type.",
            )


def _handlers(tree: ast.Module) -> Iterator[ast.ExceptHandler]:
    """Every `except` clause anywhere in a module, however deeply nested.

    @param tree the module's syntax tree
    @return handler elements in deterministic AST traversal order
    """
    # Yield exception handlers whose raises must preserve causal context.
    for node in ast.walk(tree):
        # Yield every exception-handler element at its walk position.
        if isinstance(node, ast.ExceptHandler):
            # Expose the handler to caller-owned predicate ordering.
            yield node


def _caught_names(handler: ast.ExceptHandler) -> list[str]:
    """The exception types a handler names, single or in a tuple.

    Only bare identifiers are collected; a dotted type contributes nothing, so
    `except mod.Exception` reads as catching nothing at all. That costs a
    DIAG-006 finding rather than risking a false one, but it also reaches the
    DIAG-008 message, which then says "catching everything" of a handler that
    named its type.

    @param handler the `except` clause
    @return caught-identifier elements in authored tuple order, empty for a bare ``except``
    """
    # A bare handler has no declared type identity to return.
    if handler.type is None:
        # Return the ordered empty name sequence.
        return []
    # Normalize a tuple of types or single type into authored expression order.
    nodes = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    # Return only bare-name elements, preserving normalized expression order.
    return [n.id for n in nodes if isinstance(n, ast.Name)]


def _is_only_pass(body: list[ast.stmt]) -> bool:
    """Whether a handler's whole body is `pass`.

    The one shape of swallow this recognizes. A body that does something equally
    useless -- `...`, a bare `return`, a `continue` -- is not caught here, so a
    clean run is not a proof that nothing is discarded.

    @param body handler-statement elements in source order
    @return true for exactly one statement when it is ``pass``; false otherwise
    """
    # Match the sole syntactic shape this deliberately narrow swallow predicate owns.
    return len(body) == 1 and isinstance(body[0], ast.Pass)


def _raises_from_none(node: ast.Raise) -> bool:
    """Whether a raise deliberately severs the chain behind it.

    @param node the raise statement
    @return true when its cause is written as literal ``None``; false otherwise
    """
    # Match an explicit constant None cause without treating absent cause as suppression.
    return isinstance(node.cause, ast.Constant) and node.cause.value is None


def _has_adjacent_comment(source: list[str], lineno: int) -> bool:
    """Whether a comment sits on the raise line or the two lines above it.

    Any `#` counts, deliberately. The rule asks the author to state why the
    cause is worthless; no mechanism can grade the answer, so it settles for
    proving the question was put.

    @param source source-line elements in file order
    @param lineno the 1-indexed line the raise starts on
    @return true when any candidate line contains ``#`` anywhere; false otherwise
    """
    # Inspect two preceding offsets then the raise-line offset in chronological order.
    for offset in (-2, -1, 0):
        # Translate the one-based raise line and relative offset into a zero-based index.
        index = lineno - 1 + offset
        # A bounded line containing a comment marker satisfies the shallow rationale predicate.
        if 0 <= index < len(source) and "#" in source[index]:
            # Accept immediately at the first adjacent marker.
            return True
    # No candidate line contains a comment marker.
    return False


def _rewraps_only_to_add_context(handler: ast.ExceptHandler) -> bool:
    """A handler whose entire body re-raises a broad catch as a new exception.

    Catching broadly and immediately re-wrapping adds a layer to the chain
    without adding a decision, which is what DIAG-006 prefers a note for.

    @param handler the `except` clause
    @return true when a broad catch's only statement is a ``raise`` with an operand;
        false otherwise
    """
    # A narrow caught type cannot be the broad-context-only rewrap shape.
    if not any(name in _BROAD for name in _caught_names(handler)):
        # Reject this handler from the predicate.
        return False
    # More than one statement proves the handler makes an additional decision.
    if len(handler.body) != 1:
        # Reject this handler from the sole-rewrap predicate.
        return False
    # Select the only handler-body statement.
    stmt = handler.body[0]
    # Match an explicit raised operand; a bare re-raise correctly preserves type and traceback.
    return isinstance(stmt, ast.Raise) and stmt.exc is not None


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(RaiseFromCheck()))
