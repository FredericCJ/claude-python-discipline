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

# Import annotation-only protocols without adding runtime dependencies.
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
## Each element is one forbidden placeholder fragment that cannot identify an observable
## proposition; tuple order is deliberately irrelevant.
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
        # Return true only when no structured judgment remains in the strategy to the caller.
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
    ## Each element is one supported platform id; declaration order is preserved.
    platforms: tuple[str, ...]
    ## Explicit condition under which the strategy may report not-applicable.
    not_applicable: str

    @property
    def is_automated(self) -> bool:
        """Whether the strategy is expected to produce a machine verdict.

        @return false only for a structured review
        """
        # Return false only for a structured review to the caller.
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
    ## Each element is one repository-subject kind to which the rule applies; declaration order
    ## is preserved.
    units: tuple[UnitKind, ...]
    ## Local capabilities that activate the rule; empty means unconditional.
    ## Each element is one local capability name that activates the rule; declaration order is
    ## preserved.
    capabilities: tuple[str, ...]
    ## Consequence the rule is intended to prevent or contain.
    failure_mode: str
    ## Sources and observations that make the obligation plausible.
    ## Each element is one source or observation warrant; authored evidence order is preserved.
    warrants: tuple[Warrant, ...]
    ## One exact observable strategy for every heading mechanism.
    ## Each element is one mechanism-specific verification strategy; declaration order is
    ## preserved.
    strategies: tuple[Strategy, ...]
    ## Field-evidence identifiers from independent adopters or audits.
    ## Each element is one independent field-observation id; declaration order is preserved.
    observations: tuple[str, ...]
    ## Stable-id relationship to the preceding corpus.
    migration: Migration


@dataclass(frozen=True, slots=True)
class EvidenceRegistry:
    """The complete authored evidence layer."""

    ## Parser contract version, independent of the discipline release number.
    schema_version: int
    ## Every evidence record keyed by its stable rule id.
    ## Treat rules as mapping elements whose keys identify fields and values carry their
    ## content; key order is deliberately unused.
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
    ## Each element names one commit, ledger, or audit containing the observation; declaration
    ## order is preserved.
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
    ## Treat observations as mapping elements whose keys identify fields and values carry their
    ## content; key order is deliberately unused.
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
        # Update   init   state only after the required source facts are available.
        self.where = where
        # Update   init   state only after the required source facts are available.
        self.detail = detail
        super().__init__(f"{where}: {detail}")


def load_evidence(path: Path = EVIDENCE_PATH) -> EvidenceRegistry:
    """Read and structurally validate one authored registry.

    @param path JSON registry to read
    @return a typed registry whose nested fields are all present and recognized
    @throws EvidenceParseError when JSON or any field violates the schema
    """
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Retain the immutable source representation consumed by subsequent analysis.
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    # Bind problem to the current value used by the next load evidence decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (OSError, json.JSONDecodeError) as problem:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise EvidenceParseError(str(path), str(problem)) from problem
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = _mapping(raw, "registry")
    _exact_fields(root, {"schema_version", "rules"}, "registry")
    # Compute version using  integer for later load evidence logic.
    version = _integer(root["schema_version"], "registry.schema_version")
    # Select the guarded path only after `version != 1` is satisfied.
    if version != 1:
        _invalid("registry.schema_version", f"expected 1, got {version}")
    # Compute raw rules using  mapping for later load evidence logic.
    raw_rules = _mapping(root["rules"], "registry.rules")
    # Treat parsed as mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    parsed: dict[str, RuleEvidence] = {}
    # Treat the current rule id, value as the candidate element consumed by the enclosing
    # Details: transformation.
    # Process each candidate element in deterministic source order.
    for rule_id, value in raw_rules.items():
        # Update load evidence state only after the required source facts are available.
        parsed[rule_id] = _rule_evidence(rule_id, value)
    # Return a typed registry whose nested fields are all present and recognized to the caller.
    return EvidenceRegistry(schema_version=version, rules=parsed)


def load_observations(path: Path = OBSERVATIONS_PATH) -> ObservationRegistry:
    """Read and structurally validate the named field observations.

    @param path JSON registry to read
    @return typed observations addressable by stable evidence id
    @throws EvidenceParseError when JSON or a field violates the contract
    """
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Retain the immutable source representation consumed by subsequent analysis.
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    # Bind problem to the current value used by the next load observations decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (OSError, json.JSONDecodeError) as problem:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise EvidenceParseError(str(path), str(problem)) from problem
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = _mapping(raw, "observations")
    _exact_fields(root, {"schema_version", "observations"}, "observations")
    # Compute version using  integer for later load observations logic.
    version = _integer(root["schema_version"], "observations.schema_version")
    # Select the guarded path only after `version != 1` is satisfied.
    if version != 1:
        _invalid("observations.schema_version", f"expected 1, got {version}")
    # Preserve records element values in deterministic source order.
    records = _mapping(root["observations"], "observations.observations")
    # Treat parsed as mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    parsed: dict[str, FieldObservation] = {}
    # Treat the current observation id, value as the candidate element consumed by the enclosing
    # Details: transformation.
    # Process each candidate element in deterministic source order.
    for observation_id, value in records.items():
        # Update load observations state only after the required source facts are available.
        parsed[observation_id] = _field_observation(observation_id, value)
    # Return typed observations addressable by stable evidence id to the caller.
    return ObservationRegistry(schema_version=version, observations=parsed)


def _field_observation(observation_id: str, value: object) -> FieldObservation:
    """Parse one field observation with its reproduction boundary intact.

    @param observation_id stable id supplied by the registry key
    @param value untrusted JSON value beneath that key
    @return typed observation
    """
    # Derive where from f"observations.{observation_id}" for the next  field observation
    # Details: decision.
    where = f"observations.{observation_id}"
    # Use the absence path when  OBSERVATION ID.fullmatch(observation id) has no available
    # Details: value.
    if _OBSERVATION_ID.fullmatch(observation_id) is None:
        _invalid(where, "expected V<major>E-NNN")
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
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
    # Compute locations using  strings for later field observation logic.
    locations = _strings(record["observed_in"], f"{where}.observed_in")
    # Select the empty-or-disabled path when locations has no usable value.
    if not locations:
        _invalid(f"{where}.observed_in", "at least one evidence location is required")
    # Compute reproduction using record["reproduction"] for later field observation logic.
    reproduction = record["reproduction"]
    # Use the available-value path only when reproduction is present.
    if reproduction is not None:
        # Compute reproduction using  nonempty for later field observation logic.
        reproduction = _nonempty(reproduction, f"{where}.reproduction")
    # Return typed observation to the caller.
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
    # Compute where using f"rules.{rule_id}" for later rule evidence logic.
    where = f"rules.{rule_id}"
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
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
    # Treat the current units, index, item as the candidate element consumed by the enclosing
    # Details: transformation.
    units = tuple(
        _enum(UnitKind, item, f"{where}.units[{index}]")
        for index, item in enumerate(_sequence(record["units"], f"{where}.units"))
    )
    # Select the empty-or-disabled path when units has no usable value.
    if not units:
        _invalid(f"{where}.units", "at least one governed unit is required")
    # Compute capabilities using  strings for later rule evidence logic.
    capabilities = _strings(record["capabilities"], f"{where}.capabilities")
    # Each invalid element is one capability name rejected by the grammar; declaration order is
    # preserved for the error.
    invalid = [name for name in capabilities if _CAPABILITY.fullmatch(name) is None]
    # Handle the non-empty or enabled invalid state.
    if invalid:
        _invalid(f"{where}.capabilities", f"invalid name {invalid[0]!r}")
    # Treat the current warrants, index, item as the candidate element consumed by the enclosing
    # Details: transformation.
    warrants = tuple(
        _warrant(item, f"{where}.warrants[{index}]")
        for index, item in enumerate(_sequence(record["warrants"], f"{where}.warrants"))
    )
    # Treat the current strategies, index, item as the candidate element consumed by the
    # Details: enclosing transformation.
    strategies = tuple(
        _strategy(item, f"{where}.strategies[{index}]")
        for index, item in enumerate(_sequence(record["strategies"], f"{where}.strategies"))
    )
    # Return the typed record to the caller.
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
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    record = _mapping(value, where)
    _exact_fields(record, {"source", "relation", "confidence"}, where)
    # Return the typed warrant to the caller.
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
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
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
    # Compute rejected using record["must_reject"] for later strategy logic.
    rejected = record["must_reject"]
    # Use the available-value path only when rejected is present.
    if rejected is not None:
        # Compute rejected using  nonempty for later strategy logic.
        rejected = _nonempty(rejected, f"{where}.must_reject")
    # Compute platforms using  strings for later strategy logic.
    platforms = _strings(record["platforms"], f"{where}.platforms")
    # Select the empty-or-disabled path when platforms has no usable value.
    if not platforms:
        _invalid(f"{where}.platforms", "at least one platform is required")
    # Return the typed strategy to the caller.
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
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    record = _mapping(value, where)
    _exact_fields(record, {"source", "disposition", "guidance"}, where)
    # Return the typed migration to the caller.
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
        Each element is one canonical normative `Rule`; rule-id order is
        preserved during evidence comparison.
    @param discriminated exact rule/mechanism pairs
    @param observation_ids resolvable field-evidence ids, when the registry is available
    @return every mismatch in stable rule-id order
    """
    # Treat normative as mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    normative = {rule.rule_id: rule for rule in rules}
    # Each findings element is one emitted diagnostic mapping; checker order is preserved.
    findings = [
        EvidenceFinding("E001", rule_id, "rule has no evidence record")
        for rule_id in sorted(normative.keys() - registry.rules.keys())
    ]
    # Bind rule id to the current value used by the next validate evidence decision.
    findings.extend(
        EvidenceFinding("E002", rule_id, "evidence names no normative rule")
        for rule_id in sorted(registry.rules.keys() - normative.keys())
    )
    # Select rule id as the current element from sorted(normative.keys() &
    # Details: registry.rules.keys()) while validate evidence preserves traversal order.
    # Process each candidate element in deterministic source order.
    for rule_id in sorted(normative.keys() & registry.rules.keys()):
        # Compute rule using normative[rule_id] for later validate evidence logic.
        rule = normative[rule_id]
        # Compute evidence using registry.rules[rule_id] for later validate evidence logic.
        evidence = registry.rules[rule_id]
        findings.extend(_validate_record(rule, evidence, discriminated, observation_ids))
    # Return every mismatch in stable rule-id order to the caller.
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
    # Each findings element is one emitted diagnostic mapping; checker order is preserved.
    findings: list[EvidenceFinding] = []
    # Select the empty-or-disabled path when evidence.warrants has no usable value.
    if not evidence.warrants:
        findings.append(EvidenceFinding("E003", rule.rule_id, "rule names no warrant"))
    findings.extend(_unresolved_observations(evidence, observation_ids))
    # Compute declared using Counter for later validate record logic.
    declared = Counter(rule.mechanisms)
    # Select evidenced, strategy as the current element from evidence.strategies) while
    # Details: validate record preserves traversal order.
    evidenced = Counter(strategy.mechanism for strategy in evidence.strategies)
    # Select the guarded path only after `declared != evidenced` is satisfied.
    if declared != evidenced:
        findings.append(
            EvidenceFinding(
                "E004",
                rule.rule_id,
                f"strategy mechanisms {dict(evidenced)} do not match heading {dict(declared)}",
            )
        )
    findings.extend(_retirement_findings(rule, evidence))
    # Select strategy as the current element from evidence.strategies while  validate record
    # Details: preserves traversal order.
    # Process each candidate element in deterministic source order.
    for strategy in evidence.strategies:
        # Use the absence path when strategy.is automated and strategy.must reject has no
        # Details: available value.
        if strategy.is_automated and strategy.must_reject is None:
            findings.append(
                EvidenceFinding(
                    "E008", rule.rule_id, f"{strategy.mechanism} has no must-reject case"
                )
            )
        # Use the available-value path only when strategy.is automated and strategy.must reject
        # Details: is present.
        if strategy.is_automated and strategy.must_reject is not None:
            # Derive expected marker from f"discrimination:{rule.rule_id}/{strategy.mechanism}"
            # Details: for the next  validate record decision.
            expected_marker = f"discrimination:{rule.rule_id}/{strategy.mechanism}"
            # Select the guarded path only after `strategy.must_reject != expected_marker` is
            # Details: satisfied.
            if strategy.must_reject != expected_marker:
                findings.append(
                    EvidenceFinding(
                        "E012",
                        rule.rule_id,
                        f"{strategy.mechanism} must-reject marker is not {expected_marker!r}",
                    )
                )
        # Bind placeholder to the current value used by the next  validate record decision.
        # Select the guarded path only after `strategy.is_automated and any((placeholder in
        # Details: strategy.proposition for placeholder in _VAGUE_PROPOSITION))` is satisfied.
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
        # Require each automated strategy's exact rule/mechanism rejection witness.
        if strategy.is_automated and not _strategy_witnessed(
            rule.rule_id, strategy.mechanism, discriminated
        ):
            findings.append(
                EvidenceFinding(
                    "E009", rule.rule_id, f"{strategy.mechanism} is not witnessed rejecting"
                )
            )
        # Compute expected using  expected kind for later validate record logic.
        expected = _expected_kind(strategy.mechanism)
        # Select the guarded path only after `strategy.kind not in expected` is satisfied.
        if strategy.kind not in expected:
            findings.append(
                EvidenceFinding(
                    "E010",
                    rule.rule_id,
                    f"{strategy.mechanism} cannot use kind {strategy.kind}",
                )
            )
    # Return semantic mismatches for this pair to the caller.
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
    # Return whether rejection credit resolves to the caller.
    return (rule_id, mechanism) in discriminated


def _retirement_findings(rule: Rule, evidence: RuleEvidence) -> list[EvidenceFinding]:
    """Keep force, strategies, disposition, and successor history consistent.

    @param rule normative or historical heading
    @param evidence migration and strategy record joined to that heading
    @return every retirement/supersession mismatch
    """
    # Derive disposition from evidence.migration.disposition for the next  retirement findings
    # Details: decision.
    disposition = evidence.migration.disposition
    # Compute retired using disposition in { for later retirement findings logic.
    retired = disposition in {
        MigrationDisposition.SUPERSEDED,
        MigrationDisposition.CONSOLIDATED,
        MigrationDisposition.RETIRED,
    }
    # Each findings element is one emitted diagnostic mapping; checker order is preserved.
    findings: list[EvidenceFinding] = []
    # Select the guarded path only after `retired and evidence.strategies` is satisfied.
    if retired and evidence.strategies:
        findings.append(EvidenceFinding("E005", rule.rule_id, "retired rule has strategies"))
    # Select the guarded path only after `retired is not (rule.force is Force.RETIRED)` is
    # Details: satisfied.
    if retired is not (rule.force is Force.RETIRED):
        findings.append(
            EvidenceFinding(
                "E006", rule.rule_id, "retired force and migration disposition disagree"
            )
        )
    # Select the guarded path only after `rule.superseded_by is not None and (not retired)` is
    # Details: satisfied.
    if rule.superseded_by is not None and not retired:
        findings.append(
            EvidenceFinding("E006", rule.rule_id, "heading has a successor but migration is active")
        )
    # Select the guarded path only after `rule.superseded_by is None and disposition in
    # Details: {MigrationDisposition.SUPERSEDED, MigrationDisposition.CONSOLIDATED}` is satisfied.
    if rule.superseded_by is None and disposition in {
        MigrationDisposition.SUPERSEDED,
        MigrationDisposition.CONSOLIDATED,
    }:
        findings.append(
            EvidenceFinding("E007", rule.rule_id, "replacement disposition names no successor")
        )
    # Return every retirement/supersession mismatch to the caller.
    return findings


def _unresolved_observations(
    evidence: RuleEvidence, observation_ids: AbstractSet[str] | None
) -> list[EvidenceFinding]:
    """Report field-evidence references only when a registry was supplied.

    @param evidence rule record carrying zero or more observation IDs
    @param observation_ids complete resolvable ID set, or None for legacy callers
    @return one finding per unresolved reference
    """
    # Use the absence path when observation ids has no available value.
    if observation_ids is None:
        # Return one finding per unresolved reference to the caller.
        return []
    # Bind observation to the current value used by the next  unresolved observations decision.
    # Return one finding per unresolved reference to the caller.
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
    # Select the guarded path only after `evidence.migration.disposition in
    # Details: {MigrationDisposition.SUPERSEDED, MigrationDisposition.CONSOLIDATED,
    # Details: MigrationDisposition.RETIRED}` is satisfied.
    if evidence.migration.disposition in {
        MigrationDisposition.SUPERSEDED,
        MigrationDisposition.CONSOLIDATED,
        MigrationDisposition.RETIRED,
    }:
        # Compute state using VerificationState.RETIRED for later verification state logic.
        state = VerificationState.RETIRED
    # Select the empty-or-disabled path when evidence.strategies has no usable value.
    elif not evidence.strategies:
        # Derive state from VerificationState.UNDECLARED for the next verification state
        # Details: decision.
        state = VerificationState.UNDECLARED
    # Bind strategy to the current value used by the next verification state decision.
    # Select the guarded path only after `any((mechanism_is_implemented(strategy.mechanism,
    # Details: root, rule.rule_id) is False for strategy in evidence.strategies))` is satisfied.
    elif any(
        mechanism_is_implemented(strategy.mechanism, root, rule.rule_id) is False
        for strategy in evidence.strategies
    ):
        # Compute state using VerificationState.UNBUILT for later verification state logic.
        state = VerificationState.UNBUILT
    else:
        # Collect unique kinds element values; their order is deliberately unordered.
        kinds = {strategy.kind for strategy in evidence.strategies}
        # Select the guarded path only after `kinds == {MechanismKind.STRUCTURED_REVIEW}` is
        # Details: satisfied.
        if kinds == {MechanismKind.STRUCTURED_REVIEW}:
            # Derive state from VerificationState.STRUCTURED_REVIEW for the next verification
            # Details: state decision.
            state = VerificationState.STRUCTURED_REVIEW
        # Select the guarded path only after `MechanismKind.STRUCTURED_REVIEW in kinds or
        # Details: (MechanismKind.TOOL in kinds and len(kinds) > 1)` is satisfied.
        elif MechanismKind.STRUCTURED_REVIEW in kinds or (
            MechanismKind.TOOL in kinds and len(kinds) > 1
        ):
            # Derive state from VerificationState.MIXED_VERIFIERS for the next verification
            # Details: state decision.
            state = VerificationState.MIXED_VERIFIERS
        # Select the guarded path only after `kinds == {MechanismKind.TOOL}` is satisfied.
        elif kinds == {MechanismKind.TOOL}:
            # Derive state from VerificationState.EXTERNAL_VERIFIER for the next verification
            # Details: state decision.
            state = VerificationState.EXTERNAL_VERIFIER
        else:
            # Derive state from VerificationState.LOCAL_VERIFIER for the next verification state
            # Details: decision.
            state = VerificationState.LOCAL_VERIFIER
    # Return the honest strategy state to the caller.
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
    # Retain the immutable source representation consumed by subsequent analysis.
    source = root / "enforce" / "discrimination.py"
    # Select the regular-file path only when `not source.is_file()` is satisfied.
    if not source.is_file():
        # Return the returned value, or None when the matrix cannot be trusted to the caller.
        return None
    # Derive spec from importlib.util.spec from file location for the next  discrimination value
    # Details: decision.
    spec = importlib.util.spec_from_file_location("_discipline_discrimination", source)
    # Use the absence path when spec is None or spec.loader has no available value.
    if spec is None or spec.loader is None:
        # Return the returned value, or None when the matrix cannot be trusted to the caller.
        return None
    # Derive discrimination from importlib.util.module from spec for the next  discrimination
    # Details: value decision.
    discrimination = importlib.util.module_from_spec(spec)
    # ``dataclass(slots=True)`` resolves the defining module during execution.
    sys.modules[spec.name] = discrimination
    try:
        spec.loader.exec_module(discrimination)
        # Compute getter using getattr for later discrimination value logic.
        getter: object = getattr(discrimination, getter_name, None)
        # Select the empty-or-disabled path when callable(getter) has no usable value.
        if not callable(getter):
            # Return the returned value, or None when the matrix cannot be trusted to the
            # Details: caller.
            return None
        # Preserve the completed operation outcome for validation and publication.
        result: object = getter()
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except Exception:  # ruff: ignore[blind-except] - authored matrix is input
        # Return the returned value, or None when the matrix cannot be trusted to the caller.
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
    # Preserve the completed operation outcome for validation and publication.
    result = _discrimination_value(root, "covered")
    # Treat the current item as the candidate element consumed by the enclosing transformation.
    # Select the empty-or-disabled path when isinstance(result, (set, frozenset)) or not
    # Details: all((isinstance(item, str) for item in result)) has no usable value.
    if not isinstance(result, (set, frozenset)) or not all(
        isinstance(item, str) for item in result
    ):
        # Return witnessed stable ids, or None when the matrix is absent or malformed to the
        # Details: caller.
        return None
    # Return witnessed stable ids, or None when the matrix is absent or malformed to the caller.
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
    # Preserve the completed operation outcome for validation and publication.
    result = _discrimination_value(root, "covered_strategies")
    # Select the empty-or-disabled path when isinstance(result, (set, frozenset)) has no usable
    # Details: value.
    if not isinstance(result, (set, frozenset)):
        # Return exact pairs, or None for an absent, legacy, or malformed matrix to the caller.
        return None
    # Collect unique raw element values; their order is deliberately unordered.
    raw: set[DiscriminationWitness] = set()
    # Treat the current item as the candidate element consumed by the enclosing transformation.
    # Process each candidate element in deterministic source order.
    for item in result:
        # Bind part to the current value used by the next discrimination witnesses decision.
        # Reject witness entries unless they are fixed two-string tuples.
        if not (
            isinstance(item, tuple)
            and len(item) == _WITNESS_PARTS
            and all(isinstance(part, str) for part in item)
        ):
            # Return exact pairs, or None for an absent, legacy, or malformed matrix to the
            # Details: caller.
            return None
        raw.add(item)

    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute registry using load evidence for later discrimination witnesses logic.
        registry = load_evidence(root / "discipline" / "meta" / "evidence.json")
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (EvidenceParseError, OSError):
        # Return exact pairs, or None for an absent, legacy, or malformed matrix to the caller.
        return None
    # Treat automated as mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    automated = {
        rule_id: tuple(
            strategy.mechanism for strategy in record.strategies if strategy.is_automated
        )
        for rule_id, record in registry.rules.items()
    }
    # Collect unique witnesses element values; their order is deliberately unordered.
    witnesses: set[DiscriminationWitness] = set()
    # Select mechanism, rule id as the current element from raw while discrimination witnesses
    # Details: preserves traversal order.
    # Process each candidate element in deterministic source order.
    for rule_id, mechanism in raw:
        # Compute candidates using automated.get for later discrimination witnesses logic.
        candidates = automated.get(rule_id, ())
        # Select the empty-or-disabled path when candidates has no usable value.
        if not candidates:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Handle the non-empty or enabled mechanism state.
        if mechanism:
            # Select the guarded path only after `mechanism not in candidates` is satisfied.
            if mechanism not in candidates:
                # Return exact pairs, or None for an absent, legacy, or malformed matrix to the
                # Details: caller.
                return None
            witnesses.add((rule_id, mechanism))
        # Select the guarded path only after `len(candidates) == 1` is satisfied.
        elif len(candidates) == 1:
            witnesses.add((rule_id, candidates[0]))
        else:
            # Return exact pairs, or None for an absent, legacy, or malformed matrix to the
            # Details: caller.
            return None
    # Return exact pairs, or None for an absent, legacy, or malformed matrix to the caller.
    return frozenset(witnesses)


def _expected_kind(mechanism: str) -> frozenset[MechanismKind]:
    """Mechanism kinds compatible with one heading tag.

    @param mechanism heading tag
    @return allowed evidence kinds; empty when the tag grammar is unknown
    """
    # Compute prefix using mechanism.partition for later expected kind logic.
    prefix = mechanism.partition(":")[0]
    # Select the guarded path only after `prefix == 'check'` is satisfied.
    if prefix == "check":
        # Return allowed evidence kinds; empty when the tag grammar is unknown to the caller.
        return frozenset({MechanismKind.STATIC, MechanismKind.GENERATED_DRIFT})
    # Select the guarded path only after `prefix == 'fitness'` is satisfied.
    if prefix == "fitness":
        # Return allowed evidence kinds; empty when the tag grammar is unknown to the caller.
        return frozenset({MechanismKind.BEHAVIORAL, MechanismKind.GENERATED_DRIFT})
    # Select the guarded path only after `prefix == 'auto'` is satisfied.
    if prefix == "auto":
        # Return allowed evidence kinds; empty when the tag grammar is unknown to the caller.
        return frozenset({MechanismKind.TOOL})
    # Select the guarded path only after `mechanism == 'review'` is satisfied.
    if mechanism == "review":
        # Return allowed evidence kinds; empty when the tag grammar is unknown to the caller.
        return frozenset({MechanismKind.STRUCTURED_REVIEW})
    # Return allowed evidence kinds; empty when the tag grammar is unknown to the caller.
    return frozenset()


def _mapping(value: object, where: str) -> dict[str, object]:
    """Narrow one JSON value to a string-keyed mapping.

    @param value candidate mapping
    @param where diagnostic path
    @return the narrowed mapping
    @throws EvidenceParseError when the value is not a string-keyed object
    """
    # Treat the current key as the candidate element consumed by the enclosing transformation.
    # Select the empty-or-disabled path when isinstance(value, dict) or not all((isinstance(key,
    # Details: str) for key in value)) has no usable value.
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _invalid(where, "expected an object")
    # Return the narrowed mapping to the caller.
    return cast("dict[str, object]", value)


def _sequence(value: object, where: str) -> list[object]:
    """Narrow one JSON value to a list.

    @param value candidate list
    @param where diagnostic path
    @return the narrowed list
    @throws EvidenceParseError when the value is not a list
    """
    # Select the empty-or-disabled path when isinstance(value, list) has no usable value.
    if not isinstance(value, list):
        _invalid(where, "expected an array")
    # Return the narrowed list to the caller.
    return cast("list[object]", value)


def _strings(value: object, where: str) -> tuple[str, ...]:
    """Parse an array of non-empty unique strings.

    @param value candidate array
    @param where diagnostic path
    @return strings in authored order
    @throws EvidenceParseError when an entry is empty, non-string, or repeated
    """
    # Treat the current values, index, item as the candidate element consumed by the enclosing
    # Details: transformation.
    values = tuple(
        _nonempty(item, f"{where}[{index}]") for index, item in enumerate(_sequence(value, where))
    )
    # Select the guarded path only after `len(values) != len(set(values))` is satisfied.
    if len(values) != len(set(values)):
        _invalid(where, "entries must be unique")
    # Return strings in authored order to the caller.
    return values


def _nonempty(value: object, where: str) -> str:
    """Parse a non-empty string.

    @param value candidate string
    @param where diagnostic path
    @return stripped string
    @throws EvidenceParseError when it carries no text
    """
    # Select the empty-or-disabled path when isinstance(value, str) or not value.strip() has no
    # Details: usable value.
    if not isinstance(value, str) or not value.strip():
        _invalid(where, "expected a non-empty string")
    # Return stripped string to the caller.
    return value.strip()


def _integer(value: object, where: str) -> int:
    """Parse an integer while excluding booleans.

    @param value candidate integer
    @param where diagnostic path
    @return integer value
    @throws EvidenceParseError when the value is not an integer
    """
    # Select the guarded path only after `isinstance(value, bool) or not isinstance(value, int)`
    # Details: is satisfied.
    if isinstance(value, bool) or not isinstance(value, int):
        _invalid(where, "expected an integer")
    # Return integer value to the caller.
    return value


def _enum(kind: type[_EnumT], value: object, where: str) -> _EnumT:
    """Parse one string-backed enumeration value.

    @param kind enumeration type
    @param value candidate value
    @param where diagnostic path
    @return matching enumeration member
    @throws EvidenceParseError when the value is outside the vocabulary
    """
    # Retain the immutable source representation consumed by subsequent analysis.
    text = _nonempty(value, where)
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Return matching enumeration member to the caller.
        return kind(text)
    # Bind problem to the current value used by the next  enum decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except ValueError as problem:
        # Select expected, member as the current element from kind) while  enum preserves
        # Details: traversal order.
        expected = ", ".join(member.value for member in kind)
        # Derive detail from f"expected one of {expected}; got {text!r}" for the next  enum
        # Details: decision.
        detail = f"expected one of {expected}; got {text!r}"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise EvidenceParseError(where, detail) from problem


def _exact_fields(record: Mapping[str, object], expected: set[str], where: str) -> None:
    """Require an object to carry exactly the schema's fields.

    @param record object being checked
        Treat record as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @param expected complete field set
        Collect unique expected element values; their order is deliberately unordered.
    @param where diagnostic path
    @throws EvidenceParseError on the first missing or unknown field set
    """
    # Format the relationship labels whose generated graph count is zero.
    missing = sorted(expected - record.keys())
    # Compute unknown using sorted for later exact fields logic.
    unknown = sorted(record.keys() - expected)
    # Select the guarded path only after `missing or unknown` is satisfied.
    if missing or unknown:
        # Each parts element is one missing- or unknown-field diagnostic fragment; category order
        # is preserved before joining.
        parts = []
        # Handle the non-empty or enabled missing state.
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        # Handle the non-empty or enabled unknown state.
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
    # Propagate the localized failure so callers cannot mistake it for success.
    raise EvidenceParseError(where, detail)
