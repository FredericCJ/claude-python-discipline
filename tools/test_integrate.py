"""Tests for announcing a vendored discipline to a repository's configuration.

Three properties carry the weight. **Preservation**: a repository that already
has a configuration must get the block and nothing else disturbed, byte for
byte -- which is asserted on bytes, because the defect this property exists to
catch is invisible to any assertion made on decoded text. **Provenance**: what
the integrator takes back out on `--remove` is what the install record says it
put in, never everything that merely looks like it. **Idempotence**: running
twice must leave the same file as running once, or re-vendoring would
accumulate blocks.

    pytest tools/test_integrate.py
"""

from __future__ import annotations

import json
import subprocess  # ruff: ignore[suspicious-subprocess-import]
from pathlib import Path

import pytest

import integrate
import vendor
from decides import decides
from integrate import Kind

## A configuration a project already had before the discipline arrived, in the
## line endings a Unix checkout would have. Stored as bytes and written as bytes
## so no layer between the fixture and the disk can normalise it.
EXISTING_LF: bytes = (
    b"# Acme Service\n\n## Running it\n\n    make serve\n\n"
    b"## Conventions\n\nBranch names are `feat/<ticket>`. Ask before touching `legacy/`.\n"
)

## The same configuration as a Windows checkout would have it.
EXISTING_CRLF: bytes = EXISTING_LF.replace(b"\n", b"\r\n")

## The text form, for the assertions that are genuinely about text.
EXISTING_CLAUDE: str = EXISTING_LF.decode()

## A permission entry a project could plausibly have had before the discipline
## arrived, and which the discipline would also add. Value alone cannot tell the
## two apart, which is the whole reason the install record exists.
SHARED_PERMISSION: str = "Bash(pytest:*)"

## A small but valid vendored skill used to exercise both native discovery roots.
SHARED_SKILL: str = """---
name: python-discipline
description: Shared fixture discipline.
---

Read `.agent/discipline/KERNEL.md`.
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with a vendored discipline and a manifest.

    @param tmp_path the per-test directory
    @return the repository root

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    (tmp_path / ".agent" / "discipline").mkdir(parents=True)
    # Publish the externally visible effect after all required inputs are ready.
    (tmp_path / ".agent" / "MANIFEST.json").write_text(
        json.dumps({"version": "abc123"}), encoding="utf-8"
    )
    # Return the repository root to the caller.
    return tmp_path


def run(root: Path, *args: str) -> int:
    """Invoke the integrator against a repository.

    @param root the repository root
    @param args extra command-line arguments
    @return the exit status
    """
    # Return the exit status to the caller.
    return integrate.main(["--root", str(root), *args])


def kinds(root: Path, **kwargs: object) -> dict[str, Kind]:
    """The planned action kind for each target file.

    @param root the repository root
    @param kwargs forwarded to `build_plan`
    @return file name mapped to planned action kind
    """
    # Compute plan using integrate.build plan for later kinds logic.
    plan = integrate.build_plan(root, ".agent", **kwargs)  # type: ignore[arg-type]
    # Select a as the current element from plan.actions} while kinds preserves traversal order.
    # Return file name mapped to planned action kind to the caller.
    return {a.path.name: a.kind for a in plan.actions}


def allow_list(root: Path) -> list[str]:
    """Read the permissions a repository currently grants.

    @param root the repository root
    @return the entries, in file order
    """
    # Retain the immutable source representation consumed by subsequent analysis.
    text = (root / ".claude" / "settings.json").read_text(encoding="utf-8")
    # Compute allowed using json.loads for later allow list logic.
    allowed = json.loads(text)["permissions"]["allow"]
    # Treat the current entry as the candidate element consumed by the enclosing transformation.
    # Return the entries, in file order to the caller.
    return [str(entry) for entry in allowed]


def write_settings(root: Path, allow: list[str]) -> Path:
    """Give a repository a settings file it owned before the discipline arrived.

    @param root the repository root
    @param allow the entries the project already allows
        Each element is one Claude permission expression in existing file order.
    @return the settings file

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = root / ".claude" / "settings.json"
    # Publish the externally visible effect after all required inputs are ready.
    path.parent.mkdir(parents=True, exist_ok=True)
    # Publish the externally visible effect after all required inputs are ready.
    path.write_text(json.dumps({"permissions": {"allow": allow}}, indent=2), encoding="utf-8")
    # Return the settings file to the caller.
    return path


def write_vendored_skill(root: Path, text: str = SHARED_SKILL) -> Path:
    """Seed the one skill source an installed v3.3 bundle carries.

    @param root the repository root
    @param text exact skill contents
    @return the vendored source path

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = root / ".agent" / "skills" / "python-discipline" / "SKILL.md"
    # Publish the externally visible effect after all required inputs are ready.
    path.parent.mkdir(parents=True, exist_ok=True)
    # Publish the externally visible effect after all required inputs are ready.
    path.write_text(text, encoding="utf-8", newline="")
    # Return the vendored source path to the caller.
    return path


def native_skill(root: Path, host: str) -> Path:
    """Resolve one host's repository-local skill entry point.

    @param root the repository root
    @param host either `.claude` or `.agents`
    @return that host's SKILL.md path
    """
    # Return that host's SKILL.md path to the caller.
    return root / host / "skills" / "python-discipline" / "SKILL.md"


# ------------------------------------------------------------------ greenfield


def test_greenfield_creates_both_markdown_targets(repo: Path) -> None:
    """Scenario 1: nothing exists, so a minimal file is created for each.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    assert kinds(repo) == {
        "CLAUDE.md": Kind.CREATE,
        "AGENTS.md": Kind.CREATE,
        "settings.json": Kind.CREATE,
        ".gitignore": Kind.CREATE,
        integrate.RECORD_NAME: Kind.CREATE,
    }
    run(repo)
    # Normalize the current repository path to its portable baseline key spelling.
    # Advance test greenfield creates both markdown targets through the current input element in
    # Details: declared order.
    for name in ("CLAUDE.md", "AGENTS.md"):
        # Retain the immutable source representation consumed by subsequent analysis.
        text = (repo / name).read_text(encoding="utf-8")
        assert integrate.BEGIN in text
        assert integrate.END in text
        assert "KERNEL.md" in text


def test_a_created_file_stays_minimal(repo: Path) -> None:
    """The rest of the project's configuration is the project's to write.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    run(repo)
    # Retain the immutable source representation consumed by subsequent analysis.
    text = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    # Compute outside using integrate.BLOCK RE.sub for later test a created file stays minimal
    # Details: logic.
    outside = integrate.BLOCK_RE.sub("", text).strip()
    assert outside == f"# {repo.name}"


def test_permissions_are_created_with_the_narrow_set(repo: Path) -> None:
    """Only the discipline's own read-or-verify invocations are allowed.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    run(repo)
    assert set(allow_list(repo)) == set(integrate.PERMISSIONS)


def test_derived_paths_are_ignored(repo: Path) -> None:
    """The learning index is derived; the ledger is the record.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    run(repo)
    # Retain the immutable source representation consumed by subsequent analysis.
    text = (repo / ".gitignore").read_text(encoding="utf-8")
    assert ".agent/learning/learning.db" in text
    assert "build/doc/" in text


def test_greenfield_installs_the_same_skill_for_claude_and_codex(repo: Path) -> None:
    """Both native entry points are exact copies of one vendored source.

    @param repo an otherwise empty repository with a vendored discipline
    """
    # Retain the immutable source representation consumed by subsequent analysis.
    source = write_vendored_skill(repo)

    assert run(repo) == 0

    # Select host as the current element from (".claude", ".agents") while test greenfield
    # Details: installs the same skill for claude and codex preserves traversal order.
    # Advance test greenfield installs the same skill for claude and codex through the current
    # Details: input element in declared order.
    for host in (".claude", ".agents"):
        assert native_skill(repo, host).read_bytes() == source.read_bytes()
    # Decode integration-record section keys to their ownership values; mapping key order is
    # deliberately unused.
    record = json.loads(
        (repo / ".agent" / integrate.RECORD_NAME).read_text(encoding="utf-8")
    )
    assert set(record["skills"]) == set(integrate.SKILL_TARGETS)
    # Treat the current entry as the candidate element consumed by the enclosing transformation.
    assert all(entry["created"] for entry in record["skills"].values())


def test_a_vendor_upgrade_updates_both_unchanged_native_skills(repo: Path) -> None:
    """A new shared source replaces only files the prior integration wrote.

    @param repo an otherwise empty repository with a vendored discipline

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Retain the immutable source representation consumed by subsequent analysis.
    source = write_vendored_skill(repo)
    assert run(repo) == 0
    # Compute upgraded using SHARED_SKILL + "\nUpgrade marker.\n" for later test a vendor
    # Details: upgrade updates both unchanged native skills logic.
    upgraded = SHARED_SKILL + "\nUpgrade marker.\n"
    # Publish the externally visible effect after all required inputs are ready.
    source.write_text(upgraded, encoding="utf-8", newline="")

    assert run(repo) == 0

    # Select host as the current element from (".claude", ".agents") while test a vendor upgrade
    # Details: updates both unchanged native skills preserves traversal order.
    # Advance test a vendor upgrade updates both unchanged native skills through the current
    # Details: input element in declared order.
    for host in (".claude", ".agents"):
        assert native_skill(repo, host).read_text(encoding="utf-8") == upgraded


def test_an_existing_native_skill_is_reported_and_never_overwritten(repo: Path) -> None:
    """An unrecorded name collision blocks that host without deleting its file.

    @param repo an otherwise empty repository with a vendored discipline

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Retain the immutable source representation consumed by subsequent analysis.
    source = write_vendored_skill(repo)
    # Hold baseline path keys mapped to their recorded behavior-fingerprint values.
    existing = native_skill(repo, ".agents")
    # Publish the externally visible effect after all required inputs are ready.
    existing.parent.mkdir(parents=True)
    # Publish the externally visible effect after all required inputs are ready.
    existing.write_bytes(b"project-owned\r\n")

    assert run(repo) == 1

    assert existing.read_bytes() == b"project-owned\r\n"
    assert native_skill(repo, ".claude").read_bytes() == source.read_bytes()
    # Compute plan using integrate.build plan for later test an existing native skill is
    # Details: reported and never overwritten logic.
    plan = integrate.build_plan(repo, ".agent")
    # Treat the current item as the candidate element consumed by the enclosing transformation.
    assert any(".agents/skills/python-discipline/SKILL.md" in item
               for item in plan.problems)
    assert run(repo, "--check") == 1


def test_a_directory_at_the_skill_path_blocks_without_crashing(repo: Path) -> None:
    """A non-file collision stays intact and the other host can still integrate.

    @param repo an otherwise empty repository with a vendored discipline

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Retain the immutable source representation consumed by subsequent analysis.
    source = write_vendored_skill(repo)
    # Compute collision using native skill for later test a directory at the skill path blocks
    # Details: without crashing logic.
    collision = native_skill(repo, ".agents")
    # Publish the externally visible effect after all required inputs are ready.
    collision.mkdir(parents=True)

    assert run(repo) == 1

    assert collision.is_dir()
    assert native_skill(repo, ".claude").read_bytes() == source.read_bytes()


def test_remove_deletes_only_unchanged_skill_files_it_created(repo: Path) -> None:
    """A locally edited native skill survives while its unchanged twin is removed.

    @param repo an otherwise empty repository with a vendored discipline

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    write_vendored_skill(repo)
    assert run(repo) == 0
    # Compute codex using native skill for later test remove deletes only unchanged skill files
    # Details: it created logic.
    codex = native_skill(repo, ".agents")
    # Publish the externally visible effect after all required inputs are ready.
    codex.write_bytes(codex.read_bytes() + b"\nlocal edit\n")

    assert run(repo, "--remove") == 0

    assert not native_skill(repo, ".claude").exists()
    assert codex.read_bytes().endswith(b"local edit\n")
    # Decode integration-record section keys to their ownership values; mapping key order is
    # deliberately unused.
    record = json.loads(
        (repo / ".agent" / integrate.RECORD_NAME).read_text(encoding="utf-8")
    )
    assert record["skills"] == {}


def test_skill_integration_is_idempotent(repo: Path) -> None:
    """A second apply changes neither host entry point nor the record.

    @param repo an otherwise empty repository with a vendored discipline
    """
    write_vendored_skill(repo)
    assert run(repo) == 0
    # Map each repository-relative file path to exact bytes; mapping key order is deliberately
    # unused in the idempotence comparison.
    snapshot = {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*") if path.is_file()
    }

    # Compute plan using integrate.build plan for later test skill integration is idempotent
    # Details: logic.
    plan = integrate.build_plan(repo, ".agent")
    assert plan.changing == []
    assert plan.problems == []
    assert run(repo) == 0
    # Resolve the repository-confined path used by this operation before filesystem access.
    assert snapshot == {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*") if path.is_file()
    }


# ------------------------------------------------------------------- versioning


def test_a_release_is_named_beside_the_content_hash(repo: Path) -> None:
    """A reader recognises `v1.0.0`; only a tool recognises `abc123`.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    (repo / ".agent" / "MANIFEST.json").write_text(
        json.dumps({"release": "v1.0.0", "version": "abc123"}), encoding="utf-8"
    )
    run(repo)
    # Retain the immutable source representation consumed by subsequent analysis.
    text = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert "v1.0.0 (abc123)" in text


def test_a_manifest_without_a_release_still_names_its_hash(repo: Path) -> None:
    """The release name is additional; a manifest predating it must still work.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    run(repo)
    assert "abc123" in (repo / "CLAUDE.md").read_text(encoding="utf-8")


def test_a_manifest_that_is_not_an_object_is_reported_not_crashed_on(repo: Path) -> None:
    """A malformed manifest must be diagnosable, not an AttributeError.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    (repo / ".agent" / "MANIFEST.json").write_text(json.dumps(["v1.0.0"]), encoding="utf-8")
    assert integrate.read_version(repo, ".agent") == "unreadable"


# --------------------------------------------------------- existing configuration


@pytest.mark.parametrize(("label", "original"), [("lf", EXISTING_LF), ("crlf", EXISTING_CRLF)])
def test_an_existing_file_keeps_every_byte_it_had(
    repo: Path, label: str, original: bytes,
) -> None:
    """Scenario 2: the block is appended and not one prior byte is touched.

    Asserted on bytes, and driven from both endings, because the failure this
    guards against is exactly the one a text comparison cannot see: reading
    through universal newlines and writing back through the platform separator
    rewrites every line ending in the file while every decoded comparison still
    passes. A pure-LF fixture that comes back with carriage returns in it is a
    corrupted host file, however equal the two texts look.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    @param label which ending this case drives, naming the parametrised case
    @param original the host file's exact bytes before the integrator runs

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = repo / "CLAUDE.md"
    # Publish the externally visible effect after all required inputs are ready.
    path.write_bytes(original)
    assert kinds(repo)["CLAUDE.md"] is Kind.INSERT
    run(repo)

    # Compute after using path.read bytes for later test an existing file keeps every byte it
    # Details: had logic.
    after = path.read_bytes()
    assert after.startswith(original), f"{label}: the original bytes did not survive"
    assert integrate.BEGIN.encode() in after, f"{label}: the block was not written at all"


@pytest.mark.parametrize(("label", "original"), [("lf", EXISTING_LF), ("crlf", EXISTING_CRLF)])
def test_the_block_matches_the_host_files_line_endings(
    repo: Path, label: str, original: bytes,
) -> None:
    """A CRLF file must not come back half CRLF and half LF.

    Preserving the host's bytes is necessary but not sufficient: appending an
    LF-ended block to a CRLF file leaves it mixed, which every diff tool and
    every subsequent editor will then argue about.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    @param label which ending this case drives, naming the parametrised case
    @param original the host file's exact bytes before the integrator runs

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = repo / "CLAUDE.md"
    # Publish the externally visible effect after all required inputs are ready.
    path.write_bytes(original)
    run(repo)
    # Retain the immutable source representation consumed by subsequent analysis.
    body = path.read_bytes()
    # Select the guarded path only after `original.count(b'\r')` is satisfied.
    if original.count(b"\r"):
        assert body.count(b"\r\n") == body.count(b"\n"), f"{label}: a bare LF crept in"
        assert body.count(b"\r\n") == body.count(b"\r"), f"{label}: a bare CR crept in"
    else:
        assert body.count(b"\r") == 0, f"{label}: carriage returns appeared in an LF file"


def test_a_created_file_uses_lf(repo: Path) -> None:
    """A file with no prior bytes has no ending to preserve, so LF it is.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    run(repo)
    assert (repo / "CLAUDE.md").read_bytes().count(b"\r") == 0


@decides("DEP-013")
def test_an_existing_block_is_replaced_not_duplicated(repo: Path) -> None:
    """A newer discipline replaces its own block rather than stacking one.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    run(repo)
    # Compute first using (repo / "CLAUDE.md").read_text(encoding="utf-8") for later test an
    # Details: existing block is replaced not duplicated logic.
    first = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    # Publish the externally visible effect after all required inputs are ready.
    (repo / ".agent" / "MANIFEST.json").write_text(
        json.dumps({"version": "def456"}), encoding="utf-8"
    )
    assert kinds(repo)["CLAUDE.md"] is Kind.REPLACE
    run(repo)
    # Compute second using (repo / "CLAUDE.md").read_text(encoding="utf-8") for later test an
    # Details: existing block is replaced not duplicated logic.
    second = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert second.count(integrate.BEGIN) == 1
    assert "def456" in second
    assert first != second


def test_replacing_a_block_in_a_crlf_file_leaves_no_stray_carriage_return(
    repo: Path,
) -> None:
    """The block pattern must take the region's whole ending, not half of it.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = repo / "CLAUDE.md"
    # Publish the externally visible effect after all required inputs are ready.
    path.write_bytes(EXISTING_CRLF)
    run(repo)
    # Publish the externally visible effect after all required inputs are ready.
    (repo / ".agent" / "MANIFEST.json").write_text(
        json.dumps({"version": "def456"}), encoding="utf-8"
    )
    run(repo)
    # Retain the immutable source representation consumed by subsequent analysis.
    body = path.read_bytes()
    assert body.startswith(EXISTING_CRLF)
    assert body.count(b"\r") == body.count(b"\r\n")
    assert body.count(integrate.BEGIN.encode()) == 1


def test_content_around_an_existing_block_survives_replacement(repo: Path) -> None:
    """Text after the block is as much the project's as text before it.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    run(repo)
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = repo / "CLAUDE.md"
    # Publish the externally visible effect after all required inputs are ready.
    path.write_bytes(path.read_bytes() + b"\n## Deploy\n\nAsk first.\n")
    # Publish the externally visible effect after all required inputs are ready.
    (repo / ".agent" / "MANIFEST.json").write_text(
        json.dumps({"version": "def456"}), encoding="utf-8"
    )
    run(repo)
    # Retain the immutable source representation consumed by subsequent analysis.
    text = path.read_text(encoding="utf-8")
    assert text.startswith(f"# {repo.name}")
    assert text.rstrip().endswith("Ask first.")


def test_existing_permissions_are_never_removed(repo: Path) -> None:
    """The project's own entries outrank ours; we only add.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Compute settings path using repo / ".claude" / "settings.json" for later test existing
    # Details: permissions are never removed logic.
    settings_path = repo / ".claude" / "settings.json"
    # Publish the externally visible effect after all required inputs are ready.
    settings_path.parent.mkdir(parents=True)
    # Publish the externally visible effect after all required inputs are ready.
    settings_path.write_text(
        json.dumps({"permissions": {"allow": ["Bash(make:*)"], "deny": ["Bash(rm:*)"]},
                    "model": "opus"}, indent=2),
        encoding="utf-8",
    )
    run(repo)
    # Compute settings using json.loads for later test existing permissions are never removed
    # Details: logic.
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "Bash(make:*)" in settings["permissions"]["allow"]
    assert settings["permissions"]["deny"] == ["Bash(rm:*)"]
    assert settings["model"] == "opus"
    assert set(integrate.PERMISSIONS) <= set(settings["permissions"]["allow"])


def test_unparseable_settings_are_left_alone(repo: Path) -> None:
    """Guessing at a broken config would destroy what it was trying to fix.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Compute settings path using repo / ".claude" / "settings.json" for later test unparseable
    # Details: settings are left alone logic.
    settings_path = repo / ".claude" / "settings.json"
    # Publish the externally visible effect after all required inputs are ready.
    settings_path.parent.mkdir(parents=True)
    # Publish the externally visible effect after all required inputs are ready.
    settings_path.write_text("{ not json", encoding="utf-8")
    run(repo)
    assert settings_path.read_text(encoding="utf-8") == "{ not json"


# ----------------------------------------------------------------- idempotence


def test_running_twice_changes_nothing_the_second_time(repo: Path) -> None:
    """Re-vendoring must not accumulate blocks or permission entries.

    Snapshotted as bytes: a second run that rewrote every line ending would be
    invisible to a comparison of decoded text.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    (repo / "CLAUDE.md").write_bytes(EXISTING_CRLF)
    run(repo)
    # Map each repository-relative file path to exact bytes; mapping key order is deliberately
    # unused in the idempotence comparison.
    snapshot = {
        p.relative_to(repo).as_posix(): p.read_bytes()
        for p in repo.rglob("*") if p.is_file()
    }
    # Compute plan using integrate.build plan for later test running twice changes nothing the
    # Details: second time logic.
    plan = integrate.build_plan(repo, ".agent")
    assert plan.changing == [], "a second run wanted to change something"
    run(repo)
    # Map each post-run relative file path to exact bytes; mapping key order is deliberately
    # unused in the idempotence comparison.
    after = {
        p.relative_to(repo).as_posix(): p.read_bytes()
        for p in repo.rglob("*") if p.is_file()
    }
    assert after == snapshot


def test_check_reports_a_missing_block(repo: Path) -> None:
    """`--check` is what a consuming repository runs in its own gate.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    assert run(repo, "--check") == 1
    run(repo)
    assert run(repo, "--check") == 0


def test_check_reports_a_stale_block(repo: Path) -> None:
    """An updated discipline with an old block in place is out of step.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    run(repo)
    # Publish the externally visible effect after all required inputs are ready.
    (repo / ".agent" / "MANIFEST.json").write_text(
        json.dumps({"version": "newer"}), encoding="utf-8"
    )
    assert run(repo, "--check") == 1


@decides("DEP-014")
def test_a_dry_run_writes_nothing(repo: Path) -> None:
    """The preview truncates the same pipeline; it does not predict a second one.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    assert run(repo, "--dry-run") == 0
    assert not (repo / "CLAUDE.md").exists()
    assert not (repo / ".claude" / "settings.json").exists()
    assert not (repo / ".agent" / integrate.RECORD_NAME).exists()


# --------------------------------------------------------------------- removal


@pytest.mark.parametrize(("label", "original"), [("lf", EXISTING_LF), ("crlf", EXISTING_CRLF)])
def test_removal_restores_the_original_file(
    repo: Path, label: str, original: bytes,
) -> None:
    """Uninstalling must leave a pre-existing configuration byte for byte as it was.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    @param label which ending this case drives, naming the parametrised case
    @param original the host file's exact bytes before the integrator runs

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = repo / "CLAUDE.md"
    # Publish the externally visible effect after all required inputs are ready.
    path.write_bytes(original)
    run(repo)
    run(repo, "--remove")
    assert path.read_bytes() == original, f"{label}: removal did not restore the file"


def test_removal_takes_back_only_our_permissions(repo: Path) -> None:
    """A project entry added since must survive the uninstall.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    run(repo)
    # Compute settings path using repo / ".claude" / "settings.json" for later test removal
    # Details: takes back only our permissions logic.
    settings_path = repo / ".claude" / "settings.json"
    # Compute settings using json.loads for later test removal takes back only our permissions
    # Details: logic.
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings["permissions"]["allow"].append("Bash(make:*)")
    # Publish the externally visible effect after all required inputs are ready.
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    run(repo, "--remove")
    assert allow_list(repo) == ["Bash(make:*)"]


def test_a_permission_the_project_already_had_survives_add_then_remove(repo: Path) -> None:
    """The uninstall may take back only what the install actually added.

    A project that already allowed `Bash(pytest:*)` still allows it afterwards.
    Filtering the allow list by value cannot get this right -- the entry the
    discipline would add and the entry the project already had are the same
    string -- so what is removed has to come from a record written at install
    time, naming the entries that were genuinely absent beforehand.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    write_settings(repo, ["Bash(make:*)", SHARED_PERMISSION])
    run(repo)
    assert SHARED_PERMISSION in allow_list(repo)

    run(repo, "--remove")
    assert allow_list(repo) == ["Bash(make:*)", SHARED_PERMISSION], (
        "removal deleted a permission entry the project owned before the discipline arrived"
    )


def test_an_ignore_entry_the_project_already_had_survives_add_then_remove(repo: Path) -> None:
    """The same provenance rule governs the ignore file.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Compute original using "*.pyc\nbuild/doc/\n" for later test an ignore entry the project
    # Details: already had survives add then remove logic.
    original = "*.pyc\nbuild/doc/\n"
    # Publish the externally visible effect after all required inputs are ready.
    (repo / ".gitignore").write_text(original, encoding="utf-8", newline="")
    run(repo)
    run(repo, "--remove")
    assert (repo / ".gitignore").read_text(encoding="utf-8") == original


def test_an_install_without_a_record_removes_no_permission_at_all(repo: Path) -> None:
    """An install predating the record leaves the allow list alone, and says so.

    Silent deletion of a project's configuration is strictly worse than a
    leftover entry, so where provenance is unknowable the integrator declines to
    guess and names what it left.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    write_settings(repo, ["Bash(make:*)", SHARED_PERMISSION])
    run(repo)
    # Publish the externally visible effect after all required inputs are ready.
    (repo / ".agent" / integrate.RECORD_NAME).unlink()
    # Compute before using allow list for later test an install without a record removes no
    # Details: permission at all logic.
    before = allow_list(repo)

    # Compute plan using integrate.build plan for later test an install without a record removes
    # Details: no permission at all logic.
    plan = integrate.build_plan(repo, ".agent", remove=True)
    run(repo, "--remove")

    assert allow_list(repo) == before
    # Each named element is one warning mentioning the retained permission, in plan order.
    named = [w for w in plan.warnings if SHARED_PERMISSION in w]
    assert named, "the entries left behind were not named"
    assert "predates the record" in named[0]


def test_the_record_names_only_the_entries_that_were_absent(repo: Path) -> None:
    """The record is the evidence, so it must not claim more than was added.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    write_settings(repo, [SHARED_PERMISSION])
    run(repo)
    # Decode integration-record section keys to their ownership values; mapping key order is
    # deliberately unused.
    record = json.loads(
        (repo / ".agent" / integrate.RECORD_NAME).read_text(encoding="utf-8")
    )
    assert SHARED_PERMISSION not in record["permissions_added"]
    assert set(record["permissions_added"]) == set(integrate.PERMISSIONS) - {SHARED_PERMISSION}


def test_the_record_survives_a_vendor_upgrade(tmp_path: Path) -> None:
    """An upgrade replaces the upstream half, and must not take the record with it.

    The record is what makes `--remove` safe, so a re-vendor that dropped it
    would silently downgrade every later uninstall to the guessing path.

    @param tmp_path the per-test directory

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Retain the immutable source representation consumed by subsequent analysis.
    source = Path(__file__).resolve().parent.parent
    # Resolve the repository-confined path used by this operation before filesystem access.
    target = tmp_path / "host"
    # Publish the externally visible effect after all required inputs are ready.
    target.mkdir()
    vendor.install(vendor.Plan(source, target))
    write_settings(target, [SHARED_PERMISSION])
    run(target)
    # Locate the integration-record path whose bytes must survive replacement of vendored files.
    record = target / ".agent" / integrate.RECORD_NAME
    # Compute kept using record.read text for later test the record survives a vendor upgrade
    # Details: logic.
    kept = record.read_text(encoding="utf-8")

    vendor.install(vendor.Plan(source, target))

    assert record.exists(), "the upgrade deleted the install record"
    assert record.read_text(encoding="utf-8") == kept
    run(target, "--remove")
    assert allow_list(target) == [SHARED_PERMISSION]


def test_removal_restores_an_existing_gitignore(repo: Path) -> None:
    """Removal takes its own header too, or the file is not restored.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Compute original using "*.pyc\n__pycache__/\n" for later test removal restores an existing
    # Details: gitignore logic.
    original = "*.pyc\n__pycache__/\n"
    # Publish the externally visible effect after all required inputs are ready.
    (repo / ".gitignore").write_text(original, encoding="utf-8", newline="")
    run(repo)
    run(repo, "--remove")
    assert (repo / ".gitignore").read_text(encoding="utf-8") == original


def test_removal_is_idempotent(repo: Path) -> None:
    """Removing twice is not an error, and changes nothing the second time.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    run(repo)
    run(repo, "--remove")
    # Compute plan using integrate.build plan for later test removal is idempotent logic.
    plan = integrate.build_plan(repo, ".agent", remove=True)
    assert plan.changing == []


def test_removal_leaves_a_repository_that_never_had_a_record_alone(repo: Path) -> None:
    """`--remove` on a repository with nothing installed writes no record either.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    assert integrate.build_plan(repo, ".agent", remove=True).changing == []
    run(repo, "--remove")
    assert not (repo / ".agent" / integrate.RECORD_NAME).exists()


# ------------------------------------------------------------------- warnings


def test_a_missing_discipline_is_warned_about(tmp_path: Path) -> None:
    """Announcing a discipline that is not there would be a lie.

    @param tmp_path the per-test directory, deliberately without a vendored copy
    """
    # Compute plan using integrate.build plan for later test a missing discipline is warned
    # Details: about logic.
    plan = integrate.build_plan(tmp_path, ".agent")
    # Select w as the current element from plan.warnings) while test a missing discipline is
    # Details: warned about preserves traversal order.
    assert any("vendor.py install" in w for w in plan.warnings)


def test_only_restricts_the_markdown_targets(repo: Path) -> None:
    """A project that keeps one of the two files should not gain the other.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    # Compute planned using kinds for later test only restricts the markdown targets logic.
    planned = kinds(repo, targets=("CLAUDE.md",))
    assert "AGENTS.md" not in planned
    assert planned["CLAUDE.md"] is Kind.CREATE


# ------------------------------------------------------------------- hooks
#
# FLOW-009 -- the gates pass before a change is offered -- was enforced by memory
# until `--hooks` existed. By this corpus's own standard that means it was not
# binding at all.


def _repo(root: Path, *, with_hooks: bool = True) -> Path:
    """A throwaway git repository, optionally carrying the vendored hooks.

    @param root the directory to initialise
    @param with_hooks whether to place a hook directory in it
        True enables with hooks; false selects its disabled alternative.
    @return the repository root

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    subprocess.run(("git", "init", "-q", "."), cwd=root, check=True,  # ruff: ignore[start-process-with-partial-path]
                   capture_output=True)
    # Handle the non-empty or enabled with hooks state.
    if with_hooks:
        # Compute hooks using root / "enforce" / "templates" / "hooks" for later repo logic.
        hooks = root / "enforce" / "templates" / "hooks"
        # Publish the externally visible effect after all required inputs are ready.
        hooks.mkdir(parents=True)
        # Publish the externally visible effect after all required inputs are ready.
        (hooks / "pre-push").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    # Return the repository root to the caller.
    return root


def _hooks_path(root: Path) -> str:
    """What git currently believes `core.hooksPath` is.

    @param root the repository to ask
    @return the configured value, or the empty string when unset
    """
    # Preserve the external command representation and its observed completion outcome.
    finished = subprocess.run(("git", "config", "core.hooksPath"),  # ruff: ignore[start-process-with-partial-path]
                              cwd=root, capture_output=True, text=True, check=False)
    # Return the configured value, or the empty string when unset to the caller.
    return finished.stdout.strip()


def test_hooks_are_pointed_at_not_copied(tmp_path: Path) -> None:
    """A copy is a fork; a pointer updates with the discipline.

    Copying into `.git/hooks` means the first update to the vendored discipline
    leaves a stale duplicate nobody diffs. Pointing means an update updates the
    hook, and unsetting one config removes it with no residue.

    @param tmp_path the fixture directory
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = _repo(tmp_path)
    integrate.install_hooks(root, ".agent")
    assert _hooks_path(root) == "enforce/templates/hooks"
    assert not (root / ".git" / "hooks" / "pre-push").exists(), (
        "the hook was copied into .git/hooks, which forks it from the discipline"
    )


def test_removing_the_hooks_leaves_nothing_behind(tmp_path: Path) -> None:
    """...and taking it out restores git's default completely.

    @param tmp_path the fixture directory
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = _repo(tmp_path)
    integrate.install_hooks(root, ".agent")
    integrate.install_hooks(root, ".agent", remove=True)
    assert not _hooks_path(root)


def test_a_missing_hook_directory_refuses(tmp_path: Path) -> None:
    """Pointing git at an empty path would DISABLE hooks a project already had.

    The failure mode this refuses is the quiet one: `core.hooksPath` set to a
    directory with nothing in it turns off every hook the repository has, and
    reports success while doing it.

    @param tmp_path the fixture directory
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = _repo(tmp_path, with_hooks=False)
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(FileNotFoundError):
        integrate.install_hooks(root, ".agent")
    assert not _hooks_path(root)


def test_the_shipped_hook_runs_the_whole_gate() -> None:
    """The hook must run the gate, not a chosen part of it.

    A pre-push hook running three cheap steps would report green for a tree the
    gate rejects, which is worse than no hook: it is a hook people trust.
    """
    # Compute hook using (Path(integrate.__file__).resolve().parent.parent / "enforce for later
    # Details: test the shipped hook runs the whole gate logic.
    hook = (Path(integrate.__file__).resolve().parent.parent / "enforce"
            / "templates" / "hooks" / "pre-push")
    # Retain the immutable source representation consumed by subsequent analysis.
    body = hook.read_text(encoding="utf-8")
    assert "gate.py" in body, "the hook does not run the gate at all"
    assert "--no-verify" in body, (
        "the hook does not tell a reader how to bypass it, so they will find out "
        "by guessing, and guess something worse"
    )


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    # Propagate the localized failure so callers cannot mistake it for success.
    raise SystemExit(pytest.main([__file__, "-q"]))
