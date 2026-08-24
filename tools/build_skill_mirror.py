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

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Sequence

## Anchor for the default root, derived from this file rather than the working
## directory, so the tool behaves the same however it was invoked.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent
## The one authored skill tree, relative to the repository root.
## Each element is one successive path segment; tuple order defines the canonical skill path.
SOURCE_DIR_PARTS: Final = ("skills", "python-discipline")
## Host-specific discovery roots generated from the same authored skill.
## Each outer element is one host discovery path, whose inner segments remain in path order;
## outer order fixes deterministic Claude-then-Codex reporting.
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
        # Absence and any byte delta are equally host-mirror drift.
        return not self.path.is_file() or self.path.read_bytes() != self.content

    def write(self) -> None:
        """Put the bytes on disk, creating any parent directory they need.

        @par Effects
        Creates missing parent directories, then replaces this mirror file with
        the canonical bytes.
        """
        # Establish the complete destination directory chain before publishing file bytes.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Replace the mirror with the exact canonical content after its parent exists.
        self.path.write_bytes(self.content)


def source_files(source_dir: Path) -> list[Path]:
    """Every file under the canonical skill, in stable order.

    @param source_dir the authored `skills/python-discipline/` directory
    @return the canonical skill files, sorted for deterministic output
    """
    # File-only traversal plus lexical order gives both hosts the same copy plan.
    return sorted(path for path in source_dir.rglob("*") if path.is_file())


def build_artifacts(source_dir: Path, dest_dir: Path) -> list[Artifact]:
    """One artifact per canonical skill file for one host.

    @param source_dir the authored skill directory
    @param dest_dir one host's generated discovery directory
    @return one exact-copy artifact per source file
    """
    # Each element couples canonical bytes to the same relative path below one host root.
    return [
        Artifact(dest_dir / path.relative_to(source_dir), path.read_bytes())
        # Preserve each canonical file's relative path while copying its exact bytes.
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
    # An absent host mirror cannot contain stale generated files.
    if not dest_dir.exists():
        # No discovery root means there are no retired projections to remove.
        return []
    # Collect unique wanted element values; their order is deliberately unordered.
    wanted = {path.relative_to(source_dir) for path in source_files(source_dir)}
    # Every returned path is a generated destination with no canonical counterpart.
    return sorted(
        path
        # Retain only regular mirror files whose relative path lacks a canonical source.
        for path in dest_dir.rglob("*")
        if path.is_file() and path.relative_to(dest_dir) not in wanted
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Regenerate both mirrors, or only report their staleness.

    @param argv command-line arguments, defaulting to `sys.argv`
    @return 0 on success, 1 when `--check` finds anything out of date

    @par Effects
    In write mode, creates or replaces canonical mirror files before removing
    orphaned generated files; check mode performs no filesystem writes.
    """
    # Normalize console encoding when the host stream supports runtime reconfiguration.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Configure the command-line parser that defines this tool's invocation contract.
    parser = argparse.ArgumentParser(description="Regenerate both agent skill mirrors.")
    parser.add_argument("--check", action="store_true", help="report staleness, write nothing")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    # Capture the validated invocation arguments that govern this execution.
    args = parser.parse_args(argv)
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = args.root.resolve()

    # Resolve the single authored skill directory from its declared path segments.
    source_dir = root.joinpath(*SOURCE_DIR_PARTS)
    # Resolve Claude and Codex discovery directories in declared host order.
    dest_dirs = list(starmap(root.joinpath, DEST_DIRS_PARTS))
    # Each artifact is one exact canonical-file copy for one host; host then source order is
    # preserved.
    artifacts: list[Artifact] = []
    # Expand each host destination into its ordered canonical-file copy plan.
    for dest_dir in dest_dirs:
        artifacts.extend(build_artifacts(source_dir, dest_dir))
    # Each stale element is one artifact whose destination is missing or byte-different; plan
    # order is preserved.
    stale = [artifact for artifact in artifacts if artifact.is_stale()]
    # Flatten orphan paths in host order, then lexical path order within each host.
    orphans = [
        orphan
        # Inspect host destinations in the same order used to construct mirror artifacts.
        for dest_dir in dest_dirs
        # Preserve the lexical orphan order returned for the current host.
        for orphan in orphaned_files(source_dir, dest_dir)
    ]

    # Check mode reports drift without mutating either discovery tree.
    if args.check:
        # Report stale mirror artifacts in deterministic plan order.
        for artifact in stale:
            print(f"stale mirror file: {artifact.path.relative_to(root).as_posix()}")
        # Report orphaned mirror paths in deterministic host/path order.
        for orphan in orphans:
            print(f"orphaned mirror file: {orphan.relative_to(root).as_posix()}")
        # Combine both drift classes into the command's binary check verdict.
        total = len(stale) + len(orphans)
        # Render the non-empty drift count or the stable clean-state phrase.
        verdict = f"{total} stale file(s)." if total else "up to date."
        print(f"{_CHECK_BANNER}: {verdict}")
        # Return the aggregate process status to the command-line boundary.
        return 1 if total else 0

    # Publish every canonical artifact in deterministic host/source order.
    for artifact in artifacts:
        # Create or replace the current mirror file through its encapsulated write contract.
        artifact.write()
    # Remove obsolete generated files only after all current artifacts have been published.
    for orphan in orphans:
        # Delete the current orphan so hosts cannot discover retired skill content.
        orphan.unlink()
    print(
        f"wrote {len(artifacts)} mirrored file(s) across {len(dest_dirs)} agent roots; "
        f"{len(stale)} were stale, {len(orphans)} orphan(s) removed."
    )
    # Return the aggregate process status to the command-line boundary.
    return 0


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    sys.exit(main())
