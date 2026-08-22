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
import json
import platform
import sys
import time
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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
        }


@dataclass(frozen=True, slots=True)
class GateContext:
    """Validated repository inputs shared by all post-declaration steps."""

    ## Exact governed root supplied to the CLI.
    root: Path
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


def _load_context(root: Path) -> tuple[StepResult, GateContext | None]:
    """Load one exact-root declaration and expose its content binding.

    @param root governed repository root
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
    return result, GateContext(root, declared_unit, declaration, document, use)


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


## The adopter-facing gate grows by adding adapters here, never by local wrappers.
DEFAULT_STEPS: Final[tuple[StepAdapter, ...]] = (DisciplineChecksAdapter(),)


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
    declaration_result, context = _load_context(exact_root)
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
