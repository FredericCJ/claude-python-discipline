"""Run a non-vacuous, cross-platform mutation gate over declared domain code.

The governed repository supplies only semantic inputs in ``pyproject.toml``:
domain paths, test targets, and finite budgets.  This adapter generates Cosmic
Ray's operational configuration in a throwaway copy.  An interrupted mutation
run therefore cannot leave production source mutated, and an editable install
cannot redirect tests back to the unmutated checkout because ``PYTHONPATH`` is
rebound to the copied source roots.

    python .agent/tools/mutation_gate.py --root .
    python .agent/tools/mutation_gate.py --root . --json
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import tempfile
import time
import tomllib
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Final, Never, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

## Machine-readable output contract consumed by ``project_gate.py``.
REPORT_SCHEMA: Final = 1
## Successful complete mutation verdict.
EXIT_GREEN: Final = 0
## Configuration, baseline, mutation, or score failure.
EXIT_RED: Final = 1
## Mutation execution is deliberately stricter than the ordinary test order.
PYTEST_ARGUMENTS: Final = (
    "-m", "pytest", "-q", "-p", "no:randomly", "--disable-socket",
)
## Repository material that cannot affect a unit-level mutation verdict.
IGNORED_DIRECTORIES: Final = frozenset(
    {
        ".agent",
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
        "htmlcov",
        "mutants",
    }
)
## Maximum retained process output in a diagnostic report.
OUTPUT_LIMIT: Final = 6000
## Cosmic Ray dump lines are exactly ``[work_item, work_result]``.
WORK_ITEM_PAIR_SIZE: Final = 2
## A baseline session must contain exactly its one unmutated test execution.
BASELINE_RESULT_COUNT: Final = 1
## Stable configuration failure.
CONFIGURATION_DIAGNOSTIC: Final = "MUTATION-001_CONFIGURATION"
## Stable unmutated-suite failure.
BASELINE_DIAGNOSTIC: Final = "MUTATION-005_BASELINE"
## Stable engine-report failure.
REPORT_DIAGNOSTIC: Final = "MUTATION-006_REPORT"
## Stable incomplete or incompetent mutation-execution failure.
EXECUTION_DIAGNOSTIC: Final = "MUTATION-008_EXECUTION"
## Stable surviving-mutant failure.
SURVIVOR_DIAGNOSTIC: Final = "MUTATION-009_SURVIVOR"


class MutationGateError(ValueError):
    """One stable refusal carrying an actionable diagnostic identity.

    @param diagnostic_id stable machine-facing failure code
    @param detail standalone human-facing explanation
    @param output bounded external-tool output, when one ran
    """

    def __init__(
        self, diagnostic_id: str, detail: str, output: str = "",
    ) -> None:
        """Preserve structured failure data across the CLI boundary.

        @param diagnostic_id stable machine-facing failure code
        @param detail standalone human-facing explanation
        @param output bounded external-tool output, when one ran
        """
        super().__init__(detail)
        self.diagnostic_id = diagnostic_id
        self.output = output[-OUTPUT_LIMIT:].strip()


@dataclass(frozen=True, slots=True)
class Configuration:
    """Validated local inputs required to generate the mutation run."""

    ## Exact governed repository.
    root: Path
    ## Production import roots rebound inside the isolated copy.
    source_roots: tuple[PurePosixPath, ...]
    ## Domain packages or modules mutated independently.
    domains: tuple[PurePosixPath, ...]
    ## Explicit pytest targets used for every baseline and mutant.
    test_targets: tuple[PurePosixPath, ...]
    ## Cosmic Ray's finite per-mutant test-command budget.
    mutant_timeout: float
    ## Finite budget for each Cosmic Ray control command.
    command_timeout: int


@dataclass(frozen=True, slots=True)
class DomainResult:
    """Mutation result for one declared domain path."""

    ## Repository-relative domain path.
    domain: str
    ## Non-zero number of mutants generated before execution.
    mutants: int
    ## Measured init/execute/rate wall time.
    duration_ms: int


@dataclass(frozen=True, slots=True)
class Report:
    """Complete machine-readable mutation verdict."""

    ## Output schema identity.
    schema_version: int
    ## Closed overall state.
    status: str
    ## Stable diagnostic for red results, absent on pass.
    diagnostic_id: str | None
    ## Standalone outcome explanation.
    summary: str
    ## Total generated mutants actually executed.
    mutants: int
    ## Number of declared domain paths exercised.
    domains: int
    ## Total wall time measured by this gate.
    duration_ms: int
    ## Exact installed mutation-engine version.
    tool: str
    ## Per-domain non-vacuity observations.
    results: tuple[DomainResult, ...] = ()
    ## Bounded diagnostic output for a red result.
    output: str = ""

    def as_dict(self) -> dict[str, object]:
        """Render JSON without leaking ``Path`` or tuple implementation details.

        @return JSON-compatible report record
        """
        record = asdict(self)
        record["results"] = [asdict(result) for result in self.results]
        return cast("dict[str, object]", record)


def _reject(diagnostic_id: str, detail: str) -> Never:
    """Raise one typed configuration refusal.

    @param diagnostic_id stable machine-facing failure code
    @param detail standalone explanation
    @return never; always raises
    @throws MutationGateError unconditionally
    """
    raise MutationGateError(diagnostic_id, detail)


def _problem(diagnostic_id: str, detail: str, output: str = "") -> MutationGateError:
    """Build a typed failure without embedding formatting in ``raise`` sites.

    @param diagnostic_id stable machine-facing failure code
    @param detail standalone explanation
    @param output bounded external-tool output
    @return structured mutation failure
    """
    return MutationGateError(diagnostic_id, detail, output)


def _table(document: Mapping[str, object], path: Sequence[str]) -> Mapping[str, object]:
    """Read one required TOML table without accepting scalar impostors.

    @param document decoded project document
    @param path nested table segments
    @return required table
    @throws MutationGateError when absent or malformed
    """
    current: object = document
    for index, segment in enumerate(path):
        if not isinstance(current, dict) or segment not in current:
            _reject(
                "MUTATION-001_CONFIGURATION",
                f"required table {'.'.join(path[: index + 1])!r} is absent",
            )
        current = current[segment]
    if not isinstance(current, dict):
        _reject(
            "MUTATION-001_CONFIGURATION",
            f"{'.'.join(path)!r} must be a TOML table",
        )
    return cast("Mapping[str, object]", current)


def _local_path(raw: object, field: str, root: Path) -> PurePosixPath:
    """Validate one existing repository-confined relative path.

    @param raw decoded path spelling
    @param field dotted configuration field
    @param root exact governed root
    @return normalized repository-relative path
    @throws MutationGateError when malformed, absent, or escaping
    """
    if not isinstance(raw, str) or not raw.strip():
        _reject("MUTATION-001_CONFIGURATION", f"{field} entries must be strings")
    candidate = PurePosixPath(raw.replace("\\", "/"))
    absolute = root / Path(candidate.as_posix())
    if (
        candidate.is_absolute()
        or PureWindowsPath(raw).drive
        or ".." in candidate.parts
        or not absolute.resolve().is_relative_to(root.resolve())
    ):
        _reject(
            "MUTATION-001_CONFIGURATION",
            f"{field} path {raw!r} escapes the governed repository",
        )
    if not absolute.exists():
        _reject(
            "MUTATION-001_CONFIGURATION",
            f"{field} path {raw!r} does not exist",
        )
    return candidate


def _paths(raw: object, field: str, root: Path) -> tuple[PurePosixPath, ...]:
    """Parse a non-empty unique array of local paths.

    @param raw decoded array value
    @param field dotted configuration field
    @param root exact governed root
    @return normalized paths in declaration order
    @throws MutationGateError when empty, duplicated, or unsafe
    """
    if not isinstance(raw, list) or not raw:
        _reject(
            "MUTATION-001_CONFIGURATION",
            f"{field} must be a non-empty path array",
        )
    paths = tuple(_local_path(value, field, root) for value in raw)
    if len(set(paths)) != len(paths):
        _reject("MUTATION-001_CONFIGURATION", f"{field} contains duplicates")
    return paths


def _python_files(root: Path, paths: Sequence[PurePosixPath]) -> tuple[Path, ...]:
    """Enumerate distinct Python subjects beneath explicit paths.

    @param root governed repository root
    @param paths repository-relative files or directories
    @return sorted distinct Python files
    """
    files: set[Path] = set()
    for relative in paths:
        absolute = root / Path(relative.as_posix())
        candidates = absolute.rglob("*.py") if absolute.is_dir() else (absolute,)
        files.update(candidate for candidate in candidates if candidate.is_file())
    return tuple(sorted(files))


def load_configuration(root: Path) -> Configuration:
    """Load and prove every project-controlled mutation input.

    @param root exact governed repository root
    @return validated configuration
    @throws MutationGateError when TOML or a consumed field is invalid
    """
    project_file = root / "pyproject.toml"
    try:
        document = cast(
            "Mapping[str, object]",
            tomllib.loads(project_file.read_text(encoding="utf-8")),
        )
    except (OSError, tomllib.TOMLDecodeError) as problem:
        raise _problem(
            CONFIGURATION_DIAGNOSTIC,
            f"cannot load {project_file}: {problem}",
        ) from problem
    declaration = _table(document, ("tool", "agent-discipline"))
    roles = _table(document, ("tool", "agent-discipline", "roles"))
    gate = _table(document, ("tool", "agent-discipline-gate", "mutation"))
    source_roots = _paths(
        declaration.get("source_roots"), "tool.agent-discipline.source_roots", root,
    )
    domains = _paths(
        roles.get("domain"), "tool.agent-discipline.roles.domain", root,
    )
    targets = _paths(
        gate.get("test_targets"),
        "tool.agent-discipline-gate.mutation.test_targets",
        root,
    )
    if not _python_files(root, domains):
        _reject("MUTATION-002_NO_DOMAIN", "declared domain paths contain no Python files")
    if not _python_files(root, targets):
        _reject("MUTATION-003_NO_TESTS", "mutation test targets contain no Python files")
    mutant_timeout = gate.get("mutant_timeout")
    if (
        not isinstance(mutant_timeout, (int, float))
        or isinstance(mutant_timeout, bool)
        or mutant_timeout <= 0
    ):
        _reject(
            "MUTATION-001_CONFIGURATION",
            "tool.agent-discipline-gate.mutation.mutant_timeout must be positive",
        )
    command_timeout = gate.get("command_timeout")
    if (
        not isinstance(command_timeout, int)
        or isinstance(command_timeout, bool)
        or command_timeout <= 0
    ):
        _reject(
            "MUTATION-001_CONFIGURATION",
            "tool.agent-discipline-gate.mutation.command_timeout must be a positive integer",
        )
    maximum = gate.get("maximum_survival")
    if not isinstance(maximum, (int, float)) or isinstance(maximum, bool) or maximum != 0:
        _reject(
            "MUTATION-001_CONFIGURATION",
            "tool.agent-discipline-gate.mutation.maximum_survival must be 0.0; "
            "v4 does not turn known surviving defects into a percentage allowance",
        )
    return Configuration(
        root=root,
        source_roots=source_roots,
        domains=domains,
        test_targets=targets,
        mutant_timeout=float(mutant_timeout),
        command_timeout=command_timeout,
    )


def _ignore(_directory: str, names: list[str]) -> set[str]:
    """Exclude caches, environments, VCS data, and prior build products.

    @param _directory directory currently copied
    @param names child names considered by ``copytree``
    @return names excluded from the isolated copy
    """
    return {name for name in names if name in IGNORED_DIRECTORIES}


def _isolated_copy(configuration: Configuration, workspace: Path) -> Path:
    """Copy the repository after refusing symlinks that could escape it.

    @param configuration validated mutation inputs
    @param workspace empty temporary parent
    @return isolated repository copy
    @throws MutationGateError when a symlink would make the copy ambiguous
    """
    for path in configuration.root.rglob("*"):
        if path.is_symlink():
            _reject(
                "MUTATION-004_SYMLINK",
                f"mutation isolation refuses repository symlink {path}",
            )
    destination = workspace / "repository"
    shutil.copytree(configuration.root, destination, ignore=_ignore)
    return destination


def _test_command(configuration: Configuration, copied_root: Path) -> str:
    """Build the deterministic pytest command Cosmic Ray runs for every mutant.

    @param configuration validated mutation inputs
    @param copied_root isolated repository root
    @return platform-correct command string
    """
    arguments = (
        sys.executable,
        *PYTEST_ARGUMENTS,
        "-c",
        str(copied_root / "pyproject.toml"),
        "--rootdir",
        str(copied_root),
        *(path.as_posix() for path in configuration.test_targets),
    )
    portable = tuple(argument.replace("\\", "/") for argument in arguments)
    return shlex.join(portable)


def _cosmic_configuration(
    configuration: Configuration,
    copied_root: Path,
    domain: PurePosixPath,
    path: Path,
) -> None:
    """Write one generated Cosmic Ray configuration for one domain path.

    @param configuration validated project inputs
    @param copied_root isolated repository root
    @param domain domain path to mutate
    @param path generated configuration destination
    """
    body = (
        "[cosmic-ray]\n"
        f"module-path = {json.dumps(domain.as_posix())}\n"
        f"timeout = {configuration.mutant_timeout!r}\n"
        "excluded-modules = []\n"
        f"test-command = {json.dumps(_test_command(configuration, copied_root))}\n\n"
        "[cosmic-ray.distributor]\n"
        'name = "local"\n'
    )
    path.write_text(body, encoding="utf-8")


def _environment(configuration: Configuration, copied_root: Path) -> dict[str, str]:
    """Build a deterministic import environment pointing only at copied source.

    @param configuration validated project inputs
    @param copied_root isolated repository root
    @return subprocess environment with an exact local ``PYTHONPATH``
    """
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        str(copied_root / Path(path.as_posix())) for path in configuration.source_roots
    )
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _run_command(  # ruff: ignore[too-many-arguments] - process-boundary record
    arguments: Sequence[str],
    *,
    root: Path,
    environment: Mapping[str, str],
    timeout: int,
    diagnostic_id: str,
    activity: str,
) -> str:
    """Run one Cosmic Ray control command and require a zero exit status.

    @param arguments explicit argv
    @param root isolated working directory
    @param environment deterministic subprocess environment
    @param timeout finite command budget
    @param diagnostic_id code emitted on failure
    @param activity standalone command description
    @return combined textual output
    @throws MutationGateError when the command cannot produce a green verdict
    """
    try:
        finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            tuple(arguments),
            cwd=root,
            env=dict(environment),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as problem:
        raise _problem(
            diagnostic_id,
            f"{activity} did not complete within its finite budget: {problem}",
        ) from problem
    output = finished.stdout + finished.stderr
    if finished.returncode != 0:
        raise _problem(
            diagnostic_id,
            f"{activity} exited {finished.returncode}",
            output,
        )
    return output


def _mutant_count(output: str) -> int:
    """Count JSON-lines work items emitted by ``cosmic-ray dump``.

    @param output complete dump output
    @return parsed work-item count
    @throws MutationGateError when output is malformed or empty
    """
    count = 0
    for number, line in enumerate(output.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as problem:
            raise _problem(
                REPORT_DIAGNOSTIC,
                f"Cosmic Ray dump line {number} is not JSON: {problem}",
                output,
            ) from problem
        if not isinstance(record, list) or len(record) != WORK_ITEM_PAIR_SIZE:
            raise _problem(
                REPORT_DIAGNOSTIC,
                f"Cosmic Ray dump line {number} is not a work-item/result pair",
                output,
            )
        count += 1
    if count == 0:
        _reject(
            "MUTATION-007_NO_MUTANTS",
            "Cosmic Ray generated no mutants for the declared domain paths",
        )
    return count


def _result_records(output: str) -> tuple[Mapping[str, object], ...]:
    """Parse completed Cosmic Ray result records and refuse pending work.

    @param output complete post-execution JSON-lines dump
    @return decoded result objects
    @throws MutationGateError when a result record is malformed
    """
    results: list[Mapping[str, object]] = []
    for number, line in enumerate(output.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as problem:
            raise _problem(
                REPORT_DIAGNOSTIC,
                f"Cosmic Ray result line {number} is not JSON: {problem}",
                output,
            ) from problem
        if not isinstance(record, list) or len(record) != WORK_ITEM_PAIR_SIZE:
            raise _problem(
                REPORT_DIAGNOSTIC,
                f"Cosmic Ray result line {number} is not a work-item/result pair",
                output,
            )
        result = record[1]
        if not isinstance(result, dict):
            raise _problem(
                REPORT_DIAGNOSTIC,
                f"Cosmic Ray result line {number} has no completed result",
                output,
            )
        results.append(cast("Mapping[str, object]", result))
    return tuple(results)


def _baseline_passed(output: str) -> None:
    """Require one normally executed, passing unmutated test command.

    Cosmic Ray 8.7.0's baseline command treats ``incompetent`` as success.  The
    independent dump oracle closes that false-pass path.

    @param output JSON-lines dump of the baseline session
    @throws MutationGateError when execution was killed, incompetent, or absent
    """
    results = _result_records(output)
    if len(results) != BASELINE_RESULT_COUNT:
        raise _problem(
            BASELINE_DIAGNOSTIC,
            f"baseline produced {len(results)} results instead of exactly one",
            output,
        )
    result = results[0]
    if (
        result.get("worker_outcome") != "normal"
        or result.get("test_outcome") != "survived"
    ):
        raise _problem(
            BASELINE_DIAGNOSTIC,
            "unmutated tests did not complete normally and pass",
            output,
        )


def _survivors(output: str, expected: int) -> int:
    """Count survivors only after proving every mutant completed competently.

    @param output complete post-execution JSON-lines dump
    @param expected mutant count established before execution
    @return number of surviving mutants
    @throws MutationGateError for pending, missing, abnormal, or incompetent work
    """
    results = _result_records(output)
    if len(results) != expected:
        raise _problem(
            EXECUTION_DIAGNOSTIC,
            f"only {len(results)} of {expected} generated mutants produced results",
            output,
        )
    invalid = [
        result
        for result in results
        if result.get("worker_outcome") != "normal"
        or result.get("test_outcome") not in {"killed", "survived"}
    ]
    if invalid:
        raise _problem(
            EXECUTION_DIAGNOSTIC,
            f"{len(invalid)} mutant(s) were abnormal or incompetent, not killed",
            output,
        )
    return sum(result.get("test_outcome") == "survived" for result in results)


def execute(configuration: Configuration) -> tuple[DomainResult, ...]:
    """Run baseline, non-vacuity, mutation, and zero-survivor checks.

    @param configuration validated local mutation inputs
    @return one successful observation per domain path
    @throws MutationGateError on the first red proposition
    """
    with tempfile.TemporaryDirectory(prefix="agent-mutation-gate-") as temporary:
        temporary_root = Path(temporary)
        copied_root = _isolated_copy(configuration, temporary_root)
        environment = _environment(configuration, copied_root)
        results: list[DomainResult] = []
        for index, domain in enumerate(configuration.domains):
            started = time.perf_counter()
            config = temporary_root / f"cosmic-ray-{index}.toml"
            session = temporary_root / f"cosmic-ray-{index}.sqlite"
            baseline = temporary_root / f"cosmic-ray-baseline-{index}.sqlite"
            _cosmic_configuration(configuration, copied_root, domain, config)
            prefix = (sys.executable, "-m", "cosmic_ray.cli")
            _run_command(
                (*prefix, "baseline", str(config), "--session-file", str(baseline)),
                root=copied_root,
                environment=environment,
                timeout=configuration.command_timeout,
                diagnostic_id="MUTATION-005_BASELINE",
                activity=f"unmutated baseline for {domain}",
            )
            baseline_dump = _run_command(
                (*prefix, "dump", str(baseline)),
                root=copied_root,
                environment=environment,
                timeout=configuration.command_timeout,
                diagnostic_id="MUTATION-005_BASELINE",
                activity=f"unmutated baseline report for {domain}",
            )
            _baseline_passed(baseline_dump)
            _run_command(
                (*prefix, "init", str(config), str(session)),
                root=copied_root,
                environment=environment,
                timeout=configuration.command_timeout,
                diagnostic_id="MUTATION-006_INITIALIZATION",
                activity=f"mutant initialization for {domain}",
            )
            dump = _run_command(
                (*prefix, "dump", str(session)),
                root=copied_root,
                environment=environment,
                timeout=configuration.command_timeout,
                diagnostic_id="MUTATION-006_REPORT",
                activity=f"mutant inventory for {domain}",
            )
            mutants = _mutant_count(dump)
            _run_command(
                (*prefix, "exec", str(config), str(session)),
                root=copied_root,
                environment=environment,
                timeout=configuration.command_timeout,
                diagnostic_id="MUTATION-008_EXECUTION",
                activity=f"mutation execution for {domain}",
            )
            completed = _run_command(
                (*prefix, "dump", str(session)),
                root=copied_root,
                environment=environment,
                timeout=configuration.command_timeout,
                diagnostic_id="MUTATION-006_REPORT",
                activity=f"completed mutation report for {domain}",
            )
            survivor_count = _survivors(completed, mutants)
            if survivor_count:
                raise _problem(
                    SURVIVOR_DIAGNOSTIC,
                    f"zero-survivor score for {domain} found "
                    f"{survivor_count} surviving mutant(s)",
                    completed,
                )
            _run_command(
                (
                    sys.executable,
                    "-m",
                    "cosmic_ray.tools.survival_rate",
                    "--no-estimate",
                    "--fail-over",
                    "0.0",
                    str(session),
                ),
                root=copied_root,
                environment=environment,
                timeout=configuration.command_timeout,
                diagnostic_id="MUTATION-009_SURVIVOR",
                activity=f"zero-survivor score for {domain}",
            )
            results.append(
                DomainResult(
                    domain=domain.as_posix(),
                    mutants=mutants,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                )
            )
        return tuple(results)


def run(root: Path) -> Report:
    """Produce one complete mutation report without leaking exceptions.

    @param root exact governed repository root
    @return green or red structured report
    """
    started = time.perf_counter()
    try:
        tool = f"cosmic-ray {version('cosmic-ray')}"
    except PackageNotFoundError:
        tool = "cosmic-ray unavailable"
        problem = _problem(
            "MUTATION-010_TOOL", "required distribution 'cosmic-ray' is not installed",
        )
    else:
        try:
            configuration = load_configuration(root.resolve())
            results = execute(configuration)
        except MutationGateError as caught:
            problem = caught
        else:
            mutants = sum(result.mutants for result in results)
            return Report(
                schema_version=REPORT_SCHEMA,
                status="pass",
                diagnostic_id=None,
                summary=(
                    f"all {mutants} generated mutant(s) were killed across "
                    f"{len(results)} declared domain path(s)"
                ),
                mutants=mutants,
                domains=len(results),
                duration_ms=round((time.perf_counter() - started) * 1000),
                tool=tool,
                results=results,
            )
    return Report(
        schema_version=REPORT_SCHEMA,
        status="fail",
        diagnostic_id=problem.diagnostic_id,
        summary=str(problem),
        mutants=0,
        domains=0,
        duration_ms=round((time.perf_counter() - started) * 1000),
        tool=tool,
        output=problem.output,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the mutation gate and emit either JSON or a compact text verdict.

    @param argv command-line arguments, defaulting to ``sys.argv``
    @return zero only after a non-empty zero-survivor run
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args(argv)
    report = run(arguments.root)
    if arguments.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        prefix = "PASS" if report.status == "pass" else "FAIL"
        diagnostic = "" if report.diagnostic_id is None else f" {report.diagnostic_id}"
        print(f"{prefix}{diagnostic}: {report.summary}")
        if report.output:
            print(report.output)
    return EXIT_GREEN if report.status == "pass" else EXIT_RED


if __name__ == "__main__":
    sys.exit(main())
