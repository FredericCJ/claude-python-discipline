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

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

## Machine-readable output contract consumed by ``project_gate.py``.
REPORT_SCHEMA: Final = 1
## Successful complete mutation verdict.
EXIT_GREEN: Final = 0
## Configuration, baseline, mutation, or score failure.
EXIT_RED: Final = 1
## Mutation execution is deliberately stricter than the ordinary test order.
## Each element is one pytest command-line argument; tuple order is significant and later
## entries override earlier pytest defaults where the option supports it.
PYTEST_ARGUMENTS: Final = (
    "-m",
    "pytest",
    "-q",
    "-p",
    "no:randomly",
    "--disable-socket",
)
## Repository material that cannot affect a unit-level mutation verdict.
IGNORED_DIRECTORIES: Final = frozenset({
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
})
## Maximum retained actionable survivor output in a diagnostic report.
OUTPUT_LIMIT: Final = 30000
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
        self,
        diagnostic_id: str,
        detail: str,
        output: str = "",
    ) -> None:
        """Preserve structured failure data across the CLI boundary.

        @param diagnostic_id stable machine-facing failure code
        @param detail standalone human-facing explanation
        @param output bounded external-tool output, when one ran
        """
        super().__init__(detail)
        # Update   init   state only after the required source facts are available.
        self.diagnostic_id = diagnostic_id
        # Update   init   state only after the required source facts are available.
        self.output = output[-OUTPUT_LIMIT:].strip()


@dataclass(frozen=True, slots=True)
class Configuration:
    """Validated local inputs required to generate the mutation run."""

    ## Exact governed repository.
    root: Path
    ## Production import roots rebound inside the isolated copy.
    ## Each element is a repository-relative import root; declaration order is preserved.
    source_roots: tuple[PurePosixPath, ...]
    ## Domain packages or modules mutated independently.
    ## Each element is a repository-relative mutation target; declaration order controls runs.
    domains: tuple[PurePosixPath, ...]
    ## Explicit pytest targets used for every baseline and mutant.
    ## Each element is passed to pytest in declaration order after the fixed safety arguments.
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
    ## Each element is one domain result, retaining configured domain order.
    results: tuple[DomainResult, ...] = ()
    ## Bounded diagnostic output for a red result.
    output: str = ""

    def as_dict(self) -> dict[str, object]:
        """Render JSON without leaking ``Path`` or tuple implementation details.

        @return JSON-compatible report record
        """
        # Hold the decoded mapping elements whose keys identify fields and values carry their
        # Details: content; key order is deliberately unused.
        record = asdict(self)
        # Capture result as the completed as dict outcome for subsequent validation or
        # Details: publication.
        # Update as dict state only after the required source facts are available.
        record["results"] = [asdict(result) for result in self.results]
        # Return jSON-compatible report record to the caller.
        return cast("dict[str, object]", record)


def _reject(diagnostic_id: str, detail: str) -> Never:
    """Raise one typed configuration refusal.

    @param diagnostic_id stable machine-facing failure code
    @param detail standalone explanation
    @return never; always raises
    @throws MutationGateError unconditionally
    """
    # Propagate the localized failure so callers cannot mistake it for success.
    raise MutationGateError(diagnostic_id, detail)


def _problem(diagnostic_id: str, detail: str, output: str = "") -> MutationGateError:
    """Build a typed failure without embedding formatting in ``raise`` sites.

    @param diagnostic_id stable machine-facing failure code
    @param detail standalone explanation
    @param output bounded external-tool output
    @return structured mutation failure
    """
    # Return structured mutation failure to the caller.
    return MutationGateError(diagnostic_id, detail, output)


def _table(document: Mapping[str, object], path: Sequence[str]) -> Mapping[str, object]:
    """Read one required TOML table without accepting scalar impostors.

    @param document decoded project document
        Treat document as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @param path nested table segments
        Each element names the next TOML table segment, ordered outermost to innermost.
    @return required table
    @throws MutationGateError when absent or malformed
    """
    # Preserve the documentation-stripped behavior fingerprint used for comparison.
    current: object = document
    # Locate the structural boundary used to parse the external result safely.
    # Advance table through the current input element in declared order.
    for index, segment in enumerate(path):
        # Select the empty-or-disabled path when isinstance(current, dict) or segment not in
        # Details: current has no usable value.
        if not isinstance(current, dict) or segment not in current:
            _reject(
                "MUTATION-001_CONFIGURATION",
                f"required table {'.'.join(path[: index + 1])!r} is absent",
            )
        # Preserve the documentation-stripped behavior fingerprint used for comparison.
        current = current[segment]
    # Select the empty-or-disabled path when isinstance(current, dict) has no usable value.
    if not isinstance(current, dict):
        _reject(
            "MUTATION-001_CONFIGURATION",
            f"{'.'.join(path)!r} must be a TOML table",
        )
    # Return required table to the caller.
    return cast("Mapping[str, object]", current)


def _local_path(raw: object, field: str, root: Path) -> PurePosixPath:
    """Validate one existing repository-confined relative path.

    @param raw decoded path spelling
    @param field dotted configuration field
    @param root exact governed root
    @return normalized repository-relative path
    @throws MutationGateError when malformed, absent, or escaping
    """
    # Select the empty-or-disabled path when isinstance(raw, str) or not raw.strip() has no
    # Details: usable value.
    if not isinstance(raw, str) or not raw.strip():
        _reject("MUTATION-001_CONFIGURATION", f"{field} entries must be strings")
    # Treat the current candidate as the candidate element consumed by the enclosing
    # Details: transformation.
    candidate = PurePosixPath(raw.replace("\\", "/"))
    # Compute absolute using root / Path(candidate.as_posix()) for later local path logic.
    absolute = root / Path(candidate.as_posix())
    # Select the guarded path only after `candidate.is_absolute() or PureWindowsPath(raw).drive
    # Details: or '..' in candidate.parts or (not
    # Details: absolute.resolve().is_relative_to(root.resolve()))` is satisfied.
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
    # Select the existing-artifact path only when `not absolute.exists()` is satisfied.
    if not absolute.exists():
        _reject(
            "MUTATION-001_CONFIGURATION",
            f"{field} path {raw!r} does not exist",
        )
    # Return normalized repository-relative path to the caller.
    return candidate


def _paths(raw: object, field: str, root: Path) -> tuple[PurePosixPath, ...]:
    """Parse a non-empty unique array of local paths.

    @param raw decoded array value
    @param field dotted configuration field
    @param root exact governed root
    @return normalized paths in declaration order
    @throws MutationGateError when empty, duplicated, or unsafe
    """
    # Select the empty-or-disabled path when isinstance(raw, list) or not raw has no usable
    # Details: value.
    if not isinstance(raw, list) or not raw:
        _reject(
            "MUTATION-001_CONFIGURATION",
            f"{field} must be a non-empty path array",
        )
    # Preserve paths, value element values in deterministic source order.
    paths = tuple(_local_path(value, field, root) for value in raw)
    # Select the guarded path only after `len(set(paths)) != len(paths)` is satisfied.
    if len(set(paths)) != len(paths):
        _reject("MUTATION-001_CONFIGURATION", f"{field} contains duplicates")
    # Return normalized paths in declaration order to the caller.
    return paths


def _python_files(root: Path, paths: Sequence[PurePosixPath]) -> tuple[Path, ...]:
    """Enumerate distinct Python subjects beneath explicit paths.

    @param root governed repository root
    @param paths repository-relative files or directories
        Each paths element represents one repository path; traversal order is preserved.
    @return sorted distinct Python files
    """
    # Collect unique files element values; their order is deliberately unordered.
    files: set[Path] = set()
    # Select relative as the current element from paths while python files preserves traversal
    # Details: order.
    # Advance python files through the current input element in declared order.
    for relative in paths:
        # Compute absolute using root / Path(relative.as_posix()) for later python files logic.
        absolute = root / Path(relative.as_posix())
        # Compute candidates using absolute.rglob for later python files logic.
        candidates = absolute.rglob("*.py") if absolute.is_dir() else (absolute,)
        # Treat the current candidate as the candidate element consumed by the enclosing
        # Details: transformation.
        files.update(candidate for candidate in candidates if candidate.is_file())
    # Return sorted distinct Python files to the caller.
    return tuple(sorted(files))


def load_configuration(root: Path) -> Configuration:
    """Load and prove every project-controlled mutation input.

    @param root exact governed repository root
    @return validated configuration
    @throws MutationGateError when TOML or a consumed field is invalid
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    project_file = root / "pyproject.toml"
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Hold the decoded mapping elements whose keys identify fields and values carry their
        # Details: content; key order is deliberately unused.
        document = cast(
            "Mapping[str, object]",
            tomllib.loads(project_file.read_text(encoding="utf-8")),
        )
    # Bind problem to the current value used by the next load configuration decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (OSError, tomllib.TOMLDecodeError) as problem:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _problem(
            CONFIGURATION_DIAGNOSTIC,
            f"cannot load {project_file}: {problem}",
        ) from problem
    # Compute declaration using  table for later load configuration logic.
    declaration = _table(document, ("tool", "agent-discipline"))
    # Compute roles using  table for later load configuration logic.
    roles = _table(document, ("tool", "agent-discipline", "roles"))
    # Compute gate using  table for later load configuration logic.
    gate = _table(document, ("tool", "agent-discipline-gate", "mutation"))
    # Compute source roots using  paths for later load configuration logic.
    source_roots = _paths(
        declaration.get("source_roots"),
        "tool.agent-discipline.source_roots",
        root,
    )
    # Compute domains using  paths for later load configuration logic.
    domains = _paths(
        roles.get("domain"),
        "tool.agent-discipline.roles.domain",
        root,
    )
    # Preserve governed Python-path elements in deterministic traversal order.
    targets = _paths(
        gate.get("test_targets"),
        "tool.agent-discipline-gate.mutation.test_targets",
        root,
    )
    # Select the empty-or-disabled path when  python files(root, domains) has no usable value.
    if not _python_files(root, domains):
        _reject("MUTATION-002_NO_DOMAIN", "declared domain paths contain no Python files")
    # Select the empty-or-disabled path when  python files(root, targets) has no usable value.
    if not _python_files(root, targets):
        _reject("MUTATION-003_NO_TESTS", "mutation test targets contain no Python files")
    # Compute mutant timeout using gate.get for later load configuration logic.
    mutant_timeout = gate.get("mutant_timeout")
    # Select the empty-or-disabled path when isinstance(mutant timeout, (int, float)) or
    # Details: isinstance(mutant timeout, bool) or mutant timeout <= 0 has no usable value.
    if (
        not isinstance(mutant_timeout, (int, float))
        or isinstance(mutant_timeout, bool)
        or mutant_timeout <= 0
    ):
        _reject(
            "MUTATION-001_CONFIGURATION",
            "tool.agent-discipline-gate.mutation.mutant_timeout must be positive",
        )
    # Compute command timeout using gate.get for later load configuration logic.
    command_timeout = gate.get("command_timeout")
    # Select the empty-or-disabled path when isinstance(command timeout, int) or
    # Details: isinstance(command timeout, bool) or command timeout <= 0 has no usable value.
    if (
        not isinstance(command_timeout, int)
        or isinstance(command_timeout, bool)
        or command_timeout <= 0
    ):
        _reject(
            "MUTATION-001_CONFIGURATION",
            "tool.agent-discipline-gate.mutation.command_timeout must be a positive integer",
        )
    # Compute maximum using gate.get for later load configuration logic.
    maximum = gate.get("maximum_survival")
    # Select the empty-or-disabled path when isinstance(maximum, (int, float)) or
    # Details: isinstance(maximum, bool) or maximum != 0 has no usable value.
    if not isinstance(maximum, (int, float)) or isinstance(maximum, bool) or maximum != 0:
        _reject(
            "MUTATION-001_CONFIGURATION",
            "tool.agent-discipline-gate.mutation.maximum_survival must be 0.0; "
            "v4 does not turn known surviving defects into a percentage allowance",
        )
    # Return validated configuration to the caller.
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
        Each element is one basename supplied by ``copytree``; order is deliberately unused.
    @return names excluded from the isolated copy
    """
    # Normalize the current repository path to its portable baseline key spelling.
    # Return names excluded from the isolated copy to the caller.
    return {name for name in names if name in IGNORED_DIRECTORIES}


def _isolated_copy(configuration: Configuration, workspace: Path) -> Path:
    """Copy the repository after refusing symlinks that could escape it.

    @param configuration validated mutation inputs
    @param workspace empty temporary parent
    @return isolated repository copy
    @throws MutationGateError when a symlink would make the copy ambiguous
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    # Advance isolated copy through the current input element in declared order.
    for path in configuration.root.rglob("*"):
        # Select the guarded path only after `path.is_symlink()` is satisfied.
        if path.is_symlink():
            _reject(
                "MUTATION-004_SYMLINK",
                f"mutation isolation refuses repository symlink {path}",
            )
    # Resolve the repository-confined path used by this operation before filesystem access.
    destination = workspace / "repository"
    shutil.copytree(configuration.root, destination, ignore=_ignore)
    # Return isolated repository copy to the caller.
    return destination


def _test_command(configuration: Configuration, copied_root: Path) -> str:
    """Build the deterministic pytest command Cosmic Ray runs for every mutant.

    @param configuration validated mutation inputs
    @param copied_root isolated repository root
    @return platform-correct command string
    """
    # Each arguments element is one process argument string; invocation order is preserved.
    arguments = (
        sys.executable,
        *PYTEST_ARGUMENTS,
        "-c",
        str(copied_root / "pyproject.toml"),
        "--rootdir",
        str(copied_root),
        *(path.as_posix() for path in configuration.test_targets),
    )
    # Select argument, portable as the current element from arguments) while test command
    # Details: preserves traversal order.
    portable = tuple(argument.replace("\\", "/") for argument in arguments)
    # Return platform-correct command string to the caller.
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

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Retain the immutable source representation consumed by subsequent analysis.
    body = (
        "[cosmic-ray]\n"
        f"module-path = {json.dumps(domain.as_posix())}\n"
        f"timeout = {configuration.mutant_timeout!r}\n"
        "excluded-modules = []\n"
        f"test-command = {json.dumps(_test_command(configuration, copied_root))}\n\n"
        "[cosmic-ray.distributor]\n"
        'name = "local"\n'
    )
    # Publish the externally visible effect after all required inputs are ready.
    path.write_text(body, encoding="utf-8", newline="\n")


def _environment(configuration: Configuration, copied_root: Path) -> dict[str, str]:
    """Build a deterministic import environment pointing only at copied source.

    @param configuration validated project inputs
    @param copied_root isolated repository root
    @return subprocess environment with an exact local ``PYTHONPATH``
    """
    # Build the child-process environment with the governed source root on its import path.
    environment = os.environ.copy()
    # Resolve the repository-confined path used by this operation before filesystem access.
    # Update  environment state only after the required source facts are available.
    environment["PYTHONPATH"] = os.pathsep.join(
        str(copied_root / Path(path.as_posix())) for path in configuration.source_roots
    )
    # Update  environment state only after the required source facts are available.
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    # Return subprocess environment with an exact local ``PYTHONPATH`` to the caller.
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
        Each arguments element is one process argument string; invocation order is preserved.
    @param root isolated working directory
    @param environment deterministic subprocess environment
        Treat environment as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @param timeout finite command budget
    @param diagnostic_id code emitted on failure
    @param activity standalone command description
    @return combined textual output
    @throws MutationGateError when the command cannot produce a green verdict
    """
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Preserve the external command representation and its observed completion outcome.
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
    # Bind problem to the current value used by the next run command decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (OSError, subprocess.TimeoutExpired) as problem:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _problem(
            diagnostic_id,
            f"{activity} did not complete within its finite budget: {problem}",
        ) from problem
    # Combine the checker's captured diagnostic streams without losing emission text.
    output = finished.stdout + finished.stderr
    # Enter the failure path only when the subprocess reports a nonzero status.
    if finished.returncode != 0:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _problem(
            diagnostic_id,
            f"{activity} exited {finished.returncode}",
            output,
        )
    # Return combined textual output to the caller.
    return output


def _mutant_count(output: str) -> int:
    """Count JSON-lines work items emitted by ``cosmic-ray dump``.

    @param output complete dump output
    @return parsed work-item count
    @throws MutationGateError when output is malformed or empty
    """
    # Preserve the observed item count used by the non-vacuity verdict.
    count = 0
    # Preserve the current decoded diagnostic line before location normalization.
    # Advance mutant count through the current input element in declared order.
    for number, line in enumerate(output.splitlines(), 1):
        # Select the empty-or-disabled path when line.strip() has no usable value.
        if not line.strip():
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            # Hold the decoded mapping elements whose keys identify fields and values carry
            # Details: their content; key order is deliberately unused.
            record = json.loads(line)
        # Bind problem to the current value used by the next mutant count decision.
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except json.JSONDecodeError as problem:
            # Propagate the localized failure so callers cannot mistake it for success.
            raise _problem(
                REPORT_DIAGNOSTIC,
                f"Cosmic Ray dump line {number} is not JSON: {problem}",
                output,
            ) from problem
        # Select the empty-or-disabled path when isinstance(record, list) or len(record) != WORK
        # Details: ITEM PAIR SIZE has no usable value.
        if not isinstance(record, list) or len(record) != WORK_ITEM_PAIR_SIZE:
            # Propagate the localized failure so callers cannot mistake it for success.
            raise _problem(
                REPORT_DIAGNOSTIC,
                f"Cosmic Ray dump line {number} is not a work-item/result pair",
                output,
            )
        # Preserve the observed item count used by the non-vacuity verdict.
        count += 1
    # Select the guarded path only after `count == 0` is satisfied.
    if count == 0:
        _reject(
            "MUTATION-007_NO_MUTANTS",
            "Cosmic Ray generated no mutants for the declared domain paths",
        )
    # Return parsed work-item count to the caller.
    return count


def _result_records(output: str) -> tuple[Mapping[str, object], ...]:
    """Parse completed Cosmic Ray result records and refuse pending work.

    @param output complete post-execution JSON-lines dump
    @return decoded result objects
    @throws MutationGateError when a result record is malformed
    """
    # Treat results as mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    results: list[Mapping[str, object]] = []
    # Preserve the current decoded diagnostic line before location normalization.
    # Advance result records through the current input element in declared order.
    for number, line in enumerate(output.splitlines(), 1):
        # Select the empty-or-disabled path when line.strip() has no usable value.
        if not line.strip():
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            # Hold the decoded mapping elements whose keys identify fields and values carry
            # Details: their content; key order is deliberately unused.
            record = json.loads(line)
        # Bind problem to the current value used by the next result records decision.
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except json.JSONDecodeError as problem:
            # Propagate the localized failure so callers cannot mistake it for success.
            raise _problem(
                REPORT_DIAGNOSTIC,
                f"Cosmic Ray result line {number} is not JSON: {problem}",
                output,
            ) from problem
        # Select the empty-or-disabled path when isinstance(record, list) or len(record) != WORK
        # Details: ITEM PAIR SIZE has no usable value.
        if not isinstance(record, list) or len(record) != WORK_ITEM_PAIR_SIZE:
            # Propagate the localized failure so callers cannot mistake it for success.
            raise _problem(
                REPORT_DIAGNOSTIC,
                f"Cosmic Ray result line {number} is not a work-item/result pair",
                output,
            )
        # Capture result as the completed result records outcome for subsequent validation or
        # Details: publication.
        result = record[1]
        # Select the empty-or-disabled path when isinstance(result, dict) has no usable value.
        if not isinstance(result, dict):
            # Propagate the localized failure so callers cannot mistake it for success.
            raise _problem(
                REPORT_DIAGNOSTIC,
                f"Cosmic Ray result line {number} has no completed result",
                output,
            )
        results.append(cast("Mapping[str, object]", result))
    # Return decoded result objects to the caller.
    return tuple(results)


def _baseline_passed(output: str) -> None:
    """Require one normally executed, passing unmutated test command.

    Cosmic Ray 8.7.0's baseline command treats ``incompetent`` as success.  The
    independent dump oracle closes that false-pass path.

    @param output JSON-lines dump of the baseline session
    @throws MutationGateError when execution was killed, incompetent, or absent
    """
    # Compute results using  result records for later baseline passed logic.
    results = _result_records(output)
    # Select the guarded path only after `len(results) != BASELINE_RESULT_COUNT` is satisfied.
    if len(results) != BASELINE_RESULT_COUNT:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _problem(
            BASELINE_DIAGNOSTIC,
            f"baseline produced {len(results)} results instead of exactly one",
            output,
        )
    # Capture result as the completed baseline passed outcome for subsequent validation or
    # Details: publication.
    result = results[0]
    # Select the guarded path only after `result.get('worker_outcome') != 'normal' or
    # Details: result.get('test_outcome') != 'survived'` is satisfied.
    if result.get("worker_outcome") != "normal" or result.get("test_outcome") != "survived":
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _problem(
            BASELINE_DIAGNOSTIC,
            "unmutated tests did not complete normally and pass",
            output,
        )


def _survivors(output: str, expected: int) -> tuple[Mapping[str, object], ...]:
    """Return survivors only after proving every mutant completed competently.

    @param output complete post-execution JSON-lines dump
    @param expected mutant count established before execution
    @return completed result records for every surviving mutant
    @throws MutationGateError for pending, missing, abnormal, or incompetent work
    """
    # Compute results using  result records for later survivors logic.
    results = _result_records(output)
    # Select the guarded path only after `len(results) != expected` is satisfied.
    if len(results) != expected:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _problem(
            EXECUTION_DIAGNOSTIC,
            f"only {len(results)} of {expected} generated mutants produced results",
            output,
        )
    # Each invalid element is a result that did not complete normally; engine order is preserved.
    invalid = [
        result
        for result in results
        if result.get("worker_outcome") != "normal"
        or result.get("test_outcome") not in {"killed", "survived"}
    ]
    # Handle the non-empty or enabled invalid state.
    if invalid:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise _problem(
            EXECUTION_DIAGNOSTIC,
            f"{len(invalid)} mutant(s) were abnormal or incompetent, not killed",
            output,
        )
    # Capture result as the completed survivors outcome for subsequent validation or
    # Details: publication.
    # Return completed result records for every surviving mutant to the caller.
    return tuple(result for result in results if result.get("test_outcome") == "survived")


def _survivor_output(survivors: Sequence[Mapping[str, object]]) -> str:
    """Render only mutation diffs that the selected tests failed to reject.

    Raw Cosmic Ray dumps include the complete pytest output for every killed
    mutant. Retaining their tail hid the surviving mutations that require a
    developer's attention. A red gate therefore reports each survivor's diff
    and excludes unrelated killed-test output.

    @param survivors completed surviving-mutant result records
        Treat survivors as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @return bounded, human-readable survivor diagnostics
    """
    # Each blocks element is one rendered survivor diagnostic; engine order is preserved.
    blocks: list[str] = []
    # Capture index, result as the completed survivor output outcome for subsequent validation
    # Details: or publication.
    # Advance survivor output through the current input element in declared order.
    for index, result in enumerate(survivors, 1):
        # Compute diff using result.get for later survivor output logic.
        diff = result.get("diff")
        # Compute rendered using diff if isinstance(diff, str) and diff.strip() else "<mutati
        # Details: for later survivor output logic.
        rendered = diff if isinstance(diff, str) and diff.strip() else "<mutation diff unavailable>"
        blocks.append(f"SURVIVOR {index}\n{rendered.strip()}")
    # Return bounded, human-readable survivor diagnostics to the caller.
    return "\n\n".join(blocks)


def execute(configuration: Configuration) -> tuple[DomainResult, ...]:
    """Run baseline, non-vacuity, mutation, and zero-survivor checks.

    @param configuration validated local mutation inputs
    @return one successful observation per domain path
    @throws MutationGateError on the first red proposition
    """
    # Compute temporary using "agent-mutation-gate-") as temporary: for later execute logic.
    # Confine the acquired resource to this operation and release it on every exit.
    with tempfile.TemporaryDirectory(prefix="agent-mutation-gate-") as temporary:
        # Compute temporary root using Path for later execute logic.
        temporary_root = Path(temporary)
        # Compute copied root using  isolated copy for later execute logic.
        copied_root = _isolated_copy(configuration, temporary_root)
        # Build the child-process environment with the governed source root on its import path.
        environment = _environment(configuration, copied_root)
        # Each results element is one domain observation, appended in declaration order.
        results: list[DomainResult] = []
        # Locate the structural boundary used to parse the external result safely.
        # Advance execute through the current input element in declared order.
        for index, domain in enumerate(configuration.domains):
            # Compute started using time.perf counter for later execute logic.
            started = time.perf_counter()
            # Compute config using temporary_root / f"cosmic-ray-{index}.toml" for later execute
            # Details: logic.
            config = temporary_root / f"cosmic-ray-{index}.toml"
            # Compute session using temporary_root / f"cosmic-ray-{index}.sqlite" for later
            # Details: execute logic.
            session = temporary_root / f"cosmic-ray-{index}.sqlite"
            # Hold baseline path keys mapped to their recorded behavior-fingerprint values.
            baseline = temporary_root / f"cosmic-ray-baseline-{index}.sqlite"
            _cosmic_configuration(configuration, copied_root, domain, config)
            # Each prefix element is one command token; interpreter-before-module order is fixed.
            prefix = (sys.executable, "-m", "cosmic_ray.cli")
            _run_command(
                (*prefix, "baseline", str(config), "--session-file", str(baseline)),
                root=copied_root,
                environment=environment,
                timeout=configuration.command_timeout,
                diagnostic_id="MUTATION-005_BASELINE",
                activity=f"unmutated baseline for {domain}",
            )
            # Compute baseline dump using  run command for later execute logic.
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
            # Compute dump using  run command for later execute logic.
            dump = _run_command(
                (*prefix, "dump", str(session)),
                root=copied_root,
                environment=environment,
                timeout=configuration.command_timeout,
                diagnostic_id="MUTATION-006_REPORT",
                activity=f"mutant inventory for {domain}",
            )
            # Compute mutants using  mutant count for later execute logic.
            mutants = _mutant_count(dump)
            _run_command(
                (*prefix, "exec", str(config), str(session)),
                root=copied_root,
                environment=environment,
                timeout=configuration.command_timeout,
                diagnostic_id="MUTATION-008_EXECUTION",
                activity=f"mutation execution for {domain}",
            )
            # Preserve the external command representation and its observed completion outcome.
            completed = _run_command(
                (*prefix, "dump", str(session)),
                root=copied_root,
                environment=environment,
                timeout=configuration.command_timeout,
                diagnostic_id="MUTATION-006_REPORT",
                activity=f"completed mutation report for {domain}",
            )
            # Compute survivors using  survivors for later execute logic.
            survivors = _survivors(completed, mutants)
            # Handle the non-empty or enabled survivors state.
            if survivors:
                # Propagate the localized failure so callers cannot mistake it for success.
                raise _problem(
                    SURVIVOR_DIAGNOSTIC,
                    f"zero-survivor score for {domain} found {len(survivors)} surviving mutant(s)",
                    _survivor_output(survivors),
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
        # Return one successful observation per domain path to the caller.
        return tuple(results)


def run(root: Path) -> Report:
    """Produce one complete mutation report without leaking exceptions.

    @param root exact governed repository root
    @return green or red structured report
    """
    # Compute started using time.perf counter for later run logic.
    started = time.perf_counter()
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute tool using f"cosmic-ray {version('cosmic-ray')}" for later run logic.
        tool = f"cosmic-ray {version('cosmic-ray')}"
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except PackageNotFoundError:
        # Compute tool using "cosmic-ray unavailable" for later run logic.
        tool = "cosmic-ray unavailable"
        # Compute problem using  problem for later run logic.
        problem = _problem(
            "MUTATION-010_TOOL",
            "required distribution 'cosmic-ray' is not installed",
        )
    else:
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            # Compute configuration using load configuration for later run logic.
            configuration = load_configuration(root.resolve())
            # Compute results using execute for later run logic.
            results = execute(configuration)
        # Bind caught to the current value used by the next run decision.
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except MutationGateError as caught:
            # Compute problem using caught for later run logic.
            problem = caught
        else:
            # Capture mutants, result as the completed run outcome for subsequent validation or
            # Details: publication.
            mutants = sum(result.mutants for result in results)
            # Return green or red structured report to the caller.
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
    # Return green or red structured report to the caller.
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
    # Configure the command-line parser that defines this tool's invocation contract.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    # Capture the validated invocation arguments that govern this execution.
    arguments = parser.parse_args(argv)
    # Hold the decoded checker report mapping for typed summary and diagnostic extraction.
    report = run(arguments.root)
    # Select the guarded path only after `arguments.json` is satisfied.
    if arguments.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        # Compute prefix using "PASS" if report.status == "pass" else "FAIL" for later main
        # Details: logic.
        prefix = "PASS" if report.status == "pass" else "FAIL"
        # Compute diagnostic using "" if report.diagnostic_id is None else f" {report.diagnosti
        # Details: for later main logic.
        diagnostic = "" if report.diagnostic_id is None else f" {report.diagnostic_id}"
        print(f"{prefix}{diagnostic}: {report.summary}")
        # Select the guarded path only after `report.output` is satisfied.
        if report.output:
            print(report.output)
    # Return the aggregate process status to the command-line boundary.
    return EXIT_GREEN if report.status == "pass" else EXIT_RED


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    sys.exit(main())
