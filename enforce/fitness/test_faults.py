"""Faults are data, every port has a catalogue, and containment is tested.

**Oracle: contract.** `law/TEST` and `law/ERR` held against a project tree.

* `TEST-009` -- fault injection is data, not a class per scenario
* `DEP-003`, `TEST-010` -- an adapter owns its dependency's failure modes, and
  the catalogue is covered per port
* `ERR-016`, `TEST-011` -- propagation and containment are tested, not assumed

`TEST-009` is the one that looks like style and is not. A bespoke
`ClockThatFailsOnce` puts the interesting part of a fault test in a class name,
where it cannot be enumerated, parameterised, printed in a failure message or
generated. A schedule is a value, so all four become possible at once.

    pytest enforce/fitness/test_faults.py
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, Final

from decides import decides
from fixtures import broken_copy, modules_in, package_root, reference_root

# Import path typing only while static analyzers evaluate fixture contracts.
if TYPE_CHECKING:
    from pathlib import Path

## Class names that encode a scenario instead of taking one. The shape `TEST-009`
## refuses, matched on what such a class is invariably called.
BESPOKE_FAULT = re.compile(r"(That|Which|When)(Fails|Raises|Errors|Breaks)", re.IGNORECASE)

## Fault-schedule module-name hint elements in stable discovery order.
SCHEDULE_HINTS: Final[tuple[str, ...]] = ("schedule", "faults", "faultplan")

## Unordered port-module-stem elements that publish no behavioral port.
NOT_A_PORT: Final[frozenset[str]] = frozenset({"errors"})


def classes_in(path: Path) -> list[ast.ClassDef]:
    """Every class a module defines.

    @param path the module to read
    @return class-definition elements in AST traversal order
    """
    # Parse declarations without importing or executing the inspected module.
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    # Return class-definition nodes in deterministic syntax-tree traversal order.
    return [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]


def is_frozen_value(node: ast.ClassDef) -> bool:
    """Whether a class is a frozen dataclass.

    @param node the class definition
    @return true when a dataclass decorator sets `frozen=True`; false otherwise
    """
    # Inspect decorator expressions in their lexical application order.
    for decorator in node.decorator_list:
        # Ignore bare decorators that cannot carry the `frozen` option.
        if not isinstance(decorator, ast.Call):
            # Continue with the next class decorator.
            continue
        # Normalize either name or attribute call forms to the decorator identity.
        name = getattr(decorator.func, "id", getattr(decorator.func, "attr", ""))
        # Restrict keyword inspection to dataclass configuration calls.
        if name != "dataclass":
            # Continue with the next decorator when it defines unrelated behavior.
            continue
        # Inspect dataclass keywords in lexical argument order.
        for keyword in decorator.keywords:
            # Recognize only an explicitly truthy frozen configuration.
            if keyword.arg == "frozen" and getattr(keyword.value, "value", False):
                # Report the class as an immutable schedule value immediately.
                return True
    # Report false after no decorator establishes frozen dataclass semantics.
    return False


# ------------------------------------------------------------------- TEST-009


@decides("TEST-009")
def test_fault_schedules_are_data() -> None:
    """TEST-009: a failure mode is a value, not a subclass.

    Two halves: a schedule type exists and is a frozen value, and no class in the
    tree encodes a scenario in its own name.
    """
    # Resolve the conformant package before inventorying schedule and scenario classes.
    root = reference_root()
    package = package_root(root)

    # Retain frozen schedule-class definition elements in module and AST traversal order.
    schedules = [
        node
        for module in modules_in(package / "adapters")
        if any(hint in module.stem for hint in SCHEDULE_HINTS)
        for node in classes_in(module)
        if is_frozen_value(node)
    ]
    # Reject a fault system with no enumerable immutable schedule value.
    assert schedules, (
        "no fault schedule type found under adapters/. Without one, every fault "
        "scenario becomes a class, and the interesting part of a fault test "
        "lives in a name nothing can enumerate."
    )

    # Retain bespoke scenario class-name elements in sorted module and AST order.
    bespoke = [
        node.name
        for module in sorted(package.rglob("*.py"))
        for node in classes_in(module)
        if BESPOKE_FAULT.search(node.name)
    ]
    # Reject fault scenarios encoded in class vocabulary instead of data values.
    assert not bespoke, f"scenario encoded in a class name: {', '.join(bespoke)}"


def test_a_bespoke_fault_class_is_caught(tmp_path: Path) -> None:
    """The negative case: the shape the rule exists to refuse.

    @param tmp_path the fixture directory

    @par Effects
    Creates an isolated project containing one scenario-encoded adapter class.
    """
    # Build a negative fixture whose class name encodes a one-time failure schedule.
    root = broken_copy(tmp_path, write={
        "src/refpkg/adapters/clock/bespoke.py":
            '"""A scenario as a class."""\n\n\nclass ClockThatFailsOnce:\n'
            '    """Fails the first time."""\n',
    })
    # Preserve class-name string elements in AST traversal order for predicate testing.
    names = [n.name for n in classes_in(
        package_root(root) / "adapters" / "clock" / "bespoke.py")]
    # Require the injected bespoke class to exercise the naming prohibition.
    assert any(BESPOKE_FAULT.search(n) for n in names)


# ------------------------------------------------------- DEP-003 / TEST-010


@decides("TEST-010")
def test_fault_catalogue() -> None:
    """DEP-003, TEST-010: every port has a faulty adapter and a fault test.

    An adapter owns its dependency's failure modes, which means somebody has to
    have written them down. The faulty adapter *is* that catalogue, and the fault
    layer is where it is shown to be more than a list.
    """
    # Resolve the conformant package and list published port-name elements in filename order.
    root = reference_root()
    package = package_root(root)
    ports = [p.stem for p in modules_in(package / "ports") if p.stem not in NOT_A_PORT]
    # Reject a vacuous package with no behavioral ports to catalogue.
    assert ports, "no ports found; this test would pass vacuously"

    # Combine fault-test source elements in sorted path order for port-use evidence.
    fault_text = "\n".join(
        module.read_text(encoding="utf-8")
        for module in sorted((root / "tests" / "fault").rglob("test_*.py"))
    )
    # Verify each port in deterministic module-name order.
    for port in ports:
        # Resolve the conventional faulty-adapter subject owned by the current port.
        faulty = package / "adapters" / port / "faulty.py"
        # Require both the catalog adapter and evidence that a fault test exercises it.
        assert faulty.is_file(), f"port {port} has no faulty adapter to catalogue"
        assert port in fault_text.lower(), (
            f"port {port} has a faulty adapter that no fault test exercises. A "
            f"catalogue nobody reads from is a list, not coverage."
        )


def test_an_uncovered_port_is_caught(tmp_path: Path) -> None:
    """The negative case: a faulty adapter no fault test ever drives.

    @param tmp_path the fixture directory

    @par Effects
    Creates an isolated project with the only containment test removed.
    """
    # Remove the fault test that exercises the clock catalogue.
    root = broken_copy(tmp_path, drop=["tests/fault/test_containment.py"])
    # Combine remaining fault-source elements in sorted path order.
    fault_text = "\n".join(
        m.read_text(encoding="utf-8")
        for m in sorted((root / "tests" / "fault").rglob("test_*.py"))
    )
    # Require the negative subject to contain no residual clock coverage evidence.
    assert "clock" not in fault_text.lower()


# ------------------------------------------------------- ERR-016 / TEST-011


@decides("ERR-016", "TEST-011")
def test_fault_containment() -> None:
    """ERR-016, TEST-011: containment is demonstrated, not assumed.

    The fault layer must assert about *where* a failure stopped and what it
    became -- which layer's family it surfaced as, and what survived in the
    cause chain. A fault test that only asserts "it raised" has shown that
    something broke, not that the break was contained.
    """
    # Resolve and inventory fault-test module paths in deterministic order.
    root = reference_root()
    modules = sorted((root / "tests" / "fault").rglob("test_*.py"))
    # Reject an empty fault layer before inspecting containment evidence.
    assert modules, "the fault layer is empty"

    # Combine module-source elements in sorted path order and normalize case.
    text = "\n".join(m.read_text(encoding="utf-8") for m in modules).lower()
    # Verify each evidence token and its diagnostic reason in fixed review order.
    for evidence, why in (
        ("__cause__", "the cause chain is what proves the origin survived"),
        ("layer", "containment is a claim about which layer owns the failure"),
    ):
        # Require both origin preservation and explicit layer ownership evidence.
        assert evidence in text, (
            f"no fault test mentions {evidence}: {why}"
        )


def test_a_fault_layer_asserting_nothing_about_containment_is_caught(
    tmp_path: Path,
) -> None:
    """The negative case: a fault test that only asserts something raised.

    @param tmp_path the fixture directory

    @par Effects
    Creates an isolated project whose fault test asserts only that an exception occurs.
    """
    # Replace containment coverage with a test carrying no origin or layer assertions.
    root = broken_copy(tmp_path, write={
        "tests/fault/test_containment.py":
            '"""Tests. Oracle: contract."""\n\nimport pytest\n\n\n'
            'def test_it_raises():\n    """Something broke."""\n'
            '    with pytest.raises(ValueError):\n        raise ValueError\n',
    })
    # Combine mutated fault-source elements in sorted path order and normalize case.
    text = "\n".join(
        m.read_text(encoding="utf-8")
        for m in sorted((root / "tests" / "fault").rglob("test_*.py"))
    ).lower()
    # Require the negative subject to omit explicit cause-chain evidence.
    assert "__cause__" not in text
