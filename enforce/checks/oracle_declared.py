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

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## The oracles `law/TEST` admits, strongest first. A module naming none of them
## has not answered the question; a module naming one has, whether or not it
## chose well.
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
    ## The law/TEST and law/FLOW rules this check decides.
    rules = ("FLOW-002", "TEST-004")

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield a finding when a test module declares no oracle.

        Inverted from every other check here: this one examines *only* test files,
        because it is the one rule whose subject is the suite itself.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param _layer the architectural layer, unused -- a test is a test wherever
            it sits
        @return one finding when the module holds tests and names no oracle
        """
        if not is_test_path(path) or not _holds_tests(tree):
            return

        docstring = ast.get_docstring(tree)
        if docstring is None:
            yield Finding(
                "TEST-004", path, 1,
                "test module has no docstring, so it declares no oracle",
                "Open it with what makes its assertions right: one of "
                f"{', '.join(ORACLES)}. A suite with an unstated oracle is "
                "usually asserting whatever the code already did.",
            )
            return

        found = DECLARATION.search(docstring)
        if found is None:
            yield Finding(
                "TEST-004", path, 1,
                "test module declares no oracle",
                f"State it: `Oracle: <one of {', '.join(ORACLES)}>`. It is the "
                "difference between testing the contract and testing the code.",
            )
            return

        claim = found.group("claim").lower()
        if not any(oracle in claim for oracle in ORACLES):
            yield Finding(
                "FLOW-002", path, 1,
                f"the declared oracle names none of the five: {found.group('claim')!r}",
                f"Name one of {', '.join(ORACLES)}. The list is closed so that "
                "'oracle: the tests pass' cannot be written.",
            )


def _holds_tests(tree: ast.Module) -> bool:
    """Whether a module defines at least one test function.

    @param tree the module's syntax tree
    @return True when any top-level or nested function is named `test_*`
    """
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and _TEST_FUNCTION.match(node.name)
        for node in ast.walk(tree)
    )


if __name__ == "__main__":
    raise SystemExit(main(OracleDeclaredCheck()))
