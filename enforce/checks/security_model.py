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

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

## Stable lower-snake identities shared by model records and local sink names.
IDENTIFIER: Final = re.compile(r"^[a-z][a-z0-9_]*$")
## Roles allowed to receive data inside one governed repository.
OWNER_ROLES: Final = frozenset({"domain", "application", "ports", "adapters", "shell"})
## Trust attributed to an inbound value before this repository validates it.
TRUST_LEVELS: Final = frozenset({"untrusted", "constrained", "trusted_local"})
## Closed classification vocabulary ordered from non-sensitive to sensitive.
CLASSIFICATIONS: Final = frozenset({
    "public", "internal", "confidential", "secret", "personal",
})
## Classifications that activate the sensitive-data capability.
SENSITIVE_CLASSES: Final = frozenset({"confidential", "secret", "personal"})


class SecurityModelError(ValueError):
    """One stable security-model diagnostic."""

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
    """Raise one security-model diagnostic.

    @param diagnostic_id stable mechanism diagnostic
    @param where JSON path or repository location
    @param detail explanation of the violated predicate
    @return never; this helper always raises
    @throws SecurityModelError unconditionally
    """
    raise SecurityModelError(diagnostic_id, where, detail)


def _object(value: object, where: str) -> Mapping[str, object]:
    """Require a JSON object.

    @param value untrusted decoded value
    @param where JSON path
    @return typed mapping
    """
    if not isinstance(value, dict):
        _fail("SECMODEL001_SCHEMA", where, "expected an object")
    return value


def _exact(record: Mapping[str, object], fields: set[str], where: str) -> None:
    """Reject missing and ignored fields.

    @param record decoded object
    @param fields exact accepted field set
    @param where JSON path
    @throws SecurityModelError when the field set differs
    """
    missing = fields - set(record)
    unknown = set(record) - fields
    if missing or unknown:
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
    if not isinstance(value, str) or not value.strip():
        _fail("SECMODEL001_SCHEMA", where, "expected non-empty text")
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
        _fail("SECMODEL001_SCHEMA", where, "expected lower_snake identifier")
    return text


def _strings(value: object, where: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    """Require a unique string array.

    @param value untrusted decoded value
    @param where JSON path
    @param allow_empty whether an explicit empty array is meaningful
    @return values in source order
    """
    if not isinstance(value, list) or (not value and not allow_empty):
        _fail("SECMODEL001_SCHEMA", where, "expected a string array")
    values = tuple(_text(item, f"{where}[{index}]") for index, item in enumerate(value))
    if len(values) != len(set(values)):
        _fail("SECMODEL001_SCHEMA", where, "duplicate values are not allowed")
    return values


def _records(
    value: object, where: str, *, allow_empty: bool = False,
) -> list[Mapping[str, object]]:
    """Require an array of objects.

    @param value untrusted decoded value
    @param where JSON path
    @param allow_empty whether an explicit empty array is meaningful
    @return decoded records
    """
    if not isinstance(value, list) or (not value and not allow_empty):
        _fail("SECMODEL001_SCHEMA", where, "expected a record array")
    return [_object(item, f"{where}[{index}]") for index, item in enumerate(value)]


@dataclass(frozen=True, slots=True)
class TrustBoundary:
    """One local entry boundary and the trust it establishes."""

    ## Stable local boundary identity.
    boundary_id: str
    ## Architecture contracts entering through this boundary.
    contracts: tuple[str, ...]
    ## Trust attributed before validation.
    inbound_trust: str
    ## Preconditions on which local behavior relies.
    assumptions: tuple[str, ...]
    ## Checks performed before stronger trust is granted.
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
    ## Trust-boundary ids through which the data enters.
    sources: tuple[str, ...]
    ## Local roles allowed to receive the data.
    allowed_roles: tuple[str, ...]
    ## Named output or persistence sinks allowed to receive it.
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

    ## Trust record covering every canonical architecture contract.
    boundaries: tuple[TrustBoundary, ...]
    ## Data classes intentionally handled by the repository.
    data_classes: tuple[DataClass, ...]
    ## Rationale when no sensitive class is intentionally handled.
    sensitive_data_absence: str | None


def _trust_boundary(record: Mapping[str, object], where: str) -> TrustBoundary:
    """Parse one trust-boundary record.

    @param record decoded boundary record
    @param where JSON path
    @return typed boundary
    """
    fields = {
        "id", "contracts", "inbound_trust", "assumptions", "validations",
        "trust_ceases_at", "evidence",
    }
    _exact(record, fields, where)
    inbound = _text(record["inbound_trust"], f"{where}.inbound_trust")
    if inbound not in TRUST_LEVELS:
        _fail(
            "SECMODEL003_TRUST_BOUNDARY",
            f"{where}.inbound_trust",
            f"expected one of {sorted(TRUST_LEVELS)}",
        )
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

    @param record decoded data record
    @param where JSON path
    @return typed data class
    """
    fields = {
        "id", "classification", "sources", "allowed_roles", "allowed_sinks",
        "retention", "redaction", "evidence",
    }
    _exact(record, fields, where)
    classification = _text(record["classification"], f"{where}.classification")
    if classification not in CLASSIFICATIONS:
        _fail(
            "SECMODEL004_CLASSIFICATION",
            f"{where}.classification",
            f"expected one of {sorted(CLASSIFICATIONS)}",
        )
    roles = _strings(record["allowed_roles"], f"{where}.allowed_roles")
    unknown_roles = set(roles) - OWNER_ROLES
    if unknown_roles:
        _fail(
            "SECMODEL005_EXPOSURE",
            f"{where}.allowed_roles",
            f"unknown local roles {sorted(unknown_roles)}",
        )
    sinks = _strings(record["allowed_sinks"], f"{where}.allowed_sinks", allow_empty=True)
    if any(IDENTIFIER.fullmatch(item) is None for item in sinks):
        _fail("SECMODEL005_EXPOSURE", f"{where}.allowed_sinks", "invalid sink id")
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
    """
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as problem:
        _fail("SECMODEL001_SCHEMA", str(path), str(problem))
    root = _object(raw, "$")
    _exact(
        root,
        {"schema_version", "trust_boundaries", "data_classes", "sensitive_data_absence"},
        "$",
    )
    if root["schema_version"] != 1:
        _fail("SECMODEL001_SCHEMA", "$.schema_version", "expected 1")
    boundaries = tuple(
        _trust_boundary(item, f"$.trust_boundaries[{index}]")
        for index, item in enumerate(_records(root["trust_boundaries"], "$.trust_boundaries"))
    )
    data_classes = tuple(
        _data_class(item, f"$.data_classes[{index}]")
        for index, item in enumerate(
            _records(root["data_classes"], "$.data_classes", allow_empty=True),
        )
    )
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
    """Require identities to occur once.

    @param values record identities in source order
    @param where JSON collection path
    @param diagnostic_id semantic diagnostic
    @throws SecurityModelError when an identity repeats
    """
    if len(values) != len(set(values)):
        _fail(diagnostic_id, where, "duplicate identities are not allowed")


def _validate_boundaries(
    model: SecurityModel, architecture: ArchitectureModel, root: Path,
) -> set[str]:
    """Join trust boundaries to every local contract.

    @param model parsed local security model
    @param architecture canonical architecture model
    @param root governed repository root
    @return known trust-boundary ids
    @throws SecurityModelError on incomplete joins or stale evidence
    """
    boundary_ids = [item.boundary_id for item in model.boundaries]
    _unique(boundary_ids, "$.trust_boundaries", "SECMODEL003_TRUST_BOUNDARY")
    covered = [contract for item in model.boundaries for contract in item.contracts]
    _unique(covered, "$.trust_boundaries[*].contracts", "SECMODEL002_CONTRACT_JOIN")
    expected = {item.contract_id for item in architecture.contracts}
    if set(covered) != expected:
        _fail(
            "SECMODEL002_CONTRACT_JOIN",
            "$.trust_boundaries[*].contracts",
            f"missing={sorted(expected - set(covered))}, unknown={sorted(set(covered) - expected)}",
        )
    for boundary in model.boundaries:
        _local_path(root, boundary.evidence, "SECMODEL003_TRUST_BOUNDARY")
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
    @param boundary_ids valid entry-boundary identities
    @param sensitive whether the project capability is enabled
    @param root governed repository root
    @throws SecurityModelError on stale sources, exposure, or capability mismatch
    """
    _unique(
        [item.data_id for item in model.data_classes],
        "$.data_classes",
        "SECMODEL004_CLASSIFICATION",
    )
    sensitive_records = [
        item for item in model.data_classes if item.classification in SENSITIVE_CLASSES
    ]
    if sensitive and (model.sensitive_data_absence is not None or not sensitive_records):
        _fail(
            "SECMODEL004_CLASSIFICATION",
            "$.sensitive_data_absence",
            "sensitive_data=true requires null absence and a sensitive data class",
        )
    if not sensitive and (
        model.sensitive_data_absence is None or sensitive_records
    ):
        _fail(
            "SECMODEL004_CLASSIFICATION",
            "$.sensitive_data_absence",
            "sensitive_data=false requires an absence rationale and forbids sensitive classes",
        )
    for data in model.data_classes:
        unknown_sources = set(data.sources) - boundary_ids
        if unknown_sources:
            _fail(
                "SECMODEL005_EXPOSURE",
                data.data_id,
                f"unknown source boundaries {sorted(unknown_sources)}",
            )
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
    @param sensitive whether sensitive_data is enabled
    @param root governed repository root
    @throws SecurityModelError on the first deterministic mismatch
    """
    boundary_ids = _validate_boundaries(model, architecture, root)
    _validate_data(model, boundary_ids, root, sensitive=sensitive)


class SecurityModelCheck(Check):
    """Check local trust assumptions, classification, and exposure controls."""

    ## Mechanism token for repository-local security rules.
    name = "security_model"
    ## Independently diagnosable security obligations.
    rules = ("SEC-001", "SEC-002")

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Validate canonical model paths from the nearest declaration.

        @param paths ignored caller selection; declaration-bound records are authoritative
        @return zero or one earliest deterministic finding
        """
        _ = paths
        model_path = self.declaration.security_model_path()
        architecture_path = self.declaration.architecture_path()
        root = self.declaration.root
        if model_path is None or architecture_path is None or root is None:
            return []
        try:
            model = parse(model_path)
            architecture = parse_architecture(architecture_path)
            validate(
                model,
                architecture,
                root,
                sensitive=self.declaration.has(Capability.SENSITIVE_DATA),
            )
        except ArchitectureError as problem:
            return [Finding(
                rule_id="SEC-001",
                path=architecture_path,
                line=1,
                message=f"architecture prerequisite failed at {problem.where}: {problem.detail}",
                remediation="Repair architecture.json before security contract joins.",
                diagnostic_id="SECMODEL002_CONTRACT_JOIN",
            )]
        except SecurityModelError as problem:
            prefix = problem.diagnostic_id.split("_", 1)[0]
            rule = {
                "SECMODEL001": "SEC-001",
                "SECMODEL002": "SEC-001",
                "SECMODEL003": "SEC-001",
                "SECMODEL004": "SEC-002",
                "SECMODEL005": "SEC-002",
            }[prefix]
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
        return []


if __name__ == "__main__":
    from . import main

    raise SystemExit(main(SecurityModelCheck()))
