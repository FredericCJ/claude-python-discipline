"""Every test module says what makes its assertions right.

Enforces `TEST-004` (a test module names its oracle in its docstring) and
`FLOW-002` (the obligations are named before the tests are written).

The failure this prevents is specific and common: a suite whose oracle is
"whatever the implementation did when I wrote this". Such a suite passes forever,
including across the introduction of the defect it was supposed to catch, because
it was written by reading the output rather than the contract. Naming the oracle
does not make a suite good, but it makes the bad case *sayable* -- there is no
honest way to write "oracle: whatever the code did".

The five oracles are `law/TEST`'s own list, strongest first: contract, property,
differential, golden, example.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, is_test_path, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Oracle-name elements ordered by decreasing evidentiary strength admitted by ``law/TEST``.
ORACLES: tuple[str, ...] = ("contract", "property", "differential", "golden", "example")

## Matches an oracle word only where the module is claiming one, not merely using
## the word in passing. `Oracle: contract` and `**Oracle: the port's contract**`
## both count; a sentence about "the contract suite" elsewhere does not.
DECLARATION = re.compile(
    r"\*{0,2}oracle\*{0,2}\s*[:\-—]\s*(?P<claim>[^\n]{3,200})",
    re.IGNORECASE,
)

## A file holding no test at all -- a conftest, a helper module -- has no oracle
## to declare, so requiring one would be requiring a sentence about nothing.
_TEST_FUNCTION = re.compile(r"^test_")


class OracleDeclaredCheck(ModuleCheck):
    """Reports a test module that does not say what its assertions rest on."""

    ## Invoked as `python -m checks.oracle_declared`.
    name = "oracle_declared"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("FLOW-002", "TEST-004")

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield a finding when a test module declares no oracle.

        Inverted from every other check here: this one examines *only* test files,
        because it is the one rule whose subject is the suite itself.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param _layer the architectural layer, unused -- a test is a test wherever
            it sits
        @return zero or one finding element for the earliest oracle-declaration defect
        """
        # Only modules that both look like tests and define tests own an oracle declaration.
        if not is_test_path(path) or not _holds_tests(tree):
            # Stop iteration for production and helper-only modules.
            return

        # Extract the module contract text that owns the oracle declaration.
        docstring = ast.get_docstring(tree)
        # Absence prevents even a malformed oracle claim from being inspected.
        if docstring is None:
            # Yield the missing-docstring finding before stopping this single-defect check.
            yield Finding(
                "TEST-004", path, 1,
                "test module has no docstring, so it declares no oracle",
                "Open it with what makes its assertions right: one of "
                f"{', '.join(ORACLES)}. A suite with an unstated oracle is "
                "usually asserting whatever the code already did.",
            )
            # Stop after the earliest actionable module-level defect.
            return

        # Search the module contract for one syntactically explicit oracle claim.
        found = DECLARATION.search(docstring)
        # A docstring without the declaration leaves assertion authority unstated.
        if found is None:
            # Yield the missing-declaration finding before stopping this single-defect check.
            yield Finding(
                "TEST-004", path, 1,
                "test module declares no oracle",
                f"State it: `Oracle: <one of {', '.join(ORACLES)}>`. It is the "
                "difference between testing the contract and testing the code.",
            )
            # Stop after the earliest actionable module-level defect.
            return

        # Normalize the claimed oracle prose for closed-vocabulary membership.
        claim = found.group("claim").lower()
        # The declared prose must name at least one admitted oracle category.
        if not any(oracle in claim for oracle in ORACLES):
            # Yield the unknown-oracle finding without judging which admitted choice is best.
            yield Finding(
                "FLOW-002", path, 1,
                f"the declared oracle names none of the five: {found.group('claim')!r}",
                f"Name one of {', '.join(ORACLES)}. The list is closed so that "
                "'oracle: the tests pass' cannot be written.",
            )


def _holds_tests(tree: ast.Module) -> bool:
    """Whether a module defines at least one test function.

    @param tree the module's syntax tree
    @return true when any walked function element is named ``test_*``; false otherwise
    """
    # Reduce deterministic AST walk elements to the test-function presence predicate.
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and _TEST_FUNCTION.match(node.name)
        for node in ast.walk(tree)
    )


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(OracleDeclaredCheck()))
