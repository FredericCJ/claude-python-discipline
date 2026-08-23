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

# Import model types only while static analyzers evaluate registry contracts.
if TYPE_CHECKING:
    from discipline_core import Rule
    from evidence_model import EvidenceRegistry, ObservationRegistry

## Repository containing this suite when no discrimination fixture overrides it.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent.parent
## The same override used by the other mutable fitness fixtures.
REFERENCE_VARIABLE: Final = "DISCIPLINE_REFERENCE"
## Unordered execution-outcome string elements forbidden from build-time views.
GATE_OUTCOMES: Final = frozenset({"pass", "fail", "not-applicable", "unsupported", "not-run"})


def subject_root() -> Path:
    """Return the live repository or the damaged discrimination fixture.

    @return repository whose evidence contract is under test
    """
    # Resolve a discrimination override before falling back to the live repository.
    named = os.environ.get(REFERENCE_VARIABLE)
    # Return the explicit absolute fixture root or the canonical repository root.
    return Path(named).resolve() if named else REPO_ROOT


def evidence(root: Path) -> EvidenceRegistry:
    """Load one subject's rule evidence.

    @param root repository being tested
    @return parsed evidence registry
    """
    # Parse the strict authored evidence registry at its canonical subject path.
    return load_evidence(root / "discipline" / "meta" / "evidence.json")


def declared_witnesses(registry: EvidenceRegistry) -> frozenset[tuple[str, str]]:
    """Return exact pairs for checks unrelated to matrix execution.

    @param registry evidence whose other invariants are under test
    @return unordered rule-id and mechanism-pair elements for automated strategies
    """
    # Collapse all automated strategy declarations to unique exact witness pairs.
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
    # Parse the strict authored field-observation registry at its canonical path.
    return load_observations(root / "discipline" / "meta" / "observations.json")


def rules(root: Path) -> list[Rule]:
    """Load every normative rule from one subject.

    @param root repository being tested
    @return rule elements in document and authored rule order
    """
    # Flatten document rule elements while preserving corpus traversal and source order.
    return [rule for document in iter_documents(root / "discipline") for rule in document.rules]


def generated_rules(root: Path) -> list[dict[str, object]]:
    """Read the generated lossless projection.

    @param root repository being tested
    @return JSON-shaped rule-record mapping elements in generated corpus order
    """
    # Decode the generated top-level JSON value without assuming its shape.
    payload: object = json.loads((root / "discipline" / "rules.json").read_text(encoding="utf-8"))
    # Establish the mapping root before retrieving the rules field.
    assert isinstance(payload, dict)
    # Extract the generated rule-record sequence from its public field.
    records = payload.get("rules")
    # Require an ordered list before validating each record element.
    assert isinstance(records, list)
    # Require every generated rule element to remain a JSON object mapping.
    assert all(isinstance(record, dict) for record in records)
    # Return the validated record list in generated corpus order.
    return records


@decides("EVID-001")
def test_evidence_registry_joins_rules() -> None:
    """EVID-001: the normative and evidence ID sets are identical."""
    # Load the selected subject and validate its complete normative/evidence join.
    root = subject_root()
    registry = evidence(root)
    findings = validate_evidence(registry, rules(root), declared_witnesses(registry))
    # Reject only missing or orphan evidence-record findings for this focused claim.
    assert not [finding for finding in findings if finding.code in {"E001", "E002"}]


@decides("EVID-002")
def test_strategy_claims_are_explicit() -> None:
    """EVID-002: heading mechanisms and complete strategy records agree."""
    # Load the selected subject and validate its complete strategy structure.
    root = subject_root()
    registry = evidence(root)
    findings = validate_evidence(registry, rules(root), declared_witnesses(registry))
    # Hold unordered structural finding-code string elements owned by this claim.
    structural = {"E003", "E004", "E008", "E010", "E012", "E013"}
    # Reject every finding whose code belongs to strategy completeness or joining.
    assert not [finding for finding in findings if finding.code in structural]


@decides("EVID-003")
def test_proxy_claims_preserve_residuals() -> None:
    """EVID-003: the generated projection does not erase proxy limitations."""
    # Load authored evidence and index generated records by unordered rule-id keys.
    root = subject_root()
    authored = evidence(root).rules
    # Map rule-id keys to generated record values; mapping order is insignificant.
    projected = {str(record["id"]): record for record in generated_rules(root)}
    # Compare each authored rule-id key and evidence record in registry order.
    for rule_id, record in authored.items():
        # Extract and validate the generated verification object for this rule.
        verification = projected[rule_id].get("verification")
        assert isinstance(verification, dict)
        # Extract and validate ordered generated strategy-record elements.
        strategies = verification.get("strategies")
        assert isinstance(strategies, list)
        # Count authored mechanism, relation, and residual tuple keys without order.
        expected = Counter(
            (strategy.mechanism, str(strategy.relation), strategy.residual)
            for strategy in record.strategies
        )
        # Count generated mechanism, relation, and residual tuple keys without order.
        actual = Counter(
            (
                str(strategy.get("mechanism")),
                str(strategy.get("relation")),
                str(strategy.get("residual")),
            )
            for strategy in strategies
            if isinstance(strategy, dict)
        )
        # Require the generated view to preserve every authored residual exactly.
        assert actual == expected, rule_id


@decides("EVID-004")
def test_rejection_credit_is_witnessed() -> None:
    """EVID-004: only exact strategies in the matrix claim rejection credit."""
    # Load exact matrix witnesses for the selected live or damaged repository.
    root = subject_root()
    witnessed = discrimination_witnesses(root)
    # Reject an absent or structurally malformed discrimination declaration.
    assert witnessed is not None, "the discrimination matrix is absent or malformed"
    # Collect unordered rule-id and mechanism-pair elements claiming matrix credit.
    credited = {
        (rule_id, strategy.mechanism)
        for rule_id, record in evidence(root).rules.items()
        for strategy in record.strategies
        if (strategy.must_reject or "").startswith("discrimination:")
    }
    # Derive unordered credited-pair elements absent from the executable witness set.
    missing = credited - witnessed
    # Reject false credit with a deterministic sorted pair report.
    assert not missing, sorted(missing)


@decides("EVID-005")
def test_generated_rules_publish_no_gate_outcome() -> None:
    """EVID-005: build-time data contains states, never execution verdicts."""
    # Hold unordered verdict-field-name elements forbidden from generated contracts.
    forbidden_keys = {"outcome", "gate_outcome", "result"}
    # Collapse declared verifier-availability state string elements to an unordered set.
    states = {str(state) for state in VerificationState}
    # Inspect generated rule-record elements in stable corpus order.
    for record in generated_rules(subject_root()):
        # Reject execution verdict fields at the rule-record level.
        assert forbidden_keys.isdisjoint(record)
        # Extract and validate the generated verification mapping.
        verification = record.get("verification")
        assert isinstance(verification, dict)
        # Reject execution verdict fields inside verifier-availability metadata.
        assert forbidden_keys.isdisjoint(verification)
        # Resolve the published state for membership comparisons.
        state = verification.get("state")
        # Require a declared availability state and forbid every gate outcome value.
        assert state in states
        assert state not in GATE_OUTCOMES


@decides("EVID-006")
def test_warrants_are_typed() -> None:
    """EVID-006: every rule carries at least one relation-qualified warrant."""
    # Inspect each rule-id key and evidence record in registry declaration order.
    for rule_id, record in evidence(subject_root()).rules.items():
        # Require a non-empty warrant sequence and source identity on every element.
        assert record.warrants, rule_id
        assert all(warrant.source for warrant in record.warrants), rule_id


@decides("EVID-007")
def test_field_observations_resolve() -> None:
    """EVID-007: cited observations resolve and manual evidence stays labeled."""
    # Load available observation-id keys and observation-record values for the subject.
    root = subject_root()
    available = observations(root).observations
    # Verify each rule's cited observation IDs against unordered available key membership.
    for rule_id, record in evidence(root).rules.items():
        # Reject unresolved citations while preserving the governing rule in diagnostics.
        assert set(record.observations) <= set(available), rule_id
    # Inspect each observation-id key and record in registry declaration order.
    for observation_id, observation in available.items():
        # Restrict manual classification to records with no executable reproduction.
        if observation.reproduction is None:
            # Require the explicit manual-synthesis label on non-reproducible evidence.
            assert observation.evidence_kind is ObservationKind.MANUAL_SYNTHESIS, observation_id


@decides("EVID-008")
def test_rule_migrations_are_total() -> None:
    """EVID-008: historical dispositions and successor headings agree."""
    # Load the selected registry and validate all historical migration relationships.
    root = subject_root()
    registry = evidence(root)
    findings = validate_evidence(registry, rules(root), declared_witnesses(registry))
    # Hold unordered historical finding-code string elements owned by this claim.
    historical = {"E005", "E006", "E007"}
    # Reject inconsistent retirement, successor, or disposition findings.
    assert not [finding for finding in findings if finding.code in historical]
    # Require every migration record to carry a typed disposition and guidance.
    assert all(
        isinstance(record.migration.disposition, MigrationDisposition) and record.migration.guidance
        for record in registry.rules.values()
    )
