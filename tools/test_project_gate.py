"""The v4 project gate cannot turn absence, narrowing, or silence green.

**Oracle: state and differential.** Synthetic repositories exercise exact-root
declaration failure while the worked reference exercises the same check adapter
against a known conformant tree.

    pytest tools/test_project_gate.py
"""

from __future__ import annotations

import json
import shutil
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
    report = project_gate.run(
        reference_root(),
        steps=(project_gate.DisciplineChecksAdapter(),),
    )

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
    assert deviations[0]["status"] == "fail"
    assert all(item["status"] == "not-run" for item in deviations[1:])
    encoded = json.dumps(document)
    diagnostic = report.outcomes[0].diagnostic_id
    assert diagnostic is not None
    assert diagnostic in encoded
    assert "GATE002_PREREQUISITE" in encoded


def _configured_tool_project(tmp_path: Path) -> Path:
    """Copy the worked reference and add all four external-tool tables.

    @param tmp_path isolated pytest directory
    @return configured repository root
    """
    root = tmp_path / "project"
    shutil.copytree(reference_root(), root)
    with (root / "pyproject.toml").open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(
            "\n[tool.ruff]\n"
            "src = ['src']\n"
            "\n[tool.ruff.lint]\n"
            "select = ['ALL']\n"
            "\n[tool.mypy]\n"
            "strict = true\n"
            "files = ['src']\n"
            "\n[tool.pyright]\n"
            "typeCheckingMode = 'strict'\n"
            "include = ['src']\n"
            "\n[tool.pytest.ini_options]\n"
            "testpaths = ['tests']\n",
        )
    tests = root / "tests"
    tests.mkdir(exist_ok=True)
    (tests / "test_smoke.py").write_text(
        '"""A non-vacuous gate fixture."""\n\n'
        "def test_smoke() -> None:\n"
        '    """The fixture executes."""\n'
        "    assert True\n",
        encoding="utf-8",
    )
    return root


@pytest.mark.parametrize(
    ("adapter", "output", "target"),
    [
        (project_gate.RUFF_STEP, "All checks passed!\n", "src"),
        (project_gate.MYPY_STEP, "Success: no issues found\n", "src"),
        (
            project_gate.PYRIGHT_STEP,
            '{"summary":{"filesAnalyzed":26,"errorCount":0}}',
            "src",
        ),
        (project_gate.PYTEST_STEP, "1 passed in 0.01s\n", "tests"),
    ],
    ids=("ruff", "mypy", "pyright", "pytest"),
)
def test_external_adapters_bind_config_and_non_empty_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    adapter: project_gate.ConfiguredToolAdapter,
    output: str,
    target: str,
) -> None:
    """Each adapter passes explicit local targets and records the loaded bytes.

    @param tmp_path isolated repository parent
    @param monkeypatch substitutes process and distribution observations
    @param adapter external mechanism under test
    @param output successful tool-specific report
    @param target expected explicit argv target
    """
    root = _configured_tool_project(tmp_path)
    commands: list[project_gate.PreparedCommand] = []

    def execute(
        command: project_gate.PreparedCommand, _root: Path,
    ) -> project_gate.CommandExecution:
        """Capture one prepared command and return the declared observation.

        @param command configuration-probed argv
        @param _root governed working directory
        @return successful process observation
        """
        commands.append(command)
        return project_gate.CommandExecution(0, output, 1)

    monkeypatch.setattr(project_gate, "_execute", execute)
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "test")

    report = project_gate.run(root, steps=(adapter,))
    result = report.outcomes[1]

    assert result.status is project_gate.Status.PASS
    assert result.subjects > 0
    assert result.tool == f"{adapter.distribution} test"
    assert result.configuration[0].path == "pyproject.toml"
    assert str(root / "pyproject.toml") in commands[0].command
    assert target in commands[0].command


def test_missing_tool_configuration_is_a_failed_probe(tmp_path: Path) -> None:
    """A missing Ruff table cannot become an unsupported or narrower scan."""
    root = tmp_path / "project"
    shutil.copytree(reference_root(), root)

    report = project_gate.run(root, steps=(project_gate.RUFF_STEP,))
    result = report.outcomes[1]

    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "GATE-RUFF-001_CONFIGURATION"
    assert "tool.ruff" in result.summary


def test_pyright_zero_file_report_is_not_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pyright must corroborate that its configured target produced subjects."""
    root = _configured_tool_project(tmp_path)
    monkeypatch.setattr(
        project_gate,
        "_execute",
        lambda _command, _root: project_gate.CommandExecution(
            0, '{"summary":{"filesAnalyzed":0,"errorCount":0}}', 1,
        ),
    )
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "test")

    result = project_gate.run(root, steps=(project_gate.PYRIGHT_STEP,)).outcomes[1]

    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "GATE-PYRIGHT-005_NO_SUBJECT"


def test_pytest_all_skipped_report_is_not_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured suite that executes no passing oracle remains a failure."""
    root = _configured_tool_project(tmp_path)
    monkeypatch.setattr(
        project_gate,
        "_execute",
        lambda _command, _root: project_gate.CommandExecution(0, "3 skipped in 0.01s", 1),
    )
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "test")

    result = project_gate.run(root, steps=(project_gate.PYTEST_STEP,)).outcomes[1]

    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "GATE-PYTEST-004_NO_EXECUTION"
