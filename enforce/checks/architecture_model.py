"""Validate the canonical repository-local architecture record.

``architecture.json`` is one source for four local views: information-hiding
decisions and their change scenarios, boundary interactions, resource ownership,
and failure recovery. The checker validates completeness and cross-references;
it does not claim the stated decisions are wise or the behavioral promises true.

For a component it also decides a deliberately narrow neutrality predicate:
external contract roles use lower-snake role identifiers and model text contains
no repository/topology vocabulary, endpoint URI, address, or filesystem path.
Neutral-looking prose can still conceal identity; structured adversarial review
owns that residual.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Never

from . import Check, Finding
from .project import UnitKind

# Import static collection and path contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

## Stable local identifiers used for decisions, contracts, resources, and failures.
LOCAL_ID: Final = re.compile(r"^[a-z][a-z0-9_]*$")
## Digest form for a locally vendored external contract snapshot.
DIGEST: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
## Identity-pattern elements in deterministic detection order; each regex recognizes deployment
## identity rather than a counterpart-neutral role.
IDENTITY_TEXT: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?i)\b(?:repository|repo|sibling checkout|parent checkout)\b"),
    re.compile(r"(?i)\bdeployment\s+(?:endpoint|host|topology|wiring)\b"),
    re.compile(r"(?i)\b(?:hostname|host name)\b"),
    re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://"),
    re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)"),
    re.compile(r"(?:^|\s)(?:[A-Za-z]:[\\/]|\.\.[\\/]|/[A-Za-z0-9_.-])"),
)
## Unordered role-name set whose each element may own a local decision, resource, or recovery.
OWNER_ROLES: Final = frozenset({"domain", "application", "ports", "adapters", "shell"})
## Unordered direction-name set whose each element describes a contract in the local view.
DIRECTIONS: Final = frozenset({"published", "consumed", "internal"})
## Unordered provenance-mode set whose each element identifies local or snapshot authority.
SOURCES: Final = frozenset({"local", "external_snapshot"})


class ArchitectureError(ValueError):
    """One stable architecture-model diagnostic."""

    ## Stable diagnostic namespace for rejected architecture-model propositions.
    code = "discipline.architecture_model.invalid"

    def __init__(self, diagnostic_id: str, where: str, detail: str) -> None:
        """Build a structured parse or semantic failure.

        @param diagnostic_id stable checker diagnostic
        @param where JSON path identifying the rejected value
        @param detail actionable explanation
        """
        # Initialize the standard message from the stable id, JSON location, and detail.
        super().__init__(f"{diagnostic_id} {where}: {detail}")
        # Retain the stable checker diagnostic for machine-readable gate output.
        self.diagnostic_id = diagnostic_id
        # Retain the exact JSON path identifying the rejected proposition.
        self.where = where
        # Retain the actionable schema or semantic explanation.
        self.detail = detail


def _fail(diagnostic_id: str, where: str, detail: str) -> Never:
    """Raise one model diagnostic.

    @param diagnostic_id stable checker diagnostic
    @param where JSON path identifying the rejected value
    @param detail actionable explanation
    @return never; this helper always raises
    @throws ArchitectureError unconditionally
    """
    # Translate the localized proposition into the sole typed architecture-error channel.
    raise ArchitectureError(diagnostic_id, where, detail)


def _object(value: object, where: str) -> Mapping[str, object]:
    """Require a JSON object.

    @param value untrusted decoded value
    @param where JSON path
    @return mapping whose each key is a JSON field name and each value is decoded data;
        source order is preserved by the decoder
    """
    # Only an object can supply the named fields required at this JSON location.
    if not isinstance(value, dict):
        # Reject scalar and array impostors without coercion.
        _fail("ARCH022_MODEL_SCHEMA", where, "expected an object")
    # Return the decoded key/value mapping with source order intact.
    return value


def _exact(record: Mapping[str, object], fields: set[str], where: str) -> None:
    """Require an exact field set so misspellings cannot be ignored.

    @param record mapping whose each key names a field and each value is decoded data;
        mapping iteration order is deliberately unused
    @param fields unordered field-name set whose each element is required and accepted
    @param where JSON path
    @throws ArchitectureError when fields are absent or unknown
    """
    # Build an unordered set whose each element is a required field absent from the record.
    missing = fields - set(record)
    # Build an unordered set whose each element is an unrecognized record field.
    unknown = set(record) - fields
    # Missing and unknown fields both make the closed schema unsafe to interpret.
    if missing or unknown:
        # Render each field-name set as a sorted sequence for deterministic diagnostics.
        detail = f"missing={sorted(missing)}, unknown={sorted(unknown)}"
        # Reject the exact object before any partial field interpretation.
        _fail("ARCH022_MODEL_SCHEMA", where, detail)


def _text(value: object, where: str) -> str:
    """Require a non-empty string.

    @param value untrusted decoded value
    @param where JSON path
    @return stripped text
    """
    # Require authored non-empty text rather than coercing scalar values.
    if not isinstance(value, str) or not value.strip():
        # Reject at the exact JSON path owning the contentless value.
        _fail("ARCH022_MODEL_SCHEMA", where, "expected non-empty text")
    # Return normalized text with insignificant surrounding whitespace removed.
    return value.strip()


def _identifier(value: object, where: str) -> str:
    """Require one stable lower-snake local identifier.

    @param value untrusted decoded value
    @param where JSON path
    @return validated identifier
    """
    # Parse and normalize the raw value as non-empty text first.
    text = _text(value, where)
    # Stable local identifiers use one complete lower-snake lexical shape.
    if LOCAL_ID.fullmatch(text) is None:
        # Reject topology/product identity and other invalid spellings at the exact path.
        _fail(
            "ARCH023_ROLE_IDENTITY", where,
            "expected a lower_snake role identifier, not a product or repository name",
        )
    # Return the validated stable identifier spelling.
    return text


def _texts(value: object, where: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    """Require an array of non-empty strings.

    @param value untrusted decoded value
    @param where JSON path
    @param allow_empty true when an explicit empty array is meaningful; false when non-empty
    @return non-empty string elements in source order
    """
    # Require an array and, unless explicitly permitted, at least one element.
    if not isinstance(value, list) or (not value and not allow_empty):
        # Reject absent, scalar, and disallowed empty values at the exact path.
        _fail("ARCH022_MODEL_SCHEMA", where, "expected a non-empty string array")
    # Parse each indexed text element while preserving authored source order.
    return tuple(_text(item, f"{where}[{index}]") for index, item in enumerate(value))


def _records(value: object, where: str, *, allow_empty: bool = False) -> list[Mapping[str, object]]:
    """Require an array of JSON objects.

    @param value untrusted decoded value
    @param where JSON path
    @param allow_empty true when an explicit empty view is meaningful; false when non-empty
    @return decoded object-record elements in source order
    """
    # Require an array and, unless explicitly permitted, at least one record element.
    if not isinstance(value, list) or (not value and not allow_empty):
        # Reject absent, scalar, and disallowed empty values at the exact path.
        _fail("ARCH022_MODEL_SCHEMA", where, "expected a non-empty record array")
    # Parse each indexed object element while preserving authored source order.
    return [_object(item, f"{where}[{index}]") for index, item in enumerate(value)]


@dataclass(frozen=True, slots=True)
class Decision:
    """One volatile decision and the changes its boundary should absorb."""

    ## Stable local identifier.
    decision_id: str
    ## Decision expected to vary independently.
    volatile_decision: str
    ## Architectural role hiding the decision.
    owner_role: str
    ## Concrete change-scenario text elements in authored order that should remain local.
    change_scenarios: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Operation:
    """Observable terms of one local contract operation."""

    ## Stable operation identifier.
    name: str
    ## Input contract in repository vocabulary.
    inputs: str
    ## Successful and typed outcome contract.
    outputs: str
    ## Published exceptional/refusal variant elements in authored order, explicitly possibly empty.
    errors: tuple[str, ...]
    ## Ordering guarantee or explicit absence.
    ordering: str
    ## Idempotency guarantee or explicit absence.
    idempotency: str
    ## Concurrency behavior or explicit serialization.
    concurrency: str
    ## Timeout behavior or explicit absence of a timeout at this boundary.
    timeout: str


@dataclass(frozen=True, slots=True)
class Contract:
    """One published, consumed, or repository-internal typed boundary."""

    ## Stable local contract identifier.
    contract_id: str
    ## Published, consumed, or internal direction.
    direction: str
    ## Counterpart-neutral role served by or used through the contract.
    role: str
    ## Locally meaningful contract version.
    version: str
    ## Local authority or external snapshot provenance mode.
    source: str
    ## Mapping from each provenance field-name key to its text value, or None for local authority;
    ## mapping insertion order is canonical source-role, version, then digest.
    provenance: Mapping[str, str] | None
    ## Complete operation-record elements in authored contract order.
    operations: tuple[Operation, ...]


@dataclass(frozen=True, slots=True)
class Resource:
    """One resource whose lifecycle is owned or explicitly transferred locally."""

    ## Stable local resource identifier.
    resource_id: str
    ## File, socket, thread, subprocess, queue, state, or more specific kind.
    kind: str
    ## Local architectural role initially owning lifecycle authority.
    owner_role: str
    ## Acquisition boundary and condition.
    acquire: str
    ## Release or cleanup boundary and condition.
    release: str
    ## Neutral external role receiving an explicit handoff, otherwise None.
    transfer_to_role: str | None


@dataclass(frozen=True, slots=True)
class Recovery:
    """One local failure's detection, containment, recovery, and terminal state."""

    ## Stable local failure identifier.
    failure_id: str
    ## Boundary that first detects the failure.
    detected_at: str
    ## Boundary beyond which the failure must not propagate untranslated.
    contained_at: str
    ## Local role responsible for the recovery decision.
    owner_role: str
    ## Local recovery action.
    action: str
    ## Escalation when local recovery cannot succeed.
    escalation: str
    ## Observable safe or degraded terminal state.
    terminal_state: str


@dataclass(frozen=True, slots=True)
class ArchitectureModel:
    """The complete canonical local architecture record."""

    ## Governed repository shape, joined against the project declaration.
    unit: UnitKind
    ## One responsibility owned by this repository.
    responsibility: str
    ## Information-hiding decision-record elements in authored order.
    decisions: tuple[Decision, ...]
    ## Local boundary/interaction contract-record elements in authored order.
    contracts: tuple[Contract, ...]
    ## Locally owned/transferred resource-record elements in authored order.
    resources: tuple[Resource, ...]
    ## Explanation required when the resource view is explicitly empty.
    resource_absence: str | None
    ## Local detection/containment/recovery record elements in authored order.
    recoveries: tuple[Recovery, ...]
    ## JSON-path/text pair elements in deterministic traversal order for neutrality analysis.
    all_text: tuple[tuple[str, str], ...]


def _decision(record: Mapping[str, object], where: str) -> Decision:
    """Parse one information-hiding decision.

    @param record mapping whose each key names a decision field and each value is decoded JSON;
        mapping iteration order is deliberately unused
    @param where JSON path
    @return typed decision
    """
    # Require the exact closed decision field vocabulary before interpreting content.
    _exact(record, {"id", "volatile_decision", "owner_role", "change_scenarios"}, where)
    # Parse the local architectural role responsible for hiding this decision.
    owner = _text(record["owner_role"], f"{where}.owner_role")
    # Decision ownership is limited to the five local hexagonal roles.
    if owner not in OWNER_ROLES:
        # Reject the unknown role at the exact decision field.
        _fail("ARCH021_DECISION_INCOMPLETE", f"{where}.owner_role", "unknown role")
    # Read the raw change-scenario array without coercing its shape.
    scenarios = record["change_scenarios"]
    # Each volatile decision needs at least one concrete future-change element.
    if not isinstance(scenarios, list) or not scenarios:
        # Reject absent, scalar, and empty scenario collections at the exact field.
        _fail(
            "ARCH021_DECISION_INCOMPLETE", f"{where}.change_scenarios",
            "each volatile decision needs at least one concrete change scenario",
        )
    # Construct the typed decision from its stable id, prose, owner, and ordered scenarios.
    return Decision(
        decision_id=_identifier(record["id"], f"{where}.id"),
        volatile_decision=_text(record["volatile_decision"], f"{where}.volatile_decision"),
        owner_role=owner,
        change_scenarios=_texts(scenarios, f"{where}.change_scenarios"),
    )


def _operation(record: Mapping[str, object], where: str) -> Operation:
    """Parse one complete interaction operation.

    @param record mapping whose each key names an operation field and each value is decoded JSON;
        mapping iteration order is deliberately unused
    @param where JSON path
    @return typed operation
    """
    # Build the unordered set whose each element is one required observable operation field.
    fields = {
        "name", "inputs", "outputs", "errors", "ordering",
        "idempotency", "concurrency", "timeout",
    }
    # Require the exact closed operation vocabulary before parsing any term.
    _exact(record, fields, where)
    # Construct the typed operation with error elements retained in authored order.
    return Operation(
        name=_identifier(record["name"], f"{where}.name"),
        inputs=_text(record["inputs"], f"{where}.inputs"),
        outputs=_text(record["outputs"], f"{where}.outputs"),
        errors=_texts(record["errors"], f"{where}.errors", allow_empty=True),
        ordering=_text(record["ordering"], f"{where}.ordering"),
        idempotency=_text(record["idempotency"], f"{where}.idempotency"),
        concurrency=_text(record["concurrency"], f"{where}.concurrency"),
        timeout=_text(record["timeout"], f"{where}.timeout"),
    )


def _contract(record: Mapping[str, object], where: str) -> Contract:
    """Parse one boundary contract and its snapshot provenance.

    @param record mapping whose each key names a contract field and each value is decoded JSON;
        mapping iteration order is deliberately unused
    @param where JSON path
    @return typed contract
    """
    # Build the unordered set whose each element is one required contract/provenance field.
    fields = {"id", "direction", "role", "version", "source", "provenance", "operations"}
    # Require the exact closed contract vocabulary before parsing any term.
    _exact(record, fields, where)
    # Parse the contract's direction within this repository's local view.
    direction = _text(record["direction"], f"{where}.direction")
    # Parse the local-authority or external-snapshot provenance mode.
    source = _text(record["source"], f"{where}.source")
    # Contract direction belongs to the closed published/consumed/internal vocabulary.
    if direction not in DIRECTIONS:
        # Reject the unknown direction at its exact field.
        _fail("ARCH022_MODEL_SCHEMA", f"{where}.direction", "unknown direction")
    # Provenance mode belongs to the closed local/external-snapshot vocabulary.
    if source not in SOURCES:
        # Reject the unknown mode at its exact field.
        _fail("ARCH022_MODEL_SCHEMA", f"{where}.source", "unknown provenance mode")
    # Retain the raw optional provenance object for source-mode consistency checks.
    raw_provenance = record["provenance"]
    # Start with no provenance, or later a mapping whose each field key names a text value
    # in canonical source-role/version/digest insertion order.
    provenance: Mapping[str, str] | None = None
    # A locally authoritative contract must not claim an external snapshot record.
    if source == "local" and raw_provenance is not None:
        # Reject the inconsistent provenance field.
        _fail("ARCH022_MODEL_SCHEMA", f"{where}.provenance", "local contracts use null")
    # External snapshots require a complete source role, version, and digest record.
    if source == "external_snapshot":
        # Narrow the raw provenance value to a JSON object mapping.
        parsed = _object(raw_provenance, f"{where}.provenance")
        # Require the exact closed provenance field set.
        _exact(parsed, {"source_role", "version", "digest"}, f"{where}.provenance")
        # Parse the external snapshot's declared digest text.
        digest = _text(parsed["digest"], f"{where}.provenance.digest")
        # Snapshot identity uses one exact lowercase SHA-256 spelling.
        if DIGEST.fullmatch(digest) is None:
            # Reject malformed digest provenance at the exact field.
            _fail("ARCH022_MODEL_SCHEMA", f"{where}.provenance.digest", "expected sha256 digest")
        # Build the canonical three-pair provenance mapping in source-role/version/digest order.
        provenance = {
            "source_role": _identifier(parsed["source_role"], f"{where}.provenance.source_role"),
            "version": _text(parsed["version"], f"{where}.provenance.version"),
            "digest": digest,
        }
    # Parse each operation-record element in authored contract order.
    operations = tuple(
        _operation(item, f"{where}.operations[{index}]")
        for index, item in enumerate(_records(record["operations"], f"{where}.operations"))
    )
    # Construct the typed contract from validated identity, provenance, and ordered operations.
    return Contract(
        contract_id=_identifier(record["id"], f"{where}.id"),
        direction=direction,
        role=_identifier(record["role"], f"{where}.role"),
        version=_text(record["version"], f"{where}.version"),
        source=source,
        provenance=provenance,
        operations=operations,
    )


def _resource(record: Mapping[str, object], where: str) -> Resource:
    """Parse one resource ownership or handoff record.

    @param record mapping whose each key names a resource field and each value is decoded JSON;
        mapping iteration order is deliberately unused
    @param where JSON path
    @return typed resource
    """
    # Build the unordered set whose each element is one required lifecycle/resource field.
    fields = {"id", "kind", "owner_role", "acquire", "release", "transfer_to_role"}
    # Require the exact closed resource vocabulary before parsing lifecycle terms.
    _exact(record, fields, where)
    # Parse the local architectural role initially owning lifecycle authority.
    owner = _text(record["owner_role"], f"{where}.owner_role")
    # Resource ownership is limited to the five local hexagonal roles.
    if owner not in OWNER_ROLES:
        # Reject the unknown role at the exact resource field.
        _fail("ARCH022_RESOURCE_OWNER", f"{where}.owner_role", "unknown local role")
    # Retain the raw optional external-role handoff value.
    transfer_raw = record["transfer_to_role"]
    # Parse a present neutral role identifier, or preserve the explicit no-transfer alternative.
    transfer = (
        None
        if transfer_raw is None
        else _identifier(transfer_raw, f"{where}.transfer_to_role")
    )
    # Construct the typed resource from identity, owner, lifecycle terms, and optional transfer.
    return Resource(
        resource_id=_identifier(record["id"], f"{where}.id"),
        kind=_text(record["kind"], f"{where}.kind"),
        owner_role=owner,
        acquire=_text(record["acquire"], f"{where}.acquire"),
        release=_text(record["release"], f"{where}.release"),
        transfer_to_role=transfer,
    )


def _recovery(record: Mapping[str, object], where: str) -> Recovery:
    """Parse one local failure and recovery view record.

    @param record mapping whose each key names a recovery field and each value is decoded JSON;
        mapping iteration order is deliberately unused
    @param where JSON path
    @return typed recovery record
    """
    # Build the unordered set whose each element is one required failure/recovery field.
    fields = {
        "failure", "detected_at", "contained_at", "owner_role",
        "action", "escalation", "terminal_state",
    }
    # Require the exact closed recovery vocabulary before parsing behavior terms.
    _exact(record, fields, where)
    # Parse the local architectural role responsible for recovery decisions.
    owner = _text(record["owner_role"], f"{where}.owner_role")
    # Recovery ownership is limited to the five local hexagonal roles.
    if owner not in OWNER_ROLES:
        # Reject the unknown role at the exact recovery field.
        _fail("ARCH022_RECOVERY_OWNER", f"{where}.owner_role", "unknown local role")
    # Construct the typed recovery from identity, boundaries, actions, and terminal state.
    return Recovery(
        failure_id=_identifier(record["failure"], f"{where}.failure"),
        detected_at=_text(record["detected_at"], f"{where}.detected_at"),
        contained_at=_text(record["contained_at"], f"{where}.contained_at"),
        owner_role=owner,
        action=_text(record["action"], f"{where}.action"),
        escalation=_text(record["escalation"], f"{where}.escalation"),
        terminal_state=_text(record["terminal_state"], f"{where}.terminal_state"),
    )


def _walk_text(value: object, where: str = "$") -> tuple[tuple[str, str], ...]:
    """Collect every string with its JSON path for neutrality diagnostics.

    @param value decoded JSON subtree
    @param where path of that subtree
    @return JSON-path/text pair elements in deterministic traversal order
    """
    # A string leaf contributes one path/text pair at the current traversal position.
    if isinstance(value, str):
        # Return the one-element ordered pair sequence.
        return ((where, value),)
    # Array children retain authored element order and indexed JSON paths.
    if isinstance(value, list):
        # Flatten each child's path/text elements in index then recursive traversal order.
        return tuple(
            pair
            for index, item in enumerate(value)
            for pair in _walk_text(item, f"{where}[{index}]")
        )
    # Object children use sorted keys so source field order cannot change neutrality diagnostics.
    if isinstance(value, dict):
        # Flatten each child's path/text elements in key then recursive traversal order.
        return tuple(
            pair
            for key in sorted(value)
            for pair in _walk_text(value[key], f"{where}.{key}")
        )
    # Non-string scalar leaves contribute no identity-bearing text elements.
    return ()


def parse(path: Path) -> ArchitectureModel:
    """Parse and cross-check one canonical local architecture record.

    @param path JSON model path
    @return complete typed model
    @throws ArchitectureError when syntax, fields, or local references are invalid
    @par Effects Reads the local JSON model without modifying repository state.
    """
    # Decode the exact UTF-8 model while containing access and JSON syntax failures.
    try:
        # Hold the complete untrusted decoded JSON value before schema narrowing.
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    # Translate model access and syntax failures into the stable schema channel.
    except (OSError, json.JSONDecodeError) as problem:
        # Reject at the model path while retaining the concrete decode detail.
        _fail("ARCH022_MODEL_SCHEMA", str(path), str(problem))
    # Narrow the decoded root to a source-ordered field/value mapping.
    root = _object(raw, "$")
    # Build the unordered set whose each element is one required top-level model field.
    fields = {
        "schema_version", "unit", "responsibility", "decisions", "contracts",
        "resources", "resource_absence", "recoveries",
    }
    # Require the exact closed root vocabulary before interpreting model content.
    _exact(root, fields, "$")
    # Schema version one is the sole architecture model shape understood by this package.
    if root["schema_version"] != 1:
        # Reject missing, differently typed, or future version values explicitly.
        _fail("ARCH022_MODEL_SCHEMA", "$.schema_version", "expected 1")
    # Read the raw governed repository-unit spelling without coercion.
    raw_unit = root["unit"]
    # Unit must be text before conversion to the closed repository-shape enumeration.
    if not isinstance(raw_unit, str):
        # Reject non-text unit values at the exact field.
        _fail("ARCH021_UNIT_MISMATCH", "$.unit", "expected application or component")
    # Convert the unit spelling to the application/component enumeration.
    try:
        # Hold the validated governed unit for declaration cross-checking.
        unit = UnitKind(raw_unit)
    # Translate an unknown spelling into the stable unit diagnostic.
    except ValueError:
        # Reject without guessing application-versus-component scope.
        _fail("ARCH021_UNIT_MISMATCH", "$.unit", "expected application or component")
    # Parse each decision-record element in authored array order.
    decisions = tuple(
        _decision(item, f"$.decisions[{index}]")
        for index, item in enumerate(_records(root["decisions"], "$.decisions"))
    )
    # Parse each contract-record element in authored array order.
    contracts = tuple(
        _contract(item, f"$.contracts[{index}]")
        for index, item in enumerate(_records(root["contracts"], "$.contracts"))
    )
    # Parse each resource-record element in authored order, admitting an explicit empty view.
    resources = tuple(
        _resource(item, f"$.resources[{index}]")
        for index, item in enumerate(_records(root["resources"], "$.resources", allow_empty=True))
    )
    # Read the optional explicit explanation for an empty resource view.
    absence_raw = root["resource_absence"]
    # A non-empty resource sequence makes an absence explanation inconsistent.
    if resources and absence_raw is not None:
        # Reject the contradictory explanation at its exact field.
        _fail("ARCH022_RESOURCE_OWNER", "$.resource_absence", "must be null when resources exist")
    # An empty resource sequence requires an authored explanation rather than silent omission.
    if not resources and absence_raw is None:
        # Reject the unexplained empty ownership view.
        _fail("ARCH022_RESOURCE_OWNER", "$.resource_absence", "explain the explicit empty view")
    # Parse a present absence explanation, or preserve None for the non-empty resource alternative.
    absence = None if absence_raw is None else _text(absence_raw, "$.resource_absence")
    # Parse each failure-recovery record element in authored array order.
    recoveries = tuple(
        _recovery(item, f"$.recoveries[{index}]")
        for index, item in enumerate(_records(root["recoveries"], "$.recoveries"))
    )
    # Flatten each local id element in view order: decisions, contracts, resources, recoveries.
    identities = [
        *(decision.decision_id for decision in decisions),
        *(contract.contract_id for contract in contracts),
        *(resource.resource_id for resource in resources),
        *(recovery.failure_id for recovery in recoveries),
    ]
    # Duplicate identities make cross-view references ambiguous.
    if len(identities) != len(set(identities)):
        # Reject at model root rather than selecting one duplicated view record.
        _fail("ARCH022_MODEL_SCHEMA", "$", "local ids must be unique across all views")
    # Construct the complete typed model and deterministic text traversal after cross-checks pass.
    return ArchitectureModel(
        unit=unit,
        responsibility=_text(root["responsibility"], "$.responsibility"),
        decisions=decisions,
        contracts=contracts,
        resources=resources,
        resource_absence=absence,
        recoveries=recoveries,
        all_text=_walk_text(raw),
    )


def neutrality_failure(model: ArchitectureModel) -> tuple[str, str] | None:
    """Find the first lexical component-identity or topology leak.

    @param model parsed architecture model
    @return JSON path and offending text, or None when the narrow predicate holds
    """
    # Non-component repositories do not owe counterpart-neutral external identities.
    if model.unit is not UnitKind.COMPONENT:
        # Return the no-failure alternative without scanning model prose.
        return None
    # Inspect each JSON-path/text pair in deterministic model traversal order.
    for where, value in model.all_text:
        # Any identity pattern match proves a narrow lexical topology leak.
        if any(pattern.search(value) is not None for pattern in IDENTITY_TEXT):
            # Return the first offending JSON path and exact text for localized remediation.
            return where, value
    # None means the complete component model passes the bounded lexical neutrality predicate.
    return None


class ArchitectureModelCheck(Check):
    """Join the declaration to complete, local, counterpart-neutral architecture views."""

    ## Mechanism token declared by ARCH-021 through ARCH-023.
    name = "architecture_model"
    ## Ordered rule-id elements for unit/completeness, model structure, then neutrality.
    rules = ("ARCH-021", "ARCH-022", "ARCH-023")

    def run(self, _paths: Sequence[Path]) -> list[Finding]:
        """Validate this declaration's canonical model without reading another repository.

        @param _paths path elements in caller order, ignored because the declaration owns the model
        @return an empty sequence or one earliest structural/unit/neutrality finding element
        @par Effects Resolves and reads the declared architecture model without modifying it.
        """
        # Resolve the optional local architecture artifact through the project declaration.
        path = self.declaration.architecture_path()
        # A legacy direct-check fallback has no canonical model for this check to own.
        if path is None:
            # Return the ordered empty finding sequence.
            return []
        # Parse and cross-check the complete architecture model through its typed error channel.
        try:
            # Hold the valid typed model for declaration and neutrality joins.
            model = parse(path)
        # Convert the earliest typed model refusal into the ordinary custom-check contract.
        except ArchitectureError as problem:
            # Map the stable diagnostic prefix to its owning normative rule id.
            rule = {
                "ARCH021": "ARCH-021",
                "ARCH022": "ARCH-022",
                "ARCH023": "ARCH-023",
            }[problem.diagnostic_id[:7]]
            # Return the sole localized structural finding.
            return [Finding(
                rule_id=rule, path=path, line=1,
                message=f"{problem.where}: {problem.detail}",
                remediation="Repair the canonical local architecture record from its template.",
                diagnostic_id=problem.diagnostic_id,
            )]
        # The architecture record and project declaration must name the same governed unit.
        if model.unit is not self.declaration.unit:
            # Return the sole cross-artifact unit mismatch finding.
            return [Finding(
                rule_id="ARCH-021", path=path, line=1,
                message=(
                    f"architecture unit {model.unit!s} disagrees with project unit "
                    f"{self.declaration.unit!s}"
                ),
                remediation="Use the same one governed-unit kind in both canonical records.",
                diagnostic_id="ARCH021_UNIT_MISMATCH",
            )]
        # Apply the bounded lexical counterpart-neutrality predicate to component models.
        leaked = neutrality_failure(model)
        # A present pair contains the first offending JSON path and exact identity-bearing text.
        if leaked is not None:
            # Unpack the fixed pair in JSON-path then offending-text order.
            where, value = leaked
            # Return the sole localized component-neutrality finding.
            return [Finding(
                rule_id="ARCH-023", path=path, line=1,
                message=f"{where} carries counterpart identity or deployment wiring: {value!r}",
                remediation=(
                    "Describe the external actor only by a lower_snake contract role and "
                    "remove repository, endpoint, address, and topology identity."
                ),
                diagnostic_id="ARCH023_COUNTERPART_IDENTITY",
            )]
        # A structurally complete, unit-consistent, neutral model contributes no findings.
        return []


# Run the standalone architecture-model check only at this module's process boundary.
if __name__ == "__main__":
    # Import the runner only for script execution, avoiding an ordinary module dependency cycle.
    from . import main

    # Convert the check runner's stable result into the process exit status.
    raise SystemExit(main(ArchitectureModelCheck()))
