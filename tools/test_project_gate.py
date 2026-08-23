"""The v4 project gate cannot turn absence, narrowing, or silence green.

**Oracle: state and differential.** Synthetic repositories exercise exact-root
declaration failure while the worked reference exercises the same check adapter
against a known conformant tree.

    pytest tools/test_project_gate.py
"""

from __future__ import annotations

import io
import json
import shutil
import tarfile
import zipfile
from pathlib import Path
from typing import cast

import pytest

import project_gate
from checks.__main__ import discover
from decides import decides
from fixtures import reference_root


def test_only_pass_and_valid_not_applicable_are_green() -> None:
    """Unsupported and not-run required work cannot be reported as success."""
    passed = project_gate.StepResult(
        step_id="probe",
        rules=(),
        status=project_gate.Status.PASS,
        required=True,
        diagnostic_id=None,
        summary="ran",
    )
    inapplicable = project_gate.StepResult(
        step_id="conditional",
        rules=(),
        status=project_gate.Status.NOT_APPLICABLE,
        required=False,
        diagnostic_id="GATE-NOT-APPLICABLE",
        summary="capability is false",
    )
    unsupported = project_gate.StepResult(
        step_id="platform",
        rules=(),
        status=project_gate.Status.UNSUPPORTED,
        required=True,
        diagnostic_id="GATE-UNSUPPORTED",
        summary="required tool has no Windows implementation",
    )
    not_run = project_gate.StepResult(
        step_id="blocked",
        rules=(),
        status=project_gate.Status.NOT_RUN,
        required=True,
        diagnostic_id="GATE-NOT-RUN",
        summary="declaration failed",
    )

    assert passed.green
    assert inapplicable.green
    assert not unsupported.green
    assert not not_run.green


def test_ambiguous_result_records_are_refused() -> None:
    """A non-pass result without a reason code cannot enter a report."""
    with pytest.raises(ValueError, match="stable diagnostic"):
        project_gate.StepResult(
            step_id="ambiguous",
            rules=(),
            status=project_gate.Status.FAIL,
            required=True,
            diagnostic_id=None,
            summary="failed",
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


@decides("DOC-003")
def test_ordinary_gate_schedules_documentation_presence() -> None:
    """Documentation presence is part of the default gate, not a doc-only job."""
    scheduled = [
        step
        for step in project_gate.DEFAULT_STEPS
        if isinstance(step, project_gate.DisciplineChecksAdapter)
    ]
    discovered = {type(check).__module__.rsplit(".", maxsplit=1)[-1] for check in discover()}

    assert len(scheduled) == 1
    assert "DOC-003" in scheduled[0].rules
    assert "doc_coverage" in discovered

    report = project_gate.run(reference_root(), steps=tuple(scheduled))
    assert report.green
    assert report.outcomes[1].step_id == "discipline-checks"
    assert report.outcomes[1].subjects > 0


@decides("FLOW-012")
def test_report_records_every_non_pass_as_a_deviation(tmp_path: Path) -> None:
    """Failure and prevented work retain distinct reasons in serialized output."""
    report = project_gate.run(tmp_path)
    document = report.as_dict()

    assert document["verdict"] == "fail"
    deviations = cast("list[dict[str, object]]", document["deviations"])
    assert len(deviations) == len(report.outcomes)
    assert deviations[0]["status"] == "fail"
    assert all(item["status"] == "not-run" for item in deviations[1:])
    encoded = json.dumps(document)
    diagnostic = report.outcomes[0].diagnostic_id
    assert diagnostic is not None
    assert diagnostic in encoded
    assert "GATE002_PREREQUISITE" in encoded


def _configured_tool_project(tmp_path: Path) -> Path:
    """Copy the worked reference and add every external-tool table.

    @param tmp_path isolated pytest directory
    @return configured repository root
    """
    root = tmp_path / "project"
    shutil.copytree(reference_root(), root)
    with (root / "pyproject.toml").open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(
            "\n[project]\n"
            "name = 'refpkg'\n"
            "version = '1.0.0'\n"
            "dependencies = []\n"
            "\n[build-system]\n"
            "requires = ['setuptools==84.0.0']\n"
            "build-backend = 'setuptools.build_meta'\n"
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
            "testpaths = ['tests']\n"
            "addopts = ['--disable-socket']\n"
            "timeout = 5\n"
            "timeout_method = 'thread'\n"
            "\n[tool.agent-discipline-gate]\n"
            "import_contracts = 'importlinter.toml'\n"
            "doxyfile = 'Doxyfile'\n"
            "documentation_root = 'docs'\n"
            "artifact_imports = ['refpkg']\n",
        )
        stream.write(
            "\n[tool.agent-discipline-gate.mutation]\n"
            "test_targets = ['tests']\n"
            "mutant_timeout = 5\n"
            "command_timeout = 120\n"
            "maximum_survival = 0.0\n"
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
        (
            project_gate.IMPORT_CONTRACTS_STEP,
            "import contracts: 9 kept, 0 broken\n",
            "src",
        ),
        (project_gate.PYTEST_STEP, "1 passed in 0.01s\n", "tests"),
        (
            project_gate.MUTATION_STEP,
            json.dumps({
                "status": "pass",
                "diagnostic_id": None,
                "summary": "killed",
                "mutants": 3,
                "domains": 1,
            }),
            "--root",
        ),
    ],
    ids=("ruff", "mypy", "pyright", "import-contracts", "pytest", "mutation"),
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
        command: project_gate.PreparedCommand,
        _root: Path,
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
    assert any(str(root) in argument for argument in commands[0].command)
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
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pyright must corroborate that its configured target produced subjects."""
    root = _configured_tool_project(tmp_path)
    monkeypatch.setattr(
        project_gate,
        "_execute",
        lambda _command, _root: project_gate.CommandExecution(
            0,
            '{"summary":{"filesAnalyzed":0,"errorCount":0}}',
            1,
        ),
    )
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "test")

    result = project_gate.run(root, steps=(project_gate.PYRIGHT_STEP,)).outcomes[1]

    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "GATE-PYRIGHT-005_NO_SUBJECT"


def test_pytest_all_skipped_report_is_not_green(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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


def _write_doxyfile(root: Path, source: str = "src") -> None:
    """Write the minimal Doxygen posture the adapter consumes.

    @param root configured repository root
    @param source INPUT value
    """
    (root / "Doxyfile").write_text(
        f"INPUT = {source}\n"
        "FILE_PATTERNS = *.py\n"
        "WARN_AS_ERROR = FAIL_ON_WARNINGS\n"
        "GENERATE_HTML = YES\n",
        encoding="utf-8",
    )


def test_explicit_none_documentation_is_validly_inapplicable(tmp_path: Path) -> None:
    """Only an explicit none declaration can remove the generation step."""
    root = _configured_tool_project(tmp_path)
    project_file = root / "pyproject.toml"
    project_file.write_text(
        project_file.read_text(encoding="utf-8").replace(
            'doc_engine = "doxygen"',
            'doc_engine = "none"',
        ),
        encoding="utf-8",
    )

    result = project_gate.run(
        root,
        steps=(project_gate.DocumentationAdapter(),),
    ).outcomes[1]

    assert result.status is project_gate.Status.NOT_APPLICABLE
    assert result.green
    assert not result.required


def test_missing_doxyfile_is_a_configuration_failure(tmp_path: Path) -> None:
    """A declared Doxygen engine cannot pass without its local configuration."""
    root = _configured_tool_project(tmp_path)

    result = project_gate.run(
        root,
        steps=(project_gate.DocumentationAdapter(),),
    ).outcomes[1]

    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "GATE-DOCUMENTATION-001_CONFIGURATION"
    assert "Doxyfile" in result.summary


def test_doxygen_input_cannot_escape_to_a_parent(tmp_path: Path) -> None:
    """Documentation generation cannot borrow an external repository tree."""
    root = _configured_tool_project(tmp_path)
    _write_doxyfile(root, "../peer")

    result = project_gate.run(
        root,
        steps=(project_gate.DocumentationAdapter(),),
    ).outcomes[1]

    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "GATE-DOCUMENTATION-001_CONFIGURATION"
    assert "escapes" in result.summary


def test_doxygen_pass_requires_generated_source_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean process counts only after output corroborates every Python input."""
    root = _configured_tool_project(tmp_path)
    _write_doxyfile(root)

    def execute(
        _executable: str,
        plan: project_gate.DoxygenPlan,
        _context: project_gate.GateContext,
    ) -> project_gate.DocumentationExecution:
        """Return one generated page per probed source file.

        @param _executable resolved native tool
        @param plan configuration-probed subject set
        @param _context governed repository
        @return successful corroborated generation
        """
        process = project_gate.CommandExecution(0, "", 1)
        return project_gate.DocumentationExecution(process, plan.subjects)

    monkeypatch.setattr(project_gate, "_native_executable", lambda _name: "doxygen")
    monkeypatch.setattr(project_gate, "_native_version", lambda _path: "1.10.0")
    monkeypatch.setattr(project_gate, "_execute_doxygen", execute)

    result = project_gate.run(
        root,
        steps=(project_gate.DocumentationAdapter(),),
    ).outcomes[1]

    assert result.status is project_gate.Status.PASS
    assert result.subjects >= 20
    assert result.tool == "doxygen 1.10.0"


def test_doxygen_zero_output_is_not_green(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doxygen returning zero after filtering every file is a vacuous failure."""
    root = _configured_tool_project(tmp_path)
    _write_doxyfile(root)
    monkeypatch.setattr(project_gate, "_native_executable", lambda _name: "doxygen")
    monkeypatch.setattr(project_gate, "_native_version", lambda _path: "1.10.0")
    monkeypatch.setattr(
        project_gate,
        "_execute_doxygen",
        lambda _executable, _plan, _context: project_gate.DocumentationExecution(
            project_gate.CommandExecution(0, "", 1),
            0,
        ),
    )

    result = project_gate.run(
        root,
        steps=(project_gate.DocumentationAdapter(),),
    ).outcomes[1]

    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "GATE-DOCUMENTATION-004_NO_OUTPUT"


def _write_sphinx_project(root: Path) -> None:
    """Select Sphinx and author the smallest non-vacuous documentation tree.

    @param root configured reference repository
    """
    project_file = root / "pyproject.toml"
    project_file.write_text(
        project_file.read_text(encoding="utf-8").replace(
            'doc_engine = "doxygen"',
            'doc_engine = "sphinx"',
        ),
        encoding="utf-8",
    )
    documentation = root / "docs"
    documentation.mkdir(exist_ok=True)
    (documentation / "conf.py").write_text(
        '"""Configuration consumed by the Sphinx gate proof."""\n\nproject = "Reference"\n',
        encoding="utf-8",
    )
    (documentation / "index.rst").write_text(
        "Reference\n=========\n\nA generated project-gate page.\n",
        encoding="utf-8",
    )


@pytest.mark.timeout(60)
def test_real_sphinx_build_is_supported_and_non_empty(tmp_path: Path) -> None:
    """The packaged Sphinx pin produces HTML through the real adapter.

    @param tmp_path isolated configured reference
    """
    root = _configured_tool_project(tmp_path)
    _write_sphinx_project(root)

    result = project_gate.run(
        root,
        steps=(project_gate.DocumentationAdapter(),),
    ).outcomes[1]

    assert result.status is project_gate.Status.PASS
    assert result.subjects == 1
    assert result.tool == "Sphinx 8.2.3"


def test_sphinx_zero_output_is_not_green(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zero exit without generated HTML remains a failed observation.

    @param tmp_path isolated configured reference
    @param monkeypatch substitutes only the process execution
    """
    root = _configured_tool_project(tmp_path)
    _write_sphinx_project(root)
    monkeypatch.setattr(
        project_gate,
        "_execute",
        lambda _command, _root: project_gate.CommandExecution(0, "", 1),
    )

    result = project_gate.run(
        root,
        steps=(project_gate.DocumentationAdapter(),),
    ).outcomes[1]

    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "GATE-DOCUMENTATION-004_NO_OUTPUT"


def _write_artifacts(output: Path, name: str = "refpkg", version: str = "1.0.0") -> None:
    """Create minimal wheel and sdist archives carrying shared core metadata.

    @param output artifact directory
    @param name core-metadata distribution name
    @param version core-metadata version
    """
    output.mkdir(parents=True, exist_ok=True)
    metadata = f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n\n".encode()
    wheel = output / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr(f"{name}-{version}.dist-info/METADATA", metadata)
    sdist = output / f"{name}-{version}.tar.gz"
    with tarfile.open(sdist, mode="w:gz") as archive:
        member = tarfile.TarInfo(f"{name}-{version}/PKG-INFO")
        member.size = len(metadata)
        archive.addfile(member, io.BytesIO(metadata))


def test_artifact_build_uses_only_an_isolated_repository_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build input excludes the agent bundle and produces content-bound archives."""
    root = _configured_tool_project(tmp_path)
    agent = root / ".agent"
    agent.mkdir()
    (agent / "ambient.txt").write_text("must not build", encoding="utf-8")

    def execute(
        command: project_gate.PreparedCommand,
        _root: Path,
    ) -> project_gate.CommandExecution:
        """Assert isolation and synthesize the declared artifact pair.

        @param command explicit build command
        @param _root governed working directory
        @return successful build observation
        """
        source = Path(command.command[-1])
        assert not (source / ".agent").exists()
        output = Path(command.command[command.command.index("--outdir") + 1])
        _write_artifacts(output)
        return project_gate.CommandExecution(0, "built", 2)

    monkeypatch.setattr(project_gate, "_execute", execute)
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "1.3.0")

    result = project_gate.run(
        root,
        steps=(project_gate.ArtifactBuildAdapter(),),
    ).outcomes[1]

    assert result.status is project_gate.Status.PASS
    wheel_evidence = dict(result.evidence)["wheel"]
    _, separator, digest = wheel_evidence.partition(" sha256:")
    assert separator == " sha256:"
    assert len(digest) == 64
    assert result.subjects > 0


def test_artifact_metadata_mismatch_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A filename cannot conceal a wheel and sdist for another distribution."""
    root = _configured_tool_project(tmp_path)

    def execute(
        command: project_gate.PreparedCommand,
        _root: Path,
    ) -> project_gate.CommandExecution:
        """Write internally consistent but incorrectly identified artifacts.

        @param command explicit build command
        @param _root governed working directory
        @return successful process observation
        """
        output = Path(command.command[command.command.index("--outdir") + 1])
        _write_artifacts(output, name="other")
        return project_gate.CommandExecution(0, "built", 2)

    monkeypatch.setattr(project_gate, "_execute", execute)
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "1.3.0")

    result = project_gate.run(
        root,
        steps=(project_gate.ArtifactBuildAdapter(),),
    ).outcomes[1]

    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "GATE-BUILD-004_ARTIFACT"


def test_unpinned_build_backend_is_rejected(tmp_path: Path) -> None:
    """An isolated build cannot be reproducible when its backend version floats."""
    root = _configured_tool_project(tmp_path)
    project_file = root / "pyproject.toml"
    project_file.write_text(
        project_file.read_text(encoding="utf-8").replace(
            "setuptools==84.0.0",
            "setuptools>=68",
        ),
        encoding="utf-8",
    )

    result = project_gate.run(
        root,
        steps=(project_gate.ArtifactBuildAdapter(),),
    ).outcomes[1]

    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "GATE-BUILD-001_CONFIGURATION"
    assert "exact == version" in result.summary


def test_clean_install_runs_without_a_source_tree_on_pythonpath(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wheel is installed fresh and imports run under Python isolated mode."""
    root = _configured_tool_project(tmp_path)
    commands: list[tuple[str, ...]] = []

    def execute(
        command: project_gate.PreparedCommand,
        _root: Path,
    ) -> project_gate.CommandExecution:
        """Synthesize build output and accept the fresh pip invocation.

        @param command explicit build or install command
        @param _root source-free working directory
        @return successful process observation
        """
        commands.append(command.command)
        if "build" in command.command:
            output = Path(command.command[command.command.index("--outdir") + 1])
            _write_artifacts(output)
        return project_gate.CommandExecution(0, "ok", 2)

    def create(environment: Path) -> Path:
        """Create only the path identity required by the mocked subprocess.

        @param environment fresh environment root
        @return synthetic Windows interpreter
        """
        interpreter = environment / "Scripts" / "python.exe"
        interpreter.parent.mkdir(parents=True)
        interpreter.write_bytes(b"")
        return interpreter

    def execute_timeout(
        command: tuple[str, ...],
        _root: Path,
        _timeout: int,
    ) -> project_gate.CommandExecution:
        """Capture the isolated import command and accept it.

        @param command fresh-interpreter argv
        @param _root source-free working directory
        @param _timeout finite probe budget
        @return successful process observation
        """
        commands.append(command)
        return project_gate.CommandExecution(0, "", 1)

    monkeypatch.setattr(project_gate, "_execute", execute)
    monkeypatch.setattr(project_gate, "_create_venv", create)
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "1.3.0")
    monkeypatch.setattr(project_gate, "_execute_with_timeout", execute_timeout)

    report = project_gate.run(
        root,
        steps=(project_gate.ArtifactBuildAdapter(), project_gate.CleanInstallAdapter()),
    )

    assert report.outcomes[1].status is project_gate.Status.PASS
    assert report.outcomes[2].status is project_gate.Status.PASS
    assert any("-I" in command for command in commands)
    assert all("PYTHONPATH" not in argument for command in commands for argument in command)


def test_installed_probe_checks_exact_input_and_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wheel probe fails when its exact public stdout contract drifts.

    @param tmp_path isolated project root
    @param monkeypatch replaces artifact processes while preserving their bindings
    """
    root = _configured_tool_project(tmp_path)
    project_file = root / "pyproject.toml"
    project_file.write_text(
        project_file.read_text(encoding="utf-8").replace(
            "artifact_imports = ['refpkg']\n",
            "artifact_imports = ['refpkg']\n"
            "artifact_probes = [{ name = 'behavior', command = ['refcmd'], "
            'stdin = "2\\n3\\n", expected_exit = 0, expected_stdout = "sum: 6\\n", '
            "expected_stderr = '', timeout_seconds = 5 }]\n",
        ),
        encoding="utf-8",
    )
    observed_input: list[str | None] = []

    def execute(
        command: project_gate.PreparedCommand,
        _root: Path,
    ) -> project_gate.CommandExecution:
        """Synthesize a wheel and accept its installation.

        @param command explicit build or install command
        @param _root source-free working directory
        @return successful process observation
        """
        if "build" in command.command:
            output = Path(command.command[command.command.index("--outdir") + 1])
            _write_artifacts(output)
        return project_gate.CommandExecution(0, "ok", 1)

    def create(environment: Path) -> Path:
        """Create the synthetic interpreter and installed command paths.

        @param environment fresh environment root
        @return synthetic interpreter
        """
        scripts = environment / "Scripts"
        scripts.mkdir(parents=True)
        interpreter = scripts / "python.exe"
        interpreter.write_bytes(b"")
        (scripts / "refcmd.exe").write_bytes(b"")
        return interpreter

    def execute_timeout(
        command: tuple[str, ...],
        _root: Path,
        _timeout: int,
        stdin: str | None = None,
    ) -> project_gate.CommandExecution:
        """Return exact import output and deliberately wrong command output.

        @param command fresh-environment argv
        @param _root source-free working directory
        @param _timeout finite probe budget
        @param stdin configured public input
        @return captured stream-specific observation
        """
        if "-I" in command:
            return project_gate.CommandExecution(0, "", 1, "", "")
        observed_input.append(stdin)
        return project_gate.CommandExecution(0, "sum: 5\n", 1, "sum: 5\n", "")

    monkeypatch.setattr(project_gate, "_execute", execute)
    monkeypatch.setattr(project_gate, "_create_venv", create)
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "1.3.0")
    monkeypatch.setattr(project_gate, "_execute_with_timeout", execute_timeout)

    report = project_gate.run(
        root,
        steps=(project_gate.ArtifactBuildAdapter(), project_gate.CleanInstallAdapter()),
    )

    assert observed_input == ["2\n3\n"]
    assert report.outcomes[2].status is project_gate.Status.FAIL
    assert report.outcomes[2].diagnostic_id == "GATE-INSTALL-006_OUTPUT"
    assert "stdout" in report.outcomes[2].summary


@pytest.mark.timeout(120)
def test_real_build_and_clean_install_pipeline(tmp_path: Path) -> None:
    """The configured reference really builds, installs, and imports from its wheel."""
    root = _configured_tool_project(tmp_path)

    report = project_gate.run(
        root,
        steps=(project_gate.ArtifactBuildAdapter(), project_gate.CleanInstallAdapter()),
    )

    assert report.outcomes[1].status is project_gate.Status.PASS
    assert report.outcomes[2].status is project_gate.Status.PASS
    assert report.outcomes[2].subjects == 2
