"""Validate local trust boundaries and classified-data handling.

``security-model.json`` covers only the governed repository. It joins every
local architecture contract to an entry trust decision and records how each
declared data class may move, persist, and appear in diagnostics. The checker
decides completeness, joins, vocabulary, and confined evidence paths. It does
not decide whether an assumption is realistic or a validation is sufficient;
structured adversarial review owns those semantic residuals.
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

# Import static collection contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

## Stable lower-snake identities shared by model records and local sink names.
IDENTIFIER: Final = re.compile(r"^[a-z][a-z0-9_]*$")
## Unordered role-name set whose each element may receive data inside the governed repository.
OWNER_ROLES: Final = frozenset({"domain", "application", "ports", "adapters", "shell"})
## Unordered trust-level set whose each element may describe inbound data before validation.
TRUST_LEVELS: Final = frozenset({"untrusted", "constrained", "trusted_local"})
## Unordered classification set whose each element names one closed local data category.
CLASSIFICATIONS: Final = frozenset({
    "public", "internal", "confidential", "secret", "personal",
})
## Unordered classification subset whose each element activates the sensitive-data capability.
SENSITIVE_CLASSES: Final = frozenset({"confidential", "secret", "personal"})


class SecurityModelError(ValueError):
    """One stable security-model diagnostic."""

    ## Stable diagnostic namespace for rejected security-model propositions.
    code = "discipline.security_model.invalid"

    def __init__(self, diagnostic_id: str, where: str, detail: str) -> None:
        """Build one actionable model failure.

        @param diagnostic_id stable mechanism diagnostic
        @param where JSON path or repository location
        @param detail explanation of the violated predicate
        """
        # Initialize the standard message from the stable id, JSON location, and detail.
        super().__init__(f"{diagnostic_id} {where}: {detail}")
        # Retain the stable mechanism diagnostic for machine-readable gate output.
        self.diagnostic_id = diagnostic_id
        # Retain the exact JSON or repository location of the rejected proposition.
        self.where = where
        # Retain the actionable predicate explanation.
        self.detail = detail


def _fail(diagnostic_id: str, where: str, detail: str) -> Never:
    """Raise one security-model diagnostic.

    @param diagnostic_id stable mechanism diagnostic
    @param where JSON path or repository location
    @param detail explanation of the violated predicate
    @return never; this helper always raises
    @throws SecurityModelError unconditionally
    """
    # Translate the localized proposition into the sole typed security-error channel.
    raise SecurityModelError(diagnostic_id, where, detail)


def _object(value: object, where: str) -> Mapping[str, object]:
    """Require a JSON object.

    @param value untrusted decoded value
    @param where JSON path
    @return mapping whose each key is a JSON field name and each value is decoded data;
        source order is preserved by the decoder
    """
    # Only an object can supply named fields at this JSON location.
    if not isinstance(value, dict):
        # Reject scalar and array impostors without coercion.
        _fail("SECMODEL001_SCHEMA", where, "expected an object")
    # Return the decoded key/value mapping with source order intact.
    return value


def _exact(record: Mapping[str, object], fields: set[str], where: str) -> None:
    """Reject missing and ignored fields.

    @param record mapping whose each key names a field and each value is decoded data;
        mapping iteration order is deliberately unused
    @param fields unordered field-name set whose each element is required and accepted
    @param where JSON path
    @throws SecurityModelError when the field set differs
    """
    # Build an unordered set whose each element is a required field absent from the record.
    missing = fields - set(record)
    # Build an unordered set whose each element is an unrecognized record field.
    unknown = set(record) - fields
    # Missing and unknown fields both make the closed schema unsafe to interpret.
    if missing or unknown:
        # Reject with independently sorted field-name element sequences.
        _fail(
            "SECMODEL001_SCHEMA",
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
        _fail("SECMODEL001_SCHEMA", where, "expected non-empty text")
    # Return normalized text with insignificant surrounding whitespace removed.
    return value.strip()


def _optional_text(value: object, where: str) -> str | None:
    """Require null or non-empty text.

    @param value untrusted decoded value
    @param where JSON path
    @return stripped text or None
    """
    # Preserve explicit null, or parse the present alternative as non-empty text.
    return None if value is None else _text(value, where)


def _identifier(value: object, where: str) -> str:
    """Require one lower-snake identifier.

    @param value untrusted decoded value
    @param where JSON path
    @return validated identifier
    """
    # Parse and normalize the raw value as non-empty text first.
    text = _text(value, where)
    # Stable local identities use one complete lower-snake lexical shape.
    if IDENTIFIER.fullmatch(text) is None:
        # Reject invalid identity spelling at the exact JSON path.
        _fail("SECMODEL001_SCHEMA", where, "expected lower_snake identifier")
    # Return the validated stable identifier spelling.
    return text


def _strings(value: object, where: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    """Require a unique string array.

    @param value untrusted decoded value
    @param where JSON path
    @param allow_empty true when an explicit empty array is meaningful; false when non-empty
    @return unique non-empty string elements in source order
    """
    # Require an array and, unless explicitly permitted, at least one element.
    if not isinstance(value, list) or (not value and not allow_empty):
        # Reject absent, scalar, and disallowed empty values at the exact path.
        _fail("SECMODEL001_SCHEMA", where, "expected a string array")
    # Parse each indexed text element while preserving authored source order.
    values = tuple(_text(item, f"{where}[{index}]") for index, item in enumerate(value))
    # Duplicate values have no independent meaning and make joins ambiguous.
    if len(values) != len(set(values)):
        # Reject rather than silently deduplicating source intent.
        _fail("SECMODEL001_SCHEMA", where, "duplicate values are not allowed")
    # Return the unique string elements in authored source order.
    return values


def _records(
    value: object, where: str, *, allow_empty: bool = False,
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
        _fail("SECMODEL001_SCHEMA", where, "expected a record array")
    # Parse each indexed object element while preserving authored source order.
    return [_object(item, f"{where}[{index}]") for index, item in enumerate(value)]


@dataclass(frozen=True, slots=True)
class TrustBoundary:
    """One local entry boundary and the trust it establishes."""

    ## Stable local boundary identity.
    boundary_id: str
    ## Architecture contract-id elements in authored order entering through this boundary.
    contracts: tuple[str, ...]
    ## Trust attributed before validation.
    inbound_trust: str
    ## Assumption text elements in authored order on which local behavior relies.
    assumptions: tuple[str, ...]
    ## Validation text elements in authored order performed before stronger trust is granted.
    validations: tuple[str, ...]
    ## Point beyond which this boundary's trust claim no longer applies.
    trust_ceases_at: str
    ## Local behavioral evidence path.
    evidence: str


@dataclass(frozen=True, slots=True)
class DataClass:
    """One class of data with explicit exposure controls."""

    ## Stable data-class identity.
    data_id: str
    ## Public, internal, confidential, secret, or personal.
    classification: str
    ## Trust-boundary id elements in authored order through which the data enters.
    sources: tuple[str, ...]
    ## Local role-name elements in authored order allowed to receive the data.
    allowed_roles: tuple[str, ...]
    ## Named sink-id elements in authored order allowed to receive the data.
    allowed_sinks: tuple[str, ...]
    ## Retention and deletion policy.
    retention: str
    ## Redaction or deliberate non-redaction policy.
    redaction: str
    ## Local evidence path.
    evidence: str


@dataclass(frozen=True, slots=True)
class SecurityModel:
    """Complete local trust and data-classification model."""

    ## Trust-boundary record elements in authored order covering every architecture contract.
    boundaries: tuple[TrustBoundary, ...]
    ## Data-class record elements in authored order intentionally handled by the repository.
    data_classes: tuple[DataClass, ...]
    ## Rationale when no sensitive class is intentionally handled.
    sensitive_data_absence: str | None


def _trust_boundary(record: Mapping[str, object], where: str) -> TrustBoundary:
    """Parse one trust-boundary record.

    @param record mapping whose each key names a boundary field and each value is decoded JSON;
        mapping iteration order is deliberately unused
    @param where JSON path
    @return typed boundary
    """
    # Build the unordered set whose each element is one required trust-boundary field.
    fields = {
        "id", "contracts", "inbound_trust", "assumptions", "validations",
        "trust_ceases_at", "evidence",
    }
    # Require the exact closed boundary vocabulary before parsing trust terms.
    _exact(record, fields, where)
    # Parse the trust attributed to inbound values before validation.
    inbound = _text(record["inbound_trust"], f"{where}.inbound_trust")
    # Inbound trust belongs to the closed untrusted/constrained/trusted-local vocabulary.
    if inbound not in TRUST_LEVELS:
        # Reject the unknown level at its exact field with sorted allowed elements.
        _fail(
            "SECMODEL003_TRUST_BOUNDARY",
            f"{where}.inbound_trust",
            f"expected one of {sorted(TRUST_LEVELS)}",
        )
    # Construct the boundary with contract, assumption, and validation elements in authored order.
    return TrustBoundary(
        boundary_id=_identifier(record["id"], f"{where}.id"),
        contracts=_strings(record["contracts"], f"{where}.contracts"),
        inbound_trust=inbound,
        assumptions=_strings(record["assumptions"], f"{where}.assumptions"),
        validations=_strings(record["validations"], f"{where}.validations"),
        trust_ceases_at=_text(record["trust_ceases_at"], f"{where}.trust_ceases_at"),
        evidence=_text(record["evidence"], f"{where}.evidence"),
    )


def _data_class(record: Mapping[str, object], where: str) -> DataClass:
    """Parse one classified-data record.

    @param record mapping whose each key names a data field and each value is decoded JSON;
        mapping iteration order is deliberately unused
    @param where JSON path
    @return typed data class
    """
    # Build the unordered set whose each element is one required classification/exposure field.
    fields = {
        "id", "classification", "sources", "allowed_roles", "allowed_sinks",
        "retention", "redaction", "evidence",
    }
    # Require the exact closed data-class vocabulary before parsing controls.
    _exact(record, fields, where)
    # Parse the declared closed data-classification spelling.
    classification = _text(record["classification"], f"{where}.classification")
    # Classification belongs to the model's closed local vocabulary.
    if classification not in CLASSIFICATIONS:
        # Reject the unknown category at its exact field with sorted allowed elements.
        _fail(
            "SECMODEL004_CLASSIFICATION",
            f"{where}.classification",
            f"expected one of {sorted(CLASSIFICATIONS)}",
        )
    # Parse each allowed local role-name element in authored order.
    roles = _strings(record["allowed_roles"], f"{where}.allowed_roles")
    # Build an unordered set whose each element is an allowed role absent from local vocabulary.
    unknown_roles = set(roles) - OWNER_ROLES
    # Any unknown role would permit exposure outside the closed repository architecture.
    if unknown_roles:
        # Reject with sorted unknown-role elements at the exact exposure field.
        _fail(
            "SECMODEL005_EXPOSURE",
            f"{where}.allowed_roles",
            f"unknown local roles {sorted(unknown_roles)}",
        )
    # Parse each allowed sink-id element in authored order, admitting an explicit empty set.
    sinks = _strings(record["allowed_sinks"], f"{where}.allowed_sinks", allow_empty=True)
    # Every sink identity must use the stable lower-snake lexical shape.
    if any(IDENTIFIER.fullmatch(item) is None for item in sinks):
        # Reject the complete sink collection rather than ignoring one invalid endpoint.
        _fail("SECMODEL005_EXPOSURE", f"{where}.allowed_sinks", "invalid sink id")
    # Construct the typed data class with source, role, and sink elements in authored order.
    return DataClass(
        data_id=_identifier(record["id"], f"{where}.id"),
        classification=classification,
        sources=_strings(record["sources"], f"{where}.sources"),
        allowed_roles=roles,
        allowed_sinks=sinks,
        retention=_text(record["retention"], f"{where}.retention"),
        redaction=_text(record["redaction"], f"{where}.redaction"),
        evidence=_text(record["evidence"], f"{where}.evidence"),
    )


def parse(path: Path) -> SecurityModel:
    """Parse one exact canonical security model.

    @param path local JSON model path
    @return typed security model
    @throws SecurityModelError when syntax or fields are invalid
    @par Effects Reads the local JSON model without modifying repository state.
    """
    # Decode the exact UTF-8 model while containing access, encoding, and JSON failures.
    try:
        # Hold the complete untrusted decoded JSON value before schema narrowing.
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    # Translate model-read failures into the stable schema channel.
    except (OSError, UnicodeError, json.JSONDecodeError) as problem:
        # Reject at the model path while retaining the concrete decode detail.
        _fail("SECMODEL001_SCHEMA", str(path), str(problem))
    # Narrow the decoded root to a source-ordered field/value mapping.
    root = _object(raw, "$")
    # Require the exact closed top-level model vocabulary.
    _exact(
        root,
        {"schema_version", "trust_boundaries", "data_classes", "sensitive_data_absence"},
        "$",
    )
    # Schema version one is the sole security-model shape understood by this package.
    if root["schema_version"] != 1:
        # Reject missing, differently typed, or future version values explicitly.
        _fail("SECMODEL001_SCHEMA", "$.schema_version", "expected 1")
    # Parse each trust-boundary record element in authored array order.
    boundaries = tuple(
        _trust_boundary(item, f"$.trust_boundaries[{index}]")
        for index, item in enumerate(_records(root["trust_boundaries"], "$.trust_boundaries"))
    )
    # Parse each data-class record element in authored order, admitting an explicit empty view.
    data_classes = tuple(
        _data_class(item, f"$.data_classes[{index}]")
        for index, item in enumerate(
            _records(root["data_classes"], "$.data_classes", allow_empty=True),
        )
    )
    # Construct the typed model with ordered records and the optional absence rationale.
    return SecurityModel(
        boundaries=boundaries,
        data_classes=data_classes,
        sensitive_data_absence=_optional_text(
            root["sensitive_data_absence"], "$.sensitive_data_absence",
        ),
    )


def _local_path(root: Path, spelling: str, diagnostic_id: str) -> Path:
    """Resolve one confined evidence path.

    @param root governed repository root
    @param spelling POSIX path with an optional pytest node suffix
    @param diagnostic_id diagnostic to raise for unsafe or absent evidence
    @return existing local file path
    @par Effects Resolves and inspects the declared evidence file without modifying it.
    """
    # Strip an optional pytest node suffix while retaining the local file spelling.
    file_part = spelling.split("::", 1)[0]
    # Normalize separators into a platform-independent relative path candidate.
    relative = PurePosixPath(file_part.replace("\\", "/"))
    # True means an absolute, drive-qualified, or parent-traversing shape; false is relative.
    unsafe_shape = any(
        (relative.is_absolute(), bool(PureWindowsPath(file_part).drive), ".." in relative.parts)
    )
    # Refuse every syntactically unsafe evidence path before filesystem resolution.
    if unsafe_shape:
        # Reject the exact evidence spelling without broadening the repository boundary.
        _fail(diagnostic_id, spelling, "path must stay inside the governed repository")
    # Resolve the normalized candidate against the one governed repository root.
    candidate = (root / Path(relative.as_posix())).resolve()
    # Verify containment again after filesystem and platform normalization.
    try:
        # Compute a relative form solely to prove the candidate remains inside root.
        candidate.relative_to(root.resolve())
    # A containment failure indicates link or normalization escape.
    except ValueError:
        # Reject the exact evidence spelling without using the escaped path.
        _fail(diagnostic_id, spelling, "resolved path leaves the governed repository")
    # Evidence must identify an existing file rather than a directory or future promise.
    if not candidate.is_file():
        # Reject stale or mistyped evidence at its declared spelling.
        _fail(diagnostic_id, spelling, "declared local evidence file does not exist")
    # Return the existing confined local evidence file.
    return candidate


def _unique(values: Sequence[str], where: str, diagnostic_id: str) -> None:
    """Require identities to occur once.

    @param values record-identity elements in source order
    @param where JSON collection path
    @param diagnostic_id semantic diagnostic
    @throws SecurityModelError when an identity repeats
    """
    # Equal list/set cardinality means every identity is unique; inequality proves a duplicate.
    if len(values) != len(set(values)):
        # Reject the complete identity collection rather than selecting one duplicate record.
        _fail(diagnostic_id, where, "duplicate identities are not allowed")


def _validate_boundaries(
    model: SecurityModel, architecture: ArchitectureModel, root: Path,
) -> set[str]:
    """Join trust boundaries to every local contract.

    @param model parsed local security model
    @param architecture canonical architecture model
    @param root governed repository root
    @return unordered set whose each element is one known trust-boundary id
    @throws SecurityModelError on incomplete joins or stale evidence
    @par Effects Resolves and inspects each declared evidence file without modifying it.
    """
    # Preserve each boundary-id element in authored model order for uniqueness validation.
    boundary_ids = [item.boundary_id for item in model.boundaries]
    # Require each boundary identity exactly once before using it as a join key.
    _unique(boundary_ids, "$.trust_boundaries", "SECMODEL003_TRUST_BOUNDARY")
    # Flatten each covered contract-id element in boundary then contract authored order.
    covered = [contract for item in model.boundaries for contract in item.contracts]
    # Require each architecture contract to be assigned to no more than one trust boundary.
    _unique(covered, "$.trust_boundaries[*].contracts", "SECMODEL002_CONTRACT_JOIN")
    # Build an unordered set whose each element is one canonical architecture contract id.
    expected = {item.contract_id for item in architecture.contracts}
    # Covered and expected sets must match exactly for a complete local trust view.
    if set(covered) != expected:
        # Reject with independently sorted missing and unknown contract-id elements.
        _fail(
            "SECMODEL002_CONTRACT_JOIN",
            "$.trust_boundaries[*].contracts",
            f"missing={sorted(expected - set(covered))}, unknown={sorted(set(covered) - expected)}",
        )
    # Validate evidence for every boundary record in authored model order.
    for boundary in model.boundaries:
        # Resolve and require the boundary's confined local evidence file.
        _local_path(root, boundary.evidence, "SECMODEL003_TRUST_BOUNDARY")
    # Return the unique boundary identities as an unordered membership set.
    return set(boundary_ids)


def _validate_data(
    model: SecurityModel,
    boundary_ids: set[str],
    root: Path,
    *,
    sensitive: bool,
) -> None:
    """Validate classification, exposure, and capability coherence.

    @param model parsed local security model
    @param boundary_ids unordered set whose each element is a valid entry-boundary identity
    @param sensitive true when sensitive_data is enabled; false when it is explicitly disabled
    @param root governed repository root
    @throws SecurityModelError on stale sources, exposure, or capability mismatch
    @par Effects Resolves and inspects each declared evidence file without modifying it.
    """
    # Require every data-class identity exactly once in authored model order.
    _unique(
        [item.data_id for item in model.data_classes],
        "$.data_classes",
        "SECMODEL004_CLASSIFICATION",
    )
    # Preserve each sensitive data-class record in authored model order.
    sensitive_records = [
        item for item in model.data_classes if item.classification in SENSITIVE_CLASSES
    ]
    # Enabled sensitive handling requires actual sensitive records and no absence rationale.
    if sensitive and (model.sensitive_data_absence is not None or not sensitive_records):
        # Reject the inconsistent capability/model state at the absence field.
        _fail(
            "SECMODEL004_CLASSIFICATION",
            "$.sensitive_data_absence",
            "sensitive_data=true requires null absence and a sensitive data class",
        )
    # Disabled sensitive handling requires a rationale and forbids every sensitive record.
    if not sensitive and (
        model.sensitive_data_absence is None or sensitive_records
    ):
        # Reject the inconsistent capability/model state at the absence field.
        _fail(
            "SECMODEL004_CLASSIFICATION",
            "$.sensitive_data_absence",
            "sensitive_data=false requires an absence rationale and forbids sensitive classes",
        )
    # Validate sources and evidence for every data class in authored model order.
    for data in model.data_classes:
        # Build an unordered set whose each element is a declared source absent from boundaries.
        unknown_sources = set(data.sources) - boundary_ids
        # Any unknown source breaks the trust-boundary-to-data-class join.
        if unknown_sources:
            # Reject with sorted unknown boundary-id elements at the data-class identity.
            _fail(
                "SECMODEL005_EXPOSURE",
                data.data_id,
                f"unknown source boundaries {sorted(unknown_sources)}",
            )
        # Resolve and require the data class's confined local evidence file.
        _local_path(root, data.evidence, "SECMODEL005_EXPOSURE")


def validate(
    model: SecurityModel,
    architecture: ArchitectureModel,
    root: Path,
    *,
    sensitive: bool,
) -> None:
    """Cross-check one security model against local canonical facts.

    @param model parsed local security model
    @param architecture canonical architecture model
    @param sensitive true when sensitive_data is enabled; false when it is explicitly disabled
    @param root governed repository root
    @throws SecurityModelError on the first deterministic mismatch
    @par Effects Resolves and inspects each declared evidence file without modifying it.
    """
    # Validate contract coverage and retain each known boundary id as an unordered set.
    boundary_ids = _validate_boundaries(model, architecture, root)
    # Validate data classification, exposure joins, evidence, and capability coherence.
    _validate_data(model, boundary_ids, root, sensitive=sensitive)


class SecurityModelCheck(Check):
    """Check local trust assumptions, classification, and exposure controls."""

    ## Mechanism token for repository-local security rules.
    name = "security_model"
    ## Ordered rule-id elements for trust/completeness then classification/exposure.
    rules = ("SEC-001", "SEC-002")

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Validate canonical model paths from the nearest declaration.

        @param paths path elements in caller order, ignored because declaration records are
            authoritative
        @return an empty sequence or one earliest deterministic finding element
        @par Effects Resolves and reads local model and evidence files without modifying them.
        """
        # Consume the ignored argument explicitly so the declaration remains the sole owner.
        _ = paths
        # Resolve the optional local security-model artifact through the declaration.
        model_path = self.declaration.security_model_path()
        # Resolve the prerequisite local architecture-model artifact.
        architecture_path = self.declaration.architecture_path()
        # Resolve the governed repository boundary used for evidence confinement.
        root = self.declaration.root
        # Legacy direct-check fallbacks lacking any prerequisite have no model join to validate.
        if model_path is None or architecture_path is None or root is None:
            # Skip security joins when either canonical model or the repository root is absent.
            return []
        # Parse both canonical models and validate their local joins through typed errors.
        try:
            # Hold the valid typed security model.
            model = parse(model_path)
            # Hold the valid typed architecture prerequisite.
            architecture = parse_architecture(architecture_path)
            # Validate contract coverage, classifications, evidence, and sensitive capability state.
            validate(
                model,
                architecture,
                root,
                sensitive=self.declaration.has(Capability.SENSITIVE_DATA),
            )
        # Translate a failed architecture prerequisite into the security-completeness rule.
        except ArchitectureError as problem:
            # Return the sole prerequisite finding at the architecture artifact.
            return [Finding(
                rule_id="SEC-001",
                path=architecture_path,
                line=1,
                message=f"architecture prerequisite failed at {problem.where}: {problem.detail}",
                remediation="Repair architecture.json before security contract joins.",
                diagnostic_id="SECMODEL002_CONTRACT_JOIN",
            )]
        # Translate the earliest typed security-model refusal into the ordinary finding contract.
        except SecurityModelError as problem:
            # Select the stable diagnostic family prefix preceding its subtype separator.
            prefix = problem.diagnostic_id.split("_", 1)[0]
            # Map schema/trust families to SEC-001 and classification/exposure to SEC-002.
            rule = {
                "SECMODEL001": "SEC-001",
                "SECMODEL002": "SEC-001",
                "SECMODEL003": "SEC-001",
                "SECMODEL004": "SEC-002",
                "SECMODEL005": "SEC-002",
            }[prefix]
            # Return the sole localized security-model finding.
            return [Finding(
                rule_id=rule,
                path=model_path,
                line=1,
                message=f"{problem.where}: {problem.detail}",
                remediation=(
                    "Repair the canonical local security model and its confined evidence; "
                    "do not assign trust or exposure control to another repository."
                ),
                diagnostic_id=problem.diagnostic_id,
            )]
        # Complete, joined, capability-consistent local security facts contribute no findings.
        return []


# Run the standalone security-model check only at this module's process boundary.
if __name__ == "__main__":
    # Import the runner only for script execution, avoiding an ordinary module dependency cycle.
    from . import main

    # Convert the check runner's stable result into the process exit status.
    raise SystemExit(main(SecurityModelCheck()))
