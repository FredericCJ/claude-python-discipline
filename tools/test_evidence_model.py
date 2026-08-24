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
    # Return a fresh mutable document so each test can damage one invariant in isolation.
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
    Serializes ``payload`` to ``path`` as UTF-8 JSON.
    """
    # Materialize the mutated JSON document consumed by the structural parser.
    path.write_text(json.dumps(payload), encoding="utf-8")
    # Return the same destination for direct composition with parser calls.
    return path


def strategy(payload: dict[str, object]) -> dict[str, object]:
    """Reach the sole strategy while retaining a checked type.

    @param payload valid test registry
        Treat payload as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @return mutable strategy mapping
    """
    # Narrow the top-level rule registry before selecting its sole fixture record.
    rules = payload["rules"]
    assert isinstance(rules, dict)
    # Select the TYPE-001 evidence object whose strategy the test will mutate.
    record = rules["TYPE-001"]
    assert isinstance(record, dict)
    # Narrow the ordered strategy array before indexing its sole fixture entry.
    strategies = record["strategies"]
    assert isinstance(strategies, list)
    # Select the single strategy while retaining runtime shape validation.
    found = strategies[0]
    assert isinstance(found, dict)
    # Expose the mutable strategy object to one-invariant fixture mutations.
    return found


def record(payload: dict[str, object]) -> dict[str, object]:
    """Reach the sole evidence record while retaining a checked type.

    @param payload valid test registry
        Treat payload as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @return mutable evidence mapping
    """
    # Narrow the top-level rule registry before selecting its sole fixture record.
    rules = payload["rules"]
    assert isinstance(rules, dict)
    # Select the TYPE-001 record while retaining runtime shape validation.
    found = rules["TYPE-001"]
    assert isinstance(found, dict)
    # Expose the mutable evidence object to one-invariant fixture mutations.
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
    # Build a canonical heading whose controlled variations drive semantic join tests.
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
    # Start from a complete rule record so the parameterized deletion is the sole defect.
    payload = valid_payload()
    # Remove exactly the selected required field from the rule evidence object.
    del record(payload)[field]
    # Require the parser to localize the missing field in its structural error.
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
    # Start from a complete strategy so the parameterized deletion is the sole defect.
    payload = valid_payload()
    # Remove exactly the selected required field from the strategy object.
    del strategy(payload)[field]
    # Require the parser to localize the missing strategy field.
    with pytest.raises(EvidenceParseError, match=field):
        load_evidence(write_payload(tmp_path / "evidence.json", payload))


def test_unknown_fields_are_rejected(tmp_path: Path) -> None:
    """A misspelled field cannot disappear silently."""
    # Start from a complete document so the surplus key is the sole schema defect.
    payload = valid_payload()
    # Introduce a plausible misspelling that permissive parsing might ignore.
    strategy(payload)["residue"] = "misspelled"
    # Require the exact unknown key to survive into the repair diagnostic.
    with pytest.raises(EvidenceParseError, match="unknown residue"):
        load_evidence(write_payload(tmp_path / "evidence.json", payload))


def test_field_observations_are_typed_and_reproducible(tmp_path: Path) -> None:
    """An observation ID resolves to a bounded claim and named evidence location."""
    # Treat payload as mapping elements whose keys name observation-registry fields and whose
    # values carry schema data; insertion order is preserved for deterministic fixture JSON.
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
    # Parse the authored document through the public observation registry boundary.
    registry = load_observations(write_payload(tmp_path / "observations.json", payload))
    assert registry.observations["V4E-001"].evidence_kind is ObservationKind.REPRODUCED


def test_field_observation_requires_a_location(tmp_path: Path) -> None:
    """An unlocated anecdote cannot satisfy a field-evidence reference."""
    # Treat payload as mapping elements whose keys name observation-registry fields and whose
    # values carry schema data; insertion order is preserved for deterministic fixture JSON.
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
    # Require the parser to reject evidence that an auditor cannot locate.
    with pytest.raises(EvidenceParseError, match="at least one evidence location"):
        load_observations(write_payload(tmp_path / "observations.json", payload))


def test_capabilities_use_configuration_key_grammar(tmp_path: Path) -> None:
    """Capability names are valid TOML-style identifiers before activation exists."""
    # Start from a structurally complete rule before damaging capability grammar.
    payload = valid_payload()
    # Use spaces and capitals to violate the configuration-key naming contract.
    record(payload)["capabilities"] = ["Network I/O"]
    # Require localization to the invalid capability name.
    with pytest.raises(EvidenceParseError, match="invalid name"):
        load_evidence(write_payload(tmp_path / "evidence.json", payload))


def test_heading_and_strategy_mechanisms_must_match(tmp_path: Path) -> None:
    """Evidence cannot describe a verifier the normative heading does not name."""
    # Parse evidence naming mypy so a pyright-only heading creates the intended mismatch.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", valid_payload()))
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = validate_evidence(
        registry,
        [rule(mechanisms=("auto:pyright",))],
        {("TYPE-001", "auto:mypy")},
    )
    assert [finding.code for finding in findings] == ["E004"]


def test_automated_strategy_needs_a_must_reject_case(tmp_path: Path) -> None:
    """A positive reference alone cannot demonstrate discrimination."""
    # Start from complete automated evidence before removing only its negative witness.
    payload = valid_payload()
    # Replace the exact rejection marker with the structured-review-only null form.
    strategy(payload)["must_reject"] = None
    # Parse the damaged evidence so semantic rather than structural validation owns the verdict.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = validate_evidence(registry, [rule()], {("TYPE-001", "auto:mypy")})
    assert "E008" in {finding.code for finding in findings}


def test_declared_mutation_must_have_been_witnessed(tmp_path: Path) -> None:
    """A must-reject label without an executed matrix entry receives no credit."""
    # Parse complete evidence whose declared marker will be compared with an empty witness set.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", valid_payload()))
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = validate_evidence(registry, [rule()], set())
    assert "E009" in {finding.code for finding in findings}


def test_must_reject_names_the_exact_rule_and_mechanism(tmp_path: Path) -> None:
    """A legacy rule-only label cannot identify which verifier rejected it."""
    # Start from a complete document before degrading its witness to v3 rule-only form.
    payload = valid_payload()
    # Remove the mechanism suffix that distinguishes sibling verifier strategies.
    strategy(payload)["must_reject"] = "discrimination:TYPE-001"
    # Parse the structurally valid legacy marker for semantic validation.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))

    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = validate_evidence(
        registry,
        [rule()],
        {("TYPE-001", "auto:mypy")},
    )

    # Project findings to stable codes so presentation wording cannot satisfy the test.
    assert "E012" in {finding.code for finding in findings}


def test_generated_placeholder_is_not_an_observable_proposition(tmp_path: Path) -> None:
    """Evidence must state the finite condition, not merely name a checker."""
    # Start from direct evidence before replacing its proposition with generated filler.
    payload = valid_payload()
    # Use the exact vague template the semantic validator must distinguish from an observable.
    strategy(payload)["proposition"] = (
        "auto:mypy reports no diagnostic corresponding to TYPE-001 under config."
    )
    # Parse the structurally valid placeholder for semantic validation.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))

    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = validate_evidence(
        registry,
        [rule()],
        {("TYPE-001", "auto:mypy")},
    )

    # Project findings to stable codes so only the intended placeholder diagnostic counts.
    assert "E013" in {finding.code for finding in findings}


def test_rule_only_matrix_cannot_supply_v4_rejection_credit(tmp_path: Path) -> None:
    """The v3 coverage view cannot conceal an unwitnessed second mechanism.

    @par Effects
    Writes a temporary legacy discrimination module beneath ``tmp_path``.
    """
    # Address the repository-local matrix path expected by the evidence loader.
    matrix = tmp_path / "enforce" / "discrimination.py"
    # Create the package directory before materializing the legacy module.
    matrix.parent.mkdir(parents=True)
    # Publish only the v3 rule-id getter, deliberately omitting exact strategy evidence.
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
    # Start from one witnessed mypy strategy under TYPE-001.
    payload = valid_payload()
    # Clone the complete strategy so only its mechanism identity differs.
    pyright = deepcopy(strategy(payload))
    # Attribute the sibling strategy to pyright while retaining the fixture's other fields.
    pyright["mechanism"] = "auto:pyright"
    # Narrow the rule's authored strategy list before adding the sibling verifier.
    strategies = record(payload)["strategies"]
    assert isinstance(strategies, list)
    # Add the unwitnessed pyright claim alongside the witnessed mypy claim.
    strategies.append(pyright)
    # Parse the two-strategy evidence for exact-pair semantic validation.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = validate_evidence(
        registry,
        [rule(mechanisms=("auto:mypy", "auto:pyright"))],
        {("TYPE-001", "auto:mypy")},
    )
    assert [finding.message for finding in findings if finding.code == "E009"] == [
        "auto:pyright is not witnessed rejecting"
    ]


def test_tag_and_kind_cannot_disagree(tmp_path: Path) -> None:
    """An external-tool tag cannot be presented as a local static check."""
    # Start from a correctly classified external-tool strategy.
    payload = valid_payload()
    # Misclassify the auto tag as a repository-local static mechanism.
    strategy(payload)["kind"] = "static"
    # Parse the structurally valid mismatch for semantic validation.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = validate_evidence(registry, [rule()], {("TYPE-001", "auto:mypy")})
    assert "E010" in {finding.code for finding in findings}


def test_retirement_preserves_the_id_and_removes_strategies(tmp_path: Path) -> None:
    """A superseded heading remains resolvable but cannot look actively verified."""
    # Copy the fixture so retirement edits cannot affect later tests.
    payload = deepcopy(valid_payload())
    # Remove active strategies because superseded rules describe history only.
    record(payload)["strategies"] = []
    # Narrow the migration record before changing its historical disposition.
    migration = record(payload)["migration"]
    assert isinstance(migration, dict)
    # Mark the stable id as replaced rather than merely clarified.
    migration["disposition"] = MigrationDisposition.SUPERSEDED
    # Parse the historical evidence after all retirement fields agree.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))
    # Build the corresponding retired normative heading with its explicit successor.
    retired = rule(mechanisms=(), superseded_by="TYPE-002", force=Force.RETIRED)
    assert validate_evidence(registry, [retired], set()) == []
    assert verification_state(retired, registry.rules["TYPE-001"]) is VerificationState.RETIRED


def test_withdrawal_without_a_replacement_is_representable(tmp_path: Path) -> None:
    """A rule can leave scope without inventing a successor that does not exist."""
    # Copy the fixture so withdrawal edits cannot affect later tests.
    payload = deepcopy(valid_payload())
    # Remove active strategies because withdrawn rules describe history only.
    record(payload)["strategies"] = []
    # Narrow the migration record before changing its historical disposition.
    migration = record(payload)["migration"]
    assert isinstance(migration, dict)
    # Use retired rather than superseded to state that no successor exists.
    migration["disposition"] = MigrationDisposition.RETIRED
    # Parse the internally consistent withdrawn evidence.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))
    # Build the corresponding retired heading without a successor id.
    withdrawn = rule(mechanisms=(), force=Force.RETIRED)
    assert validate_evidence(registry, [withdrawn], set()) == []
    assert verification_state(withdrawn, registry.rules["TYPE-001"]) is VerificationState.RETIRED


def test_replacement_disposition_requires_a_successor(tmp_path: Path) -> None:
    """Superseded cannot mean retired-without-replacement by implication."""
    # Copy the fixture so the malformed history is local to this test.
    payload = deepcopy(valid_payload())
    # Remove strategies to isolate successor consistency from active-verifier findings.
    record(payload)["strategies"] = []
    # Narrow the migration record before changing its disposition.
    migration = record(payload)["migration"]
    assert isinstance(migration, dict)
    # Claim replacement while the normative heading deliberately names no successor.
    migration["disposition"] = MigrationDisposition.SUPERSEDED
    # Parse the structurally valid but historically inconsistent evidence.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", payload))
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = validate_evidence(registry, [rule(mechanisms=(), force=Force.RETIRED)], set())
    assert [finding.code for finding in findings] == ["E007"]


def test_verification_state_says_what_exists_not_that_it_passed(tmp_path: Path) -> None:
    """An external strategy is a verifier declaration, never a synthetic pass."""
    # Parse a declared external strategy without executing or mocking its tool.
    registry = load_evidence(write_payload(tmp_path / "evidence.json", valid_payload()))
    assert (
        verification_state(rule(), registry.rules["TYPE-001"], tmp_path)
        is VerificationState.EXTERNAL_VERIFIER
    )
