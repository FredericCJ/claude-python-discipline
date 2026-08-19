"""Doxygen is watched catching something, and watched refusing to be vacuous.

**Oracle: differential.** The generator runs over the conformant reference and over
copies damaged in ways `law/DOC` names, and the verdicts are compared.

For the whole of its life in this repository Doxygen was installed, pinned, and
invoked only as `--version`. Four rules were `external` on it. A tool that reports
what version it is decides nothing about documentation, and these are what make
the difference visible.

**What this gate does and does not decide, measured rather than assumed.**
`enforce/Doxyfile` disables `WARN_IF_UNDOCUMENTED` and `WARN_NO_PARAMDOC` -- both
are consequences of defects verified at exactly 1.10.0 and recorded in
`discipline/fact/doxygen.md`. So an undocumented function passes this gate, and
`DOC-007` is decided by `check:doc_coverage` alone. What IS enabled is
`WARN_IF_DOC_ERROR` and `WARN_IF_INCOMPLETE_DOC` under `WARN_AS_ERROR`, which is
`DOC-005` and `DOC-010`; the page count is `DOC-011`.

    pytest tools/test_doxygen_gate.py
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, Final

import pytest

import doxygen_gate

if TYPE_CHECKING:
    from pathlib import Path

## Skip rather than fail where the binary is absent: `check_env.py` already fails
## the environment for a missing pin, and a second failure for one cause is noise.
_DOXYGEN: Final = doxygen_gate.locate_native("doxygen")

## Applied to every test here: the gate needs the binary, and `check_env.py`
## already fails the environment when the pin is missing. A second failure for
## one cause is noise a reader learns to skim.
pytestmark = pytest.mark.skipif(_DOXYGEN is None,
                                reason="doxygen is not installed in this environment")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A writable copy of the reference package.

    @param tmp_path the per-test directory
    @return the copy's root
    """
    destination = tmp_path / "reference"
    shutil.copytree(doxygen_gate.DEFAULT_ROOT, destination,
                    ignore=shutil.ignore_patterns("__pycache__", "build",
                                                  ".pytest_cache", ".mypy_cache"))
    return destination


def test_the_reference_generates_cleanly() -> None:
    """The positive case, asserted first.

    A gate that failed on the conformant package would make every negative below
    meaningless, and would be reporting the fixture rather than the rule.
    """
    status, line = doxygen_gate.run(doxygen_gate.DEFAULT_ROOT,
                                    doxygen_gate.MINIMUM_FILES)
    assert status == doxygen_gate.EXIT_OK, line


def test_a_documented_parameter_that_does_not_exist_is_caught(tree: Path) -> None:
    """DOC-005: a docstring is parsed as documentation, so it can be wrong.

    The case that proves the gate reads the docstrings rather than merely reading
    the files: `@param ghost` names an argument the signature does not have, and
    only a parser can tell.

    @param tree a writable copy of the reference
    """
    plan = tree / "src" / "refpkg" / "domain" / "plan.py"
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            "    @param entries the files under consideration, in any order",
            "    @param entries the files under consideration, in any order\n"
            "    @param ghost a parameter this function does not have", 1),
        encoding="utf-8",
    )
    status, line = doxygen_gate.run(tree, doxygen_gate.MINIMUM_FILES)
    assert status == doxygen_gate.EXIT_FAILED
    assert "ghost" in line


def test_generating_nothing_is_not_generating_cleanly(tmp_path: Path) -> None:
    """DOC-011: an empty run is a failed run.

    Written expecting the failure every other tool here has -- exiting 0 over an
    empty input -- and doxygen 1.10.0 turned out not to share it: it reports "No
    files to be processed" and fails on its own. The assertion is on the VERDICT
    rather than the wording, so it holds either way, and the module docstring was
    corrected rather than the test bent to fit the claim.

    @param tmp_path the fixture directory
    """
    (tmp_path / "src").mkdir()
    status, line = doxygen_gate.run(tmp_path, doxygen_gate.MINIMUM_FILES)
    assert status == doxygen_gate.EXIT_FAILED
    assert "no files to be processed" in line.lower() or "source page" in line


def test_no_src_is_refused_rather_than_passed(tmp_path: Path) -> None:
    """A tree with nothing to document is a caller error, not a clean run.

    @param tmp_path the fixture directory
    """
    status, _ = doxygen_gate.run(tmp_path, doxygen_gate.MINIMUM_FILES)
    assert status == doxygen_gate.EXIT_FAILED


def test_the_run_leaves_the_fixture_untouched() -> None:
    """The gate writes 235 files, and none of them into the reference.

    `OUTPUT_DIRECTORY` is overridden through stdin precisely so build products do
    not land in `enforce/fixtures/reference/`, where `broken_copy` would duplicate
    them into every mutation and the release would have to prune them.
    """
    before = {p.name for p in doxygen_gate.DEFAULT_ROOT.iterdir()}
    doxygen_gate.run(doxygen_gate.DEFAULT_ROOT, doxygen_gate.MINIMUM_FILES)
    assert {p.name for p in doxygen_gate.DEFAULT_ROOT.iterdir()} == before, (
        "the documentation run left build products in the fixture"
    )


def test_an_undocumented_function_is_not_caught_here(tree: Path) -> None:
    """The gate's limit, pinned so nobody credits it with more than it does.

    `WARN_IF_UNDOCUMENTED` is off because of a defect verified at Doxygen 1.10.0.
    An undocumented element therefore passes this gate, and `DOC-001`/`DOC-007`
    rest entirely on `check:doc_coverage`. If a later Doxygen lets those warnings
    be turned back on, THIS TEST IS WHAT FAILS -- which is the prompt to re-read
    `discipline/fact/doxygen.md` and move the setting.

    @param tree a writable copy of the reference
    """
    model = tree / "src" / "refpkg" / "domain" / "model.py"
    model.write_text(
        model.read_text(encoding="utf-8")
        + "\n\ndef undocumented(value: int) -> int:\n    return value\n",
        encoding="utf-8",
    )
    status, _ = doxygen_gate.run(tree, doxygen_gate.MINIMUM_FILES)
    assert status == doxygen_gate.EXIT_OK, (
        "doxygen now warns about undocumented elements; re-check "
        "discipline/fact/doxygen.md and consider enabling WARN_IF_UNDOCUMENTED"
    )
