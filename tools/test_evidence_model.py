"""Proof-of-failure tests for the v4 rule-evidence model."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from discipline_core import Force, Rule
from evidence_model import (
    EvidenceParseError,
    MigrationDisposition,
    ObservationKind,
    VerificationState,
    load_evidence,
    load_observations,
    validate_evidence,
    verification_state,
)


def valid_payload() -> dict[str, object]:
    """Return one complete direct-verification record.

    @return mutable JSON-shaped test data
    """
    return {
        "schema_version": 1,
        "rules": {
            "TYPE-001": {
                "units": ["application", "component"],
                "capabilities": [],
                "failure_mode": "An unchecked value crosses the typed core.",
                "warrants": [
                    {
                        "source": "sources/nodes/python-typing-contract.md",
                        "relation": "supports",
                        "confidence": "high",
                    }
                ],
                "strategies": [
                    {
                        "mechanism": "auto:mypy",
                        "kind": "tool",
                        "relation": "direct",
                        "proposition": (
                            "mypy reports no implicit Any in the configured source roots."
                        ),
                        "residual": "The checker cannot establish runtime input validity.",
                        "must_pass": "enforce/fixtures/reference",
                        "must_reject": "discrimination:TYPE-001",
                        "platforms": ["windows", "linux"],
                        "not_applicable": "never",
                    }
                ],
                "observations": [],
                "migration": {
                    "source": "v3.3.0",
                    "disposition": "clarified",
                    "guidance": "No project edit; the observable claim is now explicit.",
                },
            }
        },
    }


def write_payload(path: Path, payload: dict[str, object]) -> Path:
    """Write test JSON to a path.

    @param path destination
    @param payload JSON-shaped content
    @return destination
    """
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def strategy(payload: dict[str, object]) -> dict[str, object]:
    """Reach the sole strategy while retaining a checked type.

    @param payload valid test registry
    @return mutable strategy mapping
    """
    rules = payload["rules"]
    assert isinstance(rules, dict)
    record = rules["TYPE-001"]
    assert isinstance(record, dict)
    strategies = record["strategies"]
    assert isinstance(strategies, list)
    found = strategies[0]
    assert isinstance(found, dict)
    return found


def record(payload: dict[str, object]) -> dict[str, object]:
    """Reach the sole evidence record while retaining a checked type.

    @param payload valid test registry
    @return mutable evidence mapping
    """
    rules = payload["rules"]
    assert isinstance(rules, dict)
    found = rules["TYPE-001"]
    assert isinstance(found, dict)
    return found


def rule(
    *,
    mechanisms: tuple[str, ...] = ("auto:mypy",),
    superseded_by: str | None = None,
    force: Force = Force.BINDING,
) -> Rule:
    """Build the normative half of a joined test record.

    @param mechanisms heading mechanisms
    @param superseded_by replacement id for a retired fixture
    @param force normative or historical force tag
    @return normative rule
    """
    return Rule(
        rule_id="TYPE-001",
        module_id="law/TYPE",
        title="Keep the core typed",
        force=force,
        mechanisms=mechanisms,
        statement="The core MUST remain typed.",
        why="Unchecked values hide defects.",
        check="mypy --strict",
        see=(),
        no_mechanism=None,
        superseded_by=superseded_by,
        path=Path("discipline/law/TYPE.md"),
        line=10,
    )


@pytest.mark.parametrize(
    "field",
    [
        "units",
        "capabilities",
        "failure_mode",
        "warrants",
        "strategies",
        "observations",
        "migration",
    ],
)
def test_every_rule_field_is_required(tmp_path: Path, field: str) -> None:
    """Deleting any evidence layer field makes the registry invalid."""
    payload = valid_payload()
    del record(payload)[field]
    with pytest.raises(EvidenceParseError, match=field):
        load_evidence(write_payload(tmp_path / "evidence.json", payload))


@pytest.mark.parametrize(
    "field",
    [
        "mechanism",
        "kind",
        "relation",
        "proposition",
        "residual",
        "must_pass",
        "must_reject",
        "platforms",
        "not_applicable",
    ],
)
def test_every_strategy_field_is_required(tmp_path: Path, field: str) -> None:
    """Deleting any decidable-layer field makes the registry invalid."""
    payload = valid_payload()
    del strategy(payload)[field]
    with pytest.raises(EvidenceParseError, match=field):
        load_evidence(write_payload(tmp_path / "evidence.json", payload))


def test_unknown_fields_are_rejected(tmp_path: Path) -> None:
    """A misspelled field cannot disappear silently."""
    payload = valid_payload()
    strategy(payload)["residue"] = "misspelled"
    with pytest.raises(EvidenceParseError, match="unknown residue"):
        load_evidence(write_payload(tmp_path / "evidence.json", payload))


def test_field_observations_are_typed_and_reproducible(tmp_path: Path) -> None:
    """An observation ID resolves to a bounded claim and named evidence location."""
    payload = {
        "schema_version": 1,
        "observations": {
            "V4E-001": {
                "classification": "mechanism_defect",
                "claim": "The configured scan root was ignored.",
                "evidence_kind": "reproduced",
                "observed_in": ["adopter at abc123"],
                "reproduction": "Run the declared gate from the adopter root.",
                "scope": "one adopter repository",
                "source": "audit/A-001",
            }
        },
    }
    registry = load_observations(write_payload(tmp_path / "observations.json", payload))
    assert registry.observations["V4E-001"].evidence_kind is ObservationKind.REPRODUCED


def test_field_observation_requires_a_location(tmp_path: Path) -> None:
    """An unlocated anecdote cannot satisfy a field-evidence reference."""
    payload = {
        "schema_version": 1,
        "observations": {
            "V4E-001": {
                "classification": "mechanism_defect",
                "claim": "The configured scan root was ignored.",
                "evidence_kind": "observed",
                "observed_in": [],
                "reproduction": None,
                "scope": "one adopter repository",
                "source": "audit/A-001",
            }
        },
    }
    with pytest.raises(EvidenceParseError, match="at least one evidence location"):
        load_observations(write_payload(tmp_path / "observations.json", payload))


def test_capabilities_use_configuration_key_grammar(tmp_path: Path) -> None:
    """Capability names are valid TOML-style identifiers before activation exists."""
    payload = valid_payload()
    record(payload)["capabilities"] = ["Network I/O"]
    with pytest.raises(EvidenceParseError, match="invalid name"):
        load_evidence(write_payload(tmp_path / "evidence.json", payload))


def test_heading_and_strategy_mechanisms_must_match(tmp_path: Path) -> None:
    """Evidence cannot describe a verifier the normative heading does not name."""
    registry = load_evidence(write_payload(tmp_path / "evidence.json", valid_payload()))
    findings = validate_evidence(registry, [rule(mechanisms=("auto:pyright",))], {"TYPE-001"})
    assert [finding.code for finding in findings] == ["E004"]


def test_automated_strategy_needs_a_must_reject_case(tmp_path: Path) -> None:
    """A positive reference alone cannot demonstrate discrimination."""
    payload = valid_payload()
    strategy(payload)["must_reject"] = None
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))
    findings = validate_evidence(registry, [rule()], {"TYPE-001"})
    assert "E008" in {finding.code for finding in findings}


def test_declared_mutation_must_have_been_witnessed(tmp_path: Path) -> None:
    """A must-reject label without an executed matrix entry receives no credit."""
    registry = load_evidence(write_payload(tmp_path / "evidence.json", valid_payload()))
    findings = validate_evidence(registry, [rule()], set())
    assert "E009" in {finding.code for finding in findings}


def test_tag_and_kind_cannot_disagree(tmp_path: Path) -> None:
    """An external-tool tag cannot be presented as a local static check."""
    payload = valid_payload()
    strategy(payload)["kind"] = "static"
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))
    findings = validate_evidence(registry, [rule()], {"TYPE-001"})
    assert "E010" in {finding.code for finding in findings}


def test_retirement_preserves_the_id_and_removes_strategies(tmp_path: Path) -> None:
    """A superseded heading remains resolvable but cannot look actively verified."""
    payload = deepcopy(valid_payload())
    record(payload)["strategies"] = []
    migration = record(payload)["migration"]
    assert isinstance(migration, dict)
    migration["disposition"] = MigrationDisposition.SUPERSEDED
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))
    retired = rule(mechanisms=(), superseded_by="TYPE-002", force=Force.RETIRED)
    assert validate_evidence(registry, [retired], set()) == []
    assert verification_state(retired, registry.rules["TYPE-001"]) is VerificationState.RETIRED


def test_withdrawal_without_a_replacement_is_representable(tmp_path: Path) -> None:
    """A rule can leave scope without inventing a successor that does not exist."""
    payload = deepcopy(valid_payload())
    record(payload)["strategies"] = []
    migration = record(payload)["migration"]
    assert isinstance(migration, dict)
    migration["disposition"] = MigrationDisposition.RETIRED
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))
    withdrawn = rule(mechanisms=(), force=Force.RETIRED)
    assert validate_evidence(registry, [withdrawn], set()) == []
    assert verification_state(withdrawn, registry.rules["TYPE-001"]) is VerificationState.RETIRED


def test_replacement_disposition_requires_a_successor(tmp_path: Path) -> None:
    """Superseded cannot mean retired-without-replacement by implication."""
    payload = deepcopy(valid_payload())
    record(payload)["strategies"] = []
    migration = record(payload)["migration"]
    assert isinstance(migration, dict)
    migration["disposition"] = MigrationDisposition.SUPERSEDED
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))
    findings = validate_evidence(registry, [rule(mechanisms=(), force=Force.RETIRED)], set())
    assert [finding.code for finding in findings] == ["E007"]


def test_verification_state_says_what_exists_not_that_it_passed(tmp_path: Path) -> None:
    """An external strategy is a verifier declaration, never a synthetic pass."""
    registry = load_evidence(write_payload(tmp_path / "evidence.json", valid_payload()))
    assert (
        verification_state(rule(), registry.rules["TYPE-001"], tmp_path)
        is VerificationState.EXTERNAL_VERIFIER
    )
