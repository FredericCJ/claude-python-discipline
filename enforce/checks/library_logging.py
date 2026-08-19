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

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Calls on the logging module that configure rather than emit.
CONFIGURING = frozenset({"basicConfig", "dictConfig", "fileConfig", "captureWarnings",
                         "disable", "setLoggerClass", "shutdown"})

## Methods on a logger object that change where or whether output goes.
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
    ## The law/DIAG rule this check decides.
    rules = ("DIAG-011",)

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        """Yield findings for each logging configuration call outside the shell.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param layer the architectural layer; the shell is exempt
        @return one finding per configuring call
        """
        if layer == EXEMPT_LAYER or is_test_path(path):
            return

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            attribute = node.func.attr

            if attribute in CONFIGURING and _names_logging(node.func.value):
                yield Finding(
                    "DIAG-011", path, node.lineno,
                    f"library code calls logging.{attribute}()",
                    "Only the process entry point configures logging. A library "
                    "that does it changes how an unrelated part of the "
                    "application behaves, from an import.",
                )
            elif attribute in MUTATING and not _is_null_handler(node):
                yield Finding(
                    "DIAG-011", path, node.lineno,
                    f"library code calls {attribute}() on a logger",
                    "Get a logger and use it; do not change its level or its "
                    "handlers. Attaching a NullHandler is the one exception.",
                )


def _names_logging(expr: ast.expr) -> bool:
    """Whether an expression is the logging module itself.

    @param expr the receiver of an attribute access
    @return True when it is the name `logging`
    """
    return isinstance(expr, ast.Name) and expr.id == "logging"


def _is_null_handler(node: ast.Call) -> bool:
    """Whether a handler call is the permitted `NullHandler` attachment.

    @param node the call expression
    @return True when its single argument constructs a NullHandler
    """
    for argument in node.args:
        if isinstance(argument, ast.Call):
            func = argument.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name == PERMITTED_HANDLER:
                return True
    return False


if __name__ == "__main__":
    raise SystemExit(main(LibraryLoggingCheck()))
