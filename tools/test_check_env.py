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

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from pathlib import Path


def _write(tmp_path: Path, body: str) -> Path:
    """Place an environment declaration on disk.

    @param tmp_path the directory to write into
    @param body the file's contents
    @return the path written

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = tmp_path / "environment.yml"
    path.write_text(body, encoding="utf-8")
    return path


# ----------------------------------------------------------------- the parser


def test_exact_pins_are_read(tmp_path: Path) -> None:
    """The declaration is read without importing the parser it pins."""
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = _write(tmp_path, "dependencies:\n  - python=3.13.14\n  - pip:\n"
                            "      - ruff==0.16.3\n      - PyYAML==6.0.3\n")
    # Unpack loose, pins, python from check env.read pins for the next test exact pins are read
    # decision.
    python, pins, loose, _ = check_env.read_pins(path)
    assert python == "3.13.14"
    assert pins == {"ruff": "0.16.3", "PyYAML": "6.0.3"}
    assert loose == []


def test_a_package_named_only_in_a_comment_is_not_a_pin(tmp_path: Path) -> None:
    """environment.yml explains packages it deliberately does not pin.

    Mistaking that prose for a requirement would make the checker demand tools
    the file says outright are not installed.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = _write(tmp_path, "dependencies:\n  - pip:\n      - ruff==0.16.3\n"
                            "# - mutmut==3.4.0 is named by TEST-013 and NOT pinned here\n")
    # Parse the fixture and isolate exact pip pins from explanatory comments.
    _, pins, _, _ = check_env.read_pins(path)
    assert pins == {"ruff": "0.16.3"}


def test_a_range_is_reported_as_a_defect_in_the_lock(tmp_path: Path) -> None:
    """A range is not a lock. Accepting one quietly would defeat the file."""
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = _write(tmp_path, "dependencies:\n  - pip:\n      - ruff>=0.16.3\n")
    # Parse the ranged requirement into the declaration-defect list.
    _, _, loose, _ = check_env.read_pins(path)
    assert len(loose) == 1
    assert "range" in loose[0]


def test_a_declaration_that_pins_nothing_is_refused(tmp_path: Path) -> None:
    """An empty lock must not read as a satisfied one."""
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = _write(tmp_path, "dependencies:\n  - pip:\n")
    assert check_env.main(["--file", str(path)]) == 2


def test_a_missing_declaration_is_refused(tmp_path: Path) -> None:
    """Absent is not the same as matching."""
    assert check_env.main(["--file", str(tmp_path / "nothing.yml")]) == 2


# ------------------------------------------------------------- the comparison


def test_an_absent_package_is_drift() -> None:
    """A pin naming something not installed is the commonest drift there is."""
    # Compare an intentionally nonexistent distribution against its declared pin.
    problems = check_env.drift(None, {"a-package-that-is-not-installed": "1.0"})
    assert len(problems) == 1
    assert "not installed" in problems[0]


def test_a_wrong_version_is_drift() -> None:
    """Ruff 0.16.2 and 0.16.3 disagree by three findings in gate step 1."""
    # Compare installed pytest metadata against an intentionally impossible version.
    problems = check_env.drift(None, {"pytest": "0.0.1"})
    assert len(problems) == 1
    assert "pinned 0.0.1" in problems[0]


def test_a_wrong_interpreter_is_drift() -> None:
    """The interpreter is part of the lock, not context around it."""
    # Compare the running interpreter against an intentionally obsolete exact pin.
    problems = check_env.drift("3.0.0", {})
    assert len(problems) == 1
    assert problems[0].startswith("python:")


def test_a_matching_environment_reports_nothing() -> None:
    """The guard must not fire on the environment it was written for."""
    # Reconstruct the exact lock spelling used by the environment verifier.
    running = ".".join(str(part) for part in sys.version_info[:3])
    assert check_env.drift(running, {"pytest": check_env.installed("pytest") or ""}) == []


def test_drift_exits_non_zero(tmp_path: Path) -> None:
    """A verifier that reports drift on stdout and exits 0 blocks nothing."""
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = _write(tmp_path, "dependencies:\n  - pip:\n"
                            "      - a-package-that-is-not-installed==1.0\n")
    assert check_env.main(["--file", str(path)]) == 1


# ------------------------------------------------------------ the CI reader


def test_requirements_are_emitted_for_ci(tmp_path: Path, capsys: object) -> None:
    """The workflow installs from the declaration instead of copying it.

    @param tmp_path the directory the fixture declaration is written into
    @param capsys pytest's capture fixture, read for the emitted lines
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = _write(tmp_path, "dependencies:\n  - python=3.13.14\n  - pip:\n"
                            "      - ruff==0.16.3\n      - PyYAML==6.0.3\n")
    assert check_env.main(["--file", str(path), "--print-requirements"]) == 0
    # Capture emitted requirement tokens for exact sorted-content comparison.
    printed = capsys.readouterr().out.split()  # type: ignore[attr-defined]
    assert printed == ["PyYAML==6.0.3", "ruff==0.16.3"]


# ------------------------------------------------- conda pins, Phase 6


def test_a_conda_pin_is_read(tmp_path: Path) -> None:
    """A single-`=` line is a conda pin, not noise.

    `- doxygen=1.10.0` matches neither the pip pattern (which needs `==`) nor the
    loose-range one, so before this it was parsed by nothing and ignored in
    silence -- a declared dependency the lock did not actually cover.

    @param tmp_path the fixture directory

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Select the temporary environment declaration receiving the native-tool fixture.
    declaration = tmp_path / "environment.yml"
    declaration.write_text(
        "dependencies:\n  - python=3.13.14\n  - doxygen=1.10.0\n"
        "  - pip:\n      - ruff==0.16.3\n",
        encoding="utf-8",
    )
    # Unpack conda, loose, pins, python from check env.read pins for the next test a conda pin
    # is read decision.
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
    # Compare an undeclared native verifier to prove unverifiable pins fail closed.
    problems = check_env.drift(None, {}, {"unverifiable-native": "9.0.0"})
    assert problems
    assert "no way to verify it" in problems[0]


def test_a_verifiable_conda_pin_at_the_wrong_version_fails() -> None:
    """Doxygen is checked by running it, and a wrong pin is caught.

    Not skipped when doxygen is absent: `native_version` returning None produces
    a "not installed" complaint, which is also a failure. Either way this asserts
    something.
    """
    # Compare the installed Doxygen probe against an intentionally wrong exact pin.
    problems = check_env.drift(None, {}, {"doxygen": "0.0.1"})
    assert problems
    assert "doxygen" in problems[0]


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        ("1.10.0 (7ce1305)", "1.10.0"),
        ("pip 26.2.1 from /opt/conda/site-packages/pip", "26.2.1"),
        ("git version 2.51.2.windows.1", "2.51.2"),
        ("v22.21.1", "22.21.1"),
    ],
)
def test_native_version_grammars_are_normalized(reported: str, expected: str) -> None:
    """Every shipped native executable's real output yields its lock identity.

    @param reported representative output from one supported executable
    @param expected the exact Conda version the checker must compare
    """
    assert check_env.parse_native_version(reported) == expected


def test_native_output_without_a_dotted_version_is_not_accepted() -> None:
    """A successful-looking word cannot satisfy an executable version pin."""
    assert check_env.parse_native_version("git version unknown") is None


def test_every_shipped_conda_tool_has_an_executable_probe() -> None:
    """Adding a lock member without a verifier must fail in the test nearest it."""
    # Parse shipped native-package pins for verifier-table coverage comparison.
    _, _, _, conda = check_env.read_pins(check_env.ENVIRONMENT_PATH)
    assert set(conda) == {"doxygen", "git", "graphviz", "nodejs", "pip"}
    assert set(conda) <= set(check_env.NATIVE_VERIFIERS)


def test_the_installed_native_tools_match_their_pins() -> None:
    """The positive case: every native declaration and environment agree.

    @throws AssertionError when the pin and the installed binary differ
    """
    # Parse shipped native-package pins for live executable-version comparison.
    _, _, _, conda = check_env.read_pins(check_env.ENVIRONMENT_PATH)
    if not conda:
        pytest.skip("this declaration pins no native tools")
    assert check_env.drift(None, {}, conda) == []
