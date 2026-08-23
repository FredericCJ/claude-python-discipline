"""A compound decision is decomposed and tabulated, not written in one line.

Enforces `TEST-014`. A condition joining three operands has eight combinations,
and a suite covering "the true case and the false case" has covered two of them.
The other six are where the defect lives, and nothing in a coverage percentage
distinguishes the two situations -- both report the line as covered.

Decomposing means naming each operand, so the reason for the decision is readable
and each part can be exercised on its own. Tabulating means the combinations are
a table somewhere rather than a shape a reader has to enumerate in their head.

**The threshold is three, and it is a judgement.** Two operands are four cases and
are usually tested exhaustively without anyone deciding to. Three is where a
suite starts sampling without saying so. The number is stated here rather than
hidden in a comparison so that raising or lowering it is a visible decision.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, is_test_path, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Operands above which a condition is reported. Three gives eight combinations,
## which is where a suite starts sampling without saying so.
MAX_OPERANDS = 2


class CompoundGateCheck(ModuleCheck):
    """Reports a conditional whose test joins more operands than can be tabulated."""

    ## Invoked as `python -m checks.compound_gate`.
    name = "compound_gate"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("TEST-014",)

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield a finding per over-compound decision.

        Test files are exempt: a test's own condition is not a decision the suite
        has to cover, and ruff's composite-assertion rule already reports the
        shape that matters there.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param _layer the architectural layer, unused -- the rule binds everywhere
        @return finding elements in AST walk order, one per condition over the threshold
        """
        # Test control flow is fixture machinery rather than a production decision under test.
        if is_test_path(path):
            # Stop iteration because assertion-shape tooling owns test conditions.
            return

        # Inspect each syntax-node element in deterministic AST walk order.
        for node in ast.walk(tree):
            # Only conditional expressions and branch/loop tests define decisions here.
            if not isinstance(node, (ast.If, ast.While, ast.IfExp)):
                # Advance without counting operands in unrelated expressions.
                continue
            # Recursively count boolean leaves joined by this decision.
            operands = _operands(node.test)
            # Decisions at or below the explicit threshold need no forced truth table.
            if operands <= MAX_OPERANDS:
                # Advance to the next syntax node.
                continue
            # Yield the compound-decision finding with its exponential combination count.
            yield Finding(
                "TEST-014", path, node.lineno,
                f"the decision joins {operands} operands, giving "
                f"{2 ** operands} combinations",
                "Name each operand and tabulate the combinations. A suite "
                "covering the true and the false case has covered two of them, "
                "and the coverage figure reads the same either way.",
            )


def _operands(test: ast.expr) -> int:
    """How many boolean operands one condition joins.

    Counts the leaves of a tree of `and`/`or`, so `a and (b or c)` is three. A
    negation is not an operand of its own; it modifies the one beneath it.

    @param test the condition expression
    @return the number of leaves, or 1 for a condition that joins nothing
    """
    # A boolean operator joins the leaves contributed by each value element in source order.
    if isinstance(test, ast.BoolOp):
        # Sum recursive leaf counts across the ordered operand sequence.
        return sum(_operands(value) for value in test.values)
    # Logical negation changes one operand's truth but does not add a new operand.
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        # Delegate the leaf count to the negated expression.
        return _operands(test.operand)
    # Every other condition expression contributes one indivisible operand.
    return 1


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(CompoundGateCheck()))
