"""Fitness tests for the v4 claim and verification-evidence contract.

These tests inspect the authored registries and their generated projection. They
do not decide whether a normative rule is beneficial, nor whether a project gate
passed. Their deliberately narrower job is to keep those claims distinguishable.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Final

from decides import decides
from discipline_core import iter_documents
from evidence_model import (
    MigrationDisposition,
    ObservationKind,
    VerificationState,
    discrimination_witnesses,
    load_evidence,
    load_observations,
    validate_evidence,
)

if TYPE_CHECKING:
    from discipline_core import Rule
    from evidence_model import EvidenceRegistry, ObservationRegistry

## Repository containing this suite when no discrimination fixture overrides it.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent.parent
## The same override used by the other mutable fitness fixtures.
REFERENCE_VARIABLE: Final = "DISCIPLINE_REFERENCE"
## Execution outcomes forbidden from a build-time verifier-availability view.
GATE_OUTCOMES: Final = frozenset({"pass", "fail", "not-applicable", "unsupported", "not-run"})


def subject_root() -> Path:
    """Return the live repository or the damaged discrimination fixture.

    @return repository whose evidence contract is under test
    """
    named = os.environ.get(REFERENCE_VARIABLE)
    return Path(named).resolve() if named else REPO_ROOT


def evidence(root: Path) -> EvidenceRegistry:
    """Load one subject's rule evidence.

    @param root repository being tested
    @return parsed evidence registry
    """
    return load_evidence(root / "discipline" / "meta" / "evidence.json")


def declared_witnesses(registry: EvidenceRegistry) -> frozenset[tuple[str, str]]:
    """Return exact pairs for checks unrelated to matrix execution.

    @param registry evidence whose other invariants are under test
    @return every declared automated strategy pair
    """
    return frozenset(
        (rule_id, strategy.mechanism)
        for rule_id, record in registry.rules.items()
        for strategy in record.strategies
        if strategy.is_automated
    )


def observations(root: Path) -> ObservationRegistry:
    """Load one subject's field observations.

    @param root repository being tested
    @return parsed observation registry
    """
    return load_observations(root / "discipline" / "meta" / "observations.json")


def rules(root: Path) -> list[Rule]:
    """Load every normative rule from one subject.

    @param root repository being tested
    @return flattened authored rules
    """
    return [rule for document in iter_documents(root / "discipline") for rule in document.rules]


def generated_rules(root: Path) -> list[dict[str, object]]:
    """Read the generated lossless projection.

    @param root repository being tested
    @return JSON-shaped rule records
    """
    payload: object = json.loads((root / "discipline" / "rules.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    records = payload.get("rules")
    assert isinstance(records, list)
    assert all(isinstance(record, dict) for record in records)
    return records


@decides("EVID-001")
def test_evidence_registry_joins_rules() -> None:
    """EVID-001: the normative and evidence ID sets are identical."""
    root = subject_root()
    registry = evidence(root)
    findings = validate_evidence(registry, rules(root), declared_witnesses(registry))
    assert not [finding for finding in findings if finding.code in {"E001", "E002"}]


@decides("EVID-002")
def test_strategy_claims_are_explicit() -> None:
    """EVID-002: heading mechanisms and complete strategy records agree."""
    root = subject_root()
    registry = evidence(root)
    findings = validate_evidence(registry, rules(root), declared_witnesses(registry))
    structural = {"E003", "E004", "E008", "E010", "E012", "E013"}
    assert not [finding for finding in findings if finding.code in structural]


@decides("EVID-003")
def test_proxy_claims_preserve_residuals() -> None:
    """EVID-003: the generated projection does not erase proxy limitations."""
    root = subject_root()
    authored = evidence(root).rules
    projected = {str(record["id"]): record for record in generated_rules(root)}
    for rule_id, record in authored.items():
        verification = projected[rule_id].get("verification")
        assert isinstance(verification, dict)
        strategies = verification.get("strategies")
        assert isinstance(strategies, list)
        expected = Counter(
            (strategy.mechanism, str(strategy.relation), strategy.residual)
            for strategy in record.strategies
        )
        actual = Counter(
            (
                str(strategy.get("mechanism")),
                str(strategy.get("relation")),
                str(strategy.get("residual")),
            )
            for strategy in strategies
            if isinstance(strategy, dict)
        )
        assert actual == expected, rule_id


@decides("EVID-004")
def test_rejection_credit_is_witnessed() -> None:
    """EVID-004: only exact strategies in the matrix claim rejection credit."""
    root = subject_root()
    witnessed = discrimination_witnesses(root)
    assert witnessed is not None, "the discrimination matrix is absent or malformed"
    credited = {
        (rule_id, strategy.mechanism)
        for rule_id, record in evidence(root).rules.items()
        for strategy in record.strategies
        if (strategy.must_reject or "").startswith("discrimination:")
    }
    missing = credited - witnessed
    assert not missing, sorted(missing)


@decides("EVID-005")
def test_generated_rules_publish_no_gate_outcome() -> None:
    """EVID-005: build-time data contains states, never execution verdicts."""
    forbidden_keys = {"outcome", "gate_outcome", "result"}
    states = {str(state) for state in VerificationState}
    for record in generated_rules(subject_root()):
        assert forbidden_keys.isdisjoint(record)
        verification = record.get("verification")
        assert isinstance(verification, dict)
        assert forbidden_keys.isdisjoint(verification)
        state = verification.get("state")
        assert state in states
        assert state not in GATE_OUTCOMES


@decides("EVID-006")
def test_warrants_are_typed() -> None:
    """EVID-006: every rule carries at least one relation-qualified warrant."""
    for rule_id, record in evidence(subject_root()).rules.items():
        assert record.warrants, rule_id
        assert all(warrant.source for warrant in record.warrants), rule_id


@decides("EVID-007")
def test_field_observations_resolve() -> None:
    """EVID-007: cited observations resolve and manual evidence stays labeled."""
    root = subject_root()
    available = observations(root).observations
    for rule_id, record in evidence(root).rules.items():
        assert set(record.observations) <= set(available), rule_id
    for observation_id, observation in available.items():
        if observation.reproduction is None:
            assert observation.evidence_kind is ObservationKind.MANUAL_SYNTHESIS, observation_id


@decides("EVID-008")
def test_rule_migrations_are_total() -> None:
    """EVID-008: historical dispositions and successor headings agree."""
    root = subject_root()
    registry = evidence(root)
    findings = validate_evidence(registry, rules(root), declared_witnesses(registry))
    historical = {"E005", "E006", "E007"}
    assert not [finding for finding in findings if finding.code in historical]
    assert all(
        isinstance(record.migration.disposition, MigrationDisposition) and record.migration.guidance
        for record in registry.rules.values()
    )
