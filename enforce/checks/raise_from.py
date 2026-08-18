"""The exception chain is never broken silently.

Enforces DIAG-005 (cross-layer re-raise chains explicitly), DIAG-006 (context is
accreted with notes, not by re-wrapping), DIAG-007 (`from None` states a reason)
and DIAG-008 (nothing is swallowed).

The chain is the localization. Without it the outermost frame is all that
survives, and the true origin is gone.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from . import Check, Finding, is_test_path, main

## Catching one of these and doing nothing is the failure mode no diagnostic
## machinery can recover from: nothing is emitted to analyse.
_BROAD = frozenset({"Exception", "BaseException"})


class RaiseFromCheck(Check):
    name = "raise_from"
    rules = ("DIAG-005", "DIAG-006", "DIAG-007", "DIAG-008")

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        if is_test_path(path):
            return
        source = path.read_text(encoding="utf-8").splitlines()
        for handler in _handlers(tree):
            yield from self._check_handler(handler, path, source)

    def _check_handler(
        self, handler: ast.ExceptHandler, path: Path, source: list[str]
    ) -> Iterator[Finding]:
        caught = _caught_names(handler)

        if handler.type is None:
            yield Finding(
                "DIAG-008", path, handler.lineno,
                "bare `except` catches control-flow exceptions too",
                "Name the exception types actually handled.",
            )

        if _is_only_pass(handler.body):
            yield Finding(
                "DIAG-008", path, handler.lineno,
                f"catching {', '.join(caught) or 'everything'} and doing nothing",
                "Handle it, convert it, or use an explicit narrow suppression with a comment.",
            )

        for node in ast.walk(handler):
            if not isinstance(node, ast.Raise):
                continue
            # A bare `raise` re-raises and preserves the original traceback. It is
            # correct, and is deliberately not flagged -- see meta/CONFLICTS C4.
            if node.exc is None:
                continue
            if _raises_from_none(node):
                if not _has_adjacent_comment(source, node.lineno):
                    yield Finding(
                        "DIAG-007", path, node.lineno,
                        "`raise ... from None` discards the cause with no stated reason",
                        "Add a comment saying why the underlying cause is not useful here.",
                    )
                continue
            if node.cause is None:
                yield Finding(
                    "DIAG-005", path, node.lineno,
                    "raising inside a handler without `from`",
                    "Use `raise X from err` so __cause__ records the origin explicitly.",
                )

        if _rewraps_only_to_add_context(handler):
            yield Finding(
                "DIAG-006", path, handler.lineno,
                "re-wrapping an exception only to add context",
                "Attach a note to the live exception instead; wrapping buries the type.",
            )


def _handlers(tree: ast.Module) -> Iterator[ast.ExceptHandler]:
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            yield node


def _caught_names(handler: ast.ExceptHandler) -> list[str]:
    if handler.type is None:
        return []
    nodes = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return [n.id for n in nodes if isinstance(n, ast.Name)]


def _is_only_pass(body: list[ast.stmt]) -> bool:
    return len(body) == 1 and isinstance(body[0], ast.Pass)


def _raises_from_none(node: ast.Raise) -> bool:
    return isinstance(node.cause, ast.Constant) and node.cause.value is None


def _has_adjacent_comment(source: list[str], lineno: int) -> bool:
    """A comment on the raise line, or on either line around it."""
    for offset in (-2, -1, 0):
        index = lineno - 1 + offset
        if 0 <= index < len(source) and "#" in source[index]:
            return True
    return False


def _rewraps_only_to_add_context(handler: ast.ExceptHandler) -> bool:
    """A handler whose entire body re-raises a broad catch as a new exception.

    Catching broadly and immediately re-wrapping adds a layer to the chain
    without adding a decision, which is what DIAG-006 prefers a note for.
    """
    if not any(name in _BROAD for name in _caught_names(handler)):
        return False
    if len(handler.body) != 1:
        return False
    stmt = handler.body[0]
    return isinstance(stmt, ast.Raise) and stmt.exc is not None


if __name__ == "__main__":
    raise SystemExit(main(RaiseFromCheck()))
