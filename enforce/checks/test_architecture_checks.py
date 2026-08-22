"""Discrimination tests for v4's one-unit architecture mechanisms."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from checks import project
from checks.architecture_model import ArchitectureModelCheck
from checks.dependency_boundaries import DependencyBoundariesCheck
from checks.source_roles import SourceRolesCheck

if TYPE_CHECKING:
    from pathlib import Path


def declared_tree(
    tmp_path: Path, unit: project.UnitKind = project.UnitKind.APPLICATION,
) -> tuple[project.Declaration, Path]:
    """Create a smallest complete role-mapped application fixture.

    @param tmp_path fixture repository
    @param unit governed repository shape
    @return parsed declaration and its source root
    """
    project_file = tmp_path / "pyproject.toml"
    project_file.write_text(
        f"""[tool.agent-discipline]
unit = "{unit}"
source_roots = ["src"]
architecture = "architecture.json"
contract_conformance = "contract-conformance.json"
adapter_boundaries = [
    "src/pkg/adapters/clock",
    "src/pkg/adapters/files",
    "src/pkg/adapters/http",
]

[tool.agent-discipline.roles]
domain = ["src/pkg/domain"]
application = ["src/pkg/app"]
ports = ["src/pkg/ports"]
adapters = ["src/pkg/adapters"]
shell = ["src/pkg/__init__.py", "src/pkg/shell"]

[[tool.agent-discipline.foreign_dependencies]]
import_name = "time"
owner = "src/pkg/adapters/clock"
""",
        encoding="utf-8",
    )
    source = tmp_path / "src/pkg/domain"
    source.mkdir(parents=True)
    (source / "model.py").write_text('"""Policy."""\n', encoding="utf-8")
    package = tmp_path / "src/pkg/__init__.py"
    package.parent.mkdir(parents=True, exist_ok=True)
    package.write_text('"""Public package."""\n', encoding="utf-8")
    return project.parse(project_file), tmp_path / "src"


def architecture_payload(unit: str = "application") -> dict[str, object]:
    """A smallest complete local architecture model.

    @param unit application or component model value
    @return JSON-ready model
    """
    return {
        "schema_version": 1,
        "unit": unit,
        "responsibility": "Transform one request into one typed response.",
        "decisions": [{
            "id": "encoding_choice",
            "volatile_decision": "How boundary bytes become domain values.",
            "owner_role": "adapters",
            "change_scenarios": ["Replace the codec without changing policy."],
        }],
        "contracts": [{
            "id": "request_contract",
            "direction": "published",
            "role": "request_client",
            "version": "1",
            "source": "local",
            "provenance": None,
            "operations": [{
                "name": "request",
                "inputs": "One validated request.",
                "outputs": "One typed response.",
                "errors": ["invalid_request"],
                "ordering": "Requests are serialized.",
                "idempotency": "Repeated equal requests are equivalent.",
                "concurrency": "One request runs at a time.",
                "timeout": "No retry is performed after the local deadline.",
            }],
        }],
        "resources": [],
        "resource_absence": "No resource survives a request.",
        "recoveries": [{
            "failure": "invalid_request",
            "detected_at": "input adapter",
            "contained_at": "published boundary",
            "owner_role": "application",
            "action": "Return a typed refusal.",
            "escalation": "Render one terminal reason.",
            "terminal_state": "No state changed.",
        }],
    }


def write_architecture(root: Path, payload: dict[str, object]) -> Path:
    """Write a canonical architecture fixture.

    @param root fixture repository
    @param payload JSON-ready architecture model
    @return written model path
    """
    path = root / "architecture.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_python(root: Path, relative: str, body: str = '"""Fixture."""\n') -> Path:
    """Write one source module into the architecture fixture.

    @param root fixture source root
    @param relative path beneath the source root
    @param body Python source text
    @return written file
    """
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


def test_source_roles_accepts_a_complete_partition(tmp_path: Path) -> None:
    """The positive reference proves explicit roles do not create findings.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    check = SourceRolesCheck()
    check.declaration = declaration
    assert check.run([source]) == []


def test_source_roles_rejects_an_unmapped_source_directory(tmp_path: Path) -> None:
    """A newly seeded directory cannot disappear from role-scoped checks.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    hidden = source / "pkg/services/orphan.py"
    hidden.parent.mkdir(parents=True)
    hidden.write_text('"""Unowned policy."""\n', encoding="utf-8")
    check = SourceRolesCheck()
    check.declaration = declaration
    findings = check.run([source / "pkg/domain"])
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH018_UNMAPPED_SOURCE"
    ]


def test_source_roles_rejects_an_absent_declared_root(tmp_path: Path) -> None:
    """A typo in source_roots cannot turn an empty walk into conformance.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    source.rename(tmp_path / "moved")
    check = SourceRolesCheck()
    check.declaration = declaration
    findings = check.run([tmp_path])
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH018_SOURCE_ROOT_MISSING"
    ]


def test_local_shell_may_wire_the_real_adapter(tmp_path: Path) -> None:
    """Intentional transitive technology reach does not make shell a second owner.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    write_python(source, "pkg/adapters/clock/__init__.py")
    write_python(source, "pkg/adapters/clock/real.py", "import time\n")
    write_python(source, "pkg/shell/__init__.py")
    write_python(
        source,
        "pkg/shell/composition.py",
        "from pkg.adapters.clock.real import Clock\n",
    )
    check = DependencyBoundariesCheck()
    check.declaration = declaration
    assert check.run([source]) == []


def test_application_to_concrete_adapter_has_its_own_diagnostic(
    tmp_path: Path,
) -> None:
    """Orchestration naming a concrete adapter is not mislabeled ownership.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    write_python(source, "pkg/adapters/http/__init__.py")
    write_python(source, "pkg/app/service.py", "import pkg.adapters.http\n")
    check = DependencyBoundariesCheck()
    check.declaration = declaration
    findings = check.run([source])
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH019_APPLICATION_TO_ADAPTER"
    ]


def test_second_adapter_importing_owned_technology_has_distinct_diagnostic(
    tmp_path: Path,
) -> None:
    """Direct technology ownership is independent from dependency direction.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    write_python(source, "pkg/adapters/files/__init__.py")
    write_python(source, "pkg/adapters/files/real.py", "import time\n")
    check = DependencyBoundariesCheck()
    check.declaration = declaration
    findings = check.run([source])
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH020_FOREIGN_OWNER_BREACH"
    ]


def test_domain_importing_shell_is_an_outward_policy_edge(tmp_path: Path) -> None:
    """The generic direction diagnostic remains separate from adapter selection.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    write_python(source, "pkg/shell/runtime.py")
    write_python(source, "pkg/domain/model.py", "import pkg.shell.runtime\n")
    check = DependencyBoundariesCheck()
    check.declaration = declaration
    findings = check.run([source])
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH001_OUTWARD_POLICY_EDGE"
    ]


def test_one_adapter_boundary_cannot_import_another(tmp_path: Path) -> None:
    """Adapter independence is evaluated at the boundary package, not whole role.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    write_python(source, "pkg/adapters/clock/__init__.py")
    write_python(source, "pkg/adapters/files/__init__.py")
    write_python(
        source,
        "pkg/adapters/files/real.py",
        "import pkg.adapters.clock\n",
    )
    check = DependencyBoundariesCheck()
    check.declaration = declaration
    findings = check.run([source])
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH003_ADAPTER_TO_ADAPTER"
    ]


def test_complete_local_architecture_views_are_accepted(tmp_path: Path) -> None:
    """The positive reference joins all four local views to the declared unit.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    write_architecture(tmp_path, architecture_payload())
    check = ArchitectureModelCheck()
    check.declaration = declaration
    assert check.run([source]) == []


def test_architecture_unit_must_match_project_unit(tmp_path: Path) -> None:
    """Two canonical records cannot disagree about the governed shape.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    write_architecture(tmp_path, architecture_payload("component"))
    check = ArchitectureModelCheck()
    check.declaration = declaration
    findings = check.run([source])
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH021_UNIT_MISMATCH"
    ]


def test_volatile_decision_requires_a_change_scenario(tmp_path: Path) -> None:
    """A boundary name without a change it absorbs is not information hiding.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    payload = architecture_payload()
    decisions = payload["decisions"]
    assert isinstance(decisions, list)
    decision = decisions[0]
    assert isinstance(decision, dict)
    decision["change_scenarios"] = []
    write_architecture(tmp_path, payload)
    check = ArchitectureModelCheck()
    check.declaration = declaration
    findings = check.run([source])
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH021_DECISION_INCOMPLETE"
    ]


def test_component_role_rejects_a_peer_repository_name(tmp_path: Path) -> None:
    """A hyphenated peer identity cannot occupy a contract-role field.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path, project.UnitKind.COMPONENT)
    payload = architecture_payload("component")
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    contract = contracts[0]
    assert isinstance(contract, dict)
    contract["role"] = "sine-generator"
    write_architecture(tmp_path, payload)
    check = ArchitectureModelCheck()
    check.declaration = declaration
    findings = check.run([source])
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH023_ROLE_IDENTITY"
    ]


def test_component_model_rejects_a_deployment_endpoint(tmp_path: Path) -> None:
    """Endpoint wiring is outside a standalone component's local contract.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path, project.UnitKind.COMPONENT)
    payload = architecture_payload("component")
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    contract = contracts[0]
    assert isinstance(contract, dict)
    operations = contract["operations"]
    assert isinstance(operations, list)
    operation = operations[0]
    assert isinstance(operation, dict)
    operation["timeout"] = "Connect to tcp://127.0.0.1:9000 within one second."
    write_architecture(tmp_path, payload)
    check = ArchitectureModelCheck()
    check.declaration = declaration
    findings = check.run([source])
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH023_COUNTERPART_IDENTITY"
    ]


def test_empty_resource_view_requires_an_explanation(tmp_path: Path) -> None:
    """An empty array is explicit only when the absence itself is justified.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    payload = architecture_payload()
    payload["resource_absence"] = None
    write_architecture(tmp_path, payload)
    check = ArchitectureModelCheck()
    check.declaration = declaration
    findings = check.run([source])
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH022_RESOURCE_OWNER"
    ]
