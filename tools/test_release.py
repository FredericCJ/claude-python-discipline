"""Proof-of-failure tests for the release build's gates.

Each gate exists to stop one thing reaching an adopter, so each is tested on
material that should stop it, not only on material that should pass. The suite
also builds and operates the delivered archive itself, because helper-level
coverage cannot prove that the package actually contains a working installer.

    pytest tools/test_release.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- packaged CLI boundary
import sys
import zipfile
from typing import TYPE_CHECKING

import pytest

import release
import vendor
from checks import project as discipline_project
from checks.adversarial_review import scope_snapshot
from discipline_core import REPO_ROOT

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from pathlib import Path


def _extract_archive(archive_path: Path, root: Path) -> None:
    """Extract a produced archive only after proving every name is confined.

    @param archive_path deterministic package to unpack
    @param root fresh repository or upgrade-source directory

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    root.mkdir(parents=True, exist_ok=True)
    # Bind archive to the current value used by the next extract archive decision.
    # Confine the acquired resource to this operation and release it on every exit.
    with zipfile.ZipFile(archive_path) as archive:
        # Compute infos using archive.infolist for later extract archive logic.
        infos = archive.infolist()
        # Select escaping, info as the current element from infos]) while extract archive
        # Details: preserves traversal order.
        escaping = release.unsafe_members([info.filename for info in infos])
        assert escaping == []
        # Select info as the current element from infos while extract archive preserves
        # Details: traversal order.
        # Advance extract archive through the current input element in declared order.
        for info in infos:
            # Resolve the repository-confined path used by this operation before filesystem
            # Details: access.
            destination = root.joinpath(*info.filename.split("/"))
            # Refuse the target when its declared source directory is absent.
            if info.is_dir():
                # Publish the externally visible effect after all required inputs are ready.
                destination.mkdir(parents=True, exist_ok=True)
                # Advance after the current candidate has been conclusively excluded.
                continue
            # Publish the externally visible effect after all required inputs are ready.
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Publish the externally visible effect after all required inputs are ready.
            destination.write_bytes(archive.read(info))


def _run_script(root: Path, script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Invoke a packaged tool without importing from the source checkout.

    @param root working repository for the invocation
    @param script extracted package entry point
    @param arguments public CLI arguments
    @return captured process result
    """
    # Return captured process result to the caller.
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
    # Return captured process result to the caller.
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
    # Return host-native skill entry point to the caller.
    return root / host / "skills" / "python-discipline" / "SKILL.md"


def _run_packaged_checks(root: Path) -> subprocess.CompletedProcess[str]:
    """Run every shipped custom check without importing the source checkout.

    @param root migrated repository carrying an extracted package
    @return captured aggregate check result
    """
    # Build the child-process environment with the governed source root on its import path.
    environment = os.environ.copy()
    # Update  run packaged checks state only after the required source facts are available.
    environment["PYTHONPATH"] = str(root / ".agent" / "enforce")
    # Return captured aggregate check result to the caller.
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed packaged module
        (
            sys.executable,
            "-m",
            "checks",
            "src",
            "tests",
            "--root",
            str(root),
            "--project",
            str(root / "pyproject.toml"),
        ),
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=60,
    )


def _refresh_fixture_review(root: Path) -> None:
    """Bind copied reference-review evidence to its synthetic migrated scope.

    @param root migrated synthetic repository

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Compute declaration using discipline project.parse for later refresh fixture review logic.
    declaration = discipline_project.parse(root / "pyproject.toml")
    # Preserve the observed item count used by the non-vacuity verdict.
    count, digest = scope_snapshot(declaration)
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = root / "adversarial-review.json"
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    payload = json.loads(path.read_text(encoding="utf-8"))
    # Compute scope using payload["scope"] for later refresh fixture review logic.
    scope = payload["scope"]
    assert isinstance(scope, dict)
    # Update  refresh fixture review state only after the required source facts are available.
    scope["file_count"] = count
    # Update  refresh fixture review state only after the required source facts are available.
    scope["digest"] = digest
    # Publish the externally visible effect after all required inputs are ready.
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")


@pytest.fixture(scope="session")
def built_archives(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Build the same source twice through the real release pipeline.

    @param tmp_path_factory session-scoped temporary-directory provider
    @return two independently staged archives
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = tmp_path_factory.mktemp("release-archives")
    # Compute first using root / "first.zip" for later built archives logic.
    first = root / "first.zip"
    # Compute second using root / "second.zip" for later built archives logic.
    second = root / "second.zip"
    # Compute first count using release.build for later built archives logic.
    first_count, _ = release.build(REPO_ROOT, first, root / "stage-first")
    # Compute second count using release.build for later built archives logic.
    second_count, _ = release.build(REPO_ROOT, second, root / "stage-second")
    assert first_count == second_count > 0
    # Return two independently staged archives to the caller.
    return first, second


def _copy_release_source(destination: Path) -> None:
    """Copy only inputs a release build consumes into a mutable source tree.

    @param destination fresh source root for an upgrade archive

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    destination.mkdir(parents=True)
    # Compute ignored using shutil.ignore patterns for later copy release source logic.
    ignored = shutil.ignore_patterns(
        *vendor.SKIP_DIRS,
        "build",
        "dist",
        ".git",
    )
    # Normalize the current repository path to its portable baseline key spelling.
    # Advance copy release source through the current input element in declared order.
    for name in vendor.UPSTREAM:
        shutil.copytree(REPO_ROOT / name, destination / name, ignore=ignored)
    # Normalize the current repository path to its portable baseline key spelling.
    # Advance copy release source through the current input element in declared order.
    for name in vendor.UPSTREAM_FILES:
        shutil.copy2(REPO_ROOT / name, destination / name)
    # Compute learning using destination / "learning" for later copy release source logic.
    learning = destination / "learning"
    # Publish the externally visible effect after all required inputs are ready.
    learning.mkdir()
    # Normalize the current repository path to its portable baseline key spelling.
    # Advance copy release source through the current input element in declared order.
    for name in vendor.LEARNING_SEED:
        shutil.copy2(REPO_ROOT / "learning" / name, learning / name)
    # Compute packaging using destination / "packaging" for later copy release source logic.
    packaging = destination / "packaging"
    # Publish the externally visible effect after all required inputs are ready.
    packaging.mkdir()
    shutil.copy2(
        REPO_ROOT / "packaging" / "INSTALL-DISCIPLINE.md",
        packaging / "INSTALL-DISCIPLINE.md",
    )
    # Compute notes using f"RELEASE-NOTES-{vendor.RELEASE}.md" for later copy release source
    # Details: logic.
    notes = f"RELEASE-NOTES-{vendor.RELEASE}.md"
    shutil.copy2(REPO_ROOT / notes, destination / notes)


# ----------------------------------------------------------- archive lifecycle


@pytest.mark.timeout(180)
def test_two_clean_archive_builds_are_byte_identical(
    built_archives: tuple[Path, Path],
) -> None:
    """Independent staging cannot move bytes, members, times, or permissions.

    @param built_archives independently staged packages
        Each element is one independently staged archive, ordered first then second build.
    """
    # Unpack first, second using built_archives for later test two clean archive builds are byte
    # Details: identical logic.
    first, second = built_archives
    assert first.read_bytes() == second.read_bytes()
    # Bind archive to the current value used by the next test two clean archive builds are byte
    # Details: identical decision.
    # Confine the acquired resource to this operation and release it on every exit.
    with zipfile.ZipFile(first) as archive:
        # Compute infos using archive.infolist for later test two clean archive builds are byte
        # Details: identical logic.
        infos = archive.infolist()
        # Each names element is one archive member path in central-directory order.
        names = [info.filename for info in infos]
        assert release.unsafe_members(names) == []
        assert set(release.REQUIRED_MEMBERS) <= set(names)
        # Select info as the current element from infos) while test two clean archive builds are
        # Details: byte identical preserves traversal order.
        assert all(info.date_time == release.ZIP_EPOCH for info in infos)
        # Hold the decoded mapping elements whose keys identify fields and values carry their
        # Details: content; key order is deliberately unused.
        manifest = json.loads(archive.read(".agent/MANIFEST.json"))
        # Compute canonical using archive.read for later test two clean archive builds are byte
        # Details: identical logic.
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
        Each element is one independently staged archive, ordered first then second build.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = tmp_path / "adopter"
    # Publish the externally visible effect after all required inputs are ready.
    root.mkdir()
    # Treat original as mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    original = {
        "CLAUDE.md": b"# Project Claude\r\n",
        "AGENTS.md": b"# Project Codex\n",
        ".gitignore": b"project-output/\n",
    }
    # Retain the immutable source representation consumed by subsequent analysis.
    # Advance test archive installs checks and removes both host entries through the current
    # Details: input element in declared order.
    for name, content in original.items():
        # Resolve the repository-confined path used by this operation before filesystem access.
        path = root / name
        # Publish the externally visible effect after all required inputs are ready.
        path.parent.mkdir(parents=True, exist_ok=True)
        # Publish the externally visible effect after all required inputs are ready.
        path.write_bytes(content)
    # Treat settings as mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    settings = {
        "project": {"owner": "adopter"},
        "permissions": {"allow": ["Bash(project-check:*)"]},
    }
    # Compute settings path using root / ".claude" / "settings.json" for later test archive
    # Details: installs checks and removes both host entries logic.
    settings_path = root / ".claude" / "settings.json"
    # Publish the externally visible effect after all required inputs are ready.
    settings_path.parent.mkdir(parents=True)
    # Publish the externally visible effect after all required inputs are ready.
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    _extract_archive(built_archives[0], root)

    # Compute vendored check using  run script for later test archive installs checks and
    # Details: removes both host entries logic.
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

    # Compute canonical using root / ".agent" / "skills" / "python-discipline" / "SKILL.md for
    # Details: later test archive installs checks and removes both host entries logic.
    canonical = root / ".agent" / "skills" / "python-discipline" / "SKILL.md"
    # Select host as the current element from (".claude", ".agents") while test archive installs
    # Details: checks and removes both host entries preserves traversal order.
    # Advance test archive installs checks and removes both host entries through the current
    # Details: input element in declared order.
    for host in (".claude", ".agents"):
        assert _native_skill(root, host).read_bytes() == canonical.read_bytes()

    _assert_ok(_integrate(root, "--remove"))
    # Retain the immutable source representation consumed by subsequent analysis.
    # Advance test archive installs checks and removes both host entries through the current
    # Details: input element in declared order.
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
        Each element is one independently staged archive, ordered first then second build.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = tmp_path / "collision"
    _extract_archive(built_archives[0], root)
    # Compute codex using  native skill for later test archive refuses a codex collision without
    # Details: blocking claude logic.
    codex = _native_skill(root, ".agents")
    # Publish the externally visible effect after all required inputs are ready.
    codex.parent.mkdir(parents=True)
    # Publish the externally visible effect after all required inputs are ready.
    codex.write_bytes(b"project-owned Codex skill\r\n")

    # Preserve the external command representation and its observed completion outcome.
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
        Each element is one independently staged archive, ordered first then second build.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = tmp_path / "upgrade-adopter"
    _extract_archive(built_archives[0], root)
    _assert_ok(_integrate(root))
    # Compute learning using root / ".agent" / "learning" / "config.toml" for later test archive
    # Details: upgrade preserves project state and updates both hosts logic.
    learning = root / ".agent" / "learning" / "config.toml"
    # Compute project learning using learning.read bytes for later test archive upgrade
    # Details: preserves project state and updates both hosts logic.
    project_learning = learning.read_bytes() + b"\n# project-owned\n"
    # Publish the externally visible effect after all required inputs are ready.
    learning.write_bytes(project_learning)

    # Retain the immutable source representation consumed by subsequent analysis.
    source = tmp_path / "upgrade-source"
    _copy_release_source(source)
    # Compute source skill using source / "skills" / "python-discipline" / "SKILL.md" for later
    # Details: test archive upgrade preserves project state and updates both hosts logic.
    source_skill = source / "skills" / "python-discipline" / "SKILL.md"
    # Compute marker using b"\nArchive upgrade marker.\n" for later test archive upgrade
    # Details: preserves project state and updates both hosts logic.
    marker = b"\nArchive upgrade marker.\n"
    # Publish the externally visible effect after all required inputs are ready.
    source_skill.write_bytes(source_skill.read_bytes() + marker)
    # Compute upgraded archive using tmp_path / "upgraded.zip" for later test archive upgrade
    # Details: preserves project state and updates both hosts logic.
    upgraded_archive = tmp_path / "upgraded.zip"
    release.build(source, upgraded_archive, tmp_path / "upgrade-stage")
    # Compute upgrade package using tmp_path / "upgrade-package" for later test archive upgrade
    # Details: preserves project state and updates both hosts logic.
    upgrade_package = tmp_path / "upgrade-package"
    _extract_archive(upgraded_archive, upgrade_package)

    # Compute installed using  run script for later test archive upgrade preserves project state
    # Details: and updates both hosts logic.
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
    # Compute canonical using root / ".agent" / "skills" / "python-discipline" / "SKILL.md for
    # Details: later test archive upgrade preserves project state and updates both hosts logic.
    canonical = root / ".agent" / "skills" / "python-discipline" / "SKILL.md"
    assert canonical.read_bytes().endswith(marker)
    # Select host as the current element from (".claude", ".agents") while test archive upgrade
    # Details: preserves project state and updates both hosts preserves traversal order.
    # Advance test archive upgrade preserves project state and updates both hosts through the
    # Details: current input element in declared order.
    for host in (".claude", ".agents"):
        assert _native_skill(root, host).read_bytes() == canonical.read_bytes()


@pytest.mark.parametrize(
    ("unit", "legacy_engine"),
    [("application", "none"), ("component", "sphinx")],
)
@pytest.mark.timeout(180)
def test_archive_rejects_then_migrates_both_v4_repository_shapes(
    tmp_path: Path,
    built_archives: tuple[Path, Path],
    unit: str,
    legacy_engine: str,
) -> None:
    """The delivered v5 package gives a v4 project one bounded path to green.

    @param tmp_path fresh synthetic adopter parent
    @param built_archives independently staged packages
        Each element is one independently staged archive, ordered first then second build.
    @param unit application or independently developed single component
    @param legacy_engine former v4 structured-documentation selection

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = tmp_path / f"legacy-{unit}"
    shutil.copytree(REPO_ROOT / "enforce" / "fixtures" / "reference", root)
    # Resolve the repository-confined path used by this operation before filesystem access.
    project_file = root / "pyproject.toml"
    # Compute project text using project file.read text for later test archive rejects then
    # Details: migrates both v4 repository shapes logic.
    project_text = project_file.read_text(encoding="utf-8")
    # Compute project text using project text.replace for later test archive rejects then
    # Details: migrates both v4 repository shapes logic.
    project_text = project_text.replace('unit = "application"', f'unit = "{unit}"')
    # Compute project text using project text.replace for later test archive rejects then
    # Details: migrates both v4 repository shapes logic.
    project_text = project_text.replace('doc_engine = "doxygen"', f'doc_engine = "{legacy_engine}"')
    # Compute project text using project text.replace for later test archive rejects then
    # Details: migrates both v4 repository shapes logic.
    project_text = project_text.replace(
        'documentation_model = "documentation-model.json"\n', ""
    )
    # Publish the externally visible effect after all required inputs are ready.
    project_file.write_text(project_text, encoding="utf-8", newline="\n")
    # Publish the externally visible effect after all required inputs are ready.
    (root / "documentation-model.json").unlink()
    # Compute architecture path using root / "architecture.json" for later test archive rejects
    # Details: then migrates both v4 repository shapes logic.
    architecture_path = root / "architecture.json"
    # Compute architecture using json.loads for later test archive rejects then migrates both v4
    # Details: repository shapes logic.
    architecture = json.loads(architecture_path.read_text(encoding="utf-8"))
    # Update test archive rejects then migrates both v4 repository shapes state only after the
    # Details: required source facts are available.
    architecture["unit"] = unit
    # Publish the externally visible effect after all required inputs are ready.
    architecture_path.write_text(
        json.dumps(architecture, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    _extract_archive(built_archives[0], root)

    # Compute refused using  run script for later test archive rejects then migrates both v4
    # Details: repository shapes logic.
    refused = _run_script(
        root,
        root / ".agent" / "tools" / "project_gate.py",
        "--root",
        str(root),
    )
    assert refused.returncode == 1
    assert "DISC-PROJECT-021" in refused.stdout
    assert "migrate entity comments" in refused.stdout

    # Compute migrated using  run script for later test archive rejects then migrates both v4
    # Details: repository shapes logic.
    migrated = _run_script(
        root,
        root / ".agent" / "tools" / "migrate_v5.py",
        "--root",
        str(root),
        "--apply",
    )
    _assert_ok(migrated)
    _refresh_fixture_review(root)

    # Compute checked using  run packaged checks for later test archive rejects then migrates
    # Details: both v4 repository shapes logic.
    checked = _run_packaged_checks(root)
    _assert_ok(checked)
    assert "0 finding(s)" in checked.stdout
    assert (root / "Doxyfile").is_file()
    assert (root / "documentation-model.json").is_file()


# ------------------------------------------------------------------- leak scan


def test_an_absolute_windows_path_is_found() -> None:
    """A path rooted in a user's home names the machine it was written on."""
    # Retain the immutable source representation consumed by subsequent analysis.
    text = "see C:/Users/someone/Documents/repo/tools/nav.py for the navigator\n"
    # Preserve the optional pattern match that carries the reported analysis count.
    found = list(release.scan_text("a.md", text, release.BLOCKING_PATTERNS))
    # Select f as the current element from found] == ["windows user path"] while test an
    # Details: absolute windows path is found preserves traversal order.
    assert [f.pattern for f in found] == ["windows user path"]
    assert found[0].line == 1


def test_a_posix_home_path_is_found() -> None:
    """The same leak on the other platform."""
    # Preserve the optional pattern match that carries the reported analysis count.
    found = list(release.scan_text(
        "a.md", "run /home/someone/src/x.py\n", release.BLOCKING_PATTERNS))
    # Select f as the current element from found] == ["posix home path"] while test a posix home
    # Details: path is found preserves traversal order.
    assert [f.pattern for f in found] == ["posix home path"]


def test_a_relative_path_is_not_mistaken_for_a_home_path() -> None:
    """`tools/home/x` and a URL path must not fire the home-directory pattern."""
    # Retain the immutable source representation consumed by subsequent analysis.
    text = "tools/home/x.py and https://example.com/users/api/v1\n"
    assert not list(release.scan_text("a.md", text, release.BLOCKING_PATTERNS))


def test_a_credential_prefix_is_found() -> None:
    """Published token formats are recognisable on sight, so recognise them."""
    # Retain the immutable source representation consumed by subsequent analysis.
    text = "token = 'ghp_" + "a" * 30 + "'\n"
    # Select f as the current element from release.scan_text( while test a credential prefix is
    # Details: found preserves traversal order.
    assert [f.pattern for f in release.scan_text(
        "a.py", text, release.BLOCKING_PATTERNS)] == ["github token"]


def test_ordinary_corpus_prose_is_clean() -> None:
    """The scan must not fire on the discipline's own vocabulary."""
    # Retain the immutable source representation consumed by subsequent analysis.
    text = "tokens: 1876\nThe secret is that there is no secret.\n`.agent/tools/nav.py`\n"
    assert not list(release.scan_text("a.md", text, release.BLOCKING_PATTERNS))


def test_a_credential_assignment_is_reviewable_not_blocking() -> None:
    """The rules about redaction have to show what redaction is for."""
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = list(release.scan_text(
        "a.py", 'password = "hunter2000"\n',
        (*release.BLOCKING_PATTERNS, *release.REVIEW_PATTERNS)))
    # Unpack reviewable, stops using release.partition for later test a credential assignment is
    # Details: reviewable not blocking logic.
    stops, reviewable = release.partition(findings)
    assert not stops
    # Select f as the current element from reviewable] == ["credential-shaped assignment"] while
    # Details: test a credential assignment is reviewable not blocking preserves traversal order.
    assert [f.pattern for f in reviewable] == ["credential-shaped assignment"]


def test_the_building_account_is_derived_not_written_down() -> None:
    """The scan protects whoever runs it, not only its author's machine."""
    # Compute patterns using release.environment literals for later test the building account is
    # Details: derived not written down logic.
    patterns = release.environment_literals("jdoe", "BUILD-BOX", "D:/home/jdoe")
    # Select label as the current element from patterns] == [ while test the building account is
    # Details: derived not written down preserves traversal order.
    assert [label for label, _ in patterns] == [
        "build username", "build hostname", "build home directory"]
    # Preserve the optional pattern match that carries the reported analysis count.
    found = list(release.scan_text("a.md", "written on build-box\n", patterns))
    # Select f as the current element from found] == ["build hostname"] while test the building
    # Details: account is derived not written down preserves traversal order.
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
    # Compute patterns using release.environment literals for later test a host named after a
    # Details: common word can still build logic.
    patterns = release.environment_literals("jdoe", "MAIN", "D:/home/jdoe")
    # Select label as the current element from patterns] == ["build username", "build home
    # Details: directory"] while test a host named after a common word can still build preserves
    # Details: traversal order.
    assert [label for label, _ in patterns] == ["build username", "build home directory"]
    # Retain the immutable source representation consumed by subsequent analysis.
    source = 'def main() -> int:\n    if __name__ == "__main__":\n        main()\n'
    assert list(release.scan_text("a.py", source, patterns)) == []


def test_dropping_an_unusable_identifier_is_reported_not_silent() -> None:
    """A scan running with fewer signals than usual must say so."""
    # Compute dropped using release.unusable identifiers for later test dropping an unusable
    # Details: identifier is reported not silent logic.
    dropped = release.unusable_identifiers("jdoe", "MAIN", "D:/home/jdoe")
    # Treat the current label, value as the candidate element consumed by the enclosing
    # Details: transformation.
    assert [(label, value) for label, value, _ in dropped] == [("build hostname", "MAIN")]
    assert "too common" in dropped[0][2]


def test_the_container_home_is_public_package_configuration() -> None:
    """The shipped disposable HOME must not be rejected as its builder's identity."""
    # Derive leak patterns from the exact environment identity exposed inside the image.
    patterns = release.environment_literals(
        "builder", "BUILD-BOX", release.PACKAGE_RUNTIME_HOME,
    )
    # Keep account and host signals while excluding only the fixed package-owned home.
    assert [label for label, _ in patterns] == ["build username", "build hostname"]
    # Make the reduced scan visible in the same structured diagnostic channel as common values.
    dropped = release.unusable_identifiers(
        "builder", "BUILD-BOX", release.PACKAGE_RUNTIME_HOME,
    )
    assert [(label, value) for label, value, _ in dropped] == [
        ("build home directory", release.PACKAGE_RUNTIME_HOME),
    ]
    assert "package-owned" in dropped[0][2]
    # Preserve sensitivity to nearby temporary paths that the package did not author.
    nearby_home = release.PACKAGE_RUNTIME_HOME.replace("python-discipline", "private-builder")
    assert [
        label
        for label, _ in release.environment_literals(
            None, None, nearby_home,
        )
    ] == ["build home directory"]


def test_an_absent_identifier_is_not_reported_as_dropped() -> None:
    """A machine that sets no USER is unremarkable; saying so is noise."""
    assert release.unusable_identifiers(None, "BUILD-BOX", "   ") == ()


def test_an_identifier_inside_a_longer_word_is_not_a_leak() -> None:
    """A short login name must not match every word that contains it."""
    # Compute patterns using release.environment literals for later test an identifier inside a
    # Details: longer word is not a leak logic.
    patterns = release.environment_literals("ana", None, None)
    assert list(release.scan_text("a.md", "analysis of a banana\n", patterns)) == []
    # Preserve the optional pattern match that carries the reported analysis count.
    found = list(release.scan_text("a.md", "written by ana today\n", patterns))
    # Select f as the current element from found] == ["build username"] while test an identifier
    # Details: inside a longer word is not a leak preserves traversal order.
    assert [f.pattern for f in found] == ["build username"]


def test_a_genuine_identifier_is_still_caught_after_bounding() -> None:
    """Precision must not have been bought by switching the guard off."""
    # Compute patterns using release.environment literals for later test a genuine identifier is
    # Details: still caught after bounding logic.
    patterns = release.environment_literals("jdoe", "BUILD-BOX", "D:/home/jdoe")
    # Retain the immutable source representation consumed by subsequent analysis.
    text = "built under D:/home/jdoe by jdoe on build-box\n"
    # Select f as the current element from release.scan_text("a.md", text, patterns)} == { while
    # Details: test a genuine identifier is still caught after bounding preserves traversal order.
    assert {f.pattern for f in release.scan_text("a.md", text, patterns)} == {
        "build username", "build hostname", "build home directory"}


def test_an_excused_file_does_not_stop_the_build() -> None:
    """A fixture that proves a guard works must be allowed to contain its bait."""
    # Compute finding using release.Finding for later test an excused file does not stop the
    # Details: build logic.
    finding = release.Finding(".agent/tools/test_learn.py", 1, "aws access key", "AKIA...")
    # Unpack reviewable, stops using release.partition for later test an excused file does not
    # Details: stop the build logic.
    stops, reviewable = release.partition([finding])
    assert not stops
    assert reviewable == [finding]
    assert release.excuse(finding.member, finding.pattern)


def test_an_excuse_covers_one_pattern_only() -> None:
    """The excuse is per shape, so a different leak in the same file still stops."""
    # Compute finding using release.Finding for later test an excuse covers one pattern only
    # Details: logic.
    finding = release.Finding(".agent/tools/test_learn.py", 1, "windows user path", "C:/Users/")
    # Compute stops using release.partition for later test an excuse covers one pattern only
    # Details: logic.
    stops, _ = release.partition([finding])
    assert stops == [finding]


def test_an_excuse_does_not_cover_a_different_file() -> None:
    """Matching on the tail must not match a file that merely ends similarly."""
    assert release.excuse(".agent/tools/other_test_learn.py", "aws access key") is None


# --------------------------------------------------------------- member safety


def test_escaping_member_paths_are_rejected() -> None:
    """An archive member may not choose where it lands."""
    # Each names element is one malicious member path in assertion order.
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

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    (tmp_path / ".agent" / "tools" / "__pycache__").mkdir(parents=True)
    # Publish the externally visible effect after all required inputs are ready.
    (tmp_path / ".agent" / "tools" / "__pycache__" / "nav.pyc").write_bytes(b"\x00")
    # Publish the externally visible effect after all required inputs are ready.
    (tmp_path / ".agent" / "learning").mkdir(parents=True)
    # Publish the externally visible effect after all required inputs are ready.
    (tmp_path / ".agent" / "learning" / "learning.db").write_bytes(b"\x00")
    # Publish the externally visible effect after all required inputs are ready.
    (tmp_path / ".agent" / "tools" / "nav.py").write_text("x = 1\n", encoding="utf-8")

    # Compute removed using release.prune for later test caches and databases are pruned logic.
    removed = release.prune(tmp_path)

    assert ".agent/tools/__pycache__/" in removed
    assert ".agent/learning/learning.db" in removed
    assert release.members_of(tmp_path) == [".agent/tools/nav.py"]


def test_an_empty_project_directory_is_recorded(tmp_path: Path) -> None:
    """`overrides/` holds nothing on day one and must still arrive.

    @param tmp_path the per-test directory

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    (tmp_path / ".agent" / "overrides").mkdir(parents=True)
    # Publish the externally visible effect after all required inputs are ready.
    (tmp_path / ".agent" / "learning").mkdir()
    # Publish the externally visible effect after all required inputs are ready.
    (tmp_path / ".agent" / "learning" / "schema.sql").write_text("x", encoding="utf-8")
    assert release.empty_dirs(tmp_path) == [".agent/overrides/"]


# ---------------------------------------------------------------- empty ledger


def _seed(agent: Path) -> None:
    """Create a correctly seeded, empty project half.

    @param agent the staged `.agent/` directory

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    (agent / "learning").mkdir(parents=True)
    # Normalize the current repository path to its portable baseline key spelling.
    # Advance seed through the current input element in declared order.
    for name in release.LEDGER_SEEDS:
        # Publish the externally visible effect after all required inputs are ready.
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

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    _seed(tmp_path / ".agent")
    # Publish the externally visible effect after all required inputs are ready.
    (tmp_path / ".agent" / "learning" / "ledger.jsonl").write_text("{}\n", encoding="utf-8")
    assert release.ledger_problems(tmp_path / ".agent") == [
        "learning/ledger.jsonl is not a seed and must not ship"
    ]


def test_a_missing_seed_is_refused(tmp_path: Path) -> None:
    """An adopter who cannot record a learning cannot follow the discipline.

    @param tmp_path the per-test directory

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    (tmp_path / ".agent" / "learning").mkdir(parents=True)
    assert len(release.ledger_problems(tmp_path / ".agent")) == len(release.LEDGER_SEEDS)


def test_a_missing_learning_directory_is_refused(tmp_path: Path) -> None:
    """The project-owned half not existing at all is the louder failure.

    @param tmp_path the per-test directory

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
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

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Compute requirements using tmp_path / "requirements.txt" for later test a floating or
    # Details: missing gate dependency is refused logic.
    requirements = tmp_path / "requirements.txt"
    # Compute exact using sorted for later test a floating or missing gate dependency is refused
    # Details: logic.
    exact = sorted(release.REQUIRED_PYTHON_DISTRIBUTIONS - {"ruff"})
    # Normalize the current repository path to its portable baseline key spelling.
    # Publish the externally visible effect after all required inputs are ready.
    requirements.write_text(
        "\n".join([*(f"{name}==1" for name in exact), "ruff>=0.16"]) + "\n",
        encoding="utf-8",
    )

    # Compute problems using release.requirement problems for later test a floating or missing
    # Details: gate dependency is refused logic.
    problems = release.requirement_problems(requirements)

    # Select problem as the current element from problems) while test a floating or missing gate
    # Details: dependency is refused preserves traversal order.
    assert any("expected one exact name==version pin" in problem for problem in problems)
    assert "requirements.txt: missing required distribution ruff" in problems
