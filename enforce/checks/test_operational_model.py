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

if TYPE_CHECKING:
    from pathlib import Path

## One valid unit used as executable evidence by every fixture record.
EVIDENCE = "tests/test_ops.py::test_evidence"
## Valid unit for each budget class in the test model.
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

    @param active enabled additive facts
    @return JSON-ready operational model
    """
    enabled = frozenset(active)
    capabilities = [
        {
            "capability": capability.value,
            "resources": [],
            "resource_absence": "The fixture uses no locally owned runtime resource.",
            "recoveries": ["invalid_request"],
            "recovery_absence": None,
            "tests": [
                {"id": obligation, "evidence": EVIDENCE}
                for obligation in sorted(CAPABILITY_OBLIGATIONS[capability])
            ],
        }
        for capability in active
    ]
    lifecycle = []
    for phase, activators in PHASE_CAPABILITIES.items():
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
    budgets = []
    for kind, activators in BUDGET_CAPABILITIES.items():
        required = bool(enabled & activators)
        budgets.append({
            "kind": kind,
            "scope": f"The fixture {kind} cost.",
            "bound": {"value": 1, "unit": UNITS[kind]} if required else None,
            "not_applicable": None if required else "No active capability consumes this cost.",
            "measurement": EVIDENCE if required else None,
        })
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
    @param active enabled project capability facts
    @param payload optional model override
    @return configured checker and source root
    """
    body = v4()
    for capability in active:
        body = body.replace(
            f"{capability.value} = false",
            f"{capability.value} = true",
        )
    declaration_path = declare(tmp_path, body)
    source = tmp_path / "src/pkg"
    source.mkdir(parents=True)
    (source / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    tests = tmp_path / "tests/test_ops.py"
    tests.parent.mkdir()
    tests.write_text("def test_evidence(): ...\n", encoding="utf-8")
    (tmp_path / "architecture.json").write_text(
        json.dumps(architecture_payload()), encoding="utf-8",
    )
    (tmp_path / "operational-model.json").write_text(
        json.dumps(payload or operational_payload(active)), encoding="utf-8",
    )
    check = OperationalModelCheck()
    check.declaration = project.parse(declaration_path)
    return check, source


def _diagnostic(check: OperationalModelCheck, source: Path) -> str | None:
    """Return the first stable diagnostic from one fixture.

    @param check configured operational checker
    @param source production source root
    @return diagnostic id or None for acceptance
    """
    findings = check.run([source])
    return None if not findings else findings[0].diagnostic_id


def _records(payload: dict[str, object], key: str) -> list[dict[str, object]]:
    """Narrow one mutable record list in a JSON fixture.

    @param payload JSON-ready model
    @param key root record-array field
    @return mutable record list
    """
    value = payload[key]
    assert isinstance(value, list)
    assert all(isinstance(item, dict) for item in value)
    return value  # type: ignore[return-value]


def test_complete_operational_model_is_accepted(tmp_path: Path) -> None:
    """Explicit empty capability activation still carries universal operations.

    @param tmp_path fixture repository
    """
    check, source = _tree(tmp_path)
    assert check.run([source]) == []


def test_active_capability_requires_exactly_one_record(tmp_path: Path) -> None:
    """A true manifest fact cannot disappear from operational evidence.

    @param tmp_path fixture repository
    """
    active = (project.Capability.PUBLIC_API,)
    check, source = _tree(tmp_path, active=active, payload=operational_payload())
    assert _diagnostic(check, source) == "OPMODEL002_CAPABILITY_JOIN"


def test_resource_and_recovery_ids_join_architecture(tmp_path: Path) -> None:
    """Operational ownership cannot cite a stale architecture identity.

    @param tmp_path fixture repository
    """
    active = (project.Capability.FILESYSTEM_IO,)
    payload = operational_payload(active)
    record = _records(payload, "capability_obligations")[0]
    record["resources"] = ["missing_resource"]
    record["resource_absence"] = None
    check, source = _tree(tmp_path, active=active, payload=payload)
    assert _diagnostic(check, source) == "OPMODEL003_OWNERSHIP_JOIN"


def test_activated_interruption_requires_executable_evidence(tmp_path: Path) -> None:
    """Destructive behavior cannot excuse the interruption phase.

    @param tmp_path fixture repository
    """
    active = (project.Capability.DESTRUCTIVE_EFFECTS,)
    payload = operational_payload(active)
    interruption = next(
        item for item in _records(payload, "lifecycle") if item["phase"] == "interruption"
    )
    interruption["test"] = None
    interruption["not_applicable"] = "Interruption is ignored."
    check, source = _tree(tmp_path, active=active, payload=payload)
    assert _diagnostic(check, source) == "OPMODEL004_LIFECYCLE"


def test_safe_and_degraded_states_are_both_required(tmp_path: Path) -> None:
    """A happy state alone leaves failure terminality undefined.

    @param tmp_path fixture repository
    """
    payload = operational_payload()
    _records(payload, "states")[1]["kind"] = "safe"
    check, source = _tree(tmp_path, payload=payload)
    assert _diagnostic(check, source) == "OPMODEL005_STATE_OUTCOME"


def test_non_exception_terminal_outcome_is_observable(tmp_path: Path) -> None:
    """Refusals and dropped work must not vanish behind exception-only telemetry.

    @param tmp_path fixture repository
    """
    payload = operational_payload()
    _records(payload, "outcomes")[0]["exceptional"] = True
    check, source = _tree(tmp_path, payload=payload)
    assert _diagnostic(check, source) == "OPMODEL005_STATE_OUTCOME"


def test_activated_input_surface_requires_a_finite_budget(tmp_path: Path) -> None:
    """A public interface cannot declare accepted input work unbounded by omission.

    @param tmp_path fixture repository
    """
    active = (project.Capability.PUBLIC_API,)
    payload = operational_payload(active)
    budget = next(
        item for item in _records(payload, "budgets") if item["kind"] == "input_size"
    )
    budget["bound"] = None
    budget["measurement"] = None
    budget["not_applicable"] = "All inputs are accepted."
    check, source = _tree(tmp_path, active=active, payload=payload)
    assert _diagnostic(check, source) == "OPMODEL006_BUDGET"


def test_runtime_identity_names_version_and_build(tmp_path: Path) -> None:
    """A version without build identity cannot distinguish two delivered artifacts.

    @param tmp_path fixture repository
    """
    payload = operational_payload()
    identity = payload["identity"]
    assert isinstance(identity, dict)
    identity["runtime_fields"] = ["version"]
    check, source = _tree(tmp_path, payload=payload)
    assert _diagnostic(check, source) == "OPMODEL007_IDENTITY_PLATFORM"


def test_platform_matrix_names_windows_and_linux(tmp_path: Path) -> None:
    """An absent release platform cannot look supported.

    @param tmp_path fixture repository
    """
    payload = operational_payload()
    _records(payload, "platforms").pop()
    check, source = _tree(tmp_path, payload=payload)
    assert _diagnostic(check, source) == "OPMODEL007_IDENTITY_PLATFORM"


def test_generated_capability_obligation_cannot_be_omitted(tmp_path: Path) -> None:
    """Capability activation expands to a closed local evidence set.

    @param tmp_path fixture repository
    """
    active = (project.Capability.NETWORK_IO,)
    payload = operational_payload(active)
    record = _records(payload, "capability_obligations")[0]
    tests = record["tests"]
    assert isinstance(tests, list)
    tests.pop()
    check, source = _tree(tmp_path, active=active, payload=payload)
    assert _diagnostic(check, source) == "OPMODEL008_OBLIGATION"


def test_capability_evidence_cannot_escape_the_repository(tmp_path: Path) -> None:
    """A component cannot satisfy local evidence from a parent or sibling test.

    @param tmp_path fixture repository
    """
    active = (project.Capability.PUBLIC_API,)
    payload = operational_payload(active)
    record = _records(payload, "capability_obligations")[0]
    tests = record["tests"]
    assert isinstance(tests, list)
    evidence = tests[0]
    assert isinstance(evidence, dict)
    evidence["evidence"] = "../peer/tests/test_api.py::test_surface"
    check, source = _tree(tmp_path, active=active, payload=payload)
    assert _diagnostic(check, source) == "OPMODEL008_OBLIGATION"
