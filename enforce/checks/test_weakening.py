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

# Import checker protocols only while static analyzers evaluate contracts.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Unordered pytest mark-name elements that remove or pre-accept a failing test.
WEAKENING_MARKS = frozenset({"skip", "skipif", "xfail"})

## The keyword that turns a removal into a recorded decision.
REASON_KEYWORD = "reason"


class TestWeakeningCheck(ModuleCheck):
    """Reports a skip without a reason, and a test that asserts nothing."""

    ## Invoked as `python -m checks.test_weakening`.
    name = "test_weakening"
    ## Governing rule-id elements in stable mechanism declaration order.
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
        # Ignore production modules because this rule governs only executable tests.
        if not is_test_path(path):
            # End this generator without emitting findings for out-of-scope source.
            return

        # Visit every syntax node that could define a collected test function.
        for node in ast.walk(tree):
            # Discard nodes that cannot carry test marks or executable test bodies.
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Continue the syntax traversal with the next node.
                continue
            # Restrict enforcement to functions pytest collects by canonical name.
            if not node.name.startswith("test_"):
                # Continue with the next callable definition when it is a helper.
                continue
            # Emit unexplained-mark findings before examining the remaining body oracle.
            yield from self._marks(node, path)
            # Emit tautology or missing-oracle findings for the same collected test.
            yield from self._body(node, path)

    def _marks(self, node: ast.FunctionDef | ast.AsyncFunctionDef,
               path: Path) -> Iterator[Finding]:
        """Report a weakening mark applied with no stated reason.

        @param node the test function
        @param path the file it came from
        @return one finding per unexplained mark
        """
        # Inspect decorator elements in lexical application order.
        for decorator in node.decorator_list:
            # Preserve call structure separately from a bare decorator expression.
            call = decorator if isinstance(decorator, ast.Call) else None
            target = call.func if call is not None else decorator
            # Select only attribute-shaped pytest marks in the weakening set.
            if not isinstance(target, ast.Attribute) or target.attr not in WEAKENING_MARKS:
                # Continue with the next unrelated decorator.
                continue
            # Decide whether a call supplies a non-empty reason keyword.
            stated = call is not None and any(
                k.arg == REASON_KEYWORD and _is_nonempty(k.value) for k in call.keywords
            )
            # Report only marks whose removal decision has no stated rationale.
            if not stated:
                # Emit one actionable finding at the affected test declaration.
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
        # Retain assert-statement elements in AST traversal order for oracle analysis.
        asserts = [n for n in ast.walk(node) if isinstance(n, ast.Assert)]
        # Inspect each explicit assertion in traversal order for constant truth.
        for statement in asserts:
            # Isolate the assertion predicate from its optional diagnostic message.
            test = statement.test
            # Recognize a truthy literal that cannot discriminate behavior.
            if isinstance(test, ast.Constant) and bool(test.value):
                # Emit one tautology finding at the exact assertion site.
                yield Finding(
                    "TEST-016", path, statement.lineno,
                    f"{node.name} asserts a constant that is always true",
                    "Assert the behaviour, or delete the test. A tautology moves "
                    "the pass count up while checking nothing.",
                )
                # Stop after the first tautology so one test receives one body finding.
                return

        # Accept a real assertion or one of the supported non-assert oracle forms.
        if asserts or _has_other_oracle(node):
            # End without a weakening finding when the test can discriminate behavior.
            return
        # Emit one missing-oracle finding for a body that only executes code.
        yield Finding(
            "TEST-016", path, node.lineno,
            f"{node.name} asserts nothing",
            "A test with no oracle is a name in the pass count. Assert what the "
            "behaviour must be, or say why the call itself is the assertion.",
        )


def _is_nonempty(node: ast.expr) -> bool:
    """Whether an expression is something other than an empty string.

    @param node the keyword's value
    @return false for a literal empty or whitespace-only string; true otherwise
    """
    # Apply whitespace semantics only to literal string expressions.
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        # Return whether the literal retains any non-whitespace reason content.
        return bool(node.value.strip())
    # Treat every non-literal expression as potentially producing a non-empty reason.
    return True


def _has_other_oracle(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether a test checks something without an `assert` statement.

    @param node the test function
    @return true when it raises, fails, or uses a context oracle; false otherwise
    """
    # Visit every nested syntax node that may encode an alternative test oracle.
    for inner in ast.walk(node):
        # Treat explicit exception raising as an executable rejection oracle.
        if isinstance(inner, ast.Raise):
            # Return immediately once one alternative oracle is proven.
            return True
        # Treat a context manager as a possible pytest raises/warns oracle.
        if isinstance(inner, ast.With) and inner.items:
            # Return immediately because the context owns the behavioral assertion.
            return True
        # Inspect calls for recognized pytest or approximation oracle names.
        if isinstance(inner, ast.Call):
            # Normalize attribute and bare-name call targets to one callable identity.
            target = inner.func
            name = target.attr if isinstance(target, ast.Attribute) else getattr(
                target, "id", "")
            # Accept calls whose semantics explicitly fail or compare behavior.
            if name in {"fail", "raises", "warns", "approx", "exit"}:
                # Return immediately once the alternative oracle is found.
                return True
    # Report false after no explicit or recognized alternative oracle appears.
    return False


# Execute the checker CLI only when this module is the selected process entry point.
if __name__ == "__main__":
    # Propagate the checker verdict as the standalone process exit status.
    raise SystemExit(main(TestWeakeningCheck()))
