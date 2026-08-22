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

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

## Stable lower-snake record identifiers.
IDENTIFIER: Final = re.compile(r"^[a-z][a-z0-9_]*$")
## Stable externally observable event-code grammar.
EVENT_CODE: Final = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
## Complete lifecycle vocabulary in execution order.
LIFECYCLE_PHASES: Final = (
    "startup",
    "steady_state",
    "interruption",
    "drain",
    "shutdown",
    "forced_cleanup",
)
## Operational budget classes required to be explicitly bounded or inapplicable.
BUDGET_KINDS: Final = (
    "time",
    "memory",
    "queue",
    "retry",
    "input_size",
    "cleanup",
)
## Units accepted for each quantitative budget class.
BUDGET_UNITS: Final[Mapping[str, frozenset[str]]] = {
    "time": frozenset({"milliseconds", "seconds"}),
    "memory": frozenset({"bytes", "kibibytes", "mebibytes"}),
    "queue": frozenset({"bytes", "items"}),
    "retry": frozenset({"attempts"}),
    "input_size": frozenset({"bytes", "characters", "items"}),
    "cleanup": frozenset({"items", "milliseconds", "seconds"}),
}
## Supported local architectural owner roles.
OWNER_ROLES: Final = frozenset({"domain", "application", "ports", "adapters", "shell"})
## Required local evidence obligations activated by each true capability.
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
## Capabilities that make a lifecycle phase mandatory rather than explainably absent.
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
## Capabilities that require a finite quantitative budget by class.
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
## Supported release-platform vocabulary.
PLATFORMS: Final = frozenset({"windows", "linux"})
## Platform support outcomes kept distinct from an executed gate verdict.
RUNTIME_SUPPORT: Final = frozenset({"supported", "unsupported", "not_applicable"})
## Development-tool support cannot hide behind runtime non-applicability.
DEVELOPMENT_SUPPORT: Final = frozenset({"supported", "unsupported"})


class OperationalError(ValueError):
    """One stable operational-model diagnostic."""

    def __init__(self, diagnostic_id: str, where: str, detail: str) -> None:
        """Build one actionable model failure.

        @param diagnostic_id stable mechanism diagnostic
        @param where JSON path or repository location
        @param detail explanation of the violated predicate
        """
        super().__init__(f"{diagnostic_id} {where}: {detail}")
        self.diagnostic_id = diagnostic_id
        self.where = where
        self.detail = detail


def _fail(diagnostic_id: str, where: str, detail: str) -> Never:
    """Raise one operational diagnostic.

    @param diagnostic_id stable mechanism diagnostic
    @param where JSON path or repository location
    @param detail explanation of the violated predicate
    @return never; this helper always raises
    @throws OperationalError unconditionally
    """
    raise OperationalError(diagnostic_id, where, detail)


def _object(value: object, where: str) -> Mapping[str, object]:
    """Require a JSON object.

    @param value untrusted decoded value
    @param where JSON path
    @return typed mapping
    """
    if not isinstance(value, dict):
        _fail("OPMODEL001_SCHEMA", where, "expected an object")
    return value


def _exact(record: Mapping[str, object], fields: set[str], where: str) -> None:
    """Reject missing and ignored fields.

    @param record decoded object
    @param fields exact accepted field set
    @param where JSON path
    @throws OperationalError when the field set differs
    """
    missing = fields - set(record)
    unknown = set(record) - fields
    if missing or unknown:
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
    if not isinstance(value, str) or not value.strip():
        _fail("OPMODEL001_SCHEMA", where, "expected non-empty text")
    return value.strip()


def _optional_text(value: object, where: str) -> str | None:
    """Require null or non-empty text.

    @param value untrusted decoded value
    @param where JSON path
    @return stripped text or None
    """
    return None if value is None else _text(value, where)


def _identifier(value: object, where: str) -> str:
    """Require one lower-snake identifier.

    @param value untrusted decoded value
    @param where JSON path
    @return validated identifier
    """
    text = _text(value, where)
    if IDENTIFIER.fullmatch(text) is None:
        _fail("OPMODEL001_SCHEMA", where, "expected lower_snake identifier")
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
    @param allow_empty whether an explicit empty array is meaningful
    @return decoded object records
    """
    if not isinstance(value, list) or (not value and not allow_empty):
        _fail("OPMODEL001_SCHEMA", where, "expected a record array")
    return [_object(item, f"{where}[{index}]") for index, item in enumerate(value)]


def _strings(value: object, where: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    """Require a unique string array.

    @param value untrusted decoded value
    @param where JSON path
    @param allow_empty whether an explicit empty array is meaningful
    @return unique values in source order
    """
    if not isinstance(value, list) or (not value and not allow_empty):
        _fail("OPMODEL001_SCHEMA", where, "expected a string array")
    values = tuple(_text(item, f"{where}[{index}]") for index, item in enumerate(value))
    if len(values) != len(set(values)):
        _fail("OPMODEL001_SCHEMA", where, "duplicate values are not allowed")
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
    if (present is None) == (absent is None):
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
    ## Architecture resource ids owned or transferred by this capability.
    resources: tuple[str, ...]
    ## Explanation when it owns no resource.
    resource_absence: str | None
    ## Architecture recovery ids used by this capability.
    recoveries: tuple[str, ...]
    ## Explanation when it owns no recovery.
    recovery_absence: str | None
    ## Complete generated obligation evidence.
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
    ## Conditions entering the state.
    entry_conditions: tuple[str, ...]
    ## Operations permitted while in the state.
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
    ## Whether this outcome escapes through the exception channel.
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
    ## Fields emitted by runtime diagnostics.
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

    ## Evidence records for exactly the enabled capabilities.
    capability_records: tuple[CapabilityRecord, ...]
    ## Six canonical lifecycle phases.
    lifecycle: tuple[Lifecycle, ...]
    ## Safe and degraded local states.
    states: tuple[OperationalState, ...]
    ## Six canonical cost budgets.
    budgets: tuple[Budget, ...]
    ## Exceptional and non-exception terminal outcomes.
    outcomes: tuple[Outcome, ...]
    ## Build and runtime identity.
    identity: Identity
    ## Windows and Linux support intent.
    platforms: tuple[PlatformSupport, ...]


def _obligation(record: Mapping[str, object], where: str) -> ObligationEvidence:
    """Parse one capability obligation record.

    @param record decoded obligation record
    @param where JSON path
    @return typed evidence
    """
    _exact(record, {"id", "evidence"}, where)
    return ObligationEvidence(
        obligation_id=_identifier(record["id"], f"{where}.id"),
        evidence=_text(record["evidence"], f"{where}.evidence"),
    )


def _capability_record(record: Mapping[str, object], where: str) -> CapabilityRecord:
    """Parse one enabled capability's joins and evidence.

    @param record decoded capability record
    @param where JSON path
    @return typed record
    """
    fields = {
        "capability",
        "resources",
        "resource_absence",
        "recoveries",
        "recovery_absence",
        "tests",
    }
    _exact(record, fields, where)
    raw_capability = _text(record["capability"], f"{where}.capability")
    try:
        capability = Capability(raw_capability)
    except ValueError:
        _fail("OPMODEL002_CAPABILITY_JOIN", f"{where}.capability", "unknown capability")
    resources = _strings(record["resources"], f"{where}.resources", allow_empty=True)
    resource_absence = _optional_text(
        record["resource_absence"], f"{where}.resource_absence",
    )
    recoveries = _strings(record["recoveries"], f"{where}.recoveries", allow_empty=True)
    recovery_absence = _optional_text(
        record["recovery_absence"], f"{where}.recovery_absence",
    )
    if bool(resources) == (resource_absence is not None):
        _fail(
            "OPMODEL003_OWNERSHIP_JOIN",
            where,
            "resources require null resource_absence; an empty list requires rationale",
        )
    if bool(recoveries) == (recovery_absence is not None):
        _fail(
            "OPMODEL003_OWNERSHIP_JOIN",
            where,
            "recoveries require null recovery_absence; an empty list requires rationale",
        )
    tests = tuple(
        _obligation(item, f"{where}.tests[{index}]")
        for index, item in enumerate(_records(record["tests"], f"{where}.tests"))
    )
    identifiers = [item.obligation_id for item in tests]
    if len(identifiers) != len(set(identifiers)):
        _fail("OPMODEL008_OBLIGATION", f"{where}.tests", "duplicate obligation ids")
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

    @param record decoded lifecycle record
    @param where JSON path
    @return typed phase
    """
    fields = {"phase", "owner_role", "behavior", "terminal_state", "test", "not_applicable"}
    _exact(record, fields, where)
    phase = _text(record["phase"], f"{where}.phase")
    if phase not in LIFECYCLE_PHASES:
        _fail("OPMODEL004_LIFECYCLE", f"{where}.phase", "unknown lifecycle phase")
    owner = _text(record["owner_role"], f"{where}.owner_role")
    if owner not in OWNER_ROLES:
        _fail("OPMODEL004_LIFECYCLE", f"{where}.owner_role", "unknown local owner role")
    test = _optional_text(record["test"], f"{where}.test")
    not_applicable = _optional_text(record["not_applicable"], f"{where}.not_applicable")
    _exclusive(test, not_applicable, where, "OPMODEL004_LIFECYCLE")
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

    @param record decoded state record
    @param where JSON path
    @return typed state
    """
    fields = {
        "id", "kind", "entry_conditions", "allowed_operations",
        "observable_event", "exit_condition",
    }
    _exact(record, fields, where)
    kind = _text(record["kind"], f"{where}.kind")
    if kind not in {"safe", "degraded"}:
        _fail("OPMODEL005_STATE_OUTCOME", f"{where}.kind", "expected safe or degraded")
    event = _text(record["observable_event"], f"{where}.observable_event")
    if EVENT_CODE.fullmatch(event) is None:
        _fail(
            "OPMODEL005_STATE_OUTCOME",
            f"{where}.observable_event",
            "expected stable hyphenated uppercase event code",
        )
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
    record = _object(value, where)
    _exact(record, {"value", "unit"}, where)
    number = record["value"]
    if isinstance(number, bool) or not isinstance(number, (int, float)) or number <= 0:
        _fail("OPMODEL006_BUDGET", f"{where}.value", "expected a positive number")
    unit = _text(record["unit"], f"{where}.unit")
    if unit not in BUDGET_UNITS[kind]:
        _fail(
            "OPMODEL006_BUDGET",
            f"{where}.unit",
            f"expected one of {sorted(BUDGET_UNITS[kind])}",
        )
    return Bound(value=number, unit=unit)


def _budget(record: Mapping[str, object], where: str) -> Budget:
    """Parse one budget class.

    @param record decoded budget record
    @param where JSON path
    @return typed budget
    """
    _exact(record, {"kind", "scope", "bound", "not_applicable", "measurement"}, where)
    kind = _text(record["kind"], f"{where}.kind")
    if kind not in BUDGET_KINDS:
        _fail("OPMODEL006_BUDGET", f"{where}.kind", "unknown budget class")
    raw_bound = record["bound"]
    bound = None if raw_bound is None else _bound(raw_bound, f"{where}.bound", kind)
    not_applicable = _optional_text(record["not_applicable"], f"{where}.not_applicable")
    measurement = _optional_text(record["measurement"], f"{where}.measurement")
    if (bound is None) == (not_applicable is None):
        _fail(
            "OPMODEL006_BUDGET",
            where,
            "exactly one of bound and not_applicable is required",
        )
    if (bound is None) != (measurement is None):
        _fail(
            "OPMODEL006_BUDGET",
            where,
            "a finite bound requires measurement and non-applicability forbids it",
        )
    return Budget(
        kind=kind,
        scope=_text(record["scope"], f"{where}.scope"),
        bound=bound,
        not_applicable=not_applicable,
        measurement=measurement,
    )


def _outcome(record: Mapping[str, object], where: str) -> Outcome:
    """Parse one observable terminal outcome.

    @param record decoded outcome record
    @param where JSON path
    @return typed outcome
    """
    fields = {
        "id", "exceptional", "trigger", "event_code", "correlation_field",
        "terminal_state", "test",
    }
    _exact(record, fields, where)
    exceptional = record["exceptional"]
    if not isinstance(exceptional, bool):
        _fail("OPMODEL005_STATE_OUTCOME", f"{where}.exceptional", "expected boolean")
    event = _text(record["event_code"], f"{where}.event_code")
    if EVENT_CODE.fullmatch(event) is None:
        _fail(
            "OPMODEL005_STATE_OUTCOME",
            f"{where}.event_code",
            "expected stable hyphenated uppercase event code",
        )
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

    @param value decoded identity object
    @param where JSON path
    @return typed identity
    """
    record = _object(value, where)
    _exact(record, {"build_source", "runtime_fields", "test"}, where)
    return Identity(
        build_source=_text(record["build_source"], f"{where}.build_source"),
        runtime_fields=_strings(record["runtime_fields"], f"{where}.runtime_fields"),
        test=_text(record["test"], f"{where}.test"),
    )


def _platform(record: Mapping[str, object], where: str) -> PlatformSupport:
    """Parse one platform support declaration.

    @param record decoded platform record
    @param where JSON path
    @return typed platform support
    """
    _exact(record, {"name", "runtime", "development", "evidence", "limitation"}, where)
    name = _text(record["name"], f"{where}.name")
    runtime = _text(record["runtime"], f"{where}.runtime")
    development = _text(record["development"], f"{where}.development")
    if name not in PLATFORMS:
        _fail("OPMODEL007_IDENTITY_PLATFORM", f"{where}.name", "unknown release platform")
    if runtime not in RUNTIME_SUPPORT or development not in DEVELOPMENT_SUPPORT:
        _fail(
            "OPMODEL007_IDENTITY_PLATFORM",
            where,
            "unknown runtime or development support outcome",
        )
    evidence = _optional_text(record["evidence"], f"{where}.evidence")
    limitation = _optional_text(record["limitation"], f"{where}.limitation")
    fully_supported = runtime == "supported" and development == "supported"
    if fully_supported and (evidence is None or limitation is not None):
        _fail(
            "OPMODEL007_IDENTITY_PLATFORM",
            where,
            "fully supported requires evidence and null limitation",
        )
    if not fully_supported and limitation is None:
        _fail(
            "OPMODEL007_IDENTITY_PLATFORM",
            where,
            "a non-supported outcome requires a limitation",
        )
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
    """
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as problem:
        _fail("OPMODEL001_SCHEMA", str(path), str(problem))
    root = _object(raw, "$")
    fields = {
        "schema_version", "capability_obligations", "lifecycle", "states",
        "budgets", "outcomes", "identity", "platforms",
    }
    _exact(root, fields, "$")
    if root["schema_version"] != 1:
        _fail("OPMODEL001_SCHEMA", "$.schema_version", "expected 1")
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
    lifecycle = tuple(
        _lifecycle(item, f"$.lifecycle[{index}]")
        for index, item in enumerate(_records(root["lifecycle"], "$.lifecycle"))
    )
    states = tuple(
        _state(item, f"$.states[{index}]")
        for index, item in enumerate(_records(root["states"], "$.states"))
    )
    budgets = tuple(
        _budget(item, f"$.budgets[{index}]")
        for index, item in enumerate(_records(root["budgets"], "$.budgets"))
    )
    outcomes = tuple(
        _outcome(item, f"$.outcomes[{index}]")
        for index, item in enumerate(_records(root["outcomes"], "$.outcomes"))
    )
    platforms = tuple(
        _platform(item, f"$.platforms[{index}]")
        for index, item in enumerate(_records(root["platforms"], "$.platforms"))
    )
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
    file_part = spelling.split("::", 1)[0]
    relative = PurePosixPath(file_part.replace("\\", "/"))
    if relative.is_absolute() or PureWindowsPath(file_part).drive or ".." in relative.parts:
        _fail(diagnostic_id, spelling, "path must stay inside the governed repository")
    candidate = (root / Path(relative.as_posix())).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        _fail(diagnostic_id, spelling, "resolved path leaves the governed repository")
    if not candidate.is_file():
        _fail(diagnostic_id, spelling, "declared local evidence file does not exist")
    return candidate


def _unique(values: Sequence[str], where: str, diagnostic_id: str) -> None:
    """Require a sequence to have no duplicate identities.

    @param values identifiers in model order
    @param where JSON collection path
    @param diagnostic_id semantic diagnostic to raise
    @throws OperationalError when a duplicate exists
    """
    if len(values) != len(set(values)):
        _fail(diagnostic_id, where, "duplicate identities are not allowed")


def _validate_capabilities(
    model: OperationalModel,
    active: frozenset[Capability],
    architecture: ArchitectureModel,
    root: Path,
) -> None:
    """Join enabled facts to architecture and generated obligations.

    @param model parsed operational model
    @param active explicit true capabilities
    @param architecture canonical local architecture model
    @param root governed repository root
    @throws OperationalError on stale joins or incomplete evidence
    """
    records = {item.capability: item for item in model.capability_records}
    _unique(
        [item.capability.value for item in model.capability_records],
        "$.capability_obligations",
        "OPMODEL002_CAPABILITY_JOIN",
    )
    if set(records) != set(active):
        _fail(
            "OPMODEL002_CAPABILITY_JOIN",
            "$.capability_obligations",
            f"missing={sorted(item.value for item in active - set(records))}, "
            f"inactive={sorted(item.value for item in set(records) - active)}",
        )
    resource_ids = {item.resource_id for item in architecture.resources}
    recovery_ids = {item.failure_id for item in architecture.recoveries}
    for capability, record in records.items():
        unknown_resources = set(record.resources) - resource_ids
        unknown_recoveries = set(record.recoveries) - recovery_ids
        if unknown_resources or unknown_recoveries:
            _fail(
                "OPMODEL003_OWNERSHIP_JOIN",
                capability.value,
                f"unknown resources={sorted(unknown_resources)}, "
                f"recoveries={sorted(unknown_recoveries)}",
            )
        actual = {item.obligation_id for item in record.tests}
        required = CAPABILITY_OBLIGATIONS[capability]
        if actual != required:
            _fail(
                "OPMODEL008_OBLIGATION",
                capability.value,
                f"missing={sorted(required - actual)}, unknown={sorted(actual - required)}",
            )
        for evidence in record.tests:
            _local_path(root, evidence.evidence, "OPMODEL008_OBLIGATION")


def _validate_lifecycle(
    model: OperationalModel,
    active: frozenset[Capability],
    state_ids: set[str],
    root: Path,
) -> None:
    """Require all phases and executable evidence for activated behavior.

    @param model parsed operational model
    @param active explicit true capabilities
    @param state_ids declared local state identities
    @param root governed repository root
    @throws OperationalError on missing, stale, or excused required phases
    """
    phases = {item.phase: item for item in model.lifecycle}
    _unique(
        [item.phase for item in model.lifecycle],
        "$.lifecycle",
        "OPMODEL004_LIFECYCLE",
    )
    if set(phases) != set(LIFECYCLE_PHASES):
        _fail(
            "OPMODEL004_LIFECYCLE",
            "$.lifecycle",
            f"expected exactly {list(LIFECYCLE_PHASES)}",
        )
    for phase, record in phases.items():
        if record.terminal_state not in state_ids:
            _fail(
                "OPMODEL004_LIFECYCLE",
                phase,
                f"unknown terminal state {record.terminal_state!r}",
            )
        required_by = PHASE_CAPABILITIES[phase]
        always = phase in {"startup", "steady_state", "shutdown"}
        if record.not_applicable is not None and (always or active & required_by):
            _fail(
                "OPMODEL004_LIFECYCLE",
                phase,
                "an activated lifecycle phase requires executable evidence",
            )
        if record.test is not None:
            _local_path(root, record.test, "OPMODEL004_LIFECYCLE")


def _validate_states_and_outcomes(model: OperationalModel, root: Path) -> set[str]:
    """Require safe/degraded states and observable ordinary outcomes.

    @param model parsed operational model
    @param root governed repository root
    @return declared state ids for lifecycle joining
    @throws OperationalError on duplicates, missing kinds, or stale evidence
    """
    state_ids = [item.state_id for item in model.states]
    outcome_ids = [item.outcome_id for item in model.outcomes]
    _unique(state_ids, "$.states", "OPMODEL005_STATE_OUTCOME")
    _unique(outcome_ids, "$.outcomes", "OPMODEL005_STATE_OUTCOME")
    kinds = {item.kind for item in model.states}
    if kinds != {"safe", "degraded"}:
        _fail(
            "OPMODEL005_STATE_OUTCOME",
            "$.states",
            "at least one safe and one degraded state are required",
        )
    known = set(state_ids)
    if not any(not item.exceptional for item in model.outcomes):
        _fail(
            "OPMODEL005_STATE_OUTCOME",
            "$.outcomes",
            "at least one non-exception terminal outcome is required",
        )
    for outcome in model.outcomes:
        if outcome.terminal_state not in known:
            _fail(
                "OPMODEL005_STATE_OUTCOME",
                outcome.outcome_id,
                f"unknown terminal state {outcome.terminal_state!r}",
            )
        _local_path(root, outcome.test, "OPMODEL005_STATE_OUTCOME")
    return known


def _validate_budgets(
    model: OperationalModel,
    active: frozenset[Capability],
    root: Path,
) -> None:
    """Require every budget class and finite bounds for activated work.

    @param model parsed operational model
    @param active explicit true capabilities
    @param root governed repository root
    @throws OperationalError on missing classes or unbounded activated work
    """
    budgets = {item.kind: item for item in model.budgets}
    _unique([item.kind for item in model.budgets], "$.budgets", "OPMODEL006_BUDGET")
    if set(budgets) != set(BUDGET_KINDS):
        _fail(
            "OPMODEL006_BUDGET",
            "$.budgets",
            f"expected exactly {list(BUDGET_KINDS)}",
        )
    for kind, budget in budgets.items():
        if budget.bound is None and active & BUDGET_CAPABILITIES[kind]:
            activators = sorted(item.value for item in active & BUDGET_CAPABILITIES[kind])
            _fail(
                "OPMODEL006_BUDGET",
                kind,
                f"finite bound required by {activators}",
            )
        if budget.measurement is not None:
            _local_path(root, budget.measurement, "OPMODEL006_BUDGET")


def _validate_identity_platform(model: OperationalModel, root: Path) -> None:
    """Require build/runtime identity and explicit Windows/Linux support.

    @param model parsed operational model
    @param root governed repository root
    @throws OperationalError on missing fields, platforms, or confined evidence
    """
    required_fields = {"version", "build_id"}
    if not required_fields <= set(model.identity.runtime_fields):
        _fail(
            "OPMODEL007_IDENTITY_PLATFORM",
            "$.identity.runtime_fields",
            f"missing {sorted(required_fields - set(model.identity.runtime_fields))}",
        )
    _local_path(root, model.identity.build_source, "OPMODEL007_IDENTITY_PLATFORM")
    _local_path(root, model.identity.test, "OPMODEL007_IDENTITY_PLATFORM")
    names = [item.name for item in model.platforms]
    _unique(names, "$.platforms", "OPMODEL007_IDENTITY_PLATFORM")
    if set(names) != PLATFORMS:
        _fail(
            "OPMODEL007_IDENTITY_PLATFORM",
            "$.platforms",
            f"expected exactly {sorted(PLATFORMS)}",
        )
    for platform in model.platforms:
        if platform.evidence is not None:
            _local_path(root, platform.evidence, "OPMODEL007_IDENTITY_PLATFORM")


def validate(
    model: OperationalModel,
    active: frozenset[Capability],
    architecture: ArchitectureModel,
    root: Path,
) -> None:
    """Cross-check the operational model against declaration and architecture.

    @param model parsed operational model
    @param active explicit true capabilities
    @param architecture canonical local architecture model
    @param root governed repository root
    @throws OperationalError on the first deterministic mismatch
    """
    _validate_capabilities(model, active, architecture, root)
    state_ids = _validate_states_and_outcomes(model, root)
    _validate_lifecycle(model, active, state_ids, root)
    _validate_budgets(model, active, root)
    _validate_identity_platform(model, root)


class OperationalModelCheck(Check):
    """Check local operational ownership, bounds, outcomes, identity, and evidence."""

    ## Mechanism token for repository-local operational rules.
    name = "operational_model"
    ## Independently diagnosable operational obligations.
    rules = ("OPS-003", "OPS-004", "OPS-005", "OPS-006", "OPS-007", "OPS-008")

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Validate only canonical paths from the nearest declaration.

        @param paths ignored caller selection; declaration-bound records are authoritative
        @return zero or one earliest deterministic finding
        """
        _ = paths
        model_path = self.declaration.operational_model_path()
        architecture_path = self.declaration.architecture_path()
        root = self.declaration.root
        if model_path is None or architecture_path is None or root is None:
            return []
        try:
            model = parse(model_path)
            architecture = parse_architecture(architecture_path)
            validate(model, self.declaration.capabilities, architecture, root)
        except ArchitectureError as problem:
            return [Finding(
                rule_id="OPS-003",
                path=architecture_path,
                line=1,
                message=f"architecture prerequisite failed at {problem.where}: {problem.detail}",
                remediation="Repair architecture.json before operational ownership joins.",
                diagnostic_id="OPMODEL003_OWNERSHIP_JOIN",
            )]
        except OperationalError as problem:
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
        return []


if __name__ == "__main__":
    from . import main

    raise SystemExit(main(OperationalModelCheck()))
