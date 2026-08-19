"""Decide `law/DOC`'s generation rules by actually running Doxygen.

Four rules -- `DOC-005`, `DOC-007`, `DOC-010`, `DOC-011` -- are tagged `external`
on `auto:doxygen`. Doxygen was installed, pinned to 1.10.0, and version-verified
in the previous phase, and the only invocation anywhere in the repository was
`--version`. A tool that answers what version it is decides nothing about
documentation.

`enforce/Doxyfile` has been ready the whole time: `INPUT = src`,
`WARN_AS_ERROR = FAIL_ON_WARNINGS`. Nothing called it.

**The output goes to a temporary directory, not into the fixture.** `OUTPUT_DIRECTORY`
is overridden by feeding the configuration through stdin, because a gate step that
writes 235 files into `enforce/fixtures/reference/` would leave build products for
`broken_copy` to duplicate into every mutation and for the release to prune.

**The vacuity guard, and an honest note about it.** Every other tool wired into
this gate exits 0 when pointed at nothing, so each wrapper counts what it
examined. Doxygen turned out NOT to share that defect -- 1.10.0 reports "No files
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
from pathlib import Path
from typing import Final

## The repository root, one level up from `tools/`.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent

if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

from check_env import locate_native  # ruff: ignore[module-import-not-at-top-of-file]

## The tree Doxygen is pointed at. `INPUT = src` in the Doxyfile is relative to
## the working directory, so this is where the run happens from.
DEFAULT_ROOT: Final = REPO_ROOT / "enforce" / "fixtures" / "reference"

## The configuration, which is the one an adopter copies.
DOXYFILE: Final = REPO_ROOT / "enforce" / "Doxyfile"

## How many source pages must be generated before a clean run is believed. One
## page per input file; the reference holds 26.
MINIMUM_FILES: Final = 20

## Exit status when Doxygen ran, examined enough, and warned about nothing.
EXIT_OK: Final = 0

## Exit status when it warned, examined too little, or is not installed.
EXIT_FAILED: Final = 1


def run(root: Path, minimum: int) -> tuple[int, str]:
    """Generate documentation for one tree and report what happened.

    @param root the directory holding `src/`, and the working directory for the run
    @param minimum how many source pages must appear for the verdict to count
    @return the exit status and the line to print
    """
    executable = locate_native("doxygen")
    if executable is None:
        return EXIT_FAILED, (
            "doxygen is not installed in this environment or on PATH. It is "
            "pinned in environment.yml; `conda env update -f environment.yml`."
        )
    if not (root / "src").is_dir():
        return EXIT_FAILED, f"no src/ under {root}; nothing would be examined"

    output = Path(tempfile.mkdtemp(prefix="doxygen-gate-"))
    try:
        # The configuration is piped so `OUTPUT_DIRECTORY` can be overridden
        # without editing the file an adopter copies. Doxygen reads a config from
        # stdin when given `-`, and later assignments win.
        configuration = (DOXYFILE.read_text(encoding="utf-8")
                         + f"\nOUTPUT_DIRECTORY={output.as_posix()}\n")
        finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            (executable, "-"), input=configuration, cwd=root,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=False, timeout=600,
        )
        pages = len(list(output.rglob("*_source.html")))
    finally:
        shutil.rmtree(output, ignore_errors=True)

    if finished.returncode != 0:
        noise = (finished.stderr or finished.stdout).strip()
        return EXIT_FAILED, (
            f"doxygen reported warnings, and WARN_AS_ERROR makes those "
            f"failures:\n{noise[-1500:]}"
        )
    if pages < minimum:
        return EXIT_FAILED, (
            f"doxygen generated {pages} source page(s), below the {minimum} this "
            f"tree holds. It exited 0, so the files were not missing -- they were "
            f"filtered out, and a clean run over nothing is not a clean run."
        )
    return EXIT_OK, f"doxygen: clean over {pages} file(s)"


def main(argv: list[str] | None = None) -> int:
    """Run Doxygen over the tree and report.

    @param argv the command line, or None to read `sys.argv`
    @return the process exit status
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--minimum", type=int, default=MINIMUM_FILES,
                        help="source pages required for a clean verdict")
    arguments = parser.parse_args(argv)

    status, line = run(arguments.root, arguments.minimum)
    print(line, file=sys.stderr if status else sys.stdout)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
