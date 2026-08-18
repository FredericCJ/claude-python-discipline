"""Install the discipline into a target repository, and detect local drift.

    python tools/vendor.py install ../some-repo
    python tools/vendor.py check   ../some-repo

Layout in the target::

    .agent/
      discipline/   upstream-owned, replaced wholesale on update
      enforce/      upstream-owned
      tools/        upstream-owned, the navigator and the learning CLI
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
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from discipline_core import REPO_ROOT

## Copied on every install and replaced wholesale. Nothing here is project-owned.
UPSTREAM: Final[tuple[str, ...]] = ("discipline", "enforce", "tools")

## Root-level files copied alongside the upstream directories. INTEGRATION.md is
## what an agent reads when told to wire the discipline into a repository.
UPSTREAM_FILES: Final[tuple[str, ...]] = ("INTEGRATION.md",)

## Created once if absent, then never touched again.
PROJECT_OWNED: Final[tuple[str, ...]] = ("learning", "overrides")

## Seeded into learning/ on first install so the project can record immediately.
LEARNING_SEED: Final[tuple[str, ...]] = ("schema.sql", "config.toml")

SKIP_SUFFIXES: Final = (".pyc", ".db", ".db-wal", ".db-shm")
SKIP_DIRS: Final = frozenset({"__pycache__", ".pytest_cache", ".hypothesis"})


@dataclass(frozen=True, slots=True)
class Plan:
    """What an install would do, so `check` and `install` cannot disagree."""

    source: Path
    target: Path

    @property
    def agent_dir(self) -> Path:
        return self.target / ".agent"

    @property
    def manifest(self) -> Path:
        return self.agent_dir / "MANIFEST.json"


def iter_upstream(source: Path) -> Iterator[Path]:
    """Every upstream-owned file, in stable order."""
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
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def build_manifest(source: Path) -> dict[str, object]:
    """Content hashes of the upstream half, plus a version stamp.

    The version is derived from the content, not a wall clock, so two installs
    of the same corpus produce the same stamp (DEP-008).
    """
    files = {
        path.relative_to(source).as_posix(): digest(path) for path in iter_upstream(source)
    }
    combined = hashlib.sha256(
        "".join(f"{k}:{v}" for k, v in sorted(files.items())).encode()
    ).hexdigest()[:12]
    return {"version": combined, "generated_by": "tools/vendor.py", "files": files}


def install(plan: Plan, *, force: bool = False) -> tuple[int, list[str]]:
    """Copy the upstream half; create the project half only if absent."""
    notes: list[str] = []
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

    manifest = build_manifest(plan.source)
    plan.manifest.write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return len(manifest["files"]), notes  # type: ignore[arg-type]


def check(plan: Plan) -> list[str]:
    """Differences between a target's vendored copy and this upstream."""
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

    for name in PROJECT_OWNED:
        if not (plan.agent_dir / name).exists():
            problems.append(f"project-owned {name}/ is missing; re-run install")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    # The console encoding is not ours to choose, and a tool that dies on one is
    # worse than one that renders a character imperfectly.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Vendor the discipline into a repository.")
    parser.add_argument("command", choices=("install", "check"))
    parser.add_argument("target", type=Path)
    parser.add_argument("--source", type=Path, default=REPO_ROOT)
    parser.add_argument("--force", action="store_true",
                        help="also reset the project-owned half (destructive)")
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
