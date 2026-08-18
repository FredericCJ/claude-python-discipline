"""Tests for announcing a vendored discipline to a repository's configuration.

Two properties carry the weight. **Preservation**: a repository that already has
a configuration must get the block and nothing else disturbed, byte for byte.
**Idempotence**: running twice must leave the same file as running once, or
re-vendoring would accumulate blocks.

    pytest tools/test_integrate.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import integrate
from integrate import Kind

## A configuration a project already had before the discipline arrived.
EXISTING_CLAUDE = """# Acme Service

## Running it

    make serve

## Conventions

Branch names are `feat/<ticket>`. Ask before touching `legacy/`.
"""


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


# ------------------------------------------------------------------ greenfield


def test_greenfield_creates_both_markdown_targets(repo: Path) -> None:
    """Scenario 1: nothing exists, so a minimal file is created for each."""
    assert kinds(repo) == {
        "CLAUDE.md": Kind.CREATE,
        "AGENTS.md": Kind.CREATE,
        "settings.json": Kind.CREATE,
        ".gitignore": Kind.CREATE,
    }
    run(repo)
    for name in ("CLAUDE.md", "AGENTS.md"):
        text = (repo / name).read_text(encoding="utf-8")
        assert integrate.BEGIN in text
        assert integrate.END in text
        assert "KERNEL.md" in text


def test_a_created_file_stays_minimal(repo: Path) -> None:
    """The rest of the project's configuration is the project's to write."""
    run(repo)
    text = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    outside = integrate.BLOCK_RE.sub("", text).strip()
    assert outside == f"# {repo.name}"


def test_permissions_are_created_with_the_narrow_set(repo: Path) -> None:
    """Only the discipline's own read-or-verify invocations are allowed."""
    run(repo)
    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert set(settings["permissions"]["allow"]) == set(integrate.PERMISSIONS)


def test_derived_paths_are_ignored(repo: Path) -> None:
    """The learning index is derived; the ledger is the record."""
    run(repo)
    text = (repo / ".gitignore").read_text(encoding="utf-8")
    assert ".agent/learning/learning.db" in text
    assert "build/doc/" in text


# --------------------------------------------------------- existing configuration


def test_an_existing_file_keeps_every_byte_it_had(repo: Path) -> None:
    """Scenario 2: the block is appended and nothing else is touched."""
    (repo / "CLAUDE.md").write_text(EXISTING_CLAUDE, encoding="utf-8")
    assert kinds(repo)["CLAUDE.md"] is Kind.INSERT
    run(repo)
    text = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.startswith(EXISTING_CLAUDE)
    outside = integrate.BLOCK_RE.sub("", text).rstrip()
    assert outside == EXISTING_CLAUDE.rstrip()


def test_an_existing_block_is_replaced_not_duplicated(repo: Path) -> None:
    """A newer discipline replaces its own block rather than stacking one."""
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


def test_content_around_an_existing_block_survives_replacement(repo: Path) -> None:
    """Text after the block is as much the project's as text before it."""
    run(repo)
    path = repo / "CLAUDE.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n## Deploy\n\nAsk first.\n",
                    encoding="utf-8")
    (repo / ".agent" / "MANIFEST.json").write_text(
        json.dumps({"version": "def456"}), encoding="utf-8"
    )
    run(repo)
    text = path.read_text(encoding="utf-8")
    assert text.startswith(f"# {repo.name}")
    assert text.rstrip().endswith("Ask first.")


def test_existing_permissions_are_never_removed(repo: Path) -> None:
    """The project's own entries outrank ours; we only add."""
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
    """Guessing at a broken config would destroy what it was trying to fix."""
    settings_path = repo / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text("{ not json", encoding="utf-8")
    run(repo)
    assert settings_path.read_text(encoding="utf-8") == "{ not json"


# ----------------------------------------------------------------- idempotence


def test_running_twice_changes_nothing_the_second_time(repo: Path) -> None:
    """Re-vendoring must not accumulate blocks or permission entries."""
    run(repo)
    snapshot = {
        p.relative_to(repo).as_posix(): p.read_text(encoding="utf-8")
        for p in repo.rglob("*") if p.is_file()
    }
    plan = integrate.build_plan(repo, ".agent")
    assert plan.changing == [], "a second run wanted to change something"
    run(repo)
    after = {
        p.relative_to(repo).as_posix(): p.read_text(encoding="utf-8")
        for p in repo.rglob("*") if p.is_file()
    }
    assert after == snapshot


def test_check_reports_a_missing_block(repo: Path) -> None:
    """`--check` is what a consuming repository runs in its own gate."""
    assert run(repo, "--check") == 1
    run(repo)
    assert run(repo, "--check") == 0


def test_check_reports_a_stale_block(repo: Path) -> None:
    """An updated discipline with an old block in place is out of step."""
    run(repo)
    (repo / ".agent" / "MANIFEST.json").write_text(
        json.dumps({"version": "newer"}), encoding="utf-8"
    )
    assert run(repo, "--check") == 1


def test_a_dry_run_writes_nothing(repo: Path) -> None:
    """The preview truncates the same pipeline; it does not predict a second one."""
    assert run(repo, "--dry-run") == 0
    assert not (repo / "CLAUDE.md").exists()
    assert not (repo / ".claude" / "settings.json").exists()


# --------------------------------------------------------------------- removal


def test_removal_restores_the_original_file(repo: Path) -> None:
    """Uninstalling must leave a pre-existing configuration as it was."""
    (repo / "CLAUDE.md").write_text(EXISTING_CLAUDE, encoding="utf-8")
    run(repo)
    run(repo, "--remove")
    assert (repo / "CLAUDE.md").read_text(encoding="utf-8") == EXISTING_CLAUDE.rstrip() + "\n"


def test_removal_takes_back_only_our_permissions(repo: Path) -> None:
    """A project entry added since must survive the uninstall."""
    run(repo)
    settings_path = repo / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings["permissions"]["allow"].append("Bash(make:*)")
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    run(repo, "--remove")
    after = json.loads(settings_path.read_text(encoding="utf-8"))
    assert after["permissions"]["allow"] == ["Bash(make:*)"]


def test_removal_restores_an_existing_gitignore(repo: Path) -> None:
    """Removal takes its own header too, or the file is not restored."""
    original = "*.pyc\n__pycache__/\n"
    (repo / ".gitignore").write_text(original, encoding="utf-8")
    run(repo)
    run(repo, "--remove")
    assert (repo / ".gitignore").read_text(encoding="utf-8") == original


def test_removal_is_idempotent(repo: Path) -> None:
    """Removing twice is not an error, and changes nothing the second time."""
    run(repo)
    run(repo, "--remove")
    plan = integrate.build_plan(repo, ".agent", remove=True)
    assert plan.changing == []


# ------------------------------------------------------------------- warnings


def test_a_missing_discipline_is_warned_about(tmp_path: Path) -> None:
    """Announcing a discipline that is not there would be a lie."""
    plan = integrate.build_plan(tmp_path, ".agent")
    assert any("vendor.py install" in w for w in plan.warnings)


def test_only_restricts_the_markdown_targets(repo: Path) -> None:
    """A project that keeps one of the two files should not gain the other.

    @param repo the repository fixture
    """
    planned = kinds(repo, targets=("CLAUDE.md",))
    assert "AGENTS.md" not in planned
    assert planned["CLAUDE.md"] is Kind.CREATE


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
