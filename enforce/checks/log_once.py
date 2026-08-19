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

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Logger methods that emit a record.
EMITTERS = frozenset({"debug", "info", "warning", "warn", "error", "critical",
                      "exception", "fatal", "log"})

## Keywords that carry an exception as structure rather than as prose. A call
## using one of these has kept what the interpolation would have thrown away.
STRUCTURED = frozenset({"exc_info", "extra", "stack_info"})

## The emitter that records a traceback without being asked, so it never needs
## `exc_info` to satisfy the structured half of the rule.
IMPLIES_TRACEBACK = "exception"


class LogOnceCheck(ModuleCheck):
    """Reports logging and re-raising, and exceptions interpolated into messages."""

    ## Invoked as `python -m checks.log_once`.
    name = "log_once"
    ## The law/DIAG rules this check decides.
    rules = ("DIAG-010", "DIAG-015")

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield findings for double reporting and for prose-only exceptions.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param _layer the architectural layer, unused -- both rules bind everywhere
        @return one finding per violation
        """
        if is_test_path(path):
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                yield from self._handler(node, path)

    def _handler(self, node: ast.ExceptHandler, path: Path) -> Iterator[Finding]:
        """Report one handler that logs and re-raises, or logs an exception as prose.

        @param node the except clause
        @param path the file it came from
        @return findings for each defect in this handler
        """
        logs = [n for n in ast.walk(node) if _is_log_call(n)]
        if not logs:
            return

        reraises = any(
            isinstance(n, ast.Raise) and (n.exc is None or _names(n.exc) == {node.name})
            for n in ast.walk(node)
        )
        if reraises:
            yield Finding(
                "DIAG-010", path, logs[0].lineno,
                "this handler logs the exception and re-raises it",
                "Log where you handle, and re-raise silently everywhere else. "
                "One fault logged at three levels reads as three incidents.",
            )

        bound = node.name
        for call in logs:
            if _passes_structure(call):
                continue
            if bound and _interpolates(call, bound):
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
    @return True when it calls one of the logging levels on some object
    """
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in EMITTERS
    )


def _passes_structure(call: ast.Call) -> bool:
    """Whether a log call keeps the exception as structure.

    @param call the logging call
    @return True when a structured keyword is used, or the emitter is `exception`
    """
    if isinstance(call.func, ast.Attribute) and call.func.attr == IMPLIES_TRACEBACK:
        return True
    return any(k.arg in STRUCTURED for k in call.keywords if k.arg)


def _interpolates(call: ast.Call, bound: str) -> bool:
    """Whether a call formats the bound exception into its message.

    @param call the logging call
    @param bound the name the `except` clause bound the exception to
    @return True when the name appears inside an f-string argument
    """
    return any(
        isinstance(part, ast.FormattedValue) and bound in _names(part.value)
        for argument in call.args
        if isinstance(argument, ast.JoinedStr)
        for part in argument.values
    )


def _names(expr: ast.expr) -> set[str]:
    """Every bare identifier appearing in an expression.

    @param expr the expression to scan
    @return the identifiers found
    """
    return {n.id for n in ast.walk(expr) if isinstance(n, ast.Name)}


if __name__ == "__main__":
    raise SystemExit(main(LogOnceCheck()))
