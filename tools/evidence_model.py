"""Typed v4 evidence records for the discipline's normative rules.

The Markdown corpus states obligations. This module reads the separate authored
registry that states why each obligation is plausible and exactly what each
verification strategy can observe. Keeping the layers separate prevents a
working checker from being presented as empirical proof that its parent rule is
beneficial.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Never, TypeAlias, TypeVar, cast

from discipline_core import REPO_ROOT, Force, mechanism_is_implemented

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from collections.abc import Set as AbstractSet
    from pathlib import Path

    from discipline_core import Rule

## One exact `(rule, mechanism)` rejection witness.
DiscriminationWitness: TypeAlias = tuple[str, str]

## The authored registry. It is deliberately not generated: evidence judgments
## must be reviewed rather than inferred from the existence of a checker.
EVIDENCE_PATH: Final = REPO_ROOT / "discipline" / "meta" / "evidence.json"
## Reproducible adopter and audit observations referenced by rule evidence.
OBSERVATIONS_PATH: Final = REPO_ROOT / "discipline" / "meta" / "observations.json"

## Capability names become configuration keys later in v4, so constrain their
## spelling before any adopter can depend on an ambiguous form.
_CAPABILITY = re.compile(r"^[a-z][a-z0-9_]*$")
## Stable field-evidence identifiers are versioned independently from rule ids.
_OBSERVATION_ID = re.compile(r"^V[0-9]+E-[0-9]{3}$")
## Exact arity of a `(rule id, mechanism)` discrimination witness.
_WITNESS_PARTS: Final = 2
## Generated placeholder prose cannot stand in for an observable proposition.
_VAGUE_PROPOSITION: Final[tuple[str, ...]] = (
    "reports no diagnostic corresponding to",
    "passes against the repository artifacts and behavioral cases selected by that test",
    "emits a finding tagged",
)

## Type variable preserving the concrete string-enum class passed to `_enum`.
_EnumT = TypeVar("_EnumT", bound=StrEnum)


class UnitKind(StrEnum):
    """The two repository subjects the discipline can govern."""

    ## A repository that owns the complete delivered application.
    APPLICATION = "application"
    ## One independently developed repository participating in a larger application.
    COMPONENT = "component"


class MechanismKind(StrEnum):
    """How a strategy observes its proposition."""

    ## Repository-local syntax or structure analysis.
    STATIC = "static"
    ## A separately configured checker with its own diagnostic vocabulary.
    TOOL = "tool"
    ## Executed behavior with an oracle.
    BEHAVIORAL = "behavioral"
    ## Regeneration followed by an exact comparison.
    GENERATED_DRIFT = "generated-drift"
    ## A checked review artifact whose conclusion still requires judgment.
    STRUCTURED_REVIEW = "structured-review"


class DecisionRelation(StrEnum):
    """Whether the observation is the claim itself or only a proxy for it."""

    ## The proposition is the exact condition the mechanism observes.
    DIRECT = "direct"
    ## The observed proposition is correlated with, but does not decide, the semantic claim.
    PROXY = "proxy"


class WarrantRelation(StrEnum):
    """What a cited source contributes to the normative claim."""

    ## The source provides an argument or result in favor of the rule.
    SUPPORTS = "supports"
    ## The source documents the failure mode that prompted the rule.
    MOTIVATES = "motivates"
    ## The source narrows where or how strongly the rule applies.
    LIMITS = "limits"
    ## An adopter record reports what happened when the rule or mechanism was used.
    OBSERVED_IN = "observed-in"


class Confidence(StrEnum):
    """How strongly the author says a warrant supports the local rule."""

    ## Direct, repeatedly reproduced, or strongly established support.
    HIGH = "high"
    ## Plausible support with material extrapolation or limited observations.
    MEDIUM = "medium"
    ## Provisional support retained for explicit challenge and further evidence.
    LOW = "low"


class MigrationDisposition(StrEnum):
    """How a v3 rule enters the v4 corpus without rewriting history."""

    ## Normative and decidable meanings remain the same.
    UNCHANGED = "unchanged"
    ## The stable id remains while ambiguous meaning is narrowed.
    CLARIFIED = "clarified"
    ## A new stable id replaces this rule.
    SUPERSEDED = "superseded"
    ## Another retained rule absorbs this rule's obligation.
    CONSOLIDATED = "consolidated"
    ## The rule remains but applies only when a named local capability is active.
    CAPABILITY_ACTIVATED = "capability-activated"
    ## The obligation is withdrawn and its id remains only as history.
    RETIRED = "retired"
    ## The rule first appears in v4.
    NEW = "new"


class ObservationClassification(StrEnum):
    """Which kind of defect or fact one field observation establishes."""

    ## The normative statement itself caused or preserved the failure.
    DOCTRINE_DEFECT = "doctrine_defect"
    ## The checker disagreed with the proposition it claimed to decide.
    MECHANISM_DEFECT = "mechanism_defect"
    ## The adopter violated a sound local obligation.
    PROJECT_DEFECT = "project_defect"
    ## The adopter's local contract was missing or internally inconsistent.
    SPECIFICATION_DEFECT = "specification_defect"
    ## Versioned behavior of a tool, without a normative conclusion.
    TOOL_FACT = "tool_fact"
    ## A required verdict cannot be produced on the named platform.
    UNSUPPORTED_PLATFORM_FACT = "unsupported_platform_fact"


class ObservationKind(StrEnum):
    """How an observation was obtained without upgrading it to proof."""

    ## Captured during an adopter change or audit.
    OBSERVED = "observed"
    ## Repeated from a named commit and command.
    REPRODUCED = "reproduced"
    ## Checked directly against a pinned tool version.
    VERIFIED_TOOL_FACT = "verified_tool_fact"
    ## Human synthesis across records, explicitly not an executable reproduction.
    MANUAL_SYNTHESIS = "manual_synthesis"


class VerificationState(StrEnum):
    """What verification strategy is present, without claiming a gate outcome."""

    ## Every strategy is implemented by repository-local code.
    LOCAL_VERIFIER = "local-verifier"
    ## Every strategy is delegated to a configured external tool.
    EXTERNAL_VERIFIER = "external-verifier"
    ## More than one verifier kind contributes to the rule.
    MIXED_VERIFIERS = "mixed-verifiers"
    ## Judgment is recorded structurally but no machine decides the conclusion.
    STRUCTURED_REVIEW = "structured-review"
    ## At least one named repository-local mechanism is absent.
    UNBUILT = "unbuilt"
    ## The active rule has no verification strategy.
    UNDECLARED = "undeclared"
    ## The stable heading is retained only to resolve history.
    RETIRED = "retired"

    @property
    def is_automated(self) -> bool:
        """Whether every proposition has an automated strategy available.

        @return true only when no structured judgment remains in the strategy
        """
        return self in {
            VerificationState.LOCAL_VERIFIER,
            VerificationState.EXTERNAL_VERIFIER,
            VerificationState.MIXED_VERIFIERS,
        }


@dataclass(frozen=True, slots=True)
class Warrant:
    """One source and the limited relationship it has to a rule."""

    ## Resolvable corpus, doctrine, or adopter-evidence identifier.
    source: str
    ## The claim made about the source rather than inferred from its mere citation.
    relation: WarrantRelation
    ## Explicit strength of that relationship.
    confidence: Confidence


@dataclass(frozen=True, slots=True)
class Strategy:
    """One mechanism's exact observable proposition and known limits."""

    ## Heading tag naming the mechanism.
    mechanism: str
    ## Observation method.
    kind: MechanismKind
    ## Whether the observable proposition is direct or a proxy.
    relation: DecisionRelation
    ## Exact condition whose violation this mechanism can report.
    proposition: str
    ## What can still be wrong after that proposition passes.
    residual: str
    ## Conformant artifact on which the mechanism must pass.
    must_pass: str
    ## Deliberate violation the mechanism must reject; absent only for review.
    must_reject: str | None
    ## Platforms on which the strategy is supported and release-relevant.
    platforms: tuple[str, ...]
    ## Explicit condition under which the strategy may report not-applicable.
    not_applicable: str

    @property
    def is_automated(self) -> bool:
        """Whether the strategy is expected to produce a machine verdict.

        @return false only for a structured review
        """
        return self.kind is not MechanismKind.STRUCTURED_REVIEW


@dataclass(frozen=True, slots=True)
class Migration:
    """The historical relationship between this record and the v3 surface."""

    ## Version or rule from which this record came.
    source: str
    ## Controlled migration classification.
    disposition: MigrationDisposition
    ## Concrete action required of an adopting repository.
    guidance: str


@dataclass(frozen=True, slots=True)
class RuleEvidence:
    """The non-normative evidence attached to one stable rule id."""

    ## Stable normative id joined to this record.
    rule_id: str
    ## Repository subjects to which the rule can apply.
    units: tuple[UnitKind, ...]
    ## Local capabilities that activate the rule; empty means unconditional.
    capabilities: tuple[str, ...]
    ## Consequence the rule is intended to prevent or contain.
    failure_mode: str
    ## Sources and observations that make the obligation plausible.
    warrants: tuple[Warrant, ...]
    ## One exact observable strategy for every heading mechanism.
    strategies: tuple[Strategy, ...]
    ## Field-evidence identifiers from independent adopters or audits.
    observations: tuple[str, ...]
    ## Stable-id relationship to the preceding corpus.
    migration: Migration


@dataclass(frozen=True, slots=True)
class EvidenceRegistry:
    """The complete authored evidence layer."""

    ## Parser contract version, independent of the discipline release number.
    schema_version: int
    ## Every evidence record keyed by its stable rule id.
    rules: Mapping[str, RuleEvidence]


@dataclass(frozen=True, slots=True)
class FieldObservation:
    """One named result from an adopter, audit, or tool reproduction."""

    ## Stable identifier used by rule evidence.
    observation_id: str
    ## Defect/fact category assigned during evidence triage.
    classification: ObservationClassification
    ## Bounded statement the observation supports.
    claim: str
    ## How the result was obtained.
    evidence_kind: ObservationKind
    ## Named commits, ledgers, or audits in which it was seen.
    observed_in: tuple[str, ...]
    ## Repeatable action, absent only for explicitly manual synthesis.
    reproduction: str | None
    ## Repository-local boundary within which the observation applies.
    scope: str
    ## Authored source from which this packaged record was transcribed.
    source: str


@dataclass(frozen=True, slots=True)
class ObservationRegistry:
    """The complete authored field-evidence registry."""

    ## Parser contract version.
    schema_version: int
    ## Every observation keyed by its stable evidence id.
    observations: Mapping[str, FieldObservation]


@dataclass(frozen=True, slots=True)
class EvidenceFinding:
    """One semantic mismatch between the registry and the rule corpus."""

    ## Stable validator diagnostic code.
    code: str
    ## Normative or orphan evidence id responsible for the mismatch.
    rule_id: str
    ## Actionable explanation of the mismatch.
    message: str


class EvidenceParseError(ValueError):
    """The registry is not structurally valid v4 evidence."""

    def __init__(self, where: str, detail: str) -> None:
        """Build a diagnostic that retains its structured location.

        @param where JSON path or file carrying the invalid value
        @param detail violated structural requirement
        """
        self.where = where
        self.detail = detail
        super().__init__(f"{where}: {detail}")


def load_evidence(path: Path = EVIDENCE_PATH) -> EvidenceRegistry:
    """Read and structurally validate one authored registry.

    @param path JSON registry to read
    @return a typed registry whose nested fields are all present and recognized
    @throws EvidenceParseError when JSON or any field violates the schema
    """
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as problem:
        raise EvidenceParseError(str(path), str(problem)) from problem
    root = _mapping(raw, "registry")
    _exact_fields(root, {"schema_version", "rules"}, "registry")
    version = _integer(root["schema_version"], "registry.schema_version")
    if version != 1:
        _invalid("registry.schema_version", f"expected 1, got {version}")
    raw_rules = _mapping(root["rules"], "registry.rules")
    parsed: dict[str, RuleEvidence] = {}
    for rule_id, value in raw_rules.items():
        parsed[rule_id] = _rule_evidence(rule_id, value)
    return EvidenceRegistry(schema_version=version, rules=parsed)


def load_observations(path: Path = OBSERVATIONS_PATH) -> ObservationRegistry:
    """Read and structurally validate the named field observations.

    @param path JSON registry to read
    @return typed observations addressable by stable evidence id
    @throws EvidenceParseError when JSON or a field violates the contract
    """
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as problem:
        raise EvidenceParseError(str(path), str(problem)) from problem
    root = _mapping(raw, "observations")
    _exact_fields(root, {"schema_version", "observations"}, "observations")
    version = _integer(root["schema_version"], "observations.schema_version")
    if version != 1:
        _invalid("observations.schema_version", f"expected 1, got {version}")
    records = _mapping(root["observations"], "observations.observations")
    parsed: dict[str, FieldObservation] = {}
    for observation_id, value in records.items():
        parsed[observation_id] = _field_observation(observation_id, value)
    return ObservationRegistry(schema_version=version, observations=parsed)


def _field_observation(observation_id: str, value: object) -> FieldObservation:
    """Parse one field observation with its reproduction boundary intact.

    @param observation_id stable id supplied by the registry key
    @param value untrusted JSON value beneath that key
    @return typed observation
    """
    where = f"observations.{observation_id}"
    if _OBSERVATION_ID.fullmatch(observation_id) is None:
        _invalid(where, "expected V<major>E-NNN")
    record = _mapping(value, where)
    _exact_fields(
        record,
        {
            "classification",
            "claim",
            "evidence_kind",
            "observed_in",
            "reproduction",
            "scope",
            "source",
        },
        where,
    )
    locations = _strings(record["observed_in"], f"{where}.observed_in")
    if not locations:
        _invalid(f"{where}.observed_in", "at least one evidence location is required")
    reproduction = record["reproduction"]
    if reproduction is not None:
        reproduction = _nonempty(reproduction, f"{where}.reproduction")
    return FieldObservation(
        observation_id=observation_id,
        classification=_enum(
            ObservationClassification,
            record["classification"],
            f"{where}.classification",
        ),
        claim=_nonempty(record["claim"], f"{where}.claim"),
        evidence_kind=_enum(ObservationKind, record["evidence_kind"], f"{where}.evidence_kind"),
        observed_in=locations,
        reproduction=reproduction,
        scope=_nonempty(record["scope"], f"{where}.scope"),
        source=_nonempty(record["source"], f"{where}.source"),
    )


def _rule_evidence(rule_id: str, value: object) -> RuleEvidence:
    """Parse the evidence record for one stable id.

    @param rule_id id supplied by the registry key
    @param value untrusted JSON value under that key
    @return the typed record
    @throws EvidenceParseError when the record is incomplete or malformed
    """
    where = f"rules.{rule_id}"
    record = _mapping(value, where)
    _exact_fields(
        record,
        {
            "units",
            "capabilities",
            "failure_mode",
            "warrants",
            "strategies",
            "observations",
            "migration",
        },
        where,
    )
    units = tuple(
        _enum(UnitKind, item, f"{where}.units[{index}]")
        for index, item in enumerate(_sequence(record["units"], f"{where}.units"))
    )
    if not units:
        _invalid(f"{where}.units", "at least one governed unit is required")
    capabilities = _strings(record["capabilities"], f"{where}.capabilities")
    invalid = [name for name in capabilities if _CAPABILITY.fullmatch(name) is None]
    if invalid:
        _invalid(f"{where}.capabilities", f"invalid name {invalid[0]!r}")
    warrants = tuple(
        _warrant(item, f"{where}.warrants[{index}]")
        for index, item in enumerate(_sequence(record["warrants"], f"{where}.warrants"))
    )
    strategies = tuple(
        _strategy(item, f"{where}.strategies[{index}]")
        for index, item in enumerate(_sequence(record["strategies"], f"{where}.strategies"))
    )
    return RuleEvidence(
        rule_id=rule_id,
        units=units,
        capabilities=capabilities,
        failure_mode=_nonempty(record["failure_mode"], f"{where}.failure_mode"),
        warrants=warrants,
        strategies=strategies,
        observations=_strings(record["observations"], f"{where}.observations"),
        migration=_migration(record["migration"], f"{where}.migration"),
    )


def _warrant(value: object, where: str) -> Warrant:
    """Parse one source warrant.

    @param value untrusted warrant object
    @param where diagnostic path of that value
    @return the typed warrant
    """
    record = _mapping(value, where)
    _exact_fields(record, {"source", "relation", "confidence"}, where)
    return Warrant(
        source=_nonempty(record["source"], f"{where}.source"),
        relation=_enum(WarrantRelation, record["relation"], f"{where}.relation"),
        confidence=_enum(Confidence, record["confidence"], f"{where}.confidence"),
    )


def _strategy(value: object, where: str) -> Strategy:
    """Parse one verification strategy.

    @param value untrusted strategy object
    @param where diagnostic path of that value
    @return the typed strategy
    """
    record = _mapping(value, where)
    _exact_fields(
        record,
        {
            "mechanism",
            "kind",
            "relation",
            "proposition",
            "residual",
            "must_pass",
            "must_reject",
            "platforms",
            "not_applicable",
        },
        where,
    )
    rejected = record["must_reject"]
    if rejected is not None:
        rejected = _nonempty(rejected, f"{where}.must_reject")
    platforms = _strings(record["platforms"], f"{where}.platforms")
    if not platforms:
        _invalid(f"{where}.platforms", "at least one platform is required")
    return Strategy(
        mechanism=_nonempty(record["mechanism"], f"{where}.mechanism"),
        kind=_enum(MechanismKind, record["kind"], f"{where}.kind"),
        relation=_enum(DecisionRelation, record["relation"], f"{where}.relation"),
        proposition=_nonempty(record["proposition"], f"{where}.proposition"),
        residual=_nonempty(record["residual"], f"{where}.residual"),
        must_pass=_nonempty(record["must_pass"], f"{where}.must_pass"),
        must_reject=rejected,
        platforms=platforms,
        not_applicable=_nonempty(record["not_applicable"], f"{where}.not_applicable"),
    )


def _migration(value: object, where: str) -> Migration:
    """Parse one stable-id migration record.

    @param value untrusted migration object
    @param where diagnostic path of that value
    @return the typed migration
    """
    record = _mapping(value, where)
    _exact_fields(record, {"source", "disposition", "guidance"}, where)
    return Migration(
        source=_nonempty(record["source"], f"{where}.source"),
        disposition=_enum(MigrationDisposition, record["disposition"], f"{where}.disposition"),
        guidance=_nonempty(record["guidance"], f"{where}.guidance"),
    )


def validate_evidence(
    registry: EvidenceRegistry,
    rules: Sequence[Rule],
    discriminated: AbstractSet[DiscriminationWitness],
    observation_ids: AbstractSet[str] | None = None,
) -> list[EvidenceFinding]:
    """Check cross-record semantics the structural parser cannot know.

    @param registry parsed evidence layer
    @param rules normative rules to join by stable id
    @param discriminated exact rule/mechanism pairs
    @param observation_ids resolvable field-evidence ids, when the registry is available
    @return every mismatch in stable rule-id order
    """
    normative = {rule.rule_id: rule for rule in rules}
    findings = [
        EvidenceFinding("E001", rule_id, "rule has no evidence record")
        for rule_id in sorted(normative.keys() - registry.rules.keys())
    ]
    findings.extend(
        EvidenceFinding("E002", rule_id, "evidence names no normative rule")
        for rule_id in sorted(registry.rules.keys() - normative.keys())
    )
    for rule_id in sorted(normative.keys() & registry.rules.keys()):
        rule = normative[rule_id]
        evidence = registry.rules[rule_id]
        findings.extend(_validate_record(rule, evidence, discriminated, observation_ids))
    return findings


def _validate_record(
    rule: Rule,
    evidence: RuleEvidence,
    discriminated: AbstractSet[DiscriminationWitness],
    observation_ids: AbstractSet[str] | None,
) -> list[EvidenceFinding]:
    """Validate one joined normative/evidence pair.

    @param rule normative source record
    @param evidence evidence record with the same id
    @param discriminated exact rule/mechanism pairs
    @param observation_ids resolvable field-evidence ids, or None when unavailable
    @return semantic mismatches for this pair
    """
    findings: list[EvidenceFinding] = []
    if not evidence.warrants:
        findings.append(EvidenceFinding("E003", rule.rule_id, "rule names no warrant"))
    findings.extend(_unresolved_observations(evidence, observation_ids))
    declared = Counter(rule.mechanisms)
    evidenced = Counter(strategy.mechanism for strategy in evidence.strategies)
    if declared != evidenced:
        findings.append(
            EvidenceFinding(
                "E004",
                rule.rule_id,
                f"strategy mechanisms {dict(evidenced)} do not match heading {dict(declared)}",
            )
        )
    findings.extend(_retirement_findings(rule, evidence))
    for strategy in evidence.strategies:
        if strategy.is_automated and strategy.must_reject is None:
            findings.append(
                EvidenceFinding(
                    "E008", rule.rule_id, f"{strategy.mechanism} has no must-reject case"
                )
            )
        if strategy.is_automated and strategy.must_reject is not None:
            expected_marker = f"discrimination:{rule.rule_id}/{strategy.mechanism}"
            if strategy.must_reject != expected_marker:
                findings.append(
                    EvidenceFinding(
                        "E012",
                        rule.rule_id,
                        f"{strategy.mechanism} must-reject marker is not {expected_marker!r}",
                    )
                )
        if strategy.is_automated and any(
            placeholder in strategy.proposition for placeholder in _VAGUE_PROPOSITION
        ):
            findings.append(
                EvidenceFinding(
                    "E013",
                    rule.rule_id,
                    f"{strategy.mechanism} states a generated placeholder, not an "
                    "observable proposition",
                )
            )
        if strategy.is_automated and not _strategy_witnessed(
            rule.rule_id, strategy.mechanism, discriminated
        ):
            findings.append(
                EvidenceFinding(
                    "E009", rule.rule_id, f"{strategy.mechanism} is not witnessed rejecting"
                )
            )
        expected = _expected_kind(strategy.mechanism)
        if strategy.kind not in expected:
            findings.append(
                EvidenceFinding(
                    "E010",
                    rule.rule_id,
                    f"{strategy.mechanism} cannot use kind {strategy.kind}",
                )
            )
    return findings


def _strategy_witnessed(
    rule_id: str,
    mechanism: str,
    discriminated: AbstractSet[DiscriminationWitness],
) -> bool:
    """Whether this exact strategy has a rejection witness.

    Native v4 matrices publish exact pairs so one mechanism cannot lend credit to
    another mechanism attached to the same rule. Rule-only v3 witnesses are not
    admissible evidence for a v4 claim.

    @param rule_id normative stable id
    @param mechanism exact heading mechanism
    @param discriminated exact pairs
    @return whether rejection credit resolves
    """
    return (rule_id, mechanism) in discriminated


def _retirement_findings(rule: Rule, evidence: RuleEvidence) -> list[EvidenceFinding]:
    """Keep force, strategies, disposition, and successor history consistent.

    @param rule normative or historical heading
    @param evidence migration and strategy record joined to that heading
    @return every retirement/supersession mismatch
    """
    disposition = evidence.migration.disposition
    retired = disposition in {
        MigrationDisposition.SUPERSEDED,
        MigrationDisposition.CONSOLIDATED,
        MigrationDisposition.RETIRED,
    }
    findings: list[EvidenceFinding] = []
    if retired and evidence.strategies:
        findings.append(EvidenceFinding("E005", rule.rule_id, "retired rule has strategies"))
    if retired is not (rule.force is Force.RETIRED):
        findings.append(
            EvidenceFinding(
                "E006", rule.rule_id, "retired force and migration disposition disagree"
            )
        )
    if rule.superseded_by is not None and not retired:
        findings.append(
            EvidenceFinding("E006", rule.rule_id, "heading has a successor but migration is active")
        )
    if rule.superseded_by is None and disposition in {
        MigrationDisposition.SUPERSEDED,
        MigrationDisposition.CONSOLIDATED,
    }:
        findings.append(
            EvidenceFinding("E007", rule.rule_id, "replacement disposition names no successor")
        )
    return findings


def _unresolved_observations(
    evidence: RuleEvidence, observation_ids: AbstractSet[str] | None
) -> list[EvidenceFinding]:
    """Report field-evidence references only when a registry was supplied.

    @param evidence rule record carrying zero or more observation IDs
    @param observation_ids complete resolvable ID set, or None for legacy callers
    @return one finding per unresolved reference
    """
    if observation_ids is None:
        return []
    return [
        EvidenceFinding("E011", evidence.rule_id, f"observation {observation} does not resolve")
        for observation in evidence.observations
        if observation not in observation_ids
    ]


def verification_state(
    rule: Rule, evidence: RuleEvidence, root: Path = REPO_ROOT
) -> VerificationState:
    """Describe the available strategy without pretending it has just passed.

    @param rule normative rule whose mechanism tags are resolved
    @param evidence joined evidence record
    @param root repository against which local mechanisms are located
    @return the honest strategy state
    """
    if evidence.migration.disposition in {
        MigrationDisposition.SUPERSEDED,
        MigrationDisposition.CONSOLIDATED,
        MigrationDisposition.RETIRED,
    }:
        state = VerificationState.RETIRED
    elif not evidence.strategies:
        state = VerificationState.UNDECLARED
    elif any(
        mechanism_is_implemented(strategy.mechanism, root, rule.rule_id) is False
        for strategy in evidence.strategies
    ):
        state = VerificationState.UNBUILT
    else:
        kinds = {strategy.kind for strategy in evidence.strategies}
        if kinds == {MechanismKind.STRUCTURED_REVIEW}:
            state = VerificationState.STRUCTURED_REVIEW
        elif MechanismKind.STRUCTURED_REVIEW in kinds or (
            MechanismKind.TOOL in kinds and len(kinds) > 1
        ):
            state = VerificationState.MIXED_VERIFIERS
        elif kinds == {MechanismKind.TOOL}:
            state = VerificationState.EXTERNAL_VERIFIER
        else:
            state = VerificationState.LOCAL_VERIFIER
    return state


def _discrimination_value(root: Path, getter_name: str) -> object | None:
    """Load one value from a repository's own mutation matrix by path.

    Importing by path prevents a vendored or synthetic corpus from receiving
    credit from whichever ``discrimination`` module is already importable in the
    caller's environment.

    @param root repository whose matrix supplies the evidence
    @param getter_name zero-argument matrix function to invoke
    @return the returned value, or None when the matrix cannot be trusted
    """
    source = root / "enforce" / "discrimination.py"
    if not source.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_discipline_discrimination", source)
    if spec is None or spec.loader is None:
        return None
    discrimination = importlib.util.module_from_spec(spec)
    # ``dataclass(slots=True)`` resolves the defining module during execution.
    sys.modules[spec.name] = discrimination
    try:
        spec.loader.exec_module(discrimination)
        getter: object = getattr(discrimination, getter_name, None)
        if not callable(getter):
            return None
        result: object = getter()
    except Exception:  # ruff: ignore[blind-except] - authored matrix is input
        return None
    finally:
        sys.modules.pop(spec.name, None)
    return result


def discrimination_covered(root: Path = REPO_ROOT) -> frozenset[str] | None:
    """Load rule ids that have at least one declared mutation.

    ``None`` means there is no trustworthy matrix; an empty set means a matrix
    loaded and declared no rules.

    @param root repository whose matrix supplies the evidence
    @return witnessed stable ids, or None when the matrix is absent or malformed
    """
    result = _discrimination_value(root, "covered")
    if not isinstance(result, (set, frozenset)) or not all(
        isinstance(item, str) for item in result
    ):
        return None
    return frozenset(result)


def discrimination_witnesses(
    root: Path = REPO_ROOT,
) -> frozenset[DiscriminationWitness] | None:
    """Load and resolve exact strategy witnesses from a native v4 matrix.

    An older table entry may omit its mechanism only while the joined active
    evidence record has exactly one automated strategy. The returned value is
    always exact; retired entries are ignored and ambiguous entries invalidate
    the matrix.

    @param root repository whose matrix supplies the evidence
    @return exact pairs, or None for an absent, legacy, or malformed matrix
    """
    result = _discrimination_value(root, "covered_strategies")
    if not isinstance(result, (set, frozenset)):
        return None
    raw: set[DiscriminationWitness] = set()
    for item in result:
        if not (
            isinstance(item, tuple)
            and len(item) == _WITNESS_PARTS
            and all(isinstance(part, str) for part in item)
        ):
            return None
        raw.add(item)

    try:
        registry = load_evidence(root / "discipline" / "meta" / "evidence.json")
    except (EvidenceParseError, OSError):
        return None
    automated = {
        rule_id: tuple(
            strategy.mechanism for strategy in record.strategies if strategy.is_automated
        )
        for rule_id, record in registry.rules.items()
    }
    witnesses: set[DiscriminationWitness] = set()
    for rule_id, mechanism in raw:
        candidates = automated.get(rule_id, ())
        if not candidates:
            continue
        if mechanism:
            if mechanism not in candidates:
                return None
            witnesses.add((rule_id, mechanism))
        elif len(candidates) == 1:
            witnesses.add((rule_id, candidates[0]))
        else:
            return None
    return frozenset(witnesses)


def _expected_kind(mechanism: str) -> frozenset[MechanismKind]:
    """Mechanism kinds compatible with one heading tag.

    @param mechanism heading tag
    @return allowed evidence kinds; empty when the tag grammar is unknown
    """
    prefix = mechanism.partition(":")[0]
    if prefix == "check":
        return frozenset({MechanismKind.STATIC, MechanismKind.GENERATED_DRIFT})
    if prefix == "fitness":
        return frozenset({MechanismKind.BEHAVIORAL, MechanismKind.GENERATED_DRIFT})
    if prefix == "auto":
        return frozenset({MechanismKind.TOOL})
    if mechanism == "review":
        return frozenset({MechanismKind.STRUCTURED_REVIEW})
    return frozenset()


def _mapping(value: object, where: str) -> dict[str, object]:
    """Narrow one JSON value to a string-keyed mapping.

    @param value candidate mapping
    @param where diagnostic path
    @return the narrowed mapping
    @throws EvidenceParseError when the value is not a string-keyed object
    """
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _invalid(where, "expected an object")
    return cast("dict[str, object]", value)


def _sequence(value: object, where: str) -> list[object]:
    """Narrow one JSON value to a list.

    @param value candidate list
    @param where diagnostic path
    @return the narrowed list
    @throws EvidenceParseError when the value is not a list
    """
    if not isinstance(value, list):
        _invalid(where, "expected an array")
    return cast("list[object]", value)


def _strings(value: object, where: str) -> tuple[str, ...]:
    """Parse an array of non-empty unique strings.

    @param value candidate array
    @param where diagnostic path
    @return strings in authored order
    @throws EvidenceParseError when an entry is empty, non-string, or repeated
    """
    values = tuple(
        _nonempty(item, f"{where}[{index}]") for index, item in enumerate(_sequence(value, where))
    )
    if len(values) != len(set(values)):
        _invalid(where, "entries must be unique")
    return values


def _nonempty(value: object, where: str) -> str:
    """Parse a non-empty string.

    @param value candidate string
    @param where diagnostic path
    @return stripped string
    @throws EvidenceParseError when it carries no text
    """
    if not isinstance(value, str) or not value.strip():
        _invalid(where, "expected a non-empty string")
    return value.strip()


def _integer(value: object, where: str) -> int:
    """Parse an integer while excluding booleans.

    @param value candidate integer
    @param where diagnostic path
    @return integer value
    @throws EvidenceParseError when the value is not an integer
    """
    if isinstance(value, bool) or not isinstance(value, int):
        _invalid(where, "expected an integer")
    return value


def _enum(kind: type[_EnumT], value: object, where: str) -> _EnumT:
    """Parse one string-backed enumeration value.

    @param kind enumeration type
    @param value candidate value
    @param where diagnostic path
    @return matching enumeration member
    @throws EvidenceParseError when the value is outside the vocabulary
    """
    text = _nonempty(value, where)
    try:
        return kind(text)
    except ValueError as problem:
        expected = ", ".join(member.value for member in kind)
        detail = f"expected one of {expected}; got {text!r}"
        raise EvidenceParseError(where, detail) from problem


def _exact_fields(record: Mapping[str, object], expected: set[str], where: str) -> None:
    """Require an object to carry exactly the schema's fields.

    @param record object being checked
    @param expected complete field set
    @param where diagnostic path
    @throws EvidenceParseError on the first missing or unknown field set
    """
    missing = sorted(expected - record.keys())
    unknown = sorted(record.keys() - expected)
    if missing or unknown:
        parts = []
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        if unknown:
            parts.append(f"unknown {', '.join(unknown)}")
        _invalid(where, "; ".join(parts))


def _invalid(where: str, detail: str) -> Never:
    """Raise one consistently shaped structural error.

    @param where JSON path carrying the invalid value
    @param detail violated requirement
    @return never; this helper always raises
    @throws EvidenceParseError always
    """
    raise EvidenceParseError(where, detail)
