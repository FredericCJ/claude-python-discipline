"""Decide `law/DOC`'s generation and relationship rules by running Doxygen.

The structured documentation rules are tagged `external` on `auto:doxygen`.
Doxygen's version probe establishes tool identity but decides nothing about the
documented tree, so this gate runs the qualified 1.17 posture and inspects the
generated source and relationship projection.

`enforce/Doxyfile` has been ready the whole time: `INPUT = src`,
`WARN_AS_ERROR = FAIL_ON_WARNINGS`. Nothing called it.

**The output goes to a temporary directory, not into the fixture.** `OUTPUT_DIRECTORY`
is overridden by feeding the configuration through stdin, because a gate step that
writes 235 files into `enforce/fixtures/reference/` would leave build products for
`broken_copy` to duplicate into every mutation and for the release to prune.

**The vacuity guard, and an honest note about it.** Every other tool wired into
this gate exits 0 when pointed at nothing, so each wrapper counts what it
examined. Doxygen turned out NOT to share that defect -- 1.17.0 reports "No files
to be processed" and fails. The page count is kept anyway, because it guards the
case doxygen does not: `INPUT` matching files that all get filtered out by
`FILE_PATTERNS` or `EXCLUDE`, which produces a successful run over nothing. It is
belt-and-braces rather than load-bearing, and saying so is cheaper than a reader
later discovering the docstring overstated it.

    python tools/doxygen_gate.py
    python tools/doxygen_gate.py --root path/to/tree
"""

from __future__ import annotations

import argparse
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator

## The repository root, one level up from `tools/`.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent

# Prepend the local tools directory only when import resolution does not already contain it.
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

from check_env import locate_native  # ruff: ignore[module-import-not-at-top-of-file]

## The tree Doxygen is pointed at. `INPUT = src` in the Doxyfile is relative to
## the working directory, so this is where the run happens from.
DEFAULT_ROOT: Final = REPO_ROOT / "enforce" / "fixtures" / "reference"

## Minimal source tree used to qualify version-dependent Doxygen behavior.
PROBE_ROOT: Final = REPO_ROOT / "enforce" / "fixtures" / "doxygen_probe"

## The configuration, which is the one an adopter copies.
DOXYFILE: Final = REPO_ROOT / "enforce" / "Doxyfile"

## How many source pages must be generated before a clean run is believed. One
## page per input file; the reference holds 26.
MINIMUM_FILES: Final = 20

## Exit status when Doxygen ran, examined enough, and warned about nothing.
EXIT_OK: Final = 0

## Exit status when it warned, examined too little, or is not installed.
EXIT_FAILED: Final = 1


@dataclass(frozen=True)
class GeneratedDocumentation:
    """! One Doxygen process result while its temporary output still exists.

    @var finished completed native process, including captured diagnostic streams
    @var output temporary output directory; valid only inside `generated()`
    @var source_pages number of generated Python source pages
    @var relation_graphs call, caller, and directory-dependency SVG counts
    """

    ## Completed Doxygen process carrying status and captured output.
    finished: subprocess.CompletedProcess[str]
    ## Isolated generated-documentation root removed when the context closes.
    output: Path
    ## Count of generated Python source pages used for the non-vacuity verdict.
    source_pages: int
    ## Call, caller, and directory-dependency graph-count elements in that order.
    relation_graphs: tuple[int, int, int]


@contextmanager
def generated(
    executable: str,
    root: Path,
    *,
    extra_configuration: str = "",
) -> Iterator[GeneratedDocumentation]:
    """! Generate documentation and expose the output for bounded inspection.

    @param executable resolved Doxygen executable
    @param root directory holding the configured `src/`
    @param extra_configuration newline-delimited overrides appended last
    @return a context yielding the process result and temporary output
    """
    # Create the isolated Doxygen output root whose lifetime is confined by this context.
    output = Path(tempfile.mkdtemp(prefix="doxygen-gate-"))
    try:
        # Later Doxygen assignments win, so the gate can redirect products and a
        # qualification probe can enable an additional machine-readable view.
        configuration = (
            DOXYFILE.read_text(encoding="utf-8")
            + f"\nOUTPUT_DIRECTORY={output.as_posix()}\n"
            + extra_configuration
        )
        finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            (executable, "-"),
            input=configuration,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=600,
        )
        source_pages = len(list(output.rglob("*_source.html")))
        html = output / "html"
        # Preserve call, caller, and directory graph-count elements in declared relation order.
        relation_graphs = (
            len(list(html.glob("*_cgraph.svg"))),
            len(list(html.glob("*_icgraph.svg"))),
            len(list(html.glob("*_dep.svg"))),
        )
        yield GeneratedDocumentation(finished, output, source_pages, relation_graphs)
    finally:
        shutil.rmtree(output, ignore_errors=True)


def run(root: Path, minimum: int) -> tuple[int, str]:
    """Generate documentation for one tree and report what happened.

    @param root the directory holding `src/`, and the working directory for the run
    @param minimum how many source pages must appear for the verdict to count
    @return the exit status and the line to print
    """
    # Resolve the qualified native Doxygen executable required by this gate.
    executable = locate_native("doxygen")
    # Refuse documentation generation with environment remediation when Doxygen is unavailable.
    if executable is None:
        # Return the missing-tool refusal and its environment remediation.
        return EXIT_FAILED, (
            "doxygen is not installed in this environment or on PATH. It is "
            "pinned in environment.yml; `conda env update -f environment.yml`."
        )
    # Refuse the target when its declared source directory is absent.
    if not (root / "src").is_dir():
        # Return the empty-target refusal before invoking the documentation tool.
        return EXIT_FAILED, f"no src/ under {root}; nothing would be examined"

    # Generate into an isolated directory that is removed on every return path.
    with generated(executable, root) as result:
        # Retain the Doxygen process outcome independently from projection non-vacuity counts.
        finished = result.finished
        # Preserve the generated source-page count used to reject a vacuous build.
        pages = result.source_pages
        # Preserve call, caller, and directory graph counts in declared relation order.
        relations = result.relation_graphs

    # Enter the failure path only when the subprocess reports a nonzero status.
    if finished.returncode != 0:
        # Select the captured Doxygen diagnostics that explain the failed build.
        noise = (finished.stderr or finished.stdout).strip()
        # Return the tool-failure verdict with bounded diagnostic context.
        return EXIT_FAILED, (
            f"doxygen reported warnings, and WARN_AS_ERROR makes those failures:\n{noise[-1500:]}"
        )
    # Refuse a vacuous documentation build whose generated source coverage is below the floor.
    if pages < minimum:
        # Return the coverage refusal with observed and required page counts.
        return EXIT_FAILED, (
            f"doxygen generated {pages} source page(s), below the {minimum} this "
            f"tree holds. It exited 0, so the files were not missing -- they were "
            f"filtered out, and a clean run over nothing is not a clean run."
        )
    # Require every ordered relation-count element to prove one graph class is nonempty.
    # Refuse documentation that omits any required relationship-graph class.
    if any(count == 0 for count in relations):
        # Preserve relationship-label string elements in the same order as graph counts.
        labels = ("call", "caller", "directory dependency")
        # Format the relationship labels whose generated graph count is zero.
        missing = ", ".join(
            # Pair each label with its same-position count before selecting absent graphs.
            label for label, count in zip(labels, relations, strict=True) if count == 0
        )
        # Return the relationship refusal with every absent graph class named.
        return EXIT_FAILED, (
            "doxygen generated entity pages but no "
            f"{missing} relationship graph; enable and exercise the relation in source"
        )
    # Return the successful page and relationship counts to the command-line boundary.
    return EXIT_OK, (
        f"doxygen: clean over {pages} file(s), relations="
        f"call:{relations[0]}/caller:{relations[1]}/dependency:{relations[2]}"
    )


def main(argv: list[str] | None = None) -> int:
    """Run Doxygen over the tree and report.

    @param argv the command line, or None to read `sys.argv`
    @return the process exit status
    """
    # Configure the command-line parser that defines this tool's invocation contract.
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument(
        "--minimum",
        type=int,
        default=MINIMUM_FILES,
        help="source pages required for a clean verdict",
    )
    # Capture the validated invocation arguments that govern this execution.
    arguments = parser.parse_args(argv)

    # Capture the gate status and its single user-facing diagnostic line together.
    status, line = run(arguments.root, arguments.minimum)
    print(line, file=sys.stderr if status else sys.stdout)
    return status


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    # Convert the gate verdict to a process status only at the executable boundary.
    raise SystemExit(main())
