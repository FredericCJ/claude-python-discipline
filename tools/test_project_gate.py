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
    # Construct the sole executed-success outcome admitted by the aggregate verdict.
    passed = project_gate.StepResult(
        step_id="probe",
        rules=(),
        status=project_gate.Status.PASS,
        required=True,
        diagnostic_id=None,
        summary="ran",
    )
    # Construct a justified optional outcome whose capability makes execution irrelevant.
    inapplicable = project_gate.StepResult(
        step_id="conditional",
        rules=(),
        status=project_gate.Status.NOT_APPLICABLE,
        required=False,
        diagnostic_id="GATE-NOT-APPLICABLE",
        summary="capability is false",
    )
    # Construct required work whose implementation is unavailable on the active platform.
    unsupported = project_gate.StepResult(
        step_id="platform",
        rules=(),
        status=project_gate.Status.UNSUPPORTED,
        required=True,
        diagnostic_id="GATE-UNSUPPORTED",
        summary="required tool has no Windows implementation",
    )
    # Construct required work prevented by an earlier declaration failure.
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
    # Require construction-time refusal before an unclassifiable red result reaches a report.
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
    Writes a valid parent declaration and an empty child repository.
    """
    # Place a tempting valid declaration above the exact root under test.
    (tmp_path / "pyproject.toml").write_text(
        "[tool.agent-discipline]\nunit='application'\n",
        encoding="utf-8",
    )
    # Address the declaration-free child that must not inherit parent configuration.
    child = tmp_path / "child"
    # Materialize the exact governed root without a local project file.
    child.mkdir()

    # Run from the child to expose any accidental ancestor discovery.
    report = project_gate.run(child)

    assert not report.green
    assert report.unit is None
    assert report.outcomes[0].status is project_gate.Status.FAIL
    assert report.outcomes[1].status is project_gate.Status.NOT_RUN
    assert str(child / "pyproject.toml") in report.outcomes[0].summary


def test_reference_loads_one_declaration_for_every_check() -> None:
    """The conformant reference passes the in-process aggregate check."""
    # Limit execution to the in-process checks while retaining normal declaration loading.
    report = project_gate.run(
        reference_root(),
        steps=(project_gate.DisciplineChecksAdapter(),),
    )

    assert report.green
    assert report.unit == "application"
    # Compare each outcome's status in declaration-then-adapter report order.
    assert [result.status for result in report.outcomes] == [
        project_gate.Status.PASS,
        project_gate.Status.PASS,
    ]
    assert report.outcomes[1].subjects >= 20
    assert report.outcomes[1].configuration == report.outcomes[0].configuration


@decides("DOC-003")
def test_ordinary_gate_schedules_documentation_presence() -> None:
    """Documentation presence is part of the default gate, not a doc-only job."""
    # Each scheduled element is a custom-check adapter; default gate order is preserved.
    scheduled = [
        step
        # Each default step is classified by its concrete adapter type.
        for step in project_gate.DEFAULT_STEPS
        if isinstance(step, project_gate.DisciplineChecksAdapter)
    ]
    # Collect unique discovered element values; their order is deliberately unordered.
    discovered = {type(check).__module__.rsplit(".", maxsplit=1)[-1] for check in discover()}

    assert len(scheduled) == 1
    assert "DOC-003" in scheduled[0].rules
    assert "doc_coverage" in discovered

    # Execute only the discovered custom-check adapter against the conformant reference.
    report = project_gate.run(reference_root(), steps=tuple(scheduled))
    assert report.green
    assert report.outcomes[1].step_id == "discipline-checks"
    assert report.outcomes[1].subjects > 0


@decides("FLOW-012")
def test_report_records_every_non_pass_as_a_deviation(tmp_path: Path) -> None:
    """Failure and prevented work retain distinct reasons in serialized output."""
    # Run against an empty root so declaration failure prevents every configured adapter.
    report = project_gate.run(tmp_path)
    document = report.as_dict()

    assert document["verdict"] == "fail"
    # Narrow serialized deviations to their ordered JSON record sequence.
    deviations = cast("list[dict[str, object]]", document["deviations"])
    assert len(deviations) == len(report.outcomes)
    assert deviations[0]["status"] == "fail"
    # Require every post-declaration deviation to retain the prevented-work status.
    assert all(item["status"] == "not-run" for item in deviations[1:])
    # Encode the complete report to verify stable diagnostics survive JSON publication.
    encoded = json.dumps(document)
    # Select the declaration diagnostic whose presence anchors the serialized failure.
    diagnostic = report.outcomes[0].diagnostic_id
    assert diagnostic is not None
    assert diagnostic in encoded
    assert "GATE002_PREREQUISITE" in encoded


def _configured_tool_project(tmp_path: Path) -> Path:
    """Copy the worked reference and add every external-tool table.

    @param tmp_path isolated pytest directory
    @return configured repository root

    @par Effects
    Copies the reference and appends complete external-tool and packaging configuration.
    """
    # Isolate a writable copy of the conformant reference for configuration mutations.
    root = tmp_path / "project"
    # Copy the complete known-good source and doctrine fixture before adding gate tables.
    shutil.copytree(reference_root(), root)
    # Append all project and external-tool declarations without rewriting reference content.
    with (root / "pyproject.toml").open("a", encoding="utf-8", newline="\n") as stream:
        # Add identity, build, lint, type, test, documentation, and install-probe posture.
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
        # Add the mutation-specific execution budget and zero-survivor policy.
        stream.write(
            "\n[tool.agent-discipline-gate.mutation]\n"
            "test_targets = ['tests']\n"
            "mutant_timeout = 5\n"
            "command_timeout = 120\n"
            "maximum_survival = 0.0\n"
        )
    # Address a local test root that makes pytest and mutation target probes non-vacuous.
    tests = root / "tests"
    # Create the target directory if the reference copy does not already contain it.
    tests.mkdir(exist_ok=True)
    # Add one deterministic passing test so configured pytest has executed behavior.
    (tests / "test_smoke.py").write_text(
        '"""A non-vacuous gate fixture."""\n\n'
        "def test_smoke() -> None:\n"
        '    """The fixture executes."""\n'
        "    assert True\n",
        encoding="utf-8",
    )
    # Return the fully configured single-repository fixture.
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
    # Build a complete configured repository for the parameterized adapter.
    root = _configured_tool_project(tmp_path)
    # Each commands element is one prepared invocation in execution order.
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
        # Retain the configuration-probed argv so the test can inspect target confinement.
        commands.append(command)
        # Return the adapter-specific successful output supplied by the parameter row.
        return project_gate.CommandExecution(0, output, 1)

    monkeypatch.setattr(project_gate, "_execute", execute)
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "test")

    # Run only the parameterized adapter after normal declaration loading.
    report = project_gate.run(root, steps=(adapter,))
    result = report.outcomes[1]

    assert result.status is project_gate.Status.PASS
    assert result.subjects > 0
    assert result.tool == f"{adapter.distribution} test"
    assert result.configuration[0].path == "pyproject.toml"
    # Require at least one argv element to bind the tool to this exact repository.
    assert any(str(root) in argument for argument in commands[0].command)
    assert target in commands[0].command


def test_missing_tool_configuration_is_a_failed_probe(tmp_path: Path) -> None:
    """A missing Ruff table cannot become an unsupported or narrower scan."""
    # Copy the reference without the external Ruff table whose absence is under test.
    root = tmp_path / "project"
    # Preserve every other conformant fixture input.
    shutil.copytree(reference_root(), root)

    # Run only Ruff so its configuration refusal is not obscured by later steps.
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
    # Configure a normal pyright repository before substituting only its structured output.
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

    # Capture pyright's adapter result for the zero-subject report.
    result = project_gate.run(root, steps=(project_gate.PYRIGHT_STEP,)).outcomes[1]

    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "GATE-PYRIGHT-005_NO_SUBJECT"


def test_pytest_all_skipped_report_is_not_green(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured suite that executes no passing oracle remains a failure."""
    # Configure a normal pytest repository before substituting an all-skipped summary.
    root = _configured_tool_project(tmp_path)
    monkeypatch.setattr(
        project_gate,
        "_execute",
        lambda _command, _root: project_gate.CommandExecution(0, "3 skipped in 0.01s", 1),
    )
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "test")

    # Capture pytest's adapter result for a clean process with no passing execution.
    result = project_gate.run(root, steps=(project_gate.PYTEST_STEP,)).outcomes[1]

    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "GATE-PYTEST-004_NO_EXECUTION"


def _write_doxyfile(root: Path, source: str = "src") -> None:
    """Write the minimal Doxygen posture the adapter consumes.

    @param root configured repository root
    @param source INPUT value

    @par Effects
    Writes the minimal warning-fatal HTML Doxyfile beneath ``root``.
    """
    # Materialize exactly the four Doxygen assignments consumed by the adapter probe.
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
    Rewrites the fixture's documentation engine selection to a legacy value.
    """
    # Start from a complete v5 project whose sole defect will be the legacy engine value.
    root = _configured_tool_project(tmp_path)
    # Address the exact declaration file carrying the engine field.
    project_file = root / "pyproject.toml"
    # Replace only the supported engine token while preserving all other gate configuration.
    project_file.write_text(
        project_file.read_text(encoding="utf-8").replace(
            'doc_engine = "doxygen"',
            f'doc_engine = "{engine}"',
        ),
        encoding="utf-8",
    )

    # Run declaration plus documentation scheduling to verify migration refusal happens first.
    report = project_gate.run(
        root,
        steps=(project_gate.DocumentationAdapter(),),
    )
    result = report.outcomes[0]

    assert result.step_id == "declaration"
    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "DISC-PROJECT-021"
    assert "migrate entity comments" in result.summary
    assert report.outcomes[1].status is project_gate.Status.NOT_RUN


def test_missing_doxyfile_is_a_configuration_failure(tmp_path: Path) -> None:
    """A declared Doxygen engine cannot pass without its local configuration."""
    # Configure documentation selection while deliberately omitting its declared Doxyfile.
    root = _configured_tool_project(tmp_path)

    # Capture the documentation adapter's field-bound configuration failure.
    result = project_gate.run(
        root,
        steps=(project_gate.DocumentationAdapter(),),
    ).outcomes[1]

    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "GATE-DOCUMENTATION-001_CONFIGURATION"
    assert "Doxyfile" in result.summary


def test_doxygen_input_cannot_escape_to_a_parent(tmp_path: Path) -> None:
    """Documentation generation cannot borrow an external repository tree."""
    # Configure a project whose Doxyfile will point beyond the governed root.
    root = _configured_tool_project(tmp_path)
    _write_doxyfile(root, "../peer")

    # Capture the confinement refusal before any native executable probe.
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
    # Configure the complete local documentation subject and posture.
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
        # Represent a clean Doxygen process independently of its generated-page witness.
        process = project_gate.CommandExecution(0, "", 1)
        # Corroborate every configured Python subject with one synthetic source page.
        return project_gate.DocumentationExecution(process, plan.subjects)

    monkeypatch.setattr(project_gate, "_native_executable", lambda _name: "doxygen")
    monkeypatch.setattr(project_gate, "_native_version", lambda _path: "1.17.0")
    monkeypatch.setattr(project_gate, "_execute_doxygen", execute)

    # Capture the corroborated documentation adapter result.
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
    # Configure the same valid documentation inputs used by the positive case.
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

    # Capture the output-inspection verdict for a clean but vacuous process.
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
    Writes one minimal wheel and one minimal sdist beneath ``output``.
    """
    # Create the isolated build-output directory before opening either archive.
    output.mkdir(parents=True, exist_ok=True)
    # Encode the shared core metadata bytes both artifact readers will inspect.
    metadata = f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n\n".encode()
    # Address the sole wheel filename expected by artifact inventory.
    wheel = output / f"{name}-{version}-py3-none-any.whl"
    # Keep the wheel archive open only while writing its one metadata member.
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr(f"{name}-{version}.dist-info/METADATA", metadata)
    # Address the sole source-distribution filename expected by artifact inventory.
    sdist = output / f"{name}-{version}.tar.gz"
    # Keep the source archive open only while writing its one root PKG-INFO member.
    with tarfile.open(sdist, mode="w:gz") as archive:
        # Describe the in-memory metadata member before setting its exact byte size.
        member = tarfile.TarInfo(f"{name}-{version}/PKG-INFO")
        # Match tar metadata length to the shared encoded core-metadata body.
        member.size = len(metadata)
        # Add the fully described member from its in-memory byte stream.
        archive.addfile(member, io.BytesIO(metadata))


def test_artifact_build_uses_only_an_isolated_repository_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build input excludes the agent bundle and produces content-bound archives.

    @par Effects
    Adds excluded agent content to the configured repository fixture.
    """
    # Configure a normal build subject before adding ambient agent-only content.
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
        # Retain the immutable source representation consumed by subsequent analysis.
        source = Path(command.command[-1])
        assert not (source / ".agent").exists()
        # Combine the checker's captured diagnostic streams without losing emission text.
        output = Path(command.command[command.command.index("--outdir") + 1])
        _write_artifacts(output)
        return project_gate.CommandExecution(0, "built", 2)

    monkeypatch.setattr(project_gate, "_execute", execute)
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "1.3.0")

    # Capture the isolated build and artifact-inspection result.
    result = project_gate.run(
        root,
        steps=(project_gate.ArtifactBuildAdapter(),),
    ).outcomes[1]

    assert result.status is project_gate.Status.PASS
    # Select the content-bound wheel evidence published by the successful adapter.
    wheel_evidence = dict(result.evidence)["wheel"]
    # Split its filename and digest marker to validate a complete SHA-256 identity.
    _, separator, digest = wheel_evidence.partition(" sha256:")
    assert separator == " sha256:"
    assert len(digest) == 64
    assert result.subjects > 0


def test_artifact_metadata_mismatch_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A filename cannot conceal a wheel and sdist for another distribution."""
    # Configure a normal project whose synthetic artifacts will publish another identity.
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
        return project_gate.CommandExecution(0, "built", 2)

    monkeypatch.setattr(project_gate, "_execute", execute)
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "1.3.0")

    # Capture the post-build metadata comparison verdict.
    result = project_gate.run(
        root,
        steps=(project_gate.ArtifactBuildAdapter(),),
    ).outcomes[1]

    assert result.status is project_gate.Status.FAIL
    assert result.diagnostic_id == "GATE-BUILD-004_ARTIFACT"


def test_unpinned_build_backend_is_rejected(tmp_path: Path) -> None:
    """An isolated build cannot be reproducible when its backend version floats.

    @par Effects
    Rewrites the fixture's exact build requirement to a floating range.
    """
    # Start from complete reproducible build configuration.
    root = _configured_tool_project(tmp_path)
    # Address the exact project file carrying build isolation requirements.
    project_file = root / "pyproject.toml"
    # Weaken only the backend pin while preserving the remaining build posture.
    project_file.write_text(
        project_file.read_text(encoding="utf-8").replace(
            "setuptools==84.0.0",
            "setuptools>=68",
        ),
        encoding="utf-8",
    )

    # Capture configuration refusal before any build frontend execution.
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
    # Configure the complete build and clean-install sequence.
    root = _configured_tool_project(tmp_path)
    # Each commands element is one build, install, or probe argv in execution order.
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
        # Retain each prepared build or install argv for later isolation assertions.
        commands.append(command.command)
        # Synthetic build execution alone materializes the artifact pair.
        if "build" in command.command:
            # Combine the checker's captured diagnostic streams without losing emission text.
            output = Path(command.command[command.command.index("--outdir") + 1])
            _write_artifacts(output)
        # Accept both build and pip commands after their observable fixture effects.
        return project_gate.CommandExecution(0, "ok", 2)

    def create(environment: Path) -> Path:
        """Create only the path identity required by the mocked subprocess.

        @param environment fresh environment root
        @return synthetic Windows interpreter

        @par Effects
        Creates an empty synthetic interpreter file beneath ``environment``.
        """
        # Address the Windows venv layout used by this cross-platform mocked fixture.
        interpreter = environment / "Scripts" / "python.exe"
        # Create the scripts directory before materializing its interpreter placeholder.
        interpreter.parent.mkdir(parents=True)
        # Make interpreter existence observable without invoking a real binary.
        interpreter.write_bytes(b"")
        # Return the verified path expected by later probe substitution.
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
        # Retain the isolated interpreter argv for source-path and flag assertions.
        commands.append(command)
        # Accept the synthetic metadata/import probe.
        return project_gate.CommandExecution(0, "", 1)

    monkeypatch.setattr(project_gate, "_execute", execute)
    monkeypatch.setattr(project_gate, "_create_venv", create)
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "1.3.0")
    monkeypatch.setattr(project_gate, "_execute_with_timeout", execute_timeout)

    # Execute build followed by clean installation in their real scheduling order.
    report = project_gate.run(
        root,
        steps=(project_gate.ArtifactBuildAdapter(), project_gate.CleanInstallAdapter()),
    )

    assert report.outcomes[1].status is project_gate.Status.PASS
    assert report.outcomes[2].status is project_gate.Status.PASS
    # Require at least one post-install command to use Python isolated mode.
    assert any("-I" in command for command in commands)
    # Require every argv element to avoid ambient PYTHONPATH injection.
    assert all("PYTHONPATH" not in argument for command in commands for argument in command)


def test_installed_probe_checks_exact_input_and_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wheel probe fails when its exact public stdout contract drifts.

    @param tmp_path isolated project root
    @param monkeypatch replaces artifact processes while preserving their bindings

    @par Effects
    Adds an exact installed-command probe to the configured project fixture.
    """
    # Start from complete build and clean-install configuration.
    root = _configured_tool_project(tmp_path)
    # Address the project file whose gate table receives the behavior probe.
    project_file = root / "pyproject.toml"
    # Insert one stdin/stdout/stderr contract immediately after the import probe declaration.
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
    # Each observed_input element is the exact stdin supplied to a probe in execution order.
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
        # Synthetic build execution alone materializes the artifact pair.
        if "build" in command.command:
            # Combine the checker's captured diagnostic streams without losing emission text.
            output = Path(command.command[command.command.index("--outdir") + 1])
            _write_artifacts(output)
        # Accept both build and pip commands after any required fixture effect.
        return project_gate.CommandExecution(0, "ok", 1)

    def create(environment: Path) -> Path:
        """Create the synthetic interpreter and installed command paths.

        @param environment fresh environment root
        @return synthetic interpreter

        @par Effects
        Creates synthetic interpreter and entry-point files beneath ``environment``.
        """
        # Address the scripts directory used for both interpreter and entry-point resolution.
        scripts = environment / "Scripts"
        # Materialize the venv-local executable directory.
        scripts.mkdir(parents=True)
        # Address the synthetic interpreter selected by clean-install probes.
        interpreter = scripts / "python.exe"
        # Make interpreter existence observable without launching a real binary.
        interpreter.write_bytes(b"")
        # Materialize the installed console entry point named by project configuration.
        (scripts / "refcmd.exe").write_bytes(b"")
        # Return the interpreter path used to anchor all probe executable resolution.
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
        # The isolated metadata/import probe remains successful and silent.
        if "-I" in command:
            # Return exact separated empty streams for the import success case.
            return project_gate.CommandExecution(0, "", 1, "", "")
        # Retain the exact configured stdin passed to the installed command.
        observed_input.append(stdin)
        # Deliberately violate only stdout while keeping status and stderr conformant.
        return project_gate.CommandExecution(0, "sum: 5\n", 1, "sum: 5\n", "")

    monkeypatch.setattr(project_gate, "_execute", execute)
    monkeypatch.setattr(project_gate, "_create_venv", create)
    monkeypatch.setattr(project_gate, "_distribution_version", lambda _name: "1.3.0")
    monkeypatch.setattr(project_gate, "_execute_with_timeout", execute_timeout)

    # Execute the real build/install scheduling with only process boundaries substituted.
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
