"""Proof-of-failure tests for repository-local operational completeness."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from checks import project
from checks.operational_model import (
    BUDGET_CAPABILITIES,
    CAPABILITY_OBLIGATIONS,
    PHASE_CAPABILITIES,
    OperationalModelCheck,
)
from checks.test_architecture_checks import architecture_payload
from checks.test_project import declare, v4

# Import the fixture path protocol only during static analysis.
if TYPE_CHECKING:
    from pathlib import Path

## One valid unit used as executable evidence by every fixture record.
EVIDENCE = "tests/test_ops.py::test_evidence"
## Unordered mapping whose keys name budget classes and values name their valid units.
UNITS = {
    "time": "seconds",
    "memory": "bytes",
    "queue": "items",
    "retry": "attempts",
    "input_size": "bytes",
    "cleanup": "seconds",
}


def operational_payload(
    active: tuple[project.Capability, ...] = (),
) -> dict[str, object]:
    """Build a complete model for a selected capability set.

    @param active ordered capability-enum elements whose declaration order is
        preserved in generated obligation records
    @return JSON-ready operational model
    """
    # Collapse enabled capability elements to an unordered membership set.
    enabled = frozenset(active)
    # Preserve one obligation-record element per active capability in caller order.
    capabilities = [
        {
            "capability": capability.value,
            "resources": [],
            "resource_absence": "The fixture uses no locally owned runtime resource.",
            "recoveries": ["invalid_request"],
            "recovery_absence": None,
            "tests": [
                # Preserve sorted obligation-id elements for deterministic evidence order.
                {"id": obligation, "evidence": EVIDENCE}
                for obligation in sorted(CAPABILITY_OBLIGATIONS[capability])
            ],
        }
        # Expand each active capability element into its complete obligation record.
        for capability in active
    ]
    # Accumulate lifecycle-record elements in canonical phase-map order.
    lifecycle = []
    # Evaluate each phase key and its capability-activator value in declared map order.
    for phase, activators in PHASE_CAPABILITIES.items():
        # Require universal phases and any phase activated by an enabled capability.
        required = phase in {"startup", "steady_state", "shutdown"} or bool(
            enabled & activators
        )
        lifecycle.append({
            "phase": phase,
            "owner_role": "shell",
            "behavior": f"The local shell owns {phase} behavior.",
            "terminal_state": "ready" if phase in {"startup", "steady_state"} else "safe",
            "test": EVIDENCE if required else None,
            "not_applicable": None if required else "No active capability needs this phase.",
        })
    # Accumulate budget-record elements in canonical budget-map order.
    budgets = []
    # Evaluate each budget-kind key and its capability-activator value in declared map order.
    for kind, activators in BUDGET_CAPABILITIES.items():
        # Require a finite bound exactly when an enabled capability activates this cost.
        required = bool(enabled & activators)
        budgets.append({
            "kind": kind,
            "scope": f"The fixture {kind} cost.",
            "bound": {"value": 1, "unit": UNITS[kind]} if required else None,
            "not_applicable": None if required else "No active capability consumes this cost.",
            "measurement": EVIDENCE if required else None,
        })
    # Render the complete operational views after all capability-derived records exist.
    return {
        "schema_version": 1,
        "capability_obligations": capabilities,
        "lifecycle": lifecycle,
        "states": [
            {
                "id": "ready",
                "kind": "safe",
                "entry_conditions": ["Startup validation succeeds."],
                "allowed_operations": ["serve"],
                "observable_event": "FIXTURE-READY",
                "exit_condition": "Shutdown begins.",
            },
            {
                "id": "safe",
                "kind": "degraded",
                "entry_conditions": ["A boundary failure is contained."],
                "allowed_operations": [],
                "observable_event": "FIXTURE-DEGRADED",
                "exit_condition": "The fixture is terminal.",
            },
        ],
        "budgets": budgets,
        "outcomes": [
            {
                "id": "completed",
                "exceptional": False,
                "trigger": "The requested operation completes.",
                "event_code": "FIXTURE-COMPLETED",
                "correlation_field": "operation_id",
                "terminal_state": "safe",
                "test": EVIDENCE,
            }
        ],
        "identity": {
            "build_source": "pyproject.toml",
            "runtime_fields": ["version", "build_id"],
            "test": EVIDENCE,
        },
        "platforms": [
            {
                "name": name,
                "runtime": "supported",
                "development": "supported",
                "evidence": EVIDENCE,
                "limitation": None,
            }
            # Preserve platform-name elements in release qualification order.
            for name in ("windows", "linux")
        ],
    }


def _tree(
    tmp_path: Path,
    *,
    active: tuple[project.Capability, ...] = (),
    payload: dict[str, object] | None = None,
) -> tuple[OperationalModelCheck, Path]:
    """Create one complete operational fixture repository.

    @param tmp_path fixture repository
    @param active ordered capability-enum elements whose declaration order is preserved
    @param payload optional unordered model mapping whose keys name operational
        views and whose values hold their serialized contents
    @return configured checker and source root

    @par Effects
    Creates a complete isolated project, evidence suite, and local model artifacts.
    """
    # Start from the complete declaration with every additive capability false.
    body = v4()
    # Activate each capability element in caller order within declaration text.
    for capability in active:
        # Replace the current false fact with its true state for this capability.
        body = body.replace(
            f"{capability.value} = false",
            f"{capability.value} = true",
        )
    # Persist the selected capability declaration before constructing evidence.
    declaration_path = declare(tmp_path, body)
    # Select the bounded production root consumed by the operational checker.
    source = tmp_path / "src/pkg"
    # Materialize production source before publishing its representative module.
    source.mkdir(parents=True)
    (source / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    # Select the behavior-evidence suite cited by every complete fixture record.
    tests = tmp_path / "tests/test_ops.py"
    # Materialize and publish evidence before the model resolves its identifiers.
    tests.parent.mkdir()
    tests.write_text("def test_evidence(): ...\n", encoding="utf-8")
    # Publish architecture identities required by operational ownership joins.
    (tmp_path / "architecture.json").write_text(
        json.dumps(architecture_payload()), encoding="utf-8",
    )
    # Publish either the focused override or generated complete operational model.
    (tmp_path / "operational-model.json").write_text(
        json.dumps(payload or operational_payload(active)), encoding="utf-8",
    )
    # Configure a fresh checker from the declaration owning the fixture repository.
    check = OperationalModelCheck()
    check.declaration = project.parse(declaration_path)
    # Return the configured mechanism with its bounded production subject.
    return check, source


def _diagnostic(check: OperationalModelCheck, source: Path) -> str | None:
    """Return the first stable diagnostic from one fixture.

    @param check configured operational checker
    @param source production source root
    @return diagnostic id or None for acceptance
    """
    # Preserve ordered findings so the first refusal identifies the broken invariant.
    findings = check.run([source])
    # Collapse acceptance to no diagnostic and refusal to its leading stable identity.
    return None if not findings else findings[0].diagnostic_id


def _records(payload: dict[str, object], key: str) -> list[dict[str, object]]:
    """Narrow one mutable record list in a JSON fixture.

    @param payload JSON-ready unordered mapping whose keys name operational views
        and whose values hold their serialized contents
    @param key root record-array field
    @return mutable record list
    """
    # Select the requested root value before proving its mutable record-array shape.
    value = payload[key]
    assert isinstance(value, list)
    # Require every ordered array element to be a mutable record mapping.
    assert all(isinstance(item, dict) for item in value)
    # Return the same narrowed list so tests can mutate one focused record.
    return value  # type: ignore[return-value]


def test_complete_operational_model_is_accepted(tmp_path: Path) -> None:
    """Explicit empty capability activation still carries universal operations.

    @param tmp_path fixture repository
    """
    # Build the complete universal model with no additive capabilities enabled.
    check, source = _tree(tmp_path)
    assert check.run([source]) == []


def test_active_capability_requires_exactly_one_record(tmp_path: Path) -> None:
    """A true manifest fact cannot disappear from operational evidence.

    @param tmp_path fixture repository
    """
    # Preserve one public-API capability element in declaration order.
    active = (project.Capability.PUBLIC_API,)
    # Activate that fact around a model generated for the empty capability set.
    check, source = _tree(tmp_path, active=active, payload=operational_payload())
    assert _diagnostic(check, source) == "OPMODEL002_CAPABILITY_JOIN"


def test_resource_and_recovery_ids_join_architecture(tmp_path: Path) -> None:
    """Operational ownership cannot cite a stale architecture identity.

    @param tmp_path fixture repository
    """
    # Preserve one filesystem-I/O capability element in declaration order.
    active = (project.Capability.FILESYSTEM_IO,)
    # Start from an unordered model mapping whose keys name views and values hold records.
    payload = operational_payload(active)
    # Select the filesystem obligation record that owns resource joins.
    record = _records(payload, "capability_obligations")[0]
    # Replace explicit absence with an architecture resource identity that does not exist.
    record["resources"] = ["missing_resource"]
    record["resource_absence"] = None
    # Build the focused malformed model and its configured checker.
    check, source = _tree(tmp_path, active=active, payload=payload)
    assert _diagnostic(check, source) == "OPMODEL003_OWNERSHIP_JOIN"


def test_activated_interruption_requires_executable_evidence(tmp_path: Path) -> None:
    """Destructive behavior cannot excuse the interruption phase.

    @param tmp_path fixture repository
    """
    # Preserve one destructive-effects capability element in declaration order.
    active = (project.Capability.DESTRUCTIVE_EFFECTS,)
    # Start from an unordered model mapping whose keys name views and values hold records.
    payload = operational_payload(active)
    # Select the interruption record from ordered lifecycle elements.
    interruption = next(
        # Match each lifecycle-record element by its canonical phase value.
        item for item in _records(payload, "lifecycle") if item["phase"] == "interruption"
    )
    # Remove executable proof and substitute an inadmissible prose excuse.
    interruption["test"] = None
    interruption["not_applicable"] = "Interruption is ignored."
    # Build the focused malformed model and its configured checker.
    check, source = _tree(tmp_path, active=active, payload=payload)
    assert _diagnostic(check, source) == "OPMODEL004_LIFECYCLE"


def test_safe_and_degraded_states_are_both_required(tmp_path: Path) -> None:
    """A happy state alone leaves failure terminality undefined.

    @param tmp_path fixture repository
    """
    # Start from an unordered model mapping whose keys name views and values hold records.
    payload = operational_payload()
    # Replace the degraded state kind so no failure terminal state remains.
    _records(payload, "states")[1]["kind"] = "safe"
    # Build the focused malformed model and its configured checker.
    check, source = _tree(tmp_path, payload=payload)
    assert _diagnostic(check, source) == "OPMODEL005_STATE_OUTCOME"


def test_non_exception_terminal_outcome_is_observable(tmp_path: Path) -> None:
    """Refusals and dropped work must not vanish behind exception-only telemetry.

    @param tmp_path fixture repository
    """
    # Start from an unordered model mapping whose keys name views and values hold records.
    payload = operational_payload()
    # Mark the only terminal outcome exceptional, erasing non-exception observability.
    _records(payload, "outcomes")[0]["exceptional"] = True
    # Build the focused malformed model and its configured checker.
    check, source = _tree(tmp_path, payload=payload)
    assert _diagnostic(check, source) == "OPMODEL005_STATE_OUTCOME"


def test_activated_input_surface_requires_a_finite_budget(tmp_path: Path) -> None:
    """A public interface cannot declare accepted input work unbounded by omission.

    @param tmp_path fixture repository
    """
    # Preserve one public-API capability element in declaration order.
    active = (project.Capability.PUBLIC_API,)
    # Start from an unordered model mapping whose keys name views and values hold records.
    payload = operational_payload(active)
    # Select the input-size record from ordered budget elements.
    budget = next(
        # Match each budget-record element by its canonical kind value.
        item for item in _records(payload, "budgets") if item["kind"] == "input_size"
    )
    # Remove finite proof and substitute an inadmissible unbounded claim.
    budget["bound"] = None
    budget["measurement"] = None
    budget["not_applicable"] = "All inputs are accepted."
    # Build the focused malformed model and its configured checker.
    check, source = _tree(tmp_path, active=active, payload=payload)
    assert _diagnostic(check, source) == "OPMODEL006_BUDGET"


def test_runtime_identity_names_version_and_build(tmp_path: Path) -> None:
    """A version without build identity cannot distinguish two delivered artifacts.

    @param tmp_path fixture repository
    """
    # Start from an unordered model mapping whose keys name views and values hold records.
    payload = operational_payload()
    # Select the runtime identity record from the complete model.
    identity = payload["identity"]
    assert isinstance(identity, dict)
    # Retain version while removing the build identity needed to distinguish artifacts.
    identity["runtime_fields"] = ["version"]
    # Build the focused malformed model and its configured checker.
    check, source = _tree(tmp_path, payload=payload)
    assert _diagnostic(check, source) == "OPMODEL007_IDENTITY_PLATFORM"


def test_platform_matrix_names_windows_and_linux(tmp_path: Path) -> None:
    """An absent release platform cannot look supported.

    @param tmp_path fixture repository
    """
    # Start from an unordered model mapping whose keys name views and values hold records.
    payload = operational_payload()
    # Remove the final platform element, leaving one release leg unrepresented.
    _records(payload, "platforms").pop()
    # Build the focused incomplete matrix and its configured checker.
    check, source = _tree(tmp_path, payload=payload)
    assert _diagnostic(check, source) == "OPMODEL007_IDENTITY_PLATFORM"


def test_generated_capability_obligation_cannot_be_omitted(tmp_path: Path) -> None:
    """Capability activation expands to a closed local evidence set.

    @param tmp_path fixture repository
    """
    # Preserve one network-I/O capability element in declaration order.
    active = (project.Capability.NETWORK_IO,)
    # Start from an unordered model mapping whose keys name views and values hold records.
    payload = operational_payload(active)
    # Select the network capability record that owns generated evidence obligations.
    record = _records(payload, "capability_obligations")[0]
    # Select its ordered test-evidence elements.
    tests = record["tests"]
    assert isinstance(tests, list)
    # Remove one generated obligation element from the closed evidence set.
    tests.pop()
    # Build the focused incomplete model and its configured checker.
    check, source = _tree(tmp_path, active=active, payload=payload)
    assert _diagnostic(check, source) == "OPMODEL008_OBLIGATION"


def test_capability_evidence_cannot_escape_the_repository(tmp_path: Path) -> None:
    """A component cannot satisfy local evidence from a parent or sibling test.

    @param tmp_path fixture repository
    """
    # Preserve one public-API capability element in declaration order.
    active = (project.Capability.PUBLIC_API,)
    # Start from an unordered model mapping whose keys name views and values hold records.
    payload = operational_payload(active)
    # Select the public-interface capability record.
    record = _records(payload, "capability_obligations")[0]
    # Select its ordered test-evidence elements.
    tests = record["tests"]
    assert isinstance(tests, list)
    # Select the first generated obligation evidence record.
    evidence = tests[0]
    assert isinstance(evidence, dict)
    # Redirect local proof to a peer repository beyond the governed unit.
    evidence["evidence"] = "../peer/tests/test_api.py::test_surface"
    # Build the focused escaping model and its configured checker.
    check, source = _tree(tmp_path, active=active, payload=payload)
    assert _diagnostic(check, source) == "OPMODEL008_OBLIGATION"
