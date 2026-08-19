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
from pathlib import Path

import pytest

import integrate
import vendor
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


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with a vendored discipline and a manifest.

    @param tmp_path the per-test directory
    @return the repository root
    """
    (tmp_path / ".agent" / "discipline").mkdir(parents=True)
    (tmp_path / ".agent" / "MANIFEST.json").write_text(
        json.dumps({"version": "abc123"}), encoding="utf-8"
    )
    return tmp_path


def run(root: Path, *args: str) -> int:
    """Invoke the integrator against a repository.

    @param root the repository root
    @param args extra command-line arguments
    @return the exit status
    """
    return integrate.main(["--root", str(root), *args])


def kinds(root: Path, **kwargs: object) -> dict[str, Kind]:
    """The planned action kind for each target file.

    @param root the repository root
    @param kwargs forwarded to `build_plan`
    @return file name mapped to planned action kind
    """
    plan = integrate.build_plan(root, ".agent", **kwargs)  # type: ignore[arg-type]
    return {a.path.name: a.kind for a in plan.actions}


def allow_list(root: Path) -> list[str]:
    """Read the permissions a repository currently grants.

    @param root the repository root
    @return the entries, in file order
    """
    text = (root / ".claude" / "settings.json").read_text(encoding="utf-8")
    allowed = json.loads(text)["permissions"]["allow"]
    return [str(entry) for entry in allowed]


def write_settings(root: Path, allow: list[str]) -> Path:
    """Give a repository a settings file it owned before the discipline arrived.

    @param root the repository root
    @param allow the entries the project already allows
    @return the settings file
    """
    path = root / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"permissions": {"allow": allow}}, indent=2), encoding="utf-8")
    return path


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
    for name in ("CLAUDE.md", "AGENTS.md"):
        text = (repo / name).read_text(encoding="utf-8")
        assert integrate.BEGIN in text
        assert integrate.END in text
        assert "KERNEL.md" in text


def test_a_created_file_stays_minimal(repo: Path) -> None:
    """The rest of the project's configuration is the project's to write.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    run(repo)
    text = (repo / "CLAUDE.md").read_text(encoding="utf-8")
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
    text = (repo / ".gitignore").read_text(encoding="utf-8")
    assert ".agent/learning/learning.db" in text
    assert "build/doc/" in text


# ------------------------------------------------------------------- versioning


def test_a_release_is_named_beside_the_content_hash(repo: Path) -> None:
    """A reader recognises `v1.0.0`; only a tool recognises `abc123`.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    (repo / ".agent" / "MANIFEST.json").write_text(
        json.dumps({"release": "v1.0.0", "version": "abc123"}), encoding="utf-8"
    )
    run(repo)
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
    """
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
    """
    path = repo / "CLAUDE.md"
    path.write_bytes(original)
    assert kinds(repo)["CLAUDE.md"] is Kind.INSERT
    run(repo)

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
    """
    path = repo / "CLAUDE.md"
    path.write_bytes(original)
    run(repo)
    body = path.read_bytes()
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


def test_an_existing_block_is_replaced_not_duplicated(repo: Path) -> None:
    """A newer discipline replaces its own block rather than stacking one.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    run(repo)
    first = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    (repo / ".agent" / "MANIFEST.json").write_text(
        json.dumps({"version": "def456"}), encoding="utf-8"
    )
    assert kinds(repo)["CLAUDE.md"] is Kind.REPLACE
    run(repo)
    second = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert second.count(integrate.BEGIN) == 1
    assert "def456" in second
    assert first != second


def test_replacing_a_block_in_a_crlf_file_leaves_no_stray_carriage_return(
    repo: Path,
) -> None:
    """The block pattern must take the region's whole ending, not half of it.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    path = repo / "CLAUDE.md"
    path.write_bytes(EXISTING_CRLF)
    run(repo)
    (repo / ".agent" / "MANIFEST.json").write_text(
        json.dumps({"version": "def456"}), encoding="utf-8"
    )
    run(repo)
    body = path.read_bytes()
    assert body.startswith(EXISTING_CRLF)
    assert body.count(b"\r") == body.count(b"\r\n")
    assert body.count(integrate.BEGIN.encode()) == 1


def test_content_around_an_existing_block_survives_replacement(repo: Path) -> None:
    """Text after the block is as much the project's as text before it.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    run(repo)
    path = repo / "CLAUDE.md"
    path.write_bytes(path.read_bytes() + b"\n## Deploy\n\nAsk first.\n")
    (repo / ".agent" / "MANIFEST.json").write_text(
        json.dumps({"version": "def456"}), encoding="utf-8"
    )
    run(repo)
    text = path.read_text(encoding="utf-8")
    assert text.startswith(f"# {repo.name}")
    assert text.rstrip().endswith("Ask first.")


def test_existing_permissions_are_never_removed(repo: Path) -> None:
    """The project's own entries outrank ours; we only add.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    settings_path = repo / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps({"permissions": {"allow": ["Bash(make:*)"], "deny": ["Bash(rm:*)"]},
                    "model": "opus"}, indent=2),
        encoding="utf-8",
    )
    run(repo)
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "Bash(make:*)" in settings["permissions"]["allow"]
    assert settings["permissions"]["deny"] == ["Bash(rm:*)"]
    assert settings["model"] == "opus"
    assert set(integrate.PERMISSIONS) <= set(settings["permissions"]["allow"])


def test_unparseable_settings_are_left_alone(repo: Path) -> None:
    """Guessing at a broken config would destroy what it was trying to fix.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    settings_path = repo / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text("{ not json", encoding="utf-8")
    run(repo)
    assert settings_path.read_text(encoding="utf-8") == "{ not json"


# ----------------------------------------------------------------- idempotence


def test_running_twice_changes_nothing_the_second_time(repo: Path) -> None:
    """Re-vendoring must not accumulate blocks or permission entries.

    Snapshotted as bytes: a second run that rewrote every line ending would be
    invisible to a comparison of decoded text.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    (repo / "CLAUDE.md").write_bytes(EXISTING_CRLF)
    run(repo)
    snapshot = {
        p.relative_to(repo).as_posix(): p.read_bytes()
        for p in repo.rglob("*") if p.is_file()
    }
    plan = integrate.build_plan(repo, ".agent")
    assert plan.changing == [], "a second run wanted to change something"
    run(repo)
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
    """
    run(repo)
    (repo / ".agent" / "MANIFEST.json").write_text(
        json.dumps({"version": "newer"}), encoding="utf-8"
    )
    assert run(repo, "--check") == 1


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
    """
    path = repo / "CLAUDE.md"
    path.write_bytes(original)
    run(repo)
    run(repo, "--remove")
    assert path.read_bytes() == original, f"{label}: removal did not restore the file"


def test_removal_takes_back_only_our_permissions(repo: Path) -> None:
    """A project entry added since must survive the uninstall.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    run(repo)
    settings_path = repo / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings["permissions"]["allow"].append("Bash(make:*)")
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
    """
    original = "*.pyc\nbuild/doc/\n"
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
    """
    write_settings(repo, ["Bash(make:*)", SHARED_PERMISSION])
    run(repo)
    (repo / ".agent" / integrate.RECORD_NAME).unlink()
    before = allow_list(repo)

    plan = integrate.build_plan(repo, ".agent", remove=True)
    run(repo, "--remove")

    assert allow_list(repo) == before
    named = [w for w in plan.warnings if SHARED_PERMISSION in w]
    assert named, "the entries left behind were not named"
    assert "predates the record" in named[0]


def test_the_record_names_only_the_entries_that_were_absent(repo: Path) -> None:
    """The record is the evidence, so it must not claim more than was added.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    write_settings(repo, [SHARED_PERMISSION])
    run(repo)
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
    """
    source = Path(__file__).resolve().parent.parent
    target = tmp_path / "host"
    target.mkdir()
    vendor.install(vendor.Plan(source, target))
    write_settings(target, [SHARED_PERMISSION])
    run(target)
    record = target / ".agent" / integrate.RECORD_NAME
    kept = record.read_text(encoding="utf-8")

    vendor.install(vendor.Plan(source, target))

    assert record.exists(), "the upgrade deleted the install record"
    assert record.read_text(encoding="utf-8") == kept
    run(target, "--remove")
    assert allow_list(target) == [SHARED_PERMISSION]


def test_removal_restores_an_existing_gitignore(repo: Path) -> None:
    """Removal takes its own header too, or the file is not restored.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    original = "*.pyc\n__pycache__/\n"
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
    plan = integrate.build_plan(tmp_path, ".agent")
    assert any("vendor.py install" in w for w in plan.warnings)


def test_only_restricts_the_markdown_targets(repo: Path) -> None:
    """A project that keeps one of the two files should not gain the other.

    @param repo an otherwise empty repository with a vendored discipline at version `abc123`
    """
    planned = kinds(repo, targets=("CLAUDE.md",))
    assert "AGENTS.md" not in planned
    assert planned["CLAUDE.md"] is Kind.CREATE


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
