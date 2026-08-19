"""Production code never branches on knowing it is under test.

Enforces ARCH-012.

Testability comes from the seam, not from the code recognizing its caller. A
branch that only runs under test is a branch nothing verifies in production, and
the two paths diverge silently from the day it is written.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Final

from . import Finding, ModuleCheck, is_test_path, main

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Environment variables and attributes whose presence means "we are testing".
TEST_SIGNALS = frozenset({
    "test", "testing", "test_mode", "testmode", "pytest", "unittest",
    "ci", "debug_mode", "is_test", "under_test", "dry_test", "mock",
})

## Modules whose mere importability is used as a test detector. Matched on the
## root package, so the dotted `unittest.mock` entry can never be hit on its own
## -- `unittest` already decides it, and the entry is kept only as documentation
## of the idiom.
TEST_MODULES = frozenset({"pytest", "unittest", "unittest.mock", "hypothesis"})


class NoTestBranchesCheck(ModuleCheck):
    """Rejects production code that behaves differently once it recognizes a test.

    Every layer is examined; test files are exempt, since naming the test
    machinery is exactly their job.
    """

    ## Invoked as `python -m checks.no_test_branches`.
    name = "no_test_branches"
    ## The law/ARCH rule this mechanism decides.
    rules = ("ARCH-012",)

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        """Yield findings for both shapes of test detection in one module.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param layer the architectural layer, unused -- the rule binds everywhere
        @return findings for conditions keyed on a signal, then for runner probes
        """
        if is_test_path(path):
            return
        yield from self._env_branches(tree, path)
        yield from self._module_detection(tree, path)

    def _env_branches(self, tree: ast.Module, path: Path) -> Iterator[Finding]:
        """Report a conditional whose test mentions a known test signal.

        At most one finding per condition: several signals in the same test
        describe one defect, and repeating it teaches the reader nothing.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @return one ARCH-012 finding per offending `if` or conditional expression
        """
        for node in ast.walk(tree):
            if not isinstance(node, (ast.If, ast.IfExp)):
                continue
            if not _reads_a_switch(node.test):
                continue
            for signal in _test_signals_in(node.test):
                yield Finding(
                    "ARCH-012", path, node.lineno,
                    f"production branch keyed on a test signal (`{signal}`)",
                    "Inject a port and substitute it at the composition root (ARCH-011); "
                    "a branch only tests take is a branch production never exercises.",
                )
                break

    def _module_detection(self, tree: ast.Module, path: Path) -> Iterator[Finding]:
        """Report the two idioms that ask the runtime whether a test runner is here.

        A comparison against `sys.modules`, and a `try`-import of a test package
        guarded by `ImportError`. Both make a test dependency's presence a fact
        the program acts on.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @return one ARCH-012 finding per probe, located at the enclosing
            comparison or `try`, which is where a reader can see the branch
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for sub in ast.walk(node):
                    if _is_sys_modules_probe(sub):
                        yield Finding(
                            "ARCH-012", path, node.lineno,
                            "production code detects a test runner via sys.modules",
                            "Remove the detection; substitute behaviour at the seam instead.",
                        )
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    if _catches_import_error(handler) and _imports_test_module(node.body):
                        yield Finding(
                            "ARCH-012", path, node.lineno,
                            "production code branches on whether a test package imports",
                            "Remove the probe; a test dependency must not shape production "
                            "behaviour.",
                        )


## Where a test signal can actually come from. A condition must read one of these
## before a string inside it counts as test detection.
##
## This guard exists because the check reported `zone == "test"` in a real
## codebase whose domain classifies source files into zones -- `ports`, `test`,
## and so on. The string "test" there is a value in a taxonomy the program is
## reasoning ABOUT, not a signal about the process it is running IN. `ARCH-012`
## forbids production code that behaves differently once it recognises a test;
## comparing a domain value that happens to spell "test" recognises nothing.
##
## The distinction is the whole rule: a test signal is something the ENVIRONMENT
## tells the program. A literal on its own tells it nothing.
_SWITCH_SOURCES: Final[frozenset[str]] = frozenset({
    "environ", "getenv", "argv", "flags", "settings", "config", "options",
})


def _reads_a_switch(expr: ast.expr) -> bool:
    """Whether a condition reads something that could carry a test signal.

    Satisfied by an environment or argv read, or by a name or attribute that is
    itself one of the known signals -- `if is_test:` needs no second witness,
    because the name IS the switch.

    @param expr the condition expression
    @return True when the condition consults a plausible signal source
    """
    for node in ast.walk(expr):
        if isinstance(node, ast.Name) and node.id.lower() in TEST_SIGNALS:
            return True
        if isinstance(node, ast.Attribute) and (
            node.attr.lower() in TEST_SIGNALS or node.attr in _SWITCH_SOURCES
        ):
            return True
        if isinstance(node, ast.Call):
            named = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if named in _SWITCH_SOURCES or named in {"getenv", "get"}:
                return True
        if isinstance(node, ast.Subscript):
            inner = node.value
            if getattr(inner, "attr", getattr(inner, "id", "")) in _SWITCH_SOURCES:
                return True
    return False


def _test_signals_in(expr: ast.expr) -> Iterator[str]:
    """Every mention of a known test signal inside a condition.

    A string constant is normalized before matching -- trimmed, lowercased,
    leading dashes stripped, remaining dashes turned into underscores -- so
    `--test-mode` and `TEST_MODE` both land. A name or an attribute matches on
    its identifier alone, whatever it was read from.

    @param expr the condition expression, searched to any depth
    @return the signals as they were written in the source, in traversal order
    """
    for node in ast.walk(expr):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.strip().lower().lstrip("-").replace("-", "_") in TEST_SIGNALS:
                yield node.value
        elif isinstance(node, ast.Name) and node.id.lower() in TEST_SIGNALS:
            yield node.id
        elif isinstance(node, ast.Attribute) and node.attr.lower() in TEST_SIGNALS:
            yield node.attr


def _is_sys_modules_probe(node: ast.AST) -> bool:
    """Whether a node reads the loaded-module table, the usual runner detector.

    The literal name `sys` is required, so an aliased import slips through. That
    is the false negative this shape accepts in exchange for never accusing an
    unrelated `.modules` attribute.

    @param node any node
    @return True when it is an attribute access spelled `sys.modules`
    """
    if not isinstance(node, ast.Attribute) or node.attr != "modules":
        return False
    return isinstance(node.value, ast.Name) and node.value.id == "sys"


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    """Whether a handler is positioned to absorb a failed import.

    @param handler the `except` clause
    @return True when `ImportError` or `ModuleNotFoundError` is named plainly
        among its types; a dotted or aliased spelling is not recognized
    """
    if handler.type is None:
        return False
    nodes = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(isinstance(n, ast.Name) and n.id in {"ImportError", "ModuleNotFoundError"}
               for n in nodes)


def _imports_test_module(body: list[ast.stmt]) -> bool:
    """Whether a guarded block pulls in a test package directly.

    Only statements at the block's own level count; an import buried inside a
    nested function is not the availability probe this looks for. Matching is on
    the root package, so `unittest.mock` answers to `unittest`.

    @param body the statements the `try` guards
    @return True when any of them imports a package that only tests should need
    """
    for stmt in body:
        if isinstance(stmt, ast.Import):
            if any(a.name.split(".", 1)[0] in TEST_MODULES for a in stmt.names):
                return True
        elif isinstance(stmt, ast.ImportFrom) and stmt.module:
            if stmt.module.split(".", 1)[0] in TEST_MODULES:
                return True
    return False


if __name__ == "__main__":
    raise SystemExit(main(NoTestBranchesCheck()))
