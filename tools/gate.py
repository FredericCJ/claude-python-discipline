"""The gate: every command a change must pass before it is offered.

One definition, in one place. `FLOW-009` requires the gate to exist somewhere
runnable rather than in prose that drifts, and three things now read it:

* `enforce/fitness/test_meta.py` proves each entry names a real file and starts;
* `tools/release.py` refuses to build an archive from a tree that fails it;
* `.github/workflows/gate.yml` spells the same eleven steps out, because a
  workflow step needs its own name and failure boundary --
  `test_meta.py::test_the_workflow_mirrors_the_gate` is what keeps that copy
  honest.

Kept as data rather than as a script so a caller can decide what to do with a
failure. Running it is `subprocess`; deciding about it is the caller's business.

It lives under `tools/` rather than `enforce/` for two practical reasons: both
readers already have `tools/` importable -- the test through `conftest.py`, the
release script by sitting in it -- and `tools/` is inside the documentation
gate's covered set, where `enforce/gate.py` would not have been.
"""

from __future__ import annotations

import argparse
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from pathlib import Path
from typing import Final

## The repository root, one level up from `tools/`, so the gate decides the same
## verdict whatever directory it was invoked from.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent

## Every command a change must pass, in the order a person would want them: the
## cheap and specific first, the whole test suite last, so the fastest signal
## arrives first. `sys.executable` rather than a bare `python`, because a bare
## `python` on a machine with more than one environment is a coin toss -- and on
## the machine this was written on it resolves to an interpreter with no pytest,
## where the suite reports nothing and looks like it passed.
## Each GATE element represents one step-name and command pair; execution order is preserved.
GATE: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("format and lint", (sys.executable, "tools/lint_gate.py")),
    ("rule corpus", (sys.executable, "tools/validate.py")),
    ("navigation graph", (sys.executable, "tools/build_graph.py", "--check")),
    ("generated artefacts", (sys.executable, "tools/build_index.py", "--check")),
    ("skill mirror", (sys.executable, "tools/build_skill_mirror.py", "--check")),
    ("documentation", (sys.executable, "tools/docgate.py", "--all")),
    # Two structural checks over enforce/fixtures/reference/, added once that
    # fixture gave them a subject. Both are wrapped in a script rather than named
    # directly, because both underlying tools exit 0 when pointed at nothing --
    # `python -m importlinter.cli` checks no contract and says nothing at all,
    # and mypy reports "no issues found in 0 source files". A gate entry that
    # cannot tell that from success is the defect these entries exist to remove,
    # so each wrapper asserts how much it actually examined.
    ("import contracts", (sys.executable, "tools/import_gate.py")),
    ("types", (sys.executable, "tools/type_gate.py")),
    # `V080` asks whether a mechanism exists; this asks whether it discriminates.
    # A rule nobody has watched reject anything may be deciding nothing, and
    # ARCH-013 was exactly that for as long as it was counted mechanized.
    ("discrimination", (sys.executable, "tools/discrimination_gate.py")),
    # Doxygen was installed, pinned and version-verified for a whole release
    # while the only invocation anywhere was `--version`. Four rules were
    # `external` on a tool that answered what version it was.
    ("documentation build", (sys.executable, "tools/doxygen_gate.py")),
    ("tests", (sys.executable, "-m", "pytest", "-q")),
)


def run(*, stop_early: bool = False) -> int:
    """Run every step in order and report each verdict.

    The tuple above stays data -- this is a convenience runner over it, not a
    second definition. Nothing here decides what a failure *means*; it reports
    which steps failed and returns a status, and `release.py` still makes its own
    decision from `GATE` directly.

    Added because `python tools/gate.py` was documented as the way to run the
    gate and did nothing at all: the module had no entry point, so it imported,
    exited 0, and looked exactly like a pass. That is the same defect this file's
    own comments describe in `lint-imports` and `mypy`, reproduced in the one
    place that exists to prevent it.

    @param stop_early whether to stop at the first failing step rather than
        running all of them; running on is the default because a reader usually
        wants the whole picture
        True enables stop early; false selects its disabled alternative.
    @return 0 when every step passed, 1 otherwise
    """
    # Each failed element names one unsuccessful gate step; execution order is preserved.
    failed: list[str] = []
    # Execute gate stages in the declared order while retaining every failed stage name.
    for name, command in GATE:
        # Execute this declared gate step and retain both diagnostics for the aggregate report.
        finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            command, cwd=REPO_ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False, timeout=1800,
        )
        # Each element is one nonblank child diagnostic record in original stream order.
        lines = [x for x in (finished.stdout + finished.stderr).splitlines() if x.strip()]
        # Preserve the completed operation outcome for validation and publication.
        verdict = "ok  " if finished.returncode == 0 else "FAIL"
        print(f"{verdict} {name:22s} {lines[-1][:90] if lines else ''}")
        # Retain this stage name and diagnostics when its process makes the aggregate gate red.
        if finished.returncode != 0:
            failed.append(name)
            # Emit captured diagnostic detail only when nonblank output is available.
            if lines:
                # Bound verbose failures to their most recent ordered diagnostic records.
                print("\n".join(f"       {x[:110]}" for x in lines[-12:]))
            # Stop after this failure only when the caller selected early termination.
            if stop_early:
                # Honor fail-fast mode after recording this failed gate stage.
                break
    # Report aggregate failure only when at least one gate step was unsuccessful.
    if failed:
        print(f"\ngate: {len(failed)} of {len(GATE)} step(s) failed -- "
              f"{', '.join(failed)}", file=sys.stderr)
        # Expose the completed run outcome to its caller.
        return 1
    print(f"\ngate: all {len(GATE)} steps passed")
    # Expose the completed run outcome to its caller.
    return 0


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stop-early", action="store_true",
                        help="stop at the first failing step")
    # Translate the aggregate verdict into the status observed by automation.
    raise SystemExit(run(stop_early=parser.parse_args().stop_early))
