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

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .project import Declaration

## Stable lower-snake record and reviewer identities.
IDENTIFIER: Final = re.compile(r"^[a-z][a-z0-9_]*$")
## Git SHA-1 or SHA-256 object identity.
COMMIT_ID: Final = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
## Content digest spelling used by the scope snapshot.
DIGEST: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
## Review inputs whose exact coverage is computed rather than author-selected.
SCOPE_CATEGORIES: Final = (
    "project_declaration",
    "canonical_models",
    "production_python",
    "test_python",
    "authored_documentation",
    "tool_configuration",
    "repository_assets",
)
## Semantic attack angles every accepted review must challenge.
QUESTION_CATEGORIES: Final = (
    "architecture",
    "contracts",
    "failure_containment",
    "lifecycle_budgets",
    "trust_data",
    "observability",
    "supply_chain",
    "test_oracles",
)
## Trees that are environment state, vendored doctrine, host mirrors, or build output.
EXCLUDED_DIRECTORIES: Final = frozenset({
    ".git", ".agent", ".agents", ".claude", ".hypothesis",
    ".import_linter_cache", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    ".venv", "__pycache__", "build", "dist",
})
## Replaceable packaging-metadata trees whose stem is project-specific.
EXCLUDED_DIRECTORY_SUFFIXES: Final = (".egg-info",)
## Replaceable runtime projections and coverage products excluded from semantic review.
EXCLUDED_FILES: Final = frozenset({".coverage", "coverage.xml"})
## Replaceable interpreter and local-database products excluded by suffix.
EXCLUDED_SUFFIXES: Final = frozenset({".db", ".pyc", ".pyo", ".sqlite", ".sqlite3"})
## Consequence severity labels for review objections.
SEVERITIES: Final = frozenset({"low", "medium", "high", "critical"})
## Closure states for resolved, accepted, and still-blocking objections.
DISPOSITIONS: Final = frozenset({"resolved", "accepted_risk", "open"})
## Whether the reviewer claims personal independence or an explicit separated pass.
INDEPENDENCE: Final = frozenset({"independent", "role_separated"})


class ReviewError(ValueError):
    """One stable adversarial-review diagnostic."""

    def __init__(self, diagnostic_id: str, where: str, detail: str) -> None:
        """Build one actionable review failure.

        @param diagnostic_id stable mechanism diagnostic
        @param where JSON path or repository location
        @param detail explanation of the violated predicate
        """
        super().__init__(f"{diagnostic_id} {where}: {detail}")
        self.diagnostic_id = diagnostic_id
        self.where = where
        self.detail = detail


def _fail(diagnostic_id: str, where: str, detail: str) -> Never:
    """Raise one review diagnostic.

    @param diagnostic_id stable mechanism diagnostic
    @param where JSON path or repository location
    @param detail explanation of the violated predicate
    @return never; this helper always raises
    @throws ReviewError unconditionally
    """
    raise ReviewError(diagnostic_id, where, detail)


def _object(value: object, where: str) -> Mapping[str, object]:
    """Require a JSON object.

    @param value untrusted decoded value
    @param where JSON path
    @return typed mapping
    """
    if not isinstance(value, dict):
        _fail("REVIEW001_SCHEMA", where, "expected an object")
    return value


def _exact(record: Mapping[str, object], fields: set[str], where: str) -> None:
    """Reject missing and ignored fields.

    @param record decoded object
    @param fields exact accepted field set
    @param where JSON path
    @throws ReviewError when the field set differs
    """
    missing = fields - set(record)
    unknown = set(record) - fields
    if missing or unknown:
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
    if not isinstance(value, str) or not value.strip():
        _fail("REVIEW001_SCHEMA", where, "expected non-empty text")
    return value.strip()


def _optional_text(value: object, where: str) -> str | None:
    """Require null or non-empty text.

    @param value untrusted decoded value
    @param where JSON path
    @return stripped text or None
    """
    return None if value is None else _text(value, where)


def _identifier(value: object, where: str) -> str:
    """Require one lower-snake identity.

    @param value untrusted decoded value
    @param where JSON path
    @return validated identity
    """
    text = _text(value, where)
    if IDENTIFIER.fullmatch(text) is None:
        _fail("REVIEW001_SCHEMA", where, "expected lower_snake identifier")
    return text


def _strings(value: object, where: str) -> tuple[str, ...]:
    """Require a non-empty unique string array.

    @param value untrusted decoded value
    @param where JSON path
    @return values in source order
    """
    if not isinstance(value, list) or not value:
        _fail("REVIEW001_SCHEMA", where, "expected a non-empty string array")
    values = tuple(_text(item, f"{where}[{index}]") for index, item in enumerate(value))
    if len(values) != len(set(values)):
        _fail("REVIEW001_SCHEMA", where, "duplicate values are not allowed")
    return values


def _records(value: object, where: str) -> list[Mapping[str, object]]:
    """Require a non-empty record array.

    @param value untrusted decoded value
    @param where JSON path
    @return decoded records
    """
    if not isinstance(value, list) or not value:
        _fail("REVIEW001_SCHEMA", where, "expected a non-empty record array")
    return [_object(item, f"{where}[{index}]") for index, item in enumerate(value)]


@dataclass(frozen=True, slots=True)
class Scope:
    """Deterministic content snapshot reviewed by the artifact."""

    ## Hash algorithm, fixed to sha256 in schema version 1.
    algorithm: str
    ## Digest over relative path and content digest pairs.
    digest: str
    ## Number of files included in the digest.
    file_count: int
    ## Exact scope categories understood by the checker.
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
    ## Repository-local evidence paths examined.
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
    ## Identities that authored the reviewed change.
    authors: tuple[str, ...]
    ## Declared adversarial reviewer.
    reviewer: Reviewer
    ## Complete required challenge set.
    questions: tuple[Question, ...]
    ## At least one concrete objection proving an adversarial pass occurred.
    objections: tuple[Objection, ...]
    ## Accepted or rejected semantic verdict.
    verdict: str
    ## Bounded final conclusion.
    conclusion: str
    ## What can remain wrong after acceptance.
    residual: str


def _scope(value: object, where: str) -> Scope:
    """Parse one scope snapshot.

    @param value decoded scope object
    @param where JSON path
    @return typed scope
    """
    record = _object(value, where)
    _exact(record, {"algorithm", "digest", "file_count", "categories"}, where)
    count = record["file_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        _fail("REVIEW001_SCHEMA", f"{where}.file_count", "expected a positive integer")
    digest = _text(record["digest"], f"{where}.digest")
    if DIGEST.fullmatch(digest) is None:
        _fail("REVIEW001_SCHEMA", f"{where}.digest", "expected sha256:<64 lowercase hex>")
    return Scope(
        algorithm=_text(record["algorithm"], f"{where}.algorithm"),
        digest=digest,
        file_count=count,
        categories=_strings(record["categories"], f"{where}.categories"),
    )


def _reviewer(value: object, where: str) -> Reviewer:
    """Parse reviewer identity and separation.

    @param value decoded reviewer object
    @param where JSON path
    @return typed reviewer
    """
    record = _object(value, where)
    _exact(record, {"identity", "role", "independence", "basis"}, where)
    independence = _text(record["independence"], f"{where}.independence")
    if independence not in INDEPENDENCE:
        _fail(
            "REVIEW005_INDEPENDENCE",
            f"{where}.independence",
            f"expected one of {sorted(INDEPENDENCE)}",
        )
    return Reviewer(
        identity=_identifier(record["identity"], f"{where}.identity"),
        role=_identifier(record["role"], f"{where}.role"),
        independence=independence,
        basis=_text(record["basis"], f"{where}.basis"),
    )


def _question(record: Mapping[str, object], where: str) -> Question:
    """Parse one semantic challenge record.

    @param record decoded question record
    @param where JSON path
    @return typed question
    """
    _exact(record, {"id", "challenge", "conclusion", "evidence"}, where)
    return Question(
        question_id=_identifier(record["id"], f"{where}.id"),
        challenge=_text(record["challenge"], f"{where}.challenge"),
        conclusion=_text(record["conclusion"], f"{where}.conclusion"),
        evidence=_strings(record["evidence"], f"{where}.evidence"),
    )


def _objection(record: Mapping[str, object], where: str) -> Objection:
    """Parse one objection and closure record.

    @param record decoded objection record
    @param where JSON path
    @return typed objection
    """
    fields = {
        "id", "category", "severity", "statement", "disposition",
        "resolution", "evidence", "owner", "review_trigger",
    }
    _exact(record, fields, where)
    category = _identifier(record["category"], f"{where}.category")
    severity = _text(record["severity"], f"{where}.severity")
    disposition = _text(record["disposition"], f"{where}.disposition")
    if category not in QUESTION_CATEGORIES:
        _fail("REVIEW004_QUESTIONS", f"{where}.category", "unknown review category")
    if severity not in SEVERITIES or disposition not in DISPOSITIONS:
        _fail(
            "REVIEW006_FINDING_CLOSURE",
            where,
            "unknown severity or disposition",
        )
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
    """
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as problem:
        _fail("REVIEW001_SCHEMA", str(path), str(problem))
    root = _object(raw, "$")
    fields = {
        "schema_version", "review_id", "reviewed_commit", "scope", "authors",
        "reviewer", "questions", "objections", "verdict", "conclusion", "residual",
    }
    _exact(root, fields, "$")
    if root["schema_version"] != 1:
        _fail("REVIEW001_SCHEMA", "$.schema_version", "expected 1")
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


def _relative(root: Path, path: Path) -> str:
    """Return one confined repository-relative POSIX path.

    @param root governed repository root
    @param path candidate review input
    @return stable relative spelling
    @throws ReviewError when a declaration path escapes or is absent
    """
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError:
        _fail("REVIEW002_SCOPE_STALE", str(path), "review input leaves repository")
    if not resolved.is_file():
        _fail("REVIEW002_SCOPE_STALE", relative.as_posix(), "review input is absent")
    return relative.as_posix()


def scope_paths(declaration: Declaration) -> tuple[Path, ...]:
    """The exact files whose content an adversarial acceptance covers.

    @param declaration bounded project declaration
    @return files in stable repository-relative order
    @throws ReviewError when a required input is absent or outside the repository
    """
    root = declaration.root
    if root is None or declaration.source is None:
        _fail("REVIEW002_SCOPE_STALE", "$", "declared repository root is unavailable")
    candidates: set[Path] = set()
    review_path = declaration.adversarial_review_path()
    excluded_review = None if review_path is None else review_path.resolve()
    for directory, names, files in os.walk(root):
        names[:] = sorted(
            name
            for name in names
            if name not in EXCLUDED_DIRECTORIES
            and not name.endswith(EXCLUDED_DIRECTORY_SUFFIXES)
        )
        for name in sorted(files):
            path = (Path(directory) / name).resolve()
            if (
                path == excluded_review
                or name in EXCLUDED_FILES
                or path.suffix in EXCLUDED_SUFFIXES
            ):
                continue
            candidates.add(path)
    candidates.add(declaration.source.resolve())
    canonical = (
        declaration.architecture_path(),
        declaration.contract_conformance_path(),
        declaration.operational_model_path(),
        declaration.security_model_path(),
    )
    for canonical_path in canonical:
        if canonical_path is None:
            _fail("REVIEW002_SCOPE_STALE", "$", "canonical model path is undeclared")
        candidates.add(canonical_path.resolve())
    for source_root in declaration.source_paths():
        if not source_root.is_dir():
            _fail(
                "REVIEW002_SCOPE_STALE",
                str(source_root),
                "declared production source root is absent",
            )
        candidates.update(path.resolve() for path in source_root.rglob("*.py"))
    ordered = sorted(candidates, key=lambda path: _relative(root, path))
    for path in ordered:
        _relative(root, path)
    return tuple(ordered)


def scope_snapshot(declaration: Declaration) -> tuple[int, str]:
    """Hash every governed review input by relative name and content.

    @param declaration bounded project declaration
    @return file count and ``sha256:`` digest
    """
    root = declaration.root
    if root is None:
        _fail("REVIEW002_SCOPE_STALE", "$", "declared repository root is unavailable")
    aggregate = hashlib.sha256()
    paths = scope_paths(declaration)
    for path in paths:
        relative = _relative(root, path)
        content_digest = hashlib.sha256(_canonical_content(path)).digest()
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(content_digest)
        aggregate.update(b"\n")
    return len(paths), f"sha256:{aggregate.hexdigest()}"


def _canonical_content(path: Path) -> bytes:
    """Return portable governed content without weakening binary identity.

    Git may project the same UTF-8 text blob as LF on Linux and CRLF on Windows.
    Normalize that checkout-only distinction; invalid UTF-8 remains byte-exact.

    @param path repository-owned review input
    @return canonical bytes used by the scope digest
    """
    content = path.read_bytes()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return content
    return text.replace("\r\n", "\n").encode("utf-8")


def _unique(values: Sequence[str], where: str, diagnostic_id: str) -> None:
    """Require record identities to occur once.

    @param values identities in source order
    @param where JSON collection path
    @param diagnostic_id semantic diagnostic
    @throws ReviewError when an identity repeats
    """
    if len(values) != len(set(values)):
        _fail(diagnostic_id, where, "duplicate identities are not allowed")


def _validate_commit(review: Review, root: Path) -> None:
    """Validate commit syntax and ancestry when this root owns Git metadata.

    @param review parsed review artifact
    @param root governed repository root
    @throws ReviewError when the commit is malformed or not an ancestor
    """
    if COMMIT_ID.fullmatch(review.reviewed_commit) is None:
        _fail("REVIEW003_COMMIT", "$.reviewed_commit", "expected a full Git object id")
    if not (root / ".git").exists():
        return
    git = shutil.which("git")
    if git is None:
        _fail("REVIEW003_COMMIT", str(root), "Git is unavailable for ancestry proof")
    try:
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
    except (OSError, subprocess.TimeoutExpired) as problem:
        _fail("REVIEW003_COMMIT", str(root), f"Git ancestry probe failed: {problem}")
    if completed.returncode != 0:
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
    scope = review.scope
    if scope.algorithm != "sha256" or scope.categories != SCOPE_CATEGORIES:
        _fail(
            "REVIEW002_SCOPE_STALE",
            "$.scope",
            f"expected algorithm sha256 and categories {list(SCOPE_CATEGORIES)}",
        )
    count, digest = scope_snapshot(declaration)
    if scope.file_count != count or scope.digest != digest:
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
    ids = [item.question_id for item in review.questions]
    _unique(ids, "$.questions", "REVIEW004_QUESTIONS")
    if tuple(ids) != QUESTION_CATEGORIES:
        _fail(
            "REVIEW004_QUESTIONS",
            "$.questions",
            f"expected exactly {list(QUESTION_CATEGORIES)} in canonical order",
        )
    for question in review.questions:
        for evidence in question.evidence:
            _local_path(root, evidence, "REVIEW004_QUESTIONS")


def _validate_reviewer(review: Review) -> None:
    """Require role separation without claiming to authenticate identity.

    @param review parsed review artifact
    @throws ReviewError when reviewer and author identities overlap
    """
    _unique(review.authors, "$.authors", "REVIEW005_INDEPENDENCE")
    if review.reviewer.role != "adversarial_reviewer":
        _fail(
            "REVIEW005_INDEPENDENCE",
            "$.reviewer.role",
            "expected adversarial_reviewer",
        )
    if review.reviewer.identity in review.authors:
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
    _unique(
        [item.objection_id for item in review.objections],
        "$.objections",
        "REVIEW006_FINDING_CLOSURE",
    )
    for objection in review.objections:
        closed = objection.disposition != "open"
        if closed != (objection.resolution is not None and objection.evidence is not None):
            _fail(
                "REVIEW006_FINDING_CLOSURE",
                objection.objection_id,
                "closed objections require resolution and evidence; open ones forbid both",
            )
        if objection.evidence is not None:
            _local_path(root, objection.evidence, "REVIEW006_FINDING_CLOSURE")
    if any(item.disposition == "open" for item in review.objections):
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
    _validate_commit(review, root)
    _validate_scope(review, declaration)
    _validate_questions(review, root)
    _validate_reviewer(review)
    _validate_objections(review, root)
    if review.verdict != "accepted":
        _fail(
            "REVIEW007_VERDICT_RESIDUAL",
            "$.verdict",
            "the current governed scope has not been adversarially accepted",
        )


class AdversarialReviewCheck(Check):
    """Check review freshness, challenge coverage, independence, and closure."""

    ## Mechanism token for structured adversarial review rules.
    name = "adversarial_review"
    ## Independently diagnosable review obligations.
    rules = ("SEC-003", "SEC-004")

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Validate the canonical review from the nearest declaration.

        @param paths ignored caller selection; declaration-bound scope is authoritative
        @return zero or one earliest deterministic finding
        """
        _ = paths
        review_path = self.declaration.adversarial_review_path()
        root = self.declaration.root
        if review_path is None or root is None:
            return []
        try:
            validate(parse(review_path), self.declaration, root)
        except ReviewError as problem:
            prefix = problem.diagnostic_id.split("_", 1)[0]
            rule = {
                "REVIEW001": "SEC-003",
                "REVIEW002": "SEC-003",
                "REVIEW003": "SEC-003",
                "REVIEW004": "SEC-004",
                "REVIEW005": "SEC-004",
                "REVIEW006": "SEC-004",
                "REVIEW007": "SEC-004",
            }[prefix]
            return [Finding(
                rule_id=rule,
                path=review_path,
                line=1,
                message=f"{problem.where}: {problem.detail}",
                remediation=(
                    "Repeat the adversarial review over the exact current local scope, "
                    "close or explicitly reject its findings, and preserve the residual."
                ),
                diagnostic_id=problem.diagnostic_id,
            )]
        return []


if __name__ == "__main__":
    from . import main

    raise SystemExit(main(AdversarialReviewCheck()))
