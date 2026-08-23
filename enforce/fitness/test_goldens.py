"""A golden file is reviewed, never merely regenerated.

**Oracle: contract.** `TEST-008`, held against a project tree.

A golden test compares output against a committed expected file. Its whole value
rests on somebody having *read* that file and agreed with it. The failure mode is
specific and extremely common: the output changes, the test fails, the file is
regenerated, the test passes, and the suite has recorded the new behaviour as
correct without anyone deciding that it is. From then on the golden asserts that
the code does what the code does.

**Conditional, like the concurrency rules.** A project with no goldens satisfies
this completely; the reference has none, and says so in its README. What is
checked is that a project *with* goldens has a regeneration path that cannot be
taken silently -- an explicit flag or command, not an environment variable a CI
job might already be setting.

    pytest enforce/fitness/test_goldens.py
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from decides import decides
from fixtures import broken_copy, reference_root

# Import path typing only while static analyzers evaluate fixture contracts.
if TYPE_CHECKING:
    from pathlib import Path

## Golden-path glob string elements in explicit convention-coverage order. Search
## order is normalized away before results are returned.
GOLDEN_GLOBS: Final[tuple[str, ...]] = (
    "**/golden/**/*", "**/goldens/**/*", "**/__snapshots__/**/*",
    "**/*.golden", "**/*.approved.*", "**/*.snap",
)

## An explicit, deliberate regeneration path: something a person types.
_DELIBERATE = re.compile(r"(--(update|regenerate|bless|approve)[\w-]*"
                         r"|\bregenerate\b|\bbless\b)", re.IGNORECASE)

## A regeneration path that can be taken without anyone deciding to, because a
## CI job or a shell profile may already have set it.
_AMBIENT = re.compile(r"(environ\s*\[|getenv|environ\.get)\s*\(?\s*[\"'][^\"']*"
                      r"(UPDATE|SNAPSHOT|GOLDEN|REGEN)", re.IGNORECASE)


def goldens_in(root: Path) -> list[Path]:
    """Every golden file a project commits.

    @param root the project root
    @return unique golden-file path elements in sorted path order, excluding caches
    """
    # Accumulate file-path elements in glob traversal order before final sorting.
    found: list[Path] = []
    # Apply each supported naming convention in the declared coverage order.
    for pattern in GOLDEN_GLOBS:
        # Extend the candidate list only with real files outside interpreter caches.
        found += [
            p for p in root.glob(pattern)
            if p.is_file() and "__pycache__" not in p.parts
        ]
    # Return unique golden paths in deterministic repository-relative order.
    return sorted(set(found))


@decides("TEST-008")
def test_goldens_reviewed() -> None:
    """TEST-008: regeneration is deliberate, or there are no goldens.

    Vacuous on the reference by design. The two tests below are what stop that
    from being a free pass.
    """
    # Inventory the selected project before choosing the vacuous or governed path.
    root = reference_root()
    goldens = goldens_in(root)
    # Accept a project that commits no golden oracle and therefore needs no updater.
    if not goldens:
        # End the conditional obligation without manufacturing regeneration machinery.
        return

    # Combine ordered test-source contents into the regeneration-interface search corpus.
    harness = "\n".join(
        m.read_text(encoding="utf-8") for m in sorted(root.rglob("tests/**/*.py"))
    )
    # Require deliberate regeneration while rejecting ambient environment switches.
    assert _DELIBERATE.search(harness), (
        f"{len(goldens)} golden file(s) and no explicit regeneration path. A "
        f"golden regenerated on failure records the new behaviour as correct "
        f"without anyone deciding that it is."
    )
    assert not _AMBIENT.search(harness), (
        "goldens can be regenerated from an environment variable, which a CI job "
        "may already be setting. Regeneration that can happen by accident is "
        "regeneration nobody reviewed."
    )


def test_the_reference_commits_no_goldens() -> None:
    """The precondition, asserted rather than assumed.

    If this fails, the test above stopped being vacuous -- which is fine, and
    should be noticed rather than discovered later.
    """
    # Keep the reference's intended vacuous precondition explicit and executable.
    assert goldens_in(reference_root()) == []


def test_a_golden_with_no_deliberate_path_is_caught(tmp_path: Path) -> None:
    """The negative case, and the reason this suite is not a free pass.

    @param tmp_path the fixture directory

    @par Effects
    Creates an isolated damaged project containing a golden and its test harness.
    """
    # Build a negative project with a committed oracle but no regeneration interface.
    root = broken_copy(tmp_path, write={
        "tests/golden/expected.txt": "some output\n",
        "tests/integration/test_golden.py":
            '"""Tests. Oracle: golden."""\n\nfrom pathlib import Path\n\n\n'
            'def test_output_matches():\n    """Compare against the committed file."""\n'
            '    expected = Path("tests/golden/expected.txt").read_text()\n'
            '    assert expected\n',
    })
    # Prove the subject contains a golden before evaluating the missing-interface oracle.
    assert goldens_in(root), "the fixture did not create a golden"
    # Combine test-source elements in sorted path order for deliberate-switch detection.
    harness = "\n".join(
        m.read_text(encoding="utf-8") for m in sorted(root.rglob("tests/**/*.py"))
    )
    # Require the negative harness to remain free of an explicit regeneration path.
    assert not _DELIBERATE.search(harness)


def test_an_ambient_regeneration_switch_is_caught(tmp_path: Path) -> None:
    """The subtler negative case: a path that can be taken by accident.

    @param tmp_path the fixture directory

    @par Effects
    Creates an isolated damaged project containing an ambient golden updater.
    """
    # Build a negative project whose environment can update committed expected output.
    root = broken_copy(tmp_path, write={
        "tests/golden/expected.txt": "some output\n",
        "tests/integration/test_golden.py":
            '"""Tests. Oracle: golden."""\n\nimport os\nfrom pathlib import Path\n\n\n'
            'def test_output_matches():\n    """Regenerate if asked, by accident."""\n'
            '    target = Path("tests/golden/expected.txt")\n'
            '    if os.environ.get("UPDATE_GOLDENS"):\n'
            '        target.write_text("new output")\n'
            '    assert target.read_text()\n',
    })
    # Combine test-source elements in sorted path order for ambient-switch detection.
    harness = "\n".join(
        m.read_text(encoding="utf-8") for m in sorted(root.rglob("tests/**/*.py"))
    )
    # Require the configured environment-variable regeneration path to be detected.
    assert _AMBIENT.search(harness)
