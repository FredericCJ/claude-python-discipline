"""Install the discipline into a target repository, and detect local drift.

    python tools/vendor.py install ../some-repo
    python tools/vendor.py check   ../some-repo

Layout in the target::

    .agent/
      discipline/   upstream-owned, replaced wholesale on update
      enforce/      upstream-owned
      tools/        upstream-owned, the navigator and the learning CLI
      skills/       upstream-owned, the shared Claude Code and Codex skill source
      dev/          upstream-owned, the Windows and Linux development legs
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
import io
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from discipline_core import REPO_ROOT

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

## The published release this corpus ships as. The manifest's content hash answers
## "is this byte-for-byte the same corpus"; it is not something a reader recognises
## in a managed block, so the release name travels beside it. This constant lives
## under `tools`, which is hashed, so bumping it moves the content hash too -- the
## two can never disagree about which corpus is installed.
RELEASE: Final = "v5.0.0"

## Copied on every install and replaced wholesale. Nothing here is project-owned.
## Each element is one upstream-owned directory name; tuple order fixes copy and manifest
## traversal order.
UPSTREAM: Final[tuple[str, ...]] = (
    "discipline", "enforce", "tools", "skills", "dev",
)

## Root-level files copied alongside the upstream directories. INTEGRATION.md is
## what an agent reads when told to wire the discipline into a repository;
## requirements.txt names the Python verifier set a vendored `.agent/` needs;
## environment.yml constructs both development legs; and .dockerignore confines
## the Linux image build context to declared inputs.
## Each element is one upstream-owned root-file name; declaration order is preserved.
UPSTREAM_FILES: Final[tuple[str, ...]] = (
    "INTEGRATION.md", "requirements.txt", "environment.yml", ".dockerignore",
)

## Created once if absent, then never touched again.
## Each element is one project-owned directory name; declaration order fixes seed reporting.
PROJECT_OWNED: Final[tuple[str, ...]] = ("learning", "overrides")

## Seeded into learning/ on first install so the project can record immediately.
## Each element is one learning seed filename copied in declaration order when absent.
LEARNING_SEED: Final[tuple[str, ...]] = ("schema.sql", "config.toml")

## Build products and live databases. Hashing them would make the version stamp
## depend on whether anything had been run in the checkout.
## Each element is one excluded generated-file suffix; membership matters and tuple order is
## deliberately irrelevant.
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
        # Return the `.agent/` directory, which need not exist yet to the caller.
        return self.target / ".agent"

    @property
    def manifest(self) -> Path:
        """Where the content hashes are recorded.

        Its absence is how `check` knows a target was never vendored at all.

        @return the manifest's path, which need not exist yet
        """
        # Return the manifest's path, which need not exist yet to the caller.
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
    # Yield declared root-level upstream files before directory contents.
    for name in UPSTREAM_FILES:
        # Resolve the current root-file name against the upstream checkout.
        candidate = source / name
        # Include optional root files only when the checkout supplies them.
        if candidate.exists():
            yield candidate
    # Traverse upstream-owned directories in declaration order after root files.
    for name in UPSTREAM:
        # Resolve the current upstream directory below the selected checkout.
        root = source / name
        # Skip optional upstream directories absent from this source checkout.
        if not root.exists():
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Traverse the current directory recursively in lexical path order.
        for path in sorted(root.rglob("*")):
            # Exclude directories and generated file suffixes from the manifest stream.
            if path.is_dir() or path.suffix in SKIP_SUFFIXES:
                # Advance after the current candidate has been conclusively excluded.
                continue
            # Exclude any file nested beneath a known cache directory.
            if SKIP_DIRS & set(path.parts):
                # Advance after the current candidate has been conclusively excluded.
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
    # Return the leading 16 hex characters of its digest to the caller.
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
    # Map each source-relative POSIX path key to its truncated digest value; insertion order
    # preserves deterministic upstream traversal.
    files = {path.relative_to(source).as_posix(): digest(path) for path in iter_upstream(source)}
    # Derive an order-independent corpus stamp from lexically sorted path/digest pairs.
    combined = hashlib.sha256(
        # Serialize each path key and digest value in lexical key order before hashing.
        "".join(f"{k}:{v}" for k, v in sorted(files.items())).encode()
    ).hexdigest()[:12]
    # Return the release name, the content stamp, the generating tool, and every to the caller.
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

    @par Effects
    For every source-present upstream directory, removes the prior vendored tree,
    recreates it, copies governed files, then replaces source-present root files.
    """
    # Replace upstream-owned directories in declared order.
    for name in UPSTREAM:
        # Resolve the current directory in the upstream checkout.
        source_dir = plan.source / name
        # Leave the target untouched when the source checkout omits this directory.
        if not source_dir.exists():
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Resolve the corresponding vendored directory under `.agent/`.
        target_dir = plan.agent_dir / name
        # Remove the old upstream-owned tree so retired files cannot survive updates.
        if target_dir.exists():
            shutil.rmtree(target_dir)
        # Recreate the empty upstream directory before copying current files.
        target_dir.mkdir(parents=True, exist_ok=True)
        # Filter the stable global upstream stream to files below this source directory.
        for path in iter_upstream(plan.source):
            # Ignore root files and files belonging to the other upstream directories.
            if not path.is_relative_to(source_dir):
                # Advance after the current candidate has been conclusively excluded.
                continue
            # Preserve the upstream-relative path below the vendored `.agent/` root.
            destination = plan.agent_dir / path.relative_to(plan.source)
            # Create the destination parent before preserving source metadata and bytes.
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)

    # Ensure `.agent/` exists before copying independently owned root files.
    plan.agent_dir.mkdir(parents=True, exist_ok=True)
    # Copy declared root files in stable declaration order when present upstream.
    for name in UPSTREAM_FILES:
        # Resolve the current root-level source file.
        source_file = plan.source / name
        # Replace the vendored root file only when the source checkout supplies it.
        if source_file.exists():
            shutil.copy2(source_file, plan.agent_dir / name)


def _seed_project_half(plan: Plan, *, force: bool) -> list[str]:
    """Create the project-owned directories, and never overwrite what is there.

    Every seed copy is guarded by the destination's absence, so the reachable
    effect of `force` is to restore a seed file the project deleted -- not to
    replace one it edited.

    @param plan where to copy from and to
    @param force re-enter a project directory that already exists
        True enables force; false selects its disabled alternative.
    @return one note per project directory left untouched or seeded

    @par Effects
    Creates missing project-owned directories and absent learning seed files;
    never replaces or removes project-owned content.
    """
    # Each notes element is one human status string for a skipped or seeded project directory;
    # declaration order is preserved.
    notes: list[str] = []
    # Visit project-owned directories in declared reporting order.
    for name in PROJECT_OWNED:
        # Resolve the current project-owned directory below `.agent/`.
        target_dir = plan.agent_dir / name
        # Leave an existing directory untouched unless the caller requested missing-seed repair.
        if target_dir.exists() and not force:
            notes.append(f"{name}/ already present and left untouched")
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Create the project directory if absent without changing existing contents.
        target_dir.mkdir(parents=True, exist_ok=True)
        # Only the learning directory receives canonical seed files.
        if name == "learning":
            # Consider learning seeds in declared copy order.
            for seed in LEARNING_SEED:
                # Resolve the seed in the upstream learning template.
                source_file = plan.source / "learning" / seed
                # Resolve the matching project-owned destination filename.
                destination = target_dir / seed
                # Copy only source-present seeds that the project does not already own.
                if source_file.exists() and not destination.exists():
                    shutil.copy2(source_file, destination)
            notes.append("learning/ seeded; the ledger starts empty")
    # Return one note per project directory left untouched or seeded to the caller.
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
        True enables force; false selects its disabled alternative.
    @return how many upstream files the manifest records, and a note for each
            project directory left untouched or seeded

    @par Effects
    Replaces the upstream-owned half, creates missing project-owned scaffolding,
    then replaces the manifest; never overwrites project-owned files.
    """
    _replace_upstream(plan)
    # Seed only missing project-owned scaffolding after upstream replacement completes.
    notes = _seed_project_half(plan, force=force)

    # Build manifest field-name keys and values from the complete source corpus; top-level key
    # order is preserved for stable serialization.
    manifest = build_manifest(plan.source)
    # Publish the manifest last so it describes the completed installed state.
    plan.manifest.write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    # Return how many upstream files the manifest records, and a note for each to the caller.
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
    # A missing manifest proves no comparable vendored state exists.
    if not plan.manifest.exists():
        # Return one line per difference; empty when the target is in step to the caller.
        return [f"no manifest at {plan.manifest}; the target has not been vendored"]
    # Decode the target's recorded manifest field names and values.
    recorded = json.loads(plan.manifest.read_text(encoding="utf-8"))
    # Recompute the current upstream manifest without trusting its release label.
    current = build_manifest(plan.source)
    # Each problems element is one human difference string; version, file, then project-scaffold
    # order is preserved.
    problems: list[str] = []

    # Report corpus-stamp drift before per-file target drift.
    if recorded.get("version") != current["version"]:
        problems.append(
            f"vendored version {recorded.get('version')} != upstream {current['version']}"
        )

    # Verify recorded path/digest pairs in lexical repository-path order.
    for relative, expected in sorted(recorded.get("files", {}).items()):
        # Resolve the recorded relative path below the target's `.agent/` root.
        installed = plan.agent_dir / relative
        # Report a recorded upstream file that disappeared from the target.
        if not installed.exists():
            problems.append(f"missing: {relative}")
        # Report in-place target edits whose bytes no longer match the recorded digest.
        elif digest(installed) != expected:
            problems.append(f"locally modified: {relative}")

    # Check each project-owned directory name and report absent scaffolding.
    problems.extend(
        f"project-owned {name}/ is missing; re-run install"
        for name in PROJECT_OWNED
        if not (plan.agent_dir / name).exists()
    )
    # Return one line per difference; empty when the target is in step to the caller.
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """Install the discipline into a repository, or report how far it has drifted.

    @param argv command-line arguments, defaulting to `sys.argv`
    @return 0 when the install succeeded or the target is in step, 1 when `check`
            found any difference
    """
    # The console encoding is not ours to choose, and a tool that dies on one is
    # worse than one that renders a character imperfectly.
    if isinstance(sys.stdout, io.TextIOWrapper):
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

    # Freeze resolved source and target roots into one shared install/check plan.
    plan = Plan(args.source.resolve(), args.target.resolve())
    # Install mode performs the copy and reports project-owned seeding decisions.
    if args.command == "install":
        # Preserve the observed item count used by the non-vacuity verdict.
        count, notes = install(plan, force=args.force)
        print(f"installed {count} upstream file(s) into {plan.agent_dir}")
        # Print project-half status notes in declared directory order.
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

    # Compare the existing target against the selected upstream source.
    problems = check(plan)
    # Print differences in the stable order established by `check`.
    for problem in problems:
        print(problem)
    print(f"\n{len(problems)} difference(s)." if problems else "\nin step with upstream.")
    # Return the aggregate process status to the command-line boundary.
    return 1 if problems else 0


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    sys.exit(main())
