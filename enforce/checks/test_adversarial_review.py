"""Proof-of-failure tests for content-bound adversarial acceptance."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from checks import project
from checks.adversarial_review import (
    QUESTION_CATEGORIES,
    SCOPE_CATEGORIES,
    AdversarialReviewCheck,
    scope_snapshot,
)
from checks.test_project import declare, v4

if TYPE_CHECKING:
    from pathlib import Path

## One local review-evidence file used by every semantic question and objection.
EVIDENCE = "tests/test_review.py::test_review_evidence"
## Lexically valid fixture commit; temporary trees intentionally own no Git metadata.
COMMIT = "1" * 40


def review_payload(declaration: project.Declaration) -> dict[str, object]:
    """Build one complete accepted review over the current fixture content.

    @param declaration parsed bounded project declaration
    @return JSON-ready structured review
    """
    count, digest = scope_snapshot(declaration)
    return {
        "schema_version": 1,
        "review_id": "fixture_adversarial_acceptance",
        "reviewed_commit": COMMIT,
        "scope": {
            "algorithm": "sha256",
            "digest": digest,
            "file_count": count,
            "categories": list(SCOPE_CATEGORIES),
        },
        "authors": ["fixture_implementation_author"],
        "reviewer": {
            "identity": "fixture_adversarial_reviewer",
            "role": "adversarial_reviewer",
            "independence": "independent",
            "basis": "The reviewer did not author the scoped fixture change.",
        },
        "questions": [
            {
                "id": category,
                "challenge": f"What hostile {category} case contradicts acceptance?",
                "conclusion": f"The fixture evidence bounds the {category} conclusion.",
                "evidence": [EVIDENCE],
            }
            for category in QUESTION_CATEGORIES
        ],
        "objections": [{
            "id": "presence_is_not_semantics",
            "category": "test_oracles",
            "severity": "medium",
            "statement": "An existing test path does not prove its oracle is sufficient.",
            "disposition": "resolved",
            "resolution": "Retain the limitation in the review residual.",
            "evidence": EVIDENCE,
            "owner": "fixture_maintainer",
            "review_trigger": "Review again whenever the test oracle changes.",
        }],
        "verdict": "accepted",
        "conclusion": "No open local objection prevents fixture acceptance.",
        "residual": "The checker cannot authenticate identity or judge semantic insight.",
    }


def _tree(
    tmp_path: Path,
) -> tuple[AdversarialReviewCheck, Path, Path, dict[str, object]]:
    """Create one complete review fixture repository.

    @param tmp_path fixture repository
    @return configured checker, source root, review path, and mutable payload
    """
    declaration_path = declare(tmp_path, v4())
    source = tmp_path / "src/pkg"
    source.mkdir(parents=True)
    (source / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    evidence = tmp_path / "tests/test_review.py"
    evidence.parent.mkdir()
    evidence.write_text("def test_review_evidence(): ...\n", encoding="utf-8")
    for name in (
        "architecture.json",
        "contract-conformance.json",
        "operational-model.json",
        "security-model.json",
    ):
        (tmp_path / name).write_text("{}\n", encoding="utf-8")
    (tmp_path / "documentation-model.json").write_text(
        '{"schema_version": 1}\n', encoding="utf-8"
    )
    declaration = project.parse(declaration_path)
    payload = review_payload(declaration)
    review_path = tmp_path / "adversarial-review.json"
    _write(review_path, payload)
    check = AdversarialReviewCheck()
    check.declaration = declaration
    return check, source, review_path, payload


def _write(path: Path, payload: dict[str, object]) -> None:
    """Write a mutated review payload.

    @param path review path
    @param payload JSON-ready review
    """
    path.write_text(json.dumps(payload), encoding="utf-8")


def _diagnostic(check: AdversarialReviewCheck, source: Path) -> str | None:
    """Return the first stable review diagnostic.

    @param check configured review checker
    @param source production source root
    @return diagnostic id or None for acceptance
    """
    findings = check.run([source])
    return None if not findings else findings[0].diagnostic_id


def _records(payload: dict[str, object], key: str) -> list[dict[str, object]]:
    """Narrow one mutable review record array.

    @param payload JSON-ready review
    @param key root record-array field
    @return mutable records
    """
    value = payload[key]
    assert isinstance(value, list)
    assert all(isinstance(item, dict) for item in value)
    return cast("list[dict[str, object]]", value)


def test_complete_content_bound_review_is_accepted(tmp_path: Path) -> None:
    """Fresh scope, all questions, separated reviewer, and closure are green.

    @param tmp_path fixture repository
    """
    check, source, _, _ = _tree(tmp_path)
    assert check.run([source]) == []


def test_source_change_makes_review_stale(tmp_path: Path) -> None:
    """A reviewed artifact cannot cover production bytes changed afterward.

    @param tmp_path fixture repository
    """
    check, source, _, _ = _tree(tmp_path)
    (source / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert _diagnostic(check, source) == "REVIEW002_SCOPE_STALE"


def test_checkout_line_endings_do_not_change_review_identity(tmp_path: Path) -> None:
    """Windows CRLF projection and Linux LF projection identify the same text.

    @param tmp_path fixture repository
    """
    check, source, _, _ = _tree(tmp_path)
    module = source / "module.py"
    content = module.read_bytes()
    projected = (
        content.replace(b"\r\n", b"\n")
        if b"\r\n" in content
        else content.replace(b"\n", b"\r\n")
    )
    module.write_bytes(projected)
    assert check.run([source]) == []


def test_replaceable_tool_cache_is_outside_review_identity(tmp_path: Path) -> None:
    """A verifier cache cannot invalidate the source it just verified.

    @param tmp_path fixture repository
    """
    check, source, _, _ = _tree(tmp_path)
    cache = tmp_path / ".import_linter_cache/result.json"
    cache.parent.mkdir()
    cache.write_text('{"replaceable": true}\n', encoding="utf-8")
    assert check.run([source]) == []


def test_replaceable_packaging_metadata_is_outside_review_identity(tmp_path: Path) -> None:
    """A clean package build cannot invalidate the source it just reviewed.

    @param tmp_path fixture repository
    """
    check, source, _, _ = _tree(tmp_path)
    metadata = tmp_path / "src/pkg.egg-info/SOURCES.txt"
    metadata.parent.mkdir()
    metadata.write_text("src/pkg/module.py\n", encoding="utf-8")
    assert check.run([source]) == []


def test_scope_categories_are_closed_and_ordered(tmp_path: Path) -> None:
    """An author cannot omit tests from review by editing the category list.

    @param tmp_path fixture repository
    """
    check, source, path, payload = _tree(tmp_path)
    scope = payload["scope"]
    assert isinstance(scope, dict)
    scope["categories"] = list(SCOPE_CATEGORIES[:-1])
    _write(path, payload)
    assert _diagnostic(check, source) == "REVIEW002_SCOPE_STALE"


def test_review_commit_requires_a_full_object_id(tmp_path: Path) -> None:
    """A branch name cannot preserve which history was reviewed.

    @param tmp_path fixture repository
    """
    check, source, path, payload = _tree(tmp_path)
    payload["reviewed_commit"] = "main"
    _write(path, payload)
    assert _diagnostic(check, source) == "REVIEW003_COMMIT"


def test_every_semantic_question_is_required(tmp_path: Path) -> None:
    """A review cannot quietly omit its test-oracle attack angle.

    @param tmp_path fixture repository
    """
    check, source, path, payload = _tree(tmp_path)
    _records(payload, "questions").pop(0)
    _write(path, payload)
    assert _diagnostic(check, source) == "REVIEW004_QUESTIONS"


def test_a_missing_documentation_question_fails_doc_028(tmp_path: Path) -> None:
    """Documentation judgment cannot disappear inside generic review coverage.

    @param tmp_path fixture repository
    """
    check, source, path, payload = _tree(tmp_path)
    questions = _records(payload, "questions")
    questions[:] = [
        question for question in questions if question["id"] != "documentation_truth"
    ]
    _write(path, payload)

    assert _diagnostic(check, source) == "REVIEW008_DOCUMENTATION"


def test_question_evidence_cannot_escape_repository(tmp_path: Path) -> None:
    """A sibling review cannot satisfy this repository's acceptance.

    @param tmp_path fixture repository
    """
    check, source, path, payload = _tree(tmp_path)
    _records(payload, "questions")[0]["evidence"] = ["../peer/review.md"]
    _write(path, payload)
    assert _diagnostic(check, source) == "REVIEW004_QUESTIONS"


def test_reviewer_cannot_be_a_declared_author(tmp_path: Path) -> None:
    """Self-approval cannot be labeled independent adversarial review.

    @param tmp_path fixture repository
    """
    check, source, path, payload = _tree(tmp_path)
    reviewer = payload["reviewer"]
    assert isinstance(reviewer, dict)
    reviewer["identity"] = "fixture_implementation_author"
    _write(path, payload)
    assert _diagnostic(check, source) == "REVIEW005_INDEPENDENCE"


def test_open_objection_blocks_acceptance(tmp_path: Path) -> None:
    """A verdict cannot overwrite an unresolved finding.

    @param tmp_path fixture repository
    """
    check, source, path, payload = _tree(tmp_path)
    objection = _records(payload, "objections")[0]
    objection["disposition"] = "open"
    objection["resolution"] = None
    objection["evidence"] = None
    _write(path, payload)
    assert _diagnostic(check, source) == "REVIEW006_FINDING_CLOSURE"


def test_rejected_verdict_is_not_a_green_gate(tmp_path: Path) -> None:
    """A present review can conclude that the scope is not acceptable.

    @param tmp_path fixture repository
    """
    check, source, path, payload = _tree(tmp_path)
    payload["verdict"] = "rejected"
    _write(path, payload)
    assert _diagnostic(check, source) == "REVIEW007_VERDICT_RESIDUAL"
