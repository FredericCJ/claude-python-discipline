"""Each exception is logged once, at its handling boundary, with its fields intact.

Enforces `DIAG-010` (one log per exception, where it is handled) and `DIAG-015`
(structured fields, not sentences).

The failure `DIAG-010` prevents is the one that makes a log unreadable: a handler
logs an exception and re-raises it, the next handler up does the same, and one
fault appears three times at three levels of detail. A reader counting incidents
counts three. Log where you *handle*; re-raise silently everywhere else.

`DIAG-015`'s half here is narrower than the rule and complements ruff's `G004`:
this reports an exception interpolated into a message *instead of* being passed
as structure. `str(exc)` in an f-string discards the traceback, the cause chain
and every attribute the error carried -- which is the whole diagnostic payload,
turned into prose at the one moment it was needed.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, is_test_path, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Unordered logger-method set whose each element emits a record.
EMITTERS = frozenset({"debug", "info", "warning", "warn", "error", "critical",
                      "exception", "fatal", "log"})

## Unordered structured-keyword set whose each element preserves exception diagnostics.
STRUCTURED = frozenset({"exc_info", "extra", "stack_info"})

## The emitter that records a traceback without being asked, so it never needs
## `exc_info` to satisfy the structured half of the rule.
IMPLIES_TRACEBACK = "exception"


class LogOnceCheck(ModuleCheck):
    """Reports logging and re-raising, and exceptions interpolated into messages."""

    ## Invoked as `python -m checks.log_once`.
    name = "log_once"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("DIAG-010", "DIAG-015")

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield findings for double reporting and for prose-only exceptions.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param _layer the architectural layer, unused -- both rules bind everywhere
        @return finding elements in handler then defect order, one per violation
        """
        # Tests may intentionally construct duplicate or prose-only logging counterexamples.
        if is_test_path(path):
            # Stop iteration for the explicit test-code exemption.
            return
        # Inspect each syntax-node element in deterministic AST walk order.
        for node in ast.walk(tree):
            # Exception handlers are the only scopes with handling-versus-propagation context.
            if isinstance(node, ast.ExceptHandler):
                # Yield double-reporting then structure findings for this handler.
                yield from self._handler(node, path)

    def _handler(self, node: ast.ExceptHandler, path: Path) -> Iterator[Finding]:
        """Report one handler that logs and re-raises, or logs an exception as prose.

        @param node the except clause
        @param path the file it came from
        @return finding elements in double-reporting then log-call order
        """
        # Collect each logging-call element in deterministic handler AST walk order.
        logs = [n for n in ast.walk(node) if _is_log_call(n)]
        # A handler with no logging cannot duplicate reporting or interpolate into a log.
        if not logs:
            # Stop iteration for this handler.
            return

        # Record whether any raise propagates the current bound exception or bare active error.
        reraises = any(
            isinstance(n, ast.Raise) and (n.exc is None or _names(n.exc) == {node.name})
            for n in ast.walk(node)
        )
        # Logging plus propagation causes the next handling boundary to report the same fault.
        if reraises:
            # Yield one duplicate-reporting finding at the first log call.
            yield Finding(
                "DIAG-010", path, logs[0].lineno,
                "this handler logs the exception and re-raises it",
                "Log where you handle, and re-raise silently everywhere else. "
                "One fault logged at three levels reads as three incidents.",
            )

        # Retain the exception alias, or None for an unbound handler.
        bound = node.name
        # Inspect each logging-call element in handler walk order for structure preservation.
        for call in logs:
            # Structured keywords or logger.exception preserve the diagnostic object.
            if _passes_structure(call):
                # Advance because prose interpolation cannot be the sole exception channel.
                continue
            # An unstructured call is defective only when it formats the bound exception.
            if bound and _interpolates(call, bound):
                # Yield the prose-only exception finding at the exact log call.
                yield Finding(
                    "DIAG-015", path, call.lineno,
                    f"the exception `{bound}` is interpolated into the message",
                    "Pass it as structure -- `exc_info=`, or `logger.exception` -- "
                    "so the traceback, the cause chain and the error's own "
                    "attributes survive. A formatted sentence keeps none of them.",
                )


def _is_log_call(node: ast.AST) -> bool:
    """Whether a node is a call to a logger's emitting method.

    @param node any node
    @return true when it calls one of the logging levels on some object; false otherwise
    """
    # Match a method-style call whose terminal attribute belongs to the emitter set.
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in EMITTERS
    )


def _passes_structure(call: ast.Call) -> bool:
    """Whether a log call keeps the exception as structure.

    @param call the logging call
    @return true when a structured keyword is used or the emitter is ``exception``;
        false otherwise
    """
    # ``logger.exception`` carries the active traceback without an explicit keyword.
    if isinstance(call.func, ast.Attribute) and call.func.attr == IMPLIES_TRACEBACK:
        # Accept the implicit structured traceback channel.
        return True
    # Otherwise accept any keyword element whose name belongs to the structured set.
    return any(k.arg in STRUCTURED for k in call.keywords if k.arg)


def _interpolates(call: ast.Call, bound: str) -> bool:
    """Whether a call formats the bound exception into its message.

    @param call the logging call
    @param bound the name the `except` clause bound the exception to
    @return true when the name appears inside an f-string argument; false otherwise
    """
    # Search ordered call arguments, f-string parts, and referenced names for the alias.
    return any(
        isinstance(part, ast.FormattedValue) and bound in _names(part.value)
        for argument in call.args
        if isinstance(argument, ast.JoinedStr)
        for part in argument.values
    )


def _names(expr: ast.expr) -> set[str]:
    """Every bare identifier appearing in an expression.

    @param expr the expression to scan
    @return unordered set whose each element is a bare identifier found
    """
    # Collect each bare-name element from deterministic AST walk into an unordered set.
    return {n.id for n in ast.walk(expr) if isinstance(n, ast.Name)}


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(LogOnceCheck()))
