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
    Writes only pytest-owned release and adopter fixtures used to exercise packaging behavior.
    """
    # Establish the extraction root before resolving any archive member beneath it.
    root.mkdir(parents=True, exist_ok=True)
    # Keep the archive handle bounded to validation and extraction of this package.
    with zipfile.ZipFile(archive_path) as archive:
        # Read the central-directory records once so safety and extraction use the same census.
        infos = archive.infolist()
        # Classify every member name before any member bytes reach the filesystem.
        escaping = release.unsafe_members([
            # Each archive record contributes its declared portable member name.
            info.filename for info in infos
        ])
        assert escaping == []
        # Extract validated records in archive order to reproduce the packaged tree.
        for info in infos:
            # Resolve slash-separated archive names beneath the already-confined root.
            destination = root.joinpath(*info.filename.split("/"))
            # Directory records preserve intentionally empty package directories.
            if info.is_dir():
                # Materialize the empty directory and any required ancestry.
                destination.mkdir(parents=True, exist_ok=True)
                # Directory records carry no payload bytes.
                continue
            # Create parents for file records whose archives omit explicit directory entries.
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Write the validated member's exact packaged bytes.
            destination.write_bytes(archive.read(info))


def _run_script(root: Path, script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Invoke a packaged tool without importing from the source checkout.

    @param root working repository for the invocation
    @param script extracted package entry point
    @param arguments public CLI arguments
    @return captured process result
    """
    # Spawn a fresh interpreter rooted in the adopter so source-checkout imports cannot leak in.
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
    # Invoke the package's canonical integration entry point with the repository root explicit.
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
    # Resolve the host mirror beneath the adopter without assuming either host is primary.
    return root / host / "skills" / "python-discipline" / "SKILL.md"


def _run_packaged_checks(root: Path) -> subprocess.CompletedProcess[str]:
    """Run every shipped custom check without importing the source checkout.

    @param root migrated repository carrying an extracted package
    @return captured aggregate check result
    """
    # Build the child-process environment with the governed source root on its import path.
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / ".agent" / "enforce")
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
    Writes only pytest-owned release and adopter fixtures used to exercise packaging behavior.
    """
    # Parse the migrated project's own declaration before recomputing its review scope.
    declaration = discipline_project.parse(root / "pyproject.toml")
    # Preserve the observed item count used by the non-vacuity verdict.
    count, digest = scope_snapshot(declaration)
    path = root / "adversarial-review.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    scope = payload["scope"]
    assert isinstance(scope, dict)
    scope["file_count"] = count
    scope["digest"] = digest
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")


@pytest.fixture(scope="session")
def built_archives(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Build the same source twice through the real release pipeline.

    @param tmp_path_factory session-scoped temporary-directory provider
    @return two independently staged archives
    """
    # Allocate one session-owned directory shared by two independent staging runs.
    root = tmp_path_factory.mktemp("release-archives")
    # Name the first package output independently of its staging directory.
    first = root / "first.zip"
    # Name the second package output independently of its staging directory.
    second = root / "second.zip"
    first_count, _ = release.build(REPO_ROOT, first, root / "stage-first")
    second_count, _ = release.build(REPO_ROOT, second, root / "stage-second")
    assert first_count == second_count > 0
    return first, second


def _copy_release_source(destination: Path) -> None:
    """Copy only inputs a release build consumes into a mutable source tree.

    @param destination fresh source root for an upgrade archive

    @par Effects
    Writes only pytest-owned release and adopter fixtures used to exercise packaging behavior.
    """
    # Establish a mutable source root containing no unconsumed checkout artifacts.
    destination.mkdir(parents=True)
    # Apply the production vendor exclusions while copying directories into the release source.
    ignored = shutil.ignore_patterns(
        *vendor.SKIP_DIRS,
        "build",
        "dist",
        ".git",
    )
    # Copy every upstream directory the package contract declares.
    for name in vendor.UPSTREAM:
        shutil.copytree(REPO_ROOT / name, destination / name, ignore=ignored)
    # Copy every root file the package contract declares.
    for name in vendor.UPSTREAM_FILES:
        shutil.copy2(REPO_ROOT / name, destination / name)
    # Recreate the learning source family from distributable seeds only.
    learning = destination / "learning"
    # Keep mutable project ledgers out of this source tree.
    learning.mkdir()
    # Copy each seed artifact required to initialize a new adopter.
    for name in vendor.LEARNING_SEED:
        shutil.copy2(REPO_ROOT / "learning" / name, learning / name)
    # Recreate the packaging family containing the adopter-facing install guide.
    packaging = destination / "packaging"
    # Materialize the packaging directory before its selected file is copied.
    packaging.mkdir()
    shutil.copy2(
        REPO_ROOT / "packaging" / "INSTALL-DISCIPLINE.md",
        packaging / "INSTALL-DISCIPLINE.md",
    )
    # Select only the notes for the release identity being built.
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
    # Unpack the fixture's ordered pair as independently staged first and second packages.
    first, second = built_archives
    assert first.read_bytes() == second.read_bytes()
    # Inspect member metadata and manifest content from one byte-identical representative.
    with zipfile.ZipFile(first) as archive:
        # Retain archive records for path, timestamp, and permission assertions.
        infos = archive.infolist()
        # Each names element is one archive member path in central-directory order.
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
        Each element is one independently staged archive, ordered first then second build.

    @par Effects
    Writes only pytest-owned release and adopter fixtures used to exercise packaging behavior.
    """
    # Confine the simulated adopter and all installer effects to this test directory.
    root = tmp_path / "adopter"
    root.mkdir()
    # Each original key is a project-relative path and each value its exact pre-install bytes;
    # insertion order is preserved only to keep fixture setup and restoration deterministic.
    original = {
        "CLAUDE.md": b"# Project Claude\r\n",
        "AGENTS.md": b"# Project Codex\n",
        ".gitignore": b"project-output/\n",
    }
    # Seed each project-owned host or ignore file that installation must later restore.
    for name, content in original.items():
        # Resolve this declared project artifact beneath the simulated adopter root.
        path = root / name
        # Create host-specific parents only when the artifact requires them.
        path.parent.mkdir(parents=True, exist_ok=True)
        # Preserve deliberately mixed newline bytes for exact restoration assertions.
        path.write_bytes(content)
    # Each settings key is a host-owned section and each nested value its preserved content;
    # key order is deliberately irrelevant because comparison occurs after JSON decoding.
    settings = {
        "project": {"owner": "adopter"},
        "permissions": {"allow": ["Bash(project-check:*)"]},
    }
    settings_path = root / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    _extract_archive(built_archives[0], root)

    # Verify the extracted package against itself before allowing integration to consume it.
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

    # Treat the package-owned skill as the byte source for both host-native mirrors.
    canonical = root / ".agent" / "skills" / "python-discipline" / "SKILL.md"
    # Compare both independently installed host entries with the canonical package bytes.
    for host in (".claude", ".agents"):
        assert _native_skill(root, host).read_bytes() == canonical.read_bytes()

    _assert_ok(_integrate(root, "--remove"))
    # Verify removal restores every pre-install project artifact byte for byte.
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
    Writes only pytest-owned release and adopter fixtures used to exercise packaging behavior.
    """
    # Select the isolated adopter in which only Codex already owns the native skill path.
    root = tmp_path / "collision"
    _extract_archive(built_archives[0], root)
    # Resolve the Codex-native path that will be occupied before integration.
    codex = _native_skill(root, ".agents")
    # Create the otherwise absent Codex skill directory.
    codex.parent.mkdir(parents=True)
    # Seed unmistakably project-owned bytes that the package must not overwrite.
    codex.write_bytes(b"project-owned Codex skill\r\n")

    # Retain the partial integration outcome so collision status and independent Claude success align.
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
    Writes only pytest-owned release and adopter fixtures used to exercise packaging behavior.
    """
    # Select the existing adopter targeted by the simulated package upgrade.
    root = tmp_path / "upgrade-adopter"
    _extract_archive(built_archives[0], root)
    _assert_ok(_integrate(root))
    # Select a package-initialized file whose post-install bytes now belong to the adopter.
    learning = root / ".agent" / "learning" / "config.toml"
    # Append an adopter-owned marker that an upgrade must preserve.
    project_learning = learning.read_bytes() + b"\n# project-owned\n"
    # Persist project ownership before constructing the upgraded package.
    learning.write_bytes(project_learning)

    # Retain the immutable source representation consumed by subsequent analysis.
    source = tmp_path / "upgrade-source"
    _copy_release_source(source)
    # Select the canonical skill inside the mutable release source.
    source_skill = source / "skills" / "python-discipline" / "SKILL.md"
    # Use a unique trailing byte marker to prove upgraded canonical content propagated.
    marker = b"\nArchive upgrade marker.\n"
    # Change only a package-owned artifact in the simulated new release.
    source_skill.write_bytes(source_skill.read_bytes() + marker)
    # Name the upgraded archive independently of both source and staging tree.
    upgraded_archive = tmp_path / "upgraded.zip"
    release.build(source, upgraded_archive, tmp_path / "upgrade-stage")
    # Extract the upgraded package separately so its vendor entry point is exercised in-package.
    upgrade_package = tmp_path / "upgrade-package"
    _extract_archive(upgraded_archive, upgrade_package)

    # Upgrade through the newly extracted vendor tool, targeting the existing adopter.
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
    # Re-read the adopter's canonical skill after the package upgrade.
    canonical = root / ".agent" / "skills" / "python-discipline" / "SKILL.md"
    assert canonical.read_bytes().endswith(marker)
    # Confirm the next integration refreshes both host mirrors from upgraded canonical bytes.
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
    Writes only pytest-owned release and adopter fixtures used to exercise packaging behavior.
    """
    # Isolate one legacy repository for the parameterized application or component shape.
    root = tmp_path / f"legacy-{unit}"
    # Start from the conformant reference, then regress only v5-specific declarations.
    shutil.copytree(REPO_ROOT / "enforce" / "fixtures" / "reference", root)
    # Select the project declaration rewritten into the requested v4 shape.
    project_file = root / "pyproject.toml"
    # Retain its complete text so replacements preserve unrelated project configuration.
    project_text = project_file.read_text(encoding="utf-8")
    # Exercise both supported repository scopes through the same packaged migrator.
    project_text = project_text.replace('unit = "application"', f'unit = "{unit}"')
    # Reintroduce the parameterized v4 documentation-engine selection.
    project_text = project_text.replace('doc_engine = "doxygen"', f'doc_engine = "{legacy_engine}"')
    # Remove the v5 documentation-model declaration rather than leaving a contradictory hybrid.
    project_text = project_text.replace(
        'documentation_model = "documentation-model.json"\n', ""
    )
    # Persist the fully regressed project declaration with portable newlines.
    project_file.write_text(project_text, encoding="utf-8", newline="\n")
    # Remove the v5 model artifact so the fixture has the same absence migration must repair.
    (root / "documentation-model.json").unlink()
    # Select the architecture model whose repository-unit declaration must match pyproject.
    architecture_path = root / "architecture.json"
    # Decode the model without disturbing unrelated architectural declarations.
    architecture = json.loads(architecture_path.read_text(encoding="utf-8"))
    # Align the legacy model with this parameterized application or component case.
    architecture["unit"] = unit
    # Persist the regressed architecture model before overlaying the v5 package.
    architecture_path.write_text(
        json.dumps(architecture, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    _extract_archive(built_archives[0], root)

    # Prove the packaged project gate fails closed and points to the bounded migration path.
    refused = _run_script(
        root,
        root / ".agent" / "tools" / "project_gate.py",
        "--root",
        str(root),
    )
    assert refused.returncode == 1
    assert "DISC-PROJECT-021" in refused.stdout
    assert "migrate entity comments" in refused.stdout

    # Apply migration through the extracted package rather than the source checkout.
    migrated = _run_script(
        root,
        root / ".agent" / "tools" / "migrate_v5.py",
        "--root",
        str(root),
        "--apply",
    )
    _assert_ok(migrated)
    _refresh_fixture_review(root)

    # Run every packaged documentation check over the migrated source and tests.
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
    assert [f.pattern for f in found] == ["windows user path"]
    assert found[0].line == 1


def test_a_posix_home_path_is_found() -> None:
    """The same leak on the other platform."""
    # Preserve the optional pattern match that carries the reported analysis count.
    found = list(release.scan_text(
        "a.md", "run /home/someone/src/x.py\n", release.BLOCKING_PATTERNS))
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
    # Partition the same finding census into release blockers and human-review candidates.
    stops, reviewable = release.partition(findings)
    assert not stops
    assert [f.pattern for f in reviewable] == ["credential-shaped assignment"]


def test_the_building_account_is_derived_not_written_down() -> None:
    """The scan protects whoever runs it, not only its author's machine."""
    # Derive identity patterns from a representative build account instead of checked-in literals.
    patterns = release.environment_literals("jdoe", "BUILD-BOX", "D:/home/jdoe")
    assert [
        # Each derived pair contributes the diagnostic label visible to release operators.
        label for label, _ in patterns
    ] == [
        "build username", "build hostname", "build home directory"]
    # Preserve the optional pattern match that carries the reported analysis count.
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
    # Derive patterns with a deliberately common hostname that must be rejected as unusable.
    patterns = release.environment_literals("jdoe", "MAIN", "D:/home/jdoe")
    assert [
        # Each retained pair contributes one usable environment-identity signal.
        label for label, _ in patterns
    ] == ["build username", "build home directory"]
    # Retain the immutable source representation consumed by subsequent analysis.
    source = 'def main() -> int:\n    if __name__ == "__main__":\n        main()\n'
    assert list(release.scan_text("a.py", source, patterns)) == []


def test_dropping_an_unusable_identifier_is_reported_not_silent() -> None:
    """A scan running with fewer signals than usual must say so."""
    # Ask the companion diagnostic path which provided identities were excluded and why.
    dropped = release.unusable_identifiers("jdoe", "MAIN", "D:/home/jdoe")
    assert [
        # Each exclusion contributes its label and original value; the reason is asserted separately.
        (label, value) for label, value, _ in dropped
    ] == [("build hostname", "MAIN")]
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
    # Derive a bounded username pattern from a short but still usable identifier.
    patterns = release.environment_literals("ana", None, None)
    assert list(release.scan_text("a.md", "analysis of a banana\n", patterns)) == []
    # Preserve the optional pattern match that carries the reported analysis count.
    found = list(release.scan_text("a.md", "written by ana today\n", patterns))
    assert [f.pattern for f in found] == ["build username"]


def test_a_genuine_identifier_is_still_caught_after_bounding() -> None:
    """Precision must not have been bought by switching the guard off."""
    # Derive all three usable identity patterns for a positive leak witness.
    patterns = release.environment_literals("jdoe", "BUILD-BOX", "D:/home/jdoe")
    # Retain the immutable source representation consumed by subsequent analysis.
    text = "built under D:/home/jdoe by jdoe on build-box\n"
    assert {f.pattern for f in release.scan_text("a.md", text, patterns)} == {
        "build username", "build hostname", "build home directory"}


def test_an_excused_file_does_not_stop_the_build() -> None:
    """A fixture that proves a guard works must be allowed to contain its bait."""
    # Construct the exact bait shape and member covered by the narrow release exception.
    finding = release.Finding(".agent/tools/test_learn.py", 1, "aws access key", "AKIA...")
    # Partition one excused finding to prove it remains visible without blocking publication.
    stops, reviewable = release.partition([finding])
    assert not stops
    assert reviewable == [finding]
    assert release.excuse(finding.member, finding.pattern)


def test_an_excuse_covers_one_pattern_only() -> None:
    """The excuse is per shape, so a different leak in the same file still stops."""
    # Keep the excused member constant while changing only the detected leak pattern.
    finding = release.Finding(".agent/tools/test_learn.py", 1, "windows user path", "C:/Users/")
    # Partition the non-excused shape to prove exceptions do not apply at file granularity.
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
    Writes only pytest-owned release and adopter fixtures used to exercise packaging behavior.
    """
    # Create a generated bytecode-cache directory that must never enter a package.
    (tmp_path / ".agent" / "tools" / "__pycache__").mkdir(parents=True)
    # Add one cache payload so pruning proves removal of content, not only an empty directory.
    (tmp_path / ".agent" / "tools" / "__pycache__" / "nav.pyc").write_bytes(b"\x00")
    # Create the learning directory that legitimately survives pruning.
    (tmp_path / ".agent" / "learning").mkdir(parents=True)
    # Add mutable adopter-state data that a distributable archive must exclude.
    (tmp_path / ".agent" / "learning" / "learning.db").write_bytes(b"\x00")
    # Add one authored tool as the positive survivor control.
    (tmp_path / ".agent" / "tools" / "nav.py").write_text("x = 1\n", encoding="utf-8")

    # Prune the staged tree and retain its portable removal report.
    removed = release.prune(tmp_path)

    assert ".agent/tools/__pycache__/" in removed
    assert ".agent/learning/learning.db" in removed
    assert release.members_of(tmp_path) == [".agent/tools/nav.py"]


def test_an_empty_project_directory_is_recorded(tmp_path: Path) -> None:
    """`overrides/` holds nothing on day one and must still arrive.

    @param tmp_path the per-test directory

    @par Effects
    Writes only pytest-owned release and adopter fixtures used to exercise packaging behavior.
    """
    # Create the intentionally empty adopter-extension directory that the manifest must preserve.
    (tmp_path / ".agent" / "overrides").mkdir(parents=True)
    # Create a non-empty sibling directory to discriminate general emptiness from required emptiness.
    (tmp_path / ".agent" / "learning").mkdir()
    # Populate the sibling so it cannot appear in the empty-directory report.
    (tmp_path / ".agent" / "learning" / "schema.sql").write_text("x", encoding="utf-8")
    assert release.empty_dirs(tmp_path) == [".agent/overrides/"]


# ---------------------------------------------------------------- empty ledger


def _seed(agent: Path) -> None:
    """Create a correctly seeded, empty project half.

    @param agent the staged `.agent/` directory

    @par Effects
    Writes only pytest-owned release and adopter fixtures used to exercise packaging behavior.
    """
    # Establish the project-owned learning directory inside the staged agent tree.
    (agent / "learning").mkdir(parents=True)
    # Materialize every immutable seed declared by the release contract.
    for name in release.LEDGER_SEEDS:
        # Give each required seed benign nonempty bytes while keeping runtime ledgers absent.
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
    Writes only pytest-owned release and adopter fixtures used to exercise packaging behavior.
    """
    _seed(tmp_path / ".agent")
    # Add one project-specific ledger event to an otherwise distributable seed set.
    (tmp_path / ".agent" / "learning" / "ledger.jsonl").write_text("{}\n", encoding="utf-8")
    assert release.ledger_problems(tmp_path / ".agent") == [
        "learning/ledger.jsonl is not a seed and must not ship"
    ]


def test_a_missing_seed_is_refused(tmp_path: Path) -> None:
    """An adopter who cannot record a learning cannot follow the discipline.

    @param tmp_path the per-test directory

    @par Effects
    Writes only pytest-owned release and adopter fixtures used to exercise packaging behavior.
    """
    # Create the learning directory without any of the immutable installer seeds.
    (tmp_path / ".agent" / "learning").mkdir(parents=True)
    assert len(release.ledger_problems(tmp_path / ".agent")) == len(release.LEDGER_SEEDS)


def test_a_missing_learning_directory_is_refused(tmp_path: Path) -> None:
    """The project-owned half not existing at all is the louder failure.

    @param tmp_path the per-test directory

    @par Effects
    Writes only pytest-owned release and adopter fixtures used to exercise packaging behavior.
    """
    # Create an agent root with the entire project-owned learning subsystem absent.
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
    Writes only pytest-owned release and adopter fixtures used to exercise packaging behavior.
    """
    # Select the isolated manifest that will combine one missing exact pin with one floating range.
    requirements = tmp_path / "requirements.txt"
    # Pin every required distribution except ruff to keep the malformed dimensions precise.
    exact = sorted(release.REQUIRED_PYTHON_DISTRIBUTIONS - {"ruff"})
    # Persist exact dummy versions for controls and a range for the deliberately invalid ruff entry.
    requirements.write_text(
        "\n".join([
            # Each retained verifier distribution contributes one exact control pin.
            *(f"{name}==1" for name in exact),
            "ruff>=0.16",
        ]) + "\n",
        encoding="utf-8",
    )

    # Collect all closure diagnostics because the same malformed line should expose both defects.
    problems = release.requirement_problems(requirements)

    # Search each problem independently of emission order for the floating-pin refusal.
    assert any(
        "expected one exact name==version pin" in problem for problem in problems
    )
    assert "requirements.txt: missing required distribution ruff" in problems
