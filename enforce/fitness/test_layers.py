"""Every test layer exists, is populated, and stays inside what it may touch.

**Oracle: contract.** `law/TEST`'s own table of layers, held against a project.

* `TEST-002`, `TEST-007`, `FLOW-010` -- each layer exists and has tests in it
* `TEST-001` -- the unit layer touches no external resource

An untested seam is not visibly untested: it looks exactly like a tested one
until it fails. That is the whole argument for `TEST-002`, and it is why an
*empty* layer directory is a failure here rather than a neutral state -- an empty
`fault/` reads, to anyone glancing at the tree, as fault coverage.

    pytest enforce/fitness/test_layers.py
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, Final

from decides import decides
from fixtures import broken_copy, reference_root

# Import path typing only while static analyzers evaluate fixture contracts.
if TYPE_CHECKING:
    from pathlib import Path

## Required test-layer-name elements in canonical execution and diagnostic order.
## A project may add more; it may not omit one and call the suite whole.
LAYERS: Final[tuple[str, ...]] = ("unit", "contract", "integration", "fault", "property")

## Evidence that a property suite draws its input rather than listing it.
## `TEST-007` is about the form of the test, and these are the ways this
## toolchain expresses generation.
_GENERATED = re.compile(r"@given|hypothesis|strategies|st\.|@settings")

## Unordered root-module-name elements forbidden from the unit layer because each
## can fail for reasons outside the code under test.
FORBIDDEN_IN_UNIT: Final[frozenset[str]] = frozenset({
    "os", "io", "pathlib", "socket", "subprocess", "shutil", "tempfile",
    "sqlite3", "http", "urllib", "requests", "httpx", "asyncio", "threading",
    "multiprocessing", "random", "secrets", "time", "datetime", "logging",
})


def named_tests_in(path: Path) -> list[str]:
    """Every test function a module defines.

    @param path the module to read
    @return test-function-name elements in AST traversal order
    """
    # Parse declarations without importing or executing the inspected test module.
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    # Return test-function names in deterministic syntax-tree traversal order.
    return [
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]


def imports_of(path: Path) -> set[str]:
    """Every root module a file imports.

    @param path the module to read
    @return unordered imported root-module-name elements
    """
    # Parse imports without importing or executing the inspected test module.
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    # Accumulate unique imported root-module-name elements without ordering semantics.
    found: set[str] = set()
    # Visit every syntax node because imports may occur beneath control flow.
    for node in ast.walk(tree):
        # Expand direct-import aliases to root module identities.
        if isinstance(node, ast.Import):
            # Merge direct-import roots into the unordered dependency set.
            found |= {a.name.split(".", 1)[0] for a in node.names}
        # Accept from-imports only when they name a concrete module.
        elif isinstance(node, ast.ImportFrom) and node.module:
            # Add the from-import root module identity to the dependency set.
            found.add(node.module.split(".", 1)[0])
    # Return the complete dependency-name set after syntax traversal.
    return found


# ------------------------------------------- TEST-002 / TEST-007 / FLOW-010


@decides("TEST-002")
def test_layers_populated() -> None:
    """TEST-002, TEST-007, FLOW-010: every layer exists and holds tests.

    An empty layer is worse than a missing one. A missing directory prompts the
    question; an empty one answers it wrongly.
    """
    # Resolve the conformant project before visiting required layers in canonical order.
    root = reference_root()
    # Check every required layer name in its declared diagnostic order.
    for layer in LAYERS:
        # Resolve the layer directory and require its physical presence first.
        directory = root / "tests" / layer
        assert directory.is_dir(), (
            f"the {layer} layer does not exist. An untested seam looks exactly "
            f"like a tested one until it fails."
        )
        # Collect test-function-name elements by sorted module and AST traversal order.
        names = [n for module in sorted(directory.rglob("test_*.py"))
                 for n in named_tests_in(module)]
        # Reject a present but empty layer that would falsely signal coverage.
        assert names, f"the {layer} layer exists and contains no test"


def test_an_empty_layer_is_caught(tmp_path: Path) -> None:
    """The negative case: a directory that is present and proves nothing.

    @param tmp_path the fixture directory

    @par Effects
    Creates an isolated project copy with the fault-layer test removed.
    """
    # Remove the only fault test while retaining the misleading layer directory.
    root = broken_copy(tmp_path, drop=["tests/fault/test_containment.py"])
    # Collect remaining fault-test path elements in filesystem traversal order.
    populated = list((root / "tests" / "fault").rglob("test_*.py"))
    # Require the negative fixture to exercise the empty-layer condition exactly.
    assert populated == []


# ------------------------------------------------------------------- TEST-001


@decides("TEST-001")
def test_unit_layer_is_pure() -> None:
    """TEST-001: the unit layer imports nothing that can fail for its own reasons.

    The rule is about *localization*, not speed. A unit test that can fail
    because a directory was missing tells you nothing about the code it names.
    """
    # Resolve the conformant project before scanning unit modules in sorted path order.
    root = reference_root()
    # Inspect every unit-test module path deterministically.
    for module in sorted((root / "tests" / "unit").rglob("*.py")):
        # Intersect unordered imported-module elements with prohibited resource modules.
        reached = imports_of(module) & FORBIDDEN_IN_UNIT
        # Reject any unit test whose environment can independently produce failure.
        assert not reached, (
            f"{module.name} imports {', '.join(sorted(reached))} at the unit "
            f"layer. Move it to integration, or take the capability as a port."
        )


def test_an_impure_unit_test_is_caught(tmp_path: Path) -> None:
    """The negative case.

    @param tmp_path the fixture directory

    @par Effects
    Creates an isolated project containing one resource-reaching unit test.
    """
    # Build a negative fixture whose unit test reaches the filesystem path module.
    root = broken_copy(tmp_path, write={
        "tests/unit/test_impure.py":
            '"""Tests. Oracle: example."""\n\nimport pathlib\n\n\n'
            'def test_it():\n    """Touches a disk."""\n'
            '    assert pathlib.Path(".").exists()\n',
    })
    # Isolate unordered forbidden root-module-name elements imported by the fixture.
    reached = imports_of(root / "tests" / "unit" / "test_impure.py") & FORBIDDEN_IN_UNIT
    # Require the negative subject to identify exactly the injected resource dependency.
    assert reached == {"pathlib"}


@decides("TEST-007")
def test_property_suites_are_generated() -> None:
    """TEST-007: an invariant is tested over generated input, not three examples.

    The rule names the form, not merely the presence: round-trip, idempotence,
    involution, ordering and closure "MUST be expressed as generated-input
    property tests, not as hand-picked examples". A directory called `property/`
    holding three `assert f(2) == 2` lines satisfies every structural check that
    only counts files, and tests nothing a unit test was not already testing.

    Until v3.1 this rule was claimed by `test_layers_populated`, which counts
    named tests per layer and cannot tell the two apart.
    """
    # Resolve the reference and collect property-module path elements in sorted order.
    root = reference_root()
    modules = sorted((root / "tests" / "property").rglob("test_*.py"))
    # Reject a missing property layer subject before inspecting generation evidence.
    assert modules, "no property suite; a stated invariant has nowhere to be tested"

    # Inspect each property module in deterministic path order.
    for module in modules:
        # Read source as the generated-input vocabulary search surface.
        text = module.read_text(encoding="utf-8")
        # Require evidence that the property draws cases rather than listing examples.
        assert _GENERATED.search(text), (
            f"{module.name} is in the property layer and draws no generated "
            f"input. Hand-picked examples test the cases someone thought of, "
            f"which are the cases already covered by the unit suite."
        )


def test_a_property_suite_of_examples_is_caught(tmp_path: Path) -> None:
    """The negative case: a property module that only tries what someone typed.

    @param tmp_path the fixture directory

    @par Effects
    Creates an isolated project containing a hand-picked property example.
    """
    # Build a negative fixture whose property directory contains only one literal case.
    root = broken_copy(tmp_path, write={
        "tests/property/test_examples.py":
            '"""Oracle: property."""\n\n\ndef test_round_trip():\n'
            '    """Round trip."""\n    assert 2 + 2 == 4\n',
    })
    # Read the mutated module before applying the generated-input predicate.
    text = (root / "tests" / "property" / "test_examples.py").read_text(encoding="utf-8")
    # Require the negative subject to remain free of generation evidence.
    assert not _GENERATED.search(text)
