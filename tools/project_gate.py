"""Run the adopter-facing v5 gate against exactly one repository.

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
from typing import TYPE_CHECKING, Final, Never, Protocol, cast

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

## The installed bundle: the repository root upstream and ``.agent`` when vendored.
BUNDLE_ROOT: Final = Path(__file__).resolve().parent.parent

## Custom checks ship below the bundle rather than in the adopter's import package.
ENFORCE_ROOT: Final = BUNDLE_ROOT / "enforce"
# Prepend the local tools directory only when import resolution does not already contain it.
if str(ENFORCE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENFORCE_ROOT))

from checks import (  # ruff: ignore[module-import-not-at-top-of-file]
    Finding,
    describe,
    project,
)
from checks.__main__ import discover  # ruff: ignore[module-import-not-at-top-of-file]
from checks.documentation_model import (  # ruff: ignore[module-import-not-at-top-of-file]
    governed_paths,
)

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
    ## Each element names one consumed field; probe traversal order is retained.
    fields: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        """Render this configuration binding for the JSON report.

        @return a JSON-compatible record
        """
        # Preserve schema field order while converting the immutable field tuple to JSON shape.
        return {"path": self.path, "sha256": self.sha256, "fields": list(self.fields)}


class ResultInvariantError(ValueError):
    """A contradictory gate-result record was constructed."""


@dataclass(frozen=True, slots=True)
class StepResult:
    """One complete and independently interpretable gate outcome."""

    ## Stable identifier used by reports and failure tests.
    step_id: str
    ## Binding rules whose decidable propositions this step contributes to.
    ## Each element is a binding-rule identifier in adapter declaration order.
    rules: tuple[str, ...]
    ## One member of the closed outcome vocabulary.
    status: Status
    ## Whether the step is required after repository applicability is considered.
    ## True enables required; false selects its disabled alternative.
    required: bool
    ## Stable diagnostic distinguishing the exact failing or narrowing predicate.
    diagnostic_id: str | None
    ## Human-readable outcome or reason; never inferred from absent output.
    summary: str
    ## Executed argv, empty for an in-process check or a step that did not run.
    ## Each arguments element is one process argument string; invocation order is preserved.
    command: tuple[str, ...] = ()
    ## Every configuration input consumed by the result.
    ## Records retain probe-consumption order; each binds fields to a content digest.
    configuration: tuple[ConfigurationUse, ...] = ()
    ## Number of source files, tests, contracts, or artifacts actually examined.
    subjects: int = 0
    ## Tool identity observed by the adapter, when an external tool ran.
    tool: str | None = None
    ## Platforms on which the adapter claims support.
    ## Each supported platforms element carries one supported platform value produced or
    ## consumed by this operation; construction order is preserved.
    supported_platforms: tuple[str, ...] = ("Windows", "Linux")
    ## Measured wall time, useful for budgets but not part of the verdict.
    duration_ms: int = 0
    ## Bounded diagnostic output retained when a command fails.
    output: str = ""
    ## Content identities or named probes supporting the outcome.
    ## Each pair names an evidence kind and its observed value, in collection order.
    evidence: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        """Refuse ambiguous result records at their construction boundary.

        @throws ValueError when status, diagnostic, applicability, or subject data conflict
        """
        # Require every result to carry the stable step identity and human verdict it publishes.
        if not self.step_id or not self.summary.strip():
            # Reject an unreportable result at construction time.
            raise ResultInvariantError(_EMPTY_RESULT)
        # A passing result must not carry failure-only diagnostic identity.
        if self.status is Status.PASS and self.diagnostic_id is not None:
            # Prevent success and failure evidence from contradicting each other.
            raise ResultInvariantError(_SUCCESS_WITH_DIAGNOSTIC)
        # Every non-passing result needs an actionable stable diagnostic code.
        if self.status is not Status.PASS and self.diagnostic_id is None:
            # Refuse red or inapplicable state that reports cannot classify.
            raise ResultInvariantError(_RED_WITHOUT_DIAGNOSTIC)
        # A required step can pass or fail, but can never be declared inapplicable.
        if self.status is Status.NOT_APPLICABLE and self.required:
            # Protect the gate from silently skipping a required obligation.
            raise ResultInvariantError(_INAPPLICABLE_REQUIRED)
        # Counts and durations are measured quantities and therefore cannot be negative.
        if self.subjects < 0 or self.duration_ms < 0:
            # Reject corrupt measurement evidence before it reaches reports or baselines.
            raise ResultInvariantError(_NEGATIVE_MEASUREMENT)

    @property
    def green(self) -> bool:
        """Whether this outcome may contribute to a green aggregate verdict.

        @return True only for pass and valid not-applicable outcomes
        """
        # Only successful execution or justified irrelevance may keep the aggregate green.
        return self.status in {Status.PASS, Status.NOT_APPLICABLE}

    def as_dict(self) -> dict[str, object]:
        """Render this outcome without losing absent-versus-empty distinctions.

        @return a JSON-compatible record
        """
        # Map each report field to JSON-compatible evidence in stable schema order.
        return {
            "id": self.step_id,
            "rules": list(self.rules),
            "status": self.status.value,
            "required": self.required,
            "diagnostic_id": self.diagnostic_id,
            "summary": self.summary,
            "command": list(self.command),
            # Preserve each configuration-use element in consumption order.
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
    ## Required v5 unit kind, narrowed once at the declaration boundary.
    unit: project.UnitKind
    ## Parsed v5 declaration; no permissive ancestor fallback is possible here.
    declaration: project.Declaration
    ## Decoded root project file for configuration probes added by later adapters.
    ## Treat pyproject as mapping elements whose keys identify fields and values carry their
    ## content; key order is deliberately unused.
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
    ## Each element is one scheduled-step result, retained in execution order.
    outcomes: tuple[StepResult, ...]

    @property
    def green(self) -> bool:
        """Whether every required proposition ran or was validly inapplicable.

        @return False for an empty or non-green outcome set
        """
        # Require at least one outcome and no red result for a green aggregate verdict.
        return bool(self.outcomes) and all(result.green for result in self.outcomes)

    def as_dict(self) -> dict[str, object]:
        """Render the report with a first-class deviation ledger.

        @return a JSON-compatible record
        """
        # Each deviations element is one serialized non-pass outcome; step order is preserved.
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
## Stable declaration diagnostic used when a permissive object reaches this v5 boundary.
_MISSING_UNIT_CODE: Final = "DISC-PROJECT-002"
## Remediation detail paired with ``_MISSING_UNIT_CODE``.
_MISSING_UNIT_DETAIL: Final = "unit is required for the v5 project gate"


def _digest(path: Path) -> str:
    """Full SHA-256 for a configuration input.

    @param path local configuration file
    @return lowercase hexadecimal digest
    """
    # Bind later reports to the complete configuration bytes consumed by the step.
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _project_use(root: Path) -> ConfigurationUse:
    """Bind declaration loading to the project file at the exact root.

    @param root governed repository root
    @return configuration record for the v5 declaration
    """
    # Address only the exact-root declaration; ancestor discovery is forbidden.
    path = root / "pyproject.toml"
    # Publish the declaration digest beside every field the aggregate gate may consume.
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
            "tool.agent-discipline.documentation_model",
            "tool.agent-discipline.capabilities",
            "tool.agent-discipline.roles",
            "tool.agent-discipline.foreign_dependencies",
        ),
    )


def _required_unit(declaration: project.Declaration, source: Path) -> project.UnitKind:
    """Narrow the permissive direct-check declaration to the v5 gate contract.

    @param declaration parsed repository declaration
    @param source exact project file
    @return required unit kind
    @throws DeclarationError when a fallback declaration has no unit
    """
    # A v5 aggregate gate must know whether one application or one component is governed.
    if declaration.unit is None:
        # Translate permissive direct-check fallback into the strict gate declaration diagnostic.
        raise project.DeclarationError(_MISSING_UNIT_CODE, source, _MISSING_UNIT_DETAIL)
    # Return the explicit authored unit kind without inferring repository topology.
    return declaration.unit


def _load_context(root: Path, scratch: Path) -> tuple[StepResult, GateContext | None]:
    """Load one exact-root declaration and expose its content binding.

    @param root governed repository root
    @param scratch ephemeral gate workspace
    @return declaration outcome and context, or no context after refusal
    """
    # Start declaration timing before any filesystem or parser boundary is crossed.
    started = time.perf_counter()
    # Locate the one project declaration whose bytes and schema decide preflight.
    source = root / "pyproject.toml"
    try:
        # Load the strict declaration, unit kind, configuration, and use evidence together.
        declaration = describe(root, source)
        declared_unit = _required_unit(declaration, source)
        document = cast(
            "Mapping[str, object]",
            tomllib.loads(source.read_text(encoding="utf-8")),
        )
        use = _project_use(root)
    except (OSError, project.DeclarationError, ValueError) as problem:
        # Measure refusal time and retain the most specific declaration diagnostic available.
        duration = round((time.perf_counter() - started) * 1000)
        diagnostic = getattr(problem, "diagnostic_id", "GATE001_DECLARATION")
        # Publish one red declaration result while withholding an unusable context.
        result = StepResult(
            step_id="declaration",
            rules=("DOC-014", "FLOW-006"),
            status=Status.FAIL,
            required=True,
            diagnostic_id=str(diagnostic),
            summary=f"exact-root v5 declaration refused: {problem}",
            duration_ms=duration,
        )
        return result, None

    # Measure accepted loading before constructing the shared immutable context.
    duration = round((time.perf_counter() - started) * 1000)
    # Publish declaration success with the exact configuration evidence consumed.
    result = StepResult(
        step_id="declaration",
        rules=("DOC-014", "FLOW-006"),
        status=Status.PASS,
        required=True,
        diagnostic_id=None,
        summary=f"loaded {source} for one {declared_unit.value} repository",
        configuration=(use,),
        subjects=1,
        tool="agent-discipline declaration schema v5",
        duration_ms=duration,
    )
    return result, GateContext(root, scratch, declared_unit, declaration, document, use)


def _bounded_output(findings: Sequence[Finding]) -> str:
    """Retain actionable custom-check output without unbounded report growth.

    @param findings check findings in discovery order
        Each findings element is one emitted diagnostic mapping; checker order is preserved.
    @return at most the first fifty rendered findings
    """
    # Each rendered element is one finding diagnostic; check traversal order is preserved and
    # capped at fifty entries before a truncation marker is appended.
    rendered = [finding.render() for finding in findings[:50]]
    if len(findings) > len(rendered):
        rendered.append(f"... {len(findings) - len(rendered)} additional finding(s)")
    return "\n".join(rendered)


def _run_discipline_checks(context: GateContext) -> StepResult:
    """Run every shipped check with the same explicit declaration instance.

    @param context exact repository declaration and bounded source roots
    @return pass over a non-empty subject or the emitted findings
    """
    # Time the complete discipline-check family as one canonical gate step.
    started = time.perf_counter()
    # Preserve paths element values in deterministic source order.
    paths = list(context.declaration.source_paths())
    checks = discover()
    findings: list[Finding] = []
    for check in checks:
        # Inject the validated declaration before running each check over governed paths.
        check.declaration = context.declaration
        findings.extend(check.run(paths))
    source_files = len(governed_paths(context.declaration, paths))
    duration = round((time.perf_counter() - started) * 1000)
    if source_files == 0:
        # Refuse an otherwise clean checker run that examined no governed Python file.
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
        # Publish the bounded complete-check failure after a non-empty subject was established.
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
    ## Each element is one binding-rule identifier in declared evidence-reporting order.
    rules: tuple[str, ...] = ("DOC-003", "FLOW-007")

    def __call__(self, context: GateContext) -> StepResult:
        """Run all custom checks with one shared declaration.

        @param context exact governed repository inputs
        @return aggregate custom-check result
        """
        # Delegate to the shared check family while preserving this adapter's canonical metadata.
        return _run_discipline_checks(context)


class ConfigurationProbeError(ValueError):
    """A required tool field is missing, malformed, or points outside the root."""

    def __init__(self, field: str, detail: str) -> None:
        """Preserve the exact field for a stable gate diagnostic.

        @param field dotted configuration field
        @param detail actionable refusal reason
        """
        super().__init__(f"{field}: {detail}")
        # Retain the exact field and refusal detail for adapter translation.
        self.field = field
        self.detail = detail


class CommandExecutionError(RuntimeError):
    """An external mechanism could not complete and produce a verdict."""


@dataclass(frozen=True, slots=True)
class PreparedCommand:
    """Configuration-probed command ready for execution."""

    ## Fully explicit argv; no tool may discover targets or config from ancestors.
    ## Each arguments element is one process argument string; invocation order is preserved.
    command: tuple[str, ...]
    ## Exact configuration inputs and fields consumed.
    ## Each element binds consumed fields to one file digest; discovery order is retained.
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
    ## Captured stdout when the caller requires stream-specific evidence.
    stdout: str = ""
    ## Captured stderr when the caller requires stream-specific evidence.
    stderr: str = ""


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
    ## Each element binds project or Doxygen fields to one file digest; probe order is retained.
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
    # Keep field identity and repair detail structured for adapter translation.
    return ConfigurationProbeError(field, detail)


def _raise_probe(field: str, detail: str) -> Never:
    """Raise a configuration refusal from already-named values.

    @param field exact dotted configuration field
    @param detail actionable refusal reason
    @return never; always raises
    @throws ConfigurationProbeError unconditionally
    """
    # Route unconditional refusals through the same typed probe constructor.
    raise _probe_error(field, detail)


def _table(document: Mapping[str, object], path: tuple[str, ...]) -> Mapping[str, object]:
    """Read one required nested TOML table.

    @param document decoded project file
        Treat document as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @param path table segments
        Each segment names one TOML table, ordered outermost to innermost.
    @return nested table
    @throws ConfigurationProbeError when a segment is absent or not a table
    """
    # Preserve the documentation-stripped behavior fingerprint used for comparison.
    current: object = document
    # Each traversed element is one visited segment in outermost-to-innermost order, allowing a
    # refusal to name the exact dotted prefix that failed.
    traversed: list[str] = []
    for segment in path:
        traversed.append(segment)
        # Require the current object to expose the next declared table segment.
        if not isinstance(current, Mapping) or segment not in current:
            # Render the traversed prefix so nested absence is localized exactly.
            field = ".".join(traversed)
            # Stop at the first missing prefix so the diagnostic names the narrowest cause.
            raise _probe_error(field, "required table is absent")
        # Preserve the documentation-stripped behavior fingerprint used for comparison.
        current = current[segment]
    if not isinstance(current, Mapping):
        # Name the complete path whose terminal value is not a table.
        field = ".".join(path)
        # Refuse scalar terminal values before exposing mapping access to callers.
        raise _probe_error(field, "expected a table")
    # Narrow the fully traversed terminal value after mapping validation.
    return cast("Mapping[str, object]", current)


def _string_list(value: object, field: str) -> tuple[str, ...]:
    """Parse a non-empty path list, accepting mypy's single-string shorthand.

    @param value decoded TOML value
    @param field dotted field name
    @return non-empty strings
    @throws ConfigurationProbeError on an empty or non-string member
    """
    # Promote a scalar string to one ordered element while preserving a list value.
    values: object = [value] if isinstance(value, str) else value
    if not isinstance(values, list) or not values:
        # Refuse absent, empty, or non-list declaration shapes uniformly.
        # Reject absence, emptiness, and scalar non-text using one stable field diagnostic.
        raise _probe_error(field, "expected a non-empty string array")
    if not all(isinstance(item, str) and item.strip() for item in values):
        # Every element must be a nonblank string before tuple normalization.
        # Refuse the complete array when any target cannot identify a repository path.
        raise _probe_error(field, "every target must be a non-empty string")
    # Freeze the validated targets in declaration order for explicit argv construction.
    return tuple(cast("list[str]", values))


def _local_targets(
    context: GateContext,
    values: Sequence[str],
    field: str,
) -> tuple[tuple[str, ...], int]:
    """Resolve explicit targets while refusing parent, sibling, and empty scans.

    @param context exact governed repository
    @param values repository-relative paths
        Each element is resolved in declaration order; overlapping targets are counted once.
    @param field dotted configuration field
    @return normalized command targets and distinct Python file count
    @throws ConfigurationProbeError when a target escapes, is absent, or is empty
    """
    # Each normalized element is one portable command target in declared order; source files are
    # separately deduplicated for non-vacuity counting.
    normalized: list[str] = []
    # Collect unique files element values; their order is deliberately unordered.
    files: set[Path] = set()
    for value in values:
        # Interpret each configured value as a repository-relative path before confinement checks.
        raw = Path(value)
        candidate = (context.root / raw).resolve()
        # Absolute and parent-relative targets could make the gate inspect another repository.
        if raw.is_absolute() or not candidate.is_relative_to(context.root):
            # Refuse before testing existence outside the governed root.
            raise _probe_error(field, f"target {value!r} escapes the governed repository")
        # Reject a confined but absent path so configuration cannot silently narrow coverage.
        if not candidate.exists():
            # Reject stale configuration instead of silently narrowing the scan.
            raise _probe_error(field, f"target {value!r} does not exist")
        normalized.append(candidate.relative_to(context.root).as_posix())
        candidates = candidate.rglob("*.py") if candidate.is_dir() else (candidate,)
        files.update(path.resolve() for path in candidates if path.is_file())
    # A syntactically valid target set must still provide a non-vacuous Python subject.
    if not files:
        # Refuse success over empty directories and non-Python files.
        raise _probe_error(field, "configured targets contain no Python files")
    # Deduplicate overlapping argv paths while reporting the distinct Python file count.
    return tuple(dict.fromkeys(normalized)), len(files)


def _project_configuration(
    context: GateContext,
    fields: Sequence[str],
) -> ConfigurationUse:
    """Reuse the declaration digest while narrowing the consumed field set.

    @param context exact governed repository
    @param fields tool-specific dotted fields
        Each element names one consumed TOML field, in probe order.
    @return content-bound configuration record
    """
    # Reuse the exact project digest while limiting evidence to fields this probe read.
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
        Each element names one consumed field, in probe order.
    @return absolute file and content-bound use record
    @throws ConfigurationProbeError when the value escapes or is absent
    """
    # Require a nonblank portable relative filename at the configuration boundary.
    if not isinstance(value, str) or not value.strip():
        # Reject absence and blank paths before filesystem resolution.
        raise _probe_error(field, "expected a non-empty repository-relative file")
    # Resolve the declared repository-relative file before checking confinement and type.
    raw = Path(value)
    candidate = (context.root / raw).resolve()
    # Absolute and parent-relative configuration files could borrow sibling policy.
    if raw.is_absolute() or not candidate.is_relative_to(context.root):
        # Refuse before reading bytes outside the governed repository.
        raise _probe_error(field, f"file {value!r} escapes the governed repository")
    # Select the regular-file path only when `not candidate.is_file()` is satisfied.
    if not candidate.is_file():
        # Reject stale or directory-valued declarations at the configuration boundary.
        raise _probe_error(field, f"file {value!r} does not exist")
    use = ConfigurationUse(
        path=candidate.relative_to(context.root).as_posix(),
        sha256=_digest(candidate),
        fields=tuple(consumed_fields),
    )
    # Return both the safe absolute path and its content-bound evidence record.
    return candidate, use


def _gate_table(context: GateContext) -> Mapping[str, object]:
    """Required project-gate configuration distinct from the doctrine declaration.

    @param context decoded exact-root project file
    @return ``tool.agent-discipline-gate`` table
    """
    # Require the dedicated gate table rather than deriving execution policy from defaults.
    return _table(context.pyproject, ("tool", "agent-discipline-gate"))


def _require_value(
    table: Mapping[str, object],
    key: str,
    expected: object,
    field: str,
) -> None:
    """Require one exact configuration posture value.

    @param table containing tool configuration
        Treat table as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @param key local field name
    @param expected required value
    @param field full dotted field name
    @throws ConfigurationProbeError when the value differs
    """
    # Compare the declared scalar with the exact discipline-required value.
    if table.get(key) != expected:
        # Report both required and observed values at the full dotted field.
        raise _probe_error(field, f"expected {expected!r}, found {table.get(key)!r}")


def _prepare_ruff(context: GateContext) -> PreparedCommand:
    """Prove Ruff configuration and targets before constructing its argv.

    @param context exact governed repository
    @return explicit Ruff command
    """
    # Read Ruff's project table before validating explicit governed targets.
    table = _table(context.pyproject, ("tool", "ruff"))
    # Preserve governed Python-path elements in deterministic traversal order.
    targets, subjects = _local_targets(
        context,
        _string_list(table.get("src"), "tool.ruff.src"),
        "tool.ruff.src",
    )
    use = _project_configuration(context, ("tool.ruff", "tool.ruff.src"))
    # Construct explicit Ruff argv only after configuration and non-vacuity probes succeed.
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
    # Preserve declared root order while converting safe absolute paths to portable argv values.
    return tuple(
        # Each path contributes one repository-relative POSIX source target.
        path.resolve().relative_to(context.root).as_posix()
        for path in context.declaration.source_paths()
    )


def _prepare_mypy(context: GateContext) -> PreparedCommand:
    """Prove strict mypy configuration and a non-empty explicit target set.

    @param context exact governed repository
    @return explicit mypy command
    """
    # Read mypy's project table before validating strictness and source targets.
    table = _table(context.pyproject, ("tool", "mypy"))
    _require_value(
        table=table,
        key="strict",
        expected=True,
        field="tool.mypy.strict",
    )
    # Prefer explicit mypy files, otherwise derive targets from governed sources.
    raw_targets = (
        _string_list(table["files"], "tool.mypy.files")
        if "files" in table
        else _declared_source_targets(context)
    )
    # Preserve governed Python-path elements in deterministic traversal order.
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
    # Read Pyright's project table before validating strictness and include targets.
    table = _table(context.pyproject, ("tool", "pyright"))
    _require_value(table, "typeCheckingMode", "strict", "tool.pyright.typeCheckingMode")
    # Preserve governed Python-path elements in deterministic traversal order.
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
    # Read pytest options before validating bounded, isolated test execution.
    table = _table(context.pyproject, ("tool", "pytest", "ini_options"))
    # Preserve governed Python-path elements in deterministic traversal order.
    targets, subjects = _local_targets(
        context,
        _string_list(table.get("testpaths"), "tool.pytest.ini_options.testpaths"),
        "tool.pytest.ini_options.testpaths",
    )
    timeout = table.get("timeout")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        _raise_probe(
            "tool.pytest.ini_options.timeout",
            "expected a positive per-test timeout",
        )
    if table.get("timeout_method") != "thread":
        _raise_probe(
            "tool.pytest.ini_options.timeout_method",
            "expected 'thread', the common Windows/Linux timeout method",
        )
    addopts = _string_list(table.get("addopts"), "tool.pytest.ini_options.addopts")
    if "--disable-socket" not in addopts:
        _raise_probe(
            "tool.pytest.ini_options.addopts",
            "expected --disable-socket so ordinary pytest invocations fail closed",
        )
    use = _project_configuration(
        context,
        (
            "tool.pytest.ini_options",
            "tool.pytest.ini_options.testpaths",
            "tool.pytest.ini_options.timeout",
            "tool.pytest.ini_options.timeout_method",
            "tool.pytest.ini_options.addopts",
        ),
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
            f"--timeout={timeout}",
            "--randomly-seed=default",
            "--disable-socket",
            "-q",
            *targets,
        ),
        configuration=(use,),
        subjects=subjects,
        failure_diagnostic="GATE-PYTEST-003_FAILURE",
        subject_label="test files",
    )


def _prepare_mutation(context: GateContext) -> PreparedCommand:
    """Bind mutation execution to declared domain paths, tests, and budgets.

    @param context exact governed repository
    @return explicit portable mutation-gate command
    """
    # Resolve declared domain roles and mutation policy from validated project data.
    roles = _table(context.pyproject, ("tool", "agent-discipline", "roles"))
    domains, domain_files = _local_targets(
        context,
        _string_list(
            roles.get("domain"),
            "tool.agent-discipline.roles.domain",
        ),
        "tool.agent-discipline.roles.domain",
    )
    # Read mutation thresholds only after governed domain targets resolve.
    mutation = _table(
        context.pyproject,
        ("tool", "agent-discipline-gate", "mutation"),
    )
    # Preserve governed Python-path elements in deterministic traversal order.
    targets, test_files = _local_targets(
        context,
        _string_list(
            mutation.get("test_targets"),
            "tool.agent-discipline-gate.mutation.test_targets",
        ),
        "tool.agent-discipline-gate.mutation.test_targets",
    )
    mutant_timeout = mutation.get("mutant_timeout")
    if (
        not isinstance(mutant_timeout, (int, float))
        or isinstance(mutant_timeout, bool)
        or mutant_timeout <= 0
    ):
        _raise_probe(
            "tool.agent-discipline-gate.mutation.mutant_timeout",
            "expected a positive per-mutant test timeout",
        )
    command_timeout = mutation.get("command_timeout")
    if (
        not isinstance(command_timeout, int)
        or isinstance(command_timeout, bool)
        or command_timeout <= 0
    ):
        _raise_probe(
            "tool.agent-discipline-gate.mutation.command_timeout",
            "expected a positive integer command timeout",
        )
    maximum_survival = mutation.get("maximum_survival")
    if (
        not isinstance(maximum_survival, (int, float))
        or isinstance(maximum_survival, bool)
        or maximum_survival < 0
        or maximum_survival > 0
    ):
        _raise_probe(
            "tool.agent-discipline-gate.mutation.maximum_survival",
            "expected 0.0; known survivors cannot be a percentage allowance",
        )
    use = _project_configuration(
        context,
        (
            "tool.agent-discipline.source_roots",
            "tool.agent-discipline.roles.domain",
            "tool.agent-discipline-gate.mutation.test_targets",
            "tool.agent-discipline-gate.mutation.mutant_timeout",
            "tool.agent-discipline-gate.mutation.command_timeout",
            "tool.agent-discipline-gate.mutation.maximum_survival",
        ),
    )
    return PreparedCommand(
        command=(
            sys.executable,
            str(BUNDLE_ROOT / "tools" / "mutation_gate.py"),
            "--root",
            str(context.root),
            "--json",
        ),
        configuration=(use,),
        subjects=domain_files + test_files,
        failure_diagnostic="MUTATION-008_EXECUTION",
        subject_label=(
            f"domain/test files ({len(domains)} domain and {len(targets)} test target(s))"
        ),
    )


def _positive_count(value: object) -> bool:
    """Whether a decoded report value is a positive non-Boolean integer.

    @param value decoded JSON value
    @return true only for a positive subject count
    """
    # Exclude JSON booleans while requiring actual work to be represented by a positive count.
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _mutation_evaluation(
    execution: CommandExecution,
    command: PreparedCommand,
) -> Evaluation:
    """Require the mutation gate's structured, non-vacuous zero-survivor report.

    @param execution process observation
    @param command prepared command and expected source/test files
    @return pass or exact mutation failure
    """
    # Find the JSON suffix in mutation output before decoding its structured verdict.
    start = execution.output.find("{")
    # Decode only the structured suffix; absent or malformed JSON cannot substantiate success.
    try:
        # Preserve a mapping candidate or explicit absence for the structural verdict below.
        report = json.loads(execution.output[start:]) if start >= 0 else None
    # Invalid JSON follows the same unsubstantiated-report path as an absent suffix.
    except json.JSONDecodeError:
        # Record the lack of usable child evidence without leaking decoder exceptions.
        report = None
    # An unparsable child report cannot substantiate mutation success.
    if not isinstance(report, Mapping):
        # Report the missing structural evidence independently of process status.
        return Evaluation(
            "MUTATION-006_REPORT",
            "mutation gate emitted no parseable JSON report",
            _tail(execution.output),
        )
    diagnostic = report.get("diagnostic_id")
    status = report.get("status")
    mutants = report.get("mutants")
    domains = report.get("domains")
    # Reject either child failure or a non-passing mutation verdict before reading counts.
    if execution.returncode != 0 or status != "pass":
        # Prefer a mutation-specific diagnostic emitted by the child, falling back to gate policy.
        code = diagnostic if isinstance(diagnostic, str) else command.failure_diagnostic
        return Evaluation(
            code,
            str(report.get("summary", "mutation gate failed without a summary")),
            str(report.get("output", _tail(execution.output))),
        )
    # A zero-mutant or zero-domain success is vacuous even when the child exits cleanly.
    if not _positive_count(mutants) or not _positive_count(domains):
        # Refuse the report before it can satisfy the zero-survivor policy.
        return Evaluation(
            "MUTATION-007_NO_MUTANTS",
            "mutation gate reported success without positive mutant and domain counts",
            _tail(execution.output),
        )
    # Publish success only after structured status and both non-vacuity counts hold.
    return Evaluation(
        None,
        f"Cosmic Ray killed all {mutants} mutant(s) across {domains} domain path(s)",
    )


def _import_root_present(
    context: GateContext,
    package: str,
    source_roots: Sequence[str],
    field: str,
) -> None:
    """Require an import-linter root package to exist under a declared source root.

    @param context exact governed repository
    @param package dotted root-package name
    @param source_roots explicit local import roots
        Each element is one repository-relative import root, searched in declaration order.
    @param field configuration field carrying the package
    @throws ConfigurationProbeError when no local package matches
    """
    # Convert the import name to its relative package path for source-root probing.
    relative = Path(*package.split("."))
    # Refuse the target when its declared source directory is absent.
    if any(
        (
            (context.root / source / relative).is_dir()
            or (context.root / source / relative).with_suffix(".py").is_file()
        )
        for source in source_roots
    ):
        # Stop after the first declared source root proves the import package exists locally.
        return
    # Refuse contract configuration that names a package outside all governed source roots.
    raise _probe_error(
        field,
        f"root package {package!r} is absent from declared source roots {source_roots}",
    )


def _prepare_import_contracts(context: GateContext) -> PreparedCommand:
    """Bind import-linter to its declared config, contracts, and source roots.

    @param context exact governed repository
    @return explicit portable wrapper command
    """
    # Resolve import-contract configuration and bind it to exact project bytes.
    gate = _gate_table(context)
    config, config_use = _relative_configuration_file(
        context,
        gate.get("import_contracts"),
        "tool.agent-discipline-gate.import_contracts",
        ("tool.importlinter.root_packages", "tool.importlinter.contracts"),
    )
    # Translate configured-file read and TOML failures to the exact bound config path.
    try:
        # Decode the configured contract document before constructing its explicit command.
        document = cast(
            "Mapping[str, object]",
            tomllib.loads(config.read_text(encoding="utf-8")),
        )
    # Preserve the native parser failure as the cause of the configuration refusal.
    except (OSError, tomllib.TOMLDecodeError) as problem:
        # Report the content-bound configuration path that could not be decoded.
        raise _probe_error(config_use.path, f"cannot parse TOML: {problem}") from problem
    table = _table(document, ("tool", "importlinter"))
    packages = _string_list(
        table.get("root_packages"),
        "tool.importlinter.root_packages",
    )
    contracts_field = "tool.importlinter.contracts"
    contracts = table.get("contracts")
    # At least one explicit contract is required to avoid a vacuous import-linter pass.
    if not isinstance(contracts, list) or not contracts:
        # Reject absent, scalar, and empty contract declarations uniformly.
        raise _probe_error(
            contracts_field,
            "expected one or more contract tables",
        )
    # Every array entry must be a complete contract table rather than a scalar placeholder.
    if not all(isinstance(contract, Mapping) for contract in contracts):
        # Refuse the whole contract set when any member cannot be inspected structurally.
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
    # Expand each governed source root into the wrapper's repeated command-line option.
    source_arguments = tuple(item for source in source_roots for item in ("--source-root", source))
    # Construct wrapper argv with every source root and the minimum contract count explicit.
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
    # Preserve textual assignment order while selecting every occurrence of the requested key.
    matches = [
        match.group(2) for match in _DOXYGEN_ASSIGNMENT.finditer(text) if match.group(1) == key
    ]
    # Duplicate or absent assignments make the effective Doxygen posture ambiguous.
    if len(matches) != 1:
        # Require one authoritative single-line value for each consumed key.
        raise _probe_error(field, f"expected exactly one {key} assignment")
    try:
        # Parse the sole Doxyfile assignment with shell quoting and inline comments honored.
        values = tuple(shlex.split(matches[0], comments=True, posix=True))
    # Preserve malformed quoting detail from the shell-like assignment parser.
    except ValueError as problem:
        # Translate tokenization failure to the exact Doxyfile field.
        raise _probe_error(field, f"cannot parse {key}: {problem}") from problem
    # Empty tokenization means the assignment exists but declares no usable value.
    if not values:
        # Refuse empty assignments instead of applying Doxygen defaults.
        raise _probe_error(field, f"{key} has no value")
    # Preserve authored token order for target and posture validation.
    return values


def _prepare_doxygen(context: GateContext) -> DoxygenPlan:
    """Bind Doxygen to the declared source roots and warning posture.

    @param context exact governed repository
    @return configuration-probed build plan
    """
    # Resolve the local Doxyfile and bind every consumed documentation field.
    gate = _gate_table(context)
    doxyfile, doxyfile_use = _relative_configuration_file(
        context,
        gate.get("doxyfile"),
        "tool.agent-discipline-gate.doxyfile",
        ("INPUT", "FILE_PATTERNS", "WARN_AS_ERROR", "GENERATE_HTML"),
    )
    # Parse Doxyfile input roots from the exact shipped configuration text.
    text = doxyfile.read_text(encoding="utf-8")
    input_field = "Doxyfile.INPUT"
    inputs, subjects = _local_targets(
        context,
        _doxygen_values(text, "INPUT", input_field),
        input_field,
    )
    declared = _declared_source_targets(context)
    # Documentation input coverage must equal, not merely overlap, governed source roots.
    if set(inputs) != set(declared):
        # Refuse omitted or extra roots so generated pages describe exactly the governed source.
        raise _probe_error(
            input_field,
            f"expected declared source roots {declared}, found {inputs}",
        )
    patterns_field = "Doxyfile.FILE_PATTERNS"
    patterns = _doxygen_values(text, "FILE_PATTERNS", patterns_field)
    # Python sources must be eligible for generation under the configured file patterns.
    if "*.py" not in patterns:
        # Reject configurations that could scan roots yet silently ignore every Python file.
        raise _probe_error(patterns_field, "*.py is required")
    warning_field = "Doxyfile.WARN_AS_ERROR"
    warnings = _doxygen_values(text, "WARN_AS_ERROR", warning_field)
    # Warning posture must fail the process rather than merely log documentation defects.
    if warnings != ("FAIL_ON_WARNINGS",):
        # Refuse weaker or ambiguous warning modes.
        raise _probe_error(warning_field, "expected FAIL_ON_WARNINGS")
    html_field = "Doxyfile.GENERATE_HTML"
    html = _doxygen_values(text, "GENERATE_HTML", html_field)
    # HTML output is required because source-page counts provide the non-vacuity witness.
    if html != ("YES",):
        # Refuse configurations that cannot produce the inspected artifact family.
        raise _probe_error(html_field, "expected YES")
    gate_use = _project_configuration(
        context,
        (
            "tool.agent-discipline.doc_engine",
            "tool.agent-discipline.source_roots",
            "tool.agent-discipline-gate.doxyfile",
        ),
    )
    # Publish the probed Doxyfile, both configuration bindings, and expected source-page count.
    return DoxygenPlan(doxyfile, (gate_use, doxyfile_use), subjects)


def _native_executable(name: str) -> str | None:
    """Resolve one native tool on the active environment path.

    @param name executable basename
    @return absolute or launchable path, or None
    """
    # Delegate platform path resolution without inventing repository-local fallbacks.
    return shutil.which(name)


def _native_version(executable: str) -> str:
    """Obtain a bounded native-tool version string.

    @param executable resolved tool path
    @return first non-empty version line
    @throws CommandExecutionError when the probe fails
    """
    # Probe the executable directly and translate launch or timeout failure to the gate boundary.
    try:
        # Retain the completed version probe for status and first-line extraction.
        finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            (executable, "--version"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
    # Preserve launch and timeout detail from the native version probe.
    except (OSError, subprocess.TimeoutExpired) as problem:
        # Translate host-process failure to the adapter's execution boundary.
        raise CommandExecutionError(str(problem)) from problem
    # Reject a resolved native executable that cannot produce a usable version string.
    if finished.returncode != 0:
        # Treat an unversionable executable as unusable even though path lookup succeeded.
        raise CommandExecutionError(_tail(finished.stdout + finished.stderr))
    # Retain the final non-empty tool version line for report identity.
    return _last_line(finished.stdout + finished.stderr)


def _execute_doxygen(
    executable: str,
    plan: DoxygenPlan,
    context: GateContext,
) -> DocumentationExecution:
    """Run Doxygen into the ephemeral workspace and count generated source pages.

    @param executable resolved native tool
    @param plan configuration-probed Doxygen inputs
    @param context exact governed repository and scratch directory
    @return process observation and generated page count
    @throws CommandExecutionError when the process cannot complete
    """
    # Combine the checker's captured diagnostic streams without losing emission text.
    output = context.scratch / "doxygen"
    configuration = (
        plan.configuration_file.read_text(encoding="utf-8")
        + f"\nOUTPUT_DIRECTORY = {output.as_posix()}\n"
    )
    started = time.perf_counter()
    # Run Doxygen with the prepared stdin configuration under the documented timeout.
    try:
        # Retain process status and diagnostics for the explicit documentation observation.
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
    # Preserve launch and timeout detail from the native documentation process.
    except (OSError, subprocess.TimeoutExpired) as problem:
        # Translate host-process failure to the documentation adapter boundary.
        raise CommandExecutionError(str(problem)) from problem
    duration = round((time.perf_counter() - started) * 1000)
    process = CommandExecution(
        finished.returncode,
        finished.stdout + finished.stderr,
        duration,
    )
    # Count generated source pages beneath the isolated output tree as the non-vacuity witness.
    return DocumentationExecution(process, len(list(output.rglob("*_source.html"))))


def _documentation_configuration_failure(
    context: GateContext,
    rules: tuple[str, ...],
    problem: ConfigurationProbeError,
) -> StepResult:
    """Render a documentation configuration-load failure.

    @param context exact governed repository
    @param rules documentation generation rules
        Each element is one documentation-rule identifier in adapter declaration order.
    @param problem field-specific refusal
    @return red result
    """
    # Bind a configuration refusal to the exact project field and file digest that caused it.
    use = _project_configuration(context, (problem.field,))
    # Publish a field-bound red result without attempting Doxygen execution.
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
    context: GateContext,
    rules: tuple[str, ...],
) -> StepResult:
    """Run the configured Doxygen gate with version and output probes.

    @param context exact governed repository
    @param rules documentation generation rules
        Each element is one documentation-rule identifier in adapter declaration order.
    @return explicit Doxygen outcome
    """
    # Prepare and validate the Doxygen configuration before any host-tool execution.
    try:
        # Prepare the complete Doxygen plan before probing host availability or version.
        plan = _prepare_doxygen(context)
    # Configuration refusal precedes host-tool probing and carries exact field evidence.
    except ConfigurationProbeError as problem:
        # Translate the typed refusal to the documentation step's stable diagnostic.
        return _documentation_configuration_failure(context, rules, problem)
    # Resolve the qualified native Doxygen executable required by this gate.
    executable = _native_executable("doxygen")
    # Report the supported native tool as unavailable when no Doxygen executable resolves.
    if executable is None:
        # Distinguish unavailable supported tooling from malformed repository configuration.
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
        # Observe the native executable version before launching documentation generation.
        version = _native_version(executable)
        execution = _execute_doxygen(executable, plan, context)
    # Version or generation launch failures share one bounded execution diagnostic.
    except CommandExecutionError as problem:
        # Preserve the last known tool identity and probed configuration in the red result.
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
    # Convert Doxygen warnings or process failure into the adapter's documentation finding.
    if process.returncode != 0:
        # Convert Doxygen warnings and nonzero generation status to a build failure.
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
    # Require at least one generated source page for every configured Python subject.
    if execution.pages < plan.subjects:
        # Reject clean process status when output inspection proves incomplete generation.
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
    # Publish success only after configuration, version, process, and output probes all hold.
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


@dataclass(frozen=True, slots=True)
class DocumentationAdapter:
    """Capability-aware adapter for the sole v5 Doxygen engine."""

    ## Stable report identity.
    step_id: str = "documentation"
    ## Doxygen generation and non-vacuity predicates named by binding rules.
    ## Each element is one binding-rule identifier in declared evidence-reporting order.
    rules: tuple[str, ...] = ("DOC-005", "DOC-010", "DOC-011", "DOC-015", "DOC-029")

    def __call__(self, context: GateContext) -> StepResult:
        """Apply the declared engine without narrowing silently.

        @param context exact governed repository
        @return explicit build, inapplicability, or support outcome
        """
        # Limit native documentation execution to the two qualified development legs.
        if platform.system() not in {"Windows", "Linux"}:
            # Report unsupported host explicitly; required documentation is never skipped green.
            return StepResult(
                step_id=self.step_id,
                rules=self.rules,
                status=Status.UNSUPPORTED,
                required=True,
                diagnostic_id="GATE-DOCUMENTATION-005_PLATFORM",
                summary=f"documentation builds are not release-supported on {platform.system()}",
            )
        # Delegate supported hosts to the complete Doxygen-specific proof sequence.
        return _run_doxygen_documentation(context, self.rules)


class ArtifactError(ValueError):
    """A build or installed-artifact proof is malformed or inconsistent."""


def _artifact_error(detail: str) -> ArtifactError:
    """Build an artifact refusal from already-localized detail.

    @param detail actionable artifact inconsistency
    @return typed refusal
    """
    # Preserve artifact inconsistencies under one adapter-specific exception type.
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
    ## Each element binds build inputs to one configuration digest; validation order is retained.
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
    ## Each arguments element is one process argument string; invocation order is preserved.
    command: tuple[str, ...]
    ## Exact expected process status.
    expected_exit: int
    ## Finite execution budget.
    timeout_seconds: int
    ## Optional exact standard input supplied to the installed command.
    stdin: str | None
    ## Optional exact expected standard output.
    expected_stdout: str | None
    ## Optional exact expected standard error.
    expected_stderr: str | None


## Repository content that cannot influence the delivered artifact and must not be copied.
_ISOLATION_EXCLUDES: Final = frozenset({
    ".agent",
    ".agents",
    ".claude",
    ".git",
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
    "node_modules",
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
    # Walk each directory with mutable child names and regular-file names in filesystem order.
    for directory, names, files in os.walk(root):
        # Prune package-excluded directories before traversal can copy their descendants.
        names[:] = [name for name in names if name not in _ISOLATION_EXCLUDES]
        # Preserve the documentation-stripped behavior fingerprint used for comparison.
        current = Path(directory)
        for name in (*names, *files):
            # Reject every symbolic link before copying an isolation tree with ambiguous targets.
            path = current / name
            if path.is_symlink():
                # Name the repository-relative link and required materialization repair.
                relative = path.relative_to(root).as_posix()
                detail = f"build isolation refuses symlink {relative!r}; materialize or package it"
                raise _artifact_error(detail)
    shutil.copytree(
        root,
        destination,
        ignore=shutil.ignore_patterns(*_ISOLATION_EXCLUDES),
    )
    # Count every copied regular file so artifact evidence records a non-empty isolated subject.
    return sum(
        # Each path contributes one subject only when the copied entry is a regular file.
        1 for path in destination.rglob("*") if path.is_file()
    )


def _project_identity(context: GateContext) -> tuple[str, str]:
    """Read the required PEP 621 distribution identity.

    @param context decoded exact-root project
    @return name and version
    @throws ConfigurationProbeError when either is absent
    """
    # Read declared distribution name and version from the exact-root project table.
    table = _table(context.pyproject, ("project",))
    name = table.get("name")
    version = table.get("version")
    name_field = "project.name"
    version_field = "project.version"
    # Distribution name must be statically available for artifact identity comparison.
    if not isinstance(name, str) or not name.strip():
        # Reject dynamic, missing, and blank identity values at the project field.
        raise _probe_error(name_field, "expected a non-empty distribution name")
    # Distribution version must likewise be static and non-empty.
    if not isinstance(version, str) or not version.strip():
        # Reject dynamic or blank versions before invoking the build backend.
        raise _probe_error(version_field, "expected a static non-empty version")
    # Return normalized authored identity components without canonicalizing punctuation yet.
    return name.strip(), version.strip()


def _validate_build_system(context: GateContext) -> None:
    """Require a named backend and exact isolated-environment requirements.

    @param context decoded exact-root project
    @throws ConfigurationProbeError when backend selection can drift
    """
    # Validate build backend and exact requirements before invoking an isolated build.
    table = _table(context.pyproject, ("build-system",))
    # Retain the backend value and its full field identity for localized refusal.
    backend = table.get("build-backend")
    backend_field = "build-system.build-backend"
    if not isinstance(backend, str) or not backend.strip():
        # A missing backend makes artifact provenance and build behavior undefined.
        raise _probe_error(backend_field, "expected a backend module")
    # Parse build requirements under their full field identity for exact-pin checks.
    requirements_field = "build-system.requires"
    requirements = _string_list(table.get("requires"), requirements_field)
    # Each unpinned element is one inexact build requirement, retaining requirement order.
    unpinned = [
        requirement
        for requirement in requirements
        if _EXACT_BUILD_REQUIREMENT.fullmatch(requirement) is None
    ]
    # Any inexact build requirement permits isolated backend resolution to drift.
    if unpinned:
        # Report every offending requirement in declaration order for direct repair.
        raise _probe_error(
            requirements_field,
            f"every build requirement must use one exact == version; found {unpinned}",
        )


def _prepare_build(context: GateContext) -> tuple[BuildPlan, PreparedCommand]:
    """Probe packaging config and create the repository-only build copy.

    @param context exact governed repository
    @return build plan and explicit PEP 517 command
    """
    # Read the static distribution name and version that both artifacts must publish.
    name, version = _project_identity(context)
    _validate_build_system(context)
    # Allocate isolated source and artifact roots beneath the adapter scratch boundary.
    source = context.scratch / "isolated-source"
    artifacts = context.scratch / "artifacts"
    try:
        # Copy only materialized repository content into the isolated build source tree.
        subjects = _copy_isolated(context.root, source)
    except ArtifactError as problem:
        # Bind isolation refusal to the repository build-input field.
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
    # Return the isolated build plan beside the only command permitted to populate its output.
    return plan, command


def _canonical_distribution(name: str) -> str:
    """Normalize distribution punctuation for metadata comparison.

    @param name PEP 503-like distribution name
    @return lowercase name with one hyphen per punctuation run
    """
    # Apply the shared comparison normalization used across wheel, sdist, and project names.
    return re.sub(r"[-_.]+", "-", name).lower()


def _metadata_identity(content: bytes, source: str) -> tuple[str, str]:
    """Read Name and Version from core metadata bytes.

    @param content METADATA or PKG-INFO bytes
    @param source artifact/member label
    @return distribution name and version
    @throws ArtifactError when required fields are absent
    """
    # Parse package metadata bytes under the email-message grammar used by wheel and sdist specs.
    message = BytesParser(policy=email_policy).parsebytes(content)
    name = message.get("Name")
    version = message.get("Version")
    if not name or not version:
        # Name the artifact member whose core distribution identity is incomplete.
        detail = f"{source} has no complete Name/Version metadata"
        raise _artifact_error(detail)
    # Return raw metadata identity for caller-side canonical name comparison.
    return str(name), str(version)


def _wheel_identity(path: Path) -> tuple[str, str]:
    """Read the one wheel core-metadata record without importing the package.

    @param path wheel archive
    @return distribution name and version
    @throws ArtifactError when membership or metadata is malformed
    """
    # Open the wheel as untrusted archive data and localize archive-format failures.
    try:
        # Inspect the wheel archive and require exactly one distribution metadata member.
        with zipfile.ZipFile(path) as archive:
            # Each members element is one wheel metadata path, retained in archive order.
            members = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(members) != 1:
                # Multiple or absent metadata members make artifact identity ambiguous.
                detail = f"{path.name} contains {len(members)} METADATA files"
                raise _artifact_error(detail)
            # Parse the sole wheel metadata member without importing artifact code.
            return _metadata_identity(archive.read(members[0]), f"{path.name}:{members[0]}")
    except (OSError, zipfile.BadZipFile, KeyError) as problem:
        # Translate archive and member-read failures to one artifact diagnostic.
        detail = f"cannot read wheel {path.name}: {problem}"
        raise _artifact_error(detail) from problem


def _read_sdist_identity(path: Path) -> tuple[str, str]:
    """Read one root PKG-INFO member from an already-openable source archive.

    @param path gzipped tar source archive
    @return distribution name and version
    @throws ArtifactError when membership or metadata is malformed
    """
    # Inspect the source archive and require exactly one root package metadata member.
    with tarfile.open(path, mode="r:gz") as archive:
        # Each members element is one root-level package metadata member in archive order.
        members = [
            member
            for member in archive.getmembers()
            if member.isfile() and member.name.count("/") == 1 and member.name.endswith("/PKG-INFO")
        ]
        if len(members) != 1:
            # Multiple or absent root metadata members make source identity ambiguous.
            detail = f"{path.name} contains {len(members)} root PKG-INFO files"
            raise _artifact_error(detail)
        stream = archive.extractfile(members[0])
        # Reject a metadata member that the archive index names but cannot expose as bytes.
        if stream is None:
            # A declared metadata member without readable bytes cannot prove identity.
            detail = f"cannot read {path.name}:{members[0].name}"
            raise _artifact_error(detail)
        # Parse the sole root metadata member without extracting archive contents.
        return _metadata_identity(stream.read(), f"{path.name}:{members[0].name}")


def _sdist_identity(path: Path) -> tuple[str, str]:
    """Read source-distribution core metadata without extracting any member.

    @param path gzipped tar source archive
    @return distribution name and version
    @throws ArtifactError when membership or metadata is malformed
    """
    # Decode the source archive while translating compression and tar failures to artifact errors.
    try:
        # Delegate membership and metadata validation to the already-openable archive helper.
        return _read_sdist_identity(path)
    except (OSError, tarfile.TarError) as problem:
        # Translate tar decoding failure to the stable artifact diagnostic family.
        detail = f"cannot read sdist {path.name}: {problem}"
        raise _artifact_error(detail) from problem


def _validate_artifacts(plan: BuildPlan) -> BuiltArtifacts:
    """Require one wheel and one sdist with the declared shared identity.

    @param plan expected identity and output directory
    @return validated artifact paths and identity
    @throws ArtifactError when count or metadata differs
    """
    # Inventory wheel and source artifacts separately in lexical filename order.
    wheels = sorted(plan.artifacts.glob("*.whl"))
    sdists = sorted(plan.artifacts.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        # Require one artifact of each published format before comparing identities.
        detail = f"expected one wheel and one sdist, found {len(wheels)} and {len(sdists)}"
        raise _artifact_error(detail)
    # Read both artifact identities independently before comparing them with project metadata.
    wheel_identity = _wheel_identity(wheels[0])
    sdist_identity = _sdist_identity(sdists[0])
    # Each expected element is respectively the canonical distribution name then exact version;
    # tuple order defines the artifact identity comparison.
    expected = (_canonical_distribution(plan.name), plan.version)
    # Each observed element is one artifact identity pair in wheel-before-sdist order.
    observed = (
        (_canonical_distribution(wheel_identity[0]), wheel_identity[1]),
        (_canonical_distribution(sdist_identity[0]), sdist_identity[1]),
    )
    if observed != (expected, expected):
        # Report all expected and observed identities together so cross-format drift is visible.
        detail = f"expected artifact identity {expected}, found {observed}"
        raise _artifact_error(detail)
    # Publish validated paths and their shared canonical identity for downstream install proof.
    return BuiltArtifacts(wheels[0], sdists[0], expected[0], expected[1])


@dataclass(frozen=True, slots=True)
class ArtifactBuildAdapter:
    """Build and inspect wheel plus sdist from one isolated repository copy."""

    ## Stable report identity.
    step_id: str = "artifact-build"
    ## Delivered-artifact obligation.
    ## Each element is one binding-rule identifier in declared evidence-reporting order.
    rules: tuple[str, ...] = ("API-015", "DEP-008")

    def __call__(self, context: GateContext) -> StepResult:
        """Build both formats and bind their metadata to project declaration.

        @param context exact governed repository
        @return explicit build outcome
        """
        # Prepare project isolation and artifact commands before looking up or running the frontend.
        try:
            # Retain both the validated build plan and its executable command contract.
            plan, command = _prepare_build(context)
        # Translate project or isolation configuration refusal before starting the backend.
        except ConfigurationProbeError as problem:
            # Bind the red result to the exact project field consumed by the failed probe.
            return StepResult(
                step_id=self.step_id,
                rules=self.rules,
                status=Status.FAIL,
                required=True,
                diagnostic_id="GATE-BUILD-001_CONFIGURATION",
                summary=str(problem),
                configuration=(_project_configuration(context, (problem.field,)),),
            )
        # Resolve the installed frontend identity without conflating absence with build failure.
        try:
            # Resolve the installed build frontend version before executing artifact creation.
            version = _distribution_version("build")
        # Missing build frontend is explicit unsupported tooling on a supported platform.
        except importlib.metadata.PackageNotFoundError:
            # Preserve the prepared build command and subject evidence without executing it.
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
        # Execute the prepared build while preserving launch and timeout failure separately.
        try:
            # Retain the complete process observation consumed by artifact validation.
            execution = _execute(command, context.root)
        # Translate backend launch or timeout failure separately from a nonzero build result.
        except CommandExecutionError as problem:
            # Publish bounded execution refusal with the observed build tool identity.
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
        # Preserve backend diagnostics when isolated wheel construction fails.
        if execution.returncode != 0:
            # Preserve backend output because packaging findings are actionable repository defects.
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
            # Validate both produced artifact formats before publishing build success.
            artifacts = _validate_artifacts(plan)
        # Artifact shape and identity failures remain distinct from backend execution failure.
        except ArtifactError as problem:
            # Report invalid delivered bytes even though the build command exited successfully.
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
        # Publish success only after both formats exist and share the declared metadata identity.
        return StepResult(
            step_id=self.step_id,
            rules=self.rules,
            status=Status.PASS,
            required=True,
            diagnostic_id=None,
            summary=(
                f"built and inspected wheel plus sdist for {artifacts.name} {artifacts.version}"
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


def _optional_probe_text(value: object, field: str) -> str | None:
    """Validate one optional exact stream value without stripping it.

    @param value decoded TOML value
    @param field configuration field for diagnostics
    @return exact text or absence
    @throws ConfigurationProbeError when a non-text value is present
    """
    # Accept absence or text only for optional probe fields; other shapes are ambiguous.
    if value is not None and not isinstance(value, str):
        # Refuse coercion because probes compare exact stream bytes represented as text.
        raise _probe_error(field, "must be text or absent")
    # Preserve exact text, including whitespace, for stdout and stderr equality checks.
    return value


def _artifact_probe(raw: object, field: str) -> ArtifactProbe:
    """Parse one exact installed-command probe.

    @param raw decoded TOML table
    @param field configuration location
    @return validated probe
    @throws ConfigurationProbeError when the declaration is unsafe or ambiguous
    """
    # Require each probe declaration to be a mapping before reading its command contract.
    if not isinstance(raw, Mapping):
        # Reject scalar probe entries before any defaulting or field access.
        raise _probe_error(field, "expected a table")
    # Collect unique allowed element values; their order is deliberately unordered.
    allowed = {
        "name",
        "command",
        "expected_exit",
        "timeout_seconds",
        "stdin",
        "expected_stdout",
        "expected_stderr",
    }
    unknown = set(raw) - allowed
    # Surplus fields could represent misspelled expectations silently ignored by the runner.
    if unknown:
        # Report all unknown names in stable lexical order.
        raise _probe_error(field, f"unknown fields {sorted(unknown)}")
    name = raw.get("name")
    expected = raw.get("expected_exit", 0)
    timeout = raw.get("timeout_seconds", 10)
    # Probe names are stable report identities and therefore require visible text.
    if not isinstance(name, str) or not name.strip():
        # Refuse anonymous probes before command validation.
        raise _probe_error(field, "name must be non-empty text")
    # Expected process status must be an integer, with JSON booleans explicitly excluded.
    if not isinstance(expected, int) or isinstance(expected, bool):
        # Refuse coercion so status comparison remains exact.
        raise _probe_error(field, "expected_exit must be an integer")
    if not (
        isinstance(timeout, int)
        and not isinstance(timeout, bool)
        and 1 <= timeout <= _MAX_PROBE_TIMEOUT
    ):
        # Reject unbounded, zero, Boolean, and excessive per-probe time budgets.
        raise _probe_error(
            field,
            f"timeout_seconds must be between 1 and {_MAX_PROBE_TIMEOUT}",
        )
    # Assemble the immutable exact-output contract only after every safety field validates.
    return ArtifactProbe(
        name=name.strip(),
        command=_string_list(raw.get("command"), f"{field}.command"),
        expected_exit=expected,
        timeout_seconds=timeout,
        stdin=_optional_probe_text(raw.get("stdin"), f"{field}.stdin"),
        expected_stdout=_optional_probe_text(
            raw.get("expected_stdout"),
            f"{field}.expected_stdout",
        ),
        expected_stderr=_optional_probe_text(
            raw.get("expected_stderr"),
            f"{field}.expected_stderr",
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
    # Resolve declared import and command probes from the exact-root gate table.
    gate = _gate_table(context)
    # Retain the import field identity beside its normalized ordered values.
    import_field = "tool.agent-discipline-gate.artifact_imports"
    imports = _string_list(gate.get("artifact_imports"), import_field)
    # Each invalid element is one syntactically invalid import name in declaration order.
    invalid = [name for name in imports if _IMPORT_NAME.fullmatch(name) is None]
    # Import syntax must be safe to pass as data to the isolated interpreter script.
    if invalid:
        # Report every malformed name in authored order.
        raise _probe_error(import_field, f"invalid import names {invalid}")
    probes_field = "tool.agent-discipline-gate.artifact_probes"
    raw_probes = gate.get("artifact_probes", [])
    # Command probes are an ordered array; scalar shorthand would obscure argv boundaries.
    if not isinstance(raw_probes, list):
        # Reject non-array shapes before indexed diagnostic paths are constructed.
        raise _probe_error(probes_field, "expected an array")
    # Materialize configured artifact probes in declaration order after schema validation.
    probes = tuple(
        _artifact_probe(raw, f"{probes_field}[{index}]") for index, raw in enumerate(raw_probes)
    )
    # Repeated names would make report evidence and repairs ambiguous.
    if len({probe.name for probe in probes}) != len(probes):
        # Require one stable identity per declared command probe.
        raise _probe_error(probes_field, "probe names repeat")
    # Return imports and probes in project declaration order.
    return imports, probes


def _fresh_python(environment: Path) -> Path:
    """Locate the interpreter inside a fresh cross-platform virtual environment.

    @param environment virtual-environment root
    @return interpreter path
    """
    # Resolve the platform-specific interpreter location inside a fresh virtual environment.
    windows = environment / "Scripts" / "python.exe"
    # Prefer the Windows layout when present, otherwise select the POSIX venv layout.
    return windows if windows.is_file() else environment / "bin" / "python"


def _create_venv(environment: Path) -> Path:
    """Create a clean pip-bearing environment and return its interpreter.

    @param environment absent scratch directory
    @return fresh interpreter path
    @throws CommandExecutionError when creation is incomplete
    """
    # Create the isolated environment while translating host filesystem failure at this boundary.
    try:
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
    # Preserve filesystem-level environment creation failure as execution detail.
    except OSError as problem:
        # Translate host failure to the clean-install adapter boundary.
        raise CommandExecutionError(str(problem)) from problem
    # Resolve the platform-specific interpreter path expected from the new environment.
    interpreter = _fresh_python(environment)
    # Select the regular-file path only when `not interpreter.is_file()` is satisfied.
    if not interpreter.is_file():
        # Name the expected interpreter path when environment creation produced no usable runtime.
        detail = f"virtual environment has no interpreter at {interpreter}"
        raise CommandExecutionError(detail)
    # Return only a verified regular-file interpreter path.
    return interpreter


def _probe_argv(probe: ArtifactProbe, interpreter: Path) -> tuple[str, ...]:
    """Resolve one probe strictly inside the fresh virtual environment.

    @param probe declared argv and expectation
    @param interpreter fresh environment Python
    @return executable argv
    @throws ConfigurationProbeError when the entry point is absent
    """
    # Anchor installed command resolution beside the fresh environment's interpreter.
    scripts = interpreter.parent
    # Each resolved element is one command argument after interpreter substitution; declared
    # argument order is preserved.
    resolved = [
        str(interpreter) if argument == "{python}" else argument for argument in probe.command
    ]
    first = Path(resolved[0])
    # The explicit interpreter placeholder already resolves entirely within the fresh venv.
    if resolved[0] == str(interpreter):
        # Preserve declared arguments after safe placeholder substitution.
        return tuple(resolved)
    # All other executables must be a basename resolved from the venv's scripts directory.
    if first.is_absolute() or len(first.parts) != 1:
        # Refuse absolute, relative-directory, and traversal command paths.
        raise _probe_error(probe.name, "probe executable must be {python} or a venv entry point")
    # Each candidates element is an entry-point path, ordered as declared spelling then Windows
    # executable spelling.
    candidates = (scripts / first, (scripts / first).with_suffix(".exe"))
    executable = next((path for path in candidates if path.is_file()), None)
    # Fail closed when the installed wheel publishes none of the supported entry points.
    if executable is None:
        # Fail closed when the installed wheel did not publish the declared entry point.
        raise _probe_error(probe.name, f"installed entry point {first} does not exist")
    # Replace the declared basename with the verified venv-local executable path.
    return (str(executable), *resolved[1:])


def _execute_with_timeout(
    command: tuple[str, ...],
    root: Path,
    timeout: int,
    stdin: str | None = None,
) -> CommandExecution:
    """Execute a declared installed probe with its own finite budget.

    @param command resolved venv-local argv
        Each arguments element is one process argument string; invocation order is preserved.
    @param root source-free working directory
    @param timeout seconds before refusal
    @param stdin optional exact text supplied to standard input
    @return process observation
    @throws CommandExecutionError when launch or timeout fails
    """
    # Wrap the explicit probe command in the shared execution contract and start bounded timing.
    prepared = PreparedCommand(command, (), 1, "", "probe")
    started = time.perf_counter()
    # Execute the clean-environment probe and translate launch or timeout failure uniformly.
    try:
        # Retain process output and status for conversion to the shared execution record.
        finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            prepared.command,
            cwd=root,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    # Preserve launch and timeout detail from the installed behavior probe.
    except (OSError, subprocess.TimeoutExpired) as problem:
        # Translate host process failure without fabricating an exit status.
        raise CommandExecutionError(str(problem)) from problem
    # Return exact separated streams as well as their combined diagnostic view.
    return CommandExecution(
        finished.returncode,
        finished.stdout + finished.stderr,
        round((time.perf_counter() - started) * 1000),
        finished.stdout,
        finished.stderr,
    )


@dataclass(frozen=True, slots=True)
class InstallPlan:
    """Fresh environment plus declared installed-artifact probes."""

    ## Distribution identity expected after installation.
    name: str
    ## Distribution version expected after installation.
    version: str
    ## Modules that must import under isolated mode.
    ## Each element is one import name in project declaration order.
    imports: tuple[str, ...]
    ## Optional installed console behavior probes.
    ## Each element is one console probe in project declaration order.
    probes: tuple[ArtifactProbe, ...]
    ## Fresh environment interpreter.
    interpreter: Path
    ## Explicit wheel-install command.
    install: PreparedCommand


def _prepare_install(
    context: GateContext,
    step_id: str,
    rules: tuple[str, ...],
) -> InstallPlan | StepResult:
    """Locate the validated wheel, parse probes, and create the fresh environment.

    @param context exact governed repository
    @param step_id stable gate result identity
    @param rules delivered-artifact rules
        Each element is one delivered-artifact rule id in adapter declaration order.
    @return install plan or explicit preflight failure
    """
    # Inventory isolated build wheels before selecting the sole clean-install candidate.
    wheels = sorted((context.scratch / "artifacts").glob("*.whl"))
    # Clean installation depends on exactly one wheel validated by the prior build step.
    if len(wheels) != 1:
        # Preserve step scheduling while explaining why installation could not run.
        return StepResult(
            step_id=step_id,
            rules=rules,
            status=Status.NOT_RUN,
            required=True,
            diagnostic_id="GATE-INSTALL-000_BUILD_REQUIRED",
            summary=f"expected one validated wheel from artifact-build, found {len(wheels)}",
        )
    try:
        # Parse declared import and command probes before allocating a fresh environment.
        imports, probes = _parse_artifact_probes(context)
        name, version = _project_identity(context)
    # Translate unsafe or incomplete probe declarations before environment allocation.
    except ConfigurationProbeError as problem:
        # Bind the red preflight result to the exact project field that failed.
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
        # Create an empty virtual environment used only for wheel installation and probes.
        interpreter = _create_venv(context.scratch / "installed")
    # Fresh-environment construction failures are infrastructure execution defects.
    except CommandExecutionError as problem:
        # Publish the explicit environment failure before pip is invoked.
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
            str(interpreter),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            str(wheels[0]),
        ),
        (use,),
        1,
        "GATE-INSTALL-003_INSTALL",
        "wheel",
    )
    # Publish all clean-install inputs after wheel, configuration, and environment preflight.
    return InstallPlan(name, version, imports, probes, interpreter, install)


def _install_wheel(
    context: GateContext,
    plan: InstallPlan,
    step_id: str,
    rules: tuple[str, ...],
) -> CommandExecution | StepResult:
    """Install one wheel and translate process failure into a gate result.

    @param context exact governed repository
    @param plan fresh environment install plan
    @param step_id stable gate result identity
    @param rules delivered-artifact rules
        Each element is one delivered-artifact rule id in adapter declaration order.
    @return process observation or explicit failure
    """
    # Install the built wheel inside the fresh interpreter before any import probe is attempted.
    try:
        # Execute wheel installation inside the isolated interpreter environment.
        installed = _execute(plan.install, context.scratch)
    # Translate pip launch and timeout failure separately from a nonzero pip result.
    except CommandExecutionError as problem:
        # Preserve prepared command evidence in the explicit execution refusal.
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
    # Stop artifact qualification when installation into the isolated environment fails.
    if installed.returncode != 0:
        # Retain bounded pip output because dependency or wheel defects are actionable.
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
    # Pass the successful installation observation to import and behavior probes.
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
        Each element is one delivered-artifact rule id in adapter declaration order.
    @return accumulated duration or explicit failure
    """
    # Build one isolated interpreter script that imports every declared package and its metadata.
    script = (
        "import importlib, importlib.metadata as metadata; "
        f"assert metadata.version({plan.name!r}) == {plan.version!r}; "
        f"[importlib.import_module(name) for name in {plan.imports!r}]"
    )
    try:
        # Execute the import proof with network-disabled inherited gate conditions and timeout.
        imported = _execute_with_timeout(
            (str(plan.interpreter), "-I", "-c", script),
            context.scratch,
            60,
        )
    # Translate isolated interpreter launch or timeout into the import diagnostic family.
    except CommandExecutionError as problem:
        # Preserve install command evidence while reporting the failed post-install probe.
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
    # Reject the artifact when installed metadata or its import probe fails.
    if imported.returncode != 0:
        # Metadata mismatch and import failure both invalidate the installed artifact contract.
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
    # Return cumulative install-plus-import duration for the remaining behavior probes.
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
        Each element is one delivered-artifact rule id in adapter declaration order.
    @return total duration or first explicit probe failure
    """
    # Accumulate probe duration onto earlier install/import time for one step measurement.
    total = duration
    for probe in plan.probes:
        # Resolve and execute each declared command probe in declaration order.
        try:
            # Substitute the fresh interpreter into the probe's explicit argument vector.
            argv = _probe_argv(probe, plan.interpreter)
            # Observe one bounded command execution before matching its declared output contract.
            observed = _execute_with_timeout(
                argv,
                context.scratch,
                probe.timeout_seconds,
                probe.stdin,
            )
        # Resolve and execution failures share the installed-command probe diagnostic.
        except (ConfigurationProbeError, CommandExecutionError) as problem:
            # Stop at the first declared probe that cannot be executed safely.
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
        # Compare each declared artifact probe with its explicit expected process status.
        if observed.returncode != probe.expected_exit:
            # Report the exact status mismatch before comparing output streams.
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
        # Each mismatches element is one observed-versus-expected difference, ordered by exit
        # status, stdout, then stderr.
        mismatches = []
        if probe.expected_stdout is not None and observed.stdout != probe.expected_stdout:
            mismatches.append("stdout")
        if probe.expected_stderr is not None and observed.stderr != probe.expected_stderr:
            mismatches.append("stderr")
        # Exact expected streams, when declared, must match independently.
        if mismatches:
            # Report all mismatched stream names for the current probe.
            return StepResult(
                step_id=step_id,
                rules=rules,
                status=Status.FAIL,
                required=True,
                diagnostic_id="GATE-INSTALL-006_OUTPUT",
                summary=(f"probe {probe.name!r} did not match exact {', '.join(mismatches)}"),
                command=argv,
                configuration=plan.install.configuration,
                duration_ms=total,
                output=_tail(observed.output),
            )
    # Return the accumulated duration after every declared command contract holds.
    return total


@dataclass(frozen=True, slots=True)
class CleanInstallAdapter:
    """Install the built wheel and exercise declared public probes outside source."""

    ## Stable report identity.
    step_id: str = "clean-install"
    ## Delivered-artifact and public-entry obligations.
    ## Each element is one binding-rule identifier in declared evidence-reporting order.
    rules: tuple[str, ...] = ("API-015", "TEST-019")

    def __call__(self, context: GateContext) -> StepResult:
        """Create a fresh venv, install the wheel, and run local probes.

        @param context exact governed repository and shared scratch space
        @return explicit installation/probe outcome
        """
        # Prepare clean-install inputs; a StepResult here is an already localized preflight refusal.
        prepared = _prepare_install(context, self.step_id, self.rules)
        # Forward a localized preflight result without executing later install stages.
        if isinstance(prepared, StepResult):
            # Preserve the exact wheel or configuration refusal produced by preflight.
            return prepared
        # Install the sole wheel before any import or command probe is allowed to run.
        installed = _install_wheel(context, prepared, self.step_id, self.rules)
        # Stop when pip launch or installation failed.
        if isinstance(installed, StepResult):
            # Preserve the exact installation failure without attempting imports.
            return installed
        # Verify declared imports and distribution metadata in the isolated interpreter.
        imported = _verify_installed_imports(
            context,
            prepared,
            installed,
            self.step_id,
            self.rules,
        )
        # Stop when installed metadata or imports failed under isolated mode.
        if isinstance(imported, StepResult):
            # Preserve the exact import failure without attempting command probes.
            return imported
        # Verify every declared installed command only after imports have succeeded.
        probed = _verify_installed_commands(
            context,
            prepared,
            imported,
            self.step_id,
            self.rules,
        )
        # Stop when any declared installed command violated its exact contract.
        if isinstance(probed, StepResult):
            # Preserve the first command-contract failure as the clean-install verdict.
            return probed
        # Publish delivered-artifact success only after installation, imports, and commands pass.
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
                (f"import[{index}]", value) for index, value in enumerate(prepared.imports)
            )
            + tuple((f"probe[{index}]", probe.name) for index, probe in enumerate(prepared.probes)),
        )


def _execute(command: PreparedCommand, root: Path) -> CommandExecution:
    """Run one fixed argv with bounded time and output capture.

    @param command prepared explicit command
    @param root exact governed working directory
    @return process observation
    @throws CommandExecutionError when the process cannot start or times out
    """
    # Start timing immediately before the prepared external command boundary.
    started = time.perf_counter()
    # Execute the prepared adapter command while localizing launch and timeout failures.
    try:
        # Retain status and diagnostics for the shared execution observation.
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
    # Preserve launch and timeout detail from the prepared gate command.
    except (OSError, subprocess.TimeoutExpired) as problem:
        # Translate host-process failure without inventing a tool verdict.
        raise CommandExecutionError(str(problem)) from problem
    duration = round((time.perf_counter() - started) * 1000)
    # Publish process status, combined output, and bounded duration as one observation.
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
    # Retain the actionable end of output while preventing unbounded JSON reports.
    return output[-maximum:].strip()


def _last_line(output: str) -> str:
    """Last non-empty status line from a tool.

    @param output combined process output
    @return line or a visible no-output marker
    """
    # Normalize nonblank tool-output lines before selecting the final visible status.
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    # Prefer the final visible tool status, with an explicit marker for silent success.
    return lines[-1] if lines else "completed with no textual output"


def _distribution_version(name: str) -> str:
    """Observed installed version behind an external mechanism.

    @param name distribution package name
    @return installed version
    @throws PackageNotFoundError when the tool is unavailable
    """
    # Resolve the distribution actually installed in the qualified execution environment.
    return importlib.metadata.version(name)


def _ordinary_evaluation(
    execution: CommandExecution,
    command: PreparedCommand,
) -> Evaluation:
    """Interpret a conventional zero-success tool without hiding its subject count.

    @param execution process observation
    @param command prepared command and diagnostic
    @return pass or tool-finding evaluation
    """
    # Convert the tool process status into its predeclared project-gate diagnostic.
    if execution.returncode != 0:
        # Convert nonzero status to the tool-specific diagnostic prepared before launch.
        return Evaluation(
            command.failure_diagnostic,
            f"tool rejected {command.subjects} {command.subject_label}",
            _tail(execution.output),
        )
    # Preserve subject count and final tool status in the successful evaluation summary.
    return Evaluation(
        None,
        f"clean over {command.subjects} {command.subject_label}: {_last_line(execution.output)}",
    )


def _pyright_evaluation(
    execution: CommandExecution,
    command: PreparedCommand,
) -> Evaluation:
    """Require pyright's own report to confirm that it analysed files.

    @param execution process observation
    @param command prepared command and expected subject set
    @return pass, findings, or vacuity failure
    """
    # Find the JSON suffix in Pyright output before decoding summary metrics.
    start = execution.output.find("{")
    # Decode only the structured suffix; absent or malformed JSON cannot prove non-vacuity.
    try:
        # Preserve a mapping candidate or explicit absence for the pyright verdict below.
        report = json.loads(execution.output[start:]) if start >= 0 else None
    # Invalid JSON follows the same missing-evidence path as an absent structured suffix.
    except json.JSONDecodeError:
        # Record unusable report evidence without exposing a decoder exception to the gate.
        report = None
    # Process success without parseable structured output cannot establish non-vacuity.
    if not isinstance(report, Mapping):
        # Refuse the observation independently of pyright's exit status.
        return Evaluation(
            "GATE-PYRIGHT-004_REPORT",
            "pyright emitted no parseable JSON report",
            _tail(execution.output),
        )
    # Select the checker summary mapping that carries analyzed-file metrics.
    summary = report.get("summary")
    # The summary object carries the only authoritative analysed-file and error counts.
    if not isinstance(summary, Mapping):
        # Refuse reports that omit the metrics required by this gate.
        return Evaluation(
            "GATE-PYRIGHT-004_REPORT",
            "pyright report has no summary",
            _tail(execution.output),
        )
    analysed = summary.get("filesAnalyzed")
    # Read Pyright's exact error count separately from its analyzed-file non-vacuity metric.
    errors = summary.get("errorCount")
    # Reject Pyright process failure or any reported strict-typing error.
    if execution.returncode != 0 or errors != 0:
        # Preserve both error and analysed-file counts in the failing summary.
        return Evaluation(
            command.failure_diagnostic,
            f"pyright reported {errors!r} error(s) after analysing {analysed!r} file(s)",
            _tail(execution.output),
        )
    # A clean report over no analysed files is a vacuous type-check success.
    if not isinstance(analysed, int) or analysed <= 0:
        # Reject missing, malformed, and zero file counts.
        return Evaluation(
            "GATE-PYRIGHT-005_NO_SUBJECT",
            "pyright reported success after analysing no files",
            _tail(execution.output),
        )
    # Publish success only after structured zero errors and a positive file count agree.
    return Evaluation(None, f"pyright analysed {analysed} file(s) with zero errors")


## Pytest's terminal summary carries the number that actually executed.
_PYTEST_PASSED: Final = re.compile(r"(?:^|\s)(\d+) passed(?:,|\s|$)")


def _pytest_evaluation(
    execution: CommandExecution,
    command: PreparedCommand,
) -> Evaluation:
    """Refuse a zero-test or all-skipped pytest success.

    @param execution process observation
    @param command prepared command and expected test roots
    @return pass, test failure, or vacuity failure
    """
    # Preserve failed pytest diagnostics before applying the successful-run non-vacuity floor.
    if execution.returncode != 0:
        # Preserve configured test-file count and bounded pytest output on failure.
        return Evaluation(
            command.failure_diagnostic,
            f"pytest failed while evaluating {command.subjects} configured test file(s)",
            _tail(execution.output),
        )
    matches = _PYTEST_PASSED.findall(execution.output)
    passed = int(matches[-1]) if matches else 0
    # Zero reported passes includes empty collection and all-skipped runs.
    if passed == 0:
        # Refuse a clean process status that executed no passing test behavior.
        return Evaluation(
            "GATE-PYTEST-004_NO_EXECUTION",
            "pytest exited zero without reporting any passed test",
            _tail(execution.output),
        )
    # Publish the independently parsed positive execution count.
    return Evaluation(None, f"pytest executed {passed} passing test(s)")


@dataclass(frozen=True, slots=True)
class ConfiguredToolAdapter:
    """One external mechanism with configuration, version, and subject probes."""

    ## Stable report identity.
    step_id: str
    ## Binding rules whose decidable arms use the mechanism.
    ## Each element is one binding-rule identifier in declared evidence-reporting order.
    rules: tuple[str, ...]
    ## Import-package distribution used to obtain the observed version.
    distribution: str
    ## Tool-specific configuration probe and argv constructor.
    prepare: Callable[[GateContext], PreparedCommand]
    ## Tool-specific process-report interpreter.
    evaluate: Callable[[CommandExecution, PreparedCommand], Evaluation]
    ## Platforms on which this adapter is part of the release gate.
    ## Each supported platforms element carries one supported platform value produced or
    ## consumed by this operation; construction order is preserved.
    supported_platforms: tuple[str, ...] = ("Windows", "Linux")

    def _configuration_failure(
        self,
        context: GateContext,
        problem: ConfigurationProbeError,
    ) -> StepResult:
        """Render one failed configuration-load probe.

        @param context exact governed repository
        @param problem field-specific refusal
        @return red result
        """
        # Bind a tool configuration refusal to the exact project field and digest.
        use = _project_configuration(context, (problem.field,))
        # Bind configuration refusal to the adapter's stable identity and supported platforms.
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
        # Report explicit inapplicability before probing a distribution on an unsupported host.
        if platform.system() not in self.supported_platforms:
            # Required tools are reported unsupported, never silently skipped green.
            return StepResult(
                step_id=self.step_id,
                rules=self.rules,
                status=Status.UNSUPPORTED,
                required=True,
                diagnostic_id=f"GATE-{self.step_id.upper()}-002_PLATFORM",
                summary=f"{platform.system()} is not in {self.supported_platforms}",
                supported_platforms=self.supported_platforms,
            )
        # Prepare the adapter command while keeping configuration refusal distinct from execution.
        try:
            # Retain the validated command contract used by version lookup and execution.
            command = self.prepare(context)
        # Convert field-specific configuration refusal through the shared adapter renderer.
        except ConfigurationProbeError as problem:
            # Return before distribution lookup or command execution can obscure the root cause.
            return self._configuration_failure(context, problem)
        try:
            # Resolve the exact verifier distribution version before command preparation.
            version = _distribution_version(self.distribution)
        # Missing verifier distribution is explicit unsupported tooling.
        except importlib.metadata.PackageNotFoundError:
            # Preserve prepared command and non-vacuity evidence without executing it.
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
        # Execute the prepared verifier while keeping launch and timeout failure explicit.
        try:
            # Retain the process observation consumed by this adapter's evaluator.
            execution = _execute(command, context.root)
        # Translate launch and timeout failure separately from a tool-reported verdict.
        except CommandExecutionError as problem:
            # Publish the observed distribution identity with the execution refusal.
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
        # Interpret tool-specific output only after process execution completed normally.
        evaluation = self.evaluate(execution, command)
        # Convert the evaluation into the common exhaustive result schema.
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
## Each element is one binding-rule identifier in published adapter-reporting order.
RUFF_RULES: Final = (
    "ARCH-016",
    "DIAG-008",
    "DIAG-012",
    "DIAG-015",
    "DOC-001",
    "DOC-003",
    "DOC-006",
    "ERR-008",
    "ERR-009",
    "TYPE-003",
)
## Mypy predicates presently named by binding rules.
## Each element is one binding-rule identifier in published adapter-reporting order.
MYPY_RULES: Final = (
    "ARCH-006",
    "ERR-002",
    "ERR-005",
    "TYPE-001",
    "TYPE-002",
    "TYPE-003",
    "TYPE-013",
)
## Pyright supplies a deliberately independent strict type oracle.
## Each element is one binding-rule identifier in published adapter-reporting order.
PYRIGHT_RULES: Final = ("ERR-002", "TYPE-001")
## Pytest execution activates the configured timeout, randomization, and socket controls.
## Each element is one binding-rule identifier in published adapter-reporting order.
PYTEST_RULES: Final = ("TEST-003", "TEST-017")
## Cosmic Ray supplies an isolated, non-empty zero-survivor mutation verdict.
## Each element is one binding-rule identifier in published adapter-reporting order.
MUTATION_RULES: Final = ("TEST-013",)
## Import-linter predicates presently named by binding rules.
## Each IMPORT CONTRACT RULES element carries one IMPORT CONTRACT RULES value produced or
## consumed by this operation; construction order is preserved.
IMPORT_CONTRACT_RULES: Final = (
    "API-004",
    "ARCH-001",
    "ARCH-002",
    "ARCH-003",
    "DEP-001",
    "EFCT-001",
    "EFCT-012",
)

## Canonical Ruff adapter.
RUFF_STEP: Final = ConfiguredToolAdapter(
    "ruff",
    RUFF_RULES,
    "ruff",
    _prepare_ruff,
    _ordinary_evaluation,
)
## Canonical mypy adapter.
MYPY_STEP: Final = ConfiguredToolAdapter(
    "mypy",
    MYPY_RULES,
    "mypy",
    _prepare_mypy,
    _ordinary_evaluation,
)
## Canonical pyright adapter.
PYRIGHT_STEP: Final = ConfiguredToolAdapter(
    "pyright",
    PYRIGHT_RULES,
    "pyright",
    _prepare_pyright,
    _pyright_evaluation,
)
## Canonical pytest adapter.
PYTEST_STEP: Final = ConfiguredToolAdapter(
    "pytest",
    PYTEST_RULES,
    "pytest",
    _prepare_pytest,
    _pytest_evaluation,
)
## Canonical portable mutation adapter.
MUTATION_STEP: Final = ConfiguredToolAdapter(
    "mutation",
    MUTATION_RULES,
    "cosmic-ray",
    _prepare_mutation,
    _mutation_evaluation,
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
## Each element is one gate adapter in execution order; later steps may depend on earlier
## configuration validity.
DEFAULT_STEPS: Final[tuple[StepAdapter, ...]] = (
    DisciplineChecksAdapter(),
    RUFF_STEP,
    MYPY_STEP,
    PYRIGHT_STEP,
    IMPORT_CONTRACTS_STEP,
    DocumentationAdapter(),
    PYTEST_STEP,
    MUTATION_STEP,
    ArtifactBuildAdapter(),
    CleanInstallAdapter(),
)


def _not_run(adapter: StepAdapter, prerequisite: StepResult) -> StepResult:
    """Preserve an adapter in the report after a prerequisite failed.

    @param adapter step prevented from running
    @param prerequisite earlier red result
    @return explicit not-run result
    """
    # Preserve adapter identity and rules while naming the exact red prerequisite.
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
        Adapters execute in sequence and produce one outcome each unless declaration fails.
    @return complete report
    """
    # Resolve the governed root once before allocating one isolated scratch tree for all steps.
    exact_root = root.resolve()
    with tempfile.TemporaryDirectory(prefix="agent-project-gate-") as temporary:
        # Load declaration state first because every later adapter depends on the same context.
        declaration_result, context = _load_context(exact_root, Path(temporary))
        # Each outcomes element is one step result, beginning with declaration validation and
        # followed by adapter outcomes in scheduled order.
        outcomes = [declaration_result]
        # Withhold every adapter when declaration preflight cannot construct a safe context.
        if context is None:
            # Mark every configured adapter not-run when declaration preflight withheld context.
            outcomes.extend(_not_run(adapter, declaration_result) for adapter in steps)
            # No validated declaration means no truthful application/component unit identity.
            unit = None
        else:
            # Execute each adapter in declared gate order against the immutable shared context.
            outcomes.extend(adapter(context) for adapter in steps)
            # Publish the validated unit kind beside the complete outcome sequence.
            unit = context.unit.value
    # Publish the complete ordered report after the shared scratch tree has been reclaimed.
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
    # Select adopter root beside a vendored `.agent`, otherwise use this checkout's working root.
    return BUNDLE_ROOT.parent if BUNDLE_ROOT.name == ".agent" else Path.cwd()


def _print_report(report: GateReport) -> None:
    """Print one stable line per outcome and a final verdict.

    @param report complete gate report
    """
    # Render each step result in canonical gate order.
    for result in report.outcomes:
        # Render an optional stable diagnostic beside each step's status and summary.
        diagnostic = f" {result.diagnostic_id}" if result.diagnostic_id else ""
        print(f"{result.status.value:14s} {result.step_id:24s}{diagnostic} {result.summary}")
        if result.output:
            # Emit bounded actionable child output only for results that retained it.
            print(result.output)
    print(f"\nproject gate: {'PASS' if report.green else 'FAIL'}")


def main(argv: list[str] | None = None) -> int:
    """Parse the CLI, run the gate, and optionally persist its JSON report.

    @param argv command-line arguments, or None for ``sys.argv``
    @return zero only when the complete report is green

    @par Effects
    Runs the aggregate gate, prints its report, and optionally writes JSON evidence.
    """
    # Configure the command-line parser that defines this tool's invocation contract.
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=_default_root())
    parser.add_argument("--json", type=Path, help="write the complete report as JSON")
    # Parse the project root and optional JSON report destination before running adapters.
    arguments = parser.parse_args(argv)
    # Execute the complete gate against the explicit or installation-derived root.
    report = run(arguments.root)
    _print_report(report)
    # Persist machine-readable evidence only when the operator requested a destination.
    if arguments.json is not None:
        # Write deterministic UTF-8 JSON after the human report has been emitted.
        arguments.json.write_text(
            json.dumps(report.as_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return EXIT_GREEN if report.green else EXIT_RED


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    # Translate the aggregate gate verdict to the sole process exit boundary.
    raise SystemExit(main())
