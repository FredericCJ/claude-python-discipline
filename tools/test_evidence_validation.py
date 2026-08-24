"""Integration proofs for the v4 evidence checks in `validate.py`."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from discipline_core import parse_document
from test_evidence_model import strategy, valid_payload
from test_validate import module
from validate import Finding, Layout, Severity, check_evidence

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from pathlib import Path


def write_evidence(root: Path, payload: dict[str, object]) -> Path:
    """Place an authored registry in a throwaway corpus.

    @param root synthetic repository root
    @param payload JSON-shaped registry
        Treat payload as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @return registry path

    @par Effects
    Writes only pytest-owned evidence fixtures used to exercise structural validation.
    """
    # Select the canonical authored evidence-registry path beneath the synthetic corpus.
    path = root / "discipline" / "meta" / "evidence.json"
    # Create the registry's metadata directory before writing either joined artifact.
    path.parent.mkdir(parents=True, exist_ok=True)
    # Persist the caller's evidence payload in a readable deterministic JSON form.
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Supply the minimal empty observation registry required by evidence validation.
    (path.parent / "observations.json").write_text(
        json.dumps({"schema_version": 1, "observations": {}}), encoding="utf-8"
    )
    # Return the authored evidence path for tests that need direct mutation.
    return path


def write_matrix(root: Path, *covered: tuple[str, str]) -> None:
    """Place the smallest loadable discrimination matrix in a throwaway tree.

    @param root synthetic repository root
    @param covered exact rule and mechanism pairs the matrix witnessed
        Each element is one `(rule id, mechanism name)` tuple; caller argument
        order is preserved in the generated matrix.

    @par Effects
    Writes only pytest-owned evidence fixtures used to exercise structural validation.
        Each covered element represents one governed path; traversal order is preserved.
    """
    # Select the exact module imported by the strategy-witness resolver.
    path = root / "enforce" / "discrimination.py"
    # Create the synthetic enforcement package before materializing its matrix.
    path.parent.mkdir(parents=True, exist_ok=True)
    # Each value is one exact rule/mechanism tuple in caller order for deterministic source.
    values = ", ".join(
        # Render each covered pair as a Python literal consumed by the synthetic module.
        repr(pair) for pair in covered
    )
    # Materialize a loadable matrix whose only evidence is the declared pair set.
    path.write_text(
        '"""Synthetic discrimination matrix."""\n\n\n'
        "def covered_strategies() -> frozenset[tuple[str, str]]:\n"
        '    """Return witnessed strategies.\n\n    @return exact pairs\n    """\n'
        f"    return frozenset({{{values}}})\n",
        encoding="utf-8",
    )


def evidence_findings(root: Path) -> list[Finding]:
    """Validate the sole synthetic rule against its registry.

    @param root synthetic repository root
    @return evidence findings
    """
    # Parse the synthetic law module once, then validate that exact document graph.
    document = parse_document(module(root))
    return list(check_evidence([document], Layout(root), required=True))


def test_v100_requires_the_registry(tmp_path: Path) -> None:
    """A v4 corpus cannot omit the evidence layer."""
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = list(check_evidence([], Layout(tmp_path), required=True))
    assert [finding.code for finding in findings] == ["V100"]


def test_v100_reports_structural_corruption(tmp_path: Path) -> None:
    """Malformed evidence becomes an actionable validator finding, not a crash.

    @par Effects
    Writes only pytest-owned evidence fixtures used to exercise structural validation.
    """
    # Select the canonical registry path so malformed bytes reach the production loader.
    path = tmp_path / "discipline" / "meta" / "evidence.json"
    # Create the otherwise-valid metadata directory.
    path.parent.mkdir(parents=True)
    # Persist an unterminated JSON object as the sole structural defect.
    path.write_text("{", encoding="utf-8")
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = list(check_evidence([], Layout(tmp_path), required=True))
    assert [finding.code for finding in findings] == ["V100"]
    assert findings[0].severity is Severity.ERROR


def test_v104_rejects_a_strategy_not_named_by_the_heading(tmp_path: Path) -> None:
    """The evidence layer cannot quietly substitute another mechanism."""
    # Mutate only the evidence mechanism so the heading/evidence join is the failing edge.
    payload = valid_payload()
    strategy(payload)["mechanism"] = "auto:pyright"
    write_evidence(tmp_path, payload)
    write_matrix(tmp_path, ("TYPE-001", "auto:mypy"))
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = evidence_findings(tmp_path)
    assert "V104" in {finding.code for finding in findings}


def test_v107_counts_an_unwitnessed_strategy_without_calling_it_green(tmp_path: Path) -> None:
    """A declared must-reject label earns no credit before the matrix runs it."""
    write_evidence(tmp_path, valid_payload())
    write_matrix(tmp_path)
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = evidence_findings(tmp_path)
    assert [finding.code for finding in findings] == ["V107"]
    assert findings[0].severity is Severity.WARN


def test_a_witnessed_complete_record_is_silent(tmp_path: Path) -> None:
    """The positive control joins all three layers without residue in the validator."""
    # This complete rule/evidence/observation graph is the validator's positive control.
    payload = valid_payload()
    write_evidence(tmp_path, payload)
    write_matrix(tmp_path, ("TYPE-001", "auto:mypy"))
    assert evidence_findings(tmp_path) == []


def test_v109_rejects_an_observation_that_does_not_resolve(tmp_path: Path) -> None:
    """Field evidence must be a packaged record, not an anecdotal string."""
    # Navigate the single-rule fixture to corrupt only its observation reference.
    payload = valid_payload()
    evidence = payload["rules"]
    assert isinstance(evidence, dict)
    sole = evidence["TYPE-001"]
    assert isinstance(sole, dict)
    # Point the otherwise valid record at an observation absent from the packaged registry.
    sole["observations"] = ["V4E-999"]
    write_evidence(tmp_path, payload)
    write_matrix(tmp_path, ("TYPE-001", "auto:mypy"))
    assert [finding.code for finding in evidence_findings(tmp_path)] == ["V109"]
