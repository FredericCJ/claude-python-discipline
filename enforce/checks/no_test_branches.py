"""Production code never branches on knowing it is under test.

Enforces ARCH-012.

Testability comes from the seam, not from the code recognizing its caller. A
branch that only runs under test is a branch nothing verifies in production, and
the two paths diverge silently from the day it is written.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from . import Check, Finding, is_test_path, main

## Environment variables and attributes whose presence means "we are testing".
TEST_SIGNALS = frozenset({
    "test", "testing", "test_mode", "testmode", "pytest", "unittest",
    "ci", "debug_mode", "is_test", "under_test", "dry_test", "mock",
})

## Modules whose mere importability is used as a test detector.
TEST_MODULES = frozenset({"pytest", "unittest", "unittest.mock", "hypothesis"})


class NoTestBranchesCheck(Check):
    name = "no_test_branches"
    rules = ("ARCH-012",)

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        if is_test_path(path):
            return
        yield from self._env_branches(tree, path)
        yield from self._module_detection(tree, path)

    def _env_branches(self, tree: ast.Module, path: Path) -> Iterator[Finding]:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.If, ast.IfExp)):
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


def _test_signals_in(expr: ast.expr) -> Iterator[str]:
    for node in ast.walk(expr):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.strip().lower().lstrip("-").replace("-", "_") in TEST_SIGNALS:
                yield node.value
        elif isinstance(node, ast.Name) and node.id.lower() in TEST_SIGNALS:
            yield node.id
        elif isinstance(node, ast.Attribute) and node.attr.lower() in TEST_SIGNALS:
            yield node.attr


def _is_sys_modules_probe(node: ast.AST) -> bool:
    if not isinstance(node, ast.Attribute) or node.attr != "modules":
        return False
    return isinstance(node.value, ast.Name) and node.value.id == "sys"


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return False
    nodes = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(isinstance(n, ast.Name) and n.id in {"ImportError", "ModuleNotFoundError"}
               for n in nodes)


def _imports_test_module(body: list[ast.stmt]) -> bool:
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
