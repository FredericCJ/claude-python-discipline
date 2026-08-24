"""Library code configures no logging; it only ever gets a logger.

Enforces `DIAG-011`. A library that calls `basicConfig`, adds a handler or sets a
level has taken a decision belonging to whoever runs the process. The symptom is
familiar: importing a package silently changes how an unrelated part of the
application logs, and nothing in the importing code says so.

The one configuration a library may do is attach a `NullHandler` to its own
logger, which exists precisely so a quiet library stays quiet. That is exempt.

Scoped to everything except the shell, which *is* the process entry point and is
the one layer whose job includes deciding where output goes.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, is_test_path, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Unordered logging-call set whose each element configures process logging rather than emits.
CONFIGURING = frozenset({"basicConfig", "dictConfig", "fileConfig", "captureWarnings",
                         "disable", "setLoggerClass", "shutdown"})

## Unordered logger-method set whose each element changes where or whether output goes.
MUTATING = frozenset({"addHandler", "setLevel", "removeHandler", "addFilter"})

## The handler a library is allowed to attach to its own logger: it decides
## nothing, it only stops a warning about having decided nothing.
PERMITTED_HANDLER = "NullHandler"

## The layer that legitimately configures logging, being the process boundary.
EXEMPT_LAYER = "shell"


class LibraryLoggingCheck(ModuleCheck):
    """Reports library code configuring logging instead of only using it."""

    ## Invoked as `python -m checks.library_logging`.
    name = "library_logging"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("DIAG-011",)

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        """Yield findings for each logging configuration call outside the shell.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param layer the architectural layer; the shell is exempt
        @return finding elements in AST walk order, one per configuring call
        """
        # The shell owns process logging, while test configuration is fixture-local.
        if layer == EXEMPT_LAYER or is_test_path(path):
            # Stop iteration for the two explicitly exempt ownership contexts.
            return

        # Inspect method calls for direct root-logger configuration in library code.
        for node in ast.walk(tree):
            # Only method-style calls can match the configuration shapes owned here.
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                # Advance without interpreting unrelated syntax nodes.
                continue
            # Select the terminal called attribute for closed-vocabulary classification.
            attribute = node.func.attr

            # Module-level configuration calls are forbidden outside the shell.
            if attribute in CONFIGURING and _names_logging(node.func.value):
                # Yield the process-configuration finding at the call site.
                yield Finding(
                    "DIAG-011", path, node.lineno,
                    f"library code calls logging.{attribute}()",
                    "Only the process entry point configures logging. A library "
                    "that does it changes how an unrelated part of the "
                    "application behaves, from an import.",
                )
            # Logger mutation is forbidden except the deliberately inert NullHandler case.
            elif attribute in MUTATING and not _is_null_handler(node):
                # Yield the logger-mutation finding at the call site.
                yield Finding(
                    "DIAG-011", path, node.lineno,
                    f"library code calls {attribute}() on a logger",
                    "Get a logger and use it; do not change its level or its "
                    "handlers. Attaching a NullHandler is the one exception.",
                )


def _names_logging(expr: ast.expr) -> bool:
    """Whether an expression is the logging module itself.

    @param expr the receiver of an attribute access
    @return true when it is the name ``logging``; false otherwise
    """
    # Match only the direct module name, not arbitrary objects ending in a similar attribute.
    return isinstance(expr, ast.Name) and expr.id == "logging"


def _is_null_handler(node: ast.Call) -> bool:
    """Whether a handler call is the permitted `NullHandler` attachment.

    @param node the call expression
    @return true when any argument constructs a ``NullHandler``; false otherwise
    """
    # Inspect each positional-argument element in call order.
    for argument in node.args:
        # Only a nested constructor call can instantiate a handler.
        if isinstance(argument, ast.Call):
            # Select the nested constructor expression.
            func = argument.func
            # Resolve either a qualified terminal attribute or a bare constructor identifier.
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            # The sole permitted handler has the exact stable constructor name.
            if name == PERMITTED_HANDLER:
                # Accept immediately because one inert handler makes this attachment permitted.
                return True
    # No positional argument constructs the permitted handler.
    return False


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(LibraryLoggingCheck()))
