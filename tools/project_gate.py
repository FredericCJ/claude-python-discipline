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
        # Return a JSON-compatible record to the caller.
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
        # Select the empty-or-disabled path when self.step id or not self.summary.strip() has no
        # Details: usable value.
        if not self.step_id or not self.summary.strip():
            # Propagate the localized failure so callers cannot mistake it for success.
            raise ResultInvariantError(_EMPTY_RESULT)
        # Use the available-value path only when self.status is Status.PASS and self.diagnostic
        # Details: id is present.
        if self.status is Status.PASS and self.diagnostic_id is not None:
            # Propagate the localized failure so callers cannot mistake it for success.
            raise ResultInvariantError(_SUCCESS_WITH_DIAGNOSTIC)
        # Use the absence path when self.status is not Status.PASS and self.diagnostic id has no
        # Details: available value.
        if self.status is not Status.PASS and self.diagnostic_id is None:
            # Propagate the localized failure so callers cannot mistake it for success.
            raise ResultInvariantError(_RED_WITHOUT_DIAGNOSTIC)
        # Select the guarded path only after `self.status is Status.NOT_APPLICABLE and
        # Details: self.required` is satisfied.
        if self.status is Status.NOT_APPLICABLE and self.required:
            # Propagate the localized failure so callers cannot mistake it for success.
            raise ResultInvariantError(_INAPPLICABLE_REQUIRED)
        # Select the guarded path only after `self.subjects < 0 or self.duration_ms < 0` is
        # Details: satisfied.
        if self.subjects < 0 or self.duration_ms < 0:
            # Propagate the localized failure so callers cannot mistake it for success.
            raise ResultInvariantError(_NEGATIVE_MEASUREMENT)

    @property
    def green(self) -> bool:
        """Whether this outcome may contribute to a green aggregate verdict.

        @return True only for pass and valid not-applicable outcomes
        """
        # Return true only for pass and valid not-applicable outcomes to the caller.
        return self.status in {Status.PASS, Status.NOT_APPLICABLE}

    def as_dict(self) -> dict[str, object]:
        """Render this outcome without losing absent-versus-empty distinctions.

        @return a JSON-compatible record
        """
        # Treat the current item as the candidate element consumed by the enclosing
        # Details: transformation.
        # Return a JSON-compatible record to the caller.
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
        # Capture result as the completed green outcome for subsequent validation or
        # Details: publication.
        # Return false for an empty or non-green outcome set to the caller.
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
        # Capture result as the completed as dict outcome for subsequent validation or
        # Details: publication.
        # Return a JSON-compatible record to the caller.
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
    # Return lowercase hexadecimal digest to the caller.
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _project_use(root: Path) -> ConfigurationUse:
    """Bind declaration loading to the project file at the exact root.

    @param root governed repository root
    @return configuration record for the v5 declaration
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = root / "pyproject.toml"
    # Return configuration record for the v5 declaration to the caller.
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
    # Use the absence path when declaration.unit has no available value.
    if declaration.unit is None:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise project.DeclarationError(_MISSING_UNIT_CODE, source, _MISSING_UNIT_DETAIL)
    # Return required unit kind to the caller.
    return declaration.unit


def _load_context(root: Path, scratch: Path) -> tuple[StepResult, GateContext | None]:
    """Load one exact-root declaration and expose its content binding.

    @param root governed repository root
    @param scratch ephemeral gate workspace
    @return declaration outcome and context, or no context after refusal
    """
    # Compute started using time.perf counter for later load context logic.
    started = time.perf_counter()
    # Retain the immutable source representation consumed by subsequent analysis.
    source = root / "pyproject.toml"
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute declaration using describe for later load context logic.
        declaration = describe(root, source)
        # Compute declared unit using  required unit for later load context logic.
        declared_unit = _required_unit(declaration, source)
        # Hold the decoded mapping elements whose keys identify fields and values carry their
        # Details: content; key order is deliberately unused.
        document = cast(
            "Mapping[str, object]",
            tomllib.loads(source.read_text(encoding="utf-8")),
        )
        # Compute use using  project use for later load context logic.
        use = _project_use(root)
    # Bind problem to the current value used by the next load context decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (OSError, project.DeclarationError, ValueError) as problem:
        # Compute duration using round for later load context logic.
        duration = round((time.perf_counter() - started) * 1000)
        # Compute diagnostic using getattr for later load context logic.
        diagnostic = getattr(problem, "diagnostic_id", "GATE001_DECLARATION")
        # Capture result as the completed load context outcome for subsequent validation or
        # Details: publication.
        result = StepResult(
            step_id="declaration",
            rules=("DOC-014", "FLOW-006"),
            status=Status.FAIL,
            required=True,
            diagnostic_id=str(diagnostic),
            summary=f"exact-root v5 declaration refused: {problem}",
            duration_ms=duration,
        )
        # Return declaration outcome and context, or no context after refusal to the caller.
        return result, None

    # Compute duration using round for later load context logic.
    duration = round((time.perf_counter() - started) * 1000)
    # Capture result as the completed load context outcome for subsequent validation or
    # Details: publication.
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
    # Return declaration outcome and context, or no context after refusal to the caller.
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
    # Select the guarded path only after `len(findings) > len(rendered)` is satisfied.
    if len(findings) > len(rendered):
        rendered.append(f"... {len(findings) - len(rendered)} additional finding(s)")
    # Return at most the first fifty rendered findings to the caller.
    return "\n".join(rendered)


def _run_discipline_checks(context: GateContext) -> StepResult:
    """Run every shipped check with the same explicit declaration instance.

    @param context exact repository declaration and bounded source roots
    @return pass over a non-empty subject or the emitted findings
    """
    # Compute started using time.perf counter for later run discipline checks logic.
    started = time.perf_counter()
    # Preserve paths element values in deterministic source order.
    paths = list(context.declaration.source_paths())
    # Compute checks using discover for later run discipline checks logic.
    checks = discover()
    # Each findings element is one emitted diagnostic mapping; checker order is preserved.
    findings: list[Finding] = []
    # Select check as the current element from checks while run discipline checks preserves
    # Details: traversal order.
    # Advance run discipline checks through the current input element in declared order.
    for check in checks:
        # Update  run discipline checks state only after the required source facts are
        # Details: available.
        check.declaration = context.declaration
        findings.extend(check.run(paths))
    # Compute source files using len for later run discipline checks logic.
    source_files = len(governed_paths(context.declaration, paths))
    # Compute duration using round for later run discipline checks logic.
    duration = round((time.perf_counter() - started) * 1000)
    # Select the guarded path only after `source_files == 0` is satisfied.
    if source_files == 0:
        # Return pass over a non-empty subject or the emitted findings to the caller.
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
    # Handle the non-empty or enabled findings state.
    if findings:
        # Return pass over a non-empty subject or the emitted findings to the caller.
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
    # Return pass over a non-empty subject or the emitted findings to the caller.
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
        # Return aggregate custom-check result to the caller.
        return _run_discipline_checks(context)


class ConfigurationProbeError(ValueError):
    """A required tool field is missing, malformed, or points outside the root."""

    def __init__(self, field: str, detail: str) -> None:
        """Preserve the exact field for a stable gate diagnostic.

        @param field dotted configuration field
        @param detail actionable refusal reason
        """
        super().__init__(f"{field}: {detail}")
        # Update   init   state only after the required source facts are available.
        self.field = field
        # Update   init   state only after the required source facts are available.
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
    # Return typed refusal to the caller.
    return ConfigurationProbeError(field, detail)


def _raise_probe(field: str, detail: str) -> Never:
    """Raise a configuration refusal from already-named values.

    @param field exact dotted configuration field
    @param detail actionable refusal reason
    @return never; always raises
    @throws ConfigurationProbeError unconditionally
    """
    # Propagate the localized failure so callers cannot mistake it for success.
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
    # Select segment as the current element from path while table preserves traversal order.
    # Advance table through the current input element in declared order.
    for segment in path:
        traversed.append(segment)
        # Select the empty-or-disabled path when isinstance(current, Mapping) or segment not in
        # Details: current has no usable value.
        if not isinstance(current, Mapping) or segment not in current:
            # Compute field using ".".join(traversed) for later table logic.
            field = ".".join(traversed)
            # Propagate the localized failure so callers cannot mistake it for success.
            raise _probe_error(field, "required table is absent")
        # Preserve the documentation-stripped behavior fingerprint used for comparison.
        current = current[segment]
    # Select the empty-or-disabled path when isinstance(current, Mapping) has no usable value.
    if not isinstance(current, Mapping):
        # Compute field using ".".join(path) for later table logic.
        field = ".".join(path)
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(field, "expected a table")
    # Return nested table to the caller.
    return cast("Mapping[str, object]", current)


def _string_list(value: object, field: str) -> tuple[str, ...]:
    """Parse a non-empty path list, accepting mypy's single-string shorthand.

    @param value decoded TOML value
    @param field dotted field name
    @return non-empty strings
    @throws ConfigurationProbeError on an empty or non-string member
    """
    # Compute values using [value] if isinstance(value, str) else value for later string list
    # Details: logic.
    values: object = [value] if isinstance(value, str) else value
    # Select the empty-or-disabled path when isinstance(values, list) or not values has no
    # Details: usable value.
    if not isinstance(values, list) or not values:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(field, "expected a non-empty string array")
    # Treat the current item as the candidate element consumed by the enclosing transformation.
    # Select the empty-or-disabled path when all((isinstance(item, str) and item.strip() for
    # Details: item in values)) has no usable value.
    if not all(isinstance(item, str) and item.strip() for item in values):
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(field, "every target must be a non-empty string")
    # Return non-empty strings to the caller.
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
    # Treat the current value as the candidate element consumed by the enclosing transformation.
    # Advance local targets through the current input element in declared order.
    for value in values:
        # Retain the immutable source representation consumed by subsequent analysis.
        raw = Path(value)
        # Treat the current candidate as the candidate element consumed by the enclosing
        # Details: transformation.
        candidate = (context.root / raw).resolve()
        # Select the guarded path only after `raw.is_absolute() or not
        # Details: candidate.is_relative_to(context.root)` is satisfied.
        if raw.is_absolute() or not candidate.is_relative_to(context.root):
            # Propagate the localized failure so callers cannot mistake it for success.
            raise _probe_error(field, f"target {value!r} escapes the governed repository")
        # Select the existing-artifact path only when `not candidate.exists()` is satisfied.
        if not candidate.exists():
            # Propagate the localized failure so callers cannot mistake it for success.
            raise _probe_error(field, f"target {value!r} does not exist")
        normalized.append(candidate.relative_to(context.root).as_posix())
        # Compute candidates using candidate.rglob for later local targets logic.
        candidates = candidate.rglob("*.py") if candidate.is_dir() else (candidate,)
        # Resolve the repository-confined path used by this operation before filesystem access.
        files.update(path.resolve() for path in candidates if path.is_file())
    # Select the empty-or-disabled path when files has no usable value.
    if not files:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(field, "configured targets contain no Python files")
    # Return normalized command targets and distinct Python file count to the caller.
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
    # Return content-bound configuration record to the caller.
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
    # Select the empty-or-disabled path when isinstance(value, str) or not value.strip() has no
    # Details: usable value.
    if not isinstance(value, str) or not value.strip():
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(field, "expected a non-empty repository-relative file")
    # Retain the immutable source representation consumed by subsequent analysis.
    raw = Path(value)
    # Treat the current candidate as the candidate element consumed by the enclosing
    # Details: transformation.
    candidate = (context.root / raw).resolve()
    # Select the guarded path only after `raw.is_absolute() or not
    # Details: candidate.is_relative_to(context.root)` is satisfied.
    if raw.is_absolute() or not candidate.is_relative_to(context.root):
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(field, f"file {value!r} escapes the governed repository")
    # Select the regular-file path only when `not candidate.is_file()` is satisfied.
    if not candidate.is_file():
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(field, f"file {value!r} does not exist")
    # Compute use using ConfigurationUse for later relative configuration file logic.
    use = ConfigurationUse(
        path=candidate.relative_to(context.root).as_posix(),
        sha256=_digest(candidate),
        fields=tuple(consumed_fields),
    )
    # Return absolute file and content-bound use record to the caller.
    return candidate, use


def _gate_table(context: GateContext) -> Mapping[str, object]:
    """Required project-gate configuration distinct from the doctrine declaration.

    @param context decoded exact-root project file
    @return ``tool.agent-discipline-gate`` table
    """
    # Return ``tool.agent-discipline-gate`` table to the caller.
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
    # Select the guarded path only after `table.get(key) != expected` is satisfied.
    if table.get(key) != expected:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(field, f"expected {expected!r}, found {table.get(key)!r}")


def _prepare_ruff(context: GateContext) -> PreparedCommand:
    """Prove Ruff configuration and targets before constructing its argv.

    @param context exact governed repository
    @return explicit Ruff command
    """
    # Compute table using  table for later prepare ruff logic.
    table = _table(context.pyproject, ("tool", "ruff"))
    # Preserve governed Python-path elements in deterministic traversal order.
    targets, subjects = _local_targets(
        context,
        _string_list(table.get("src"), "tool.ruff.src"),
        "tool.ruff.src",
    )
    # Compute use using  project configuration for later prepare ruff logic.
    use = _project_configuration(context, ("tool.ruff", "tool.ruff.src"))
    # Return explicit Ruff command to the caller.
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
    # Resolve the repository-confined path used by this operation before filesystem access.
    # Return non-empty POSIX paths to the caller.
    return tuple(
        path.resolve().relative_to(context.root).as_posix()
        for path in context.declaration.source_paths()
    )


def _prepare_mypy(context: GateContext) -> PreparedCommand:
    """Prove strict mypy configuration and a non-empty explicit target set.

    @param context exact governed repository
    @return explicit mypy command
    """
    # Compute table using  table for later prepare mypy logic.
    table = _table(context.pyproject, ("tool", "mypy"))
    _require_value(
        table=table,
        key="strict",
        expected=True,
        field="tool.mypy.strict",
    )
    # Compute raw targets using ( for later prepare mypy logic.
    raw_targets = (
        _string_list(table["files"], "tool.mypy.files")
        if "files" in table
        else _declared_source_targets(context)
    )
    # Preserve governed Python-path elements in deterministic traversal order.
    targets, subjects = _local_targets(context, raw_targets, "tool.mypy.files")
    # Compute use using  project configuration for later prepare mypy logic.
    use = _project_configuration(
        context,
        ("tool.mypy", "tool.mypy.strict", "tool.mypy.files"),
    )
    # Return explicit mypy command to the caller.
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
    # Compute table using  table for later prepare pyright logic.
    table = _table(context.pyproject, ("tool", "pyright"))
    _require_value(table, "typeCheckingMode", "strict", "tool.pyright.typeCheckingMode")
    # Preserve governed Python-path elements in deterministic traversal order.
    targets, subjects = _local_targets(
        context,
        _string_list(table.get("include"), "tool.pyright.include"),
        "tool.pyright.include",
    )
    # Compute use using  project configuration for later prepare pyright logic.
    use = _project_configuration(
        context,
        ("tool.pyright", "tool.pyright.typeCheckingMode", "tool.pyright.include"),
    )
    # Return explicit pyright command requesting machine-readable output to the caller.
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
    # Compute table using  table for later prepare pytest logic.
    table = _table(context.pyproject, ("tool", "pytest", "ini_options"))
    # Preserve governed Python-path elements in deterministic traversal order.
    targets, subjects = _local_targets(
        context,
        _string_list(table.get("testpaths"), "tool.pytest.ini_options.testpaths"),
        "tool.pytest.ini_options.testpaths",
    )
    # Compute timeout using table.get for later prepare pytest logic.
    timeout = table.get("timeout")
    # Select the empty-or-disabled path when isinstance(timeout, (int, float)) or
    # Details: isinstance(timeout, bool) or timeout <= 0 has no usable value.
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        _raise_probe(
            "tool.pytest.ini_options.timeout",
            "expected a positive per-test timeout",
        )
    # Select the guarded path only after `table.get('timeout_method') != 'thread'` is satisfied.
    if table.get("timeout_method") != "thread":
        _raise_probe(
            "tool.pytest.ini_options.timeout_method",
            "expected 'thread', the common Windows/Linux timeout method",
        )
    # Compute addopts using  string list for later prepare pytest logic.
    addopts = _string_list(table.get("addopts"), "tool.pytest.ini_options.addopts")
    # Select the guarded path only after `'--disable-socket' not in addopts` is satisfied.
    if "--disable-socket" not in addopts:
        _raise_probe(
            "tool.pytest.ini_options.addopts",
            "expected --disable-socket so ordinary pytest invocations fail closed",
        )
    # Compute use using  project configuration for later prepare pytest logic.
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
    # Return explicit pytest command to the caller.
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
    # Compute roles using  table for later prepare mutation logic.
    roles = _table(context.pyproject, ("tool", "agent-discipline", "roles"))
    # Unpack domain files, domains using  local targets for later prepare mutation logic.
    domains, domain_files = _local_targets(
        context,
        _string_list(
            roles.get("domain"),
            "tool.agent-discipline.roles.domain",
        ),
        "tool.agent-discipline.roles.domain",
    )
    # Compute mutation using  table for later prepare mutation logic.
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
    # Compute mutant timeout using mutation.get for later prepare mutation logic.
    mutant_timeout = mutation.get("mutant_timeout")
    # Select the empty-or-disabled path when isinstance(mutant timeout, (int, float)) or
    # Details: isinstance(mutant timeout, bool) or mutant timeout <= 0 has no usable value.
    if (
        not isinstance(mutant_timeout, (int, float))
        or isinstance(mutant_timeout, bool)
        or mutant_timeout <= 0
    ):
        _raise_probe(
            "tool.agent-discipline-gate.mutation.mutant_timeout",
            "expected a positive per-mutant test timeout",
        )
    # Compute command timeout using mutation.get for later prepare mutation logic.
    command_timeout = mutation.get("command_timeout")
    # Select the empty-or-disabled path when isinstance(command timeout, int) or
    # Details: isinstance(command timeout, bool) or command timeout <= 0 has no usable value.
    if (
        not isinstance(command_timeout, int)
        or isinstance(command_timeout, bool)
        or command_timeout <= 0
    ):
        _raise_probe(
            "tool.agent-discipline-gate.mutation.command_timeout",
            "expected a positive integer command timeout",
        )
    # Compute maximum survival using mutation.get for later prepare mutation logic.
    maximum_survival = mutation.get("maximum_survival")
    # Select the empty-or-disabled path when isinstance(maximum survival, (int, float)) or
    # Details: isinstance(maximum survival, bool) or maximum survival < 0 or
    # Details: (maximum survival > 0) has no usable value.
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
    # Compute use using  project configuration for later prepare mutation logic.
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
    # Return explicit portable mutation-gate command to the caller.
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
    # Return true only for a positive subject count to the caller.
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
    # Locate the structural boundary used to parse the external result safely.
    start = execution.output.find("{")
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Hold the decoded checker report mapping for typed summary and diagnostic extraction.
        report = json.loads(execution.output[start:]) if start >= 0 else None
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except json.JSONDecodeError:
        # Hold the decoded checker report mapping for typed summary and diagnostic extraction.
        report = None
    # Select the empty-or-disabled path when isinstance(report, Mapping) has no usable value.
    if not isinstance(report, Mapping):
        # Return pass or exact mutation failure to the caller.
        return Evaluation(
            "MUTATION-006_REPORT",
            "mutation gate emitted no parseable JSON report",
            _tail(execution.output),
        )
    # Compute diagnostic using report.get for later mutation evaluation logic.
    diagnostic = report.get("diagnostic_id")
    # Capture status as the completed mutation evaluation outcome for subsequent validation or
    # Details: publication.
    status = report.get("status")
    # Compute mutants using report.get for later mutation evaluation logic.
    mutants = report.get("mutants")
    # Compute domains using report.get for later mutation evaluation logic.
    domains = report.get("domains")
    # Enter the failure path only when the subprocess reports a nonzero status.
    if execution.returncode != 0 or status != "pass":
        # Capture code as the completed mutation evaluation outcome for subsequent validation or
        # Details: publication.
        code = diagnostic if isinstance(diagnostic, str) else command.failure_diagnostic
        # Return pass or exact mutation failure to the caller.
        return Evaluation(
            code,
            str(report.get("summary", "mutation gate failed without a summary")),
            str(report.get("output", _tail(execution.output))),
        )
    # Select the empty-or-disabled path when  positive count(mutants) or not  positive
    # Details: count(domains) has no usable value.
    if not _positive_count(mutants) or not _positive_count(domains):
        # Return pass or exact mutation failure to the caller.
        return Evaluation(
            "MUTATION-007_NO_MUTANTS",
            "mutation gate reported success without positive mutant and domain counts",
            _tail(execution.output),
        )
    # Return pass or exact mutation failure to the caller.
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
    # Compute relative using Path for later import root present logic.
    relative = Path(*package.split("."))
    # Retain the immutable source representation consumed by subsequent analysis.
    # Refuse the target when its declared source directory is absent.
    if any(
        (
            (context.root / source / relative).is_dir()
            or (context.root / source / relative).with_suffix(".py").is_file()
        )
        for source in source_roots
    ):
        # Return the completed  import root present result to its caller.
        return
    # Propagate the localized failure so callers cannot mistake it for success.
    raise _probe_error(
        field,
        f"root package {package!r} is absent from declared source roots {source_roots}",
    )


def _prepare_import_contracts(context: GateContext) -> PreparedCommand:
    """Bind import-linter to its declared config, contracts, and source roots.

    @param context exact governed repository
    @return explicit portable wrapper command
    """
    # Compute gate using  gate table for later prepare import contracts logic.
    gate = _gate_table(context)
    # Unpack config, config use using  relative configuration file for later prepare import
    # Details: contracts logic.
    config, config_use = _relative_configuration_file(
        context,
        gate.get("import_contracts"),
        "tool.agent-discipline-gate.import_contracts",
        ("tool.importlinter.root_packages", "tool.importlinter.contracts"),
    )
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Hold the decoded mapping elements whose keys identify fields and values carry their
        # Details: content; key order is deliberately unused.
        document = cast(
            "Mapping[str, object]",
            tomllib.loads(config.read_text(encoding="utf-8")),
        )
    # Bind problem to the current value used by the next prepare import contracts decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (OSError, tomllib.TOMLDecodeError) as problem:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(config_use.path, f"cannot parse TOML: {problem}") from problem
    # Compute table using  table for later prepare import contracts logic.
    table = _table(document, ("tool", "importlinter"))
    # Compute packages using  string list for later prepare import contracts logic.
    packages = _string_list(
        table.get("root_packages"),
        "tool.importlinter.root_packages",
    )
    # Compute contracts field using "tool.importlinter.contracts" for later prepare import
    # Details: contracts logic.
    contracts_field = "tool.importlinter.contracts"
    # Compute contracts using table.get for later prepare import contracts logic.
    contracts = table.get("contracts")
    # Select the empty-or-disabled path when isinstance(contracts, list) or not contracts has no
    # Details: usable value.
    if not isinstance(contracts, list) or not contracts:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(
            contracts_field,
            "expected one or more contract tables",
        )
    # Select contract as the current element from contracts) while prepare import contracts
    # Details: preserves traversal order.
    # Select the empty-or-disabled path when all((isinstance(contract, Mapping) for contract in
    # Details: contracts)) has no usable value.
    if not all(isinstance(contract, Mapping) for contract in contracts):
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(contracts_field, "every contract must be a table")
    # Compute source roots using  declared source targets for later prepare import contracts
    # Details: logic.
    source_roots = _declared_source_targets(context)
    # Select package as the current element from packages while prepare import contracts
    # Details: preserves traversal order.
    # Advance prepare import contracts through the current input element in declared order.
    for package in packages:
        _import_root_present(
            context,
            package,
            source_roots,
            "tool.importlinter.root_packages",
        )
    # Compute gate use using  project configuration for later prepare import contracts logic.
    gate_use = _project_configuration(
        context,
        ("tool.agent-discipline-gate.import_contracts", "tool.agent-discipline.source_roots"),
    )
    # Retain the immutable source representation consumed by subsequent analysis.
    source_arguments = tuple(item for source in source_roots for item in ("--source-root", source))
    # Return explicit portable wrapper command to the caller.
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
    # Select the guarded path only after `len(matches) != 1` is satisfied.
    if len(matches) != 1:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(field, f"expected exactly one {key} assignment")
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute values using tuple for later doxygen values logic.
        values = tuple(shlex.split(matches[0], comments=True, posix=True))
    # Bind problem to the current value used by the next doxygen values decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except ValueError as problem:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(field, f"cannot parse {key}: {problem}") from problem
    # Select the empty-or-disabled path when values has no usable value.
    if not values:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(field, f"{key} has no value")
    # Return shell-like tokens after the equals sign to the caller.
    return values


def _prepare_doxygen(context: GateContext) -> DoxygenPlan:
    """Bind Doxygen to the declared source roots and warning posture.

    @param context exact governed repository
    @return configuration-probed build plan
    """
    # Compute gate using  gate table for later prepare doxygen logic.
    gate = _gate_table(context)
    # Unpack doxyfile, doxyfile use using  relative configuration file for later prepare doxygen
    # Details: logic.
    doxyfile, doxyfile_use = _relative_configuration_file(
        context,
        gate.get("doxyfile"),
        "tool.agent-discipline-gate.doxyfile",
        ("INPUT", "FILE_PATTERNS", "WARN_AS_ERROR", "GENERATE_HTML"),
    )
    # Retain the immutable source representation consumed by subsequent analysis.
    text = doxyfile.read_text(encoding="utf-8")
    # Compute input field using "Doxyfile.INPUT" for later prepare doxygen logic.
    input_field = "Doxyfile.INPUT"
    # Unpack inputs, subjects using  local targets for later prepare doxygen logic.
    inputs, subjects = _local_targets(
        context,
        _doxygen_values(text, "INPUT", input_field),
        input_field,
    )
    # Compute declared using  declared source targets for later prepare doxygen logic.
    declared = _declared_source_targets(context)
    # Select the guarded path only after `set(inputs) != set(declared)` is satisfied.
    if set(inputs) != set(declared):
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(
            input_field,
            f"expected declared source roots {declared}, found {inputs}",
        )
    # Compute patterns field using "Doxyfile.FILE_PATTERNS" for later prepare doxygen logic.
    patterns_field = "Doxyfile.FILE_PATTERNS"
    # Compute patterns using  doxygen values for later prepare doxygen logic.
    patterns = _doxygen_values(text, "FILE_PATTERNS", patterns_field)
    # Select the guarded path only after `'*.py' not in patterns` is satisfied.
    if "*.py" not in patterns:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(patterns_field, "*.py is required")
    # Compute warning field using "Doxyfile.WARN_AS_ERROR" for later prepare doxygen logic.
    warning_field = "Doxyfile.WARN_AS_ERROR"
    # Compute warnings using  doxygen values for later prepare doxygen logic.
    warnings = _doxygen_values(text, "WARN_AS_ERROR", warning_field)
    # Select the guarded path only after `warnings != ('FAIL_ON_WARNINGS',)` is satisfied.
    if warnings != ("FAIL_ON_WARNINGS",):
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(warning_field, "expected FAIL_ON_WARNINGS")
    # Compute html field using "Doxyfile.GENERATE_HTML" for later prepare doxygen logic.
    html_field = "Doxyfile.GENERATE_HTML"
    # Compute html using  doxygen values for later prepare doxygen logic.
    html = _doxygen_values(text, "GENERATE_HTML", html_field)
    # Select the guarded path only after `html != ('YES',)` is satisfied.
    if html != ("YES",):
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(html_field, "expected YES")
    # Compute gate use using  project configuration for later prepare doxygen logic.
    gate_use = _project_configuration(
        context,
        (
            "tool.agent-discipline.doc_engine",
            "tool.agent-discipline.source_roots",
            "tool.agent-discipline-gate.doxyfile",
        ),
    )
    # Return configuration-probed build plan to the caller.
    return DoxygenPlan(doxyfile, (gate_use, doxyfile_use), subjects)


def _native_executable(name: str) -> str | None:
    """Resolve one native tool on the active environment path.

    @param name executable basename
    @return absolute or launchable path, or None
    """
    # Return absolute or launchable path, or None to the caller.
    return shutil.which(name)


def _native_version(executable: str) -> str:
    """Obtain a bounded native-tool version string.

    @param executable resolved tool path
    @return first non-empty version line
    @throws CommandExecutionError when the probe fails
    """
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Preserve the external command representation and its observed completion outcome.
        finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            (executable, "--version"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
    # Bind problem to the current value used by the next native version decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (OSError, subprocess.TimeoutExpired) as problem:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise CommandExecutionError(str(problem)) from problem
    # Enter the failure path only when the subprocess reports a nonzero status.
    if finished.returncode != 0:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise CommandExecutionError(_tail(finished.stdout + finished.stderr))
    # Return first non-empty version line to the caller.
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
    # Compute configuration using ( for later execute doxygen logic.
    configuration = (
        plan.configuration_file.read_text(encoding="utf-8")
        + f"\nOUTPUT_DIRECTORY = {output.as_posix()}\n"
    )
    # Compute started using time.perf counter for later execute doxygen logic.
    started = time.perf_counter()
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Preserve the external command representation and its observed completion outcome.
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
    # Bind problem to the current value used by the next execute doxygen decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (OSError, subprocess.TimeoutExpired) as problem:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise CommandExecutionError(str(problem)) from problem
    # Compute duration using round for later execute doxygen logic.
    duration = round((time.perf_counter() - started) * 1000)
    # Preserve the external command representation and its observed completion outcome.
    process = CommandExecution(
        finished.returncode,
        finished.stdout + finished.stderr,
        duration,
    )
    # Return process observation and generated page count to the caller.
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
    # Compute use using  project configuration for later documentation configuration failure
    # Details: logic.
    use = _project_configuration(context, (problem.field,))
    # Return red result to the caller.
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
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute plan using  prepare doxygen for later run doxygen documentation logic.
        plan = _prepare_doxygen(context)
    # Bind problem to the current value used by the next run doxygen documentation decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except ConfigurationProbeError as problem:
        # Return explicit Doxygen outcome to the caller.
        return _documentation_configuration_failure(context, rules, problem)
    # Resolve the qualified native Doxygen executable required by this gate.
    executable = _native_executable("doxygen")
    # Use the absence path when executable has no available value.
    if executable is None:
        # Return explicit Doxygen outcome to the caller.
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
    # Compute version using "unknown" for later run doxygen documentation logic.
    version = "unknown"
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute version using  native version for later run doxygen documentation logic.
        version = _native_version(executable)
        # Preserve the external command representation and its observed completion outcome.
        execution = _execute_doxygen(executable, plan, context)
    # Bind problem to the current value used by the next run doxygen documentation decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except CommandExecutionError as problem:
        # Return explicit Doxygen outcome to the caller.
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
    # Preserve the external command representation and its observed completion outcome.
    process = execution.process
    # Enter the failure path only when the subprocess reports a nonzero status.
    if process.returncode != 0:
        # Return explicit Doxygen outcome to the caller.
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
    # Select the guarded path only after `execution.pages < plan.subjects` is satisfied.
    if execution.pages < plan.subjects:
        # Return explicit Doxygen outcome to the caller.
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
    # Return explicit Doxygen outcome to the caller.
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
        # Select the guarded path only after `platform.system() not in {'Windows', 'Linux'}` is
        # Details: satisfied.
        if platform.system() not in {"Windows", "Linux"}:
            # Return explicit build, inapplicability, or support outcome to the caller.
            return StepResult(
                step_id=self.step_id,
                rules=self.rules,
                status=Status.UNSUPPORTED,
                required=True,
                diagnostic_id="GATE-DOCUMENTATION-005_PLATFORM",
                summary=f"documentation builds are not release-supported on {platform.system()}",
            )
        # Return explicit build, inapplicability, or support outcome to the caller.
        return _run_doxygen_documentation(context, self.rules)


class ArtifactError(ValueError):
    """A build or installed-artifact proof is malformed or inconsistent."""


def _artifact_error(detail: str) -> ArtifactError:
    """Build an artifact refusal from already-localized detail.

    @param detail actionable artifact inconsistency
    @return typed refusal
    """
    # Return typed refusal to the caller.
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
    # Preserve directory, files, names element values in deterministic source order.
    # Advance copy isolated through the current input element in declared order.
    for directory, names, files in os.walk(root):
        # Normalize the current repository path to its portable baseline key spelling.
        # Update  copy isolated state only after the required source facts are available.
        names[:] = [name for name in names if name not in _ISOLATION_EXCLUDES]
        # Preserve the documentation-stripped behavior fingerprint used for comparison.
        current = Path(directory)
        # Normalize the current repository path to its portable baseline key spelling.
        # Advance copy isolated through the current input element in declared order.
        for name in (*names, *files):
            # Resolve the repository-confined path used by this operation before filesystem
            # Details: access.
            path = current / name
            # Select the guarded path only after `path.is_symlink()` is satisfied.
            if path.is_symlink():
                # Compute relative using path.relative to for later copy isolated logic.
                relative = path.relative_to(root).as_posix()
                # Compute detail using f"build isolation refuses symlink {relative!r};
                # Details: materialize  for later copy isolated logic.
                detail = f"build isolation refuses symlink {relative!r}; materialize or package it"
                # Propagate the localized failure so callers cannot mistake it for success.
                raise _artifact_error(detail)
    shutil.copytree(
        root,
        destination,
        ignore=shutil.ignore_patterns(*_ISOLATION_EXCLUDES),
    )
    # Resolve the repository-confined path used by this operation before filesystem access.
    # Return copied regular-file count to the caller.
    return sum(1 for path in destination.rglob("*") if path.is_file())


def _project_identity(context: GateContext) -> tuple[str, str]:
    """Read the required PEP 621 distribution identity.

    @param context decoded exact-root project
    @return name and version
    @throws ConfigurationProbeError when either is absent
    """
    # Compute table using  table for later project identity logic.
    table = _table(context.pyproject, ("project",))
    # Normalize the current repository path to its portable baseline key spelling.
    name = table.get("name")
    # Compute version using table.get for later project identity logic.
    version = table.get("version")
    # Compute name field using "project.name" for later project identity logic.
    name_field = "project.name"
    # Compute version field using "project.version" for later project identity logic.
    version_field = "project.version"
    # Select the empty-or-disabled path when isinstance(name, str) or not name.strip() has no
    # Details: usable value.
    if not isinstance(name, str) or not name.strip():
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(name_field, "expected a non-empty distribution name")
    # Select the empty-or-disabled path when isinstance(version, str) or not version.strip() has
    # Details: no usable value.
    if not isinstance(version, str) or not version.strip():
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(version_field, "expected a static non-empty version")
    # Return name and version to the caller.
    return name.strip(), version.strip()


def _validate_build_system(context: GateContext) -> None:
    """Require a named backend and exact isolated-environment requirements.

    @param context decoded exact-root project
    @throws ConfigurationProbeError when backend selection can drift
    """
    # Compute table using  table for later validate build system logic.
    table = _table(context.pyproject, ("build-system",))
    # Compute backend using table.get for later validate build system logic.
    backend = table.get("build-backend")
    # Compute backend field using "build-system.build-backend" for later validate build system
    # Details: logic.
    backend_field = "build-system.build-backend"
    # Select the empty-or-disabled path when isinstance(backend, str) or not backend.strip() has
    # Details: no usable value.
    if not isinstance(backend, str) or not backend.strip():
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(backend_field, "expected a backend module")
    # Compute requirements field using "build-system.requires" for later validate build system
    # Details: logic.
    requirements_field = "build-system.requires"
    # Compute requirements using  string list for later validate build system logic.
    requirements = _string_list(table.get("requires"), requirements_field)
    # Each unpinned element is one inexact build requirement, retaining requirement order.
    unpinned = [
        requirement
        for requirement in requirements
        if _EXACT_BUILD_REQUIREMENT.fullmatch(requirement) is None
    ]
    # Handle the non-empty or enabled unpinned state.
    if unpinned:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(
            requirements_field,
            f"every build requirement must use one exact == version; found {unpinned}",
        )


def _prepare_build(context: GateContext) -> tuple[BuildPlan, PreparedCommand]:
    """Probe packaging config and create the repository-only build copy.

    @param context exact governed repository
    @return build plan and explicit PEP 517 command
    """
    # Normalize the current repository path to its portable baseline key spelling.
    name, version = _project_identity(context)
    _validate_build_system(context)
    # Retain the immutable source representation consumed by subsequent analysis.
    source = context.scratch / "isolated-source"
    # Compute artifacts using context.scratch / "artifacts" for later prepare build logic.
    artifacts = context.scratch / "artifacts"
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute subjects using  copy isolated for later prepare build logic.
        subjects = _copy_isolated(context.root, source)
    # Bind problem to the current value used by the next prepare build decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except ArtifactError as problem:
        # Compute build inputs field using "repository.build_inputs" for later prepare build
        # Details: logic.
        build_inputs_field = "repository.build_inputs"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(build_inputs_field, str(problem)) from problem
    # Compute use using  project configuration for later prepare build logic.
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
    # Compute plan using BuildPlan for later prepare build logic.
    plan = BuildPlan(source, artifacts, name, version, subjects, (use,))
    # Preserve the external command representation and its observed completion outcome.
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
    # Return build plan and explicit PEP 517 command to the caller.
    return plan, command


def _canonical_distribution(name: str) -> str:
    """Normalize distribution punctuation for metadata comparison.

    @param name PEP 503-like distribution name
    @return lowercase name with one hyphen per punctuation run
    """
    # Return lowercase name with one hyphen per punctuation run to the caller.
    return re.sub(r"[-_.]+", "-", name).lower()


def _metadata_identity(content: bytes, source: str) -> tuple[str, str]:
    """Read Name and Version from core metadata bytes.

    @param content METADATA or PKG-INFO bytes
    @param source artifact/member label
    @return distribution name and version
    @throws ArtifactError when required fields are absent
    """
    # Compute message using BytesParser for later metadata identity logic.
    message = BytesParser(policy=email_policy).parsebytes(content)
    # Normalize the current repository path to its portable baseline key spelling.
    name = message.get("Name")
    # Compute version using message.get for later metadata identity logic.
    version = message.get("Version")
    # Select the empty-or-disabled path when name or not version has no usable value.
    if not name or not version:
        # Compute detail using f"{source} has no complete Name/Version metadata" for later
        # Details: metadata identity logic.
        detail = f"{source} has no complete Name/Version metadata"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _artifact_error(detail)
    # Return distribution name and version to the caller.
    return str(name), str(version)


def _wheel_identity(path: Path) -> tuple[str, str]:
    """Read the one wheel core-metadata record without importing the package.

    @param path wheel archive
    @return distribution name and version
    @throws ArtifactError when membership or metadata is malformed
    """
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Bind archive to the current value used by the next wheel identity decision.
        # Confine the acquired resource to this operation and release it on every exit.
        with zipfile.ZipFile(path) as archive:
            # Each members element is one wheel metadata path, retained in archive order.
            members = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            # Select the guarded path only after `len(members) != 1` is satisfied.
            if len(members) != 1:
                # Compute detail using f"{path.name} contains {len(members)} METADATA files" for
                # Details: later wheel identity logic.
                detail = f"{path.name} contains {len(members)} METADATA files"
                # Propagate the localized failure so callers cannot mistake it for success.
                raise _artifact_error(detail)
            # Return distribution name and version to the caller.
            return _metadata_identity(archive.read(members[0]), f"{path.name}:{members[0]}")
    # Bind problem to the current value used by the next wheel identity decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (OSError, zipfile.BadZipFile, KeyError) as problem:
        # Compute detail using f"cannot read wheel {path.name}: {problem}" for later wheel
        # Details: identity logic.
        detail = f"cannot read wheel {path.name}: {problem}"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _artifact_error(detail) from problem


def _read_sdist_identity(path: Path) -> tuple[str, str]:
    """Read one root PKG-INFO member from an already-openable source archive.

    @param path gzipped tar source archive
    @return distribution name and version
    @throws ArtifactError when membership or metadata is malformed
    """
    # Compute archive using "r:gz") as archive: for later read sdist identity logic.
    # Confine the acquired resource to this operation and release it on every exit.
    with tarfile.open(path, mode="r:gz") as archive:
        # Each members element is one root-level package metadata member in archive order.
        members = [
            member
            for member in archive.getmembers()
            if member.isfile() and member.name.count("/") == 1 and member.name.endswith("/PKG-INFO")
        ]
        # Select the guarded path only after `len(members) != 1` is satisfied.
        if len(members) != 1:
            # Compute detail using f"{path.name} contains {len(members)} root PKG-INFO files"
            # Details: for later read sdist identity logic.
            detail = f"{path.name} contains {len(members)} root PKG-INFO files"
            # Propagate the localized failure so callers cannot mistake it for success.
            raise _artifact_error(detail)
        # Compute stream using archive.extractfile for later read sdist identity logic.
        stream = archive.extractfile(members[0])
        # Use the absence path when stream has no available value.
        if stream is None:
            # Compute detail using f"cannot read {path.name}:{members[0].name}" for later read
            # Details: sdist identity logic.
            detail = f"cannot read {path.name}:{members[0].name}"
            # Propagate the localized failure so callers cannot mistake it for success.
            raise _artifact_error(detail)
        # Return distribution name and version to the caller.
        return _metadata_identity(stream.read(), f"{path.name}:{members[0].name}")


def _sdist_identity(path: Path) -> tuple[str, str]:
    """Read source-distribution core metadata without extracting any member.

    @param path gzipped tar source archive
    @return distribution name and version
    @throws ArtifactError when membership or metadata is malformed
    """
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Return distribution name and version to the caller.
        return _read_sdist_identity(path)
    # Bind problem to the current value used by the next sdist identity decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (OSError, tarfile.TarError) as problem:
        # Compute detail using f"cannot read sdist {path.name}: {problem}" for later sdist
        # Details: identity logic.
        detail = f"cannot read sdist {path.name}: {problem}"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _artifact_error(detail) from problem


def _validate_artifacts(plan: BuildPlan) -> BuiltArtifacts:
    """Require one wheel and one sdist with the declared shared identity.

    @param plan expected identity and output directory
    @return validated artifact paths and identity
    @throws ArtifactError when count or metadata differs
    """
    # Compute wheels using sorted for later validate artifacts logic.
    wheels = sorted(plan.artifacts.glob("*.whl"))
    # Compute sdists using sorted for later validate artifacts logic.
    sdists = sorted(plan.artifacts.glob("*.tar.gz"))
    # Select the guarded path only after `len(wheels) != 1 or len(sdists) != 1` is satisfied.
    if len(wheels) != 1 or len(sdists) != 1:
        # Compute detail using f"expected one wheel and one sdist, found {len(wheels)} and  for
        # Details: later validate artifacts logic.
        detail = f"expected one wheel and one sdist, found {len(wheels)} and {len(sdists)}"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _artifact_error(detail)
    # Compute wheel identity using  wheel identity for later validate artifacts logic.
    wheel_identity = _wheel_identity(wheels[0])
    # Compute sdist identity using  sdist identity for later validate artifacts logic.
    sdist_identity = _sdist_identity(sdists[0])
    # Each expected element is respectively the canonical distribution name then exact version;
    # tuple order defines the artifact identity comparison.
    expected = (_canonical_distribution(plan.name), plan.version)
    # Each observed element is one artifact identity pair in wheel-before-sdist order.
    observed = (
        (_canonical_distribution(wheel_identity[0]), wheel_identity[1]),
        (_canonical_distribution(sdist_identity[0]), sdist_identity[1]),
    )
    # Select the guarded path only after `observed != (expected, expected)` is satisfied.
    if observed != (expected, expected):
        # Compute detail using f"expected artifact identity {expected}, found {observed}" for
        # Details: later validate artifacts logic.
        detail = f"expected artifact identity {expected}, found {observed}"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _artifact_error(detail)
    # Return validated artifact paths and identity to the caller.
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
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            # Preserve the external command representation and its observed completion outcome.
            plan, command = _prepare_build(context)
        # Bind problem to the current value used by the next call decision.
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except ConfigurationProbeError as problem:
            # Return explicit build outcome to the caller.
            return StepResult(
                step_id=self.step_id,
                rules=self.rules,
                status=Status.FAIL,
                required=True,
                diagnostic_id="GATE-BUILD-001_CONFIGURATION",
                summary=str(problem),
                configuration=(_project_configuration(context, (problem.field,)),),
            )
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            # Compute version using  distribution version for later call logic.
            version = _distribution_version("build")
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except importlib.metadata.PackageNotFoundError:
            # Return explicit build outcome to the caller.
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
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            # Preserve the external command representation and its observed completion outcome.
            execution = _execute(command, context.root)
        # Bind problem to the current value used by the next call decision.
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except CommandExecutionError as problem:
            # Return explicit build outcome to the caller.
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
        # Enter the failure path only when the subprocess reports a nonzero status.
        if execution.returncode != 0:
            # Return explicit build outcome to the caller.
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
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            # Compute artifacts using  validate artifacts for later call logic.
            artifacts = _validate_artifacts(plan)
        # Bind problem to the current value used by the next call decision.
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except ArtifactError as problem:
            # Return explicit build outcome to the caller.
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
        # Return explicit build outcome to the caller.
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
    # Select the guarded path only after `value is not None and (not isinstance(value, str))` is
    # Details: satisfied.
    if value is not None and not isinstance(value, str):
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(field, "must be text or absent")
    # Return exact text or absence to the caller.
    return value


def _artifact_probe(raw: object, field: str) -> ArtifactProbe:
    """Parse one exact installed-command probe.

    @param raw decoded TOML table
    @param field configuration location
    @return validated probe
    @throws ConfigurationProbeError when the declaration is unsafe or ambiguous
    """
    # Select the empty-or-disabled path when isinstance(raw, Mapping) has no usable value.
    if not isinstance(raw, Mapping):
        # Propagate the localized failure so callers cannot mistake it for success.
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
    # Compute unknown using set for later artifact probe logic.
    unknown = set(raw) - allowed
    # Handle the non-empty or enabled unknown state.
    if unknown:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(field, f"unknown fields {sorted(unknown)}")
    # Normalize the current repository path to its portable baseline key spelling.
    name = raw.get("name")
    # Compute expected using raw.get for later artifact probe logic.
    expected = raw.get("expected_exit", 0)
    # Compute timeout using raw.get for later artifact probe logic.
    timeout = raw.get("timeout_seconds", 10)
    # Select the empty-or-disabled path when isinstance(name, str) or not name.strip() has no
    # Details: usable value.
    if not isinstance(name, str) or not name.strip():
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(field, "name must be non-empty text")
    # Select the empty-or-disabled path when isinstance(expected, int) or isinstance(expected,
    # Details: bool) has no usable value.
    if not isinstance(expected, int) or isinstance(expected, bool):
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(field, "expected_exit must be an integer")
    # Select the empty-or-disabled path when (isinstance(timeout, int) and (not
    # Details: isinstance(timeout, bool)) and
    # Details: (1 <= timeout <=  MAX PROBE TIMEOUT)) has no usable value.
    if not (
        isinstance(timeout, int)
        and not isinstance(timeout, bool)
        and 1 <= timeout <= _MAX_PROBE_TIMEOUT
    ):
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(
            field,
            f"timeout_seconds must be between 1 and {_MAX_PROBE_TIMEOUT}",
        )
    # Return validated probe to the caller.
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
    # Compute gate using  gate table for later parse artifact probes logic.
    gate = _gate_table(context)
    # Compute import field using "tool.agent-discipline-gate.artifact_imports" for later parse
    # Details: artifact probes logic.
    import_field = "tool.agent-discipline-gate.artifact_imports"
    # Compute imports using  string list for later parse artifact probes logic.
    imports = _string_list(gate.get("artifact_imports"), import_field)
    # Each invalid element is one syntactically invalid import name in declaration order.
    invalid = [name for name in imports if _IMPORT_NAME.fullmatch(name) is None]
    # Handle the non-empty or enabled invalid state.
    if invalid:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(import_field, f"invalid import names {invalid}")
    # Compute probes field using "tool.agent-discipline-gate.artifact_probes" for later parse
    # Details: artifact probes logic.
    probes_field = "tool.agent-discipline-gate.artifact_probes"
    # Compute raw probes using gate.get for later parse artifact probes logic.
    raw_probes = gate.get("artifact_probes", [])
    # Select the empty-or-disabled path when isinstance(raw probes, list) has no usable value.
    if not isinstance(raw_probes, list):
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(probes_field, "expected an array")
    # Retain the immutable source representation consumed by subsequent analysis.
    probes = tuple(
        _artifact_probe(raw, f"{probes_field}[{index}]") for index, raw in enumerate(raw_probes)
    )
    # Select probe as the current element from probes}) != len(probes) while parse artifact
    # Details: probes preserves traversal order.
    # Select the guarded path only after `len({probe.name for probe in probes}) != len(probes)`
    # Details: is satisfied.
    if len({probe.name for probe in probes}) != len(probes):
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(probes_field, "probe names repeat")
    # Return import names and executable probes to the caller.
    return imports, probes


def _fresh_python(environment: Path) -> Path:
    """Locate the interpreter inside a fresh cross-platform virtual environment.

    @param environment virtual-environment root
    @return interpreter path
    """
    # Compute windows using environment / "Scripts" / "python.exe" for later fresh python logic.
    windows = environment / "Scripts" / "python.exe"
    # Return interpreter path to the caller.
    return windows if windows.is_file() else environment / "bin" / "python"


def _create_venv(environment: Path) -> Path:
    """Create a clean pip-bearing environment and return its interpreter.

    @param environment absent scratch directory
    @return fresh interpreter path
    @throws CommandExecutionError when creation is incomplete
    """
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
    # Bind problem to the current value used by the next create venv decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except OSError as problem:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise CommandExecutionError(str(problem)) from problem
    # Compute interpreter using  fresh python for later create venv logic.
    interpreter = _fresh_python(environment)
    # Select the regular-file path only when `not interpreter.is_file()` is satisfied.
    if not interpreter.is_file():
        # Compute detail using f"virtual environment has no interpreter at {interpreter}" for
        # Details: later create venv logic.
        detail = f"virtual environment has no interpreter at {interpreter}"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise CommandExecutionError(detail)
    # Return fresh interpreter path to the caller.
    return interpreter


def _probe_argv(probe: ArtifactProbe, interpreter: Path) -> tuple[str, ...]:
    """Resolve one probe strictly inside the fresh virtual environment.

    @param probe declared argv and expectation
    @param interpreter fresh environment Python
    @return executable argv
    @throws ConfigurationProbeError when the entry point is absent
    """
    # Compute scripts using interpreter.parent for later probe argv logic.
    scripts = interpreter.parent
    # Each resolved element is one command argument after interpreter substitution; declared
    # argument order is preserved.
    resolved = [
        str(interpreter) if argument == "{python}" else argument for argument in probe.command
    ]
    # Compute first using Path for later probe argv logic.
    first = Path(resolved[0])
    # Select the guarded path only after `resolved[0] == str(interpreter)` is satisfied.
    if resolved[0] == str(interpreter):
        # Return executable argv to the caller.
        return tuple(resolved)
    # Select the guarded path only after `first.is_absolute() or len(first.parts) != 1` is
    # Details: satisfied.
    if first.is_absolute() or len(first.parts) != 1:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(probe.name, "probe executable must be {python} or a venv entry point")
    # Each candidates element is an entry-point path, ordered as declared spelling then Windows
    # executable spelling.
    candidates = (scripts / first, (scripts / first).with_suffix(".exe"))
    # Resolve the repository-confined path used by this operation before filesystem access.
    executable = next((path for path in candidates if path.is_file()), None)
    # Use the absence path when executable has no available value.
    if executable is None:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _probe_error(probe.name, f"installed entry point {first} does not exist")
    # Return executable argv to the caller.
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
    # Compute prepared using PreparedCommand for later execute with timeout logic.
    prepared = PreparedCommand(command, (), 1, "", "probe")
    # Compute started using time.perf counter for later execute with timeout logic.
    started = time.perf_counter()
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Preserve the external command representation and its observed completion outcome.
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
    # Bind problem to the current value used by the next execute with timeout decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (OSError, subprocess.TimeoutExpired) as problem:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise CommandExecutionError(str(problem)) from problem
    # Return process observation to the caller.
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
    # Compute wheels using sorted for later prepare install logic.
    wheels = sorted((context.scratch / "artifacts").glob("*.whl"))
    # Select the guarded path only after `len(wheels) != 1` is satisfied.
    if len(wheels) != 1:
        # Return install plan or explicit preflight failure to the caller.
        return StepResult(
            step_id=step_id,
            rules=rules,
            status=Status.NOT_RUN,
            required=True,
            diagnostic_id="GATE-INSTALL-000_BUILD_REQUIRED",
            summary=f"expected one validated wheel from artifact-build, found {len(wheels)}",
        )
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Unpack imports, probes using  parse artifact probes for later prepare install logic.
        imports, probes = _parse_artifact_probes(context)
        # Normalize the current repository path to its portable baseline key spelling.
        name, version = _project_identity(context)
    # Bind problem to the current value used by the next prepare install decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except ConfigurationProbeError as problem:
        # Return install plan or explicit preflight failure to the caller.
        return StepResult(
            step_id=step_id,
            rules=rules,
            status=Status.FAIL,
            required=True,
            diagnostic_id="GATE-INSTALL-001_CONFIGURATION",
            summary=str(problem),
            configuration=(_project_configuration(context, (problem.field,)),),
        )
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute interpreter using  create venv for later prepare install logic.
        interpreter = _create_venv(context.scratch / "installed")
    # Bind problem to the current value used by the next prepare install decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except CommandExecutionError as problem:
        # Return install plan or explicit preflight failure to the caller.
        return StepResult(
            step_id=step_id,
            rules=rules,
            status=Status.FAIL,
            required=True,
            diagnostic_id="GATE-INSTALL-002_ENVIRONMENT",
            summary=f"cannot create clean environment: {problem}",
        )
    # Compute use using  project configuration for later prepare install logic.
    use = _project_configuration(
        context,
        (
            "project.dependencies",
            "tool.agent-discipline-gate.artifact_imports",
            "tool.agent-discipline-gate.artifact_probes",
        ),
    )
    # Compute install using PreparedCommand for later prepare install logic.
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
    # Return install plan or explicit preflight failure to the caller.
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
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute installed using  execute for later install wheel logic.
        installed = _execute(plan.install, context.scratch)
    # Bind problem to the current value used by the next install wheel decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except CommandExecutionError as problem:
        # Return process observation or explicit failure to the caller.
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
    # Enter the failure path only when the subprocess reports a nonzero status.
    if installed.returncode != 0:
        # Return process observation or explicit failure to the caller.
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
    # Return process observation or explicit failure to the caller.
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
    # Compute script using ( for later verify installed imports logic.
    script = (
        "import importlib, importlib.metadata as metadata; "
        f"assert metadata.version({plan.name!r}) == {plan.version!r}; "
        f"[importlib.import_module(name) for name in {plan.imports!r}]"
    )
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute imported using  execute with timeout for later verify installed imports logic.
        imported = _execute_with_timeout(
            (str(plan.interpreter), "-I", "-c", script),
            context.scratch,
            60,
        )
    # Bind problem to the current value used by the next verify installed imports decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except CommandExecutionError as problem:
        # Return accumulated duration or explicit failure to the caller.
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
    # Compute duration using installed.duration_ms + imported.duration_ms for later verify
    # Details: installed imports logic.
    duration = installed.duration_ms + imported.duration_ms
    # Enter the failure path only when the subprocess reports a nonzero status.
    if imported.returncode != 0:
        # Return accumulated duration or explicit failure to the caller.
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
    # Return accumulated duration or explicit failure to the caller.
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
    # Compute total using duration for later verify installed commands logic.
    total = duration
    # Select probe as the current element from plan.probes while verify installed commands
    # Details: preserves traversal order.
    # Advance verify installed commands through the current input element in declared order.
    for probe in plan.probes:
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            # Compute argv using  probe argv for later verify installed commands logic.
            argv = _probe_argv(probe, plan.interpreter)
            # Compute observed using  execute with timeout for later verify installed commands
            # Details: logic.
            observed = _execute_with_timeout(
                argv,
                context.scratch,
                probe.timeout_seconds,
                probe.stdin,
            )
        # Bind problem to the current value used by the next verify installed commands decision.
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except (ConfigurationProbeError, CommandExecutionError) as problem:
            # Return total duration or first explicit probe failure to the caller.
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
        # Compute total using observed.duration_ms for later verify installed commands logic.
        total += observed.duration_ms
        # Enter the failure path only when the subprocess reports a nonzero status.
        if observed.returncode != probe.expected_exit:
            # Return total duration or first explicit probe failure to the caller.
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
        # Select the guarded path only after `probe.expected_stdout is not None and
        # Details: observed.stdout != probe.expected_stdout` is satisfied.
        if probe.expected_stdout is not None and observed.stdout != probe.expected_stdout:
            mismatches.append("stdout")
        # Select the guarded path only after `probe.expected_stderr is not None and
        # Details: observed.stderr != probe.expected_stderr` is satisfied.
        if probe.expected_stderr is not None and observed.stderr != probe.expected_stderr:
            mismatches.append("stderr")
        # Handle the non-empty or enabled mismatches state.
        if mismatches:
            # Return total duration or first explicit probe failure to the caller.
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
    # Return total duration or first explicit probe failure to the caller.
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
        # Compute prepared using  prepare install for later call logic.
        prepared = _prepare_install(context, self.step_id, self.rules)
        # Select the guarded path only after `isinstance(prepared, StepResult)` is satisfied.
        if isinstance(prepared, StepResult):
            # Return explicit installation/probe outcome to the caller.
            return prepared
        # Compute installed using  install wheel for later call logic.
        installed = _install_wheel(context, prepared, self.step_id, self.rules)
        # Select the guarded path only after `isinstance(installed, StepResult)` is satisfied.
        if isinstance(installed, StepResult):
            # Return explicit installation/probe outcome to the caller.
            return installed
        # Compute imported using  verify installed imports for later call logic.
        imported = _verify_installed_imports(
            context,
            prepared,
            installed,
            self.step_id,
            self.rules,
        )
        # Select the guarded path only after `isinstance(imported, StepResult)` is satisfied.
        if isinstance(imported, StepResult):
            # Return explicit installation/probe outcome to the caller.
            return imported
        # Compute probed using  verify installed commands for later call logic.
        probed = _verify_installed_commands(
            context,
            prepared,
            imported,
            self.step_id,
            self.rules,
        )
        # Select the guarded path only after `isinstance(probed, StepResult)` is satisfied.
        if isinstance(probed, StepResult):
            # Return explicit installation/probe outcome to the caller.
            return probed
        # Treat the current index, value, probe as the candidate element consumed by the
        # Details: enclosing transformation.
        # Return explicit installation/probe outcome to the caller.
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
    # Compute started using time.perf counter for later execute logic.
    started = time.perf_counter()
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Preserve the external command representation and its observed completion outcome.
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
    # Bind problem to the current value used by the next execute decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (OSError, subprocess.TimeoutExpired) as problem:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise CommandExecutionError(str(problem)) from problem
    # Compute duration using round for later execute logic.
    duration = round((time.perf_counter() - started) * 1000)
    # Return process observation to the caller.
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
    # Return stripped tail to the caller.
    return output[-maximum:].strip()


def _last_line(output: str) -> str:
    """Last non-empty status line from a tool.

    @param output combined process output
    @return line or a visible no-output marker
    """
    # Each lines element represents one decoded record; lexical order is preserved.
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    # Return line or a visible no-output marker to the caller.
    return lines[-1] if lines else "completed with no textual output"


def _distribution_version(name: str) -> str:
    """Observed installed version behind an external mechanism.

    @param name distribution package name
    @return installed version
    @throws PackageNotFoundError when the tool is unavailable
    """
    # Return installed version to the caller.
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
    # Enter the failure path only when the subprocess reports a nonzero status.
    if execution.returncode != 0:
        # Return pass or tool-finding evaluation to the caller.
        return Evaluation(
            command.failure_diagnostic,
            f"tool rejected {command.subjects} {command.subject_label}",
            _tail(execution.output),
        )
    # Return pass or tool-finding evaluation to the caller.
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
    # Locate the structural boundary used to parse the external result safely.
    start = execution.output.find("{")
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Hold the decoded checker report mapping for typed summary and diagnostic extraction.
        report = json.loads(execution.output[start:]) if start >= 0 else None
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except json.JSONDecodeError:
        # Hold the decoded checker report mapping for typed summary and diagnostic extraction.
        report = None
    # Select the empty-or-disabled path when isinstance(report, Mapping) has no usable value.
    if not isinstance(report, Mapping):
        # Return pass, findings, or vacuity failure to the caller.
        return Evaluation(
            "GATE-PYRIGHT-004_REPORT",
            "pyright emitted no parseable JSON report",
            _tail(execution.output),
        )
    # Select the checker summary mapping that carries analyzed-file metrics.
    summary = report.get("summary")
    # Select the empty-or-disabled path when isinstance(summary, Mapping) has no usable value.
    if not isinstance(summary, Mapping):
        # Return pass, findings, or vacuity failure to the caller.
        return Evaluation(
            "GATE-PYRIGHT-004_REPORT",
            "pyright report has no summary",
            _tail(execution.output),
        )
    # Compute analysed using summary.get for later pyright evaluation logic.
    analysed = summary.get("filesAnalyzed")
    # Preserve finding-record elements in checker emission order for the final verdict.
    errors = summary.get("errorCount")
    # Enter the failure path only when the subprocess reports a nonzero status.
    if execution.returncode != 0 or errors != 0:
        # Return pass, findings, or vacuity failure to the caller.
        return Evaluation(
            command.failure_diagnostic,
            f"pyright reported {errors!r} error(s) after analysing {analysed!r} file(s)",
            _tail(execution.output),
        )
    # Select the empty-or-disabled path when isinstance(analysed, int) or analysed <= 0 has no
    # Details: usable value.
    if not isinstance(analysed, int) or analysed <= 0:
        # Return pass, findings, or vacuity failure to the caller.
        return Evaluation(
            "GATE-PYRIGHT-005_NO_SUBJECT",
            "pyright reported success after analysing no files",
            _tail(execution.output),
        )
    # Return pass, findings, or vacuity failure to the caller.
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
    # Enter the failure path only when the subprocess reports a nonzero status.
    if execution.returncode != 0:
        # Return pass, test failure, or vacuity failure to the caller.
        return Evaluation(
            command.failure_diagnostic,
            f"pytest failed while evaluating {command.subjects} configured test file(s)",
            _tail(execution.output),
        )
    # Compute matches using  PYTEST PASSED.findall for later pytest evaluation logic.
    matches = _PYTEST_PASSED.findall(execution.output)
    # Compute passed using int for later pytest evaluation logic.
    passed = int(matches[-1]) if matches else 0
    # Select the guarded path only after `passed == 0` is satisfied.
    if passed == 0:
        # Return pass, test failure, or vacuity failure to the caller.
        return Evaluation(
            "GATE-PYTEST-004_NO_EXECUTION",
            "pytest exited zero without reporting any passed test",
            _tail(execution.output),
        )
    # Return pass, test failure, or vacuity failure to the caller.
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
        # Compute use using  project configuration for later configuration failure logic.
        use = _project_configuration(context, (problem.field,))
        # Return red result to the caller.
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
        # Select the guarded path only after `platform.system() not in self.supported_platforms`
        # Details: is satisfied.
        if platform.system() not in self.supported_platforms:
            # Return explicit tool outcome to the caller.
            return StepResult(
                step_id=self.step_id,
                rules=self.rules,
                status=Status.UNSUPPORTED,
                required=True,
                diagnostic_id=f"GATE-{self.step_id.upper()}-002_PLATFORM",
                summary=f"{platform.system()} is not in {self.supported_platforms}",
                supported_platforms=self.supported_platforms,
            )
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            # Preserve the external command representation and its observed completion outcome.
            command = self.prepare(context)
        # Bind problem to the current value used by the next call decision.
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except ConfigurationProbeError as problem:
            # Return explicit tool outcome to the caller.
            return self._configuration_failure(context, problem)
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            # Compute version using  distribution version for later call logic.
            version = _distribution_version(self.distribution)
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except importlib.metadata.PackageNotFoundError:
            # Return explicit tool outcome to the caller.
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
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            # Preserve the external command representation and its observed completion outcome.
            execution = _execute(command, context.root)
        # Bind problem to the current value used by the next call decision.
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except CommandExecutionError as problem:
            # Return explicit tool outcome to the caller.
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
        # Compute evaluation using self.evaluate for later call logic.
        evaluation = self.evaluate(execution, command)
        # Return explicit tool outcome to the caller.
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
    # Return explicit not-run result to the caller.
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
    # Compute exact root using root.resolve for later run logic.
    exact_root = root.resolve()
    # Compute temporary using "agent-project-gate-") as temporary: for later run logic.
    # Confine the acquired resource to this operation and release it on every exit.
    with tempfile.TemporaryDirectory(prefix="agent-project-gate-") as temporary:
        # Unpack context, declaration result using  load context for later run logic.
        declaration_result, context = _load_context(exact_root, Path(temporary))
        # Each outcomes element is one step result, beginning with declaration validation and
        # followed by adapter outcomes in scheduled order.
        outcomes = [declaration_result]
        # Use the absence path when context has no available value.
        if context is None:
            # Select adapter as the current element from steps) while run preserves traversal
            # Details: order.
            outcomes.extend(_not_run(adapter, declaration_result) for adapter in steps)
            # Compute unit using None for later run logic.
            unit = None
        else:
            # Select adapter as the current element from steps) while run preserves traversal
            # Details: order.
            outcomes.extend(adapter(context) for adapter in steps)
            # Compute unit using context.unit.value for later run logic.
            unit = context.unit.value
    # Return complete report to the caller.
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
    # Return the vendored bundle's parent, or the caller's working directory upstream to the
    # Details: caller.
    return BUNDLE_ROOT.parent if BUNDLE_ROOT.name == ".agent" else Path.cwd()


def _print_report(report: GateReport) -> None:
    """Print one stable line per outcome and a final verdict.

    @param report complete gate report
    """
    # Capture result as the completed print report outcome for subsequent validation or
    # Details: publication.
    # Advance print report through the current input element in declared order.
    for result in report.outcomes:
        # Compute diagnostic using f" {result.diagnostic_id}" if result.diagnostic_id else ""
        # Details: for later print report logic.
        diagnostic = f" {result.diagnostic_id}" if result.diagnostic_id else ""
        print(f"{result.status.value:14s} {result.step_id:24s}{diagnostic} {result.summary}")
        # Select the guarded path only after `result.output` is satisfied.
        if result.output:
            print(result.output)
    print(f"\nproject gate: {'PASS' if report.green else 'FAIL'}")


def main(argv: list[str] | None = None) -> int:
    """Parse the CLI, run the gate, and optionally persist its JSON report.

    @param argv command-line arguments, or None for ``sys.argv``
    @return zero only when the complete report is green

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Configure the command-line parser that defines this tool's invocation contract.
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=_default_root())
    parser.add_argument("--json", type=Path, help="write the complete report as JSON")
    # Capture the validated invocation arguments that govern this execution.
    arguments = parser.parse_args(argv)
    # Hold the decoded checker report mapping for typed summary and diagnostic extraction.
    report = run(arguments.root)
    _print_report(report)
    # Use the available-value path only when arguments.json is present.
    if arguments.json is not None:
        # Publish the externally visible effect after all required inputs are ready.
        arguments.json.write_text(
            json.dumps(report.as_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    # Return the aggregate process status to the command-line boundary.
    return EXIT_GREEN if report.green else EXIT_RED


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    # Propagate the localized failure so callers cannot mistake it for success.
    raise SystemExit(main())
