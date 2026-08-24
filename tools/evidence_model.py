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
        # Treat every machine-executed verifier state as automated, including mixed tools.
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
        # Structured review alone requires human judgment; every other kind executes mechanically.
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
        # Retain the structured JSON path independently of the formatted exception message.
        self.where = where
        # Retain the violated requirement for callers that need machine-readable detail.
        self.detail = detail
        super().__init__(f"{where}: {detail}")


def load_evidence(path: Path = EVIDENCE_PATH) -> EvidenceRegistry:
    """Read and structurally validate one authored registry.

    @param path JSON registry to read
    @return a typed registry whose nested fields are all present and recognized
    @throws EvidenceParseError when JSON or any field violates the schema
    """
    # Translate filesystem and JSON failures into the registry's stable structural error type.
    try:
        # Decode without narrowing so every schema assumption remains explicit below.
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    # Preserve the originating read or decoder failure as the exception cause.
    except (OSError, json.JSONDecodeError) as problem:
        # Localize the failure to the registry file before crossing the parser boundary.
        raise EvidenceParseError(str(path), str(problem)) from problem
    # Narrow the document root before any keyed schema access.
    root = _mapping(raw, "registry")
    _exact_fields(root, {"schema_version", "rules"}, "registry")
    version = _integer(root["schema_version"], "registry.schema_version")
    # Reject unknown schema versions rather than interpreting them with v1 semantics.
    if version != 1:
        _invalid("registry.schema_version", f"expected 1, got {version}")
    raw_rules = _mapping(root["rules"], "registry.rules")
    # Treat parsed as mapping elements whose keys are stable rule ids and whose values are typed
    # evidence records; authored key order is preserved for deterministic diagnostics.
    parsed: dict[str, RuleEvidence] = {}
    # Parse each authored rule record under a path retaining its stable id.
    for rule_id, value in raw_rules.items():
        # Store the typed record under the same id used by normative joins.
        parsed[rule_id] = _rule_evidence(rule_id, value)
    # Publish a registry only after every nested record has validated.
    return EvidenceRegistry(schema_version=version, rules=parsed)


def load_observations(path: Path = OBSERVATIONS_PATH) -> ObservationRegistry:
    """Read and structurally validate the named field observations.

    @param path JSON registry to read
    @return typed observations addressable by stable evidence id
    @throws EvidenceParseError when JSON or a field violates the contract
    """
    # Translate filesystem and JSON failures into the observation registry's stable error type.
    try:
        # Decode without narrowing so all observation schema assumptions remain explicit.
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    # Preserve the originating read or decoder failure as the exception cause.
    except (OSError, json.JSONDecodeError) as problem:
        # Localize the failure to the observation file before crossing the parser boundary.
        raise EvidenceParseError(str(path), str(problem)) from problem
    # Narrow the document root before keyed schema access.
    root = _mapping(raw, "observations")
    _exact_fields(root, {"schema_version", "observations"}, "observations")
    version = _integer(root["schema_version"], "observations.schema_version")
    # Reject unknown schema versions rather than interpreting them with v1 semantics.
    if version != 1:
        _invalid("observations.schema_version", f"expected 1, got {version}")
    # Preserve records element values in deterministic source order.
    records = _mapping(root["observations"], "observations.observations")
    # Map each stable observation id to its typed record in authored order.
    parsed: dict[str, FieldObservation] = {}
    # Validate each observation independently while retaining its registry key in diagnostics.
    for observation_id, value in records.items():
        # Store the typed observation under the same id referenced by rule evidence.
        parsed[observation_id] = _field_observation(observation_id, value)
    # Publish the observation registry only after all references are structurally usable.
    return ObservationRegistry(schema_version=version, observations=parsed)


def _field_observation(observation_id: str, value: object) -> FieldObservation:
    """Parse one field observation with its reproduction boundary intact.

    @param observation_id stable id supplied by the registry key
    @param value untrusted JSON value beneath that key
    @return typed observation
    """
    # Build the diagnostic prefix once so every nested failure names the same record.
    where = f"observations.{observation_id}"
    # Enforce the versioned observation-id grammar before parsing its body.
    if _OBSERVATION_ID.fullmatch(observation_id) is None:
        _invalid(where, "expected V<major>E-NNN")
    # Narrow the record before exact-field validation and member access.
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
    # Preserve each authored evidence location in declaration order.
    locations = _strings(record["observed_in"], f"{where}.observed_in")
    # A field observation without any resolvable location cannot support an audit.
    if not locations:
        _invalid(f"{where}.observed_in", "at least one evidence location is required")
    # Preserve explicit null as the distinction between observed and reproducible evidence.
    reproduction = record["reproduction"]
    # Validate reproduction text only when the author claims one exists.
    if reproduction is not None:
        # Narrow the optional value to a non-empty command or procedure.
        reproduction = _nonempty(reproduction, f"{where}.reproduction")
    # Assemble the immutable observation after every member has been validated.
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
    # Build one diagnostic prefix tying every nested error to the normative rule id.
    where = f"rules.{rule_id}"
    # Narrow the record before exact-field validation and member access.
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
    # Preserve each governed unit in authored order while validating the controlled vocabulary.
    units = tuple(
        # Each indexed item becomes one UnitKind with its exact JSON path retained on failure.
        _enum(UnitKind, item, f"{where}.units[{index}]")
        for index, item in enumerate(_sequence(record["units"], f"{where}.units"))
    )
    # Evidence must state whether the rule governs applications, components, or both.
    if not units:
        _invalid(f"{where}.units", "at least one governed unit is required")
    # Preserve capability names in authored order for later scope validation.
    capabilities = _strings(record["capabilities"], f"{where}.capabilities")
    # Each invalid element is one capability name rejected by the grammar; declaration order is
    # preserved for the error.
    invalid = [name for name in capabilities if _CAPABILITY.fullmatch(name) is None]
    if invalid:
        _invalid(f"{where}.capabilities", f"invalid name {invalid[0]!r}")
    # Parse source warrants in authored order because their sequence is review-significant.
    warrants = tuple(
        _warrant(item, f"{where}.warrants[{index}]")
        for index, item in enumerate(_sequence(record["warrants"], f"{where}.warrants"))
    )
    # Parse verification strategies in authored order for deterministic joins and publication.
    strategies = tuple(
        _strategy(item, f"{where}.strategies[{index}]")
        for index, item in enumerate(_sequence(record["strategies"], f"{where}.strategies"))
    )
    # Assemble the immutable rule record only after all nested structures validate.
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
    # Narrow the warrant object before enforcing its complete field set.
    record = _mapping(value, where)
    _exact_fields(record, {"source", "relation", "confidence"}, where)
    # Assemble the warrant while validating its source and controlled vocabularies.
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
    # Narrow the strategy object before enforcing its complete field set.
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
    # Preserve explicit null for structured reviews that have no executable rejection fixture.
    rejected = record["must_reject"]
    # Automated rejection text, when present, must identify a non-empty witness.
    if rejected is not None:
        # Narrow the optional rejection marker before constructing the strategy.
        rejected = _nonempty(rejected, f"{where}.must_reject")
    # Preserve supported platform ids in declaration order.
    platforms = _strings(record["platforms"], f"{where}.platforms")
    # Every verification strategy must declare at least one supported execution platform.
    if not platforms:
        _invalid(f"{where}.platforms", "at least one platform is required")
    # Assemble the immutable strategy after its proposition, witness, and scope validate.
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
    # Narrow the migration object before enforcing its complete historical fields.
    record = _mapping(value, where)
    _exact_fields(record, {"source", "disposition", "guidance"}, where)
    # Assemble the stable-id history after its controlled disposition validates.
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
    # Treat normative as mapping elements whose keys are stable rule ids and whose values are
    # canonical Rule records; input order is preserved but set joins below define comparison order.
    normative = {rule.rule_id: rule for rule in rules}
    # Each findings element is one cross-record mismatch; sorted rule-id order is preserved.
    findings = [
        EvidenceFinding("E001", rule_id, "rule has no evidence record")
        # Each missing normative id contributes exactly one absent-evidence finding.
        for rule_id in sorted(normative.keys() - registry.rules.keys())
    ]
    # Add orphan evidence records after missing records to keep diagnostic categories stable.
    findings.extend(
        EvidenceFinding("E002", rule_id, "evidence names no normative rule")
        # Each orphan registry id contributes exactly one absent-rule finding.
        for rule_id in sorted(registry.rules.keys() - normative.keys())
    )
    # Validate only ids present on both sides after reporting each unmatched side.
    for rule_id in sorted(normative.keys() & registry.rules.keys()):
        # Select the canonical heading for this joined stable id.
        rule = normative[rule_id]
        # Select its authored evidence record from the same joined stable id.
        evidence = registry.rules[rule_id]
        findings.extend(_validate_record(rule, evidence, discriminated, observation_ids))
    # Return all mismatches instead of truncating the evidence audit at first failure.
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
    # Each findings element is one mismatch for this rule; validation order is preserved.
    findings: list[EvidenceFinding] = []
    # Every active or historical rule requires at least one source relationship.
    if not evidence.warrants:
        findings.append(EvidenceFinding("E003", rule.rule_id, "rule names no warrant"))
    findings.extend(_unresolved_observations(evidence, observation_ids))
    # Count heading mechanisms so duplicate declarations remain semantically visible.
    declared = Counter(rule.mechanisms)
    # Count evidence strategies by mechanism so multiplicity must match the heading exactly.
    evidenced = Counter(strategy.mechanism for strategy in evidence.strategies)
    # Reject missing, extra, or duplicated strategy mechanisms as the same join mismatch.
    if declared != evidenced:
        findings.append(
            EvidenceFinding(
                "E004",
                rule.rule_id,
                f"strategy mechanisms {dict(evidenced)} do not match heading {dict(declared)}",
            )
    )
    findings.extend(_retirement_findings(rule, evidence))
    # Validate every strategy independently so one rule can expose all evidence defects.
    for strategy in evidence.strategies:
        # Automated mechanisms require a declared negative witness.
        if strategy.is_automated and strategy.must_reject is None:
            findings.append(
                EvidenceFinding(
                    "E008", rule.rule_id, f"{strategy.mechanism} has no must-reject case"
                )
            )
        # When present, an automated witness must resolve to this exact rule/mechanism pair.
        if strategy.is_automated and strategy.must_reject is not None:
            # Derive the only admissible marker from the joined identity.
            expected_marker = f"discrimination:{rule.rule_id}/{strategy.mechanism}"
            # Reject markers that could lend another mechanism's observation as evidence.
            if strategy.must_reject != expected_marker:
                findings.append(
                    EvidenceFinding(
                        "E012",
                        rule.rule_id,
                        f"{strategy.mechanism} must-reject marker is not {expected_marker!r}",
                    )
                )
        # Generated placeholder prose is not an observable verification proposition.
        if strategy.is_automated and any(
            # Each placeholder is one forbidden generic phrase searched within the proposition.
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
        # Resolve mechanism-tag grammar to the evidence kinds it can honestly support.
        expected = _expected_kind(strategy.mechanism)
        # Reject a kind that overstates or contradicts how the mechanism executes.
        if strategy.kind not in expected:
            findings.append(
                EvidenceFinding(
                    "E010",
                    rule.rule_id,
                    f"{strategy.mechanism} cannot use kind {strategy.kind}",
                )
            )
    # Return the complete per-rule mismatch set in validation order.
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
    # Require the exact pair; rule-only coverage cannot certify sibling strategies.
    return (rule_id, mechanism) in discriminated


def _retirement_findings(rule: Rule, evidence: RuleEvidence) -> list[EvidenceFinding]:
    """Keep force, strategies, disposition, and successor history consistent.

    @param rule normative or historical heading
    @param evidence migration and strategy record joined to that heading
    @return every retirement/supersession mismatch
    """
    # Read historical disposition once for all force and successor consistency checks.
    disposition = evidence.migration.disposition
    # Collapse all inactive dispositions to the retirement truth required by the heading.
    retired = disposition in {
        MigrationDisposition.SUPERSEDED,
        MigrationDisposition.CONSOLIDATED,
        MigrationDisposition.RETIRED,
    }
    # Each findings element is one history inconsistency; check order is preserved.
    findings: list[EvidenceFinding] = []
    # Inactive rules cannot retain verification strategies for current behavior.
    if retired and evidence.strategies:
        findings.append(EvidenceFinding("E005", rule.rule_id, "retired rule has strategies"))
    # Migration disposition and normative force must agree on whether the rule is active.
    if retired is not (rule.force is Force.RETIRED):
        findings.append(
            EvidenceFinding(
                "E006", rule.rule_id, "retired force and migration disposition disagree"
            )
        )
    # A heading naming a successor must have an inactive historical disposition.
    if rule.superseded_by is not None and not retired:
        findings.append(
            EvidenceFinding("E006", rule.rule_id, "heading has a successor but migration is active")
        )
    # Replacement dispositions require the heading to identify what superseded this rule.
    if rule.superseded_by is None and disposition in {
        MigrationDisposition.SUPERSEDED,
        MigrationDisposition.CONSOLIDATED,
    }:
        findings.append(
            EvidenceFinding("E007", rule.rule_id, "replacement disposition names no successor")
        )
    # Return every independently actionable historical mismatch.
    return findings


def _unresolved_observations(
    evidence: RuleEvidence, observation_ids: AbstractSet[str] | None
) -> list[EvidenceFinding]:
    """Report field-evidence references only when a registry was supplied.

    @param evidence rule record carrying zero or more observation IDs
    @param observation_ids complete resolvable ID set, or None for legacy callers
    @return one finding per unresolved reference
    """
    # Legacy callers that supplied no registry cannot support a resolution claim.
    if observation_ids is None:
        # Preserve backward compatibility by declining the optional cross-registry check.
        return []
    # Emit one stable mismatch for each authored reference absent from the registry.
    return [
        EvidenceFinding("E011", evidence.rule_id, f"observation {observation} does not resolve")
        # Each referenced observation id is checked without reordering authored evidence.
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
    # Historical disposition dominates every active-strategy classification.
    if evidence.migration.disposition in {
        MigrationDisposition.SUPERSEDED,
        MigrationDisposition.CONSOLIDATED,
        MigrationDisposition.RETIRED,
    }:
        # Represent inactive stable ids without implying any current verifier.
        state = VerificationState.RETIRED
    # Active evidence with no strategy has not declared how the rule is verified.
    elif not evidence.strategies:
        # Distinguish missing strategy declaration from a named but absent implementation.
        state = VerificationState.UNDECLARED
    # A named local mechanism absent from the repository makes the strategy unbuilt.
    elif any(
        # Each strategy must resolve against its own rule id and repository root.
        mechanism_is_implemented(strategy.mechanism, root, rule.rule_id) is False
        for strategy in evidence.strategies
    ):
        # Do not infer partial availability when any required verifier is absent.
        state = VerificationState.UNBUILT
    else:
        # Collect unique kinds element values; their order is deliberately unordered.
        kinds = {strategy.kind for strategy in evidence.strategies}
        # Purely human judgment remains distinct from every executable verifier state.
        if kinds == {MechanismKind.STRUCTURED_REVIEW}:
            # Record the human-only classification selected by the homogeneous kind set.
            state = VerificationState.STRUCTURED_REVIEW
        # Mixed review or multiple executable classes require an aggregate presentation.
        elif MechanismKind.STRUCTURED_REVIEW in kinds or (
            MechanismKind.TOOL in kinds and len(kinds) > 1
        ):
            # Record that no single verifier class describes the combined strategy set.
            state = VerificationState.MIXED_VERIFIERS
        # A homogeneous tool-only strategy is externally delegated.
        elif kinds == {MechanismKind.TOOL}:
            # Record external delegation without implying that the tool ran successfully.
            state = VerificationState.EXTERNAL_VERIFIER
        else:
            # Remaining implemented check and fitness strategies execute inside the repository.
            state = VerificationState.LOCAL_VERIFIER
    # Return the classified availability without claiming the verifier passed this run.
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
    # Resolve the matrix from the requested repository rather than the caller's import path.
    source = root / "enforce" / "discrimination.py"
    # Absence means this repository publishes no trustworthy discrimination matrix.
    if not source.is_file():
        # Preserve None as distinct from a valid matrix that covers nothing.
        return None
    # Build an isolated module specification tied to the repository-local source file.
    spec = importlib.util.spec_from_file_location("_discipline_discrimination", source)
    # A missing specification or loader makes the matrix unexecutable.
    if spec is None or spec.loader is None:
        # Decline evidence rather than falling back to an ambient module.
        return None
    # Instantiate the isolated module before registering it for dataclass resolution.
    discrimination = importlib.util.module_from_spec(spec)
    # ``dataclass(slots=True)`` resolves the defining module during execution.
    sys.modules[spec.name] = discrimination
    # Treat authored matrix execution as untrusted evidence and always clear module state.
    try:
        spec.loader.exec_module(discrimination)
        # Resolve only the zero-argument evidence getter requested by the caller.
        getter: object = getattr(discrimination, getter_name, None)
        # A missing or non-callable getter indicates an incompatible matrix surface.
        if not callable(getter):
            # Decline the incompatible evidence API without guessing a fallback.
            return None
        # Invoke the validated getter while the repository-local module remains registered.
        result: object = getter()
    # Any authored-code failure makes the matrix untrustworthy as evidence.
    except Exception:  # ruff: ignore[blind-except] - authored matrix is input
        # Collapse execution defects to unavailable evidence at this query boundary.
        return None
    finally:
        # Remove the temporary module so later repositories cannot reuse its definitions.
        sys.modules.pop(spec.name, None)
    # Return the opaque value for caller-specific structural validation.
    return result


def discrimination_covered(root: Path = REPO_ROOT) -> frozenset[str] | None:
    """Load rule ids that have at least one declared mutation.

    ``None`` means there is no trustworthy matrix; an empty set means a matrix
    loaded and declared no rules.

    @param root repository whose matrix supplies the evidence
    @return witnessed stable ids, or None when the matrix is absent or malformed
    """
    # Ask the repository-local matrix for its covered rule-id set.
    result = _discrimination_value(root, "covered")
    # Require a set-like collection containing only stable textual ids.
    if not isinstance(result, (set, frozenset)) or not all(
        isinstance(item, str) for item in result
    ):
        # Treat malformed and unavailable matrices identically as untrusted evidence.
        return None
    # Freeze a valid result so callers cannot mutate evidence returned by authored code.
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
    # Ask the repository-local matrix for raw rule/mechanism witness pairs.
    result = _discrimination_value(root, "covered_strategies")
    # Exact strategy resolution starts only from a set-like matrix result.
    if not isinstance(result, (set, frozenset)):
        # Reject legacy or malformed getter values without coercion.
        return None
    # Collect unique raw element values; their order is deliberately unordered.
    raw: set[DiscriminationWitness] = set()
    for item in result:
        # Require every raw witness to be a two-part tuple of strings.
        if not (
            isinstance(item, tuple)
            and len(item) == _WITNESS_PARTS
            and all(isinstance(part, str) for part in item)
        ):
            # One malformed witness invalidates the matrix as a whole.
            return None
        raw.add(item)

    # Join raw entries to the same repository's evidence declarations.
    try:
        # Load exact automated strategies from the repository under inspection.
        registry = load_evidence(root / "discipline" / "meta" / "evidence.json")
    # Missing or malformed evidence prevents trustworthy mechanism attribution.
    except (EvidenceParseError, OSError):
        # Decline all strategy witnesses rather than using an ambient registry.
        return None
    # Treat automated as mapping elements whose keys are stable rule ids and whose values are
    # mechanism tuples in evidence order; key order is preserved but not semantically significant.
    automated = {
        # Each tuple contains only automated mechanism names declared for that rule.
        rule_id: tuple(
            # Each strategy contributes its exact tag only when machine-executed.
            strategy.mechanism for strategy in record.strategies if strategy.is_automated
        )
        # Each evidence record establishes one rule's admissible candidates.
        for rule_id, record in registry.rules.items()
    }
    # Collect unique witnesses element values; their order is deliberately unordered.
    witnesses: set[DiscriminationWitness] = set()
    for rule_id, mechanism in raw:
        # Resolve the raw entry against automated candidates declared for the same rule.
        candidates = automated.get(rule_id, ())
        # Ignore retired and review-only rules that expose no current automated strategy.
        if not candidates:
            # Continue resolving independent active entries.
            continue
        # Explicit mechanism attribution must match the joined evidence record.
        if mechanism:
            # Reject stale and cross-rule mechanism names.
            if mechanism not in candidates:
                # One false attribution invalidates all evidence from this matrix.
                return None
            witnesses.add((rule_id, mechanism))
        # Legacy shorthand is admissible only when exactly one candidate exists.
        elif len(candidates) == 1:
            witnesses.add((rule_id, candidates[0]))
        else:
            # Refuse to guess which sibling strategy the mutation observed.
            return None
    # Freeze exact pairs after every raw entry resolves without ambiguity.
    return frozenset(witnesses)


def _expected_kind(mechanism: str) -> frozenset[MechanismKind]:
    """Mechanism kinds compatible with one heading tag.

    @param mechanism heading tag
    @return allowed evidence kinds; empty when the tag grammar is unknown
    """
    # Read only the mechanism grammar prefix while preserving exact review tags below.
    prefix = mechanism.partition(":")[0]
    # Native checks may provide static or generated-drift evidence.
    if prefix == "check":
        # Return both admissible kinds because the specific check selects between them.
        return frozenset({MechanismKind.STATIC, MechanismKind.GENERATED_DRIFT})
    # Fitness tests may observe behavior or generated artifact drift.
    if prefix == "fitness":
        # Return both admissible kinds because the named node determines the relation.
        return frozenset({MechanismKind.BEHAVIORAL, MechanismKind.GENERATED_DRIFT})
    # Auto tags delegate their verdict to a configured external tool.
    if prefix == "auto":
        # Restrict auto evidence to the external-tool kind.
        return frozenset({MechanismKind.TOOL})
    # The exact review tag identifies a structured human judgment.
    if mechanism == "review":
        # Restrict review evidence to structured review rather than machine execution.
        return frozenset({MechanismKind.STRUCTURED_REVIEW})
    # Unknown mechanism grammar has no honest compatible evidence kind.
    return frozenset()


def _mapping(value: object, where: str) -> dict[str, object]:
    """Narrow one JSON value to a string-keyed mapping.

    @param value candidate mapping
    @param where diagnostic path
    @return the narrowed mapping
    @throws EvidenceParseError when the value is not a string-keyed object
    """
    # Require both object shape and textual keys before exposing mapping operations.
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _invalid(where, "expected an object")
    # Narrow only after the runtime key contract has been established.
    return cast("dict[str, object]", value)


def _sequence(value: object, where: str) -> list[object]:
    """Narrow one JSON value to a list.

    @param value candidate list
    @param where diagnostic path
    @return the narrowed list
    @throws EvidenceParseError when the value is not a list
    """
    # JSON arrays alone preserve the authored element order required by nested paths.
    if not isinstance(value, list):
        _invalid(where, "expected an array")
    # Narrow only after confirming the mutable JSON array representation.
    return cast("list[object]", value)


def _strings(value: object, where: str) -> tuple[str, ...]:
    """Parse an array of non-empty unique strings.

    @param value candidate array
    @param where diagnostic path
    @return strings in authored order
    @throws EvidenceParseError when an entry is empty, non-string, or repeated
    """
    # Preserve authored order while validating every indexed item as non-empty text.
    values = tuple(
        # Each item retains its array index in any structural diagnostic.
        _nonempty(item, f"{where}[{index}]") for index, item in enumerate(_sequence(value, where))
    )
    # Duplicate entries would make scope and evidence multiplicity ambiguous.
    if len(values) != len(set(values)):
        _invalid(where, "entries must be unique")
    # Return the immutable authored sequence after uniqueness validation.
    return values


def _nonempty(value: object, where: str) -> str:
    """Parse a non-empty string.

    @param value candidate string
    @param where diagnostic path
    @return stripped string
    @throws EvidenceParseError when it carries no text
    """
    # Reject non-text and whitespace-only values at their exact JSON path.
    if not isinstance(value, str) or not value.strip():
        _invalid(where, "expected a non-empty string")
    # Normalize surrounding whitespace while retaining internal authored text.
    return value.strip()


def _integer(value: object, where: str) -> int:
    """Parse an integer while excluding booleans.

    @param value candidate integer
    @param where diagnostic path
    @return integer value
    @throws EvidenceParseError when the value is not an integer
    """
    # JSON booleans are Python integers but cannot stand in for schema versions.
    if isinstance(value, bool) or not isinstance(value, int):
        _invalid(where, "expected an integer")
    # Return the unchanged validated integer.
    return value


def _enum(kind: type[_EnumT], value: object, where: str) -> _EnumT:
    """Parse one string-backed enumeration value.

    @param kind enumeration type
    @param value candidate value
    @param where diagnostic path
    @return matching enumeration member
    @throws EvidenceParseError when the value is outside the vocabulary
    """
    # Validate textual shape before delegating vocabulary membership to the enum.
    text = _nonempty(value, where)
    # Translate enum construction failures into path-aware evidence diagnostics.
    try:
        # Return the matching controlled-vocabulary member on the success path.
        return kind(text)
    # Retain the rejected value and admissible vocabulary when membership fails.
    except ValueError as problem:
        # Format expected enum values in their declaration order for direct repair.
        expected = ", ".join(member.value for member in kind)
        # Preserve both vocabulary and actual text in the structural detail.
        detail = f"expected one of {expected}; got {text!r}"
        # Chain the native enum failure beneath the repository-specific parse error.
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
    # Compute missing fields in sorted order for deterministic diagnostics.
    missing = sorted(expected - record.keys())
    # Compute unknown fields separately so both schema deviations can be reported together.
    unknown = sorted(record.keys() - expected)
    # Build a diagnostic only when the actual field set differs from the schema.
    if missing or unknown:
        # Each parts element is one missing- or unknown-field diagnostic fragment; category order
        # is preserved before joining.
        parts = []
        # Emit the absent-field fragment before any unknown-field fragment.
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        # Retain all surplus fields instead of silently ignoring forward-incompatible data.
        if unknown:
            parts.append(f"unknown {', '.join(unknown)}")
        # Raise one localized structural error containing both independently useful fragments.
        _invalid(where, "; ".join(parts))


def _invalid(where: str, detail: str) -> Never:
    """Raise one consistently shaped structural error.

    @param where JSON path carrying the invalid value
    @param detail violated requirement
    @return never; this helper always raises
    @throws EvidenceParseError always
    """
    # Centralize structural failure construction so every parser reports the same shape.
    raise EvidenceParseError(where, detail)
