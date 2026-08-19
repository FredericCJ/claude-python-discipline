"""The published surface is a contract: structured, versioned, and self-describing.

**Oracle: contract.** `law/API` held against a project tree, and against this
repository's own release path where the rule is about delivery.

* `API-001`, `API-002`, `FLOW-001` -- a contract states more than a signature, and
  the implementation is not the contract
* `API-005`, `API-006`, `API-008` -- structured output is primary, the human form
  renders the same object, and the surface describes itself
* `API-007` -- exit status is part of the contract
* `API-009` -- automation gets no relaxed validation
* `API-010`, `API-013` -- every published payload carries a schema version
* `API-012` -- a format change ships with a migration and its test
* `API-015` -- the delivered artifact is what gets tested

`API-002` is the sharpest of these and the easiest to check: a `Protocol` method
with a *body* has stopped being a contract and become an implementation nobody
can substitute against.

    pytest enforce/fitness/test_api.py
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

import pytest

from fixtures import broken_copy, package_root, reference_root

## The repository root, three levels up from this file.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent.parent

## Names an entry point goes by.
ENTRY_POINTS: Final[frozenset[str]] = frozenset({"cli", "main", "__main__"})

## A named exit-status constant. `API-007` makes the status part of the contract,
## and a literal `return 2` names nothing a caller can depend on.
_EXIT_CONSTANT = re.compile(r"^EXIT_[A-Z_]+\s*[:=]", re.MULTILINE)

## The field that lets a consumer tell whether it understands what it parsed.
_SCHEMA_VERSION = re.compile(r"schema_version", re.IGNORECASE)

## A branch on whether the caller is a machine. `API-009` refuses this: two
## validation paths mean the stricter one is the one nobody exercises.
_AGENT_BRANCH = re.compile(r"\b(is_agent|is_machine|for_agent|automated|non_?interactive"
                           r"|AGENT_MODE|CI_MODE)\b")


def module_text(package: Path, *names: str) -> str:
    """The concatenated source of the named modules under a package.

    @param package the package directory
    @param names module stems to gather, at any depth
    @return their contents joined, or the empty string when none exist
    """
    wanted = set(names)
    return "\n".join(
        m.read_text(encoding="utf-8")
        for m in sorted(package.rglob("*.py"))
        if m.stem in wanted and "__pycache__" not in m.parts
    )


def protocol_methods(package: Path) -> list[tuple[str, ast.FunctionDef]]:
    """Every method defined on a `Protocol` in the package.

    @param package the package directory
    @return each method paired with the class name that owns it
    """
    found: list[tuple[str, ast.FunctionDef]] = []
    for module in sorted((package / "ports").glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(getattr(b, "id", getattr(b, "attr", "")) == "Protocol"
                       for b in node.bases):
                continue
            found += [(node.name, s) for s in node.body
                      if isinstance(s, ast.FunctionDef)]
    return found


# ------------------------------------------- API-001 / API-002 / FLOW-001


def test_contract_documented() -> None:
    """API-001, API-002, FLOW-001: the contract exists, and is not the code.

    A `Protocol` method may hold a docstring and an ellipsis. Anything more is an
    implementation living in the place reserved for the promise, and every
    adapter then inherits behaviour the contract never described.
    """
    package = package_root(reference_root())
    methods = protocol_methods(package)
    assert methods, "no Protocol methods found; this test would pass vacuously"

    for owner, method in methods:
        assert ast.get_docstring(method), (
            f"{owner}.{method.name} is part of a contract and states nothing"
        )
        substantive = [
            s for s in method.body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
            and not isinstance(s, ast.Pass)
        ]
        assert not substantive, (
            f"{owner}.{method.name} has an implementation in its contract. A "
            f"Protocol method with a body is behaviour every adapter inherits "
            f"and the contract never described."
        )


def test_a_protocol_carrying_an_implementation_is_caught(tmp_path: Path) -> None:
    """The negative case for `API-002`.

    @param tmp_path the fixture directory
    """
    contract = (
        '        @throws ClockUnavailable when no reading can be taken\n        """\n'
    )
    root = broken_copy(tmp_path, replace=[
        ("src/refpkg/ports/clock.py", contract + "        ...",
         contract + "        return Instant(0)"),
    ])
    bodies = [m for _, m in protocol_methods(package_root(root))]
    assert any(
        any(isinstance(s, ast.Return) for s in method.body) for method in bodies
    )


# ------------------------------------------- API-005 / API-006 / API-008


def test_structured_output() -> None:
    """API-005, API-006, API-008: one result object, two renderings, self-describing.

    The property that matters is that the human form *formats* the machine form.
    A separately computed human rendering is a second implementation of the
    answer, free to disagree with the one a script parses.
    """
    package = package_root(reference_root())
    text = module_text(package, *ENTRY_POINTS)
    assert text, "no entry point found under the package"

    assert "json" in text, "the entry point emits no machine-readable form"
    assert _SCHEMA_VERSION.search(text), (
        "the payload carries no schema version, so a consumer cannot tell "
        "whether it understands what it just parsed"
    )

    tree = ast.parse(text)
    renderers = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name in {"render", "format", "emit"}
    ]
    assert renderers, "no rendering function; the two forms cannot share an object"
    for renderer in renderers:
        arguments = {a.arg for a in (*renderer.args.args, *renderer.args.kwonlyargs)}
        assert arguments & {"payload", "result", "record", "data"}, (
            f"{renderer.name}() does not take the result object, so the human "
            f"form is computed rather than rendered"
        )


# ------------------------------------------------------------------- API-007


def test_exit_codes() -> None:
    """API-007: exit status is named, not a literal at the point of return.

    A caller scripting against `1` and `2` is depending on something nobody wrote
    down. Naming them makes the status a published surface that a change has to
    be deliberate about.
    """
    package = package_root(reference_root())
    text = module_text(package, *ENTRY_POINTS)
    constants = _EXIT_CONSTANT.findall(text)
    assert len(constants) >= 2, (
        f"only {len(constants)} named exit constant(s). Success and failure are "
        f"different contracts, and a script cannot tell them apart from literals."
    )


# ------------------------------------------------------------------- API-009


def test_agent_parity() -> None:
    """API-009: there is one validation path, whoever is calling.

    Two paths mean the stricter one is the one nobody exercises, and the relaxed
    one is the one automation takes -- at volume, unattended.
    """
    package = package_root(reference_root())
    for module in sorted(package.rglob("*.py")):
        if "__pycache__" in module.parts:
            continue
        found = _AGENT_BRANCH.search(module.read_text(encoding="utf-8"))
        assert found is None, (
            f"{module.name} branches on {found.group(0)!r}. A dispatch at any "
            f"tier is validated identically by the core."
        )


# ------------------------------------------------------- API-010 / API-013


def test_schema_versioned() -> None:
    """API-010, API-013: the payload says which version it is.

    `API-013` is the half people skip: compatibility is not inherited from the
    fact that an old parser happens not to crash on new output.
    """
    package = package_root(reference_root())
    text = module_text(package, *ENTRY_POINTS)
    assert _SCHEMA_VERSION.search(text), "no schema version in the published payload"

    # Both assignment forms, because an annotated constant -- which is what the
    # discipline's own typing rules push an author towards -- is an `AnnAssign`
    # and not an `Assign`. Checking only the latter reported the reference's own
    # `SCHEMA_VERSION: str = "1"` as undeclared.
    tree = ast.parse(text)
    declared = [
        n for n in ast.walk(tree)
        if (isinstance(n, ast.Assign)
            and any(getattr(t, "id", "").upper() == "SCHEMA_VERSION" for t in n.targets))
        or (isinstance(n, ast.AnnAssign)
            and getattr(n.target, "id", "").upper() == "SCHEMA_VERSION")
    ]
    assert declared, "the schema version is emitted but never declared as a constant"


# ------------------------------------------------------------------- API-012


def test_migrations() -> None:
    """API-012: a format past its first version ships a migration and its test.

    Conditional, and vacuous for a format still at version 1 -- which is correct:
    there is nothing to migrate from. The reference is at 1 and says so.
    """
    package = package_root(reference_root())
    text = module_text(package, *ENTRY_POINTS)
    found = re.search(r"SCHEMA_VERSION\s*[:=].*?[\"'](\d+)[\"']", text, re.DOTALL)
    assert found, "no schema version declared"

    if int(found.group(1)) == 1:
        return
    root = reference_root()
    migrations = list(root.rglob("*migrat*"))
    assert migrations, (
        f"the payload is at version {found.group(1)} and no migration exists. A "
        f"format change without one strands every consumer on the old version."
    )


# ------------------------------------------------------------------- API-015


def test_delivered_boundary() -> None:
    """API-015: what ships is what the installer writes, not a hand-made copy.

    Checked against this repository's own release path, because that is where the
    rule has a subject. `release.py` builds the archive by running `vendor.py`
    against a scratch tree, so a file the installer would not write cannot reach
    an adopter because somebody dragged a folder.
    """
    release = REPO_ROOT / "tools" / "release.py"
    if not release.is_file():
        pytest.skip("this tree publishes no archive")

    text = release.read_text(encoding="utf-8")
    assert "vendor.install" in text or "vendor" in text, (
        "the release does not build through the installer, so what ships is not "
        "what an adopter would get from installing"
    )
    assert "REQUIRED_MEMBERS" in text, (
        "the release asserts nothing about what the archive must contain"
    )


def test_the_release_runs_the_gate() -> None:
    """API-015, the other half: the delivered artifact is cut from a passing tree.

    An archive built from a tree whose tests fail is a delivered artifact nobody
    tested, whatever the suite said the day before.
    """
    release = REPO_ROOT / "tools" / "release.py"
    if not release.is_file():
        pytest.skip("this tree publishes no archive")
    text = release.read_text(encoding="utf-8")
    assert "gate.GATE" in text or "run_gate" in text, (
        "release.py does not run the gate before staging; an archive can be cut "
        "from a tree that fails it"
    )
