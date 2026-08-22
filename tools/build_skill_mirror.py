"""Mirror the canonical skill into Claude Code and Codex discovery roots.

    python tools/build_skill_mirror.py [--check] [--root PATH]

`skills/python-discipline/` is the one authored skill. Both supported hosts need
their own repository-local discovery path, so this builder makes exact mirrors
at `.claude/skills/python-discipline/` and
`.agents/skills/python-discipline/`. Keeping one source is load-bearing: Claude
Code and Codex must not receive two disciplines that merely started alike.

The skill routes into the repository's canonical `discipline/` tree (or the
vendored `.agent/discipline/` tree) instead of carrying another copy of the
corpus. Earlier releases mirrored the whole corpus below the Claude skill's
`references/`; that made the skill Claude-specific and left a second body of
rules to keep current. Orphan removal deliberately retires that old mirror.

``--check`` writes nothing and exits non-zero if either host mirror is stale or
carries a file the canonical skill no longer has, which is the form run in CI.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from itertools import starmap
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

## Anchor for the default root, derived from this file rather than the working
## directory, so the tool behaves the same however it was invoked.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent
## The one authored skill tree, relative to the repository root.
SOURCE_DIR_PARTS: Final = ("skills", "python-discipline")
## Host-specific discovery roots generated from the same authored skill.
DEST_DIRS_PARTS: Final[tuple[tuple[str, ...], ...]] = (
    (".claude", "skills", "python-discipline"),
    (".agents", "skills", "python-discipline"),
)

## Heads the console summary so a human knows every copy direction without
## reading the source.
_CHECK_BANNER: Final = (
    "skill mirrors (skills/python-discipline/ -> "
    ".claude/skills/python-discipline/ + .agents/skills/python-discipline/)"
)


@dataclass(frozen=True, slots=True)
class Artifact:
    """One mirrored file and the bytes it should contain."""

    ## Where the file belongs in a host discovery tree, absolute.
    path: Path
    ## Its full intended contents, exactly as read from the canonical skill.
    content: bytes

    def is_stale(self) -> bool:
        """Whether what is on disk differs from the canonical skill.

        @return True when writing would change the tree
        """
        return not self.path.is_file() or self.path.read_bytes() != self.content

    def write(self) -> None:
        """Put the bytes on disk, creating any parent directory they need."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(self.content)


def source_files(source_dir: Path) -> list[Path]:
    """Every file under the canonical skill, in stable order.

    @param source_dir the authored `skills/python-discipline/` directory
    @return the canonical skill files, sorted for deterministic output
    """
    return sorted(path for path in source_dir.rglob("*") if path.is_file())


def build_artifacts(source_dir: Path, dest_dir: Path) -> list[Artifact]:
    """One artifact per canonical skill file for one host.

    @param source_dir the authored skill directory
    @param dest_dir one host's generated discovery directory
    @return one exact-copy artifact per source file
    """
    return [
        Artifact(dest_dir / path.relative_to(source_dir), path.read_bytes())
        for path in source_files(source_dir)
    ]


def orphaned_files(source_dir: Path, dest_dir: Path) -> list[Path]:
    """Files in a host mirror with no canonical counterpart.

    A retired file must not remain discoverable by one host after the other has
    stopped receiving it. This also removes the pre-v3.3 `references/` corpus
    mirror after the canonical skill becomes a router into `discipline/`.

    @param source_dir the authored skill directory
    @param dest_dir one host's generated discovery directory
    @return generated files with no source counterpart, sorted
    """
    if not dest_dir.exists():
        return []
    wanted = {path.relative_to(source_dir) for path in source_files(source_dir)}
    return sorted(
        path
        for path in dest_dir.rglob("*")
        if path.is_file() and path.relative_to(dest_dir) not in wanted
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Regenerate both mirrors, or only report their staleness.

    @param argv command-line arguments, defaulting to `sys.argv`
    @return 0 on success, 1 when `--check` finds anything out of date
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Regenerate both agent skill mirrors.")
    parser.add_argument("--check", action="store_true", help="report staleness, write nothing")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    source_dir = root.joinpath(*SOURCE_DIR_PARTS)
    dest_dirs = list(starmap(root.joinpath, DEST_DIRS_PARTS))
    artifacts: list[Artifact] = []
    for dest_dir in dest_dirs:
        artifacts.extend(build_artifacts(source_dir, dest_dir))
    stale = [artifact for artifact in artifacts if artifact.is_stale()]
    orphans = [
        orphan
        for dest_dir in dest_dirs
        for orphan in orphaned_files(source_dir, dest_dir)
    ]

    if args.check:
        for artifact in stale:
            print(f"stale mirror file: {artifact.path.relative_to(root).as_posix()}")
        for orphan in orphans:
            print(f"orphaned mirror file: {orphan.relative_to(root).as_posix()}")
        total = len(stale) + len(orphans)
        verdict = f"{total} stale file(s)." if total else "up to date."
        print(f"{_CHECK_BANNER}: {verdict}")
        return 1 if total else 0

    for artifact in artifacts:
        artifact.write()
    for orphan in orphans:
        orphan.unlink()
    print(
        f"wrote {len(artifacts)} mirrored file(s) across {len(dest_dirs)} agent roots; "
        f"{len(stale)} were stale, {len(orphans)} orphan(s) removed."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
