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

from decides import decides
from fixtures import broken_copy, package_root, reference_root

## The repository root, three levels up from this file.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent.parent

## Unordered module-stem string elements recognized as published entry points.
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
    @param names module-stem string elements; caller order is insignificant because
        matching source paths are sorted before concatenation
    @return their contents joined, or the empty string when none exist
    """
    # Collapse requested module-stem elements to an unordered membership set.
    wanted = set(names)
    # Join matching source-text elements in deterministic module-path order.
    return "\n".join(
        m.read_text(encoding="utf-8")
        for m in sorted(package.rglob("*.py"))
        if m.stem in wanted and "__pycache__" not in m.parts
    )


def protocol_methods(package: Path) -> list[tuple[str, ast.FunctionDef]]:
    """Every method defined on a `Protocol` in the package.

    @param package the package directory
    @return owner-name and method-definition pair elements in sorted module/AST order
    """
    # Accumulate owner-and-method pair elements in module and syntax traversal order.
    found: list[tuple[str, ast.FunctionDef]] = []
    # Inspect public port modules in deterministic filename order.
    for module in sorted((package / "ports").glob("*.py")):
        # Parse protocol declarations without importing or executing port source.
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        # Visit every node because protocol classes may be nested by generated source.
        for node in ast.walk(tree):
            # Discard non-class syntax before examining base identities.
            if not isinstance(node, ast.ClassDef):
                # Continue the syntax traversal with the next node.
                continue
            # Select only classes that directly name the Protocol base.
            if not any(getattr(b, "id", getattr(b, "attr", "")) == "Protocol"
                       for b in node.bases):
                # Continue with the next class when it is an implementation type.
                continue
            # Append each synchronous protocol method in lexical class-body order.
            found += [(node.name, s) for s in node.body
                      if isinstance(s, ast.FunctionDef)]
    # Return the complete ordered protocol method census.
    return found


# ------------------------------------------- API-001 / API-002 / FLOW-001


@decides("API-001", "API-002")
def test_contract_documented() -> None:
    """API-001, API-002: the contract states its terms, and is not the code.

    A `Protocol` method may hold a docstring and an ellipsis. Anything more is an
    implementation living in the place reserved for the promise, and every
    adapter then inherits behaviour the contract never described.

    **`API-001` is not satisfied by the presence of a docstring.** Until v3.1 this
    test asserted `get_docstring(method)` was truthy and claimed the rule, so a
    method documented as `"x"` passed while stating none of the seven things the
    rule requires. That is the same defect -- existence standing in for agreement
    -- that `@decides` exists to stop, and it was found by asking what this
    function could actually reject.

    What is checked here is the mechanical subset: every argument named, and the
    result stated unless the signature returns None. Ordering, idempotency and
    concurrency are canonical operation terms in `architecture.json`, joined to
    term evidence by `checks.contract_conformance`.
    """
    # Resolve the conformant package and inventory its protocol method pairs.
    package = package_root(reference_root())
    methods = protocol_methods(package)
    # Reject a vacuous contract surface before checking documentation and bodies.
    assert methods, "no Protocol methods found; this test would pass vacuously"

    # Inspect each owner-and-method pair in deterministic source declaration order.
    for owner, method in methods:
        # Recover the structured contract text attached to the protocol operation.
        documentation = ast.get_docstring(method)
        # Require every published operation to state a non-empty contract.
        assert documentation, (
            f"{owner}.{method.name} is part of a contract and states nothing"
        )
        # Check positional then keyword-only argument definitions in signature order.
        for argument in (*method.args.args, *method.args.kwonlyargs):
            # Exclude receiver parameters whose meaning is owned by method binding.
            if argument.arg in {"self", "cls"}:
                # Continue with the next caller-controlled operation parameter.
                continue
            # Require the contract to explain each caller-controlled named argument.
            assert f"@param {argument.arg}" in documentation, (
                f"{owner}.{method.name} takes {argument.arg!r} and the contract "
                f"never says what it is. A signature names an argument; a "
                f"contract says what a caller may pass and what happens if they "
                f"do not."
            )
        # `-> None` is an `ast.Constant` holding None, not a `Name` called
        # "None". Reading it as a Name reported every void method as an
        # undescribed result, which is how this assertion first ran.
        annotation = method.returns
        void = isinstance(annotation, ast.Constant) and annotation.value is None
        # Require result semantics for every operation whose signature returns a value.
        if not void:
            # Reject a value-returning protocol method with no structured result contract.
            assert "@return" in documentation, (
                f"{owner}.{method.name} returns something the contract does not "
                f"describe, so every adapter is free to return a different one."
            )
        # Retain executable statement elements in lexical order after docs and pass markers.
        substantive = [
            s for s in method.body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
            and not isinstance(s, ast.Pass)
        ]
        # Reject behavior embedded in the substitutable protocol declaration.
        assert not substantive, (
            f"{owner}.{method.name} has an implementation in its contract. A "
            f"Protocol method with a body is behaviour every adapter inherits "
            f"and the contract never described."
        )


def test_a_contract_that_only_has_a_docstring_is_caught(tmp_path: Path) -> None:
    """The negative case for `API-001`, and the reason it was rewritten.

    The damage here is the one the old assertion could not see: the docstring is
    present, non-empty and useless. `TEST-015` asks every mechanism to be shown
    failing, and a mechanism whose companion only proves it catches an *absent*
    docstring has not been shown to check what the rule says.

    @param tmp_path the fixture directory

    @par Effects
    Creates an isolated project whose clock contract keeps only a hollow summary.
    """
    # Preserve the exact useful contract text used as the replacement anchor.
    stated = ('        """The current instant.\n\n'
              '        @return the current instant, at or after the epoch\n'
              '        @throws ClockUnavailable when no reading can be taken\n'
              '        """')
    # Replace the structured result contract with a present but useless docstring.
    root = broken_copy(tmp_path, replace=[
        ("src/refpkg/ports/clock.py", stated, '        """The current instant."""'),
    ])
    # Retain owner-and-method pair elements lacking results in source declaration order.
    methods = protocol_methods(package_root(root))
    hollow = [
        (owner, method) for owner, method in methods
        if "@return" not in (ast.get_docstring(method) or "")
    ]
    # Require the negative fixture to exercise semantic incompleteness, not absence.
    assert hollow, "the damage did not land; the contract still states its result"


def test_a_protocol_carrying_an_implementation_is_caught(tmp_path: Path) -> None:
    """The negative case for `API-002`.

    @param tmp_path the fixture directory

    @par Effects
    Creates an isolated project whose clock protocol performs a concrete return.
    """
    # Preserve the end of the clock contract as the executable-body insertion anchor.
    contract = (
        '        @throws ClockUnavailable when no reading can be taken\n        """\n'
    )
    # Replace the ellipsis contract marker with a concrete implementation return.
    root = broken_copy(tmp_path, replace=[
        ("src/refpkg/ports/clock.py", contract + "        ...",
         contract + "        return Instant(0)"),
    ])
    # Preserve method-definition elements in source declaration order for body inspection.
    bodies = [m for _, m in protocol_methods(package_root(root))]
    # Require at least one injected protocol body to contain executable return behavior.
    assert any(
        any(isinstance(s, ast.Return) for s in method.body) for method in bodies
    )


# ------------------------------------------- API-005 / API-006 / API-008


@decides("API-005", "API-006")
def test_structured_output() -> None:
    """API-005, API-006, API-008: one result object, two renderings, self-describing.

    The property that matters is that the human form *formats* the machine form.
    A separately computed human rendering is a second implementation of the
    answer, free to disagree with the one a script parses.
    """
    # Resolve and combine conformant entry-point source in deterministic module order.
    package = package_root(reference_root())
    text = module_text(package, *ENTRY_POINTS)
    # Establish a non-vacuous published boundary before inspecting its renderings.
    assert text, "no entry point found under the package"

    # Require both structured encoding and an explicit consumer-visible schema identity.
    assert "json" in text, "the entry point emits no machine-readable form"
    assert _SCHEMA_VERSION.search(text), (
        "the payload carries no schema version, so a consumer cannot tell "
        "whether it understands what it just parsed"
    )

    # Parse the combined entry-point source to identify candidate renderer definitions.
    tree = ast.parse(text)
    # Retain renderer-definition elements in AST traversal order.
    renderers = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name in {"render", "format", "emit"}
    ]
    # Reject a boundary whose human form cannot share a structured result object.
    assert renderers, "no rendering function; the two forms cannot share an object"
    # Inspect each renderer definition in syntax-tree traversal order.
    for renderer in renderers:
        # Collapse caller-visible parameter-name elements to an unordered membership set.
        arguments = {a.arg for a in (*renderer.args.args, *renderer.args.kwonlyargs)}
        # Require one parameter that semantically carries the already-computed result.
        assert arguments & {"payload", "result", "record", "data"}, (
            f"{renderer.name}() does not take the result object, so the human "
            f"form is computed rather than rendered"
        )


# ------------------------------------------------------------------- API-007


@decides("API-007")
def test_exit_codes() -> None:
    """API-007: exit status is named, not a literal at the point of return.

    A caller scripting against `1` and `2` is depending on something nobody wrote
    down. Naming them makes the status a published surface that a change has to
    be deliberate about.
    """
    # Resolve and combine entry-point source before extracting named exit declarations.
    package = package_root(reference_root())
    text = module_text(package, *ENTRY_POINTS)
    # Preserve exit-constant match elements in textual occurrence order.
    constants = _EXIT_CONSTANT.findall(text)
    # Require distinct named success and failure statuses for automation callers.
    assert len(constants) >= 2, (
        f"only {len(constants)} named exit constant(s). Success and failure are "
        f"different contracts, and a script cannot tell them apart from literals."
    )


# ------------------------------------------------------------------- API-009


@decides("API-009")
def test_agent_parity() -> None:
    """API-009: there is one validation path, whoever is calling.

    Two paths mean the stricter one is the one nobody exercises, and the relaxed
    one is the one automation takes -- at volume, unattended.
    """
    # Resolve the conformant package before scanning all source paths deterministically.
    package = package_root(reference_root())
    # Inspect every Python source module in sorted path order.
    for module in sorted(package.rglob("*.py")):
        # Exclude interpreter cache paths from the authored validation surface.
        if "__pycache__" in module.parts:
            # Advance to the next authored module.
            continue
        # Search for a caller-identity branch in the complete module source.
        found = _AGENT_BRANCH.search(module.read_text(encoding="utf-8"))
        # Reject any relaxed validation path selected by automation identity.
        assert found is None, (
            f"{module.name} branches on {found.group(0)!r}. A dispatch at any "
            f"tier is validated identically by the core."
        )


# ------------------------------------------------------- API-010 / API-013


@decides("API-010")
def test_schema_versioned() -> None:
    """API-010, API-013: the payload says which version it is.

    `API-013` is the half people skip: compatibility is not inherited from the
    fact that an old parser happens not to crash on new output.
    """
    # Resolve and combine conformant entry-point source for version declaration checks.
    package = package_root(reference_root())
    text = module_text(package, *ENTRY_POINTS)
    # Require the published payload path to reference its schema version.
    assert _SCHEMA_VERSION.search(text), "no schema version in the published payload"

    # Both assignment forms, because an annotated constant -- which is what the
    # discipline's own typing rules push an author towards -- is an `AnnAssign`
    # and not an `Assign`. Checking only the latter reported the reference's own
    # `SCHEMA_VERSION: str = "1"` as undeclared.
    tree = ast.parse(text)
    # Retain schema-version declaration-node elements in deterministic AST order.
    declared = [
        n for n in ast.walk(tree)
        if (isinstance(n, ast.Assign)
            and any(getattr(t, "id", "").upper() == "SCHEMA_VERSION" for t in n.targets))
        or (isinstance(n, ast.AnnAssign)
            and getattr(n.target, "id", "").upper() == "SCHEMA_VERSION")
    ]
    # Reject a version emitted ad hoc rather than declared as a durable constant.
    assert declared, "the schema version is emitted but never declared as a constant"


# ------------------------------------------------------------------- API-012


@decides("API-012")
def test_migrations() -> None:
    """API-012: a format past its first version ships a migration and its test.

    Conditional, and vacuous for a format still at version 1 -- which is correct:
    there is nothing to migrate from. The reference is at 1 and says so.
    """
    # Resolve and combine entry-point source before parsing the declared format version.
    package = package_root(reference_root())
    text = module_text(package, *ENTRY_POINTS)
    found = re.search(r"SCHEMA_VERSION\s*[:=].*?[\"'](\d+)[\"']", text, re.DOTALL)
    # Require a parseable integer version before applying the migration precondition.
    assert found, "no schema version declared"

    # Treat version one as having no predecessor that could require migration.
    if int(found.group(1)) == 1:
        # End the conditional obligation for the initial published format.
        return
    # Inventory migration-path elements in filesystem traversal order for later versions.
    root = reference_root()
    migrations = list(root.rglob("*migrat*"))
    # Reject a post-v1 format that strands consumers without a migration path.
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
    # Locate the optional release implementation that owns packaged delivery.
    release = REPO_ROOT / "tools" / "release.py"
    # Mark the publication-specific obligation inapplicable to non-publishing trees.
    if not release.is_file():
        # Report explicit inapplicability rather than passing on an absent subject.
        pytest.skip("this tree publishes no archive")

    # Read release source as the installer-use and archive-membership search surface.
    text = release.read_text(encoding="utf-8")
    # Require both installer staging and an explicit archive content contract.
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
    # Locate the optional release implementation that owns packaged delivery.
    release = REPO_ROOT / "tools" / "release.py"
    # Mark the publication-specific obligation inapplicable to non-publishing trees.
    if not release.is_file():
        # Report explicit inapplicability rather than passing on an absent subject.
        pytest.skip("this tree publishes no archive")
    # Read release source as the pre-staging gate invocation search surface.
    text = release.read_text(encoding="utf-8")
    # Require release staging to depend on the canonical executable gate.
    assert "gate.GATE" in text or "run_gate" in text, (
        "release.py does not run the gate before staging; an archive can be cut "
        "from a tree that fails it"
    )
