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
    discrimination_witnesses,
    load_evidence,
    load_observations,
    validate_evidence,
    verification_state,
)


def valid_payload() -> dict[str, object]:
    """Return one complete direct-verification record.

    @return mutable JSON-shaped test data
    """
    # Return mutable JSON-shaped test data to the caller.
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
                        "must_reject": "discrimination:TYPE-001/auto:mypy",
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
        Treat payload as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @return destination

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    path.write_text(json.dumps(payload), encoding="utf-8")
    # Return destination to the caller.
    return path


def strategy(payload: dict[str, object]) -> dict[str, object]:
    """Reach the sole strategy while retaining a checked type.

    @param payload valid test registry
        Treat payload as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @return mutable strategy mapping
    """
    # Compute rules using payload["rules"] for later strategy logic.
    rules = payload["rules"]
    assert isinstance(rules, dict)
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    record = rules["TYPE-001"]
    assert isinstance(record, dict)
    # Compute strategies using record["strategies"] for later strategy logic.
    strategies = record["strategies"]
    assert isinstance(strategies, list)
    # Preserve the optional pattern match that carries the reported analysis count.
    found = strategies[0]
    assert isinstance(found, dict)
    # Return mutable strategy mapping to the caller.
    return found


def record(payload: dict[str, object]) -> dict[str, object]:
    """Reach the sole evidence record while retaining a checked type.

    @param payload valid test registry
        Treat payload as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @return mutable evidence mapping
    """
    # Compute rules using payload["rules"] for later record logic.
    rules = payload["rules"]
    assert isinstance(rules, dict)
    # Preserve the optional pattern match that carries the reported analysis count.
    found = rules["TYPE-001"]
    assert isinstance(found, dict)
    # Return mutable evidence mapping to the caller.
    return found


def rule(
    *,
    mechanisms: tuple[str, ...] = ("auto:mypy",),
    superseded_by: str | None = None,
    force: Force = Force.BINDING,
) -> Rule:
    """Build the normative half of a joined test record.

    @param mechanisms heading mechanisms
        Each mechanisms element carries one mechanism value produced or consumed by this
        operation; construction order is preserved.
    @param superseded_by replacement id for a retired fixture
    @param force normative or historical force tag
    @return normative rule
    """
    # Return normative rule to the caller.
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
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    payload = valid_payload()
    # Carry out this operation at its documented position in the semantic sequence.
    del record(payload)[field]
    # Confine the acquired resource to this operation and release it on every exit.
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
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    payload = valid_payload()
    # Carry out this operation at its documented position in the semantic sequence.
    del strategy(payload)[field]
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(EvidenceParseError, match=field):
        load_evidence(write_payload(tmp_path / "evidence.json", payload))


def test_unknown_fields_are_rejected(tmp_path: Path) -> None:
    """A misspelled field cannot disappear silently."""
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    payload = valid_payload()
    # Update test unknown fields are rejected state only after the required source facts are
    # Details: available.
    strategy(payload)["residue"] = "misspelled"
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(EvidenceParseError, match="unknown residue"):
        load_evidence(write_payload(tmp_path / "evidence.json", payload))


def test_field_observations_are_typed_and_reproducible(tmp_path: Path) -> None:
    """An observation ID resolves to a bounded claim and named evidence location."""
    # Treat payload as mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
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
    # Derive registry from load observations for the next test field observations are typed and
    # Details: reproducible decision.
    registry = load_observations(write_payload(tmp_path / "observations.json", payload))
    assert registry.observations["V4E-001"].evidence_kind is ObservationKind.REPRODUCED


def test_field_observation_requires_a_location(tmp_path: Path) -> None:
    """An unlocated anecdote cannot satisfy a field-evidence reference."""
    # Treat payload as mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
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
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(EvidenceParseError, match="at least one evidence location"):
        load_observations(write_payload(tmp_path / "observations.json", payload))


def test_capabilities_use_configuration_key_grammar(tmp_path: Path) -> None:
    """Capability names are valid TOML-style identifiers before activation exists."""
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    payload = valid_payload()
    # Update test capabilities use configuration key grammar state only after the required
    # Details: source facts are available.
    record(payload)["capabilities"] = ["Network I/O"]
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(EvidenceParseError, match="invalid name"):
        load_evidence(write_payload(tmp_path / "evidence.json", payload))


def test_heading_and_strategy_mechanisms_must_match(tmp_path: Path) -> None:
    """Evidence cannot describe a verifier the normative heading does not name."""
    # Derive registry from load evidence for the next test heading and strategy mechanisms must
    # Details: match decision.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", valid_payload()))
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = validate_evidence(
        registry,
        [rule(mechanisms=("auto:pyright",))],
        {("TYPE-001", "auto:mypy")},
    )
    # Select finding as the current element from findings] == ["E004"] while test heading and
    # Details: strategy mechanisms must match preserves traversal order.
    assert [finding.code for finding in findings] == ["E004"]


def test_automated_strategy_needs_a_must_reject_case(tmp_path: Path) -> None:
    """A positive reference alone cannot demonstrate discrimination."""
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    payload = valid_payload()
    # Update test automated strategy needs a must reject case state only after the required
    # Details: source facts are available.
    strategy(payload)["must_reject"] = None
    # Derive registry from load evidence for the next test automated strategy needs a must
    # Details: reject case decision.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = validate_evidence(registry, [rule()], {("TYPE-001", "auto:mypy")})
    # Select finding as the current element from findings} while test automated strategy needs a
    # Details: must reject case preserves traversal order.
    assert "E008" in {finding.code for finding in findings}


def test_declared_mutation_must_have_been_witnessed(tmp_path: Path) -> None:
    """A must-reject label without an executed matrix entry receives no credit."""
    # Derive registry from load evidence for the next test declared mutation must have been
    # Details: witnessed decision.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", valid_payload()))
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = validate_evidence(registry, [rule()], set())
    # Select finding as the current element from findings} while test declared mutation must
    # Details: have been witnessed preserves traversal order.
    assert "E009" in {finding.code for finding in findings}


def test_must_reject_names_the_exact_rule_and_mechanism(tmp_path: Path) -> None:
    """A legacy rule-only label cannot identify which verifier rejected it."""
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    payload = valid_payload()
    # Update test must reject names the exact rule and mechanism state only after the required
    # Details: source facts are available.
    strategy(payload)["must_reject"] = "discrimination:TYPE-001"
    # Derive registry from load evidence for the next test must reject names the exact rule and
    # Details: mechanism decision.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))

    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = validate_evidence(
        registry,
        [rule()],
        {("TYPE-001", "auto:mypy")},
    )

    # Select finding as the current element from findings} while test must reject names the
    # Details: exact rule and mechanism preserves traversal order.
    assert "E012" in {finding.code for finding in findings}


def test_generated_placeholder_is_not_an_observable_proposition(tmp_path: Path) -> None:
    """Evidence must state the finite condition, not merely name a checker."""
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    payload = valid_payload()
    # Update test generated placeholder is not an observable proposition state only after the
    # Details: required source facts are available.
    strategy(payload)["proposition"] = (
        "auto:mypy reports no diagnostic corresponding to TYPE-001 under config."
    )
    # Derive registry from load evidence for the next test generated placeholder is not an
    # Details: observable proposition decision.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))

    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = validate_evidence(
        registry,
        [rule()],
        {("TYPE-001", "auto:mypy")},
    )

    # Select finding as the current element from findings} while test generated placeholder is
    # Details: not an observable proposition preserves traversal order.
    assert "E013" in {finding.code for finding in findings}


def test_rule_only_matrix_cannot_supply_v4_rejection_credit(tmp_path: Path) -> None:
    """The v3 coverage view cannot conceal an unwitnessed second mechanism.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Derive matrix from tmp_path / "enforce" / "discrimination.py" for the next test rule only
    # Details: matrix cannot supply v4 rejection credit decision.
    matrix = tmp_path / "enforce" / "discrimination.py"
    # Publish the externally visible effect after all required inputs are ready.
    matrix.parent.mkdir(parents=True)
    # Publish the externally visible effect after all required inputs are ready.
    matrix.write_text(
        '"""Legacy matrix."""\n\n\n'
        "def covered() -> frozenset[str]:\n"
        '    """Return a rule-only claim.\n\n    @return ids\n    """\n'
        '    return frozenset({"TYPE-001"})\n',
        encoding="utf-8",
    )

    assert discrimination_witnesses(tmp_path) is None


def test_one_tool_cannot_lend_rejection_credit_to_another(tmp_path: Path) -> None:
    """Exact strategy pairs prevent a shared rule id from masking a gap."""
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    payload = valid_payload()
    # Derive pyright from deepcopy for the next test one tool cannot lend rejection credit to
    # Details: another decision.
    pyright = deepcopy(strategy(payload))
    # Update test one tool cannot lend rejection credit to another state only after the required
    # Details: source facts are available.
    pyright["mechanism"] = "auto:pyright"
    # Derive strategies from record for the next test one tool cannot lend rejection credit to
    # Details: another decision.
    strategies = record(payload)["strategies"]
    assert isinstance(strategies, list)
    strategies.append(pyright)
    # Derive registry from load evidence for the next test one tool cannot lend rejection credit
    # Details: to another decision.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = validate_evidence(
        registry,
        [rule(mechanisms=("auto:mypy", "auto:pyright"))],
        {("TYPE-001", "auto:mypy")},
    )
    # Select finding as the current element from findings if finding.code == "E009"] == [ while
    # Details: test one tool cannot lend rejection credit to another preserves traversal order.
    assert [finding.message for finding in findings if finding.code == "E009"] == [
        "auto:pyright is not witnessed rejecting"
    ]


def test_tag_and_kind_cannot_disagree(tmp_path: Path) -> None:
    """An external-tool tag cannot be presented as a local static check."""
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    payload = valid_payload()
    # Update test tag and kind cannot disagree state only after the required source facts are
    # Details: available.
    strategy(payload)["kind"] = "static"
    # Derive registry from load evidence for the next test tag and kind cannot disagree
    # Details: decision.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = validate_evidence(registry, [rule()], {("TYPE-001", "auto:mypy")})
    # Select finding as the current element from findings} while test tag and kind cannot
    # Details: disagree preserves traversal order.
    assert "E010" in {finding.code for finding in findings}


def test_retirement_preserves_the_id_and_removes_strategies(tmp_path: Path) -> None:
    """A superseded heading remains resolvable but cannot look actively verified."""
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    payload = deepcopy(valid_payload())
    # Update test retirement preserves the id and removes strategies state only after the
    # Details: required source facts are available.
    record(payload)["strategies"] = []
    # Derive migration from record for the next test retirement preserves the id and removes
    # Details: strategies decision.
    migration = record(payload)["migration"]
    assert isinstance(migration, dict)
    # Update test retirement preserves the id and removes strategies state only after the
    # Details: required source facts are available.
    migration["disposition"] = MigrationDisposition.SUPERSEDED
    # Derive registry from load evidence for the next test retirement preserves the id and
    # Details: removes strategies decision.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))
    # Derive retired from rule for the next test retirement preserves the id and removes
    # Details: strategies decision.
    retired = rule(mechanisms=(), superseded_by="TYPE-002", force=Force.RETIRED)
    assert validate_evidence(registry, [retired], set()) == []
    assert verification_state(retired, registry.rules["TYPE-001"]) is VerificationState.RETIRED


def test_withdrawal_without_a_replacement_is_representable(tmp_path: Path) -> None:
    """A rule can leave scope without inventing a successor that does not exist."""
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    payload = deepcopy(valid_payload())
    # Update test withdrawal without a replacement is representable state only after the
    # Details: required source facts are available.
    record(payload)["strategies"] = []
    # Derive migration from record for the next test withdrawal without a replacement is
    # Details: representable decision.
    migration = record(payload)["migration"]
    assert isinstance(migration, dict)
    # Update test withdrawal without a replacement is representable state only after the
    # Details: required source facts are available.
    migration["disposition"] = MigrationDisposition.RETIRED
    # Derive registry from load evidence for the next test withdrawal without a replacement is
    # Details: representable decision.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))
    # Derive withdrawn from rule for the next test withdrawal without a replacement is
    # Details: representable decision.
    withdrawn = rule(mechanisms=(), force=Force.RETIRED)
    assert validate_evidence(registry, [withdrawn], set()) == []
    assert verification_state(withdrawn, registry.rules["TYPE-001"]) is VerificationState.RETIRED


def test_replacement_disposition_requires_a_successor(tmp_path: Path) -> None:
    """Superseded cannot mean retired-without-replacement by implication."""
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    payload = deepcopy(valid_payload())
    # Update test replacement disposition requires a successor state only after the required
    # Details: source facts are available.
    record(payload)["strategies"] = []
    # Derive migration from record for the next test replacement disposition requires a
    # Details: successor decision.
    migration = record(payload)["migration"]
    assert isinstance(migration, dict)
    # Update test replacement disposition requires a successor state only after the required
    # Details: source facts are available.
    migration["disposition"] = MigrationDisposition.SUPERSEDED
    # Derive registry from load evidence for the next test replacement disposition requires a
    # Details: successor decision.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = validate_evidence(registry, [rule(mechanisms=(), force=Force.RETIRED)], set())
    # Select finding as the current element from findings] == ["E007"] while test replacement
    # Details: disposition requires a successor preserves traversal order.
    assert [finding.code for finding in findings] == ["E007"]


def test_verification_state_says_what_exists_not_that_it_passed(tmp_path: Path) -> None:
    """An external strategy is a verifier declaration, never a synthetic pass."""
    # Derive registry from load evidence for the next test verification state says what exists
    # Details: not that it passed decision.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", valid_payload()))
    assert (
        verification_state(rule(), registry.rules["TYPE-001"], tmp_path)
        is VerificationState.EXTERNAL_VERIFIER
    )
