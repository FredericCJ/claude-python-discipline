"""A test that weakens must say so.

Enforces `TEST-016`. Three shapes of silent weakening are reported, and all three
leave a suite that still passes while checking less than it did:

* a skip or an xfail with no reason, which removes a test from the suite and
  leaves nobody a way to know whether the condition still holds;
* a test whose body asserts nothing, which is a name in the pass count and
  nothing else;
* `assert True`, which is the same thing written more confidently.

The pass count is what makes this dangerous. Every one of these keeps the number
green and moves it up, so the signal a reader actually watches improves at the
moment the suite gets weaker. A skip with a stated reason is legitimate and
common -- the point is that the reason is the difference between a decision and
an erosion.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, is_test_path, main

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Marks that remove a test from the suite, or expect it to fail.
WEAKENING_MARKS = frozenset({"skip", "skipif", "xfail"})

## The keyword that turns a removal into a recorded decision.
REASON_KEYWORD = "reason"


class TestWeakeningCheck(ModuleCheck):
    """Reports a skip without a reason, and a test that asserts nothing."""

    ## Invoked as `python -m checks.test_weakening`.
    name = "test_weakening"
    ## The law/TEST rule this check decides.
    rules = ("TEST-016",)

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield findings for silent weakening in a test module.

        Inverted like `oracle_declared`: this examines *only* test files, being
        the rule whose subject is the suite.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param _layer the architectural layer, unused -- a test is a test anywhere
        @return one finding per weakening
        """
        if not is_test_path(path):
            return

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            yield from self._marks(node, path)
            yield from self._body(node, path)

    def _marks(self, node: ast.FunctionDef | ast.AsyncFunctionDef,
               path: Path) -> Iterator[Finding]:
        """Report a weakening mark applied with no stated reason.

        @param node the test function
        @param path the file it came from
        @return one finding per unexplained mark
        """
        for decorator in node.decorator_list:
            call = decorator if isinstance(decorator, ast.Call) else None
            target = call.func if call is not None else decorator
            if not isinstance(target, ast.Attribute) or target.attr not in WEAKENING_MARKS:
                continue
            stated = call is not None and any(
                k.arg == REASON_KEYWORD and _is_nonempty(k.value) for k in call.keywords
            )
            if not stated:
                yield Finding(
                    "TEST-016", path, node.lineno,
                    f"{node.name} is marked `{target.attr}` with no reason",
                    "State why, and what would let it come back. A skip without "
                    "one removes a test from the suite and leaves nobody a way to "
                    "know whether the condition still holds.",
                )

    def _body(self, node: ast.FunctionDef | ast.AsyncFunctionDef,
              path: Path) -> Iterator[Finding]:
        """Report a test that asserts nothing, or asserts a tautology.

        A test raising, calling `pytest.fail`, or using `pytest.raises` asserts
        without an `assert` statement, so those are not reported.

        @param node the test function
        @param path the file it came from
        @return one finding when the body checks nothing
        """
        asserts = [n for n in ast.walk(node) if isinstance(n, ast.Assert)]
        for statement in asserts:
            test = statement.test
            if isinstance(test, ast.Constant) and bool(test.value):
                yield Finding(
                    "TEST-016", path, statement.lineno,
                    f"{node.name} asserts a constant that is always true",
                    "Assert the behaviour, or delete the test. A tautology moves "
                    "the pass count up while checking nothing.",
                )
                return

        if asserts or _has_other_oracle(node):
            return
        yield Finding(
            "TEST-016", path, node.lineno,
            f"{node.name} asserts nothing",
            "A test with no oracle is a name in the pass count. Assert what the "
            "behaviour must be, or say why the call itself is the assertion.",
        )


def _is_nonempty(node: ast.expr) -> bool:
    """Whether an expression is something other than an empty string.

    @param node the keyword's value
    @return True unless it is a literal empty or whitespace-only string
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return bool(node.value.strip())
    return True


def _has_other_oracle(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether a test checks something without an `assert` statement.

    @param node the test function
    @return True when it raises, fails, or uses a raising context manager
    """
    for inner in ast.walk(node):
        if isinstance(inner, ast.Raise):
            return True
        if isinstance(inner, ast.With) and inner.items:
            return True
        if isinstance(inner, ast.Call):
            target = inner.func
            name = target.attr if isinstance(target, ast.Attribute) else getattr(
                target, "id", "")
            if name in {"fail", "raises", "warns", "approx", "exit"}:
                return True
    return False


if __name__ == "__main__":
    raise SystemExit(main(TestWeakeningCheck()))
