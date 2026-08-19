"""Proof-of-failure tests for the environment lock.

`DEP-005` and `DEP-006` are the rules this decides: the environment is pinned,
and a command says whether the running interpreter matches. Each case below
feeds the parser or the comparison something it must reject, because a verifier
only ever observed to pass has not been shown to verify anything (`FLOW-007`).

    pytest tools/test_check_env.py
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

import check_env

if TYPE_CHECKING:
    from pathlib import Path


def _write(tmp_path: Path, body: str) -> Path:
    """Place an environment declaration on disk.

    @param tmp_path the directory to write into
    @param body the file's contents
    @return the path written
    """
    path = tmp_path / "environment.yml"
    path.write_text(body, encoding="utf-8")
    return path


# ----------------------------------------------------------------- the parser


def test_exact_pins_are_read(tmp_path: Path) -> None:
    """The declaration is read without importing the parser it pins."""
    path = _write(tmp_path, "dependencies:\n  - python=3.13.14\n  - pip:\n"
                            "      - ruff==0.16.3\n      - PyYAML==6.0.3\n")
    python, pins, loose, _ = check_env.read_pins(path)
    assert python == "3.13.14"
    assert pins == {"ruff": "0.16.3", "PyYAML": "6.0.3"}
    assert loose == []


def test_a_package_named_only_in_a_comment_is_not_a_pin(tmp_path: Path) -> None:
    """environment.yml explains packages it deliberately does not pin.

    Mistaking that prose for a requirement would make the checker demand tools
    the file says outright are not installed.
    """
    path = _write(tmp_path, "dependencies:\n  - pip:\n      - ruff==0.16.3\n"
                            "# - mutmut==3.4.0 is named by TEST-013 and NOT pinned here\n")
    _, pins, _, _ = check_env.read_pins(path)
    assert pins == {"ruff": "0.16.3"}


def test_a_range_is_reported_as_a_defect_in_the_lock(tmp_path: Path) -> None:
    """A range is not a lock. Accepting one quietly would defeat the file."""
    path = _write(tmp_path, "dependencies:\n  - pip:\n      - ruff>=0.16.3\n")
    _, _, loose, _ = check_env.read_pins(path)
    assert len(loose) == 1
    assert "range" in loose[0]


def test_a_declaration_that_pins_nothing_is_refused(tmp_path: Path) -> None:
    """An empty lock must not read as a satisfied one."""
    path = _write(tmp_path, "dependencies:\n  - pip:\n")
    assert check_env.main(["--file", str(path)]) == 2


def test_a_missing_declaration_is_refused(tmp_path: Path) -> None:
    """Absent is not the same as matching."""
    assert check_env.main(["--file", str(tmp_path / "nothing.yml")]) == 2


# ------------------------------------------------------------- the comparison


def test_an_absent_package_is_drift() -> None:
    """A pin naming something not installed is the commonest drift there is."""
    problems = check_env.drift(None, {"a-package-that-is-not-installed": "1.0"})
    assert len(problems) == 1
    assert "not installed" in problems[0]


def test_a_wrong_version_is_drift() -> None:
    """Ruff 0.16.2 and 0.16.3 disagree by three findings in gate step 1."""
    problems = check_env.drift(None, {"pytest": "0.0.1"})
    assert len(problems) == 1
    assert "pinned 0.0.1" in problems[0]


def test_a_wrong_interpreter_is_drift() -> None:
    """The interpreter is part of the lock, not context around it."""
    problems = check_env.drift("3.0.0", {})
    assert len(problems) == 1
    assert problems[0].startswith("python:")


def test_a_matching_environment_reports_nothing() -> None:
    """The guard must not fire on the environment it was written for."""
    running = ".".join(str(part) for part in sys.version_info[:3])
    assert check_env.drift(running, {"pytest": check_env.installed("pytest") or ""}) == []


def test_drift_exits_non_zero(tmp_path: Path) -> None:
    """A verifier that reports drift on stdout and exits 0 blocks nothing."""
    path = _write(tmp_path, "dependencies:\n  - pip:\n"
                            "      - a-package-that-is-not-installed==1.0\n")
    assert check_env.main(["--file", str(path)]) == 1


# ------------------------------------------------------------ the CI reader


def test_requirements_are_emitted_for_ci(tmp_path: Path, capsys: object) -> None:
    """The workflow installs from the declaration instead of copying it.

    @param tmp_path the directory the fixture declaration is written into
    @param capsys pytest's capture fixture, read for the emitted lines
    """
    path = _write(tmp_path, "dependencies:\n  - python=3.13.14\n  - pip:\n"
                            "      - ruff==0.16.3\n      - PyYAML==6.0.3\n")
    assert check_env.main(["--file", str(path), "--print-requirements"]) == 0
    printed = capsys.readouterr().out.split()  # type: ignore[attr-defined]
    assert printed == ["PyYAML==6.0.3", "ruff==0.16.3"]


# ------------------------------------------------- conda pins, Phase 6


def test_a_conda_pin_is_read(tmp_path: Path) -> None:
    """A single-`=` line is a conda pin, not noise.

    `- doxygen=1.10.0` matches neither the pip pattern (which needs `==`) nor the
    loose-range one, so before this it was parsed by nothing and ignored in
    silence -- a declared dependency the lock did not actually cover.

    @param tmp_path the fixture directory
    """
    declaration = tmp_path / "environment.yml"
    declaration.write_text(
        "dependencies:\n  - python=3.13.14\n  - doxygen=1.10.0\n"
        "  - pip:\n      - ruff==0.16.3\n",
        encoding="utf-8",
    )
    python, pins, loose, conda = check_env.read_pins(declaration)
    assert python == "3.13.14"
    assert pins == {"ruff": "0.16.3"}
    assert conda == {"doxygen": "1.10.0"}
    assert loose == []


def test_a_conda_pin_nobody_can_verify_is_reported() -> None:
    """An unverifiable pin fails rather than passing quietly.

    The failure this refuses: adding a conda dependency the checker has no
    verifier for, and having the lock report success anyway. That is how a lock
    stops covering things one entry at a time.
    """
    problems = check_env.drift(None, {}, {"graphviz": "9.0.0"})
    assert problems
    assert "no way to verify it" in problems[0]


def test_a_verifiable_conda_pin_at_the_wrong_version_fails() -> None:
    """Doxygen is checked by running it, and a wrong pin is caught.

    Not skipped when doxygen is absent: `native_version` returning None produces
    a "not installed" complaint, which is also a failure. Either way this asserts
    something.
    """
    problems = check_env.drift(None, {}, {"doxygen": "0.0.1"})
    assert problems
    assert "doxygen" in problems[0]


def test_the_installed_doxygen_matches_its_pin() -> None:
    """The positive case: the declaration and the environment agree.

    @throws AssertionError when the pin and the installed binary differ
    """
    _, _, _, conda = check_env.read_pins(check_env.ENVIRONMENT_PATH)
    if "doxygen" not in conda:
        pytest.skip("this declaration pins no doxygen")
    assert check_env.drift(None, {}, conda) == []
