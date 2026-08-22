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

if TYPE_CHECKING:
    from pathlib import Path


def declare(tmp_path: Path, body: str) -> Path:
    """Write one project file verbatim.

    @param tmp_path directory to write into
    @param body complete TOML body
    @return written ``pyproject.toml``
    """
    path = tmp_path / "pyproject.toml"
    path.write_text(dedent(body), encoding="utf-8")
    return path


def v4(*, extra: str = "", tables: str = "") -> str:
    """A minimal complete declaration with optional fields and child tables.

    @param extra scalar entries in the main declaration table
    @param tables complete child-table text
    @return TOML suitable for ``declare``
    """
    return f"""
        [tool.agent-discipline]
        unit = "application"
        source_roots = ["src/pkg"]
        architecture = "architecture.json"
        contract_conformance = "contract-conformance.json"
        operational_model = "operational-model.json"
        security_model = "security-model.json"
        adversarial_review = "adversarial-review.json"
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
    tmp_path: Path, kind: project.UnitKind,
) -> None:
    """Application and single-component repositories share one declaration model.

    @param tmp_path fixture repository
    @param kind one supported repository shape
    """
    path = declare(
        tmp_path,
        v4(extra=f'unit = "{kind}"').replace('unit = "application"\n', "", 1),
    )
    assert project.parse(path).unit is kind


def test_a_missing_unit_is_refused(tmp_path: Path) -> None:
    """A repository cannot silently acquire application semantics.

    @param tmp_path fixture repository
    """
    path = declare(
        tmp_path,
        '[tool.agent-discipline]\nsource_roots=["src"]\narchitecture="architecture.json"\ncontract_conformance="contract-conformance.json"\n',
    )
    with pytest.raises(ValueError, match="DISC-PROJECT-001"):
        project.parse(path)


def test_an_unknown_unit_is_refused(tmp_path: Path) -> None:
    """Several components in one repository is not a third unit kind.

    @param tmp_path fixture repository
    """
    path = declare(
        tmp_path,
        '[tool.agent-discipline]\nunit="system"\nsource_roots=["src"]\narchitecture="architecture.json"\ncontract_conformance="contract-conformance.json"\n',
    )
    with pytest.raises(ValueError, match="DISC-PROJECT-002"):
        project.parse(path)


def test_a_missing_architecture_record_is_refused(tmp_path: Path) -> None:
    """The local views cannot be silently absent from a declared v4 unit.

    @param tmp_path fixture repository
    """
    path = declare(
        tmp_path,
        '[tool.agent-discipline]\nunit="application"\nsource_roots=["src"]\n',
    )
    with pytest.raises(ValueError, match="DISC-PROJECT-014"):
        project.parse(path)


def test_a_missing_contract_conformance_registry_is_refused(tmp_path: Path) -> None:
    """Implementation evidence cannot silently disappear from the project gate.

    @param tmp_path fixture repository
    """
    path = declare(
        tmp_path,
        '[tool.agent-discipline]\nunit="application"\nsource_roots=["src"]\narchitecture="architecture.json"\n',
    )
    with pytest.raises(ValueError, match="DISC-PROJECT-015"):
        project.parse(path)


def test_a_missing_capability_manifest_is_refused(tmp_path: Path) -> None:
    """Capability absence cannot silently mean that every added obligation is off.

    @param tmp_path fixture repository
    """
    path = declare(
        tmp_path,
        '[tool.agent-discipline]\nunit="application"\nsource_roots=["src"]\n'
        'architecture="architecture.json"\n'
        'contract_conformance="contract-conformance.json"\n',
    )
    with pytest.raises(ValueError, match="DISC-PROJECT-016"):
        project.parse(path)


def test_a_missing_operational_model_is_refused(tmp_path: Path) -> None:
    """Operational completeness cannot remain an optional side document.

    @param tmp_path fixture repository
    """
    path = declare(
        tmp_path,
        v4().replace('operational_model = "operational-model.json"\n', ""),
    )
    with pytest.raises(ValueError, match="DISC-PROJECT-018"):
        project.parse(path)


def test_a_missing_security_model_is_refused(tmp_path: Path) -> None:
    """Trust-boundary omission cannot silently narrow the security gate.

    @param tmp_path fixture repository
    """
    path = declare(
        tmp_path,
        v4().replace('security_model = "security-model.json"\n', ""),
    )
    with pytest.raises(ValueError, match="DISC-PROJECT-019"):
        project.parse(path)


def test_a_missing_adversarial_review_is_refused(tmp_path: Path) -> None:
    """A missing review artifact cannot look like semantic acceptance.

    @param tmp_path fixture repository
    """
    path = declare(
        tmp_path,
        v4().replace('adversarial_review = "adversarial-review.json"\n', ""),
    )
    with pytest.raises(ValueError, match="DISC-PROJECT-020"):
        project.parse(path)


def test_a_partial_capability_manifest_is_refused(tmp_path: Path) -> None:
    """Adding a future capability cannot default old declarations to false.

    @param tmp_path fixture repository
    """
    path = declare(
        tmp_path,
        v4().replace("sensitive_data = false\n", ""),
    )
    with pytest.raises(ValueError, match="DISC-PROJECT-016"):
        project.parse(path)


def test_capability_values_are_boolean(tmp_path: Path) -> None:
    """A truthy string cannot activate or deactivate an obligation accidentally.

    @param tmp_path fixture repository
    """
    path = declare(
        tmp_path,
        v4().replace("network_io = false", 'network_io = "false"'),
    )
    with pytest.raises(ValueError, match="DISC-PROJECT-017"):
        project.parse(path)


def test_enabled_capabilities_are_typed_facts(tmp_path: Path) -> None:
    """The parsed declaration exposes enum facts rather than arbitrary strings.

    @param tmp_path fixture repository
    """
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
    found = project.parse(declare(tmp_path, v4(tables="""
        [tool.agent-discipline.roles]
        application = ["src/pkg/services"]
        shell = ["src/pkg/entry"]
    """)))
    assert layer_of(tmp_path / "src/pkg/services/clean.py", found) == "app"
    assert layer_of(tmp_path / "src/pkg/unmapped/clean.py", found) == "unknown"


def test_legacy_aliases_remain_parseable_for_migration(tmp_path: Path) -> None:
    """A dry-run migrator must be able to understand rather than ignore v3 aliases.

    @param tmp_path fixture repository
    """
    found = project.parse(declare(tmp_path, v4(tables="""
        [tool.agent-discipline.layers]
        services = "app"
        composition = "shell"
    """)))
    assert found.canonical("services") == "app"
    assert layer_of(tmp_path / "src/pkg/services/clean.py", found) == "app"


def test_an_unknown_role_is_refused(tmp_path: Path) -> None:
    """A misspelled role cannot make its directory disappear from checks.

    @param tmp_path fixture repository
    """
    path = declare(tmp_path, v4(tables="""
        [tool.agent-discipline.roles]
        middleware = ["src/pkg/middleware"]
    """))
    with pytest.raises(ValueError, match="DISC-PROJECT-005"):
        project.parse(path)


def test_a_role_outside_source_roots_is_refused(tmp_path: Path) -> None:
    """A role may not expand the bounded production tree implicitly.

    @param tmp_path fixture repository
    """
    path = declare(tmp_path, v4(tables="""
        [tool.agent-discipline.roles]
        domain = ["other/pkg/domain"]
    """))
    with pytest.raises(ValueError, match="DISC-PROJECT-006"):
        project.parse(path)


def test_overlapping_roles_are_refused(tmp_path: Path) -> None:
    """One source path cannot acquire two architectural owners.

    @param tmp_path fixture repository
    """
    path = declare(tmp_path, v4(tables="""
        [tool.agent-discipline.roles]
        application = ["src/pkg/services"]
        adapters = ["src/pkg/services/http"]
    """))
    with pytest.raises(ValueError, match="DISC-PROJECT-006"):
        project.parse(path)


def test_foreign_import_has_one_adapter_owner(tmp_path: Path) -> None:
    """A technology import is registered against a boundary, not one module.

    @param tmp_path fixture repository
    """
    found = project.parse(declare(tmp_path, v4(tables="""
        [tool.agent-discipline.roles]
        adapters = ["src/pkg/adapters"]

        [[tool.agent-discipline.foreign_dependencies]]
        import_name = "httpx"
        owner = "src/pkg/adapters/http"
    """)))
    assert found.foreign_ownership["httpx"].as_posix() == "src/pkg/adapters/http"


def test_duplicate_foreign_import_owners_are_refused(tmp_path: Path) -> None:
    """One import root cannot have two direct owners.

    @param tmp_path fixture repository
    """
    path = declare(tmp_path, v4(tables="""
        [tool.agent-discipline.roles]
        adapters = ["src/pkg/adapters"]

        [[tool.agent-discipline.foreign_dependencies]]
        import_name = "httpx"
        owner = "src/pkg/adapters/http"

        [[tool.agent-discipline.foreign_dependencies]]
        import_name = "httpx"
        owner = "src/pkg/adapters/backup_http"
    """))
    with pytest.raises(ValueError, match="DISC-PROJECT-011"):
        project.parse(path)


def test_foreign_owner_outside_adapters_is_refused(tmp_path: Path) -> None:
    """The shell selects adapters but never becomes the direct technology owner.

    @param tmp_path fixture repository
    """
    path = declare(tmp_path, v4(tables="""
        [tool.agent-discipline.roles]
        adapters = ["src/pkg/adapters"]
        shell = ["src/pkg/shell"]

        [[tool.agent-discipline.foreign_dependencies]]
        import_name = "httpx"
        owner = "src/pkg/shell"
    """))
    with pytest.raises(ValueError, match="DISC-PROJECT-012"):
        project.parse(path)


@pytest.mark.parametrize("bad", ["../peer", "/absolute", "C:/peer", "./"])
def test_source_roots_cannot_escape_or_name_the_repository(
    tmp_path: Path, bad: str,
) -> None:
    """Every inspected source root is bounded by this checkout.

    @param tmp_path fixture repository
    @param bad unsafe path spelling
    """
    path = declare(
        tmp_path,
        f'[tool.agent-discipline]\nunit="component"\nsource_roots=["{bad}"]\narchitecture="architecture.json"\ncontract_conformance="contract-conformance.json"\n',
    )
    with pytest.raises(ValueError, match="DISC-PROJECT-004"):
        project.parse(path)


# ------------------------------------------------------------ the doc engine


@pytest.mark.parametrize("engine", ["doxygen", "sphinx", "none"])
def test_each_known_engine_is_accepted(tmp_path: Path, engine: str) -> None:
    """The three recognized documentation syntaxes remain explicit.

    @param tmp_path fixture repository
    @param engine engine under test
    """
    found = project.parse(declare(tmp_path, v4(extra=f'doc_engine = "{engine}"')))
    assert found.doc_engine == engine


def test_an_unknown_engine_is_refused_not_ignored(tmp_path: Path) -> None:
    """A misspelled engine cannot silently deactivate form rules.

    @param tmp_path fixture repository
    """
    path = declare(tmp_path, v4(extra='doc_engine = "doxy"'))
    with pytest.raises(ValueError, match="DISC-PROJECT-007"):
        project.parse(path)


def test_doxygen_narrows_nothing(tmp_path: Path) -> None:
    """A complete Doxygen declaration leaves no direct-check caveat.

    @param tmp_path fixture repository
    """
    found = project.parse(declare(tmp_path, v4(extra='doc_engine = "doxygen"')))
    assert found.narrowed() == ()


# --------------------------------------------------------- repository boundary


def test_the_declaration_is_found_from_a_nested_path(tmp_path: Path) -> None:
    """A check pointed at source finds the repository's own declaration.

    @param tmp_path fixture repository
    """
    declare(tmp_path, v4(extra='doc_engine = "sphinx"'))
    nested = tmp_path / "src/pkg/domain"
    nested.mkdir(parents=True)
    assert project.load(nested).doc_engine == "sphinx"


def test_a_nearer_project_without_the_table_blocks_parent_inheritance(
    tmp_path: Path,
) -> None:
    """A component never inherits a parent/meta-repository declaration.

    @param tmp_path parent fixture containing a nested component checkout
    """
    declare(tmp_path, v4(extra='doc_engine = "doxygen"'))
    component = tmp_path / "component"
    component.mkdir()
    declare(component, '[project]\nname="component"\n')
    source = component / "src"
    source.mkdir()
    assert project.find_declaration(source) is None
    assert project.load(source) is project.DEFAULT


def test_an_explicit_parent_or_sibling_project_is_refused(tmp_path: Path) -> None:
    """Command-line configuration cannot pierce the local repository boundary.

    @param tmp_path parent fixture containing two projects
    """
    parent = declare(tmp_path, v4())
    component = tmp_path / "component"
    component.mkdir()
    declare(component, v4())
    source = component / "src"
    source.mkdir()
    with pytest.raises(ValueError, match="DISC-PROJECT-009"):
        project.load(source, parent)


def test_the_nearest_project_may_be_named_explicitly(tmp_path: Path) -> None:
    """Explicit loading is deterministic when it names the same local boundary.

    @param tmp_path fixture repository
    """
    local = declare(tmp_path, v4(extra='doc_engine = "sphinx"'))
    source = tmp_path / "src"
    source.mkdir()
    assert project.load(source, local).doc_engine == "sphinx"
