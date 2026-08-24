"""Tests for the shared Claude Code and Codex skill mirrors.

**Oracle: state.** Each assertion compares both generated discovery trees with
one canonical skill tree. The failure proof damages only one host copy and
requires `--check` to name it, so agreement cannot mean checking Claude twice.

    pytest tools/test_build_skill_mirror.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from pathlib import Path

    import pytest

import build_skill_mirror


def seed(root: Path) -> Path:
    """Create a small canonical skill tree with a nested asset.

    @param root the throwaway repository root
    @return the canonical skill directory

    @par Effects
    Writes only pytest-owned discipline sources and their generated Claude/Codex mirror fixtures.
    """
    # Establish the canonical skill source whose generated host mirrors are under test.
    source = root / "skills" / "python-discipline"
    (source / "assets").mkdir(parents=True)
    (source / "SKILL.md").write_bytes(b"---\nname: python-discipline\n---\n")
    (source / "assets" / "routing.txt").write_bytes(b"one corpus\r\n")
    return source


def mirrored(root: Path, host: str, relative: str) -> Path:
    """Resolve one generated file below a host's discovery root.

    @param root the throwaway repository root
    @param host either `.claude` or `.agents`
    @param relative a path below the skill directory
    @return the generated path
    """
    # Keep host-specific discovery roots outside the canonical skill tree.
    return root / host / "skills" / "python-discipline" / relative


def test_one_source_is_mirrored_byte_for_byte_to_both_hosts(tmp_path: Path) -> None:
    """Claude Code and Codex receive every canonical file with exact bytes.

    @param tmp_path the throwaway repository root
    """
    # Retain the canonical source while checking freshly generated host mirrors.
    source = seed(tmp_path)

    assert build_skill_mirror.main(["--root", str(tmp_path)]) == 0

    # Verify canonical bytes and nested assets independently in both host discovery roots.
    for host in (".claude", ".agents"):
        assert mirrored(tmp_path, host, "SKILL.md").read_bytes() == (
            source / "SKILL.md"
        ).read_bytes()
        assert mirrored(tmp_path, host, "assets/routing.txt").read_bytes() == (
            source / "assets" / "routing.txt"
        ).read_bytes()


def test_check_names_the_host_copy_that_drifted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """The check observes Codex drift independently of the Claude mirror.

    @param tmp_path the throwaway repository root
    @param capsys pytest's captured-console fixture

    @par Effects
    Writes only pytest-owned discipline sources and their generated Claude/Codex mirror fixtures.
    """
    seed(tmp_path)
    assert build_skill_mirror.main(["--root", str(tmp_path)]) == 0
    # Corrupt only Codex's projection so the diagnostic must identify that host.
    mirrored(tmp_path, ".agents", "SKILL.md").write_bytes(b"drift\n")

    assert build_skill_mirror.main(["--root", str(tmp_path), "--check"]) == 1
    # Combine the checker's captured diagnostic streams without losing emission text.
    output = capsys.readouterr().out
    assert ".agents/skills/python-discipline/SKILL.md" in output
    assert ".claude/skills/python-discipline/SKILL.md" not in output


def test_retired_files_are_removed_from_both_host_mirrors(tmp_path: Path) -> None:
    """A file removed once cannot survive as guidance for either agent.

    @param tmp_path the throwaway repository root

    @par Effects
    Writes only pytest-owned discipline sources and their generated Claude/Codex mirror fixtures.
    """
    # Retain the canonical source while removing one upstream file before regeneration.
    source = seed(tmp_path)
    assert build_skill_mirror.main(["--root", str(tmp_path)]) == 0
    (source / "assets" / "routing.txt").unlink()

    assert build_skill_mirror.main(["--root", str(tmp_path)]) == 0

    # Verify the retired asset disappeared independently from both host mirrors.
    for host in (".claude", ".agents"):
        assert not mirrored(tmp_path, host, "assets/routing.txt").exists()
