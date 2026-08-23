"""Validate repository-local operational completeness.

``operational-model.json`` joins the additive capability manifest to this
repository's architecture resources and recoveries, lifecycle phases, states,
budgets, observable terminal outcomes, build/runtime identity, and declared
platform support. It never models a peer, parent, or system topology.

The checker decides exact records, joins, and confined evidence references. It
does not claim that a named test asserts the stated behavior or that a numeric
budget is suitable; execution and adversarial review own those residuals.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Final, Never

from . import Check, Finding
from .architecture_model import ArchitectureError, ArchitectureModel
from .architecture_model import parse as parse_architecture
from .project import Capability

# Import collection protocols only for static annotations.
if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

## Stable lower-snake record identifiers.
IDENTIFIER: Final = re.compile(r"^[a-z][a-z0-9_]*$")
## Stable externally observable event-code grammar.
EVENT_CODE: Final = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
## Lifecycle-phase elements in required execution order.
LIFECYCLE_PHASES: Final = (
    "startup",
    "steady_state",
    "interruption",
    "drain",
    "shutdown",
    "forced_cleanup",
)
## Budget-class elements in deterministic declaration order, each bounded or inapplicable.
BUDGET_KINDS: Final = (
    "time",
    "memory",
    "queue",
    "retry",
    "input_size",
    "cleanup",
)
## Mapping from each budget-class key to an unordered set of accepted unit-name values;
## mapping insertion order follows ``BUDGET_KINDS``.
BUDGET_UNITS: Final[Mapping[str, frozenset[str]]] = {
    "time": frozenset({"milliseconds", "seconds"}),
    "memory": frozenset({"bytes", "kibibytes", "mebibytes"}),
    "queue": frozenset({"bytes", "items"}),
    "retry": frozenset({"attempts"}),
    "input_size": frozenset({"bytes", "characters", "items"}),
    "cleanup": frozenset({"items", "milliseconds", "seconds"}),
}
## Unordered owner-role set whose each element may own local operational behavior.
OWNER_ROLES: Final = frozenset({"domain", "application", "ports", "adapters", "shell"})
## Mapping from each true capability key to its unordered required-obligation value set;
## mapping insertion order follows ``Capability`` declaration order.
CAPABILITY_OBLIGATIONS: Final[Mapping[Capability, frozenset[str]]] = {
    Capability.PUBLIC_API: frozenset({"installed_surface", "structured_terminal_outcome"}),
    Capability.FILESYSTEM_IO: frozenset({"failure_translation", "resource_ownership"}),
    Capability.PERSISTENT_STATE: frozenset({
        "schema_compatibility", "migration", "single_writer", "corruption_recovery",
    }),
    Capability.GENERATED_ARTIFACTS: frozenset({
        "source_of_truth", "provenance", "lossless_round_trip",
        "independent_drift", "byte_stability",
    }),
    Capability.NETWORK_IO: frozenset({
        "malformed_input", "timeout", "backpressure", "disconnect",
        "ordering", "local_shutdown",
    }),
    Capability.LAUNCHES_SUBPROCESSES: frozenset({
        "command_identity", "launch_failure", "lifecycle_authority",
    }),
    Capability.OWNS_SUBPROCESS_LIFECYCLE: frozenset({
        "signal_routing", "graceful_stop", "timeout_escalation", "no_orphans",
    }),
    Capability.CONCURRENCY: frozenset({
        "ordering", "cancellation", "race", "bounded_queue",
    }),
    Capability.DESTRUCTIVE_EFFECTS: frozenset({"plan_apply", "interruption", "recovery"}),
    Capability.BOUNDED_LATENCY: frozenset({"latency_measurement"}),
    Capability.SENSITIVE_DATA: frozenset({
        "classification", "redaction", "least_exposure", "security_review",
    }),
}
## Mapping from each lifecycle-phase key to its unordered activating-capability value set;
## mapping insertion order follows runtime execution order.
PHASE_CAPABILITIES: Final[Mapping[str, frozenset[Capability]]] = {
    "startup": frozenset(Capability),
    "steady_state": frozenset(Capability),
    "interruption": frozenset({
        Capability.NETWORK_IO,
        Capability.OWNS_SUBPROCESS_LIFECYCLE,
        Capability.CONCURRENCY,
        Capability.DESTRUCTIVE_EFFECTS,
    }),
    "drain": frozenset({
        Capability.NETWORK_IO,
        Capability.OWNS_SUBPROCESS_LIFECYCLE,
        Capability.CONCURRENCY,
    }),
    "shutdown": frozenset(Capability),
    "forced_cleanup": frozenset({
        Capability.NETWORK_IO,
        Capability.OWNS_SUBPROCESS_LIFECYCLE,
    }),
}
## Mapping from each budget-class key to its unordered activating-capability value set;
## mapping insertion order follows ``BUDGET_KINDS``.
BUDGET_CAPABILITIES: Final[Mapping[str, frozenset[Capability]]] = {
    "time": frozenset({
        Capability.NETWORK_IO,
        Capability.OWNS_SUBPROCESS_LIFECYCLE,
        Capability.BOUNDED_LATENCY,
    }),
    "memory": frozenset({
        Capability.PERSISTENT_STATE,
        Capability.GENERATED_ARTIFACTS,
        Capability.NETWORK_IO,
    }),
    "queue": frozenset({Capability.NETWORK_IO, Capability.CONCURRENCY}),
    "retry": frozenset({
        Capability.NETWORK_IO,
        Capability.PERSISTENT_STATE,
        Capability.LAUNCHES_SUBPROCESSES,
    }),
    "input_size": frozenset({
        Capability.PUBLIC_API,
        Capability.PERSISTENT_STATE,
        Capability.NETWORK_IO,
    }),
    "cleanup": frozenset({
        Capability.FILESYSTEM_IO,
        Capability.NETWORK_IO,
        Capability.LAUNCHES_SUBPROCESSES,
        Capability.OWNS_SUBPROCESS_LIFECYCLE,
        Capability.CONCURRENCY,
        Capability.DESTRUCTIVE_EFFECTS,
    }),
}
## Unordered platform-name set whose each element requires an explicit support declaration.
PLATFORMS: Final = frozenset({"windows", "linux"})
## Unordered runtime-support set whose each element is distinct from an executed gate verdict.
RUNTIME_SUPPORT: Final = frozenset({"supported", "unsupported", "not_applicable"})
## Unordered development-support set whose each element forbids runtime non-applicability.
DEVELOPMENT_SUPPORT: Final = frozenset({"supported", "unsupported"})


class OperationalError(ValueError):
    """One stable operational-model diagnostic."""

    ## Stable diagnostic namespace for rejected operational-model propositions.
    code = "discipline.operational_model.invalid"

    def __init__(self, diagnostic_id: str, where: str, detail: str) -> None:
        """Build one actionable model failure.

        @param diagnostic_id stable mechanism diagnostic
        @param where JSON path or repository location
        @param detail explanation of the violated predicate
        """
        # Initialize the standard message from the stable id, JSON location, and detail.
        super().__init__(f"{diagnostic_id} {where}: {detail}")
        # Retain the mechanism diagnostic for deterministic rule selection.
        self.diagnostic_id = diagnostic_id
        # Retain the exact model or repository location that failed validation.
        self.where = where
        # Retain the actionable schema or semantic explanation.
        self.detail = detail


def _fail(diagnostic_id: str, where: str, detail: str) -> Never:
    """Raise one operational diagnostic.

    @param diagnostic_id stable mechanism diagnostic
    @param where JSON path or repository location
    @param detail explanation of the violated predicate
    @return never; this helper always raises
    @throws OperationalError unconditionally
    """
    # Translate the localized failure into the sole typed operational-error channel.
    raise OperationalError(diagnostic_id, where, detail)


def _object(value: object, where: str) -> Mapping[str, object]:
    """Require a JSON object.

    @param value untrusted decoded value
    @param where JSON path
    @return mapping whose each key is a field name and each value is decoded data;
        source order is preserved by the decoder
    """
    # Only a JSON object can supply named operational-model fields.
    if not isinstance(value, dict):
        # Reject scalar and array impostors without coercion.
        _fail("OPMODEL001_SCHEMA", where, "expected an object")
    # Return the decoded key/value mapping with source order intact.
    return value


def _exact(record: Mapping[str, object], fields: set[str], where: str) -> None:
    """Reject missing and ignored fields.

    @param record mapping whose each key names a field and each value is decoded data;
        mapping iteration order is deliberately unused
    @param fields unordered field-name set whose each element is required and accepted
    @param where JSON path
    @throws OperationalError when the field set differs
    """
    # Build an unordered set whose each element is a required field absent from the record.
    missing = fields - set(record)
    # Build an unordered set whose each element is an unrecognized record field.
    unknown = set(record) - fields
    # Missing and unknown fields both make the closed schema unsafe to interpret.
    if missing or unknown:
        # Reject the exact object before any partial field interpretation.
        _fail(
            "OPMODEL001_SCHEMA",
            where,
            f"missing={sorted(missing)}, unknown={sorted(unknown)}",
        )


def _text(value: object, where: str) -> str:
    """Require non-empty text.

    @param value untrusted decoded value
    @param where JSON path
    @return stripped text
    """
    # Require authored non-empty text rather than coercing scalar values.
    if not isinstance(value, str) or not value.strip():
        # Reject at the exact JSON path owning the contentless value.
        _fail("OPMODEL001_SCHEMA", where, "expected non-empty text")
    # Return normalized text with insignificant surrounding whitespace removed.
    return value.strip()


def _optional_text(value: object, where: str) -> str | None:
    """Require null or non-empty text.

    @param value untrusted decoded value
    @param where JSON path
    @return stripped text or None
    """
    # Preserve explicit absence; otherwise apply the ordinary text contract.
    return None if value is None else _text(value, where)


def _identifier(value: object, where: str) -> str:
    """Require one lower-snake identifier.

    @param value untrusted decoded value
    @param where JSON path
    @return validated identifier
    """
    # Parse and normalize the raw value as non-empty text first.
    text = _text(value, where)
    # Stable operational identifiers use one complete lower-snake lexical shape.
    if IDENTIFIER.fullmatch(text) is None:
        # Reject invalid spelling at the exact field path.
        _fail("OPMODEL001_SCHEMA", where, "expected lower_snake identifier")
    # Return the validated stable identifier.
    return text


def _records(
    value: object,
    where: str,
    *,
    allow_empty: bool = False,
) -> list[Mapping[str, object]]:
    """Require an array of objects.

    @param value untrusted decoded value
    @param where JSON path
    @param allow_empty true when an explicit empty array is meaningful; false when non-empty
    @return decoded object-record elements in source order
    """
    # Require an array and, unless explicitly permitted, at least one record element.
    if not isinstance(value, list) or (not value and not allow_empty):
        # Reject absent, scalar, and disallowed empty values at the exact path.
        _fail("OPMODEL001_SCHEMA", where, "expected a record array")
    # Parse each indexed object element while preserving authored source order.
    return [_object(item, f"{where}[{index}]") for index, item in enumerate(value)]


def _strings(value: object, where: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    """Require a unique string array.

    @param value untrusted decoded value
    @param where JSON path
    @param allow_empty true when an explicit empty array is meaningful; false when non-empty
    @return unique string elements in source order
    """
    # Require an array and, unless explicitly permitted, at least one string element.
    if not isinstance(value, list) or (not value and not allow_empty):
        # Reject absent, scalar, and disallowed empty values at the exact path.
        _fail("OPMODEL001_SCHEMA", where, "expected a string array")
    # Parse each indexed string element while preserving authored source order.
    values = tuple(_text(item, f"{where}[{index}]") for index, item in enumerate(value))
    # Duplicate elements cannot carry distinct operational meaning.
    if len(values) != len(set(values)):
        # Reject the complete array instead of silently deduplicating it.
        _fail("OPMODEL001_SCHEMA", where, "duplicate values are not allowed")
    # Return the validated unique sequence in authored order.
    return values


def _exclusive(
    present: str | None,
    absent: str | None,
    where: str,
    diagnostic_id: str,
) -> None:
    """Require exactly one evidence or non-applicability value.

    @param present executable evidence path
    @param absent explicit non-applicability rationale
    @param where JSON path
    @param diagnostic_id semantic diagnostic to raise
    @throws OperationalError unless exactly one value is present
    """
    # Evidence and non-applicability must form an exclusive, exhaustive disposition.
    if (present is None) == (absent is None):
        # Reject both omission and contradictory dual disposition.
        _fail(
            diagnostic_id,
            where,
            "exactly one of executable evidence and not_applicable is required",
        )


@dataclass(frozen=True, slots=True)
class ObligationEvidence:
    """One capability-specific required observation."""

    ## Stable obligation identifier from the generated map.
    obligation_id: str
    ## Exact local pytest node or review evidence path.
    evidence: str


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    """Architecture joins and evidence for one enabled capability."""

    ## Enabled capability.
    capability: Capability
    ## Architecture resource-id elements in authored order owned or transferred here.
    resources: tuple[str, ...]
    ## Explanation when it owns no resource.
    resource_absence: str | None
    ## Architecture recovery-id elements in authored order used by this capability.
    recoveries: tuple[str, ...]
    ## Explanation when it owns no recovery.
    recovery_absence: str | None
    ## Obligation-evidence elements in authored order, complete for the capability.
    tests: tuple[ObligationEvidence, ...]


@dataclass(frozen=True, slots=True)
class Lifecycle:
    """One phase of the repository-local runtime lifecycle."""

    ## Canonical lifecycle phase.
    phase: str
    ## Local role owning the phase transition.
    owner_role: str
    ## Observable local behavior.
    behavior: str
    ## Local state after the phase.
    terminal_state: str
    ## Executable evidence when applicable.
    test: str | None
    ## Rationale when the phase is not applicable.
    not_applicable: str | None


@dataclass(frozen=True, slots=True)
class OperationalState:
    """One safe or degraded repository-local state."""

    ## Stable state identifier.
    state_id: str
    ## Safe or degraded classification.
    kind: str
    ## Entry-condition text elements in authored evaluation order.
    entry_conditions: tuple[str, ...]
    ## Permitted-operation text elements in authored order, explicitly possibly empty.
    allowed_operations: tuple[str, ...]
    ## Structured event emitted on entry.
    observable_event: str
    ## Condition leaving the state or terminality statement.
    exit_condition: str


@dataclass(frozen=True, slots=True)
class Bound:
    """One positive quantitative limit."""

    ## Positive quantity.
    value: int | float
    ## Unit appropriate to the budget class.
    unit: str


@dataclass(frozen=True, slots=True)
class Budget:
    """One bounded or explicitly inapplicable operational cost."""

    ## Canonical budget class.
    kind: str
    ## Operation or resource to which the budget applies.
    scope: str
    ## Finite limit when applicable.
    bound: Bound | None
    ## Explanation when the budget class cannot apply.
    not_applicable: str | None
    ## Exact measurement evidence when bounded.
    measurement: str | None


@dataclass(frozen=True, slots=True)
class Outcome:
    """One observable terminal outcome, exceptional or ordinary."""

    ## Stable outcome identifier.
    outcome_id: str
    ## True when this outcome escapes through the exception channel; false when ordinary.
    exceptional: bool
    ## Condition producing the outcome.
    trigger: str
    ## Stable observable event code.
    event_code: str
    ## Correlation field carried by the event.
    correlation_field: str
    ## State id reached by the outcome.
    terminal_state: str
    ## Exact local behavioral evidence.
    test: str


@dataclass(frozen=True, slots=True)
class Identity:
    """Build source and runtime identity evidence."""

    ## Local source from which build identity is derived.
    build_source: str
    ## Runtime-diagnostic field-name elements in authored emission order.
    runtime_fields: tuple[str, ...]
    ## Exact local behavioral evidence.
    test: str


@dataclass(frozen=True, slots=True)
class PlatformSupport:
    """Runtime and development-tool support for one release platform."""

    ## Windows or Linux.
    name: str
    ## Supported, unsupported, or not applicable runtime state.
    runtime: str
    ## Supported or unsupported development-tool state.
    development: str
    ## Local evidence path when support is claimed.
    evidence: str | None
    ## Required explanation for any non-supported state.
    limitation: str | None


@dataclass(frozen=True, slots=True)
class OperationalModel:
    """Complete canonical operational view for one repository."""

    ## Capability-record elements in authored order for exactly the enabled capabilities.
    capability_records: tuple[CapabilityRecord, ...]
    ## Six lifecycle-record elements in canonical execution order.
    lifecycle: tuple[Lifecycle, ...]
    ## Safe and degraded state-record elements in authored order.
    states: tuple[OperationalState, ...]
    ## Six budget-record elements in canonical class order.
    budgets: tuple[Budget, ...]
    ## Exceptional and ordinary outcome-record elements in authored order.
    outcomes: tuple[Outcome, ...]
    ## Build and runtime identity.
    identity: Identity
    ## Windows and Linux support-record elements in authored order.
    platforms: tuple[PlatformSupport, ...]


def _obligation(record: Mapping[str, object], where: str) -> ObligationEvidence:
    """Parse one capability obligation record.

    @param record mapping whose each key names an obligation field and each value is decoded
        data; mapping iteration order is deliberately unused
    @param where JSON path
    @return typed evidence
    """
    # Close the obligation schema before interpreting its evidence path.
    _exact(record, {"id", "evidence"}, where)
    # Materialize the validated obligation identity and evidence spelling.
    return ObligationEvidence(
        obligation_id=_identifier(record["id"], f"{where}.id"),
        evidence=_text(record["evidence"], f"{where}.evidence"),
    )


def _capability_record(record: Mapping[str, object], where: str) -> CapabilityRecord:
    """Parse one enabled capability's joins and evidence.

    @param record mapping whose each key names a capability field and each value is decoded
        data; mapping iteration order is deliberately unused
    @param where JSON path
    @return typed record
    """
    # Define the unordered field-name set whose each element is required and accepted.
    fields = {
        "capability",
        "resources",
        "resource_absence",
        "recoveries",
        "recovery_absence",
        "tests",
    }
    # Close the capability schema before interpreting its joins and obligations.
    _exact(record, fields, where)
    # Parse the raw capability spelling before enum conversion.
    raw_capability = _text(record["capability"], f"{where}.capability")
    # Resolve the spelling through the canonical capability enum.
    try:
        # Convert only exact declared values without aliases or coercion.
        capability = Capability(raw_capability)
    # Translate an unknown enum spelling into the capability-join diagnostic.
    except ValueError:
        # Reject stale or invented capability vocabulary at its exact field path.
        _fail("OPMODEL002_CAPABILITY_JOIN", f"{where}.capability", "unknown capability")
    # Parse resource-id elements in authored order, allowing an explicit empty join.
    resources = _strings(record["resources"], f"{where}.resources", allow_empty=True)
    # Parse the optional rationale required when the resource join is empty.
    resource_absence = _optional_text(
        record["resource_absence"], f"{where}.resource_absence",
    )
    # Parse recovery-id elements in authored order, allowing an explicit empty join.
    recoveries = _strings(record["recoveries"], f"{where}.recoveries", allow_empty=True)
    # Parse the optional rationale required when the recovery join is empty.
    recovery_absence = _optional_text(
        record["recovery_absence"], f"{where}.recovery_absence",
    )
    # A non-empty resource join and an absence rationale are mutually exclusive.
    if bool(resources) == (resource_absence is not None):
        # Reject both unexplained emptiness and contradictory evidence plus absence.
        _fail(
            "OPMODEL003_OWNERSHIP_JOIN",
            where,
            "resources require null resource_absence; an empty list requires rationale",
        )
    # A non-empty recovery join and an absence rationale are mutually exclusive.
    if bool(recoveries) == (recovery_absence is not None):
        # Reject both unexplained emptiness and contradictory evidence plus absence.
        _fail(
            "OPMODEL003_OWNERSHIP_JOIN",
            where,
            "recoveries require null recovery_absence; an empty list requires rationale",
        )
    # Parse each obligation-evidence element in authored order.
    tests = tuple(
        _obligation(item, f"{where}.tests[{index}]")
        for index, item in enumerate(_records(record["tests"], f"{where}.tests"))
    )
    # Collect each obligation identifier in authored order for uniqueness checking.
    identifiers = [item.obligation_id for item in tests]
    # Duplicate obligation identities would make evidence selection ambiguous.
    if len(identifiers) != len(set(identifiers)):
        # Reject the containing capability record rather than selecting one duplicate.
        _fail("OPMODEL008_OBLIGATION", f"{where}.tests", "duplicate obligation ids")
    # Materialize the complete validated capability record.
    return CapabilityRecord(
        capability=capability,
        resources=resources,
        resource_absence=resource_absence,
        recoveries=recoveries,
        recovery_absence=recovery_absence,
        tests=tests,
    )


def _lifecycle(record: Mapping[str, object], where: str) -> Lifecycle:
    """Parse one lifecycle phase.

    @param record mapping whose each key names a lifecycle field and each value is decoded data;
        mapping iteration order is deliberately unused
    @param where JSON path
    @return typed phase
    """
    # Define the unordered field-name set whose each element is required and accepted.
    fields = {"phase", "owner_role", "behavior", "terminal_state", "test", "not_applicable"}
    # Close the lifecycle schema before interpreting its evidence disposition.
    _exact(record, fields, where)
    # Parse the declared canonical phase name.
    phase = _text(record["phase"], f"{where}.phase")
    # Every record must occupy one known lifecycle position.
    if phase not in LIFECYCLE_PHASES:
        # Reject invented lifecycle vocabulary at its exact field path.
        _fail("OPMODEL004_LIFECYCLE", f"{where}.phase", "unknown lifecycle phase")
    # Parse the architectural role that owns the phase transition.
    owner = _text(record["owner_role"], f"{where}.owner_role")
    # Lifecycle authority must remain inside one supported local role.
    if owner not in OWNER_ROLES:
        # Reject topology or undeclared ownership vocabulary.
        _fail("OPMODEL004_LIFECYCLE", f"{where}.owner_role", "unknown local owner role")
    # Parse the optional executable phase evidence.
    test = _optional_text(record["test"], f"{where}.test")
    # Parse the optional rationale for a phase that cannot apply.
    not_applicable = _optional_text(record["not_applicable"], f"{where}.not_applicable")
    # Require one and only one evidence disposition before activation checks.
    _exclusive(test, not_applicable, where, "OPMODEL004_LIFECYCLE")
    # Materialize the validated lifecycle record.
    return Lifecycle(
        phase=phase,
        owner_role=owner,
        behavior=_text(record["behavior"], f"{where}.behavior"),
        terminal_state=_identifier(record["terminal_state"], f"{where}.terminal_state"),
        test=test,
        not_applicable=not_applicable,
    )


def _state(record: Mapping[str, object], where: str) -> OperationalState:
    """Parse one safe or degraded local state.

    @param record mapping whose each key names a state field and each value is decoded data;
        mapping iteration order is deliberately unused
    @param where JSON path
    @return typed state
    """
    # Define the unordered field-name set whose each element is required and accepted.
    fields = {
        "id", "kind", "entry_conditions", "allowed_operations",
        "observable_event", "exit_condition",
    }
    # Close the state schema before interpreting classification and event identity.
    _exact(record, fields, where)
    # Parse the safe-or-degraded state classification.
    kind = _text(record["kind"], f"{where}.kind")
    # No third implicit operational condition is permitted.
    if kind not in {"safe", "degraded"}:
        # Reject unknown classification at the exact field path.
        _fail("OPMODEL005_STATE_OUTCOME", f"{where}.kind", "expected safe or degraded")
    # Parse the externally observable event spelling emitted on entry.
    event = _text(record["observable_event"], f"{where}.observable_event")
    # Event identity must follow the stable uppercase code grammar.
    if EVENT_CODE.fullmatch(event) is None:
        # Reject prose and unstable local spellings as observable codes.
        _fail(
            "OPMODEL005_STATE_OUTCOME",
            f"{where}.observable_event",
            "expected stable hyphenated uppercase event code",
        )
    # Materialize the validated state and its ordered condition/operation elements.
    return OperationalState(
        state_id=_identifier(record["id"], f"{where}.id"),
        kind=kind,
        entry_conditions=_strings(record["entry_conditions"], f"{where}.entry_conditions"),
        allowed_operations=_strings(
            record["allowed_operations"],
            f"{where}.allowed_operations",
            allow_empty=True,
        ),
        observable_event=event,
        exit_condition=_text(record["exit_condition"], f"{where}.exit_condition"),
    )


def _bound(value: object, where: str, kind: str) -> Bound:
    """Parse a positive bound with a class-appropriate unit.

    @param value decoded bound object
    @param where JSON path
    @param kind enclosing budget class
    @return typed positive bound
    """
    # Require the decoded bound to be an object with a closed schema.
    record = _object(value, where)
    _exact(record, {"value", "unit"}, where)
    # Select the raw numeric quantity without accepting boolean-as-integer coercion.
    number = record["value"]
    # A usable operational limit must be a positive finite-scale numeric value.
    if isinstance(number, bool) or not isinstance(number, (int, float)) or number <= 0:
        # Reject zero, negative, boolean, and non-numeric quantities.
        _fail("OPMODEL006_BUDGET", f"{where}.value", "expected a positive number")
    # Parse the authored unit spelling for class-specific validation.
    unit = _text(record["unit"], f"{where}.unit")
    # Each budget class admits only its explicitly comparable units.
    if unit not in BUDGET_UNITS[kind]:
        # Render accepted unit-name elements in deterministic lexical order.
        _fail(
            "OPMODEL006_BUDGET",
            f"{where}.unit",
            f"expected one of {sorted(BUDGET_UNITS[kind])}",
        )
    # Materialize the positive quantity in its class-appropriate unit.
    return Bound(value=number, unit=unit)


def _budget(record: Mapping[str, object], where: str) -> Budget:
    """Parse one budget class.

    @param record mapping whose each key names a budget field and each value is decoded data;
        mapping iteration order is deliberately unused
    @param where JSON path
    @return typed budget
    """
    # Close the budget schema before interpreting its bound disposition.
    _exact(record, {"kind", "scope", "bound", "not_applicable", "measurement"}, where)
    # Parse the canonical budget-class name.
    kind = _text(record["kind"], f"{where}.kind")
    # Every record must occupy one required budget class.
    if kind not in BUDGET_KINDS:
        # Reject invented budget vocabulary at its exact field path.
        _fail("OPMODEL006_BUDGET", f"{where}.kind", "unknown budget class")
    # Retain explicit null separately from a decoded quantitative bound.
    raw_bound = record["bound"]
    # Parse the optional quantitative bound using its class-specific unit vocabulary.
    bound = None if raw_bound is None else _bound(raw_bound, f"{where}.bound", kind)
    # Parse the optional rationale for a budget that cannot apply.
    not_applicable = _optional_text(record["not_applicable"], f"{where}.not_applicable")
    # Parse the optional exact measurement-evidence spelling.
    measurement = _optional_text(record["measurement"], f"{where}.measurement")
    # A finite bound and a non-applicability rationale are exclusive and exhaustive.
    if (bound is None) == (not_applicable is None):
        # Reject both omission and contradictory dual disposition.
        _fail(
            "OPMODEL006_BUDGET",
            where,
            "exactly one of bound and not_applicable is required",
        )
    # Measurement evidence exists exactly when a finite bound is asserted.
    if (bound is None) != (measurement is None):
        # Reject unmeasured limits and evidence attached to non-applicability.
        _fail(
            "OPMODEL006_BUDGET",
            where,
            "a finite bound requires measurement and non-applicability forbids it",
        )
    # Materialize the validated budget and evidence disposition.
    return Budget(
        kind=kind,
        scope=_text(record["scope"], f"{where}.scope"),
        bound=bound,
        not_applicable=not_applicable,
        measurement=measurement,
    )


def _outcome(record: Mapping[str, object], where: str) -> Outcome:
    """Parse one observable terminal outcome.

    @param record mapping whose each key names an outcome field and each value is decoded data;
        mapping iteration order is deliberately unused
    @param where JSON path
    @return typed outcome
    """
    # Define the unordered field-name set whose each element is required and accepted.
    fields = {
        "id", "exceptional", "trigger", "event_code", "correlation_field",
        "terminal_state", "test",
    }
    # Close the outcome schema before interpreting its event identity.
    _exact(record, fields, where)
    # Select the exceptional-channel flag without scalar coercion.
    exceptional = record["exceptional"]
    # JSON booleans alone can state the exceptional versus ordinary distinction.
    if not isinstance(exceptional, bool):
        # Reject integer and textual impostors at the exact field path.
        _fail("OPMODEL005_STATE_OUTCOME", f"{where}.exceptional", "expected boolean")
    # Parse the stable externally observable terminal event code.
    event = _text(record["event_code"], f"{where}.event_code")
    # Event identity must follow the uppercase hyphenated code grammar.
    if EVENT_CODE.fullmatch(event) is None:
        # Reject prose and unstable local spellings as observable codes.
        _fail(
            "OPMODEL005_STATE_OUTCOME",
            f"{where}.event_code",
            "expected stable hyphenated uppercase event code",
        )
    # Materialize the validated terminal outcome and its evidence reference.
    return Outcome(
        outcome_id=_identifier(record["id"], f"{where}.id"),
        exceptional=exceptional,
        trigger=_text(record["trigger"], f"{where}.trigger"),
        event_code=event,
        correlation_field=_identifier(
            record["correlation_field"], f"{where}.correlation_field",
        ),
        terminal_state=_identifier(record["terminal_state"], f"{where}.terminal_state"),
        test=_text(record["test"], f"{where}.test"),
    )


def _identity(value: object, where: str) -> Identity:
    """Parse build and runtime identity evidence.

    @param value decoded identity object whose field order is deliberately unused
    @param where JSON path
    @return typed identity
    """
    # Require the decoded identity to be an object with a closed schema.
    record = _object(value, where)
    _exact(record, {"build_source", "runtime_fields", "test"}, where)
    # Materialize the source, ordered runtime-field elements, and evidence spelling.
    return Identity(
        build_source=_text(record["build_source"], f"{where}.build_source"),
        runtime_fields=_strings(record["runtime_fields"], f"{where}.runtime_fields"),
        test=_text(record["test"], f"{where}.test"),
    )


def _platform(record: Mapping[str, object], where: str) -> PlatformSupport:
    """Parse one platform support declaration.

    @param record mapping whose each key names a platform field and each value is decoded data;
        mapping iteration order is deliberately unused
    @param where JSON path
    @return typed platform support
    """
    # Close the platform schema before interpreting interdependent support fields.
    _exact(record, {"name", "runtime", "development", "evidence", "limitation"}, where)
    # Parse the release-platform identifier.
    name = _text(record["name"], f"{where}.name")
    # Parse runtime-support intent independently from executed evidence.
    runtime = _text(record["runtime"], f"{where}.runtime")
    # Parse development-tool support intent independently from runtime support.
    development = _text(record["development"], f"{where}.development")
    # Every platform record must identify one supported release leg.
    if name not in PLATFORMS:
        # Reject invented platform vocabulary at the exact field path.
        _fail("OPMODEL007_IDENTITY_PLATFORM", f"{where}.name", "unknown release platform")
    # Runtime and development support must each use their distinct closed vocabularies.
    if runtime not in RUNTIME_SUPPORT or development not in DEVELOPMENT_SUPPORT:
        # Reject unknown support outcomes before interpreting evidence.
        _fail(
            "OPMODEL007_IDENTITY_PLATFORM",
            where,
            "unknown runtime or development support outcome",
        )
    # Parse the optional local support-evidence path.
    evidence = _optional_text(record["evidence"], f"{where}.evidence")
    # Parse the optional explanation for any unsupported aspect.
    limitation = _optional_text(record["limitation"], f"{where}.limitation")
    # Record whether both runtime and development are asserted supported.
    fully_supported = runtime == "supported" and development == "supported"
    # Full support requires evidence and forbids a contradictory limitation.
    if fully_supported and (evidence is None or limitation is not None):
        # Reject unsupported or unexplained fully-supported declarations.
        _fail(
            "OPMODEL007_IDENTITY_PLATFORM",
            where,
            "fully supported requires evidence and null limitation",
        )
    # Any non-supported outcome must state its exact limitation.
    if not fully_supported and limitation is None:
        # Reject a support gap that gives developers no actionable boundary.
        _fail(
            "OPMODEL007_IDENTITY_PLATFORM",
            where,
            "a non-supported outcome requires a limitation",
        )
    # Materialize the internally consistent support-intent record.
    return PlatformSupport(
        name=name,
        runtime=runtime,
        development=development,
        evidence=evidence,
        limitation=limitation,
    )


def parse(path: Path) -> OperationalModel:
    """Parse one exact canonical operational model.

    @param path local JSON model path
    @return typed operational model
    @throws OperationalError when syntax or fields are invalid

    @par Effects
    Reads the model file at ``path`` once before validating the decoded snapshot.
    """
    # Read and decode one immutable operational-model snapshot.
    try:
        # Decode the file snapshot into an untrusted JSON value.
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    # Translate filesystem, encoding, and JSON failures into the model error channel.
    except (OSError, UnicodeError, json.JSONDecodeError) as problem:
        # Preserve the path and parser detail in a stable schema diagnostic.
        _fail("OPMODEL001_SCHEMA", str(path), str(problem))
    # Require the decoded root to be a JSON object.
    root = _object(raw, "$")
    # Define the unordered root-field set whose each element is required and accepted.
    fields = {
        "schema_version", "capability_obligations", "lifecycle", "states",
        "budgets", "outcomes", "identity", "platforms",
    }
    # Close the root schema before interpreting any nested record sequence.
    _exact(root, fields, "$")
    # Reject incompatible schema versions before reading their records.
    if root["schema_version"] != 1:
        # State the sole supported schema version at the canonical location.
        _fail("OPMODEL001_SCHEMA", "$.schema_version", "expected 1")
    # Parse each capability-record element in authored order, allowing an empty inactive view.
    capability_records = tuple(
        _capability_record(item, f"$.capability_obligations[{index}]")
        for index, item in enumerate(
            _records(
                root["capability_obligations"],
                "$.capability_obligations",
                allow_empty=True,
            )
        )
    )
    # Parse each lifecycle-record element in authored execution order.
    lifecycle = tuple(
        _lifecycle(item, f"$.lifecycle[{index}]")
        for index, item in enumerate(_records(root["lifecycle"], "$.lifecycle"))
    )
    # Parse each operational-state record element in authored order.
    states = tuple(
        _state(item, f"$.states[{index}]")
        for index, item in enumerate(_records(root["states"], "$.states"))
    )
    # Parse each budget-record element in authored canonical-class order.
    budgets = tuple(
        _budget(item, f"$.budgets[{index}]")
        for index, item in enumerate(_records(root["budgets"], "$.budgets"))
    )
    # Parse each terminal-outcome record element in authored order.
    outcomes = tuple(
        _outcome(item, f"$.outcomes[{index}]")
        for index, item in enumerate(_records(root["outcomes"], "$.outcomes"))
    )
    # Parse each platform-support record element in authored order.
    platforms = tuple(
        _platform(item, f"$.platforms[{index}]")
        for index, item in enumerate(_records(root["platforms"], "$.platforms"))
    )
    # Materialize the complete validated operational-model snapshot.
    return OperationalModel(
        capability_records=capability_records,
        lifecycle=lifecycle,
        states=states,
        budgets=budgets,
        outcomes=outcomes,
        identity=_identity(root["identity"], "$.identity"),
        platforms=platforms,
    )


def _local_path(root: Path, spelling: str, diagnostic_id: str) -> Path:
    """Resolve one confined evidence or source path.

    @param root governed repository root
    @param spelling POSIX path with an optional pytest node suffix
    @param diagnostic_id diagnostic to raise for unsafe or absent evidence
    @return existing local file path
    """
    # Remove an optional pytest-node suffix before resolving the owning file.
    file_part = spelling.split("::", 1)[0]
    # Normalize accepted separators into one repository-relative POSIX spelling.
    relative = PurePosixPath(file_part.replace("\\", "/"))
    # Reject absolute, drive-qualified, and parent-traversing declarations lexically.
    if relative.is_absolute() or PureWindowsPath(file_part).drive or ".." in relative.parts:
        # Report the caller-selected diagnostic at the unsafe authored spelling.
        _fail(diagnostic_id, spelling, "path must stay inside the governed repository")
    # Resolve symlinks and normalization against the governed repository root.
    candidate = (root / Path(relative.as_posix())).resolve()
    # Prove confinement again after filesystem resolution.
    try:
        candidate.relative_to(root.resolve())
    # Translate an escaped resolved path into the caller's diagnostic namespace.
    except ValueError:
        # Reject symlink and normalization escapes at their authored spelling.
        _fail(diagnostic_id, spelling, "resolved path leaves the governed repository")
    # Evidence must name an existing regular file rather than a directory or future artifact.
    if not candidate.is_file():
        # Reject absent evidence at validation time.
        _fail(diagnostic_id, spelling, "declared local evidence file does not exist")
    # Return the confined existing evidence path.
    return candidate


def _unique(values: Sequence[str], where: str, diagnostic_id: str) -> None:
    """Require a sequence to have no duplicate identities.

    @param values identifier elements in model order
    @param where JSON collection path
    @param diagnostic_id semantic diagnostic to raise
    @throws OperationalError when a duplicate exists
    """
    # Compare sequence cardinality with its unordered identity set.
    if len(values) != len(set(values)):
        # Reject the containing collection rather than selecting one duplicate.
        _fail(diagnostic_id, where, "duplicate identities are not allowed")


def _validate_capabilities(
    model: OperationalModel,
    active: frozenset[Capability],
    architecture: ArchitectureModel,
    root: Path,
) -> None:
    """Join enabled facts to architecture and generated obligations.

    @param model parsed operational model
    @param active unordered set whose each element is an explicit true capability
    @param architecture canonical local architecture model
    @param root governed repository root
    @throws OperationalError on stale joins or incomplete evidence
    """
    # Map each capability key to its evidence-record value; order is immaterial.
    records = {item.capability: item for item in model.capability_records}
    # Prove authored capability identities are unique before dictionary comparison.
    _unique(
        [item.capability.value for item in model.capability_records],
        "$.capability_obligations",
        "OPMODEL002_CAPABILITY_JOIN",
    )
    # Operational records must equal the explicit true-capability set exactly.
    if set(records) != set(active):
        # Sort both capability-name differences for deterministic diagnostics.
        _fail(
            "OPMODEL002_CAPABILITY_JOIN",
            "$.capability_obligations",
            f"missing={sorted(item.value for item in active - set(records))}, "
            f"inactive={sorted(item.value for item in set(records) - active)}",
        )
    # Build an unordered set whose each element is a canonical architecture resource id.
    resource_ids = {item.resource_id for item in architecture.resources}
    # Build an unordered set whose each element is a canonical architecture recovery id.
    recovery_ids = {item.failure_id for item in architecture.recoveries}
    # Validate each capability key/value pair in authored insertion order.
    for capability, record in records.items():
        # Build an unordered set whose each element is an unknown joined resource id.
        unknown_resources = set(record.resources) - resource_ids
        # Build an unordered set whose each element is an unknown joined recovery id.
        unknown_recoveries = set(record.recoveries) - recovery_ids
        # Either unknown join would assign operational ownership without architecture authority.
        if unknown_resources or unknown_recoveries:
            # Sort both unknown-id sets for deterministic actionable diagnostics.
            _fail(
                "OPMODEL003_OWNERSHIP_JOIN",
                capability.value,
                f"unknown resources={sorted(unknown_resources)}, "
                f"recoveries={sorted(unknown_recoveries)}",
            )
        # Build the unordered actual-obligation set from each evidence record.
        actual = {item.obligation_id for item in record.tests}
        # Select the unordered required-obligation set generated for this capability.
        required = CAPABILITY_OBLIGATIONS[capability]
        # Evidence must equal the generated obligation set without omission or invention.
        if actual != required:
            # Sort both obligation differences for deterministic diagnostics.
            _fail(
                "OPMODEL008_OBLIGATION",
                capability.value,
                f"missing={sorted(required - actual)}, unknown={sorted(actual - required)}",
            )
        # Confine each obligation-evidence element in authored order.
        for evidence in record.tests:
            # Prove the evidence file exists inside this repository.
            _local_path(root, evidence.evidence, "OPMODEL008_OBLIGATION")


def _validate_lifecycle(
    model: OperationalModel,
    active: frozenset[Capability],
    state_ids: set[str],
    root: Path,
) -> None:
    """Require all phases and executable evidence for activated behavior.

    @param model parsed operational model
    @param active unordered set whose each element is an explicit true capability
    @param state_ids unordered set whose each element is a declared local state identity
    @param root governed repository root
    @throws OperationalError on missing, stale, or excused required phases
    """
    # Map each lifecycle-phase key to its record value; insertion order is authored order.
    phases = {item.phase: item for item in model.lifecycle}
    # Prove authored lifecycle identities are unique before dictionary comparison.
    _unique(
        [item.phase for item in model.lifecycle],
        "$.lifecycle",
        "OPMODEL004_LIFECYCLE",
    )
    # The model must contain exactly the six canonical lifecycle phases.
    if set(phases) != set(LIFECYCLE_PHASES):
        # Report canonical phase elements in their required execution order.
        _fail(
            "OPMODEL004_LIFECYCLE",
            "$.lifecycle",
            f"expected exactly {list(LIFECYCLE_PHASES)}",
        )
    # Validate each phase key/value pair in authored insertion order.
    for phase, record in phases.items():
        # Every phase must finish in one state declared by the same model.
        if record.terminal_state not in state_ids:
            # Reject cross-reference to an unknown local state identity.
            _fail(
                "OPMODEL004_LIFECYCLE",
                phase,
                f"unknown terminal state {record.terminal_state!r}",
            )
        # Select the unordered capability set that activates this phase.
        required_by = PHASE_CAPABILITIES[phase]
        # Startup, steady-state, and shutdown apply independently of capabilities.
        always = phase in {"startup", "steady_state", "shutdown"}
        # An always-on or capability-activated phase cannot be excused as inapplicable.
        if record.not_applicable is not None and (always or active & required_by):
            # Require executable evidence for behavior the declaration activates.
            _fail(
                "OPMODEL004_LIFECYCLE",
                phase,
                "an activated lifecycle phase requires executable evidence",
            )
        # Executable dispositions must reference evidence confined to this repository.
        if record.test is not None:
            # Prove the phase evidence file exists inside the governed root.
            _local_path(root, record.test, "OPMODEL004_LIFECYCLE")


def _validate_states_and_outcomes(model: OperationalModel, root: Path) -> set[str]:
    """Require safe/degraded states and observable ordinary outcomes.

    @param model parsed operational model
    @param root governed repository root
    @return unordered set whose each element is a declared state id for lifecycle joining
    @throws OperationalError on duplicates, missing kinds, or stale evidence
    """
    # Collect each state identifier in authored order for uniqueness and later joining.
    state_ids = [item.state_id for item in model.states]
    # Collect each terminal-outcome identifier in authored order for uniqueness checking.
    outcome_ids = [item.outcome_id for item in model.outcomes]
    # Prove both authored identity sequences contain no aliases.
    _unique(state_ids, "$.states", "OPMODEL005_STATE_OUTCOME")
    _unique(outcome_ids, "$.outcomes", "OPMODEL005_STATE_OUTCOME")
    # Build an unordered set whose each element is a represented state classification.
    kinds = {item.kind for item in model.states}
    # Both ordinary safe operation and explicit degraded behavior must be modeled.
    if kinds != {"safe", "degraded"}:
        # Reject an incomplete or invented state classification set.
        _fail(
            "OPMODEL005_STATE_OUTCOME",
            "$.states",
            "at least one safe and one degraded state are required",
        )
    # Build an unordered state-id set for terminal-state membership checks.
    known = set(state_ids)
    # At least one terminal result must use the ordinary return channel.
    if not any(not item.exceptional for item in model.outcomes):
        # Reject a model that treats every completion as exceptional.
        _fail(
            "OPMODEL005_STATE_OUTCOME",
            "$.outcomes",
            "at least one non-exception terminal outcome is required",
        )
    # Validate each terminal-outcome element in authored order.
    for outcome in model.outcomes:
        # Every outcome must terminate in one locally declared state.
        if outcome.terminal_state not in known:
            # Reject cross-reference to an unknown local state identity.
            _fail(
                "OPMODEL005_STATE_OUTCOME",
                outcome.outcome_id,
                f"unknown terminal state {outcome.terminal_state!r}",
            )
        # Prove the executable outcome evidence exists inside this repository.
        _local_path(root, outcome.test, "OPMODEL005_STATE_OUTCOME")
    # Return the complete order-independent state identity set for lifecycle joining.
    return known


def _validate_budgets(
    model: OperationalModel,
    active: frozenset[Capability],
    root: Path,
) -> None:
    """Require every budget class and finite bounds for activated work.

    @param model parsed operational model
    @param active unordered set whose each element is an explicit true capability
    @param root governed repository root
    @throws OperationalError on missing classes or unbounded activated work
    """
    # Map each budget-class key to its record value; insertion order is authored order.
    budgets = {item.kind: item for item in model.budgets}
    # Prove authored budget classes are unique before dictionary comparison.
    _unique([item.kind for item in model.budgets], "$.budgets", "OPMODEL006_BUDGET")
    # The model must contain exactly the six canonical budget classes.
    if set(budgets) != set(BUDGET_KINDS):
        # Report canonical class elements in their required declaration order.
        _fail(
            "OPMODEL006_BUDGET",
            "$.budgets",
            f"expected exactly {list(BUDGET_KINDS)}",
        )
    # Validate each budget key/value pair in authored insertion order.
    for kind, budget in budgets.items():
        # Capability-activated work cannot declare its governing budget inapplicable.
        if budget.bound is None and active & BUDGET_CAPABILITIES[kind]:
            # Sort each activating capability-name element for a deterministic diagnostic.
            activators = sorted(item.value for item in active & BUDGET_CAPABILITIES[kind])
            # Require a finite bound and measurement for the activated cost class.
            _fail(
                "OPMODEL006_BUDGET",
                kind,
                f"finite bound required by {activators}",
            )
        # A finite bound's measurement must be confined to local evidence.
        if budget.measurement is not None:
            # Prove the measurement evidence file exists inside this repository.
            _local_path(root, budget.measurement, "OPMODEL006_BUDGET")


def _validate_identity_platform(model: OperationalModel, root: Path) -> None:
    """Require build/runtime identity and explicit Windows/Linux support.

    @param model parsed operational model
    @param root governed repository root
    @throws OperationalError on missing fields, platforms, or confined evidence
    """
    # Define the unordered runtime-field set whose each element is mandatory.
    required_fields = {"version", "build_id"}
    # Runtime diagnostics must expose both release version and build identity.
    if not required_fields <= set(model.identity.runtime_fields):
        # Sort missing field-name elements for a deterministic diagnostic.
        _fail(
            "OPMODEL007_IDENTITY_PLATFORM",
            "$.identity.runtime_fields",
            f"missing {sorted(required_fields - set(model.identity.runtime_fields))}",
        )
    # Prove build identity derives from a source file inside this repository.
    _local_path(root, model.identity.build_source, "OPMODEL007_IDENTITY_PLATFORM")
    # Prove runtime-identity behavior has executable local evidence.
    _local_path(root, model.identity.test, "OPMODEL007_IDENTITY_PLATFORM")
    # Collect each platform name in authored order for uniqueness and completeness checks.
    names = [item.name for item in model.platforms]
    # Prove authored platform identities contain no aliases.
    _unique(names, "$.platforms", "OPMODEL007_IDENTITY_PLATFORM")
    # Support intent must cover exactly the Windows and Linux release legs.
    if set(names) != PLATFORMS:
        # Report required platform-name elements in deterministic lexical order.
        _fail(
            "OPMODEL007_IDENTITY_PLATFORM",
            "$.platforms",
            f"expected exactly {sorted(PLATFORMS)}",
        )
    # Validate each platform-support element in authored order.
    for platform in model.platforms:
        # Claimed support evidence, when present, must be confined locally.
        if platform.evidence is not None:
            # Prove the support artifact exists inside this repository.
            _local_path(root, platform.evidence, "OPMODEL007_IDENTITY_PLATFORM")


def validate(
    model: OperationalModel,
    active: frozenset[Capability],
    architecture: ArchitectureModel,
    root: Path,
) -> None:
    """Cross-check the operational model against declaration and architecture.

    @param model parsed operational model
    @param active unordered set whose each element is an explicit true capability
    @param architecture canonical local architecture model
    @param root governed repository root
    @throws OperationalError on the first deterministic mismatch
    """
    # Validate declaration and architecture joins before downstream operational views.
    _validate_capabilities(model, active, architecture, root)
    # Validate state/outcome closure and retain the unordered declared state-id set.
    state_ids = _validate_states_and_outcomes(model, root)
    # Validate phase activation and evidence against the proven state identities.
    _validate_lifecycle(model, active, state_ids, root)
    # Validate all cost classes and capability-activated finite bounds.
    _validate_budgets(model, active, root)
    # Validate build/runtime identity and both supported release-platform declarations.
    _validate_identity_platform(model, root)


class OperationalModelCheck(Check):
    """Check local operational ownership, bounds, outcomes, identity, and evidence."""

    ## Mechanism token for repository-local operational rules.
    name = "operational_model"
    ## Rule-id elements in deterministic reporting order for operational obligations.
    rules = ("OPS-003", "OPS-004", "OPS-005", "OPS-006", "OPS-007", "OPS-008")

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Validate only canonical paths from the nearest declaration.

        @param paths path elements in caller order, deliberately ignored because
            declaration-bound records are authoritative
        @return zero or one earliest deterministic finding
        """
        # Mark the protocol parameter consumed while retaining the common checker signature.
        _ = paths
        # Resolve the canonical model paths and governed root from the declaration.
        model_path = self.declaration.operational_model_path()
        architecture_path = self.declaration.architecture_path()
        root = self.declaration.root
        # A project without the complete optional model pair has no operational gate to run.
        if model_path is None or architecture_path is None or root is None:
            # Return an ordered empty finding sequence for an undeclared mechanism.
            return []
        # Parse and cross-check the complete local operational proposition.
        try:
            # Parse the operational model before resolving its architecture references.
            model = parse(model_path)
            # Parse the canonical architecture model used as the join authority.
            architecture = parse_architecture(architecture_path)
            # Validate all declaration, architecture, and confined-evidence joins.
            validate(model, self.declaration.capabilities, architecture, root)
        # Translate an invalid prerequisite architecture model into the ownership rule.
        except ArchitectureError as problem:
            # Return the sole earliest finding with prerequisite-specific remediation.
            return [Finding(
                rule_id="OPS-003",
                path=architecture_path,
                line=1,
                message=f"architecture prerequisite failed at {problem.where}: {problem.detail}",
                remediation="Repair architecture.json before operational ownership joins.",
                diagnostic_id="OPMODEL003_OWNERSHIP_JOIN",
            )]
        # Translate a typed operational failure into its owning discipline rule.
        except OperationalError as problem:
            # Map each diagnostic-prefix key to its governing rule-id value; order is immaterial.
            rule = {
                "OPMODEL001": "OPS-003",
                "OPMODEL002": "OPS-008",
                "OPMODEL003": "OPS-003",
                "OPMODEL004": "OPS-004",
                "OPMODEL005": "OPS-005",
                "OPMODEL006": "OPS-006",
                "OPMODEL007": "OPS-007",
                "OPMODEL008": "OPS-008",
            }[problem.diagnostic_id[:10]]
            # Return the sole earliest finding with the model diagnostic preserved.
            return [Finding(
                rule_id=rule,
                path=model_path,
                line=1,
                message=f"{problem.where}: {problem.detail}",
                remediation=(
                    "Repair the canonical local operational model and its confined "
                    "evidence; do not assign a local obligation to another repository."
                ),
                diagnostic_id=problem.diagnostic_id,
            )]
        # A complete validation produces the ordered empty finding sequence.
        return []


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    from . import main

    # Translate the checker result into the process exit status.
    raise SystemExit(main(OperationalModelCheck()))
