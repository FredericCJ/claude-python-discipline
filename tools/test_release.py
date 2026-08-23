"""Proof-of-failure tests for the release build's gates.

Each gate exists to stop one thing reaching an adopter, so each is tested on
material that should stop it, not only on material that should pass. The suite
also builds and operates the delivered archive itself, because helper-level
coverage cannot prove that the package actually contains a working installer.

    pytest tools/test_release.py
"""

from __future__ import annotations

import json
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- packaged CLI boundary
import sys
import zipfile
from typing import TYPE_CHECKING

import pytest

import release
import vendor
from discipline_core import REPO_ROOT

if TYPE_CHECKING:
    from pathlib import Path


def _extract_archive(archive_path: Path, root: Path) -> None:
    """Extract a produced archive only after proving every name is confined.

    @param archive_path deterministic package to unpack
    @param root fresh repository or upgrade-source directory
    """
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        escaping = release.unsafe_members([info.filename for info in infos])
        assert escaping == []
        for info in infos:
            destination = root.joinpath(*info.filename.split("/"))
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(info))


def _run_script(root: Path, script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Invoke a packaged tool without importing from the source checkout.

    @param root working repository for the invocation
    @param script extracted package entry point
    @param arguments public CLI arguments
    @return captured process result
    """
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed interpreter and extracted script
        (sys.executable, str(script), *arguments),
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=60,
    )


def _integrate(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the extracted combined-host integrator.

    @param root repository carrying the extracted package
    @param arguments integration mode such as check or remove
    @return captured process result
    """
    return _run_script(
        root,
        root / ".agent" / "tools" / "integrate.py",
        "--root",
        str(root),
        *arguments,
    )


def _assert_ok(completed: subprocess.CompletedProcess[str]) -> None:
    """Make a failed packaged invocation retain both diagnostic channels.

    @param completed captured packaged process
    """
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _native_skill(root: Path, host: str) -> Path:
    """Locate one host's installed native skill.

    @param root repository carrying the integration
    @param host `.claude` or `.agents`
    @return host-native skill entry point
    """
    return root / host / "skills" / "python-discipline" / "SKILL.md"


@pytest.fixture(scope="session")
def built_archives(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Build the same source twice through the real release pipeline.

    @param tmp_path_factory session-scoped temporary-directory provider
    @return two independently staged archives
    """
    root = tmp_path_factory.mktemp("release-archives")
    first = root / "first.zip"
    second = root / "second.zip"
    first_count, _ = release.build(REPO_ROOT, first, root / "stage-first")
    second_count, _ = release.build(REPO_ROOT, second, root / "stage-second")
    assert first_count == second_count > 0
    return first, second


def _copy_release_source(destination: Path) -> None:
    """Copy only inputs a release build consumes into a mutable source tree.

    @param destination fresh source root for an upgrade archive
    """
    destination.mkdir(parents=True)
    ignored = shutil.ignore_patterns(
        *vendor.SKIP_DIRS,
        "build",
        "dist",
        ".git",
    )
    for name in vendor.UPSTREAM:
        shutil.copytree(REPO_ROOT / name, destination / name, ignore=ignored)
    for name in vendor.UPSTREAM_FILES:
        shutil.copy2(REPO_ROOT / name, destination / name)
    learning = destination / "learning"
    learning.mkdir()
    for name in vendor.LEARNING_SEED:
        shutil.copy2(REPO_ROOT / "learning" / name, learning / name)
    packaging = destination / "packaging"
    packaging.mkdir()
    shutil.copy2(
        REPO_ROOT / "packaging" / "INSTALL-DISCIPLINE.md",
        packaging / "INSTALL-DISCIPLINE.md",
    )
    notes = f"RELEASE-NOTES-{vendor.RELEASE}.md"
    shutil.copy2(REPO_ROOT / notes, destination / notes)


# ----------------------------------------------------------- archive lifecycle


@pytest.mark.timeout(180)
def test_two_clean_archive_builds_are_byte_identical(
    built_archives: tuple[Path, Path],
) -> None:
    """Independent staging cannot move bytes, members, times, or permissions.

    @param built_archives independently staged packages
    """
    first, second = built_archives
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        assert release.unsafe_members(names) == []
        assert set(release.REQUIRED_MEMBERS) <= set(names)
        assert all(info.date_time == release.ZIP_EPOCH for info in infos)
        manifest = json.loads(archive.read(".agent/MANIFEST.json"))
        canonical = archive.read(".agent/skills/python-discipline/SKILL.md")
    assert manifest["release"] == vendor.RELEASE
    assert "skills/python-discipline/SKILL.md" in manifest["files"]
    assert "dev/docker.sh" in manifest["files"]
    assert "dev/windows.ps1" in manifest["files"]
    assert "environment.yml" in manifest["files"]
    assert ".dockerignore" in manifest["files"]
    assert canonical.startswith(b"---\nname: python-discipline\n")


@pytest.mark.timeout(180)
def test_archive_installs_checks_and_removes_both_host_entries(
    tmp_path: Path,
    built_archives: tuple[Path, Path],
) -> None:
    """The delivered package owns one skill and restores host-owned material.

    @param tmp_path fresh adopter repository
    @param built_archives independently staged packages
    """
    root = tmp_path / "adopter"
    root.mkdir()
    original = {
        "CLAUDE.md": b"# Project Claude\r\n",
        "AGENTS.md": b"# Project Codex\n",
        ".gitignore": b"project-output/\n",
    }
    for name, content in original.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    settings = {
        "project": {"owner": "adopter"},
        "permissions": {"allow": ["Bash(project-check:*)"]},
    }
    settings_path = root / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    _extract_archive(built_archives[0], root)

    vendored_check = _run_script(
        root,
        root / ".agent" / "tools" / "vendor.py",
        "check",
        str(root),
        "--source",
        str(root / ".agent"),
    )
    _assert_ok(vendored_check)
    _assert_ok(_integrate(root))
    _assert_ok(_integrate(root, "--check"))

    canonical = root / ".agent" / "skills" / "python-discipline" / "SKILL.md"
    for host in (".claude", ".agents"):
        assert _native_skill(root, host).read_bytes() == canonical.read_bytes()

    _assert_ok(_integrate(root, "--remove"))
    for name, content in original.items():
        assert (root / name).read_bytes() == content
    assert json.loads(settings_path.read_text(encoding="utf-8")) == settings
    assert not _native_skill(root, ".claude").exists()
    assert not _native_skill(root, ".agents").exists()


@pytest.mark.timeout(180)
def test_archive_refuses_a_codex_collision_without_blocking_claude(
    tmp_path: Path,
    built_archives: tuple[Path, Path],
) -> None:
    """An unowned Codex skill survives while the independent Claude path lands.

    @param tmp_path fresh adopter repository
    @param built_archives independently staged packages
    """
    root = tmp_path / "collision"
    _extract_archive(built_archives[0], root)
    codex = _native_skill(root, ".agents")
    codex.parent.mkdir(parents=True)
    codex.write_bytes(b"project-owned Codex skill\r\n")

    completed = _integrate(root)

    assert completed.returncode == 1
    assert codex.read_bytes() == b"project-owned Codex skill\r\n"
    assert _native_skill(root, ".claude").read_bytes() == (
        root / ".agent" / "skills" / "python-discipline" / "SKILL.md"
    ).read_bytes()


@pytest.mark.timeout(180)
def test_archive_upgrade_preserves_project_state_and_updates_both_hosts(
    tmp_path: Path,
    built_archives: tuple[Path, Path],
) -> None:
    """The packaged vendor path upgrades owned bytes without overlay extraction.

    @param tmp_path fresh adopter and mutable release source
    @param built_archives independently staged packages
    """
    root = tmp_path / "upgrade-adopter"
    _extract_archive(built_archives[0], root)
    _assert_ok(_integrate(root))
    learning = root / ".agent" / "learning" / "config.toml"
    project_learning = learning.read_bytes() + b"\n# project-owned\n"
    learning.write_bytes(project_learning)

    source = tmp_path / "upgrade-source"
    _copy_release_source(source)
    source_skill = source / "skills" / "python-discipline" / "SKILL.md"
    marker = b"\nArchive upgrade marker.\n"
    source_skill.write_bytes(source_skill.read_bytes() + marker)
    upgraded_archive = tmp_path / "upgraded.zip"
    release.build(source, upgraded_archive, tmp_path / "upgrade-stage")
    upgrade_package = tmp_path / "upgrade-package"
    _extract_archive(upgraded_archive, upgrade_package)

    installed = _run_script(
        upgrade_package,
        upgrade_package / ".agent" / "tools" / "vendor.py",
        "install",
        str(root),
        "--source",
        str(upgrade_package / ".agent"),
    )
    _assert_ok(installed)
    assert learning.read_bytes() == project_learning
    assert _integrate(root, "--check").returncode == 1

    _assert_ok(_integrate(root))
    _assert_ok(_integrate(root, "--check"))
    canonical = root / ".agent" / "skills" / "python-discipline" / "SKILL.md"
    assert canonical.read_bytes().endswith(marker)
    for host in (".claude", ".agents"):
        assert _native_skill(root, host).read_bytes() == canonical.read_bytes()


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


# --------------------------------------------------------- dependency closure


def test_the_adopter_manifest_closes_every_python_gate_branch() -> None:
    """The shipped source manifest exactly pins the declared verifier set."""
    assert release.requirement_problems(REPO_ROOT / "requirements.txt") == []


def test_a_floating_or_missing_gate_dependency_is_refused(tmp_path: Path) -> None:
    """One range cannot substitute for the absent exact verifier pin.

    @param tmp_path isolated malformed manifest
    """
    requirements = tmp_path / "requirements.txt"
    exact = sorted(release.REQUIRED_PYTHON_DISTRIBUTIONS - {"ruff"})
    requirements.write_text(
        "\n".join([*(f"{name}==1" for name in exact), "ruff>=0.16"]) + "\n",
        encoding="utf-8",
    )

    problems = release.requirement_problems(requirements)

    assert any("expected one exact name==version pin" in problem for problem in problems)
    assert "requirements.txt: missing required distribution ruff" in problems
