"""Proof-of-failure tests for the bounded v4 project declaration.

The important negative cases are the ones that formerly produced a narrower
green scan: an unknown source role, a missing unit, and a component inheriting a
parent repository's declaration. Each is refused with a stable diagnostic id.

    pytest enforce/checks/test_project.py
"""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from checks import layer_of, project

# Import the fixture path protocol only during static analysis.
if TYPE_CHECKING:
    from pathlib import Path


def declare(tmp_path: Path, body: str) -> Path:
    """Write one project file verbatim.

    @param tmp_path directory to write into
    @param body complete TOML body
    @return written ``pyproject.toml``

    @par Effects
    Creates or replaces the isolated project declaration with normalized fixture text.
    """
    # Select the canonical declaration path inside the fixture repository.
    path = tmp_path / "pyproject.toml"
    # Publish the dedented declaration as the repository's configuration boundary.
    path.write_text(dedent(body), encoding="utf-8")
    # Return the persisted declaration for direct parser probes.
    return path


def v4(*, extra: str = "", tables: str = "", doc_engine: str = "doxygen") -> str:
    """A minimal complete declaration with optional fields and child tables.

    @param extra scalar entries in the main declaration table
    @param tables complete child-table text
    @param doc_engine explicit documentation syntax selection
    @return TOML suitable for ``declare``
    """
    # Render the smallest declaration carrying every mandatory project fact.
    return f"""
        [tool.agent-discipline]
        unit = "application"
        source_roots = ["src/pkg"]
        architecture = "architecture.json"
        contract_conformance = "contract-conformance.json"
        operational_model = "operational-model.json"
        security_model = "security-model.json"
        adversarial_review = "adversarial-review.json"
        doc_engine = "{doc_engine}"
        documentation_model = "documentation-model.json"
        {extra}

        [tool.agent-discipline.capabilities]
        public_api = false
        filesystem_io = false
        persistent_state = false
        generated_artifacts = false
        network_io = false
        launches_subprocesses = false
        owns_subprocess_lifecycle = false
        concurrency = false
        destructive_effects = false
        bounded_latency = false
        sensitive_data = false

        {tables}
    """


# ------------------------------------------------------------------- defaults


def test_an_undeclared_project_is_conspicuously_incomplete() -> None:
    """Direct checks retain defaults, but the v4 gate can see they are incomplete."""
    assert project.DEFAULT.unit is None
    assert project.DEFAULT.source_roots == ()
    assert project.DEFAULT.canonical("domain") == "domain"
    assert project.DEFAULT.canonical("services") is None
    assert "DISC-PROJECT-001" in project.DEFAULT.narrowed()[0]


def test_a_missing_declaration_falls_back_for_direct_checks(tmp_path: Path) -> None:
    """The loader preserves a diagnostic fallback; the project gate rejects it.

    @param tmp_path empty directory standing in for an undeclared project
    """
    assert project.load(tmp_path) is project.DEFAULT


@pytest.mark.parametrize("kind", list(project.UnitKind))
def test_both_governed_unit_kinds_are_accepted(
    tmp_path: Path,
    kind: project.UnitKind,
) -> None:
    """Application and single-component repositories share one declaration model.

    @param tmp_path fixture repository
    @param kind one supported repository shape
    """
    # Materialize the selected governed unit kind in an otherwise complete declaration.
    path = declare(
        tmp_path,
        v4(extra=f'unit = "{kind}"').replace('unit = "application"\n', "", 1),
    )
    assert project.parse(path).unit is kind


def test_a_missing_unit_is_refused(tmp_path: Path) -> None:
    """A repository cannot silently acquire application semantics.

    @param tmp_path fixture repository
    """
    # Materialize a declaration that omits the repository's governed unit shape.
    path = declare(
        tmp_path,
        '[tool.agent-discipline]\nsource_roots=["src"]\narchitecture="architecture.json"\ncontract_conformance="contract-conformance.json"\n',
    )
    # Require a stable missing-unit diagnostic instead of an implicit default.
    with pytest.raises(ValueError, match="DISC-PROJECT-001"):
        project.parse(path)


def test_an_unknown_unit_is_refused(tmp_path: Path) -> None:
    """Several components in one repository is not a third unit kind.

    @param tmp_path fixture repository
    """
    # Materialize the forbidden multi-component system value as a unit kind.
    path = declare(
        tmp_path,
        '[tool.agent-discipline]\nunit="system"\nsource_roots=["src"]\narchitecture="architecture.json"\ncontract_conformance="contract-conformance.json"\n',
    )
    # Require the unsupported-kind diagnostic to preserve the one-unit boundary.
    with pytest.raises(ValueError, match="DISC-PROJECT-002"):
        project.parse(path)


def test_a_missing_architecture_record_is_refused(tmp_path: Path) -> None:
    """The local views cannot be silently absent from a declared v4 unit.

    @param tmp_path fixture repository
    """
    # Materialize a governed unit with no local architecture record path.
    path = declare(
        tmp_path,
        '[tool.agent-discipline]\nunit="application"\nsource_roots=["src"]\n',
    )
    # Require architecture omission to fail at declaration parsing.
    with pytest.raises(ValueError, match="DISC-PROJECT-014"):
        project.parse(path)


def test_a_missing_contract_conformance_registry_is_refused(tmp_path: Path) -> None:
    """Implementation evidence cannot silently disappear from the project gate.

    @param tmp_path fixture repository
    """
    # Materialize a declaration with architecture but no conformance registry.
    path = declare(
        tmp_path,
        '[tool.agent-discipline]\nunit="application"\nsource_roots=["src"]\narchitecture="architecture.json"\n',
    )
    # Require implementation-evidence omission to produce its dedicated diagnostic.
    with pytest.raises(ValueError, match="DISC-PROJECT-015"):
        project.parse(path)


def test_a_missing_capability_manifest_is_refused(tmp_path: Path) -> None:
    """Capability absence cannot silently mean that every added obligation is off.

    @param tmp_path fixture repository
    """
    # Materialize required scalar facts without the capability subtable.
    path = declare(
        tmp_path,
        '[tool.agent-discipline]\nunit="application"\nsource_roots=["src"]\n'
        'architecture="architecture.json"\n'
        'contract_conformance="contract-conformance.json"\n',
    )
    # Require absent capability facts to fail rather than default false.
    with pytest.raises(ValueError, match="DISC-PROJECT-016"):
        project.parse(path)


def test_a_missing_operational_model_is_refused(tmp_path: Path) -> None:
    """Operational completeness cannot remain an optional side document.

    @param tmp_path fixture repository
    """
    # Materialize a complete declaration minus its operational-model binding.
    path = declare(
        tmp_path,
        v4().replace('operational_model = "operational-model.json"\n', ""),
    )
    # Require the omitted operational view to fail conspicuously.
    with pytest.raises(ValueError, match="DISC-PROJECT-018"):
        project.parse(path)


def test_a_missing_security_model_is_refused(tmp_path: Path) -> None:
    """Trust-boundary omission cannot silently narrow the security gate.

    @param tmp_path fixture repository
    """
    # Materialize a complete declaration minus its security-model binding.
    path = declare(
        tmp_path,
        v4().replace('security_model = "security-model.json"\n', ""),
    )
    # Require the omitted security view to fail conspicuously.
    with pytest.raises(ValueError, match="DISC-PROJECT-019"):
        project.parse(path)


def test_a_missing_adversarial_review_is_refused(tmp_path: Path) -> None:
    """A missing review artifact cannot look like semantic acceptance.

    @param tmp_path fixture repository
    """
    # Materialize a complete declaration minus its adversarial-review binding.
    path = declare(
        tmp_path,
        v4().replace('adversarial_review = "adversarial-review.json"\n', ""),
    )
    # Require absent semantic-review evidence to fail conspicuously.
    with pytest.raises(ValueError, match="DISC-PROJECT-020"):
        project.parse(path)


def test_a_missing_documentation_model_is_refused(tmp_path: Path) -> None:
    """Documentation scopes and project vocabulary cannot remain implicit.

    @param tmp_path fixture repository
    """
    # Materialize a complete declaration minus its documentation-model binding.
    path = declare(
        tmp_path,
        v4().replace('documentation_model = "documentation-model.json"\n', ""),
    )
    # Require implicit documentation scope to be rejected.
    with pytest.raises(ValueError, match="DISC-PROJECT-022"):
        project.parse(path)


def test_documentation_model_path_cannot_escape(tmp_path: Path) -> None:
    """A model in a parent repository cannot govern the local component.

    @param tmp_path fixture repository
    """
    # Redirect the documentation model beyond the fixture repository boundary.
    body = v4().replace(
        'documentation_model = "documentation-model.json"',
        'documentation_model = "../documentation-model.json"',
    )
    # Require the escaping model path to be rejected before loading its contents.
    with pytest.raises(ValueError, match="DISC-PROJECT-004"):
        project.parse(declare(tmp_path, body))


def test_a_partial_capability_manifest_is_refused(tmp_path: Path) -> None:
    """Adding a future capability cannot default old declarations to false.

    @param tmp_path fixture repository
    """
    # Materialize a capability table missing one required boolean fact.
    path = declare(
        tmp_path,
        v4().replace("sensitive_data = false\n", ""),
    )
    # Require partial capability knowledge to fail instead of narrowing obligations.
    with pytest.raises(ValueError, match="DISC-PROJECT-016"):
        project.parse(path)


def test_capability_values_are_boolean(tmp_path: Path) -> None:
    """A truthy string cannot activate or deactivate an obligation accidentally.

    @param tmp_path fixture repository
    """
    # Materialize a textual lookalike where a boolean capability fact is required.
    path = declare(
        tmp_path,
        v4().replace("network_io = false", 'network_io = "false"'),
    )
    # Require strict boolean typing at the project boundary.
    with pytest.raises(ValueError, match="DISC-PROJECT-017"):
        project.parse(path)


def test_enabled_capabilities_are_typed_facts(tmp_path: Path) -> None:
    """The parsed declaration exposes enum facts rather than arbitrary strings.

    @param tmp_path fixture repository
    """
    # Parse a declaration with network I/O true and sensitive-data handling false.
    found = project.parse(
        declare(tmp_path, v4().replace("network_io = false", "network_io = true"))
    )
    assert found.has(project.Capability.NETWORK_IO)
    assert not found.has(project.Capability.SENSITIVE_DATA)


# ------------------------------------------------------------- source and roles


def test_explicit_role_paths_classify_source(tmp_path: Path) -> None:
    """Classification uses a complete relative path, not a guessed segment.

    @param tmp_path fixture repository
    """
    # Parse explicit application and shell ownership paths for classification probes.
    found = project.parse(
        declare(
            tmp_path,
            v4(
                tables="""
        [tool.agent-discipline.roles]
        application = ["src/pkg/services"]
        shell = ["src/pkg/entry"]
    """
            ),
        )
    )
    assert layer_of(tmp_path / "src/pkg/services/clean.py", found) == "app"
    assert layer_of(tmp_path / "src/pkg/unmapped/clean.py", found) == "unknown"


def test_legacy_aliases_remain_parseable_for_migration(tmp_path: Path) -> None:
    """A dry-run migrator must be able to understand rather than ignore v3 aliases.

    @param tmp_path fixture repository
    """
    # Parse legacy service and composition aliases as migration input.
    found = project.parse(
        declare(
            tmp_path,
            v4(
                tables="""
        [tool.agent-discipline.layers]
        services = "app"
        composition = "shell"
    """
            ),
        )
    )
    assert found.canonical("services") == "app"
    assert layer_of(tmp_path / "src/pkg/services/clean.py", found) == "app"


def test_an_unknown_role_is_refused(tmp_path: Path) -> None:
    """A misspelled role cannot make its directory disappear from checks.

    @param tmp_path fixture repository
    """
    # Materialize a misspelled role whose directory would otherwise escape classification.
    path = declare(
        tmp_path,
        v4(
            tables="""
        [tool.agent-discipline.roles]
        middleware = ["src/pkg/middleware"]
    """
        ),
    )
    # Require unknown ownership vocabulary to fail at the declaration boundary.
    with pytest.raises(ValueError, match="DISC-PROJECT-005"):
        project.parse(path)


def test_a_role_outside_source_roots_is_refused(tmp_path: Path) -> None:
    """A role may not expand the bounded production tree implicitly.

    @param tmp_path fixture repository
    """
    # Materialize domain ownership outside the explicitly governed source roots.
    path = declare(
        tmp_path,
        v4(
            tables="""
        [tool.agent-discipline.roles]
        domain = ["other/pkg/domain"]
    """
        ),
    )
    # Require role ownership to remain inside the bounded production tree.
    with pytest.raises(ValueError, match="DISC-PROJECT-006"):
        project.parse(path)


def test_overlapping_roles_are_refused(tmp_path: Path) -> None:
    """One source path cannot acquire two architectural owners.

    @param tmp_path fixture repository
    """
    # Materialize nested application and adapter owners for the same source subtree.
    path = declare(
        tmp_path,
        v4(
            tables="""
        [tool.agent-discipline.roles]
        application = ["src/pkg/services"]
        adapters = ["src/pkg/services/http"]
    """
        ),
    )
    # Require every governed source path to have one unambiguous role owner.
    with pytest.raises(ValueError, match="DISC-PROJECT-006"):
        project.parse(path)


def test_foreign_import_has_one_adapter_owner(tmp_path: Path) -> None:
    """A technology import is registered against a boundary, not one module.

    @param tmp_path fixture repository
    """
    # Parse one technology import assigned to one adapter-owned boundary.
    found = project.parse(
        declare(
            tmp_path,
            v4(
                tables="""
        [tool.agent-discipline.roles]
        adapters = ["src/pkg/adapters"]

        [[tool.agent-discipline.foreign_dependencies]]
        import_name = "httpx"
        owner = "src/pkg/adapters/http"
    """
            ),
        )
    )
    assert found.foreign_ownership["httpx"].as_posix() == "src/pkg/adapters/http"


def test_duplicate_foreign_import_owners_are_refused(tmp_path: Path) -> None:
    """One import root cannot have two direct owners.

    @param tmp_path fixture repository
    """
    # Materialize two competing adapter owners for the same import root.
    path = declare(
        tmp_path,
        v4(
            tables="""
        [tool.agent-discipline.roles]
        adapters = ["src/pkg/adapters"]

        [[tool.agent-discipline.foreign_dependencies]]
        import_name = "httpx"
        owner = "src/pkg/adapters/http"

        [[tool.agent-discipline.foreign_dependencies]]
        import_name = "httpx"
        owner = "src/pkg/adapters/backup_http"
    """
        ),
    )
    # Require foreign dependency ownership to remain singular and deterministic.
    with pytest.raises(ValueError, match="DISC-PROJECT-011"):
        project.parse(path)


def test_foreign_owner_outside_adapters_is_refused(tmp_path: Path) -> None:
    """The shell selects adapters but never becomes the direct technology owner.

    @param tmp_path fixture repository
    """
    # Materialize a shell path claiming direct ownership of a technology import.
    path = declare(
        tmp_path,
        v4(
            tables="""
        [tool.agent-discipline.roles]
        adapters = ["src/pkg/adapters"]
        shell = ["src/pkg/shell"]

        [[tool.agent-discipline.foreign_dependencies]]
        import_name = "httpx"
        owner = "src/pkg/shell"
    """
        ),
    )
    # Require technology ownership to terminate at an adapter boundary.
    with pytest.raises(ValueError, match="DISC-PROJECT-012"):
        project.parse(path)


@pytest.mark.parametrize("bad", ["../peer", "/absolute", "C:/peer", "./"])
def test_source_roots_cannot_escape_or_name_the_repository(
    tmp_path: Path,
    bad: str,
) -> None:
    """Every inspected source root is bounded by this checkout.

    @param tmp_path fixture repository
    @param bad unsafe path spelling
    """
    # Materialize the current unsafe source-root spelling as a component declaration.
    path = declare(
        tmp_path,
        f'[tool.agent-discipline]\nunit="component"\nsource_roots=["{bad}"]\narchitecture="architecture.json"\ncontract_conformance="contract-conformance.json"\n',
    )
    # Require every absolute, escaping, or repository-wide root to be rejected.
    with pytest.raises(ValueError, match="DISC-PROJECT-004"):
        project.parse(path)


# ------------------------------------------------------------ the doc engine


def test_a_missing_engine_is_refused_not_defaulted(tmp_path: Path) -> None:
    """A v4 gate cannot silently deactivate engine-specific documentation checks.

    @param tmp_path fixture repository
    """
    # Remove the explicit engine fact from an otherwise complete v5 declaration.
    body = v4().replace('        doc_engine = "doxygen"\n', "", 1)
    # Require documentation enforcement to remain explicitly enabled.
    with pytest.raises(ValueError, match="DISC-PROJECT-007"):
        project.parse(declare(tmp_path, body))


def test_doxygen_is_the_only_v5_engine(tmp_path: Path) -> None:
    """A v5 project retains exactly one structured documentation system.

    @param tmp_path fixture repository
    """
    # Parse the complete v5 documentation declaration as the accepting control.
    found = project.parse(declare(tmp_path, v4()))
    assert found.doc_engine == "doxygen"


@pytest.mark.parametrize("engine", ["sphinx", "none"])
def test_a_v4_engine_gets_one_actionable_migration_diagnostic(tmp_path: Path, engine: str) -> None:
    """Former explicit choices fail as migrations rather than narrowed scans.

    @param tmp_path fixture repository
    @param engine former v4 selection
    """
    # Require each removed v4 choice to identify the exact v5 replacement.
    with pytest.raises(ValueError, match=r"DISC-PROJECT-021.*replace it with 'doxygen'"):
        project.parse(declare(tmp_path, v4(doc_engine=engine)))


def test_an_unknown_engine_is_refused_not_ignored(tmp_path: Path) -> None:
    """A misspelled engine cannot silently deactivate form rules.

    @param tmp_path fixture repository
    """
    # Materialize a misspelled engine that must not narrow documentation checks.
    path = declare(tmp_path, v4(doc_engine="doxy"))
    # Require unknown engine vocabulary to fail rather than be ignored.
    with pytest.raises(ValueError, match="DISC-PROJECT-007"):
        project.parse(path)


def test_doxygen_narrows_nothing(tmp_path: Path) -> None:
    """A complete Doxygen declaration leaves no direct-check caveat.

    @param tmp_path fixture repository
    """
    # Parse the sole supported engine as the non-narrowing control.
    found = project.parse(declare(tmp_path, v4(doc_engine="doxygen")))
    assert found.narrowed() == ()


# --------------------------------------------------------- repository boundary


def test_the_declaration_is_found_from_a_nested_path(tmp_path: Path) -> None:
    """A check pointed at source finds the repository's own declaration.

    @param tmp_path fixture repository

    @par Effects
    Writes an isolated project declaration and creates a nested source directory.
    """
    # Establish the fixture repository's governing declaration before nesting source.
    declare(tmp_path, v4())
    # Select a deeply nested domain path as the declaration-discovery origin.
    nested = tmp_path / "src/pkg/domain"
    # Materialize the source origin only after its ancestor declaration exists.
    nested.mkdir(parents=True)
    assert project.load(nested).doc_engine == "doxygen"


def test_a_nearer_project_without_the_table_blocks_parent_inheritance(
    tmp_path: Path,
) -> None:
    """A component never inherits a parent/meta-repository declaration.

    @param tmp_path parent fixture containing a nested component checkout

    @par Effects
    Writes parent and nested declarations and creates their component source directories.
    """
    # Establish a complete outer declaration that the nested component must not inherit.
    declare(tmp_path, v4(doc_engine="doxygen"))
    # Select the independently bounded nested component repository.
    component = tmp_path / "component"
    # Materialize that component boundary before its nearer declaration.
    component.mkdir()
    # Give the component a project file that deliberately lacks the discipline table.
    declare(component, '[project]\nname="component"\n')
    # Select a source origin beneath the nearer incomplete project boundary.
    source = component / "src"
    # Materialize the lookup origin after both project boundaries exist.
    source.mkdir()
    assert project.find_declaration(source) is None
    assert project.load(source) is project.DEFAULT


def test_an_explicit_parent_or_sibling_project_is_refused(tmp_path: Path) -> None:
    """Command-line configuration cannot pierce the local repository boundary.

    @param tmp_path parent fixture containing two projects

    @par Effects
    Writes outer and nested declarations and creates the nested source directories.
    """
    # Persist the outer declaration whose explicit use would pierce the component boundary.
    parent = declare(tmp_path, v4())
    # Select the independently declared nested component repository.
    component = tmp_path / "component"
    # Materialize the component boundary before placing its declaration.
    component.mkdir()
    # Establish the nearer valid declaration that owns component source.
    declare(component, v4())
    # Select the source origin governed by that nearer declaration.
    source = component / "src"
    # Materialize the lookup origin after both competing declarations exist.
    source.mkdir()
    # Require an explicitly supplied outer project to be rejected as nonlocal.
    with pytest.raises(ValueError, match="DISC-PROJECT-009"):
        project.load(source, parent)


def test_the_nearest_project_may_be_named_explicitly(tmp_path: Path) -> None:
    """Explicit loading is deterministic when it names the same local boundary.

    @param tmp_path fixture repository

    @par Effects
    Writes one local declaration and creates its source directory.
    """
    # Persist the declaration that is both explicit and nearest to the source origin.
    local = declare(tmp_path, v4())
    # Select a source path owned by that same local repository boundary.
    source = tmp_path / "src"
    # Materialize the lookup origin after the local declaration exists.
    source.mkdir()
    assert project.load(source, local).doc_engine == "doxygen"
