"""Regeneration is idempotent, byte-stable, drift-detecting and committed.

**Oracle: differential.** Every assertion runs a generator twice, or runs it
against what is on disk, and compares bytes. Nothing here reads prose.

* `DEP-009` -- regeneration is idempotent and byte-stable
* `DEP-010` -- drift between model and output fails the build
* `DEP-011` -- generated output is committed

This suite is unusual among the fitness tests in having its subject *here*: the
corpus's own derived layer is a generated artefact of exactly the kind the rule
describes, and the three builders already expose the `--check` form the rule
requires. The property being protected is the one every staleness check rests on
-- if regeneration were not byte-stable, `--check` could only ever mean "this was
rebuilt just now".

    pytest enforce/fitness/test_generated.py
"""

from __future__ import annotations

import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from pathlib import Path
from typing import Final

import pytest

from decides import decides

## The repository root, three levels up from this file.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent.parent

## Each generator against the artefacts it owns. The `--check` form writes
## nothing and exits non-zero when what is on disk differs from what it would
## produce, which is `DEP-010` made runnable.
GENERATORS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("index", ("discipline/INDEX.md", "discipline/rules.json", "enforce/ENFORCEMENT.md")),
    ("graph", ("discipline/graph.json",)),
    ("skill_mirror", (".claude/skills/python-discipline/references/KERNEL.md",)),
)

## How the three builders are invoked.
COMMANDS: Final[dict[str, tuple[str, ...]]] = {
    "index": (sys.executable, "tools/build_index.py"),
    "graph": (sys.executable, "tools/build_graph.py"),
    "skill_mirror": (sys.executable, "tools/build_skill_mirror.py"),
}


def run(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    """Run one builder from the repository root.

    @param command the argv to run
    @return the finished process
    """
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv from GENERATORS, no shell
        command, cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=300,
    )


@pytest.mark.parametrize("name", [n for n, _ in GENERATORS])
@decides("DEP-009", "DEP-010", "DEP-011")
def test_regeneration_stable(name: str) -> None:
    """DEP-009, DEP-010, DEP-011: the artefact on disk is what the builder makes.

    Runs the `--check` form, which writes nothing and compares. A pass means all
    three at once: the output is byte-stable (or the comparison could not hold),
    drift is detected (that is what the check reports), and it is committed (or
    there would be nothing to compare against).

    @param name the generator under test
    """
    finished = run((*COMMANDS[name], "--check"))
    assert finished.returncode == 0, (
        f"the {name} artefacts differ from what the builder produces:\n"
        f"{finished.stdout[-600:]}{finished.stderr[-400:]}"
    )


@pytest.mark.parametrize(("name", "artefacts"), GENERATORS,
                         ids=[n for n, _ in GENERATORS])
def test_generated_output_is_committed(name: str, artefacts: tuple[str, ...]) -> None:
    """DEP-011: the artefact is in the tree, not produced on demand.

    Without this, `--check` would pass against a file nobody has ever seen.

    @param name the generator under test
    @param artefacts the files it owns
    """
    missing = [a for a in artefacts if not (REPO_ROOT / a).is_file()]
    assert not missing, f"{name} owns uncommitted artefact(s): {', '.join(missing)}"


def test_the_check_form_can_fail() -> None:
    """FLOW-007: the staleness check is observed failing, not assumed to work.

    A generated file is copied out, damaged in place, the check is run, and the
    original is restored -- so the assertion rests on a real non-zero exit rather
    than on the builder's reputation.

    The damage is done in place and undone in a `finally`, because `--check`
    compares the builder's output against the tree it is pointed at; a copy in a
    temporary directory would not be the file the builder reads.
    """
    target = REPO_ROOT / "discipline" / "INDEX.md"
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\ndrift\n")
        finished = run((*COMMANDS["index"], "--check"))
        assert finished.returncode != 0, (
            "the staleness check passed against a file that had been changed; "
            "every drift guarantee downstream of it is decorative"
        )
    finally:
        target.write_bytes(original)
