"""Regenerate the skill's reference mirror from `discipline/`.

    python tools/build_skill_mirror.py [--check] [--root PATH]

`.claude/skills/python-discipline/references/` is a byte-for-byte copy of
`discipline/`, read by an agent session that has loaded the `python-discipline`
skill instead of the corpus directly. Until this tool existed the copy was made
by hand and drifted -- a stale conflict-id vocabulary in one file, a stale token
count and a missing cross-reference in another. This tool removes the hand step:
the mirror is now exactly what a walk of `discipline/` produces, and nothing
under `references/` may be edited directly.

`SKILL.md` itself -- the skill's frontmatter and routing prose, one directory up
from `references/` -- is hand-authored, adapted from the corpus rather than
copied from it, and this tool never touches it.

``--check`` writes nothing and exits non-zero if the mirror is stale or carries
a file the corpus no longer has, which is the form to run in CI.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

## Anchor for the default root, derived from this file rather than the working
## directory, so the tool behaves the same however it was invoked.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent
## The corpus this tool mirrors from. Never written to.
SOURCE_DIR_NAME: Final = "discipline"
## Where the mirror lives, relative to the repository root.
DEST_DIR_PARTS: Final = (".claude", "skills", "python-discipline", "references")

## Heads the console summary so a human running this by hand knows the direction
## of the copy without reading the source.
_CHECK_BANNER: Final = "skill mirror (discipline/ -> .claude/skills/python-discipline/references/)"


@dataclass(frozen=True, slots=True)
class Artifact:
    """One mirrored file and the bytes it should contain.

    Mirrors the `Artifact` shape in `tools/build_index.py` deliberately: the two
    tools follow the same generated-artifact shape, so a reader who knows one
    knows the other. The two names are kept out of a single code span on
    purpose -- Doxygen 1.10.0 reads `path::Name` as an explicit link request and
    fails the documentation build when it cannot resolve it.
    """

    ## Where the file belongs in the mirror, absolute.
    path: Path
    ## Its full intended contents, exactly as read from the source file.
    text: str

    def is_stale(self) -> bool:
        """Whether what is on disk differs from what was just read from the source.

        A file that does not exist counts as stale, so a fresh checkout reports
        work to do rather than agreement.

        @return True when writing would change the tree
        """
        if not self.path.exists():
            return True
        return self.path.read_text(encoding="utf-8") != self.text

    def write(self) -> None:
        """Put the text on disk, creating any parent directory it needs.

        Unconditional. Staleness is the caller's question; this leaves the file
        in the intended state either way.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.text, encoding="utf-8")


def source_files(source_dir: Path) -> list[Path]:
    """Every file under the corpus, in a stable order.

    @param source_dir `discipline/`, absolute
    @return the corpus's files, sorted so the mirror's write order is deterministic
    """
    return sorted(p for p in source_dir.rglob("*") if p.is_file())


def build_artifacts(source_dir: Path, dest_dir: Path) -> list[Artifact]:
    """One `Artifact` per corpus file, addressed at its mirrored path.

    The mirror's shape is the corpus's shape: every relative path under
    `discipline/` reappears, unchanged, under `references/`. Nothing is
    filtered, renamed or rewritten -- a selective mirror is exactly the kind of
    human judgement call that drifts, which is what a hand-copied duplicate
    already proved.

    @param source_dir `discipline/`, absolute
    @param dest_dir the mirror root, absolute
    @return one artifact per corpus file
    """
    return [
        Artifact(dest_dir / path.relative_to(source_dir), path.read_text(encoding="utf-8"))
        for path in source_files(source_dir)
    ]


def orphaned_files(source_dir: Path, dest_dir: Path) -> list[Path]:
    """Files under the mirror that no longer correspond to anything in the corpus.

    A file removed from `discipline/` must not go on being served from the
    mirror; left alone it would be indistinguishable from a current rule.

    @param source_dir `discipline/`, absolute
    @param dest_dir the mirror root, absolute
    @return mirrored files with no source counterpart, sorted
    """
    if not dest_dir.exists():
        return []
    wanted = {p.relative_to(source_dir) for p in source_files(source_dir)}
    return sorted(
        p for p in dest_dir.rglob("*")
        if p.is_file() and p.relative_to(dest_dir) not in wanted
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Regenerate the mirror, or under `--check` only report staleness.

    @param argv command-line arguments, defaulting to `sys.argv`
    @return 0 on success, 1 when `--check` finds anything out of date
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Regenerate the skill's discipline mirror.")
    parser.add_argument("--check", action="store_true", help="report staleness, write nothing")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    source_dir = root / SOURCE_DIR_NAME
    dest_dir = root.joinpath(*DEST_DIR_PARTS)

    artifacts = build_artifacts(source_dir, dest_dir)
    stale = [a for a in artifacts if a.is_stale()]
    orphans = orphaned_files(source_dir, dest_dir)

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
        f"wrote {len(artifacts)} mirrored file(s); "
        f"{len(stale)} were stale, {len(orphans)} orphan(s) removed."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
