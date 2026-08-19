"""Proof-of-failure tests for the release build's gates.

Each gate exists to stop one thing reaching an adopter, so each is tested on
material that should stop it, not only on material that should pass. The
archive is built once by hand at release time; these cover the decisions it
makes, which is where a silent mistake would live.

    pytest tools/test_release.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import release

if TYPE_CHECKING:
    from pathlib import Path


# ------------------------------------------------------------------- leak scan


def test_an_absolute_windows_path_is_found() -> None:
    """A path rooted in a user's home names the machine it was written on."""
    text = "see C:/Users/someone/Documents/repo/tools/nav.py for the navigator\n"
    found = list(release.scan_text("a.md", text, release.BLOCKING_PATTERNS))
    assert [f.pattern for f in found] == ["windows user path"]
    assert found[0].line == 1


def test_a_posix_home_path_is_found() -> None:
    """The same leak on the other platform."""
    found = list(release.scan_text(
        "a.md", "run /home/someone/src/x.py\n", release.BLOCKING_PATTERNS))
    assert [f.pattern for f in found] == ["posix home path"]


def test_a_relative_path_is_not_mistaken_for_a_home_path() -> None:
    """`tools/home/x` and a URL path must not fire the home-directory pattern."""
    text = "tools/home/x.py and https://example.com/users/api/v1\n"
    assert not list(release.scan_text("a.md", text, release.BLOCKING_PATTERNS))


def test_a_credential_prefix_is_found() -> None:
    """Published token formats are recognisable on sight, so recognise them."""
    text = "token = 'ghp_" + "a" * 30 + "'\n"
    assert [f.pattern for f in release.scan_text(
        "a.py", text, release.BLOCKING_PATTERNS)] == ["github token"]


def test_ordinary_corpus_prose_is_clean() -> None:
    """The scan must not fire on the discipline's own vocabulary."""
    text = "tokens: 1876\nThe secret is that there is no secret.\n`.agent/tools/nav.py`\n"
    assert not list(release.scan_text("a.md", text, release.BLOCKING_PATTERNS))


def test_a_credential_assignment_is_reviewable_not_blocking() -> None:
    """The rules about redaction have to show what redaction is for."""
    findings = list(release.scan_text(
        "a.py", 'password = "hunter2000"\n',
        (*release.BLOCKING_PATTERNS, *release.REVIEW_PATTERNS)))
    stops, reviewable = release.partition(findings)
    assert not stops
    assert [f.pattern for f in reviewable] == ["credential-shaped assignment"]


def test_the_building_account_is_derived_not_written_down() -> None:
    """The scan protects whoever runs it, not only its author's machine."""
    patterns = release.environment_literals("jdoe", "BUILD-BOX", "D:/home/jdoe")
    assert [label for label, _ in patterns] == [
        "build username", "build hostname", "build home directory"]
    found = list(release.scan_text("a.md", "written on build-box\n", patterns))
    assert [f.pattern for f in found] == ["build hostname"]


def test_short_or_absent_identifiers_are_dropped() -> None:
    """A one-character username would match most of the corpus."""
    assert release.environment_literals(None, "x", "  ") == ()


def test_a_host_named_after_a_common_word_can_still_build() -> None:
    """The defect this guard was written for: a machine named `MAIN`.

    Escaped as a bare literal, that hostname matched `def main(`, `__main__` and
    every mention of the branch, so the build aborted on thousands of findings
    and could not complete on that host at all.
    """
    patterns = release.environment_literals("jdoe", "MAIN", "D:/home/jdoe")
    assert [label for label, _ in patterns] == ["build username", "build home directory"]
    source = 'def main() -> int:\n    if __name__ == "__main__":\n        main()\n'
    assert list(release.scan_text("a.py", source, patterns)) == []


def test_dropping_an_unusable_identifier_is_reported_not_silent() -> None:
    """A scan running with fewer signals than usual must say so."""
    dropped = release.unusable_identifiers("jdoe", "MAIN", "D:/home/jdoe")
    assert [(label, value) for label, value, _ in dropped] == [("build hostname", "MAIN")]
    assert "too common" in dropped[0][2]


def test_an_absent_identifier_is_not_reported_as_dropped() -> None:
    """A machine that sets no USER is unremarkable; saying so is noise."""
    assert release.unusable_identifiers(None, "BUILD-BOX", "   ") == ()


def test_an_identifier_inside_a_longer_word_is_not_a_leak() -> None:
    """A short login name must not match every word that contains it."""
    patterns = release.environment_literals("ana", None, None)
    assert list(release.scan_text("a.md", "analysis of a banana\n", patterns)) == []
    found = list(release.scan_text("a.md", "written by ana today\n", patterns))
    assert [f.pattern for f in found] == ["build username"]


def test_a_genuine_identifier_is_still_caught_after_bounding() -> None:
    """Precision must not have been bought by switching the guard off."""
    patterns = release.environment_literals("jdoe", "BUILD-BOX", "D:/home/jdoe")
    text = "built under D:/home/jdoe by jdoe on build-box\n"
    assert {f.pattern for f in release.scan_text("a.md", text, patterns)} == {
        "build username", "build hostname", "build home directory"}


def test_an_excused_file_does_not_stop_the_build() -> None:
    """A fixture that proves a guard works must be allowed to contain its bait."""
    finding = release.Finding(".agent/tools/test_learn.py", 1, "aws access key", "AKIA...")
    stops, reviewable = release.partition([finding])
    assert not stops
    assert reviewable == [finding]
    assert release.excuse(finding.member, finding.pattern)


def test_an_excuse_covers_one_pattern_only() -> None:
    """The excuse is per shape, so a different leak in the same file still stops."""
    finding = release.Finding(".agent/tools/test_learn.py", 1, "windows user path", "C:/Users/")
    stops, _ = release.partition([finding])
    assert stops == [finding]


def test_an_excuse_does_not_cover_a_different_file() -> None:
    """Matching on the tail must not match a file that merely ends similarly."""
    assert release.excuse(".agent/tools/other_test_learn.py", "aws access key") is None


# --------------------------------------------------------------- member safety


def test_escaping_member_paths_are_rejected() -> None:
    """An archive member may not choose where it lands."""
    names = ["/etc/passwd", "C:/Windows/x", "../../x", "a/../../b", "a\\..\\b"]
    assert release.unsafe_members(names) == names


def test_ordinary_member_paths_are_accepted() -> None:
    """A relative name with a dot in it is not an escape."""
    assert not release.unsafe_members(
        [".agent/tools/integrate.py", "INSTALL-DISCIPLINE.md", "a/.b/c.md"])


# --------------------------------------------------------------------- pruning


def test_caches_and_databases_are_pruned(tmp_path: Path) -> None:
    """A cache in the archive would make the release depend on what had been run.

    @param tmp_path the per-test directory
    """
    (tmp_path / ".agent" / "tools" / "__pycache__").mkdir(parents=True)
    (tmp_path / ".agent" / "tools" / "__pycache__" / "nav.pyc").write_bytes(b"\x00")
    (tmp_path / ".agent" / "learning").mkdir(parents=True)
    (tmp_path / ".agent" / "learning" / "learning.db").write_bytes(b"\x00")
    (tmp_path / ".agent" / "tools" / "nav.py").write_text("x = 1\n", encoding="utf-8")

    removed = release.prune(tmp_path)

    assert ".agent/tools/__pycache__/" in removed
    assert ".agent/learning/learning.db" in removed
    assert release.members_of(tmp_path) == [".agent/tools/nav.py"]


def test_an_empty_project_directory_is_recorded(tmp_path: Path) -> None:
    """`overrides/` holds nothing on day one and must still arrive.

    @param tmp_path the per-test directory
    """
    (tmp_path / ".agent" / "overrides").mkdir(parents=True)
    (tmp_path / ".agent" / "learning").mkdir()
    (tmp_path / ".agent" / "learning" / "schema.sql").write_text("x", encoding="utf-8")
    assert release.empty_dirs(tmp_path) == [".agent/overrides/"]


# ---------------------------------------------------------------- empty ledger


def _seed(agent: Path) -> None:
    """Create a correctly seeded, empty project half.

    @param agent the staged `.agent/` directory
    """
    (agent / "learning").mkdir(parents=True)
    for name in release.LEDGER_SEEDS:
        (agent / "learning" / name).write_text("-- seed\n", encoding="utf-8")


def test_a_seeded_ledger_is_accepted(tmp_path: Path) -> None:
    """Seeds only is what the installer produces and what must ship.

    @param tmp_path the per-test directory
    """
    _seed(tmp_path / ".agent")
    assert release.ledger_problems(tmp_path / ".agent") == []


def test_a_populated_ledger_is_refused(tmp_path: Path) -> None:
    """Another project's learnings are not this adopter's rules.

    @param tmp_path the per-test directory
    """
    _seed(tmp_path / ".agent")
    (tmp_path / ".agent" / "learning" / "ledger.jsonl").write_text("{}\n", encoding="utf-8")
    assert release.ledger_problems(tmp_path / ".agent") == [
        "learning/ledger.jsonl is not a seed and must not ship"
    ]


def test_a_missing_seed_is_refused(tmp_path: Path) -> None:
    """An adopter who cannot record a learning cannot follow the discipline.

    @param tmp_path the per-test directory
    """
    (tmp_path / ".agent" / "learning").mkdir(parents=True)
    assert len(release.ledger_problems(tmp_path / ".agent")) == len(release.LEDGER_SEEDS)


def test_a_missing_learning_directory_is_refused(tmp_path: Path) -> None:
    """The project-owned half not existing at all is the louder failure.

    @param tmp_path the per-test directory
    """
    (tmp_path / ".agent").mkdir()
    assert release.ledger_problems(tmp_path / ".agent") == [
        "learning/ is missing; the installer did not seed it"
    ]
