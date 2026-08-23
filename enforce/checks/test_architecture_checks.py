"""Discrimination tests for v4's one-unit architecture mechanisms."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from checks import project
from checks.architecture_model import ArchitectureModelCheck
from checks.dependency_boundaries import DependencyBoundariesCheck
from checks.source_roles import SourceRolesCheck

# Import the fixture path protocol only during static analysis.
if TYPE_CHECKING:
    from pathlib import Path


def declared_tree(
    tmp_path: Path, unit: project.UnitKind = project.UnitKind.APPLICATION,
) -> tuple[project.Declaration, Path]:
    """Create a smallest complete role-mapped application fixture.

    @param tmp_path fixture repository
    @param unit governed repository shape
    @return parsed declaration and its source root

    @par Effects
    Creates a complete isolated declaration, production tree, and documentation model.
    """
    # Select the canonical declaration path for the synthetic governed unit.
    project_file = tmp_path / "pyproject.toml"
    # Publish every mandatory project fact and the complete local role partition.
    project_file.write_text(
        f"""[tool.agent-discipline]
unit = "{unit}"
source_roots = ["src"]
architecture = "architecture.json"
contract_conformance = "contract-conformance.json"
operational_model = "operational-model.json"
security_model = "security-model.json"
adversarial_review = "adversarial-review.json"
doc_engine = "doxygen"
documentation_model = "documentation-model.json"
adapter_boundaries = [
    "src/pkg/adapters/clock",
    "src/pkg/adapters/files",
    "src/pkg/adapters/http",
]

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
    # Select the domain root that guarantees the declared production tree is nonempty.
    source = tmp_path / "src/pkg/domain"
    # Materialize and publish representative policy source beneath the domain owner.
    source.mkdir(parents=True)
    (source / "model.py").write_text('"""Policy."""\n', encoding="utf-8")
    # Select the package shell entity explicitly named by the role map.
    package = tmp_path / "src/pkg/__init__.py"
    # Materialize and publish the package entity after its domain subtree exists.
    package.parent.mkdir(parents=True, exist_ok=True)
    package.write_text('"""Public package."""\n', encoding="utf-8")
    # Publish the complete documentation scope required by the project declaration.
    (tmp_path / "documentation-model.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "engine": "doxygen",
                "scopes": [
                    {"path": "src", "kind": "production", "ownership": "governed"}
                ],
                "controlled_abbreviations": [],
                "identifier_grammars": [],
                "generated_names": {
                    "markers": ["generated", "derived"],
                    "mappings": {},
                },
                "semantic_properties": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    # Return the parsed declaration and the bounded source root it governs.
    return project.parse(project_file), tmp_path / "src"


def architecture_payload(unit: str = "application") -> dict[str, object]:
    """A smallest complete local architecture model.

    @param unit application or component model value
    @return JSON-ready model
    """
    # Render one decision, published contract, explicit resource absence, and recovery.
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
    @param payload JSON-ready mapping whose unordered keys name architecture views
        and whose values hold their serialized contents
    @return written model path

    @par Effects
    Creates or replaces the repository-local architecture model.
    """
    # Select the declaration-owned architecture record path.
    path = root / "architecture.json"
    # Publish the complete architecture model as stable indented JSON.
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Return the persisted model for focused mutation probes.
    return path


def write_python(root: Path, relative: str, body: str = '"""Fixture."""\n') -> Path:
    """Write one source module into the architecture fixture.

    @param root fixture source root
    @param relative path beneath the source root
    @param body Python source text
    @return written file

    @par Effects
    Creates parent packages and creates or replaces one isolated Python module.
    """
    # Resolve the source entity whose relative path determines its architectural role.
    target = root / relative
    # Materialize the package tree before publishing the requested source body.
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    # Return the persisted module as the boundary-check subject.
    return target


def test_source_roles_accepts_a_complete_partition(tmp_path: Path) -> None:
    """The positive reference proves explicit roles do not create findings.

    @param tmp_path fixture repository
    """
    # Build the complete role partition and its bounded production subject.
    declaration, source = declared_tree(tmp_path)
    # Configure a fresh role checker from the owning project declaration.
    check = SourceRolesCheck()
    check.declaration = declaration
    assert check.run([source]) == []


def test_source_roles_rejects_an_unmapped_source_directory(tmp_path: Path) -> None:
    """A newly seeded directory cannot disappear from role-scoped checks.

    @param tmp_path fixture repository

    @par Effects
    Creates a complete fixture repository, then adds one unowned source module.
    """
    # Build the complete role partition before seeding an undeclared directory.
    declaration, source = declared_tree(tmp_path)
    # Select a policy module beneath a source directory absent from every role owner.
    hidden = source / "pkg/services/orphan.py"
    # Materialize and publish the orphan only after the declared partition exists.
    hidden.parent.mkdir(parents=True)
    hidden.write_text('"""Unowned policy."""\n', encoding="utf-8")
    # Configure a fresh role checker from the unchanged declaration.
    check = SourceRolesCheck()
    check.declaration = declaration
    # Preserve ordered findings from a deliberately narrower invocation origin.
    findings = check.run([source / "pkg/domain"])
    # Compare each finding element's identity in diagnostic order.
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH018_UNMAPPED_SOURCE"
    ]


def test_source_roles_rejects_an_absent_declared_root(tmp_path: Path) -> None:
    """A typo in source_roots cannot turn an empty walk into conformance.

    @param tmp_path fixture repository

    @par Effects
    Creates a complete fixture repository, then renames its declared source root.
    """
    # Build a declaration whose source root initially exists.
    declaration, source = declared_tree(tmp_path)
    # Move the complete source tree away while leaving the declaration unchanged.
    source.rename(tmp_path / "moved")
    # Configure a fresh role checker from the now-stale declaration.
    check = SourceRolesCheck()
    check.declaration = declaration
    # Preserve ordered findings from the repository root so absence cannot hide.
    findings = check.run([tmp_path])
    # Compare each finding element's identity in diagnostic order.
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH018_SOURCE_ROOT_MISSING"
    ]


def test_local_shell_may_wire_the_real_adapter(tmp_path: Path) -> None:
    """Intentional transitive technology reach does not make shell a second owner.

    @param tmp_path fixture repository
    """
    # Build the complete role partition before adding an intentional composition edge.
    declaration, source = declared_tree(tmp_path)
    # Publish the owned technology adapter and the shell that selects it.
    write_python(source, "pkg/adapters/clock/__init__.py")
    write_python(source, "pkg/adapters/clock/real.py", "import time\n")
    write_python(source, "pkg/shell/__init__.py")
    write_python(
        source,
        "pkg/shell/composition.py",
        "from pkg.adapters.clock.real import Clock\n",
    )
    # Configure dependency enforcement from the fixture's ownership declaration.
    check = DependencyBoundariesCheck()
    check.declaration = declaration
    assert check.run([source]) == []


def test_application_to_concrete_adapter_has_its_own_diagnostic(
    tmp_path: Path,
) -> None:
    """Orchestration naming a concrete adapter is not mislabeled ownership.

    @param tmp_path fixture repository
    """
    # Build the complete role partition before adding the forbidden application edge.
    declaration, source = declared_tree(tmp_path)
    # Publish an HTTP adapter boundary and application source importing it directly.
    write_python(source, "pkg/adapters/http/__init__.py")
    write_python(source, "pkg/app/service.py", "import pkg.adapters.http\n")
    # Configure dependency enforcement from the fixture's ownership declaration.
    check = DependencyBoundariesCheck()
    check.declaration = declaration
    # Preserve ordered findings to distinguish selection from ownership diagnostics.
    findings = check.run([source])
    # Compare each finding element's identity in diagnostic order.
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH019_APPLICATION_TO_ADAPTER"
    ]


def test_second_adapter_importing_owned_technology_has_distinct_diagnostic(
    tmp_path: Path,
) -> None:
    """Direct technology ownership is independent from dependency direction.

    @param tmp_path fixture repository
    """
    # Build the declared clock owner before introducing a competing file adapter.
    declaration, source = declared_tree(tmp_path)
    # Publish a second adapter boundary that imports the clock owner's technology.
    write_python(source, "pkg/adapters/files/__init__.py")
    write_python(source, "pkg/adapters/files/real.py", "import time\n")
    # Configure dependency enforcement from the original singular ownership declaration.
    check = DependencyBoundariesCheck()
    check.declaration = declaration
    # Preserve ordered findings to isolate direct foreign-ownership breach.
    findings = check.run([source])
    # Compare each finding element's identity in diagnostic order.
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH020_FOREIGN_OWNER_BREACH"
    ]


def test_domain_importing_shell_is_an_outward_policy_edge(tmp_path: Path) -> None:
    """The generic direction diagnostic remains separate from adapter selection.

    @param tmp_path fixture repository
    """
    # Build the complete role partition before adding an outward domain dependency.
    declaration, source = declared_tree(tmp_path)
    # Publish shell runtime and policy source that reaches outward to it.
    write_python(source, "pkg/shell/runtime.py")
    write_python(source, "pkg/domain/model.py", "import pkg.shell.runtime\n")
    # Configure dependency enforcement from the fixture's ownership declaration.
    check = DependencyBoundariesCheck()
    check.declaration = declaration
    # Preserve ordered findings to isolate the generic policy-direction diagnostic.
    findings = check.run([source])
    # Compare each finding element's identity in diagnostic order.
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH001_OUTWARD_POLICY_EDGE"
    ]


def test_one_adapter_boundary_cannot_import_another(tmp_path: Path) -> None:
    """Adapter independence is evaluated at the boundary package, not whole role.

    @param tmp_path fixture repository
    """
    # Build independent adapter owners before coupling the file adapter to the clock.
    declaration, source = declared_tree(tmp_path)
    # Publish both boundary roots and the cross-adapter import under test.
    write_python(source, "pkg/adapters/clock/__init__.py")
    write_python(source, "pkg/adapters/files/__init__.py")
    write_python(
        source,
        "pkg/adapters/files/real.py",
        "import pkg.adapters.clock\n",
    )
    # Configure dependency enforcement from the fixture's boundary declarations.
    check = DependencyBoundariesCheck()
    check.declaration = declaration
    # Preserve ordered findings to isolate adapter-to-adapter coupling.
    findings = check.run([source])
    # Compare each finding element's identity in diagnostic order.
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH003_ADAPTER_TO_ADAPTER"
    ]


def test_complete_local_architecture_views_are_accepted(tmp_path: Path) -> None:
    """The positive reference joins all four local views to the declared unit.

    @param tmp_path fixture repository
    """
    # Build the complete local project and production subject.
    declaration, source = declared_tree(tmp_path)
    # Publish all required architecture views as the accepting control.
    write_architecture(tmp_path, architecture_payload())
    # Configure architecture enforcement from the owning declaration.
    check = ArchitectureModelCheck()
    check.declaration = declaration
    assert check.run([source]) == []


def test_architecture_unit_must_match_project_unit(tmp_path: Path) -> None:
    """Two canonical records cannot disagree about the governed shape.

    @param tmp_path fixture repository
    """
    # Build an application declaration before publishing a component model.
    declaration, source = declared_tree(tmp_path)
    # Publish the contradictory unit shape in the canonical architecture record.
    write_architecture(tmp_path, architecture_payload("component"))
    # Configure architecture enforcement from the application declaration.
    check = ArchitectureModelCheck()
    check.declaration = declaration
    # Preserve ordered findings to isolate canonical unit disagreement.
    findings = check.run([source])
    # Compare each finding element's identity in diagnostic order.
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH021_UNIT_MISMATCH"
    ]


def test_volatile_decision_requires_a_change_scenario(tmp_path: Path) -> None:
    """A boundary name without a change it absorbs is not information hiding.

    @param tmp_path fixture repository
    """
    # Build the complete local project before weakening decision rationale.
    declaration, source = declared_tree(tmp_path)
    # Start from the complete architecture model.
    payload = architecture_payload()
    # Select the ordered decision-record elements for focused mutation.
    decisions = payload["decisions"]
    assert isinstance(decisions, list)
    # Select the sole volatile-decision record.
    decision = decisions[0]
    assert isinstance(decision, dict)
    # Remove every change scenario that justifies the information boundary.
    decision["change_scenarios"] = []
    # Publish the incomplete decision view for validation.
    write_architecture(tmp_path, payload)
    # Configure architecture enforcement from the owning declaration.
    check = ArchitectureModelCheck()
    check.declaration = declaration
    # Preserve ordered findings to isolate decision incompleteness.
    findings = check.run([source])
    # Compare each finding element's identity in diagnostic order.
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH021_DECISION_INCOMPLETE"
    ]


def test_component_role_rejects_a_peer_repository_name(tmp_path: Path) -> None:
    """A hyphenated peer identity cannot occupy a contract-role field.

    @param tmp_path fixture repository
    """
    # Build an independently governed component repository and production subject.
    declaration, source = declared_tree(tmp_path, project.UnitKind.COMPONENT)
    # Start from a complete component-local architecture model.
    payload = architecture_payload("component")
    # Select the ordered contract-record elements for role mutation.
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    # Select the sole published component contract.
    contract = contracts[0]
    assert isinstance(contract, dict)
    # Substitute a peer repository identity where a local abstract role belongs.
    contract["role"] = "sine-generator"
    # Publish the counterpart-coupled model for validation.
    write_architecture(tmp_path, payload)
    # Configure architecture enforcement from the component declaration.
    check = ArchitectureModelCheck()
    check.declaration = declaration
    # Preserve ordered findings to isolate peer identity leakage.
    findings = check.run([source])
    # Compare each finding element's identity in diagnostic order.
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH023_ROLE_IDENTITY"
    ]


def test_component_model_rejects_a_deployment_endpoint(tmp_path: Path) -> None:
    """Endpoint wiring is outside a standalone component's local contract.

    @param tmp_path fixture repository
    """
    # Build an independently governed component repository and production subject.
    declaration, source = declared_tree(tmp_path, project.UnitKind.COMPONENT)
    # Start from a complete component-local architecture model.
    payload = architecture_payload("component")
    # Select the ordered contract-record elements for operation mutation.
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    # Select the sole published component contract.
    contract = contracts[0]
    assert isinstance(contract, dict)
    # Select its ordered operation-record elements.
    operations = contract["operations"]
    assert isinstance(operations, list)
    # Select the sole request operation whose timeout remains locally abstract.
    operation = operations[0]
    assert isinstance(operation, dict)
    # Inject deployment endpoint wiring that belongs to a top-level integrator.
    operation["timeout"] = "Connect to tcp://127.0.0.1:9000 within one second."
    # Publish the deployment-coupled component model for validation.
    write_architecture(tmp_path, payload)
    # Configure architecture enforcement from the component declaration.
    check = ArchitectureModelCheck()
    check.declaration = declaration
    # Preserve ordered findings to isolate counterpart identity leakage.
    findings = check.run([source])
    # Compare each finding element's identity in diagnostic order.
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH023_COUNTERPART_IDENTITY"
    ]


def test_empty_resource_view_requires_an_explanation(tmp_path: Path) -> None:
    """An empty array is explicit only when the absence itself is justified.

    @param tmp_path fixture repository
    """
    # Build the complete application repository before removing absence rationale.
    declaration, source = declared_tree(tmp_path)
    # Start from a model with an explicit empty-resource explanation.
    payload = architecture_payload()
    # Remove the explanation while leaving the resource record array empty.
    payload["resource_absence"] = None
    # Publish the unexplained empty resource view for validation.
    write_architecture(tmp_path, payload)
    # Configure architecture enforcement from the owning declaration.
    check = ArchitectureModelCheck()
    check.declaration = declaration
    # Preserve ordered findings to isolate resource-ownership incompleteness.
    findings = check.run([source])
    # Compare each finding element's identity in diagnostic order.
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH022_RESOURCE_OWNER"
    ]
