"""Validate content-bound semantic and adversarial review evidence.

The review artifact binds a judgment to one base commit and a deterministic
digest of every repository-owned input and artifact except explicit environment
state, vendored discipline, native host mirrors, build output, and the review's
self-reference. UTF-8 CRLF checkout projections are canonicalized to LF so the
same reviewed Git content has one identity on Windows and Linux; binary bytes
remain exact. The checker can decide freshness, scope, question coverage,
declared role separation, and finding closure. It cannot
decide whether the reviewer was genuinely independent or insightful; that
residual remains explicit in both the doctrine evidence and the artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed Git provenance probe
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Final, Never

from . import Check, Finding

# Import annotation-only contracts without introducing runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .project import Declaration

## Stable lower-snake record and reviewer identities.
IDENTIFIER: Final = re.compile(r"^[a-z][a-z0-9_]*$")
## Git SHA-1 or SHA-256 object identity.
COMMIT_ID: Final = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
## Content digest spelling used by the scope snapshot.
DIGEST: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
## Review-scope category elements in canonical digest-accounting order.
SCOPE_CATEGORIES: Final = (
    "project_declaration",
    "canonical_models",
    "production_python",
    "test_python",
    "authored_documentation",
    "tool_configuration",
    "repository_assets",
)
## Semantic-question category elements in required adversarial-review order.
QUESTION_CATEGORIES: Final = (
    "architecture",
    "contracts",
    "failure_containment",
    "lifecycle_budgets",
    "trust_data",
    "observability",
    "supply_chain",
    "test_oracles",
    "documentation_truth",
    "documentation_allocation",
    "documentation_obsolescence",
    "domain_naming",
)
## Documentation-question elements in canonical order whose conclusions remain semantic.
DOCUMENTATION_QUESTION_CATEGORIES: Final = QUESTION_CATEGORIES[-4:]
## Unordered directory-name set whose each element denotes excluded replaceable state.
EXCLUDED_DIRECTORIES: Final = frozenset({
    ".git",
    ".agent",
    ".agents",
    ".claude",
    ".hypothesis",
    ".import_linter_cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
})
## Directory-suffix elements in deterministic matching order for replaceable metadata.
EXCLUDED_DIRECTORY_SUFFIXES: Final = (".egg-info",)
## Unordered file-name set whose each element denotes an excluded runtime projection.
EXCLUDED_FILES: Final = frozenset({".coverage", "coverage.xml"})
## Unordered suffix set whose each element denotes an excluded interpreter or database product.
EXCLUDED_SUFFIXES: Final = frozenset({".db", ".pyc", ".pyo", ".sqlite", ".sqlite3"})
## Unordered severity-name set whose each element classifies an objection consequence.
SEVERITIES: Final = frozenset({"low", "medium", "high", "critical"})
## Unordered disposition-name set whose each element classifies objection closure.
DISPOSITIONS: Final = frozenset({"resolved", "accepted_risk", "open"})
## Unordered independence-name set whose each element states a reviewer-separation basis.
INDEPENDENCE: Final = frozenset({"independent", "role_separated"})


class ReviewError(ValueError):
    """One stable adversarial-review diagnostic."""

    ## Stable diagnostic namespace for rejected adversarial-review propositions.
    code = "discipline.adversarial_review.invalid"

    def __init__(self, diagnostic_id: str, where: str, detail: str) -> None:
        """Build one actionable review failure.

        @param diagnostic_id stable mechanism diagnostic
        @param where JSON path or repository location
        @param detail explanation of the violated predicate
        """
        # Initialize the standard message from the stable id, location, and detail.
        super().__init__(f"{diagnostic_id} {where}: {detail}")
        # Retain the mechanism diagnostic for deterministic rule selection.
        self.diagnostic_id = diagnostic_id
        # Retain the exact model or repository location that failed validation.
        self.where = where
        # Retain the actionable schema or semantic explanation.
        self.detail = detail


def _fail(diagnostic_id: str, where: str, detail: str) -> Never:
    """Raise one review diagnostic.

    @param diagnostic_id stable mechanism diagnostic
    @param where JSON path or repository location
    @param detail explanation of the violated predicate
    @return never; this helper always raises
    @throws ReviewError unconditionally
    """
    # Translate the localized failure into the sole typed review-error channel.
    raise ReviewError(diagnostic_id, where, detail)


def _object(value: object, where: str) -> Mapping[str, object]:
    """Require a JSON object.

    @param value untrusted decoded value
    @param where JSON path
    @return mapping whose each key is a field name and each value is decoded data;
        source order is preserved by the decoder
    """
    # Only a JSON object can supply named review fields.
    if not isinstance(value, dict):
        # Reject scalar and array impostors without coercion.
        _fail("REVIEW001_SCHEMA", where, "expected an object")
    # Return the decoded key/value mapping with source order intact.
    return value


def _exact(record: Mapping[str, object], fields: set[str], where: str) -> None:
    """Reject missing and ignored fields.

    @param record mapping whose each key names a field and each value is decoded data;
        mapping iteration order is deliberately unused
    @param fields unordered field-name set whose each element is required and accepted
    @param where JSON path
    @throws ReviewError when the field set differs
    """
    # Build an unordered set whose each element is a required field absent from the record.
    missing = fields - set(record)
    # Build an unordered set whose each element is an unrecognized record field.
    unknown = set(record) - fields
    # Missing and unknown fields both make the closed schema unsafe to interpret.
    if missing or unknown:
        # Reject the exact object before any partial field interpretation.
        _fail(
            "REVIEW001_SCHEMA",
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
        _fail("REVIEW001_SCHEMA", where, "expected non-empty text")
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
    """Require one lower-snake identity.

    @param value untrusted decoded value
    @param where JSON path
    @return validated identity
    """
    # Parse and normalize the raw value as non-empty text first.
    text = _text(value, where)
    # Stable review identities use one complete lower-snake lexical shape.
    if IDENTIFIER.fullmatch(text) is None:
        # Reject invalid spelling at the exact field path.
        _fail("REVIEW001_SCHEMA", where, "expected lower_snake identifier")
    # Return the validated stable identity.
    return text


def _strings(value: object, where: str) -> tuple[str, ...]:
    """Require a non-empty unique string array.

    @param value untrusted decoded value
    @param where JSON path
    @return unique string elements in source order
    """
    # Require a non-empty array of authored string elements.
    if not isinstance(value, list) or not value:
        # Reject absent, scalar, and empty values at the exact path.
        _fail("REVIEW001_SCHEMA", where, "expected a non-empty string array")
    # Parse each indexed string element while preserving authored source order.
    values = tuple(_text(item, f"{where}[{index}]") for index, item in enumerate(value))
    # Duplicate values cannot carry distinct review meaning.
    if len(values) != len(set(values)):
        # Reject the complete array rather than silently deduplicating it.
        _fail("REVIEW001_SCHEMA", where, "duplicate values are not allowed")
    # Return the validated unique sequence in authored order.
    return values


def _records(value: object, where: str) -> list[Mapping[str, object]]:
    """Require a non-empty record array.

    @param value untrusted decoded value
    @param where JSON path
    @return decoded mapping-record elements in source order
    """
    # Require a non-empty array of authored record elements.
    if not isinstance(value, list) or not value:
        # Reject absent, scalar, and empty values at the exact path.
        _fail("REVIEW001_SCHEMA", where, "expected a non-empty record array")
    # Parse each indexed object element while preserving authored source order.
    return [_object(item, f"{where}[{index}]") for index, item in enumerate(value)]


@dataclass(frozen=True, slots=True)
class Scope:
    """Deterministic content snapshot reviewed by the artifact."""

    ## Hash algorithm, fixed to sha256 in schema version 1.
    algorithm: str
    ## Digest over ordered relative-path and content-digest pair elements.
    digest: str
    ## Number of files included in the digest.
    file_count: int
    ## Scope-category elements in canonical digest-accounting order.
    categories: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Reviewer:
    """Declared adversarial reviewer identity and separation basis."""

    ## Stable reviewer identity distinct from author identities.
    identity: str
    ## Exact adversarial reviewer role.
    role: str
    ## Independent person or deliberately role-separated pass.
    independence: str
    ## Auditable statement of how separation was obtained and what remains.
    basis: str


@dataclass(frozen=True, slots=True)
class Question:
    """One required semantic attack angle and its conclusion."""

    ## Required category identity.
    question_id: str
    ## Concrete hostile question asked of the reviewed scope.
    challenge: str
    ## Reviewer's bounded conclusion.
    conclusion: str
    ## Repository-local evidence-path elements in authored examination order.
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Objection:
    """One concrete objection and its disposition."""

    ## Stable objection identity.
    objection_id: str
    ## Required semantic category.
    category: str
    ## Consequence severity.
    severity: str
    ## Concrete defect, risk, or unsupported claim.
    statement: str
    ## Resolved, accepted risk, or still open.
    disposition: str
    ## Repair or risk-acceptance rationale, absent only while open.
    resolution: str | None
    ## Confined closure evidence, absent only while open.
    evidence: str | None
    ## Local role or maintainer identity owning follow-up.
    owner: str
    ## Event that forces this objection to be reviewed again.
    review_trigger: str


@dataclass(frozen=True, slots=True)
class Review:
    """Complete content-bound adversarial acceptance record."""

    ## Stable review identity.
    review_id: str
    ## Repository commit from which the reviewed change began.
    reviewed_commit: str
    ## Exact governed content snapshot.
    scope: Scope
    ## Author-identity elements in authored declaration order.
    authors: tuple[str, ...]
    ## Declared adversarial reviewer.
    reviewer: Reviewer
    ## Question-record elements in canonical required challenge order.
    questions: tuple[Question, ...]
    ## Objection-record elements in authored order, with at least one required.
    objections: tuple[Objection, ...]
    ## Accepted or rejected semantic verdict.
    verdict: str
    ## Bounded final conclusion.
    conclusion: str
    ## What can remain wrong after acceptance.
    residual: str


def _scope(value: object, where: str) -> Scope:
    """Parse one scope snapshot.

    @param value decoded scope object whose field order is deliberately unused
    @param where JSON path
    @return typed scope
    """
    # Require the decoded scope to be an object with a closed schema.
    record = _object(value, where)
    _exact(record, {"algorithm", "digest", "file_count", "categories"}, where)
    # Select the raw file count without accepting boolean-as-integer coercion.
    count = record["file_count"]
    # A non-vacuous review scope contains a positive integer number of files.
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        # Reject zero, negative, boolean, and non-integer counts.
        _fail("REVIEW001_SCHEMA", f"{where}.file_count", "expected a positive integer")
    # Parse the claimed aggregate content digest.
    digest = _text(record["digest"], f"{where}.digest")
    # Scope identity must use the exact lowercase sha256 spelling.
    if DIGEST.fullmatch(digest) is None:
        # Reject malformed or alternate digest forms at the exact field path.
        _fail("REVIEW001_SCHEMA", f"{where}.digest", "expected sha256:<64 lowercase hex>")
    # Materialize the validated digest declaration and ordered category elements.
    return Scope(
        algorithm=_text(record["algorithm"], f"{where}.algorithm"),
        digest=digest,
        file_count=count,
        categories=_strings(record["categories"], f"{where}.categories"),
    )


def _reviewer(value: object, where: str) -> Reviewer:
    """Parse reviewer identity and separation.

    @param value decoded reviewer object whose field order is deliberately unused
    @param where JSON path
    @return typed reviewer
    """
    # Require the decoded reviewer to be an object with a closed schema.
    record = _object(value, where)
    _exact(record, {"identity", "role", "independence", "basis"}, where)
    # Parse the declared reviewer-separation mode.
    independence = _text(record["independence"], f"{where}.independence")
    # Separation must use one explicitly modeled basis.
    if independence not in INDEPENDENCE:
        # Sort accepted basis-name elements for a deterministic diagnostic.
        _fail(
            "REVIEW005_INDEPENDENCE",
            f"{where}.independence",
            f"expected one of {sorted(INDEPENDENCE)}",
        )
    # Materialize the validated reviewer identity, role, and separation claim.
    return Reviewer(
        identity=_identifier(record["identity"], f"{where}.identity"),
        role=_identifier(record["role"], f"{where}.role"),
        independence=independence,
        basis=_text(record["basis"], f"{where}.basis"),
    )


def _question(record: Mapping[str, object], where: str) -> Question:
    """Parse one semantic challenge record.

    @param record mapping whose each key names a question field and each value is decoded
        data; mapping iteration order is deliberately unused
    @param where JSON path
    @return typed question
    """
    # Close the question schema before interpreting its challenge and evidence.
    _exact(record, {"id", "challenge", "conclusion", "evidence"}, where)
    # Materialize the validated question with evidence-path elements in authored order.
    return Question(
        question_id=_identifier(record["id"], f"{where}.id"),
        challenge=_text(record["challenge"], f"{where}.challenge"),
        conclusion=_text(record["conclusion"], f"{where}.conclusion"),
        evidence=_strings(record["evidence"], f"{where}.evidence"),
    )


def _objection(record: Mapping[str, object], where: str) -> Objection:
    """Parse one objection and closure record.

    @param record mapping whose each key names an objection field and each value is decoded
        data; mapping iteration order is deliberately unused
    @param where JSON path
    @return typed objection
    """
    # Define the unordered field-name set whose each element is required and accepted.
    fields = {
        "id",
        "category",
        "severity",
        "statement",
        "disposition",
        "resolution",
        "evidence",
        "owner",
        "review_trigger",
    }
    # Close the objection schema before interpreting dependent closure fields.
    _exact(record, fields, where)
    # Parse the required semantic attack category.
    category = _identifier(record["category"], f"{where}.category")
    # Parse the claimed consequence severity.
    severity = _text(record["severity"], f"{where}.severity")
    # Parse the claimed closure disposition.
    disposition = _text(record["disposition"], f"{where}.disposition")
    # Every objection must remain attached to one required question category.
    if category not in QUESTION_CATEGORIES:
        # Reject invented review categories at the exact field path.
        _fail("REVIEW004_QUESTIONS", f"{where}.category", "unknown review category")
    # Severity and disposition must both come from their closed vocabularies.
    if severity not in SEVERITIES or disposition not in DISPOSITIONS:
        # Reject unknown closure vocabulary before interpreting optional evidence.
        _fail(
            "REVIEW006_FINDING_CLOSURE",
            where,
            "unknown severity or disposition",
        )
    # Materialize the validated objection and its possibly open closure state.
    return Objection(
        objection_id=_identifier(record["id"], f"{where}.id"),
        category=category,
        severity=severity,
        statement=_text(record["statement"], f"{where}.statement"),
        disposition=disposition,
        resolution=_optional_text(record["resolution"], f"{where}.resolution"),
        evidence=_optional_text(record["evidence"], f"{where}.evidence"),
        owner=_text(record["owner"], f"{where}.owner"),
        review_trigger=_text(record["review_trigger"], f"{where}.review_trigger"),
    )


def parse(path: Path) -> Review:
    """Parse one exact structured review artifact.

    @param path local review JSON path
    @return typed review
    @throws ReviewError when syntax or fields are invalid

    @par Effects
    Reads the review file at ``path`` once before validating the decoded snapshot.
    """
    # Read and decode one immutable adversarial-review snapshot.
    try:
        # Decode the file snapshot into an untrusted JSON value.
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    # Translate filesystem, encoding, and JSON failures into the review error channel.
    except (OSError, UnicodeError, json.JSONDecodeError) as problem:
        # Preserve the path and parser detail in a stable schema diagnostic.
        _fail("REVIEW001_SCHEMA", str(path), str(problem))
    # Require the decoded root to be a JSON object.
    root = _object(raw, "$")
    # Define the unordered root-field set whose each element is required and accepted.
    fields = {
        "schema_version",
        "review_id",
        "reviewed_commit",
        "scope",
        "authors",
        "reviewer",
        "questions",
        "objections",
        "verdict",
        "conclusion",
        "residual",
    }
    # Close the root schema before interpreting any nested review record.
    _exact(root, fields, "$")
    # Reject incompatible schema versions before reading their records.
    if root["schema_version"] != 1:
        # State the sole supported schema version at the canonical location.
        _fail("REVIEW001_SCHEMA", "$.schema_version", "expected 1")
    # Materialize the complete validated review with authored sequence order preserved.
    return Review(
        review_id=_identifier(root["review_id"], "$.review_id"),
        reviewed_commit=_text(root["reviewed_commit"], "$.reviewed_commit"),
        scope=_scope(root["scope"], "$.scope"),
        authors=tuple(
            _identifier(item, f"$.authors[{index}]")
            for index, item in enumerate(_strings(root["authors"], "$.authors"))
        ),
        reviewer=_reviewer(root["reviewer"], "$.reviewer"),
        questions=tuple(
            _question(item, f"$.questions[{index}]")
            for index, item in enumerate(_records(root["questions"], "$.questions"))
        ),
        objections=tuple(
            _objection(item, f"$.objections[{index}]")
            for index, item in enumerate(_records(root["objections"], "$.objections"))
        ),
        verdict=_text(root["verdict"], "$.verdict"),
        conclusion=_text(root["conclusion"], "$.conclusion"),
        residual=_text(root["residual"], "$.residual"),
    )


def _local_path(root: Path, spelling: str, diagnostic_id: str) -> Path:
    """Resolve one confined evidence path.

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


def _relative(root: Path, path: Path) -> str:
    """Return one confined repository-relative POSIX path.

    @param root governed repository root
    @param path candidate review input
    @return stable relative spelling
    @throws ReviewError when a declaration path escapes or is absent
    """
    # Resolve symlinks and normalization before deriving review identity.
    resolved = path.resolve()
    # Prove the resolved input remains beneath the governed repository root.
    try:
        # Derive the repository-relative path from the already-resolved candidate.
        relative = resolved.relative_to(root.resolve())
    # Translate a confinement escape into the stale-scope diagnostic.
    except ValueError:
        # Reject the escaped candidate using its supplied spelling.
        _fail("REVIEW002_SCOPE_STALE", str(path), "review input leaves repository")
    # A review digest may include only existing regular file content.
    if not resolved.is_file():
        # Report the stable relative spelling of the absent input.
        _fail("REVIEW002_SCOPE_STALE", relative.as_posix(), "review input is absent")
    # Return one platform-neutral relative spelling for sorting and hashing.
    return relative.as_posix()


def scope_paths(declaration: Declaration) -> tuple[Path, ...]:
    """The exact files whose content an adversarial acceptance covers.

    @param declaration bounded project declaration
    @return file-path elements in stable repository-relative order
    @throws ReviewError when a required input is absent or outside the repository

    @par Effects
    Walks the declared repository and reads filesystem metadata to enumerate exact inputs.
    """
    # Select the validated repository root that bounds every review input.
    root = declaration.root
    # A review cannot be scoped without both a root and its project declaration.
    if root is None or declaration.source is None:
        # Reject the incomplete declaration before walking any ambient directory.
        _fail("REVIEW002_SCOPE_STALE", "$", "declared repository root is unavailable")
    # Accumulate an unordered set whose each element is one exact review-input path.
    candidates: set[Path] = set()
    # Resolve the self-referential review artifact so it can be excluded from its digest.
    review_path = declaration.adversarial_review_path()
    # Preserve explicit absence or the normalized artifact identity.
    excluded_review = None if review_path is None else review_path.resolve()
    # Walk each repository directory in a deterministically pruned order.
    for directory, names, files in os.walk(root):
        # Retain only semantically owned child-directory names in lexical order.
        names[:] = sorted(
            name
            for name in names
            if name not in EXCLUDED_DIRECTORIES and not name.endswith(EXCLUDED_DIRECTORY_SUFFIXES)
        )
        # Consider each file-name element in lexical order within its directory.
        for name in sorted(files):
            # Resolve the candidate so aliases collapse in the path set.
            path = (Path(directory) / name).resolve()
            # Exclude self-reference and declared replaceable artifacts.
            if (
                path == excluded_review
                or name in EXCLUDED_FILES
                or path.suffix in EXCLUDED_SUFFIXES
            ):
                # Advance without adding an environment or generated-state artifact.
                continue
            # Add the repository-owned file to the unordered candidate identity set.
            candidates.add(path)
    # Explicitly retain the declaration even if walking filters change later.
    candidates.add(declaration.source.resolve())
    # Collect canonical model-path elements in their stable declaration order.
    canonical = (
        declaration.architecture_path(),
        declaration.contract_conformance_path(),
        declaration.operational_model_path(),
        declaration.security_model_path(),
        declaration.documentation_model_path(),
    )
    # Require and add each canonical-model element in declaration order.
    for canonical_path in canonical:
        # Every reviewable v5 repository must declare the complete model set.
        if canonical_path is None:
            # Reject incomplete scope authority rather than silently omitting a model.
            _fail("REVIEW002_SCOPE_STALE", "$", "canonical model path is undeclared")
        # Add the resolved canonical model identity to the review-input set.
        candidates.add(canonical_path.resolve())
    # Expand each declared production-root element in declaration precedence order.
    for source_root in declaration.source_paths():
        # An absent production root makes the declared scope stale.
        if not source_root.is_dir():
            # Reject before treating an empty walk as successful review coverage.
            _fail(
                "REVIEW002_SCOPE_STALE",
                str(source_root),
                "declared production source root is absent",
            )
        # Add every Python source element; set identity removes duplicates across nested roots.
        candidates.update(path.resolve() for path in source_root.rglob("*.py"))
    # Sort candidate path elements by their confined repository-relative spellings.
    ordered = sorted(candidates, key=lambda path: _relative(root, path))
    # Revalidate each ordered path so absent files cannot survive sorting side effects.
    for path in ordered:
        # Prove confinement and existence for the exact snapshot returned.
        _relative(root, path)
    # Freeze the deterministic ordered review-input sequence.
    return tuple(ordered)


def scope_snapshot(declaration: Declaration) -> tuple[int, str]:
    """Hash every governed review input by relative name and content.

    @param declaration bounded project declaration
    @return file count and ``sha256:`` digest

    @par Effects
    Reads every file selected by ``scope_paths`` while constructing the content digest.
    """
    # Select the validated repository root that supplies stable relative identities.
    root = declaration.root
    # Hashing cannot proceed without the same bounded root used for enumeration.
    if root is None:
        # Reject the incomplete declaration before hashing ambient paths.
        _fail("REVIEW002_SCOPE_STALE", "$", "declared repository root is unavailable")
    # Initialize one sha256 accumulator for ordered path/content pairs.
    aggregate = hashlib.sha256()
    # Enumerate the complete input-path elements in stable relative order.
    paths = scope_paths(declaration)
    # Fold each ordered path/content pair into the aggregate digest.
    for path in paths:
        # Derive the confined platform-neutral path identity.
        relative = _relative(root, path)
        # Hash canonical file bytes separately to delimit content from path encoding.
        content_digest = hashlib.sha256(_canonical_content(path)).digest()
        # Append the path bytes, a NUL delimiter, fixed digest bytes, and record newline.
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(content_digest)
        aggregate.update(b"\n")
    # Return non-vacuity count and stable tagged aggregate digest.
    return len(paths), f"sha256:{aggregate.hexdigest()}"


def _canonical_content(path: Path) -> bytes:
    """Return portable governed content without weakening binary identity.

    Git may project the same UTF-8 text blob as LF on Linux and CRLF on Windows.
    Normalize that checkout-only distinction; invalid UTF-8 remains byte-exact.

    @param path repository-owned review input
    @return canonical bytes used by the scope digest

    @par Effects
    Reads the exact bytes of ``path`` once.
    """
    # Read one exact file snapshot before deciding whether text normalization applies.
    content = path.read_bytes()
    # Attempt strict UTF-8 decoding to distinguish text from binary inputs.
    try:
        # Decode without replacement so invalid bytes cannot be weakened.
        text = content.decode("utf-8")
    # Preserve byte-exact identity for content that is not valid UTF-8 text.
    except UnicodeDecodeError:
        # Return the original bytes unchanged.
        return content
    # Normalize only checkout-level CRLF variation, then restore canonical UTF-8 bytes.
    return text.replace("\r\n", "\n").encode("utf-8")


def _unique(values: Sequence[str], where: str, diagnostic_id: str) -> None:
    """Require record identities to occur once.

    @param values identity elements in source order
    @param where JSON collection path
    @param diagnostic_id semantic diagnostic
    @throws ReviewError when an identity repeats
    """
    # Compare sequence cardinality with its unordered identity set.
    if len(values) != len(set(values)):
        # Reject the containing collection rather than selecting one duplicate.
        _fail(diagnostic_id, where, "duplicate identities are not allowed")


def _validate_commit(review: Review, root: Path) -> None:
    """Validate commit syntax and ancestry when this root owns Git metadata.

    @param review parsed review artifact
    @param root governed repository root
    @throws ReviewError when the commit is malformed or not an ancestor

    @par Effects
    Reads repository metadata and, when ``.git`` exists, executes a bounded Git ancestry
    probe without a shell.
    """
    # Require a full Git object identity before consulting repository state.
    if COMMIT_ID.fullmatch(review.reviewed_commit) is None:
        # Reject abbreviated and malformed identities at the exact field path.
        _fail("REVIEW003_COMMIT", "$.reviewed_commit", "expected a full Git object id")
    # Extracted packages without Git metadata can retain syntax-bound review evidence.
    if not (root / ".git").exists():
        # Stop before attempting an ancestry relation unavailable in an archive.
        return
    # Resolve the Git executable through the current development environment.
    git = shutil.which("git")
    # A checkout claiming ancestry must have Git available to prove it.
    if git is None:
        # Reject unverifiable ancestry rather than silently accepting it.
        _fail("REVIEW003_COMMIT", str(root), "Git is unavailable for ancestry proof")
    # Execute one time-bounded, fixed-argument ancestry predicate.
    try:
        # Capture output so a successful validation remains quiet and deterministic.
        completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed argv, no shell
            (
                git,
                "-C",
                str(root),
                "merge-base",
                "--is-ancestor",
                review.reviewed_commit,
                "HEAD",
            ),
            capture_output=True,
            check=False,
            timeout=5,
        )
    # Translate launch and timeout failures into the commit diagnostic.
    except (OSError, subprocess.TimeoutExpired) as problem:
        # Preserve the repository root and operating-system detail.
        _fail("REVIEW003_COMMIT", str(root), f"Git ancestry probe failed: {problem}")
    # Git returns nonzero when the reviewed base is not an ancestor of current HEAD.
    if completed.returncode != 0:
        # Reject a review bound to unrelated or future history.
        _fail(
            "REVIEW003_COMMIT",
            "$.reviewed_commit",
            "commit is not an ancestor of this repository HEAD",
        )


def _validate_scope(review: Review, declaration: Declaration) -> None:
    """Require exact category and content freshness.

    @param review parsed review artifact
    @param declaration bounded project declaration
    @throws ReviewError when selected content differs from the reviewed snapshot
    """
    # Select the claimed content snapshot for exact algorithm and category validation.
    scope = review.scope
    # The digest contract fixes both hash algorithm and complete category sequence.
    if scope.algorithm != "sha256" or scope.categories != SCOPE_CATEGORIES:
        # Report the canonical ordered category elements expected by this schema.
        _fail(
            "REVIEW002_SCOPE_STALE",
            "$.scope",
            f"expected algorithm sha256 and categories {list(SCOPE_CATEGORIES)}",
        )
    # Recompute current non-vacuity count and aggregate content digest.
    count, digest = scope_snapshot(declaration)
    # Either changed membership or changed bytes make the semantic review stale.
    if scope.file_count != count or scope.digest != digest:
        # Report both reviewed and current identities for deterministic refresh guidance.
        _fail(
            "REVIEW002_SCOPE_STALE",
            "$.scope",
            f"reviewed count/digest={scope.file_count}/{scope.digest}, current={count}/{digest}",
        )


def _validate_questions(review: Review, root: Path) -> None:
    """Require every semantic attack angle and confined evidence.

    @param review parsed review artifact
    @param root governed repository root
    @throws ReviewError when coverage or evidence is stale
    """
    # Collect each question identifier in authored order for uniqueness and ordering checks.
    ids = [item.question_id for item in review.questions]
    # Prove the authored question identities contain no aliases.
    _unique(ids, "$.questions", "REVIEW004_QUESTIONS")
    # Every required semantic angle must appear exactly once in canonical order.
    if tuple(ids) != QUESTION_CATEGORIES:
        # Route missing documentation-semantic questions to their dedicated v5 rule.
        diagnostic = (
            "REVIEW008_DOCUMENTATION"
            if any(category not in ids for category in DOCUMENTATION_QUESTION_CATEGORIES)
            else "REVIEW004_QUESTIONS"
        )
        # Reject incomplete or reordered challenge coverage with the complete expectation.
        _fail(
            diagnostic,
            "$.questions",
            f"expected exactly {list(QUESTION_CATEGORIES)} in canonical order",
        )
    # Validate each question-record element in canonical order.
    for question in review.questions:
        # Validate each evidence-path element in authored examination order.
        for evidence in question.evidence:
            # Prove the examined artifact exists inside the governed repository.
            _local_path(root, evidence, "REVIEW004_QUESTIONS")


def _validate_reviewer(review: Review) -> None:
    """Require role separation without claiming to authenticate identity.

    @param review parsed review artifact
    @throws ReviewError when reviewer and author identities overlap
    """
    # Prove each authored author-identity element appears once.
    _unique(review.authors, "$.authors", "REVIEW005_INDEPENDENCE")
    # The reviewer must declare the one role reserved for adversarial challenge.
    if review.reviewer.role != "adversarial_reviewer":
        # Reject operational or author roles that do not state adversarial responsibility.
        _fail(
            "REVIEW005_INDEPENDENCE",
            "$.reviewer.role",
            "expected adversarial_reviewer",
        )
    # Declared reviewer identity must not also claim authorship of the reviewed change.
    if review.reviewer.identity in review.authors:
        # Reject explicit identity overlap without overclaiming identity authentication.
        _fail(
            "REVIEW005_INDEPENDENCE",
            "$.reviewer.identity",
            "reviewer identity also appears among change authors",
        )


def _validate_objections(review: Review, root: Path) -> None:
    """Require concrete challenge and closure before acceptance.

    @param review parsed review artifact
    @param root governed repository root
    @throws ReviewError on duplicate, open, or unevidenced closure
    """
    # Prove each authored objection identity appears once before evaluating closure.
    _unique(
        [item.objection_id for item in review.objections],
        "$.objections",
        "REVIEW006_FINDING_CLOSURE",
    )
    # Validate each objection-record element in authored order.
    for objection in review.objections:
        # A non-open disposition defines the two-state closure predicate.
        closed = objection.disposition != "open"
        # Closed objections require both rationale and evidence; open objections forbid both.
        if closed != (objection.resolution is not None and objection.evidence is not None):
            # Reject inconsistent closure rather than inferring intent from partial fields.
            _fail(
                "REVIEW006_FINDING_CLOSURE",
                objection.objection_id,
                "closed objections require resolution and evidence; open ones forbid both",
            )
        # Closure evidence, when present, must reference a confined local artifact.
        if objection.evidence is not None:
            # Prove the closure artifact exists inside the governed repository.
            _local_path(root, objection.evidence, "REVIEW006_FINDING_CLOSURE")
    # Acceptance cannot coexist with any still-open objection.
    if any(item.disposition == "open" for item in review.objections):
        # Reject the review until every objection is resolved or explicitly accepted as risk.
        _fail(
            "REVIEW006_FINDING_CLOSURE",
            "$.objections",
            "accepted scope still has an open objection",
        )


def validate(review: Review, declaration: Declaration, root: Path) -> None:
    """Cross-check structured review integrity and acceptance.

    @param review parsed review artifact
    @param declaration bounded project declaration
    @param root governed repository root
    @throws ReviewError on the first deterministic mismatch
    """
    # Establish history identity before validating the mutable content snapshot.
    _validate_commit(review, root)
    # Prove exact current scope membership and bytes.
    _validate_scope(review, declaration)
    # Prove complete semantic attack coverage and confined evidence.
    _validate_questions(review, root)
    # Prove declared role separation without claiming identity authentication.
    _validate_reviewer(review)
    # Prove every concrete objection has an internally consistent closed disposition.
    _validate_objections(review, root)
    # Only an explicit accepted verdict permits the governed scope to pass.
    if review.verdict != "accepted":
        # Reject provisional and negative verdicts regardless of completed mechanics.
        _fail(
            "REVIEW007_VERDICT_RESIDUAL",
            "$.verdict",
            "the current governed scope has not been adversarially accepted",
        )


class AdversarialReviewCheck(Check):
    """Check review freshness, challenge coverage, independence, and closure."""

    ## Mechanism token for structured adversarial review rules.
    name = "adversarial_review"
    ## Rule-id elements in deterministic reporting order for review obligations.
    rules = ("SEC-003", "SEC-004", "DOC-028")

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Validate the canonical review from the nearest declaration.

        @param paths path elements in caller order, deliberately ignored because the
            declaration-bound scope is authoritative
        @return zero or one earliest deterministic finding
        """
        # Mark the protocol parameter consumed while retaining the common checker signature.
        _ = paths
        # Resolve the canonical review path and governed repository root.
        review_path = self.declaration.adversarial_review_path()
        root = self.declaration.root
        # A project without a complete optional review declaration has no review gate to run.
        if review_path is None or root is None:
            # Return an ordered empty finding sequence for an undeclared mechanism.
            return []
        # Parse and validate the complete content-bound adversarial review.
        try:
            # Validate the parsed review against its exact current declaration-bound scope.
            validate(parse(review_path), self.declaration, root)
        # Translate a typed review failure into its owning discipline rule.
        except ReviewError as problem:
            # Extract the stable diagnostic-family prefix before rule selection.
            prefix = problem.diagnostic_id.split("_", 1)[0]
            # Map each diagnostic-prefix key to its governing rule-id value; order is immaterial.
            rule = {
                "REVIEW001": "SEC-003",
                "REVIEW002": "SEC-003",
                "REVIEW003": "SEC-003",
                "REVIEW004": "SEC-004",
                "REVIEW005": "SEC-004",
                "REVIEW006": "SEC-004",
                "REVIEW007": "SEC-004",
                "REVIEW008": "DOC-028",
            }[prefix]
            # Return the sole earliest finding with the review diagnostic preserved.
            return [
                Finding(
                    rule_id=rule,
                    path=review_path,
                    line=1,
                    message=f"{problem.where}: {problem.detail}",
                    remediation=(
                        "Repeat the adversarial review over the exact current local scope, "
                        "close or explicitly reject its findings, and preserve the residual."
                    ),
                    diagnostic_id=problem.diagnostic_id,
                )
            ]
        # A complete validation produces the ordered empty finding sequence.
        return []


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    from . import main

    # Translate the checker result into the process exit status.
    raise SystemExit(main(AdversarialReviewCheck()))
