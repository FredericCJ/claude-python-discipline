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

if TYPE_CHECKING:
    from pathlib import Path

## Class names that encode a scenario instead of taking one. The shape `TEST-009`
## refuses, matched on what such a class is invariably called.
BESPOKE_FAULT = re.compile(r"(That|Which|When)(Fails|Raises|Errors|Breaks)", re.IGNORECASE)

## What a fault schedule looks like: a frozen value carrying which calls fail.
SCHEDULE_HINTS: Final[tuple[str, ...]] = ("schedule", "faults", "faultplan")

## Modules under `ports/` that publish no port.
NOT_A_PORT: Final[frozenset[str]] = frozenset({"errors"})


def classes_in(path: Path) -> list[ast.ClassDef]:
    """Every class a module defines.

    @param path the module to read
    @return the class definitions found
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]


def is_frozen_value(node: ast.ClassDef) -> bool:
    """Whether a class is a frozen dataclass.

    @param node the class definition
    @return True when a `dataclass` decorator sets `frozen=True`
    """
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        name = getattr(decorator.func, "id", getattr(decorator.func, "attr", ""))
        if name != "dataclass":
            continue
        for keyword in decorator.keywords:
            if keyword.arg == "frozen" and getattr(keyword.value, "value", False):
                return True
    return False


# ------------------------------------------------------------------- TEST-009


@decides("TEST-009")
def test_fault_schedules_are_data() -> None:
    """TEST-009: a failure mode is a value, not a subclass.

    Two halves: a schedule type exists and is a frozen value, and no class in the
    tree encodes a scenario in its own name.
    """
    root = reference_root()
    package = package_root(root)

    schedules = [
        node
        for module in modules_in(package / "adapters")
        if any(hint in module.stem for hint in SCHEDULE_HINTS)
        for node in classes_in(module)
        if is_frozen_value(node)
    ]
    assert schedules, (
        "no fault schedule type found under adapters/. Without one, every fault "
        "scenario becomes a class, and the interesting part of a fault test "
        "lives in a name nothing can enumerate."
    )

    bespoke = [
        node.name
        for module in sorted(package.rglob("*.py"))
        for node in classes_in(module)
        if BESPOKE_FAULT.search(node.name)
    ]
    assert not bespoke, f"scenario encoded in a class name: {', '.join(bespoke)}"


def test_a_bespoke_fault_class_is_caught(tmp_path: Path) -> None:
    """The negative case: the shape the rule exists to refuse.

    @param tmp_path the fixture directory
    """
    root = broken_copy(tmp_path, write={
        "src/refpkg/adapters/clock/bespoke.py":
            '"""A scenario as a class."""\n\n\nclass ClockThatFailsOnce:\n'
            '    """Fails the first time."""\n',
    })
    names = [n.name for n in classes_in(
        package_root(root) / "adapters" / "clock" / "bespoke.py")]
    assert any(BESPOKE_FAULT.search(n) for n in names)


# ------------------------------------------------------- DEP-003 / TEST-010


@decides("TEST-010")
def test_fault_catalogue() -> None:
    """DEP-003, TEST-010: every port has a faulty adapter and a fault test.

    An adapter owns its dependency's failure modes, which means somebody has to
    have written them down. The faulty adapter *is* that catalogue, and the fault
    layer is where it is shown to be more than a list.
    """
    root = reference_root()
    package = package_root(root)
    ports = [p.stem for p in modules_in(package / "ports") if p.stem not in NOT_A_PORT]
    assert ports, "no ports found; this test would pass vacuously"

    fault_text = "\n".join(
        module.read_text(encoding="utf-8")
        for module in sorted((root / "tests" / "fault").rglob("test_*.py"))
    )
    for port in ports:
        faulty = package / "adapters" / port / "faulty.py"
        assert faulty.is_file(), f"port {port} has no faulty adapter to catalogue"
        assert port in fault_text.lower(), (
            f"port {port} has a faulty adapter that no fault test exercises. A "
            f"catalogue nobody reads from is a list, not coverage."
        )


def test_an_uncovered_port_is_caught(tmp_path: Path) -> None:
    """The negative case: a faulty adapter no fault test ever drives.

    @param tmp_path the fixture directory
    """
    root = broken_copy(tmp_path, drop=["tests/fault/test_containment.py"])
    fault_text = "\n".join(
        m.read_text(encoding="utf-8")
        for m in sorted((root / "tests" / "fault").rglob("test_*.py"))
    )
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
    root = reference_root()
    modules = sorted((root / "tests" / "fault").rglob("test_*.py"))
    assert modules, "the fault layer is empty"

    text = "\n".join(m.read_text(encoding="utf-8") for m in modules).lower()
    for evidence, why in (
        ("__cause__", "the cause chain is what proves the origin survived"),
        ("layer", "containment is a claim about which layer owns the failure"),
    ):
        assert evidence in text, (
            f"no fault test mentions {evidence}: {why}"
        )


def test_a_fault_layer_asserting_nothing_about_containment_is_caught(
    tmp_path: Path,
) -> None:
    """The negative case: a fault test that only asserts something raised.

    @param tmp_path the fixture directory
    """
    root = broken_copy(tmp_path, write={
        "tests/fault/test_containment.py":
            '"""Tests. Oracle: contract."""\n\nimport pytest\n\n\n'
            'def test_it_raises():\n    """Something broke."""\n'
            '    with pytest.raises(ValueError):\n        raise ValueError\n',
    })
    text = "\n".join(
        m.read_text(encoding="utf-8")
        for m in sorted((root / "tests" / "fault").rglob("test_*.py"))
    ).lower()
    assert "__cause__" not in text
