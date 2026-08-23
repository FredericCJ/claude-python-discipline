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
    # Compute passed using project gate.StepResult for later test only pass and valid not
    # Details: applicable are green logic.
    passed = project_gate.StepResult(
        step_id="probe",
        rules=(),
        status=project_gate.Status.PASS,
        required=True,
        diagnostic_id=None,
        summary="ran",
    )
    # Compute inapplicable using project gate.StepResult for later test only pass and valid not
    # Details: applicable are green logic.
    inapplicable = project_gate.StepResult(
        step_id="conditional",
        rules=(),
        status=project_gate.Status.NOT_APPLICABLE,
        required=False,
        diagnostic_id="GATE-NOT-APPLICABLE",
        summary="capability is false",
    )
    # Compute unsupported using project gate.StepResult for later test only pass and valid not
    # Details: applicable are green logic.
    unsupported = project_gate.StepResult(
        step_id="platform",
        rules=(),
        status=project_gate.Status.UNSUPPORTED,
        required=True,
        diagnostic_id="GATE-UNSUPPORTED",
        summary="required tool has no Windows implementation",
    )
    # Compute not run using project gate.StepResult for later test only pass and valid not
    # Details: applicable are green logic.
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
    # Confine the acquired resource to this operation and release it on every exit.
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
    """An exact child root cannot borrow its parent's valid declaration.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    (tmp_path / "pyproject.toml").write_text(
        "[tool.agent-discipline]\nunit='application'\n",
        encoding="utf-8",
    )
    # Compute child using tmp_path / "child" for later test missing local declaration never
    # Details: falls back to parent logic.
    child = tmp_path / "child"
    # Publish the externally visible effect after all required inputs are ready.
    child.mkdir()

    # Hold the decoded checker report mapping for typed summary and diagnostic extraction.
    report = project_gate.run(child)

    assert not report.green
    assert report.unit is None
    assert report.outcomes[0].status is project_gate.Status.FAIL
    assert report.outcomes[1].status is project_gate.Status.NOT_RUN
    assert str(child / "pyproject.toml") in report.outcomes[0].summary


def test_reference_loads_one_declaration_for_every_check() -> None:
    """The conformant reference passes the in-process aggregate check."""
    # Hold the decoded checker report mapping for typed summary and diagnostic extraction.
    report = project_gate.run(
        reference_root(),
        steps=(project_gate.DisciplineChecksAdapter(),),
    )

    assert report.green
    assert report.unit == "application"
    # Capture result as the completed test reference loads one declaration for every check
    # Details: outcome for subsequent validation or publication.
    assert [result.status for result in report.outcomes] == [
        project_gate.Status.PASS,
        project_gate.Status.PASS,
    ]
    assert report.outcomes[1].subjects >= 20
    assert report.outcomes[1].configuration == report.outcomes[0].configuration


@decides("DOC-003")
def test_ordinary_gate_schedules_documentation_presence() -> None:
    """Documentation presence is part of the default gate, not a doc-only job."""
    # Each scheduled element carries one scheduled value produced or consumed by this operation;
    # Details: construction order is preserved.
    scheduled = [
        step
        for step in project_gate.DEFAULT_STEPS
        if isinstance(step, project_gate.DisciplineChecksAdapter)
    ]
    # Collect unique discovered element values; their order is deliberately unordered.
    discovered = {type(check).__module__.rsplit(".", maxsplit=1)[-1] for check in discover()}

    assert len(scheduled) == 1
    assert "DOC-003" in scheduled[0].rules
    assert "doc_coverage" in discovered

    # Hold the decoded checker report mapping for typed summary and diagnostic extraction.
    report = project_gate.run(reference_root(), steps=tuple(scheduled))
    assert report.green
    assert report.outcomes[1].step_id == "discipline-checks"
    assert report.outcomes[1].subjects > 0


@decides("FLOW-012")
def test_report_records_every_non_pass_as_a_deviation(tmp_path: Path) -> None:
    """Failure and prevented work retain distinct reasons in serialized output."""
    # Hold the decoded checker report mapping for typed summary and diagnostic extraction.
    report = project_gate.run(tmp_path)
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    document = report.as_dict()

    assert document["verdict"] == "fail"
    # Compute deviations using cast for later test report records every non pass as a deviation
    # Details: logic.
    deviations = cast("list[dict[str, object]]", document["deviations"])
    assert len(deviations) == len(report.outcomes)
    assert deviations[0]["status"] == "fail"
    # Treat the current item as the candidate element consumed by the enclosing transformation.
    assert all(item["status"] == "not-run" for item in deviations[1:])
    # Compute encoded using json.dumps for later test report records every non pass as a
    # Details: deviation logic.
    encoded = json.dumps(document)
    # Compute diagnostic using report.outcomes[0].diagnostic_id for later test report records
    # Details: every non pass as a deviation logic.
    diagnostic = report.outcomes[0].diagnostic_id
    assert diagnostic is not None
    assert diagnostic in encoded
    assert "GATE002_PREREQUISITE" in encoded


def _configured_tool_project(tmp_path: Path) -> Path:
    """Copy the worked reference and add every external-tool table.

    @param tmp_path isolated pytest directory
    @return configured repository root

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = tmp_path / "project"
    shutil.copytree(reference_root(), root)
    # Compute stream using "utf-8", newline="\n") as stream: for later configured tool project
    # Details: logic.
    # Confine the acquired resource to this operation and release it on every exit.
    with (root / "pyproject.toml").open("a", encoding="utf-8", newline="\n") as stream:
        # Publish the externally visible effect after all required inputs are ready.
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
            "artifact_imports = ['refpkg']\n",
        )
        # Publish the externally visible effect after all required inputs are ready.
        stream.write(
            "\n[tool.agent-discipline-gate.mutation]\n"
            "test_targets = ['tests']\n"
            "mutant_timeout = 5\n"
            "command_timeout = 120\n"
            "maximum_survival = 0.0\n"
        )
    # Compute tests using root / "tests" for later configured tool project logic.
    tests = root / "tests"
    # Publish the externally visible effect after all required inputs are ready.
    tests.mkdir(exist_ok=True)
    # Publish the externally visible effect after all required inputs are ready.
    (tests / "test_smoke.py").write_text(
        '"""A non-vacuous gate fixture."""\n\n'
        "def test_smoke() -> None:\n"
        '    """The fixture executes."""\n'
        "    assert True\n",
        encoding="utf-8",
    )
    # Return configured repository root to the caller.
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
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = _configured_tool_project(tmp_path)
    # Each commands element carries one command value produced or consumed by this operation;
    # Details: construction order is preserved.
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
        # Return successful process observation to the caller.
        return project_gate.CommandExecution(0, output, 1)

    monkeypatch.setattr(project_gate, "_execute", execute)
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "test")

    # Hold the decoded checker report mapping for typed summary and diagnostic extraction.
    report = project_gate.run(root, steps=(adapter,))
    # Capture result as the completed test external adapters bind config and non empty targets
    # Details: outcome for subsequent validation or publication.
    result = report.outcomes[1]

    assert result.status is project_gate.Status.PASS
    assert result.subjects > 0
    assert result.tool == f"{adapter.distribution} test"
    assert result.configuration[0].path == "pyproject.toml"
    # Select argument as the current element from commands[0].command) while test external
    # Details: adapters bind config and non empty targets preserves traversal order.
    assert any(str(root) in argument for argument in commands[0].command)
    assert target in commands[0].command


def test_missing_tool_configuration_is_a_failed_probe(tmp_path: Path) -> None:
    """A missing Ruff table cannot become an unsupported or narrower scan."""
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = tmp_path / "project"
    shutil.copytree(reference_root(), root)

    # Hold the decoded checker report mapping for typed summary and diagnostic extraction.
    report = project_gate.run(root, steps=(project_gate.RUFF_STEP,))
    # Capture result as the completed test missing tool configuration is a failed probe outcome
    # Details: for subsequent validation or publication.
    result = report.outcomes[1]

    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "GATE-RUFF-001_CONFIGURATION"
    assert "tool.ruff" in result.summary


def test_pyright_zero_file_report_is_not_green(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pyright must corroborate that its configured target produced subjects."""
    # Resolve the repository-confined path used by this operation before filesystem access.
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

    # Capture result as the completed test pyright zero file report is not green outcome for
    # Details: subsequent validation or publication.
    result = project_gate.run(root, steps=(project_gate.PYRIGHT_STEP,)).outcomes[1]

    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "GATE-PYRIGHT-005_NO_SUBJECT"


def test_pytest_all_skipped_report_is_not_green(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured suite that executes no passing oracle remains a failure."""
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = _configured_tool_project(tmp_path)
    monkeypatch.setattr(
        project_gate,
        "_execute",
        lambda _command, _root: project_gate.CommandExecution(0, "3 skipped in 0.01s", 1),
    )
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "test")

    # Capture result as the completed test pytest all skipped report is not green outcome for
    # Details: subsequent validation or publication.
    result = project_gate.run(root, steps=(project_gate.PYTEST_STEP,)).outcomes[1]

    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "GATE-PYTEST-004_NO_EXECUTION"


def _write_doxyfile(root: Path, source: str = "src") -> None:
    """Write the minimal Doxygen posture the adapter consumes.

    @param root configured repository root
    @param source INPUT value

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    (root / "Doxyfile").write_text(
        f"INPUT = {source}\n"
        "FILE_PATTERNS = *.py\n"
        "WARN_AS_ERROR = FAIL_ON_WARNINGS\n"
        "GENERATE_HTML = YES\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("engine", ["none", "sphinx"])
def test_legacy_documentation_engine_is_a_migration_failure(
    tmp_path: Path,
    engine: str,
) -> None:
    """A v4 engine choice receives one actionable v5 declaration refusal.

    @param tmp_path isolated configured reference
    @param engine former engine selection

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = _configured_tool_project(tmp_path)
    # Resolve the repository-confined path used by this operation before filesystem access.
    project_file = root / "pyproject.toml"
    # Publish the externally visible effect after all required inputs are ready.
    project_file.write_text(
        project_file.read_text(encoding="utf-8").replace(
            'doc_engine = "doxygen"',
            f'doc_engine = "{engine}"',
        ),
        encoding="utf-8",
    )

    # Hold the decoded checker report mapping for typed summary and diagnostic extraction.
    report = project_gate.run(
        root,
        steps=(project_gate.DocumentationAdapter(),),
    )
    # Capture result as the completed test legacy documentation engine is a migration failure
    # Details: outcome for subsequent validation or publication.
    result = report.outcomes[0]

    assert result.step_id == "declaration"
    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "DISC-PROJECT-021"
    assert "migrate entity comments" in result.summary
    assert report.outcomes[1].status is project_gate.Status.NOT_RUN


def test_missing_doxyfile_is_a_configuration_failure(tmp_path: Path) -> None:
    """A declared Doxygen engine cannot pass without its local configuration."""
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = _configured_tool_project(tmp_path)

    # Capture result as the completed test missing doxyfile is a configuration failure outcome
    # Details: for subsequent validation or publication.
    result = project_gate.run(
        root,
        steps=(project_gate.DocumentationAdapter(),),
    ).outcomes[1]

    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "GATE-DOCUMENTATION-001_CONFIGURATION"
    assert "Doxyfile" in result.summary


def test_doxygen_input_cannot_escape_to_a_parent(tmp_path: Path) -> None:
    """Documentation generation cannot borrow an external repository tree."""
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = _configured_tool_project(tmp_path)
    _write_doxyfile(root, "../peer")

    # Capture result as the completed test doxygen input cannot escape to a parent outcome for
    # Details: subsequent validation or publication.
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
    # Resolve the repository-confined path used by this operation before filesystem access.
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
        # Preserve the external command representation and its observed completion outcome.
        process = project_gate.CommandExecution(0, "", 1)
        # Return successful corroborated generation to the caller.
        return project_gate.DocumentationExecution(process, plan.subjects)

    monkeypatch.setattr(project_gate, "_native_executable", lambda _name: "doxygen")
    monkeypatch.setattr(project_gate, "_native_version", lambda _path: "1.17.0")
    monkeypatch.setattr(project_gate, "_execute_doxygen", execute)

    # Capture result as the completed test doxygen pass requires generated source pages outcome
    # Details: for subsequent validation or publication.
    result = project_gate.run(
        root,
        steps=(project_gate.DocumentationAdapter(),),
    ).outcomes[1]

    assert result.status is project_gate.Status.PASS
    assert result.subjects >= 20
    assert result.tool == "doxygen 1.17.0"


def test_doxygen_zero_output_is_not_green(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doxygen returning zero after filtering every file is a vacuous failure."""
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = _configured_tool_project(tmp_path)
    _write_doxyfile(root)
    monkeypatch.setattr(project_gate, "_native_executable", lambda _name: "doxygen")
    monkeypatch.setattr(project_gate, "_native_version", lambda _path: "1.17.0")
    monkeypatch.setattr(
        project_gate,
        "_execute_doxygen",
        lambda _executable, _plan, _context: project_gate.DocumentationExecution(
            project_gate.CommandExecution(0, "", 1),
            0,
        ),
    )

    # Capture result as the completed test doxygen zero output is not green outcome for
    # Details: subsequent validation or publication.
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

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    output.mkdir(parents=True, exist_ok=True)
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    metadata = f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n\n".encode()
    # Compute wheel using output / f"{name}-{version}-py3-none-any.whl" for later write
    # Details: artifacts logic.
    wheel = output / f"{name}-{version}-py3-none-any.whl"
    # Compute archive using "w") as archive: for later write artifacts logic.
    # Confine the acquired resource to this operation and release it on every exit.
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr(f"{name}-{version}.dist-info/METADATA", metadata)
    # Compute sdist using output / f"{name}-{version}.tar.gz" for later write artifacts logic.
    sdist = output / f"{name}-{version}.tar.gz"
    # Compute archive using "w:gz") as archive: for later write artifacts logic.
    # Confine the acquired resource to this operation and release it on every exit.
    with tarfile.open(sdist, mode="w:gz") as archive:
        # Compute member using tarfile.TarInfo for later write artifacts logic.
        member = tarfile.TarInfo(f"{name}-{version}/PKG-INFO")
        # Update  write artifacts state only after the required source facts are available.
        member.size = len(metadata)
        archive.addfile(member, io.BytesIO(metadata))


def test_artifact_build_uses_only_an_isolated_repository_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build input excludes the agent bundle and produces content-bound archives.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = _configured_tool_project(tmp_path)
    # Compute agent using root / ".agent" for later test artifact build uses only an isolated
    # Details: repository copy logic.
    agent = root / ".agent"
    # Publish the externally visible effect after all required inputs are ready.
    agent.mkdir()
    # Publish the externally visible effect after all required inputs are ready.
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
        # Retain the immutable source representation consumed by subsequent analysis.
        source = Path(command.command[-1])
        assert not (source / ".agent").exists()
        # Combine the checker's captured diagnostic streams without losing emission text.
        output = Path(command.command[command.command.index("--outdir") + 1])
        _write_artifacts(output)
        # Return successful build observation to the caller.
        return project_gate.CommandExecution(0, "built", 2)

    monkeypatch.setattr(project_gate, "_execute", execute)
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "1.3.0")

    # Capture result as the completed test artifact build uses only an isolated repository copy
    # Details: outcome for subsequent validation or publication.
    result = project_gate.run(
        root,
        steps=(project_gate.ArtifactBuildAdapter(),),
    ).outcomes[1]

    assert result.status is project_gate.Status.PASS
    # Compute wheel evidence using dict for later test artifact build uses only an isolated
    # Details: repository copy logic.
    wheel_evidence = dict(result.evidence)["wheel"]
    # Unpack digest, separator using wheel evidence.partition for later test artifact build uses
    # Details: only an isolated repository copy logic.
    _, separator, digest = wheel_evidence.partition(" sha256:")
    assert separator == " sha256:"
    assert len(digest) == 64
    assert result.subjects > 0


def test_artifact_metadata_mismatch_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A filename cannot conceal a wheel and sdist for another distribution."""
    # Resolve the repository-confined path used by this operation before filesystem access.
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
        # Combine the checker's captured diagnostic streams without losing emission text.
        output = Path(command.command[command.command.index("--outdir") + 1])
        _write_artifacts(output, name="other")
        # Return successful process observation to the caller.
        return project_gate.CommandExecution(0, "built", 2)

    monkeypatch.setattr(project_gate, "_execute", execute)
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "1.3.0")

    # Capture result as the completed test artifact metadata mismatch is rejected outcome for
    # Details: subsequent validation or publication.
    result = project_gate.run(
        root,
        steps=(project_gate.ArtifactBuildAdapter(),),
    ).outcomes[1]

    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "GATE-BUILD-004_ARTIFACT"


def test_unpinned_build_backend_is_rejected(tmp_path: Path) -> None:
    """An isolated build cannot be reproducible when its backend version floats.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = _configured_tool_project(tmp_path)
    # Resolve the repository-confined path used by this operation before filesystem access.
    project_file = root / "pyproject.toml"
    # Publish the externally visible effect after all required inputs are ready.
    project_file.write_text(
        project_file.read_text(encoding="utf-8").replace(
            "setuptools==84.0.0",
            "setuptools>=68",
        ),
        encoding="utf-8",
    )

    # Capture result as the completed test unpinned build backend is rejected outcome for
    # Details: subsequent validation or publication.
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
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = _configured_tool_project(tmp_path)
    # Each commands element carries one command value produced or consumed by this operation;
    # Details: construction order is preserved.
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
        # Select the guarded path only after `'build' in command.command` is satisfied.
        if "build" in command.command:
            # Combine the checker's captured diagnostic streams without losing emission text.
            output = Path(command.command[command.command.index("--outdir") + 1])
            _write_artifacts(output)
        # Return successful process observation to the caller.
        return project_gate.CommandExecution(0, "ok", 2)

    def create(environment: Path) -> Path:
        """Create only the path identity required by the mocked subprocess.

        @param environment fresh environment root
        @return synthetic Windows interpreter

        @par Effects
        Creates, replaces, or removes repository artifacts in implementation order.
        """
        # Compute interpreter using environment / "Scripts" / "python.exe" for later create
        # Details: logic.
        interpreter = environment / "Scripts" / "python.exe"
        # Publish the externally visible effect after all required inputs are ready.
        interpreter.parent.mkdir(parents=True)
        # Publish the externally visible effect after all required inputs are ready.
        interpreter.write_bytes(b"")
        # Return synthetic Windows interpreter to the caller.
        return interpreter

    def execute_timeout(
        command: tuple[str, ...],
        _root: Path,
        _timeout: int,
    ) -> project_gate.CommandExecution:
        """Capture the isolated import command and accept it.

        @param command fresh-interpreter argv
            Each arguments element is one process argument string; invocation order is
            preserved.
        @param _root source-free working directory
        @param _timeout finite probe budget
        @return successful process observation
        """
        commands.append(command)
        # Return successful process observation to the caller.
        return project_gate.CommandExecution(0, "", 1)

    monkeypatch.setattr(project_gate, "_execute", execute)
    monkeypatch.setattr(project_gate, "_create_venv", create)
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "1.3.0")
    monkeypatch.setattr(project_gate, "_execute_with_timeout", execute_timeout)

    # Hold the decoded checker report mapping for typed summary and diagnostic extraction.
    report = project_gate.run(
        root,
        steps=(project_gate.ArtifactBuildAdapter(), project_gate.CleanInstallAdapter()),
    )

    assert report.outcomes[1].status is project_gate.Status.PASS
    assert report.outcomes[2].status is project_gate.Status.PASS
    # Preserve the external command representation and its observed completion outcome.
    assert any("-I" in command for command in commands)
    # Preserve the external command representation and its observed completion outcome.
    assert all("PYTHONPATH" not in argument for command in commands for argument in command)


def test_installed_probe_checks_exact_input_and_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wheel probe fails when its exact public stdout contract drifts.

    @param tmp_path isolated project root
    @param monkeypatch replaces artifact processes while preserving their bindings

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = _configured_tool_project(tmp_path)
    # Resolve the repository-confined path used by this operation before filesystem access.
    project_file = root / "pyproject.toml"
    # Publish the externally visible effect after all required inputs are ready.
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
    # Each observed input element carries one observed input value produced or consumed by this
    # Details: operation; construction order is preserved.
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
        # Select the guarded path only after `'build' in command.command` is satisfied.
        if "build" in command.command:
            # Combine the checker's captured diagnostic streams without losing emission text.
            output = Path(command.command[command.command.index("--outdir") + 1])
            _write_artifacts(output)
        # Return successful process observation to the caller.
        return project_gate.CommandExecution(0, "ok", 1)

    def create(environment: Path) -> Path:
        """Create the synthetic interpreter and installed command paths.

        @param environment fresh environment root
        @return synthetic interpreter

        @par Effects
        Creates, replaces, or removes repository artifacts in implementation order.
        """
        # Compute scripts using environment / "Scripts" for later create logic.
        scripts = environment / "Scripts"
        # Publish the externally visible effect after all required inputs are ready.
        scripts.mkdir(parents=True)
        # Compute interpreter using scripts / "python.exe" for later create logic.
        interpreter = scripts / "python.exe"
        # Publish the externally visible effect after all required inputs are ready.
        interpreter.write_bytes(b"")
        # Publish the externally visible effect after all required inputs are ready.
        (scripts / "refcmd.exe").write_bytes(b"")
        # Return synthetic interpreter to the caller.
        return interpreter

    def execute_timeout(
        command: tuple[str, ...],
        _root: Path,
        _timeout: int,
        stdin: str | None = None,
    ) -> project_gate.CommandExecution:
        """Return exact import output and deliberately wrong command output.

        @param command fresh-environment argv
            Each arguments element is one process argument string; invocation order is
            preserved.
        @param _root source-free working directory
        @param _timeout finite probe budget
        @param stdin configured public input
        @return captured stream-specific observation
        """
        # Select the guarded path only after `'-I' in command` is satisfied.
        if "-I" in command:
            # Return captured stream-specific observation to the caller.
            return project_gate.CommandExecution(0, "", 1, "", "")
        observed_input.append(stdin)
        # Return captured stream-specific observation to the caller.
        return project_gate.CommandExecution(0, "sum: 5\n", 1, "sum: 5\n", "")

    monkeypatch.setattr(project_gate, "_execute", execute)
    monkeypatch.setattr(project_gate, "_create_venv", create)
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "1.3.0")
    monkeypatch.setattr(project_gate, "_execute_with_timeout", execute_timeout)

    # Hold the decoded checker report mapping for typed summary and diagnostic extraction.
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
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = _configured_tool_project(tmp_path)

    # Hold the decoded checker report mapping for typed summary and diagnostic extraction.
    report = project_gate.run(
        root,
        steps=(project_gate.ArtifactBuildAdapter(), project_gate.CleanInstallAdapter()),
    )

    assert report.outcomes[1].status is project_gate.Status.PASS
    assert report.outcomes[2].status is project_gate.Status.PASS
    assert report.outcomes[2].subjects == 2
