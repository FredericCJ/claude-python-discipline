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
        # Retain the stable diagnostic separately from the human exception message.
        self.diagnostic_id = diagnostic_id
        # Bound child output at construction so no later report path can leak an unbounded log.
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
        # Convert the immutable report to a fresh JSON-shaped mapping in field order.
        record = asdict(self)
        # Replace nested dataclass values with explicit mappings in configured domain order.
        record["results"] = [asdict(result) for result in self.results]
        # Narrow the fully converted record for JSON serialization callers.
        return cast("dict[str, object]", record)


def _reject(diagnostic_id: str, detail: str) -> Never:
    """Raise one typed configuration refusal.

    @param diagnostic_id stable machine-facing failure code
    @param detail standalone explanation
    @return never; always raises
    @throws MutationGateError unconditionally
    """
    # Centralize unconditional configuration failures under the structured gate error.
    raise MutationGateError(diagnostic_id, detail)


def _problem(diagnostic_id: str, detail: str, output: str = "") -> MutationGateError:
    """Build a typed failure without embedding formatting in ``raise`` sites.

    @param diagnostic_id stable machine-facing failure code
    @param detail standalone explanation
    @param output bounded external-tool output
    @return structured mutation failure
    """
    # Construct, but do not raise, a failure for branches that must retain shared cleanup.
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
    for index, segment in enumerate(path):
        # Require each dotted prefix to exist as a table before descending further.
        if not isinstance(current, dict) or segment not in current:
            _reject(
                "MUTATION-001_CONFIGURATION",
                f"required table {'.'.join(path[: index + 1])!r} is absent",
            )
        # Preserve the documentation-stripped behavior fingerprint used for comparison.
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
    # Textual non-empty input is required before portable path parsing.
    if not isinstance(raw, str) or not raw.strip():
        _reject("MUTATION-001_CONFIGURATION", f"{field} entries must be strings")
    # Normalize Windows separators to the portable repository declaration spelling.
    candidate = PurePosixPath(raw.replace("\\", "/"))
    # Resolve the candidate beneath the exact governed root for confinement checks.
    absolute = root / Path(candidate.as_posix())
    # Refuse absolute, drive-qualified, traversal, and resolved escape spellings.
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
    # Reject a confined but absent mutation target before Cosmic Ray configuration is generated.
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
    # A target collection must be an explicit non-empty array to prevent vacuous runs.
    if not isinstance(raw, list) or not raw:
        _reject(
            "MUTATION-001_CONFIGURATION",
            f"{field} must be a non-empty path array",
        )
    # Preserve paths, value element values in deterministic source order.
    paths = tuple(_local_path(value, field, root) for value in raw)
    if len(set(paths)) != len(paths):
        _reject("MUTATION-001_CONFIGURATION", f"{field} contains duplicates")
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
    for relative in paths:
        # Resolve the declared relative subject beneath the validated root.
        absolute = root / Path(relative.as_posix())
        # Expand directories recursively while treating declared files as singleton candidates.
        candidates = absolute.rglob("*.py") if absolute.is_dir() else (absolute,)
        # Retain only regular Python candidates, deduplicating overlapping target roots.
        files.update(candidate for candidate in candidates if candidate.is_file())
    return tuple(sorted(files))


def load_configuration(root: Path) -> Configuration:
    """Load and prove every project-controlled mutation input.

    @param root exact governed repository root
    @return validated configuration
    @throws MutationGateError when TOML or a consumed field is invalid
    """
    # Address the exact-root declaration; mutation configuration never discovers ancestors.
    project_file = root / "pyproject.toml"
    # Translate project reads and TOML decoding into the stable configuration diagnostic.
    try:
        # Decode the project document while retaining an explicit mapping type boundary.
        document = cast(
            "Mapping[str, object]",
            tomllib.loads(project_file.read_text(encoding="utf-8")),
        )
    # Preserve the original filesystem or parser failure beneath the gate error.
    except (OSError, tomllib.TOMLDecodeError) as problem:
        # Bind the refusal to the exact project file that could not be loaded.
        raise _problem(
            CONFIGURATION_DIAGNOSTIC,
            f"cannot load {project_file}: {problem}",
        ) from problem
    declaration = _table(document, ("tool", "agent-discipline"))
    roles = _table(document, ("tool", "agent-discipline", "roles"))
    gate = _table(document, ("tool", "agent-discipline-gate", "mutation"))
    source_roots = _paths(
        declaration.get("source_roots"),
        "tool.agent-discipline.source_roots",
        root,
    )
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
        Each element is one basename supplied by ``copytree``; order is deliberately unused.
    @return names excluded from the isolated copy
    """
    # Return only cache, environment, VCS, and build names; input order is deliberately unused.
    return {
        # Each name is retained when it belongs to the fixed isolation exclusion set.
        name for name in names if name in IGNORED_DIRECTORIES
    }


def _isolated_copy(configuration: Configuration, workspace: Path) -> Path:
    """Copy the repository after refusing symlinks that could escape it.

    @param configuration validated mutation inputs
    @param workspace empty temporary parent
    @return isolated repository copy
    @throws MutationGateError when a symlink would make the copy ambiguous
    """
    # Inspect every repository entry before copying so no symlink target can retain ambient reach.
    for path in configuration.root.rglob("*"):
        # Any symbolic link makes isolation semantics dependent on an external target.
        if path.is_symlink():
            _reject(
                "MUTATION-004_SYMLINK",
                f"mutation isolation refuses repository symlink {path}",
            )
    destination = workspace / "repository"
    shutil.copytree(configuration.root, destination, ignore=_ignore)
    # Return the complete isolated repository only after the symlink-free copy succeeds.
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
    portable = tuple(argument.replace("\\", "/") for argument in arguments)
    # Quote the portable argv deterministically for Cosmic Ray's string command field.
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
    Writes one generated Cosmic Ray configuration to ``path``.
    """
    # Render the exact Cosmic Ray session declaration from the validated project model.
    body = (
        "[cosmic-ray]\n"
        f"module-path = {json.dumps(domain.as_posix())}\n"
        f"timeout = {configuration.mutant_timeout!r}\n"
        "excluded-modules = []\n"
        f"test-command = {json.dumps(_test_command(configuration, copied_root))}\n\n"
        "[cosmic-ray.distributor]\n"
        'name = "local"\n'
    )
    # Materialize the complete generated configuration with platform-stable newlines.
    path.write_text(body, encoding="utf-8", newline="\n")


def _environment(configuration: Configuration, copied_root: Path) -> dict[str, str]:
    """Build a deterministic import environment pointing only at copied source.

    @param configuration validated project inputs
    @param copied_root isolated repository root
    @return subprocess environment with an exact local ``PYTHONPATH``
    """
    # Build the child-process environment with the governed source root on its import path.
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
    # Execute the isolated mutation command while converting launch and timeout failures uniformly.
    try:
        # Retain status and both diagnostic channels as one mutation-step observation.
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
    # Preserve launch and timeout detail from the Cosmic Ray control command.
    except (OSError, subprocess.TimeoutExpired) as problem:
        # Translate host-process failure to the activity-specific stable diagnostic.
        raise _problem(
            diagnostic_id,
            f"{activity} did not complete within its finite budget: {problem}",
        ) from problem
    # Combine the checker's captured diagnostic streams without losing emission text.
    output = finished.stdout + finished.stderr
    # Reject Cosmic Ray initialization or execution failure before interpreting its inventory.
    if finished.returncode != 0:
        # Preserve combined output because initialization and execution failures are actionable.
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
    # Count parsed mutation records so an empty inventory cannot pass as success.
    count = 0
    for number, line in enumerate(output.splitlines(), 1):
        # Ignore separator lines while retaining original one-based diagnostic numbering.
        if not line.strip():
            # Continue to the next possible JSON work-item record.
            continue
        # Translate malformed JSON lines into bounded Cosmic Ray report diagnostics.
        try:
            # Decode one work-item/result pair without assuming its nested shape.
            record = json.loads(line)
        # Preserve decoder detail and exact line number for engine-report repair.
        except json.JSONDecodeError as problem:
            # Reject the whole inventory because its mutant count is no longer trustworthy.
            raise _problem(
                REPORT_DIAGNOSTIC,
                f"Cosmic Ray dump line {number} is not JSON: {problem}",
                output,
            ) from problem
        # Every dump line must contain the engine's two-element work-item/result pair.
        if not isinstance(record, list) or len(record) != WORK_ITEM_PAIR_SIZE:
            # Refuse malformed records rather than incrementing a false mutant count.
            raise _problem(
                REPORT_DIAGNOSTIC,
                f"Cosmic Ray dump line {number} is not a work-item/result pair",
                output,
            )
        # Credit this line only after its mutation outcome and module fields parse successfully.
        count += 1
    # A zero-item inventory cannot establish mutation-testing competence.
    if count == 0:
        _reject(
            "MUTATION-007_NO_MUTANTS",
            "Cosmic Ray generated no mutants for the declared domain paths",
        )
    # Return the positive number of structurally valid generated work items.
    return count


def _result_records(output: str) -> tuple[Mapping[str, object], ...]:
    """Parse completed Cosmic Ray result records and refuse pending work.

    @param output complete post-execution JSON-lines dump
    @return decoded result objects
    @throws MutationGateError when a result record is malformed
    """
    # Each results element is one completed result mapping; dump order is preserved.
    results: list[Mapping[str, object]] = []
    # Parse every nonblank JSON-lines record with one-based diagnostic numbering.
    for number, line in enumerate(output.splitlines(), 1):
        # Blank separators carry no work-item result.
        if not line.strip():
            # Continue to the next possible result record.
            continue
        # Translate malformed JSON into the stable report diagnostic.
        try:
            # Decode one work-item/result pair without trusting nested shape.
            record = json.loads(line)
        # Preserve decoder detail and exact dump line for repair.
        except json.JSONDecodeError as problem:
            # Reject the complete result set because execution completeness cannot be proven.
            raise _problem(
                REPORT_DIAGNOSTIC,
                f"Cosmic Ray result line {number} is not JSON: {problem}",
                output,
            ) from problem
        # Require the engine's exact two-element work-item/result envelope.
        if not isinstance(record, list) or len(record) != WORK_ITEM_PAIR_SIZE:
            # Refuse incompatible or truncated result records.
            raise _problem(
                REPORT_DIAGNOSTIC,
                f"Cosmic Ray result line {number} is not a work-item/result pair",
                output,
            )
        result = record[1]
        # Pending work carries no completed result mapping and must never count as killed.
        if not isinstance(result, dict):
            # Reject incomplete execution instead of silently omitting the work item.
            raise _problem(
                REPORT_DIAGNOSTIC,
                f"Cosmic Ray result line {number} has no completed result",
                output,
            )
        results.append(cast("Mapping[str, object]", result))
    # Freeze completed result mappings in engine emission order.
    return tuple(results)


def _baseline_passed(output: str) -> None:
    """Require one normally executed, passing unmutated test command.

    Cosmic Ray 8.7.0's baseline command treats ``incompetent`` as success.  The
    independent dump oracle closes that false-pass path.

    @param output JSON-lines dump of the baseline session
    @throws MutationGateError when execution was killed, incompetent, or absent
    """
    # Parse the baseline dump to completed records before interpreting outcomes.
    results = _result_records(output)
    # Exactly one unmutated test-command execution must be present.
    if len(results) != BASELINE_RESULT_COUNT:
        # Reject absent and duplicated baselines as equally incompetent evidence.
        raise _problem(
            BASELINE_DIAGNOSTIC,
            f"baseline produced {len(results)} results instead of exactly one",
            output,
        )
    # Select the sole structurally valid baseline result.
    result = results[0]
    # Normal worker completion plus survived test outcome means unmutated tests passed.
    if result.get("worker_outcome") != "normal" or result.get("test_outcome") != "survived":
        # Reject killed, incompetent, timed-out, or otherwise abnormal baseline behavior.
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
    # Parse every completed mutant result before comparing with the generated inventory.
    results = _result_records(output)
    # Result cardinality must equal the pre-execution mutant count.
    if len(results) != expected:
        # Refuse partial execution even if every reported subset member was killed.
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
    # Abnormal and incompetent outcomes are not equivalent to killed mutants.
    if invalid:
        # Report the invalid outcome count while preserving the bounded raw dump.
        raise _problem(
            EXECUTION_DIAGNOSTIC,
            f"{len(invalid)} mutant(s) were abnormal or incompetent, not killed",
            output,
        )
    # Return only normally completed survivors in engine result order.
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
    for index, result in enumerate(survivors, 1):
        # Read the mutation diff without trusting the engine's result field type.
        diff = result.get("diff")
        # Substitute a visible marker when surviving mutation text is unavailable.
        rendered = diff if isinstance(diff, str) and diff.strip() else "<mutation diff unavailable>"
        blocks.append(f"SURVIVOR {index}\n{rendered.strip()}")
    return "\n\n".join(blocks)


def execute(configuration: Configuration) -> tuple[DomainResult, ...]:
    """Run baseline, non-vacuity, mutation, and zero-survivor checks.

    @param configuration validated local mutation inputs
    @return one successful observation per domain path
    @throws MutationGateError on the first red proposition
    """
    # Keep every repository copy, session database, and generated config under one reclaimed root.
    with tempfile.TemporaryDirectory(prefix="agent-mutation-gate-") as temporary:
        # Convert the managed temporary directory to the path API used by isolation helpers.
        temporary_root = Path(temporary)
        # Copy the governed repository only after its symlink confinement check passes.
        copied_root = _isolated_copy(configuration, temporary_root)
        # Build the child-process environment with the governed source root on its import path.
        environment = _environment(configuration, copied_root)
        # Each results element is one domain observation, appended in declaration order.
        results: list[DomainResult] = []
        for index, domain in enumerate(configuration.domains):
            # Start the per-domain measurement before baseline and engine initialization.
            started = time.perf_counter()
            # Allocate a generated config unique to this declared domain index.
            config = temporary_root / f"cosmic-ray-{index}.toml"
            # Allocate a mutation session database distinct from baseline observations.
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
            survivors = _survivors(completed, mutants)
            # Any competent survivor is a concrete defect the configured tests failed to detect.
            if survivors:
                # Fail with only survivor diffs so killed-mutant output cannot hide repair evidence.
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
        # Return one successful non-empty observation per domain in declaration order.
        return tuple(results)


def run(root: Path) -> Report:
    """Produce one complete mutation report without leaking exceptions.

    @param root exact governed repository root
    @return green or red structured report
    """
    # Measure the complete tool lookup, configuration, isolation, and mutation execution path.
    started = time.perf_counter()
    try:
        # Bind the report to the installed mutation engine version before reading project input.
        tool = f"cosmic-ray {version('cosmic-ray')}"
    except PackageNotFoundError:
        # Preserve an explicit unavailable-tool identity in the red report.
        tool = "cosmic-ray unavailable"
        # Construct the stable missing-distribution failure shared by the final report path.
        problem = _problem(
            "MUTATION-010_TOOL",
            "required distribution 'cosmic-ray' is not installed",
        )
    else:
        # Translate configuration and execution refusals into one complete red report.
        try:
            # Load every repository-controlled mutation input before allocating engine state.
            configuration = load_configuration(root.resolve())
            # Execute baseline, inventory, mutation, competence, and survivor proofs.
            results = execute(configuration)
        # Retain the structured gate error for the shared red report construction.
        except MutationGateError as caught:
            # Preserve the failed proposition's exact diagnostic, summary, and bounded output.
            problem = caught
        else:
            # Sum independently positive domain counts into the report's total mutant evidence.
            mutants = sum(result.mutants for result in results)
            # Publish success only after every declared domain completed with zero survivors.
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
    # Publish the structured failure selected by tool lookup, configuration, or execution.
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
    # Parse the exact project root and report format before constructing the mutation verdict.
    arguments = parser.parse_args(argv)
    # Produce the complete structured mutation verdict for the requested exact root.
    report = run(arguments.root)
    if arguments.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        # Select the concise human status prefix from the closed report state.
        prefix = "PASS" if report.status == "pass" else "FAIL"
        # Include stable diagnostic identity only for red reports.
        diagnostic = "" if report.diagnostic_id is None else f" {report.diagnostic_id}"
        print(f"{prefix}{diagnostic}: {report.summary}")
        # Print bounded external output only when the failure retained actionable detail.
        if report.output:
            print(report.output)
    return EXIT_GREEN if report.status == "pass" else EXIT_RED


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    # Translate the structured verdict to the sole process exit boundary.
    sys.exit(main())
