"""Every port is a contract, has three adapters, and is tested through one suite.

**Oracle: contract.** Each assertion restates a clause of `law/ARCH` and holds it
against a project tree, so these are the four rules that carry the thesis:

* `ARCH-007`, `TYPE-009` -- a port is a `Protocol` with a published contract
* `ARCH-008` -- real, fake and faulty, unconditionally
* `ARCH-009`, `TEST-005`, `TEST-006` -- one suite against all three
* `ARCH-010` -- a port earns its place from a stated justification

Every test runs against the conformant reference for its positive case and
against a `broken_copy` for its negative, so none of them can pass vacuously
(`FLOW-007`).

**The convention these rest on**, stated once here because a fitness test cannot
infer it: a port at `ports/<name>.py` has its adapters at
`adapters/<name>/{real,fake,faulty}.py`, and its contract suite at
`tests/contract/test_<name>_contract.py`. A project laying its ports out
otherwise is not thereby wrong -- but it needs its own fitness tests, because
these read the filesystem and nothing else.

    pytest enforce/fitness/test_ports.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Final

import pytest

from decides import decides
from fixtures import broken_copy, modules_in, package_root, reference_root

if TYPE_CHECKING:
    from pathlib import Path

## Modules under `ports/` that publish no port. `errors` declares the failure
## modes the ports share, which `ARCH-007` requires a contract to state.
NOT_A_PORT: Final[frozenset[str]] = frozenset({"errors"})

## The three implementations `ARCH-008` requires of every port, unconditionally.
TRIAD: Final[tuple[str, ...]] = ("real", "fake", "faulty")

## The eight justifications `ARCH-010` closes the list at. A port naming none of
## them has not earned its place, and "port" degrades into wrapping the standard
## library.
JUSTIFICATIONS: Final[tuple[str, ...]] = (
    "replacing the implementation",
    "testing the core against a fake",
    "behavioural contract",
    "controlling a specific effect",
    "fault injection",
    "observing an interaction",
    "isolating the core",
    "more than one real adapter",
)

## What a contract must state, per `ARCH-007`. Matched loosely on the noun, since
## a contract is prose and the rule is about what it covers rather than its shape.
CONTRACT_TOPICS: Final[tuple[str, ...]] = ("contract", "error", "raise")


def ports_of(root: Path) -> list[Path]:
    """Every port module in a project.

    @param root the project root
    @return the modules under `ports/` that publish a port
    """
    return [p for p in modules_in(package_root(root) / "ports")
            if p.stem not in NOT_A_PORT]


def protocols_in(path: Path) -> list[ast.ClassDef]:
    """Every `Protocol` class a module defines.

    @param path the module to read
    @return the class definitions deriving from `Protocol`
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(getattr(b, "id", getattr(b, "attr", "")) == "Protocol" for b in node.bases)
    ]


# --------------------------------------------------------- ARCH-007 / TYPE-009


@decides("ARCH-007", "TYPE-009")
def test_every_port_is_a_protocol() -> None:
    """ARCH-007, TYPE-009: a port is a structural contract, with its terms stated.

    Structural rather than nominal is what lets an adapter satisfy a port without
    importing anything from the core, which is what keeps the dependency pointing
    inward at all.
    """
    root = reference_root()
    ports = ports_of(root)
    assert ports, "the reference declares no ports; this test would pass vacuously"

    for port in ports:
        protocols = protocols_in(port)
        assert protocols, f"{port.name} is under ports/ and defines no Protocol"
        docstring = ast.get_docstring(
            ast.parse(port.read_text(encoding="utf-8"))) or ""
        lowered = docstring.lower()
        assert any(topic in lowered for topic in CONTRACT_TOPICS), (
            f"{port.name} publishes a Protocol with no stated contract. Without "
            f"one there is nothing for a fake to be faithful to."
        )


def test_a_port_without_a_protocol_is_caught(tmp_path: Path) -> None:
    """The negative case: a port module that publishes an ordinary class.

    @param tmp_path the fixture directory
    """
    root = broken_copy(tmp_path, write={
        "src/refpkg/ports/clock.py": '"""A port with no contract."""\n\n\nclass Clock:\n'
                                     '    """Not a Protocol."""\n',
    })
    port = package_root(root) / "ports" / "clock.py"
    assert protocols_in(port) == []


# ------------------------------------------------------------------- ARCH-008


@decides("ARCH-008")
def test_port_triad() -> None:
    """ARCH-008: real, fake and faulty for every port, with no qualifier.

    The port judged to have no failure mode is the one whose failure is
    discovered in production, which is why this rule admits no exception -- and
    why a clock, which looks unfailable, has a faulty adapter in the reference.
    """
    root = reference_root()
    package = package_root(root)
    for port in ports_of(root):
        family = package / "adapters" / port.stem
        assert family.is_dir(), f"port {port.stem} has no adapter package"
        present = {p.stem for p in modules_in(family)}
        missing = [kind for kind in TRIAD if kind not in present]
        assert not missing, (
            f"port {port.stem} is missing its {', '.join(missing)} adapter(s). "
            f"Swappability is proved by three implementations, not asserted by one."
        )


def test_a_missing_faulty_adapter_is_caught(tmp_path: Path) -> None:
    """The negative case, and the one an unconditional rule exists to catch.

    @param tmp_path the fixture directory
    """
    root = broken_copy(tmp_path, drop=["src/refpkg/adapters/clock/faulty.py"])
    present = {p.stem for p in modules_in(package_root(root) / "adapters" / "clock")}
    assert "faulty" not in present


# ------------------------------------------- ARCH-009 / TEST-005 / TEST-006


@decides("ARCH-009", "TEST-005", "TEST-006")
def test_contract_suite_per_adapter() -> None:
    """ARCH-009, TEST-005, TEST-006: one suite, run against all three adapters.

    A fake that can drift from its real counterpart without a test failing is
    worthless, and every unit test standing on that fake is worth as little. The
    shared suite is what makes the fake's fidelity a checked property rather than
    an intention.
    """
    root = reference_root()
    for port in ports_of(root):
        suite = root / "tests" / "contract" / f"test_{port.stem}_contract.py"
        assert suite.is_file(), (
            f"port {port.stem} has no contract suite at {suite.name}"
        )
        text = suite.read_text(encoding="utf-8")
        named = [kind for kind in TRIAD if kind in text]
        assert len(named) == len(TRIAD), (
            f"{suite.name} does not exercise all three adapters; it names "
            f"{', '.join(named) or 'none'}. The faulty adapter runs in healthy "
            f"mode, which is what stops it being a second implementation nobody "
            f"holds to the contract."
        )


def test_a_suite_covering_one_adapter_is_caught(tmp_path: Path) -> None:
    """The negative case: a suite that tests only the fake.

    @param tmp_path the fixture directory
    """
    root = broken_copy(tmp_path, write={
        "tests/contract/test_clock_contract.py":
            '"""Tests. Oracle: contract."""\n\n\ndef test_it():\n'
            '    """Only the fake."""\n    assert True\n',
    })
    text = (root / "tests" / "contract" / "test_clock_contract.py").read_text(
        encoding="utf-8")
    assert not all(kind in text for kind in TRIAD)


# ------------------------------------------------------------------- ARCH-010


@decides("ARCH-010")
def test_port_justification() -> None:
    """ARCH-010: a port names which of the eight reasons it claims.

    Without a closed list, "port" degrades into wrapping standard-library calls
    and the boundary stops meaning anything. The list is closed so that a port
    whose justification is "it seemed tidier" cannot be written down.
    """
    root = reference_root()
    for port in ports_of(root):
        docstring = ast.get_docstring(
            ast.parse(port.read_text(encoding="utf-8"))) or ""
        lowered = docstring.lower()
        claimed = [j for j in JUSTIFICATIONS if j in lowered]
        assert claimed, (
            f"{port.name} claims none of the eight justifications. A port that "
            f"cannot say why it exists is an abstraction added by habit, and "
            f"each one lengthens every trace."
        )


def test_a_port_with_no_justification_is_caught(tmp_path: Path) -> None:
    """The negative case.

    @param tmp_path the fixture directory
    """
    root = broken_copy(tmp_path, write={
        "src/refpkg/ports/clock.py":
            '"""A port that says nothing about why it exists."""\n\n'
            'from typing import Protocol\n\n\nclass Clock(Protocol):\n'
            '    """A clock."""\n',
    })
    port = package_root(root) / "ports" / "clock.py"
    docstring = (ast.get_docstring(ast.parse(port.read_text(encoding="utf-8"))) or "").lower()
    assert not any(j in docstring for j in JUSTIFICATIONS)


def test_the_reference_is_present() -> None:
    """Everything above is vacuous without it, so its absence is its own failure."""
    with pytest.raises(FileNotFoundError):
        package_root(reference_root().parent)
