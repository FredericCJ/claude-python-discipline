"""Install the discipline into a target repository, and detect local drift.

    python tools/vendor.py install ../some-repo
    python tools/vendor.py check   ../some-repo

Layout in the target::

    .agent/
      discipline/   upstream-owned, replaced wholesale on update
      enforce/      upstream-owned
      tools/        upstream-owned, the navigator and the learning CLI
      skills/       upstream-owned, the shared Claude Code and Codex skill source
      learning/     PROJECT-OWNED, created once and never overwritten
      overrides/    PROJECT-OWNED, local waivers
      MANIFEST.json content hashes of everything upstream-owned

The split is the point. An update replaces the upstream half and cannot touch
what the project accumulated, and `check` reports any upstream file edited in
place -- a local edit to a read-only file is a fork nobody declared, and the
next update would silently discard it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from discipline_core import REPO_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

## The published release this corpus ships as. The manifest's content hash answers
## "is this byte-for-byte the same corpus"; it is not something a reader recognises
## in a managed block, so the release name travels beside it. This constant lives
## under `tools`, which is hashed, so bumping it moves the content hash too -- the
## two can never disagree about which corpus is installed.
RELEASE: Final = "v4.0.0"

## Copied on every install and replaced wholesale. Nothing here is project-owned.
UPSTREAM: Final[tuple[str, ...]] = ("discipline", "enforce", "tools", "skills")

## Root-level files copied alongside the upstream directories. INTEGRATION.md is
## what an agent reads when told to wire the discipline into a repository;
## requirements.txt names the two packages a vendored `.agent/` needs, which the
## adopter previously had to discover from an ImportError.
UPSTREAM_FILES: Final[tuple[str, ...]] = ("INTEGRATION.md", "requirements.txt")

## Created once if absent, then never touched again.
PROJECT_OWNED: Final[tuple[str, ...]] = ("learning", "overrides")

## Seeded into learning/ on first install so the project can record immediately.
LEARNING_SEED: Final[tuple[str, ...]] = ("schema.sql", "config.toml")

## Build products and live databases. Hashing them would make the version stamp
## depend on whether anything had been run in the checkout.
SKIP_SUFFIXES: Final = (".pyc", ".db", ".db-wal", ".db-shm")

## Caches, excluded whole so their contents need no rule of their own. A tool
## writes its cache beside the configuration it resolved, so any of these can
## appear inside an upstream directory; hashing one would make the version stamp
## depend on what had been run in the checkout (DEP-008).
SKIP_DIRS: Final = frozenset({
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".hypothesis",
    ".mypy_cache",
    ".import_linter_cache",
})


@dataclass(frozen=True, slots=True)
class Plan:
    """What an install would do, so `check` and `install` cannot disagree."""

    ## The upstream checkout material is copied from.
    source: Path
    ## The repository being vendored into; nothing outside its `.agent/` is touched.
    target: Path

    @property
    def agent_dir(self) -> Path:
        """Where both halves live inside the target.

        @return the `.agent/` directory, which need not exist yet
        """
        return self.target / ".agent"

    @property
    def manifest(self) -> Path:
        """Where the content hashes are recorded.

        Its absence is how `check` knows a target was never vendored at all.

        @return the manifest's path, which need not exist yet
        """
        return self.agent_dir / "MANIFEST.json"


def iter_upstream(source: Path) -> Iterator[Path]:
    """Every upstream-owned file, in stable order.

    The order is fixed so the manifest is written identically twice over the
    same tree: its keys are serialized in insertion order, not sorted. The
    version stamp is order-independent by construction, but it does depend on
    *which* files appear, which is why caches and build products are excluded.

    @param source the upstream checkout
    @return each file an install would copy, root-level files first
    """
    for name in UPSTREAM_FILES:
        candidate = source / name
        if candidate.exists():
            yield candidate
    for name in UPSTREAM:
        root = source / name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_dir() or path.suffix in SKIP_SUFFIXES:
                continue
            if SKIP_DIRS & set(path.parts):
                continue
            yield path


def digest(path: Path) -> str:
    """A file's SHA-256, truncated for a manifest people have to read.

    Sixty-four bits is far past sufficient for the one question asked of it --
    has this file been edited in place -- and full hashes make the manifest
    unreadable.

    @param path the file to hash
    @return the leading 16 hex characters of its digest
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def build_manifest(source: Path) -> dict[str, object]:
    """Content hashes of the upstream half, plus a version stamp.

    The version is derived from the content, not a wall clock, so two installs
    of the same corpus produce the same stamp (DEP-008). The release name is
    recorded alongside it and is never what staleness is judged by: a hash
    cannot be claimed, only computed.

    @param source the upstream checkout
    @return the release name, the content stamp, the generating tool, and every
            upstream file's source-relative POSIX path mapped to its digest
    """
    files = {path.relative_to(source).as_posix(): digest(path) for path in iter_upstream(source)}
    combined = hashlib.sha256(
        "".join(f"{k}:{v}" for k, v in sorted(files.items())).encode()
    ).hexdigest()[:12]
    return {
        "release": RELEASE,
        "version": combined,
        "generated_by": "tools/vendor.py",
        "files": files,
    }


def _replace_upstream(plan: Plan) -> None:
    """Repopulate the upstream half wholesale, then copy the root-level files.

    Each upstream directory is deleted before being refilled, so a file removed
    upstream does not survive an update; one missing from the source is left as it
    stands rather than emptied, since an absent source says nothing about what the
    target should hold.

    @param plan where to copy from and to
    """
    for name in UPSTREAM:
        source_dir = plan.source / name
        if not source_dir.exists():
            continue
        target_dir = plan.agent_dir / name
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        for path in iter_upstream(plan.source):
            if not path.is_relative_to(source_dir):
                continue
            destination = plan.agent_dir / path.relative_to(plan.source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)

    plan.agent_dir.mkdir(parents=True, exist_ok=True)
    for name in UPSTREAM_FILES:
        source_file = plan.source / name
        if source_file.exists():
            shutil.copy2(source_file, plan.agent_dir / name)


def _seed_project_half(plan: Plan, *, force: bool) -> list[str]:
    """Create the project-owned directories, and never overwrite what is there.

    Every seed copy is guarded by the destination's absence, so the reachable
    effect of `force` is to restore a seed file the project deleted -- not to
    replace one it edited.

    @param plan where to copy from and to
    @param force re-enter a project directory that already exists
    @return one note per project directory left untouched or seeded
    """
    notes: list[str] = []
    for name in PROJECT_OWNED:
        target_dir = plan.agent_dir / name
        if target_dir.exists() and not force:
            notes.append(f"{name}/ already present and left untouched")
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        if name == "learning":
            for seed in LEARNING_SEED:
                source_file = plan.source / "learning" / seed
                destination = target_dir / seed
                if source_file.exists() and not destination.exists():
                    shutil.copy2(source_file, destination)
            notes.append("learning/ seeded; the ledger starts empty")
    return notes


def install(plan: Plan, *, force: bool = False) -> tuple[int, list[str]]:
    """Copy the upstream half; create the project half only if absent.

    An upstream directory that exists in the source is deleted before being
    repopulated, so a file removed upstream does not survive an update; one
    missing from the source is left as it stands rather than emptied.

    The project half is never destroyed, `force` included. An existing
    `learning/` or `overrides/` is normally skipped whole; `force` re-enters it,
    but every seed copy is still guarded by the destination's absence, so the
    reachable effect of `force` is to restore a seed file the project deleted.
    Nothing there is overwritten or removed by either path.

    @param plan where to copy from and to
    @param force re-run seeding over an existing project half, replacing seed
                 files that have gone missing
    @return how many upstream files the manifest records, and a note for each
            project directory left untouched or seeded
    """
    _replace_upstream(plan)
    notes = _seed_project_half(plan, force=force)

    manifest = build_manifest(plan.source)
    plan.manifest.write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return len(manifest["files"]), notes  # type: ignore[arg-type]


def check(plan: Plan) -> list[str]:
    """Differences between a target's vendored copy and this upstream.

    Reports staleness (a version stamp that is not this corpus's), drift (an
    upstream file edited in place or deleted, either of which the next update
    would silently discard), and a project-owned directory that has vanished.
    A target with no manifest is reported as never vendored, not as in step.

    @param plan the target and the upstream to judge it against
    @return one line per difference; empty when the target is in step
    """
    if not plan.manifest.exists():
        return [f"no manifest at {plan.manifest}; the target has not been vendored"]
    recorded = json.loads(plan.manifest.read_text(encoding="utf-8"))
    current = build_manifest(plan.source)
    problems: list[str] = []

    if recorded.get("version") != current["version"]:
        problems.append(
            f"vendored version {recorded.get('version')} != upstream {current['version']}"
        )

    for relative, expected in sorted(recorded.get("files", {}).items()):
        installed = plan.agent_dir / relative
        if not installed.exists():
            problems.append(f"missing: {relative}")
        elif digest(installed) != expected:
            problems.append(f"locally modified: {relative}")

    problems.extend(
        f"project-owned {name}/ is missing; re-run install"
        for name in PROJECT_OWNED
        if not (plan.agent_dir / name).exists()
    )
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """Install the discipline into a repository, or report how far it has drifted.

    @param argv command-line arguments, defaulting to `sys.argv`
    @return 0 when the install succeeded or the target is in step, 1 when `check`
            found any difference
    """
    # The console encoding is not ours to choose, and a tool that dies on one is
    # worse than one that renders a character imperfectly.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Vendor the discipline into a repository.")
    parser.add_argument("command", choices=("install", "check"))
    parser.add_argument("target", type=Path)
    parser.add_argument("--source", type=Path, default=REPO_ROOT)
    # This help text overstates what the flag does: `install` never overwrites or
    # deletes anything under learning/ or overrides/, with or without --force.
    # See install() for what actually happens. Correcting the string is a
    # behaviour change and belongs to whoever owns the intended semantics.
    parser.add_argument(
        "--force", action="store_true", help="also reset the project-owned half (destructive)"
    )
    args = parser.parse_args(argv)

    plan = Plan(args.source.resolve(), args.target.resolve())
    if args.command == "install":
        count, notes = install(plan, force=args.force)
        print(f"installed {count} upstream file(s) into {plan.agent_dir}")
        for note in notes:
            print(f"  {note}")
        # Copying the files does not announce them: nothing under .agent/ is loaded
        # by an agent session on its own. Integration is the step that puts a
        # pointer in CLAUDE.md, AGENTS.md and the permission settings.
        print("\nThe discipline is present but not yet announced. Next:")
        print(f"  python {plan.agent_dir.name}/tools/integrate.py --dry-run")
        print(f"  python {plan.agent_dir.name}/tools/integrate.py")
        print(f"See {plan.agent_dir.name}/INTEGRATION.md for what that changes.")
        return 0

    problems = check(plan)
    for problem in problems:
        print(problem)
    print(f"\n{len(problems)} difference(s)." if problems else "\nin step with upstream.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
