"""Run the adopter-facing v4 gate against exactly one repository.

The gate is deliberately a report-producing program rather than a sequence of
shell snippets.  Every step has one of five closed outcomes, records the exact
configuration it consumed, and remains present when an earlier prerequisite
fails.  Absence is therefore ``not-run`` rather than an accidental green line.

This module works from the upstream checkout and from ``.agent/tools`` after
vendoring.  In both cases the governed root is explicit: no operation searches
an ancestor for a declaration or borrows configuration from a sibling checkout.

    python .agent/tools/project_gate.py --root .
    python .agent/tools/project_gate.py --root . --json gate-report.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shlex
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import tarfile
import tempfile
import time
import tomllib
import venv
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default as email_policy
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

## The installed bundle: the repository root upstream and ``.agent`` when vendored.
BUNDLE_ROOT: Final = Path(__file__).resolve().parent.parent

## Custom checks ship below the bundle rather than in the adopter's import package.
ENFORCE_ROOT: Final = BUNDLE_ROOT / "enforce"
if str(ENFORCE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENFORCE_ROOT))

from checks import (  # ruff: ignore[module-import-not-at-top-of-file]
    Finding,
    describe,
    project,
)
from checks.__main__ import discover  # ruff: ignore[module-import-not-at-top-of-file]

## Machine-readable report schema.  Increment for an incompatible JSON change.
REPORT_SCHEMA: Final = 1

## A gate with no steps is vacuous even when declaration loading succeeds.
EXIT_GREEN: Final = 0

## Any fail, unsupported, or not-run result makes the process red.
EXIT_RED: Final = 1


class Status(StrEnum):
    """The exhaustive result vocabulary for one gate step."""

    ## The proposition ran against its declared subject and held.
    PASS = "pass"  # ruff: ignore[hardcoded-password-string] - outcome label
    ## The proposition ran or its configuration probe failed and did not hold.
    FAIL = "fail"
    ## A declared capability makes the proposition irrelevant to this repository.
    NOT_APPLICABLE = "not-applicable"
    ## The proposition is required but has no implementation on this platform.
    UNSUPPORTED = "unsupported"
    ## A prerequisite prevented the proposition from running.
    NOT_RUN = "not-run"


@dataclass(frozen=True, slots=True)
class ConfigurationUse:
    """One configuration file and the exact fields a step consumed."""

    ## Repository-relative POSIX path, never an ancestor path.
    path: str
    ## Full content digest, so a report can be joined to the bytes it judged.
    sha256: str
    ## Dotted field names actually consulted by the step.
    fields: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        """Render this configuration binding for the JSON report.

        @return a JSON-compatible record
        """
        return {"path": self.path, "sha256": self.sha256, "fields": list(self.fields)}


class ResultInvariantError(ValueError):
    """A contradictory gate-result record was constructed."""


@dataclass(frozen=True, slots=True)
class StepResult:
    """One complete and independently interpretable gate outcome."""

    ## Stable identifier used by reports and failure tests.
    step_id: str
    ## Binding rules whose decidable propositions this step contributes to.
    rules: tuple[str, ...]
    ## One member of the closed outcome vocabulary.
    status: Status
    ## Whether the step is required after repository applicability is considered.
    required: bool
    ## Stable diagnostic distinguishing the exact failing or narrowing predicate.
    diagnostic_id: str | None
    ## Human-readable outcome or reason; never inferred from absent output.
    summary: str
    ## Executed argv, empty for an in-process check or a step that did not run.
    command: tuple[str, ...] = ()
    ## Every configuration input consumed by the result.
    configuration: tuple[ConfigurationUse, ...] = ()
    ## Number of source files, tests, contracts, or artifacts actually examined.
    subjects: int = 0
    ## Tool identity observed by the adapter, when an external tool ran.
    tool: str | None = None
    ## Platforms on which the adapter claims support.
    supported_platforms: tuple[str, ...] = ("Windows", "Linux")
    ## Measured wall time, useful for budgets but not part of the verdict.
    duration_ms: int = 0
    ## Bounded diagnostic output retained when a command fails.
    output: str = ""
    ## Content identities or named probes supporting the outcome.
    evidence: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        """Refuse ambiguous result records at their construction boundary.

        @throws ValueError when status, diagnostic, applicability, or subject data conflict
        """
        if not self.step_id or not self.summary.strip():
            raise ResultInvariantError(_EMPTY_RESULT)
        if self.status is Status.PASS and self.diagnostic_id is not None:
            raise ResultInvariantError(_SUCCESS_WITH_DIAGNOSTIC)
        if self.status is not Status.PASS and self.diagnostic_id is None:
            raise ResultInvariantError(_RED_WITHOUT_DIAGNOSTIC)
        if self.status is Status.NOT_APPLICABLE and self.required:
            raise ResultInvariantError(_INAPPLICABLE_REQUIRED)
        if self.subjects < 0 or self.duration_ms < 0:
            raise ResultInvariantError(_NEGATIVE_MEASUREMENT)

    @property
    def green(self) -> bool:
        """Whether this outcome may contribute to a green aggregate verdict.

        @return True only for pass and valid not-applicable outcomes
        """
        return self.status in {Status.PASS, Status.NOT_APPLICABLE}

    def as_dict(self) -> dict[str, object]:
        """Render this outcome without losing absent-versus-empty distinctions.

        @return a JSON-compatible record
        """
        return {
            "id": self.step_id,
            "rules": list(self.rules),
            "status": self.status.value,
            "required": self.required,
            "diagnostic_id": self.diagnostic_id,
            "summary": self.summary,
            "command": list(self.command),
            "configuration": [item.as_dict() for item in self.configuration],
            "subjects": self.subjects,
            "tool": self.tool,
            "supported_platforms": list(self.supported_platforms),
            "duration_ms": self.duration_ms,
            "output": self.output,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class GateContext:
    """Validated repository inputs shared by all post-declaration steps."""

    ## Exact governed root supplied to the CLI.
    root: Path
    ## Ephemeral workspace for caches and later build/install isolation.
    scratch: Path
    ## Required v4 unit kind, narrowed once at the declaration boundary.
    unit: project.UnitKind
    ## Parsed v4 declaration; no permissive ancestor fallback is possible here.
    declaration: project.Declaration
    ## Decoded root project file for configuration probes added by later adapters.
    pyproject: Mapping[str, object]
    ## Content-bound declaration record reused by every consuming step.
    declaration_use: ConfigurationUse


class StepAdapter(Protocol):
    """One in-process or external mechanism adapter."""

    @property
    def step_id(self) -> str:
        """Stable result identity.

        @return report key
        """
        ...

    @property
    def rules(self) -> tuple[str, ...]:
        """Rules contributed by the adapter.

        @return binding rule identifiers
        """
        ...

    def __call__(self, context: GateContext) -> StepResult:
        """Run the mechanism against one already-validated repository.

        @param context exact local repository declaration and configuration
        @return one explicit outcome
        """
        ...


@dataclass(frozen=True, slots=True)
class GateReport:
    """The complete gate verdict, including every deviation from pass."""

    ## Exact governed repository root.
    root: Path
    ## Locally declared unit kind, absent only when declaration loading failed.
    unit: str | None
    ## Runtime platform used to interpret support declarations.
    platform: str
    ## Interpreter identity used by Python-backed tools.
    python: str
    ## Ordered step outcomes, including those prevented from running.
    outcomes: tuple[StepResult, ...]

    @property
    def green(self) -> bool:
        """Whether every required proposition ran or was validly inapplicable.

        @return False for an empty or non-green outcome set
        """
        return bool(self.outcomes) and all(result.green for result in self.outcomes)

    def as_dict(self) -> dict[str, object]:
        """Render the report with a first-class deviation ledger.

        @return a JSON-compatible record
        """
        deviations = [
            {
                "step": result.step_id,
                "status": result.status.value,
                "diagnostic_id": result.diagnostic_id,
                "reason": result.summary,
            }
            for result in self.outcomes
            if result.status is not Status.PASS
        ]
        return {
            "schema_version": REPORT_SCHEMA,
            "root": str(self.root),
            "unit": self.unit,
            "platform": self.platform,
            "python": self.python,
            "verdict": "pass" if self.green else "fail",
            "outcomes": [result.as_dict() for result in self.outcomes],
            "deviations": deviations,
        }


## Stable result-invariant messages are data, not ad hoc exception prose.
_EMPTY_RESULT: Final = "gate results require a step id and non-empty summary"
## Passing means there is no failure diagnostic to act on.
_SUCCESS_WITH_DIAGNOSTIC: Final = "a green step cannot carry a failure diagnostic"
## Silence cannot explain a red or narrowed result.
_RED_WITHOUT_DIAGNOSTIC: Final = "every red result requires a stable diagnostic"
## Inapplicability is what removes a conditional step from the required set.
_INAPPLICABLE_REQUIRED: Final = "a not-applicable step cannot remain required"
## Corrupt measurements must not enter performance or subject-count baselines.
_NEGATIVE_MEASUREMENT: Final = "gate counts and durations cannot be negative"
## Stable declaration diagnostic used when a permissive object reaches this v4 boundary.
_MISSING_UNIT_CODE: Final = "DISC-PROJECT-002"
## Remediation detail paired with ``_MISSING_UNIT_CODE``.
_MISSING_UNIT_DETAIL: Final = "unit is required for the v4 project gate"


def _digest(path: Path) -> str:
    """Full SHA-256 for a configuration input.

    @param path local configuration file
    @return lowercase hexadecimal digest
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _project_use(root: Path) -> ConfigurationUse:
    """Bind declaration loading to the project file at the exact root.

    @param root governed repository root
    @return configuration record for the v4 declaration
    """
    path = root / "pyproject.toml"
    return ConfigurationUse(
        path="pyproject.toml",
        sha256=_digest(path),
        fields=(
            "tool.agent-discipline.unit",
            "tool.agent-discipline.source_roots",
            "tool.agent-discipline.architecture",
            "tool.agent-discipline.contract_conformance",
            "tool.agent-discipline.operational_model",
            "tool.agent-discipline.security_model",
            "tool.agent-discipline.adversarial_review",
            "tool.agent-discipline.doc_engine",
            "tool.agent-discipline.capabilities",
            "tool.agent-discipline.roles",
            "tool.agent-discipline.foreign_dependencies",
        ),
    )


def _required_unit(declaration: project.Declaration, source: Path) -> project.UnitKind:
    """Narrow the permissive direct-check declaration to the v4 gate contract.

    @param declaration parsed repository declaration
    @param source exact project file
    @return required unit kind
    @throws DeclarationError when a fallback declaration has no unit
    """
    if declaration.unit is None:
        raise project.DeclarationError(_MISSING_UNIT_CODE, source, _MISSING_UNIT_DETAIL)
    return declaration.unit


def _load_context(root: Path, scratch: Path) -> tuple[StepResult, GateContext | None]:
    """Load one exact-root declaration and expose its content binding.

    @param root governed repository root
    @param scratch ephemeral gate workspace
    @return declaration outcome and context, or no context after refusal
    """
    started = time.perf_counter()
    source = root / "pyproject.toml"
    try:
        declaration = describe(root, source)
        declared_unit = _required_unit(declaration, source)
        document = cast(
            "Mapping[str, object]",
            tomllib.loads(source.read_text(encoding="utf-8")),
        )
        use = _project_use(root)
    except (OSError, project.DeclarationError, ValueError) as problem:
        duration = round((time.perf_counter() - started) * 1000)
        diagnostic = getattr(problem, "diagnostic_id", "GATE001_DECLARATION")
        result = StepResult(
            step_id="declaration",
            rules=("DOC-014", "FLOW-006"),
            status=Status.FAIL,
            required=True,
            diagnostic_id=str(diagnostic),
            summary=f"exact-root v4 declaration refused: {problem}",
            duration_ms=duration,
        )
        return result, None

    duration = round((time.perf_counter() - started) * 1000)
    result = StepResult(
        step_id="declaration",
        rules=("DOC-014", "FLOW-006"),
        status=Status.PASS,
        required=True,
        diagnostic_id=None,
        summary=f"loaded {source} for one {declared_unit.value} repository",
        configuration=(use,),
        subjects=1,
        tool="agent-discipline declaration schema v4",
        duration_ms=duration,
    )
    return result, GateContext(root, scratch, declared_unit, declaration, document, use)


def _bounded_output(findings: Sequence[Finding]) -> str:
    """Retain actionable custom-check output without unbounded report growth.

    @param findings check findings in discovery order
    @return at most the first fifty rendered findings
    """
    rendered = [finding.render() for finding in findings[:50]]
    if len(findings) > len(rendered):
        rendered.append(f"... {len(findings) - len(rendered)} additional finding(s)")
    return "\n".join(rendered)


def _run_discipline_checks(context: GateContext) -> StepResult:
    """Run every shipped check with the same explicit declaration instance.

    @param context exact repository declaration and bounded source roots
    @return pass over a non-empty subject or the emitted findings
    """
    started = time.perf_counter()
    paths = list(context.declaration.source_paths())
    checks = discover()
    findings: list[Finding] = []
    for check in checks:
        check.declaration = context.declaration
        findings.extend(check.run(paths))
    source_files = sum(
        1
        for path in paths
        for candidate in (path.rglob("*.py") if path.is_dir() else (path,))
        if candidate.is_file()
    )
    duration = round((time.perf_counter() - started) * 1000)
    if source_files == 0:
        return StepResult(
            step_id="discipline-checks",
            rules=("DOC-003", "FLOW-007"),
            status=Status.FAIL,
            required=True,
            diagnostic_id="GATE003_NO_CHECK_SUBJECT",
            summary="the declared source roots contain no Python files",
            configuration=(context.declaration_use,),
            subjects=0,
            tool=f"{len(checks)} shipped checks",
            duration_ms=duration,
        )
    if findings:
        return StepResult(
            step_id="discipline-checks",
            rules=("DOC-003", "FLOW-007"),
            status=Status.FAIL,
            required=True,
            diagnostic_id="GATE003_CHECK_FINDING",
            summary=f"{len(findings)} discipline finding(s) over {source_files} file(s)",
            configuration=(context.declaration_use,),
            subjects=source_files,
            tool=f"{len(checks)} shipped checks",
            duration_ms=duration,
            output=_bounded_output(findings),
        )
    return StepResult(
        step_id="discipline-checks",
        rules=("DOC-003", "FLOW-007"),
        status=Status.PASS,
        required=True,
        diagnostic_id=None,
        summary=f"{len(checks)} discipline checks passed over {source_files} file(s)",
        configuration=(context.declaration_use,),
        subjects=source_files,
        tool=f"{len(checks)} shipped checks",
        duration_ms=duration,
    )


@dataclass(frozen=True, slots=True)
class DisciplineChecksAdapter:
    """Adapter metadata and invocation for all shipped custom checks."""

    ## Stable aggregate result identity.
    step_id: str = "discipline-checks"
    ## Gate-scheduling and proof-of-failure obligations decided by the adapter.
    rules: tuple[str, ...] = ("DOC-003", "FLOW-007")

    def __call__(self, context: GateContext) -> StepResult:
        """Run all custom checks with one shared declaration.

        @param context exact governed repository inputs
        @return aggregate custom-check result
        """
        return _run_discipline_checks(context)


class ConfigurationProbeError(ValueError):
    """A required tool field is missing, malformed, or points outside the root."""

    def __init__(self, field: str, detail: str) -> None:
        """Preserve the exact field for a stable gate diagnostic.

        @param field dotted configuration field
        @param detail actionable refusal reason
        """
        super().__init__(f"{field}: {detail}")
        self.field = field
        self.detail = detail


class CommandExecutionError(RuntimeError):
    """An external mechanism could not complete and produce a verdict."""


@dataclass(frozen=True, slots=True)
class PreparedCommand:
    """Configuration-probed command ready for execution."""

    ## Fully explicit argv; no tool may discover targets or config from ancestors.
    command: tuple[str, ...]
    ## Exact configuration inputs and fields consumed.
    configuration: tuple[ConfigurationUse, ...]
    ## Non-empty source, test, or contract count established before launch.
    subjects: int
    ## Diagnostic emitted when the command reports findings.
    failure_diagnostic: str
    ## Human description of the inspected subject.
    subject_label: str


@dataclass(frozen=True, slots=True)
class CommandExecution:
    """Bounded external-process observation."""

    ## Process exit status.
    returncode: int
    ## Combined stdout and stderr, decoded with replacement.
    output: str
    ## Measured wall time.
    duration_ms: int


@dataclass(frozen=True, slots=True)
class Evaluation:
    """Semantic interpretation of one external process observation."""

    ## None for pass, otherwise the precise failed predicate.
    diagnostic_id: str | None
    ## Standalone outcome explanation.
    summary: str
    ## Bounded details retained only when action is required.
    output: str = ""


@dataclass(frozen=True, slots=True)
class DoxygenPlan:
    """Configuration-probed Doxygen build inputs."""

    ## Local Doxyfile.
    configuration_file: Path
    ## Project table and Doxyfile bindings.
    configuration: tuple[ConfigurationUse, ...]
    ## Declared Python source count expected to generate source pages.
    subjects: int


@dataclass(frozen=True, slots=True)
class DocumentationExecution:
    """Documentation process observation plus generated page count."""

    ## Bounded process observation.
    process: CommandExecution
    ## Generated HTML pages proving the tool did more than parse configuration.
    pages: int


def _probe_error(field: str, detail: str) -> ConfigurationProbeError:
    """Build a typed configuration refusal without raising inside parsing loops.

    @param field dotted configuration field
    @param detail actionable refusal reason
    @return typed refusal
    """
    return ConfigurationProbeError(field, detail)


def _table(document: Mapping[str, object], path: tuple[str, ...]) -> Mapping[str, object]:
    """Read one required nested TOML table.

    @param document decoded project file
    @param path table segments
    @return nested table
    @throws ConfigurationProbeError when a segment is absent or not a table
    """
    current: object = document
    traversed: list[str] = []
    for segment in path:
        traversed.append(segment)
        if not isinstance(current, Mapping) or segment not in current:
            field = ".".join(traversed)
            raise _probe_error(field, "required table is absent")
        current = current[segment]
    if not isinstance(current, Mapping):
        field = ".".join(path)
        raise _probe_error(field, "expected a table")
    return cast("Mapping[str, object]", current)


def _string_list(value: object, field: str) -> tuple[str, ...]:
    """Parse a non-empty path list, accepting mypy's single-string shorthand.

    @param value decoded TOML value
    @param field dotted field name
    @return non-empty strings
    @throws ConfigurationProbeError on an empty or non-string member
    """
    values: object = [value] if isinstance(value, str) else value
    if not isinstance(values, list) or not values:
        raise _probe_error(field, "expected a non-empty string array")
    if not all(isinstance(item, str) and item.strip() for item in values):
        raise _probe_error(field, "every target must be a non-empty string")
    return tuple(cast("list[str]", values))


def _local_targets(
    context: GateContext, values: Sequence[str], field: str,
) -> tuple[tuple[str, ...], int]:
    """Resolve explicit targets while refusing parent, sibling, and empty scans.

    @param context exact governed repository
    @param values repository-relative paths
    @param field dotted configuration field
    @return normalized command targets and distinct Python file count
    @throws ConfigurationProbeError when a target escapes, is absent, or is empty
    """
    normalized: list[str] = []
    files: set[Path] = set()
    for value in values:
        raw = Path(value)
        candidate = (context.root / raw).resolve()
        if raw.is_absolute() or not candidate.is_relative_to(context.root):
            raise _probe_error(field, f"target {value!r} escapes the governed repository")
        if not candidate.exists():
            raise _probe_error(field, f"target {value!r} does not exist")
        normalized.append(candidate.relative_to(context.root).as_posix())
        candidates = candidate.rglob("*.py") if candidate.is_dir() else (candidate,)
        files.update(path.resolve() for path in candidates if path.is_file())
    if not files:
        raise _probe_error(field, "configured targets contain no Python files")
    return tuple(dict.fromkeys(normalized)), len(files)


def _project_configuration(
    context: GateContext, fields: Sequence[str],
) -> ConfigurationUse:
    """Reuse the declaration digest while narrowing the consumed field set.

    @param context exact governed repository
    @param fields tool-specific dotted fields
    @return content-bound configuration record
    """
    return ConfigurationUse(
        path=context.declaration_use.path,
        sha256=context.declaration_use.sha256,
        fields=tuple(fields),
    )


def _relative_configuration_file(
    context: GateContext,
    value: object,
    field: str,
    consumed_fields: Sequence[str],
) -> tuple[Path, ConfigurationUse]:
    """Resolve one configured file without ancestor or sibling discovery.

    @param context exact governed repository
    @param value decoded path value
    @param field dotted field carrying the path
    @param consumed_fields fields read from the target file
    @return absolute file and content-bound use record
    @throws ConfigurationProbeError when the value escapes or is absent
    """
    if not isinstance(value, str) or not value.strip():
        raise _probe_error(field, "expected a non-empty repository-relative file")
    raw = Path(value)
    candidate = (context.root / raw).resolve()
    if raw.is_absolute() or not candidate.is_relative_to(context.root):
        raise _probe_error(field, f"file {value!r} escapes the governed repository")
    if not candidate.is_file():
        raise _probe_error(field, f"file {value!r} does not exist")
    use = ConfigurationUse(
        path=candidate.relative_to(context.root).as_posix(),
        sha256=_digest(candidate),
        fields=tuple(consumed_fields),
    )
    return candidate, use


def _gate_table(context: GateContext) -> Mapping[str, object]:
    """Required project-gate configuration distinct from the doctrine declaration.

    @param context decoded exact-root project file
    @return ``tool.agent-discipline-gate`` table
    """
    return _table(context.pyproject, ("tool", "agent-discipline-gate"))


def _require_value(
    table: Mapping[str, object], key: str, expected: object, field: str,
) -> None:
    """Require one exact configuration posture value.

    @param table containing tool configuration
    @param key local field name
    @param expected required value
    @param field full dotted field name
    @throws ConfigurationProbeError when the value differs
    """
    if table.get(key) != expected:
        raise _probe_error(field, f"expected {expected!r}, found {table.get(key)!r}")


def _prepare_ruff(context: GateContext) -> PreparedCommand:
    """Prove Ruff configuration and targets before constructing its argv.

    @param context exact governed repository
    @return explicit Ruff command
    """
    table = _table(context.pyproject, ("tool", "ruff"))
    targets, subjects = _local_targets(
        context,
        _string_list(table.get("src"), "tool.ruff.src"),
        "tool.ruff.src",
    )
    use = _project_configuration(context, ("tool.ruff", "tool.ruff.src"))
    return PreparedCommand(
        command=(
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(context.root / "pyproject.toml"),
            *targets,
        ),
        configuration=(use,),
        subjects=subjects,
        failure_diagnostic="GATE-RUFF-003_FINDINGS",
        subject_label="Python files",
    )


def _declared_source_targets(context: GateContext) -> tuple[str, ...]:
    """Repository-relative source roots from the validated declaration.

    @param context exact governed repository
    @return non-empty POSIX paths
    """
    return tuple(
        path.resolve().relative_to(context.root).as_posix()
        for path in context.declaration.source_paths()
    )


def _prepare_mypy(context: GateContext) -> PreparedCommand:
    """Prove strict mypy configuration and a non-empty explicit target set.

    @param context exact governed repository
    @return explicit mypy command
    """
    table = _table(context.pyproject, ("tool", "mypy"))
    _require_value(
        table=table,
        key="strict",
        expected=True,
        field="tool.mypy.strict",
    )
    raw_targets = (
        _string_list(table["files"], "tool.mypy.files")
        if "files" in table
        else _declared_source_targets(context)
    )
    targets, subjects = _local_targets(context, raw_targets, "tool.mypy.files")
    use = _project_configuration(
        context,
        ("tool.mypy", "tool.mypy.strict", "tool.mypy.files"),
    )
    return PreparedCommand(
        command=(
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(context.root / "pyproject.toml"),
            "--no-incremental",
            "--cache-dir",
            str(context.scratch / "mypy-cache"),
            *targets,
        ),
        configuration=(use,),
        subjects=subjects,
        failure_diagnostic="GATE-MYPY-003_FINDINGS",
        subject_label="Python files",
    )


def _prepare_pyright(context: GateContext) -> PreparedCommand:
    """Prove strict pyright configuration and a non-empty explicit include set.

    @param context exact governed repository
    @return explicit pyright command requesting machine-readable output
    """
    table = _table(context.pyproject, ("tool", "pyright"))
    _require_value(table, "typeCheckingMode", "strict", "tool.pyright.typeCheckingMode")
    targets, subjects = _local_targets(
        context,
        _string_list(table.get("include"), "tool.pyright.include"),
        "tool.pyright.include",
    )
    use = _project_configuration(
        context,
        ("tool.pyright", "tool.pyright.typeCheckingMode", "tool.pyright.include"),
    )
    return PreparedCommand(
        command=(
            sys.executable,
            "-m",
            "pyright",
            "--project",
            str(context.root / "pyproject.toml"),
            "--outputjson",
            *targets,
        ),
        configuration=(use,),
        subjects=subjects,
        failure_diagnostic="GATE-PYRIGHT-003_FINDINGS",
        subject_label="Python files",
    )


def _prepare_pytest(context: GateContext) -> PreparedCommand:
    """Prove pytest configuration and name every local test root explicitly.

    @param context exact governed repository
    @return explicit pytest command
    """
    table = _table(context.pyproject, ("tool", "pytest", "ini_options"))
    targets, subjects = _local_targets(
        context,
        _string_list(table.get("testpaths"), "tool.pytest.ini_options.testpaths"),
        "tool.pytest.ini_options.testpaths",
    )
    use = _project_configuration(
        context,
        ("tool.pytest.ini_options", "tool.pytest.ini_options.testpaths"),
    )
    return PreparedCommand(
        command=(
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(context.root / "pyproject.toml"),
            "--rootdir",
            str(context.root),
            "--strict-config",
            "--strict-markers",
            "-q",
            *targets,
        ),
        configuration=(use,),
        subjects=subjects,
        failure_diagnostic="GATE-PYTEST-003_FAILURE",
        subject_label="test files",
    )


def _import_root_present(
    context: GateContext, package: str, source_roots: Sequence[str], field: str,
) -> None:
    """Require an import-linter root package to exist under a declared source root.

    @param context exact governed repository
    @param package dotted root-package name
    @param source_roots explicit local import roots
    @param field configuration field carrying the package
    @throws ConfigurationProbeError when no local package matches
    """
    relative = Path(*package.split("."))
    if any(
        ((context.root / source / relative).is_dir()
         or (context.root / source / relative).with_suffix(".py").is_file())
        for source in source_roots
    ):
        return
    raise _probe_error(
        field,
        f"root package {package!r} is absent from declared source roots {source_roots}",
    )


def _prepare_import_contracts(context: GateContext) -> PreparedCommand:
    """Bind import-linter to its declared config, contracts, and source roots.

    @param context exact governed repository
    @return explicit portable wrapper command
    """
    gate = _gate_table(context)
    config, config_use = _relative_configuration_file(
        context,
        gate.get("import_contracts"),
        "tool.agent-discipline-gate.import_contracts",
        ("tool.importlinter.root_packages", "tool.importlinter.contracts"),
    )
    try:
        document = cast(
            "Mapping[str, object]",
            tomllib.loads(config.read_text(encoding="utf-8")),
        )
    except (OSError, tomllib.TOMLDecodeError) as problem:
        raise _probe_error(config_use.path, f"cannot parse TOML: {problem}") from problem
    table = _table(document, ("tool", "importlinter"))
    packages = _string_list(
        table.get("root_packages"),
        "tool.importlinter.root_packages",
    )
    contracts_field = "tool.importlinter.contracts"
    contracts = table.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        raise _probe_error(
            contracts_field,
            "expected one or more contract tables",
        )
    if not all(isinstance(contract, Mapping) for contract in contracts):
        raise _probe_error(contracts_field, "every contract must be a table")
    source_roots = _declared_source_targets(context)
    for package in packages:
        _import_root_present(
            context,
            package,
            source_roots,
            "tool.importlinter.root_packages",
        )
    gate_use = _project_configuration(
        context,
        ("tool.agent-discipline-gate.import_contracts", "tool.agent-discipline.source_roots"),
    )
    source_arguments = tuple(
        item
        for source in source_roots
        for item in ("--source-root", source)
    )
    return PreparedCommand(
        command=(
            sys.executable,
            str(BUNDLE_ROOT / "tools" / "import_gate.py"),
            "--root",
            str(context.root),
            "--config",
            config.relative_to(context.root).as_posix(),
            "--minimum",
            str(len(contracts)),
            *source_arguments,
        ),
        configuration=(gate_use, config_use),
        subjects=len(contracts),
        failure_diagnostic="GATE-IMPORT-CONTRACTS-003_BROKEN",
        subject_label="import contracts",
    )


## Doxygen assignments consumed by the gate are deliberately narrow and exact.
_DOXYGEN_ASSIGNMENT: Final = re.compile(
    r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$",
    re.MULTILINE,
)


def _doxygen_values(text: str, key: str, field: str) -> tuple[str, ...]:
    """Read one single-line Doxygen assignment.

    @param text Doxyfile contents
    @param key assignment name
    @param field diagnostic field name
    @return shell-like tokens after the equals sign
    @throws ConfigurationProbeError when absent, repeated, or malformed
    """
    matches = [match.group(2) for match in _DOXYGEN_ASSIGNMENT.finditer(text)
               if match.group(1) == key]
    if len(matches) != 1:
        raise _probe_error(field, f"expected exactly one {key} assignment")
    try:
        values = tuple(shlex.split(matches[0], comments=True, posix=True))
    except ValueError as problem:
        raise _probe_error(field, f"cannot parse {key}: {problem}") from problem
    if not values:
        raise _probe_error(field, f"{key} has no value")
    return values


def _prepare_doxygen(context: GateContext) -> DoxygenPlan:
    """Bind Doxygen to the declared source roots and warning posture.

    @param context exact governed repository
    @return configuration-probed build plan
    """
    gate = _gate_table(context)
    doxyfile, doxyfile_use = _relative_configuration_file(
        context,
        gate.get("doxyfile"),
        "tool.agent-discipline-gate.doxyfile",
        ("INPUT", "FILE_PATTERNS", "WARN_AS_ERROR", "GENERATE_HTML"),
    )
    text = doxyfile.read_text(encoding="utf-8")
    input_field = "Doxyfile.INPUT"
    inputs, subjects = _local_targets(
        context,
        _doxygen_values(text, "INPUT", input_field),
        input_field,
    )
    declared = _declared_source_targets(context)
    if set(inputs) != set(declared):
        raise _probe_error(
            input_field,
            f"expected declared source roots {declared}, found {inputs}",
        )
    patterns_field = "Doxyfile.FILE_PATTERNS"
    patterns = _doxygen_values(text, "FILE_PATTERNS", patterns_field)
    if "*.py" not in patterns:
        raise _probe_error(patterns_field, "*.py is required")
    warning_field = "Doxyfile.WARN_AS_ERROR"
    warnings = _doxygen_values(text, "WARN_AS_ERROR", warning_field)
    if warnings != ("FAIL_ON_WARNINGS",):
        raise _probe_error(warning_field, "expected FAIL_ON_WARNINGS")
    html_field = "Doxyfile.GENERATE_HTML"
    html = _doxygen_values(text, "GENERATE_HTML", html_field)
    if html != ("YES",):
        raise _probe_error(html_field, "expected YES")
    gate_use = _project_configuration(
        context,
        (
            "tool.agent-discipline.doc_engine",
            "tool.agent-discipline.source_roots",
            "tool.agent-discipline-gate.doxyfile",
        ),
    )
    return DoxygenPlan(doxyfile, (gate_use, doxyfile_use), subjects)


def _native_executable(name: str) -> str | None:
    """Resolve one native tool on the active environment path.

    @param name executable basename
    @return absolute or launchable path, or None
    """
    return shutil.which(name)


def _native_version(executable: str) -> str:
    """Obtain a bounded native-tool version string.

    @param executable resolved tool path
    @return first non-empty version line
    @throws CommandExecutionError when the probe fails
    """
    try:
        finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            (executable, "--version"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as problem:
        raise CommandExecutionError(str(problem)) from problem
    if finished.returncode != 0:
        raise CommandExecutionError(_tail(finished.stdout + finished.stderr))
    return _last_line(finished.stdout + finished.stderr)


def _execute_doxygen(
    executable: str, plan: DoxygenPlan, context: GateContext,
) -> DocumentationExecution:
    """Run Doxygen into the ephemeral workspace and count generated source pages.

    @param executable resolved native tool
    @param plan configuration-probed Doxygen inputs
    @param context exact governed repository and scratch directory
    @return process observation and generated page count
    @throws CommandExecutionError when the process cannot complete
    """
    output = context.scratch / "doxygen"
    configuration = (
        plan.configuration_file.read_text(encoding="utf-8")
        + f"\nOUTPUT_DIRECTORY = {output.as_posix()}\n"
    )
    started = time.perf_counter()
    try:
        finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            (executable, "-"),
            cwd=context.root,
            input=configuration,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as problem:
        raise CommandExecutionError(str(problem)) from problem
    duration = round((time.perf_counter() - started) * 1000)
    process = CommandExecution(
        finished.returncode,
        finished.stdout + finished.stderr,
        duration,
    )
    return DocumentationExecution(process, len(list(output.rglob("*_source.html"))))


def _documentation_configuration_failure(
    context: GateContext, rules: tuple[str, ...], problem: ConfigurationProbeError,
) -> StepResult:
    """Render a documentation configuration-load failure.

    @param context exact governed repository
    @param rules documentation generation rules
    @param problem field-specific refusal
    @return red result
    """
    use = _project_configuration(context, (problem.field,))
    return StepResult(
        step_id="documentation",
        rules=rules,
        status=Status.FAIL,
        required=True,
        diagnostic_id="GATE-DOCUMENTATION-001_CONFIGURATION",
        summary=str(problem),
        configuration=(use,),
    )


def _run_doxygen_documentation(
    context: GateContext, rules: tuple[str, ...],
) -> StepResult:
    """Run the configured Doxygen gate with version and output probes.

    @param context exact governed repository
    @param rules documentation generation rules
    @return explicit Doxygen outcome
    """
    try:
        plan = _prepare_doxygen(context)
    except ConfigurationProbeError as problem:
        return _documentation_configuration_failure(context, rules, problem)
    executable = _native_executable("doxygen")
    if executable is None:
        return StepResult(
            step_id="documentation",
            rules=rules,
            status=Status.UNSUPPORTED,
            required=True,
            diagnostic_id="GATE-DOCUMENTATION-002_TOOL",
            summary="doc_engine is doxygen but no doxygen executable is available",
            configuration=plan.configuration,
            subjects=plan.subjects,
            supported_platforms=("Windows", "Linux"),
        )
    version = "unknown"
    try:
        version = _native_version(executable)
        execution = _execute_doxygen(executable, plan, context)
    except CommandExecutionError as problem:
        return StepResult(
            step_id="documentation",
            rules=rules,
            status=Status.FAIL,
            required=True,
            diagnostic_id="GATE-DOCUMENTATION-006_EXECUTION",
            summary=f"doxygen did not complete: {problem}",
            command=(executable, "-"),
            configuration=plan.configuration,
            subjects=plan.subjects,
            tool=f"doxygen {version}",
        )
    process = execution.process
    if process.returncode != 0:
        return StepResult(
            step_id="documentation",
            rules=rules,
            status=Status.FAIL,
            required=True,
            diagnostic_id="GATE-DOCUMENTATION-003_BUILD",
            summary="Doxygen reported warnings or generation failure",
            command=(executable, "-"),
            configuration=plan.configuration,
            subjects=plan.subjects,
            tool=f"doxygen {version}",
            duration_ms=process.duration_ms,
            output=_tail(process.output),
        )
    if execution.pages < plan.subjects:
        return StepResult(
            step_id="documentation",
            rules=rules,
            status=Status.FAIL,
            required=True,
            diagnostic_id="GATE-DOCUMENTATION-004_NO_OUTPUT",
            summary=(
                f"Doxygen generated {execution.pages} source page(s) for "
                f"{plan.subjects} configured Python file(s)"
            ),
            command=(executable, "-"),
            configuration=plan.configuration,
            subjects=plan.subjects,
            tool=f"doxygen {version}",
            duration_ms=process.duration_ms,
            output=_tail(process.output),
        )
    return StepResult(
        step_id="documentation",
        rules=rules,
        status=Status.PASS,
        required=True,
        diagnostic_id=None,
        summary=f"Doxygen generated {execution.pages} source page(s) without warnings",
        command=(executable, "-"),
        configuration=plan.configuration,
        subjects=plan.subjects,
        tool=f"doxygen {version}",
        duration_ms=process.duration_ms,
    )


def _prepare_sphinx(context: GateContext) -> tuple[PreparedCommand, Path]:
    """Bind Sphinx to one local source directory and configuration file.

    @param context exact governed repository
    @return prepared command and ephemeral output directory
    """
    gate = _gate_table(context)
    field = "tool.agent-discipline-gate.documentation_root"
    roots, _python_subjects = _local_targets(
        context,
        _string_list(gate.get("documentation_root"), field),
        field,
    )
    if len(roots) != 1:
        raise _probe_error(field, "Sphinx requires exactly one documentation root")
    source = context.root / roots[0]
    config = source / "conf.py"
    if not config.is_file():
        raise _probe_error(field, f"{roots[0]}/conf.py does not exist")
    authored = sum(
        1
        for suffix in ("*.rst", "*.md")
        for path in source.rglob(suffix)
        if path.is_file()
    )
    if authored == 0:
        raise _probe_error(field, "documentation root contains no .rst or .md source")
    output = context.scratch / "sphinx"
    gate_use = _project_configuration(
        context,
        ("tool.agent-discipline.doc_engine", field),
    )
    config_use = ConfigurationUse(
        path=config.relative_to(context.root).as_posix(),
        sha256=_digest(config),
        fields=("Sphinx configuration module",),
    )
    command = PreparedCommand(
        command=(
            sys.executable,
            "-m",
            "sphinx",
            "-W",
            "--keep-going",
            "-b",
            "html",
            roots[0],
            str(output),
        ),
        configuration=(gate_use, config_use),
        subjects=authored,
        failure_diagnostic="GATE-DOCUMENTATION-003_BUILD",
        subject_label="documentation sources",
    )
    return command, output


def _run_sphinx_documentation(
    context: GateContext, rules: tuple[str, ...],
) -> StepResult:
    """Run the configured Sphinx gate and require generated HTML.

    @param context exact governed repository
    @param rules documentation generation rules
    @return explicit Sphinx outcome
    """
    try:
        command, output = _prepare_sphinx(context)
    except ConfigurationProbeError as problem:
        return _documentation_configuration_failure(context, rules, problem)
    try:
        version = _distribution_version("Sphinx")
    except importlib.metadata.PackageNotFoundError:
        return StepResult(
            step_id="documentation",
            rules=rules,
            status=Status.UNSUPPORTED,
            required=True,
            diagnostic_id="GATE-DOCUMENTATION-002_TOOL",
            summary="doc_engine is sphinx but the Sphinx distribution is unavailable",
            command=command.command,
            configuration=command.configuration,
            subjects=command.subjects,
        )
    try:
        execution = _execute(command, context.root)
    except CommandExecutionError as problem:
        return StepResult(
            step_id="documentation",
            rules=rules,
            status=Status.FAIL,
            required=True,
            diagnostic_id="GATE-DOCUMENTATION-006_EXECUTION",
            summary=f"Sphinx did not complete: {problem}",
            command=command.command,
            configuration=command.configuration,
            subjects=command.subjects,
            tool=f"Sphinx {version}",
        )
    pages = len(list(output.rglob("*.html")))
    if execution.returncode != 0 or pages == 0:
        diagnostic = (
            command.failure_diagnostic
            if execution.returncode != 0
            else "GATE-DOCUMENTATION-004_NO_OUTPUT"
        )
        return StepResult(
            step_id="documentation",
            rules=rules,
            status=Status.FAIL,
            required=True,
            diagnostic_id=diagnostic,
            summary=f"Sphinx returned {execution.returncode} and generated {pages} HTML page(s)",
            command=command.command,
            configuration=command.configuration,
            subjects=command.subjects,
            tool=f"Sphinx {version}",
            duration_ms=execution.duration_ms,
            output=_tail(execution.output),
        )
    return StepResult(
        step_id="documentation",
        rules=rules,
        status=Status.PASS,
        required=True,
        diagnostic_id=None,
        summary=f"Sphinx generated {pages} HTML page(s) without warnings",
        command=command.command,
        configuration=command.configuration,
        subjects=command.subjects,
        tool=f"Sphinx {version}",
        duration_ms=execution.duration_ms,
    )


@dataclass(frozen=True, slots=True)
class DocumentationAdapter:
    """Capability-aware adapter for none, Doxygen, and Sphinx projects."""

    ## Stable report identity.
    step_id: str = "documentation"
    ## Doxygen/Sphinx generation predicates named by binding rules.
    rules: tuple[str, ...] = ("DOC-005", "DOC-010", "DOC-011")

    def __call__(self, context: GateContext) -> StepResult:
        """Apply the declared engine without narrowing silently.

        @param context exact governed repository
        @return explicit build, inapplicability, or support outcome
        """
        if context.declaration.doc_engine == "none":
            return StepResult(
                step_id=self.step_id,
                rules=self.rules,
                status=Status.NOT_APPLICABLE,
                required=False,
                diagnostic_id="GATE-DOCUMENTATION-000_NOT_APPLICABLE",
                summary="doc_engine is explicitly none; generated documentation is not required",
                configuration=(context.declaration_use,),
            )
        if platform.system() not in {"Windows", "Linux"}:
            return StepResult(
                step_id=self.step_id,
                rules=self.rules,
                status=Status.UNSUPPORTED,
                required=True,
                diagnostic_id="GATE-DOCUMENTATION-005_PLATFORM",
                summary=f"documentation builds are not release-supported on {platform.system()}",
            )
        if context.declaration.doc_engine == "doxygen":
            return _run_doxygen_documentation(context, self.rules)
        return _run_sphinx_documentation(context, self.rules)


class ArtifactError(ValueError):
    """A build or installed-artifact proof is malformed or inconsistent."""


def _artifact_error(detail: str) -> ArtifactError:
    """Build an artifact refusal from already-localized detail.

    @param detail actionable artifact inconsistency
    @return typed refusal
    """
    return ArtifactError(detail)


@dataclass(frozen=True, slots=True)
class BuildPlan:
    """Isolated source copy and expected distribution identity."""

    ## Scratch copy containing no parent, sibling, VCS, or agent bundle.
    source: Path
    ## Ephemeral output directory.
    artifacts: Path
    ## Declared distribution name.
    name: str
    ## Declared distribution version.
    version: str
    ## Number of repository-owned files copied into isolation.
    subjects: int
    ## Project/build table content binding.
    configuration: tuple[ConfigurationUse, ...]


@dataclass(frozen=True, slots=True)
class BuiltArtifacts:
    """One validated wheel and source distribution."""

    ## Built wheel path.
    wheel: Path
    ## Built source archive path.
    sdist: Path
    ## Canonical distribution identity read from both artifacts.
    name: str
    ## Version read from both artifacts.
    version: str


@dataclass(frozen=True, slots=True)
class ArtifactProbe:
    """One explicitly declared installed entry-point behavior probe."""

    ## Stable human-facing probe name.
    name: str
    ## Venv-local argv; ``{python}`` denotes the fresh interpreter.
    command: tuple[str, ...]
    ## Exact expected process status.
    expected_exit: int
    ## Finite execution budget.
    timeout_seconds: int


## Repository content that cannot influence the delivered artifact and must not be copied.
_ISOLATION_EXCLUDES: Final = frozenset({
    ".agent", ".agents", ".claude", ".git", ".hypothesis", ".import_linter_cache",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".venv", "__pycache__",
    "build", "dist", "node_modules",
})

## Import names accepted by the installed smoke probe.
_IMPORT_NAME: Final = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")

## One exact PEP 508-like build requirement; environment markers remain allowed.
_EXACT_BUILD_REQUIREMENT: Final = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_.,-]+\])?"
    r"==[A-Za-z0-9][A-Za-z0-9_.+!-]*(?:\s*;\s*.+)?$",
)

## Longest installed behavior probe accepted by project configuration.
_MAX_PROBE_TIMEOUT: Final = 300


def _copy_isolated(root: Path, destination: Path) -> int:
    """Copy only one repository's authored inputs into an ephemeral build root.

    @param root exact governed repository
    @param destination absent scratch directory
    @return copied regular-file count
    @throws ArtifactError when a symlink could preserve ambient filesystem reach
    """
    for directory, names, files in os.walk(root):
        names[:] = [name for name in names if name not in _ISOLATION_EXCLUDES]
        current = Path(directory)
        for name in (*names, *files):
            path = current / name
            if path.is_symlink():
                relative = path.relative_to(root).as_posix()
                detail = (
                    f"build isolation refuses symlink {relative!r}; "
                    "materialize or package it"
                )
                raise _artifact_error(detail)
    shutil.copytree(
        root,
        destination,
        ignore=shutil.ignore_patterns(*_ISOLATION_EXCLUDES),
    )
    return sum(1 for path in destination.rglob("*") if path.is_file())


def _project_identity(context: GateContext) -> tuple[str, str]:
    """Read the required PEP 621 distribution identity.

    @param context decoded exact-root project
    @return name and version
    @throws ConfigurationProbeError when either is absent
    """
    table = _table(context.pyproject, ("project",))
    name = table.get("name")
    version = table.get("version")
    name_field = "project.name"
    version_field = "project.version"
    if not isinstance(name, str) or not name.strip():
        raise _probe_error(name_field, "expected a non-empty distribution name")
    if not isinstance(version, str) or not version.strip():
        raise _probe_error(version_field, "expected a static non-empty version")
    return name.strip(), version.strip()


def _validate_build_system(context: GateContext) -> None:
    """Require a named backend and exact isolated-environment requirements.

    @param context decoded exact-root project
    @throws ConfigurationProbeError when backend selection can drift
    """
    table = _table(context.pyproject, ("build-system",))
    backend = table.get("build-backend")
    backend_field = "build-system.build-backend"
    if not isinstance(backend, str) or not backend.strip():
        raise _probe_error(backend_field, "expected a backend module")
    requirements_field = "build-system.requires"
    requirements = _string_list(table.get("requires"), requirements_field)
    unpinned = [
        requirement
        for requirement in requirements
        if _EXACT_BUILD_REQUIREMENT.fullmatch(requirement) is None
    ]
    if unpinned:
        raise _probe_error(
            requirements_field,
            f"every build requirement must use one exact == version; found {unpinned}",
        )


def _prepare_build(context: GateContext) -> tuple[BuildPlan, PreparedCommand]:
    """Probe packaging config and create the repository-only build copy.

    @param context exact governed repository
    @return build plan and explicit PEP 517 command
    """
    name, version = _project_identity(context)
    _validate_build_system(context)
    source = context.scratch / "isolated-source"
    artifacts = context.scratch / "artifacts"
    try:
        subjects = _copy_isolated(context.root, source)
    except ArtifactError as problem:
        build_inputs_field = "repository.build_inputs"
        raise _probe_error(build_inputs_field, str(problem)) from problem
    use = _project_configuration(
        context,
        (
            "project.name",
            "project.version",
            "project.dependencies",
            "build-system.requires",
            "build-system.build-backend",
        ),
    )
    plan = BuildPlan(source, artifacts, name, version, subjects, (use,))
    command = PreparedCommand(
        command=(
            sys.executable,
            "-m",
            "build",
            "--sdist",
            "--wheel",
            "--outdir",
            str(artifacts),
            str(source),
        ),
        configuration=plan.configuration,
        subjects=subjects,
        failure_diagnostic="GATE-BUILD-003_FAILURE",
        subject_label="isolated repository files",
    )
    return plan, command


def _canonical_distribution(name: str) -> str:
    """Normalize distribution punctuation for metadata comparison.

    @param name PEP 503-like distribution name
    @return lowercase name with one hyphen per punctuation run
    """
    return re.sub(r"[-_.]+", "-", name).lower()


def _metadata_identity(content: bytes, source: str) -> tuple[str, str]:
    """Read Name and Version from core metadata bytes.

    @param content METADATA or PKG-INFO bytes
    @param source artifact/member label
    @return distribution name and version
    @throws ArtifactError when required fields are absent
    """
    message = BytesParser(policy=email_policy).parsebytes(content)
    name = message.get("Name")
    version = message.get("Version")
    if not name or not version:
        detail = f"{source} has no complete Name/Version metadata"
        raise _artifact_error(detail)
    return str(name), str(version)


def _wheel_identity(path: Path) -> tuple[str, str]:
    """Read the one wheel core-metadata record without importing the package.

    @param path wheel archive
    @return distribution name and version
    @throws ArtifactError when membership or metadata is malformed
    """
    try:
        with zipfile.ZipFile(path) as archive:
            members = [name for name in archive.namelist()
                       if name.endswith(".dist-info/METADATA")]
            if len(members) != 1:
                detail = f"{path.name} contains {len(members)} METADATA files"
                raise _artifact_error(detail)
            return _metadata_identity(archive.read(members[0]), f"{path.name}:{members[0]}")
    except (OSError, zipfile.BadZipFile, KeyError) as problem:
        detail = f"cannot read wheel {path.name}: {problem}"
        raise _artifact_error(detail) from problem


def _read_sdist_identity(path: Path) -> tuple[str, str]:
    """Read one root PKG-INFO member from an already-openable source archive.

    @param path gzipped tar source archive
    @return distribution name and version
    @throws ArtifactError when membership or metadata is malformed
    """
    with tarfile.open(path, mode="r:gz") as archive:
        members = [
            member
            for member in archive.getmembers()
            if member.isfile()
            and member.name.count("/") == 1
            and member.name.endswith("/PKG-INFO")
        ]
        if len(members) != 1:
            detail = f"{path.name} contains {len(members)} root PKG-INFO files"
            raise _artifact_error(detail)
        stream = archive.extractfile(members[0])
        if stream is None:
            detail = f"cannot read {path.name}:{members[0].name}"
            raise _artifact_error(detail)
        return _metadata_identity(stream.read(), f"{path.name}:{members[0].name}")


def _sdist_identity(path: Path) -> tuple[str, str]:
    """Read source-distribution core metadata without extracting any member.

    @param path gzipped tar source archive
    @return distribution name and version
    @throws ArtifactError when membership or metadata is malformed
    """
    try:
        return _read_sdist_identity(path)
    except (OSError, tarfile.TarError) as problem:
        detail = f"cannot read sdist {path.name}: {problem}"
        raise _artifact_error(detail) from problem


def _validate_artifacts(plan: BuildPlan) -> BuiltArtifacts:
    """Require one wheel and one sdist with the declared shared identity.

    @param plan expected identity and output directory
    @return validated artifact paths and identity
    @throws ArtifactError when count or metadata differs
    """
    wheels = sorted(plan.artifacts.glob("*.whl"))
    sdists = sorted(plan.artifacts.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        detail = (
            f"expected one wheel and one sdist, found {len(wheels)} and {len(sdists)}"
        )
        raise _artifact_error(detail)
    wheel_identity = _wheel_identity(wheels[0])
    sdist_identity = _sdist_identity(sdists[0])
    expected = (_canonical_distribution(plan.name), plan.version)
    observed = (
        (_canonical_distribution(wheel_identity[0]), wheel_identity[1]),
        (_canonical_distribution(sdist_identity[0]), sdist_identity[1]),
    )
    if observed != (expected, expected):
        detail = f"expected artifact identity {expected}, found {observed}"
        raise _artifact_error(detail)
    return BuiltArtifacts(wheels[0], sdists[0], expected[0], expected[1])


@dataclass(frozen=True, slots=True)
class ArtifactBuildAdapter:
    """Build and inspect wheel plus sdist from one isolated repository copy."""

    ## Stable report identity.
    step_id: str = "artifact-build"
    ## Delivered-artifact obligation.
    rules: tuple[str, ...] = ("API-015", "DEP-008")

    def __call__(self, context: GateContext) -> StepResult:
        """Build both formats and bind their metadata to project declaration.

        @param context exact governed repository
        @return explicit build outcome
        """
        try:
            plan, command = _prepare_build(context)
        except ConfigurationProbeError as problem:
            return StepResult(
                step_id=self.step_id,
                rules=self.rules,
                status=Status.FAIL,
                required=True,
                diagnostic_id="GATE-BUILD-001_CONFIGURATION",
                summary=str(problem),
                configuration=(_project_configuration(context, (problem.field,)),),
            )
        try:
            version = _distribution_version("build")
        except importlib.metadata.PackageNotFoundError:
            return StepResult(
                step_id=self.step_id,
                rules=self.rules,
                status=Status.UNSUPPORTED,
                required=True,
                diagnostic_id="GATE-BUILD-002_TOOL",
                summary="required distribution 'build' is not installed",
                command=command.command,
                configuration=command.configuration,
                subjects=command.subjects,
            )
        try:
            execution = _execute(command, context.root)
        except CommandExecutionError as problem:
            return StepResult(
                step_id=self.step_id,
                rules=self.rules,
                status=Status.FAIL,
                required=True,
                diagnostic_id="GATE-BUILD-006_EXECUTION",
                summary=f"build did not complete: {problem}",
                command=command.command,
                configuration=command.configuration,
                subjects=command.subjects,
                tool=f"build {version}",
            )
        if execution.returncode != 0:
            return StepResult(
                step_id=self.step_id,
                rules=self.rules,
                status=Status.FAIL,
                required=True,
                diagnostic_id=command.failure_diagnostic,
                summary="isolated wheel/sdist build failed",
                command=command.command,
                configuration=command.configuration,
                subjects=command.subjects,
                tool=f"build {version}",
                duration_ms=execution.duration_ms,
                output=_tail(execution.output),
            )
        try:
            artifacts = _validate_artifacts(plan)
        except ArtifactError as problem:
            return StepResult(
                step_id=self.step_id,
                rules=self.rules,
                status=Status.FAIL,
                required=True,
                diagnostic_id="GATE-BUILD-004_ARTIFACT",
                summary=str(problem),
                command=command.command,
                configuration=command.configuration,
                subjects=command.subjects,
                tool=f"build {version}",
                duration_ms=execution.duration_ms,
            )
        return StepResult(
            step_id=self.step_id,
            rules=self.rules,
            status=Status.PASS,
            required=True,
            diagnostic_id=None,
            summary=(
                f"built and inspected wheel plus sdist for "
                f"{artifacts.name} {artifacts.version}"
            ),
            command=command.command,
            configuration=command.configuration,
            subjects=command.subjects,
            tool=f"build {version}",
            duration_ms=execution.duration_ms,
            evidence=(
                ("wheel", f"{artifacts.wheel.name} sha256:{_digest(artifacts.wheel)}"),
                ("sdist", f"{artifacts.sdist.name} sha256:{_digest(artifacts.sdist)}"),
            ),
        )


def _parse_artifact_probes(
    context: GateContext,
) -> tuple[tuple[str, ...], tuple[ArtifactProbe, ...]]:
    """Parse installed import and command probes from the project-gate table.

    @param context decoded exact-root project
    @return import names and executable probes
    @throws ConfigurationProbeError when a probe is unsafe or ambiguous
    """
    gate = _gate_table(context)
    import_field = "tool.agent-discipline-gate.artifact_imports"
    imports = _string_list(gate.get("artifact_imports"), import_field)
    invalid = [name for name in imports if _IMPORT_NAME.fullmatch(name) is None]
    if invalid:
        raise _probe_error(import_field, f"invalid import names {invalid}")
    probes_field = "tool.agent-discipline-gate.artifact_probes"
    raw_probes = gate.get("artifact_probes", [])
    if not isinstance(raw_probes, list):
        raise _probe_error(probes_field, "expected an array")
    probes: list[ArtifactProbe] = []
    for index, raw in enumerate(raw_probes):
        field = f"tool.agent-discipline-gate.artifact_probes[{index}]"
        if not isinstance(raw, Mapping):
            raise _probe_error(field, "expected a table")
        unknown = set(raw) - {"name", "command", "expected_exit", "timeout_seconds"}
        if unknown:
            raise _probe_error(field, f"unknown fields {sorted(unknown)}")
        name = raw.get("name")
        command = raw.get("command")
        expected = raw.get("expected_exit", 0)
        timeout = raw.get("timeout_seconds", 10)
        if not isinstance(name, str) or not name.strip():
            raise _probe_error(field, "name must be non-empty text")
        argv = _string_list(command, f"{field}.command")
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise _probe_error(field, "expected_exit must be an integer")
        timeout_valid = (
            isinstance(timeout, int)
            and not isinstance(timeout, bool)
            and 1 <= timeout <= _MAX_PROBE_TIMEOUT
        )
        if not timeout_valid:
            raise _probe_error(
                field,
                f"timeout_seconds must be between 1 and {_MAX_PROBE_TIMEOUT}",
            )
        probes.append(ArtifactProbe(name.strip(), argv, expected, timeout))
    if len({probe.name for probe in probes}) != len(probes):
        raise _probe_error(probes_field, "probe names repeat")
    return imports, tuple(probes)


def _fresh_python(environment: Path) -> Path:
    """Locate the interpreter inside a fresh cross-platform virtual environment.

    @param environment virtual-environment root
    @return interpreter path
    """
    windows = environment / "Scripts" / "python.exe"
    return windows if windows.is_file() else environment / "bin" / "python"


def _create_venv(environment: Path) -> Path:
    """Create a clean pip-bearing environment and return its interpreter.

    @param environment absent scratch directory
    @return fresh interpreter path
    @throws CommandExecutionError when creation is incomplete
    """
    try:
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
    except OSError as problem:
        raise CommandExecutionError(str(problem)) from problem
    interpreter = _fresh_python(environment)
    if not interpreter.is_file():
        detail = f"virtual environment has no interpreter at {interpreter}"
        raise CommandExecutionError(detail)
    return interpreter


def _probe_argv(probe: ArtifactProbe, interpreter: Path) -> tuple[str, ...]:
    """Resolve one probe strictly inside the fresh virtual environment.

    @param probe declared argv and expectation
    @param interpreter fresh environment Python
    @return executable argv
    @throws ConfigurationProbeError when the entry point is absent
    """
    scripts = interpreter.parent
    resolved = [
        str(interpreter) if argument == "{python}" else argument
        for argument in probe.command
    ]
    first = Path(resolved[0])
    if resolved[0] == str(interpreter):
        return tuple(resolved)
    if first.is_absolute() or len(first.parts) != 1:
        raise _probe_error(probe.name, "probe executable must be {python} or a venv entry point")
    candidates = (scripts / first, (scripts / first).with_suffix(".exe"))
    executable = next((path for path in candidates if path.is_file()), None)
    if executable is None:
        raise _probe_error(probe.name, f"installed entry point {first} does not exist")
    return (str(executable), *resolved[1:])


def _execute_with_timeout(
    command: tuple[str, ...], root: Path, timeout: int,
) -> CommandExecution:
    """Execute a declared installed probe with its own finite budget.

    @param command resolved venv-local argv
    @param root source-free working directory
    @param timeout seconds before refusal
    @return process observation
    @throws CommandExecutionError when launch or timeout fails
    """
    prepared = PreparedCommand(command, (), 1, "", "probe")
    started = time.perf_counter()
    try:
        finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            prepared.command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as problem:
        raise CommandExecutionError(str(problem)) from problem
    return CommandExecution(
        finished.returncode,
        finished.stdout + finished.stderr,
        round((time.perf_counter() - started) * 1000),
    )


@dataclass(frozen=True, slots=True)
class InstallPlan:
    """Fresh environment plus declared installed-artifact probes."""

    ## Distribution identity expected after installation.
    name: str
    ## Distribution version expected after installation.
    version: str
    ## Modules that must import under isolated mode.
    imports: tuple[str, ...]
    ## Optional installed console behavior probes.
    probes: tuple[ArtifactProbe, ...]
    ## Fresh environment interpreter.
    interpreter: Path
    ## Explicit wheel-install command.
    install: PreparedCommand


def _prepare_install(
    context: GateContext, step_id: str, rules: tuple[str, ...],
) -> InstallPlan | StepResult:
    """Locate the validated wheel, parse probes, and create the fresh environment.

    @param context exact governed repository
    @param step_id stable gate result identity
    @param rules delivered-artifact rules
    @return install plan or explicit preflight failure
    """
    wheels = sorted((context.scratch / "artifacts").glob("*.whl"))
    if len(wheels) != 1:
        return StepResult(
            step_id=step_id,
            rules=rules,
            status=Status.NOT_RUN,
            required=True,
            diagnostic_id="GATE-INSTALL-000_BUILD_REQUIRED",
            summary=f"expected one validated wheel from artifact-build, found {len(wheels)}",
        )
    try:
        imports, probes = _parse_artifact_probes(context)
        name, version = _project_identity(context)
    except ConfigurationProbeError as problem:
        return StepResult(
            step_id=step_id,
            rules=rules,
            status=Status.FAIL,
            required=True,
            diagnostic_id="GATE-INSTALL-001_CONFIGURATION",
            summary=str(problem),
            configuration=(_project_configuration(context, (problem.field,)),),
        )
    try:
        interpreter = _create_venv(context.scratch / "installed")
    except CommandExecutionError as problem:
        return StepResult(
            step_id=step_id,
            rules=rules,
            status=Status.FAIL,
            required=True,
            diagnostic_id="GATE-INSTALL-002_ENVIRONMENT",
            summary=f"cannot create clean environment: {problem}",
        )
    use = _project_configuration(
        context,
        (
            "project.dependencies",
            "tool.agent-discipline-gate.artifact_imports",
            "tool.agent-discipline-gate.artifact_probes",
        ),
    )
    install = PreparedCommand(
        (
            str(interpreter), "-m", "pip", "install", "--disable-pip-version-check",
            "--no-input", str(wheels[0]),
        ),
        (use,),
        1,
        "GATE-INSTALL-003_INSTALL",
        "wheel",
    )
    return InstallPlan(name, version, imports, probes, interpreter, install)


def _install_wheel(
    context: GateContext, plan: InstallPlan, step_id: str, rules: tuple[str, ...],
) -> CommandExecution | StepResult:
    """Install one wheel and translate process failure into a gate result.

    @param context exact governed repository
    @param plan fresh environment install plan
    @param step_id stable gate result identity
    @param rules delivered-artifact rules
    @return process observation or explicit failure
    """
    try:
        installed = _execute(plan.install, context.scratch)
    except CommandExecutionError as problem:
        return StepResult(
            step_id=step_id,
            rules=rules,
            status=Status.FAIL,
            required=True,
            diagnostic_id="GATE-INSTALL-006_EXECUTION",
            summary=f"pip did not complete: {problem}",
            command=plan.install.command,
            configuration=plan.install.configuration,
        )
    if installed.returncode != 0:
        return StepResult(
            step_id=step_id,
            rules=rules,
            status=Status.FAIL,
            required=True,
            diagnostic_id=plan.install.failure_diagnostic,
            summary="fresh-environment wheel installation failed",
            command=plan.install.command,
            configuration=plan.install.configuration,
            duration_ms=installed.duration_ms,
            output=_tail(installed.output),
        )
    return installed


def _verify_installed_imports(
    context: GateContext,
    plan: InstallPlan,
    installed: CommandExecution,
    step_id: str,
    rules: tuple[str, ...],
) -> int | StepResult:
    """Check metadata and imports under Python isolated mode.

    @param context exact governed repository
    @param plan expected identity and import list
    @param installed successful pip observation
    @param step_id stable gate result identity
    @param rules delivered-artifact rules
    @return accumulated duration or explicit failure
    """
    script = (
        "import importlib, importlib.metadata as metadata; "
        f"assert metadata.version({plan.name!r}) == {plan.version!r}; "
        f"[importlib.import_module(name) for name in {plan.imports!r}]"
    )
    try:
        imported = _execute_with_timeout(
            (str(plan.interpreter), "-I", "-c", script),
            context.scratch,
            60,
        )
    except CommandExecutionError as problem:
        return StepResult(
            step_id=step_id,
            rules=rules,
            status=Status.FAIL,
            required=True,
            diagnostic_id="GATE-INSTALL-004_IMPORT",
            summary=f"installed import probe did not complete: {problem}",
            command=plan.install.command,
            configuration=plan.install.configuration,
        )
    duration = installed.duration_ms + imported.duration_ms
    if imported.returncode != 0:
        return StepResult(
            step_id=step_id,
            rules=rules,
            status=Status.FAIL,
            required=True,
            diagnostic_id="GATE-INSTALL-004_IMPORT",
            summary="installed metadata or import probe failed",
            command=plan.install.command,
            configuration=plan.install.configuration,
            duration_ms=duration,
            output=_tail(imported.output),
        )
    return duration


def _verify_installed_commands(
    context: GateContext,
    plan: InstallPlan,
    duration: int,
    step_id: str,
    rules: tuple[str, ...],
) -> int | StepResult:
    """Run each declared venv-local command with its exact budget and status.

    @param context exact governed repository
    @param plan declared installed probes
    @param duration accumulated install/import duration
    @param step_id stable gate result identity
    @param rules delivered-artifact rules
    @return total duration or first explicit probe failure
    """
    total = duration
    for probe in plan.probes:
        try:
            argv = _probe_argv(probe, plan.interpreter)
            observed = _execute_with_timeout(argv, context.scratch, probe.timeout_seconds)
        except (ConfigurationProbeError, CommandExecutionError) as problem:
            return StepResult(
                step_id=step_id,
                rules=rules,
                status=Status.FAIL,
                required=True,
                diagnostic_id="GATE-INSTALL-005_PROBE",
                summary=f"probe {probe.name!r} could not run: {problem}",
                command=plan.install.command,
                configuration=plan.install.configuration,
                duration_ms=total,
            )
        total += observed.duration_ms
        if observed.returncode != probe.expected_exit:
            return StepResult(
                step_id=step_id,
                rules=rules,
                status=Status.FAIL,
                required=True,
                diagnostic_id="GATE-INSTALL-005_PROBE",
                summary=(
                    f"probe {probe.name!r} returned {observed.returncode}, "
                    f"expected {probe.expected_exit}"
                ),
                command=argv,
                configuration=plan.install.configuration,
                duration_ms=total,
                output=_tail(observed.output),
            )
    return total


@dataclass(frozen=True, slots=True)
class CleanInstallAdapter:
    """Install the built wheel and exercise declared public probes outside source."""

    ## Stable report identity.
    step_id: str = "clean-install"
    ## Delivered-artifact and public-entry obligations.
    rules: tuple[str, ...] = ("API-015", "TEST-019")

    def __call__(self, context: GateContext) -> StepResult:
        """Create a fresh venv, install the wheel, and run local probes.

        @param context exact governed repository and shared scratch space
        @return explicit installation/probe outcome
        """
        prepared = _prepare_install(context, self.step_id, self.rules)
        if isinstance(prepared, StepResult):
            return prepared
        installed = _install_wheel(context, prepared, self.step_id, self.rules)
        if isinstance(installed, StepResult):
            return installed
        imported = _verify_installed_imports(
            context, prepared, installed, self.step_id, self.rules,
        )
        if isinstance(imported, StepResult):
            return imported
        probed = _verify_installed_commands(
            context, prepared, imported, self.step_id, self.rules,
        )
        if isinstance(probed, StepResult):
            return probed
        return StepResult(
            step_id=self.step_id,
            rules=self.rules,
            status=Status.PASS,
            required=True,
            diagnostic_id=None,
            summary=(
                f"installed {prepared.name} {prepared.version}; imported "
                f"{len(prepared.imports)} module(s) and ran "
                f"{len(prepared.probes)} entry-point probe(s)"
            ),
            command=prepared.install.command,
            configuration=prepared.install.configuration,
            subjects=1 + len(prepared.imports) + len(prepared.probes),
            tool="fresh venv pip",
            duration_ms=probed,
            evidence=tuple(
                (f"import[{index}]", value)
                for index, value in enumerate(prepared.imports)
            ) + tuple(
                (f"probe[{index}]", probe.name)
                for index, probe in enumerate(prepared.probes)
            ),
        )


def _execute(command: PreparedCommand, root: Path) -> CommandExecution:
    """Run one fixed argv with bounded time and output capture.

    @param command prepared explicit command
    @param root exact governed working directory
    @return process observation
    @throws CommandExecutionError when the process cannot start or times out
    """
    started = time.perf_counter()
    try:
        finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            command.command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=1800,
        )
    except (OSError, subprocess.TimeoutExpired) as problem:
        raise CommandExecutionError(str(problem)) from problem
    duration = round((time.perf_counter() - started) * 1000)
    return CommandExecution(
        returncode=finished.returncode,
        output=finished.stdout + finished.stderr,
        duration_ms=duration,
    )


def _tail(output: str, maximum: int = 4000) -> str:
    """Bound retained tool output from the actionable end.

    @param output combined process output
    @param maximum maximum retained characters
    @return stripped tail
    """
    return output[-maximum:].strip()


def _last_line(output: str) -> str:
    """Last non-empty status line from a tool.

    @param output combined process output
    @return line or a visible no-output marker
    """
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else "completed with no textual output"


def _distribution_version(name: str) -> str:
    """Observed installed version behind an external mechanism.

    @param name distribution package name
    @return installed version
    @throws PackageNotFoundError when the tool is unavailable
    """
    return importlib.metadata.version(name)


def _ordinary_evaluation(
    execution: CommandExecution, command: PreparedCommand,
) -> Evaluation:
    """Interpret a conventional zero-success tool without hiding its subject count.

    @param execution process observation
    @param command prepared command and diagnostic
    @return pass or tool-finding evaluation
    """
    if execution.returncode != 0:
        return Evaluation(
            command.failure_diagnostic,
            f"tool rejected {command.subjects} {command.subject_label}",
            _tail(execution.output),
        )
    return Evaluation(
        None,
        f"clean over {command.subjects} {command.subject_label}: {_last_line(execution.output)}",
    )


def _pyright_evaluation(
    execution: CommandExecution, command: PreparedCommand,
) -> Evaluation:
    """Require pyright's own report to confirm that it analysed files.

    @param execution process observation
    @param command prepared command and expected subject set
    @return pass, findings, or vacuity failure
    """
    start = execution.output.find("{")
    try:
        report = json.loads(execution.output[start:]) if start >= 0 else None
    except json.JSONDecodeError:
        report = None
    if not isinstance(report, Mapping):
        return Evaluation(
            "GATE-PYRIGHT-004_REPORT",
            "pyright emitted no parseable JSON report",
            _tail(execution.output),
        )
    summary = report.get("summary")
    if not isinstance(summary, Mapping):
        return Evaluation(
            "GATE-PYRIGHT-004_REPORT",
            "pyright report has no summary",
            _tail(execution.output),
        )
    analysed = summary.get("filesAnalyzed")
    errors = summary.get("errorCount")
    if execution.returncode != 0 or errors != 0:
        return Evaluation(
            command.failure_diagnostic,
            f"pyright reported {errors!r} error(s) after analysing {analysed!r} file(s)",
            _tail(execution.output),
        )
    if not isinstance(analysed, int) or analysed <= 0:
        return Evaluation(
            "GATE-PYRIGHT-005_NO_SUBJECT",
            "pyright reported success after analysing no files",
            _tail(execution.output),
        )
    return Evaluation(None, f"pyright analysed {analysed} file(s) with zero errors")


## Pytest's terminal summary carries the number that actually executed.
_PYTEST_PASSED: Final = re.compile(r"(?:^|\s)(\d+) passed(?:,|\s|$)")


def _pytest_evaluation(
    execution: CommandExecution, command: PreparedCommand,
) -> Evaluation:
    """Refuse a zero-test or all-skipped pytest success.

    @param execution process observation
    @param command prepared command and expected test roots
    @return pass, test failure, or vacuity failure
    """
    if execution.returncode != 0:
        return Evaluation(
            command.failure_diagnostic,
            f"pytest failed while evaluating {command.subjects} configured test file(s)",
            _tail(execution.output),
        )
    matches = _PYTEST_PASSED.findall(execution.output)
    passed = int(matches[-1]) if matches else 0
    if passed == 0:
        return Evaluation(
            "GATE-PYTEST-004_NO_EXECUTION",
            "pytest exited zero without reporting any passed test",
            _tail(execution.output),
        )
    return Evaluation(None, f"pytest executed {passed} passing test(s)")


@dataclass(frozen=True, slots=True)
class ConfiguredToolAdapter:
    """One external mechanism with configuration, version, and subject probes."""

    ## Stable report identity.
    step_id: str
    ## Binding rules whose decidable arms use the mechanism.
    rules: tuple[str, ...]
    ## Import-package distribution used to obtain the observed version.
    distribution: str
    ## Tool-specific configuration probe and argv constructor.
    prepare: Callable[[GateContext], PreparedCommand]
    ## Tool-specific process-report interpreter.
    evaluate: Callable[[CommandExecution, PreparedCommand], Evaluation]
    ## Platforms on which this adapter is part of the release gate.
    supported_platforms: tuple[str, ...] = ("Windows", "Linux")

    def _configuration_failure(
        self, context: GateContext, problem: ConfigurationProbeError,
    ) -> StepResult:
        """Render one failed configuration-load probe.

        @param context exact governed repository
        @param problem field-specific refusal
        @return red result
        """
        use = _project_configuration(context, (problem.field,))
        return StepResult(
            step_id=self.step_id,
            rules=self.rules,
            status=Status.FAIL,
            required=True,
            diagnostic_id=f"GATE-{self.step_id.upper()}-001_CONFIGURATION",
            summary=str(problem),
            configuration=(use,),
            supported_platforms=self.supported_platforms,
        )

    def __call__(self, context: GateContext) -> StepResult:
        """Probe, identify, run, and interpret one external tool.

        @param context exact governed repository
        @return explicit tool outcome
        """
        if platform.system() not in self.supported_platforms:
            return StepResult(
                step_id=self.step_id,
                rules=self.rules,
                status=Status.UNSUPPORTED,
                required=True,
                diagnostic_id=f"GATE-{self.step_id.upper()}-002_PLATFORM",
                summary=f"{platform.system()} is not in {self.supported_platforms}",
                supported_platforms=self.supported_platforms,
            )
        try:
            command = self.prepare(context)
        except ConfigurationProbeError as problem:
            return self._configuration_failure(context, problem)
        try:
            version = _distribution_version(self.distribution)
        except importlib.metadata.PackageNotFoundError:
            return StepResult(
                step_id=self.step_id,
                rules=self.rules,
                status=Status.UNSUPPORTED,
                required=True,
                diagnostic_id=f"GATE-{self.step_id.upper()}-002_TOOL",
                summary=f"required distribution {self.distribution!r} is not installed",
                command=command.command,
                configuration=command.configuration,
                subjects=command.subjects,
                supported_platforms=self.supported_platforms,
            )
        try:
            execution = _execute(command, context.root)
        except CommandExecutionError as problem:
            return StepResult(
                step_id=self.step_id,
                rules=self.rules,
                status=Status.FAIL,
                required=True,
                diagnostic_id=f"GATE-{self.step_id.upper()}-006_EXECUTION",
                summary=f"tool did not complete: {problem}",
                command=command.command,
                configuration=command.configuration,
                subjects=command.subjects,
                tool=f"{self.distribution} {version}",
                supported_platforms=self.supported_platforms,
            )
        evaluation = self.evaluate(execution, command)
        return StepResult(
            step_id=self.step_id,
            rules=self.rules,
            status=Status.PASS if evaluation.diagnostic_id is None else Status.FAIL,
            required=True,
            diagnostic_id=evaluation.diagnostic_id,
            summary=evaluation.summary,
            command=command.command,
            configuration=command.configuration,
            subjects=command.subjects,
            tool=f"{self.distribution} {version}",
            supported_platforms=self.supported_platforms,
            duration_ms=execution.duration_ms,
            output=evaluation.output,
        )


## Ruff predicates presently named by binding rules.
RUFF_RULES: Final = (
    "ARCH-016", "DIAG-008", "DIAG-012", "DIAG-015", "DOC-001", "DOC-003",
    "DOC-006", "ERR-008", "ERR-009", "TYPE-003",
)
## Mypy predicates presently named by binding rules.
MYPY_RULES: Final = (
    "ARCH-006", "ERR-002", "ERR-005", "TYPE-001", "TYPE-002", "TYPE-003",
    "TYPE-006", "TYPE-013",
)
## Pyright supplies a deliberately independent strict type oracle.
PYRIGHT_RULES: Final = ("ERR-002", "TYPE-001")
## Pytest execution activates the configured timeout, randomization, and socket controls.
PYTEST_RULES: Final = ("TEST-003", "TEST-017")
## Import-linter predicates presently named by binding rules.
IMPORT_CONTRACT_RULES: Final = (
    "API-004", "ARCH-001", "ARCH-002", "ARCH-003", "DEP-001", "EFCT-001",
    "EFCT-012",
)

## Canonical Ruff adapter.
RUFF_STEP: Final = ConfiguredToolAdapter(
    "ruff", RUFF_RULES, "ruff", _prepare_ruff, _ordinary_evaluation,
)
## Canonical mypy adapter.
MYPY_STEP: Final = ConfiguredToolAdapter(
    "mypy", MYPY_RULES, "mypy", _prepare_mypy, _ordinary_evaluation,
)
## Canonical pyright adapter.
PYRIGHT_STEP: Final = ConfiguredToolAdapter(
    "pyright", PYRIGHT_RULES, "pyright", _prepare_pyright, _pyright_evaluation,
)
## Canonical pytest adapter.
PYTEST_STEP: Final = ConfiguredToolAdapter(
    "pytest", PYTEST_RULES, "pytest", _prepare_pytest, _pytest_evaluation,
)
## Canonical import-linter adapter using the portable API wrapper.
IMPORT_CONTRACTS_STEP: Final = ConfiguredToolAdapter(
    "import-contracts",
    IMPORT_CONTRACT_RULES,
    "import-linter",
    _prepare_import_contracts,
    _ordinary_evaluation,
)


## The adopter-facing gate grows by adding adapters here, never by local wrappers.
DEFAULT_STEPS: Final[tuple[StepAdapter, ...]] = (
    DisciplineChecksAdapter(),
    RUFF_STEP,
    MYPY_STEP,
    PYRIGHT_STEP,
    IMPORT_CONTRACTS_STEP,
    DocumentationAdapter(),
    PYTEST_STEP,
    ArtifactBuildAdapter(),
    CleanInstallAdapter(),
)


def _not_run(adapter: StepAdapter, prerequisite: StepResult) -> StepResult:
    """Preserve an adapter in the report after a prerequisite failed.

    @param adapter step prevented from running
    @param prerequisite earlier red result
    @return explicit not-run result
    """
    return StepResult(
        step_id=adapter.step_id,
        rules=adapter.rules,
        status=Status.NOT_RUN,
        required=True,
        diagnostic_id="GATE002_PREREQUISITE",
        summary=(
            f"not run because {prerequisite.step_id} ended as "
            f"{prerequisite.status.value}: {prerequisite.summary}"
        ),
    )


def run(root: Path, *, steps: Sequence[StepAdapter] = DEFAULT_STEPS) -> GateReport:
    """Run every adapter against exactly ``root`` and retain every outcome.

    @param root governed repository root; no parent discovery is performed
    @param steps injectable ordered adapter set
    @return complete report
    """
    exact_root = root.resolve()
    with tempfile.TemporaryDirectory(prefix="agent-project-gate-") as temporary:
        declaration_result, context = _load_context(exact_root, Path(temporary))
        outcomes = [declaration_result]
        if context is None:
            outcomes.extend(_not_run(adapter, declaration_result) for adapter in steps)
            unit = None
        else:
            outcomes.extend(adapter(context) for adapter in steps)
            unit = context.unit.value
    return GateReport(
        root=exact_root,
        unit=unit,
        platform=platform.system(),
        python=platform.python_version(),
        outcomes=tuple(outcomes),
    )


def _default_root() -> Path:
    """Select the only safe implicit root for this installation shape.

    @return the vendored bundle's parent, or the caller's working directory upstream
    """
    return BUNDLE_ROOT.parent if BUNDLE_ROOT.name == ".agent" else Path.cwd()


def _print_report(report: GateReport) -> None:
    """Print one stable line per outcome and a final verdict.

    @param report complete gate report
    """
    for result in report.outcomes:
        diagnostic = f" {result.diagnostic_id}" if result.diagnostic_id else ""
        print(f"{result.status.value:14s} {result.step_id:24s}{diagnostic} {result.summary}")
        if result.output:
            print(result.output)
    print(f"\nproject gate: {'PASS' if report.green else 'FAIL'}")


def main(argv: list[str] | None = None) -> int:
    """Parse the CLI, run the gate, and optionally persist its JSON report.

    @param argv command-line arguments, or None for ``sys.argv``
    @return zero only when the complete report is green
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=_default_root())
    parser.add_argument("--json", type=Path, help="write the complete report as JSON")
    arguments = parser.parse_args(argv)
    report = run(arguments.root)
    _print_report(report)
    if arguments.json is not None:
        arguments.json.write_text(
            json.dumps(report.as_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return EXIT_GREEN if report.green else EXIT_RED


if __name__ == "__main__":
    raise SystemExit(main())
