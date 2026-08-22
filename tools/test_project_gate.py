"""The v4 project gate cannot turn absence, narrowing, or silence green.

**Oracle: state and differential.** Synthetic repositories exercise exact-root
declaration failure while the worked reference exercises the same check adapter
against a known conformant tree.

    pytest tools/test_project_gate.py
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest

import project_gate
from fixtures import reference_root

if TYPE_CHECKING:
    from pathlib import Path


def test_only_pass_and_valid_not_applicable_are_green() -> None:
    """Unsupported and not-run required work cannot be reported as success."""
    passed = project_gate.StepResult(
        step_id="probe", rules=(), status=project_gate.Status.PASS,
        required=True, diagnostic_id=None, summary="ran",
    )
    inapplicable = project_gate.StepResult(
        step_id="conditional", rules=(), status=project_gate.Status.NOT_APPLICABLE,
        required=False, diagnostic_id="GATE-NOT-APPLICABLE",
        summary="capability is false",
    )
    unsupported = project_gate.StepResult(
        step_id="platform", rules=(), status=project_gate.Status.UNSUPPORTED,
        required=True, diagnostic_id="GATE-UNSUPPORTED",
        summary="required tool has no Windows implementation",
    )
    not_run = project_gate.StepResult(
        step_id="blocked", rules=(), status=project_gate.Status.NOT_RUN,
        required=True, diagnostic_id="GATE-NOT-RUN", summary="declaration failed",
    )

    assert passed.green
    assert inapplicable.green
    assert not unsupported.green
    assert not not_run.green


def test_ambiguous_result_records_are_refused() -> None:
    """A non-pass result without a reason code cannot enter a report."""
    with pytest.raises(ValueError, match="stable diagnostic"):
        project_gate.StepResult(
            step_id="ambiguous", rules=(), status=project_gate.Status.FAIL,
            required=True, diagnostic_id=None, summary="failed",
        )


def test_missing_local_declaration_never_falls_back_to_parent(tmp_path: Path) -> None:
    """An exact child root cannot borrow its parent's valid declaration."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.agent-discipline]\nunit='application'\n",
        encoding="utf-8",
    )
    child = tmp_path / "child"
    child.mkdir()

    report = project_gate.run(child)

    assert not report.green
    assert report.unit is None
    assert report.outcomes[0].status is project_gate.Status.FAIL
    assert report.outcomes[1].status is project_gate.Status.NOT_RUN
    assert str(child / "pyproject.toml") in report.outcomes[0].summary


def test_reference_loads_one_declaration_for_every_check() -> None:
    """The conformant reference passes the in-process aggregate check."""
    report = project_gate.run(reference_root())

    assert report.green
    assert report.unit == "application"
    assert [result.status for result in report.outcomes] == [
        project_gate.Status.PASS,
        project_gate.Status.PASS,
    ]
    assert report.outcomes[1].subjects >= 20
    assert report.outcomes[1].configuration == report.outcomes[0].configuration


def test_report_records_every_non_pass_as_a_deviation(tmp_path: Path) -> None:
    """Failure and prevented work retain distinct reasons in serialized output."""
    report = project_gate.run(tmp_path)
    document = report.as_dict()

    assert document["verdict"] == "fail"
    deviations = cast("list[dict[str, object]]", document["deviations"])
    assert [item["status"] for item in deviations] == ["fail", "not-run"]
    encoded = json.dumps(document)
    diagnostic = report.outcomes[0].diagnostic_id
    assert diagnostic is not None
    assert diagnostic in encoded
    assert "GATE002_PREREQUISITE" in encoded
