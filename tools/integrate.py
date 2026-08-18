"""Announce a vendored discipline to a repository's top-level agent configuration.

    python .agent/tools/integrate.py --dry-run     # what would change, and why
    python .agent/tools/integrate.py               # apply it
    python .agent/tools/integrate.py --check       # exit non-zero if absent or stale
    python .agent/tools/integrate.py --remove      # take it back out cleanly

Vendoring puts the discipline in `.agent/`. Nothing there is loaded by an agent
session on its own: what an agent reads first is `CLAUDE.md`, `AGENTS.md` and the
permission settings. This writes a **managed block** into those, so the discipline
is announced rather than merely present.

Two situations, one mechanism:

* **Greenfield** -- the file does not exist. A minimal file is created carrying the
  block and nothing else, because the rest of that file is the project's to write.
* **Existing configuration** -- the file exists. The block is inserted, or an
  earlier one replaced, and **every byte outside the markers is preserved**.

Structured as plan-then-apply (EFCT-005, EFCT-006) because it edits files the
project owns. `--dry-run` truncates the same pipeline rather than predicting what
a different code path would do, so what it shows is what runs.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final

## Opens the managed region. The version lets `--check` see a stale block.
BEGIN: Final = "<!-- BEGIN AGENT DISCIPLINE"
## Closes the managed region.
END: Final = "<!-- END AGENT DISCIPLINE -->"
## Matches a whole managed region, however old, so it can be replaced wholesale.
BLOCK_RE: Final = re.compile(
    re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.DOTALL
)

## Markdown files that an agent session reads without being told to.
MARKDOWN_TARGETS: Final[tuple[str, ...]] = ("CLAUDE.md", "AGENTS.md")

## Where Claude Code keeps project-shared settings.
SETTINGS_PATH: Final = ".claude/settings.json"

## Narrow, read-or-verify invocations the discipline's own tooling needs. Nothing
## here writes to the repository except the learning ledger, which is the point.
PERMISSIONS: Final[tuple[str, ...]] = (
    "Bash(python .agent/tools/nav.py:*)",
    "Bash(python .agent/tools/learn.py:*)",
    "Bash(python .agent/tools/validate.py:*)",
    "Bash(python -m checks.:*)",
    "Bash(ruff check:*)",
    "Bash(mypy:*)",
    "Bash(pytest:*)",
    "Bash(lint-imports:*)",
    "Bash(doxygen:*)",
)

## Introduces the ignore entries, and is removed together with them.
GITIGNORE_HEADER: Final = "# Derived by the vendored discipline; the ledger is the record."

## Paths the discipline derives and must not have committed.
GITIGNORE_ENTRIES: Final[tuple[str, ...]] = (
    ".agent/learning/learning.db",
    ".agent/learning/learning.db-wal",
    ".agent/learning/learning.db-shm",
    "build/doc/",
)


class Kind(StrEnum):
    """What an action does to its target."""

    CREATE = "create"
    INSERT = "insert"
    REPLACE = "replace"
    MERGE = "merge"
    REMOVE = "remove"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class Action:
    """One file change, computed before anything is written."""

    ## What will happen to the file.
    kind: Kind
    ## The file, relative to the repository root.
    path: Path
    ## Contents before, empty when the file does not exist.
    before: str
    ## Contents after; equal to `before` when the action is a skip.
    after: str
    ## Why this action and not another, shown in the plan.
    reason: str

    @property
    def changes(self) -> bool:
        """Whether applying this action would alter the file.

        @return True when before and after differ
        """
        return self.before != self.after

    def diff(self, root: Path) -> str:
        """A unified diff of the change, for the dry run.

        @param root the repository root, for display paths
        @return the diff text, empty when nothing changes
        """
        if not self.changes:
            return ""
        name = self.path.relative_to(root).as_posix()
        return "".join(
            difflib.unified_diff(
                self.before.splitlines(keepends=True),
                self.after.splitlines(keepends=True),
                fromfile=f"a/{name}", tofile=f"b/{name}", n=2,
            )
        )


@dataclass(slots=True)
class Plan:
    """Every action, plus anything the caller should know before applying."""

    ## The actions, in the order they will be applied.
    actions: list[Action] = field(default_factory=list)
    ## Advisory notes; none of these block an apply.
    warnings: list[str] = field(default_factory=list)

    @property
    def changing(self) -> list[Action]:
        """Actions that would actually alter a file.

        @return the subset whose before and after differ
        """
        return [a for a in self.actions if a.changes]


# ------------------------------------------------------------------ the block


def render_block(version: str, agent_dir: str) -> str:
    """The managed block, as it will appear in every target.

    Kept deliberately short: it is loaded into every session, so it points at the
    kernel rather than restating it.

    @param version the vendored discipline's content hash, so staleness is visible
    @param agent_dir where the discipline was vendored, relative to the root
    @return the block text, markers included
    """
    return f"""{BEGIN} {version} -- managed by {agent_dir}/tools/integrate.py; \
edits inside this block are overwritten -->
## Engineering discipline

This repository vendors a Python engineering discipline at `{agent_dir}/discipline/`.
**Read `{agent_dir}/discipline/KERNEL.md` before writing Python here.** It is about
1,800 tokens and carries the thesis, the always-apply invariants and a router to the
rest; everything else is loaded on demand.

The thesis: *a failure must be machine-diagnosable and machine-repairable* — an agent
meeting a defect should be able to name what broke, where, in which layer, against which
contract, from the program's own output. Deep error traceability and least coupling exist
to serve that. Anything mechanically verifiable shall be mechanically verified.

Do not read the modules speculatively. Ask instead:

```bash
python {agent_dir}/tools/nav.py context --file <path> --error "<message>"
python {agent_dir}/tools/nav.py applies <path>          # which rules govern this file
python {agent_dir}/tools/learn.py retrieve --file <path> --error "<message>"
```

Before reporting done, record what this session learned about this repository — or that
it learned nothing:

```bash
python {agent_dir}/tools/learn.py record --kind diagnostic \\
    --claim "..." --action "..." --trigger "error:..." --link RULE-ID
```

Every element of the code carries a documentation comment in Doxygen form; see
`{agent_dir}/discipline/law/DOC.md`. The gate is `ruff check`, `mypy`, `pytest`,
`lint-imports` and the checks under `{agent_dir}/enforce/`.

Rule ids such as `ARCH-002` and `DIAG-005` are stable — cite them in review comments and
commit messages.
{END}
"""


def read_version(root: Path, agent_dir: str) -> str:
    """The vendored discipline's version, from its manifest.

    @param root the repository root
    @param agent_dir where the discipline was vendored
    @return the recorded version, or "unversioned" when there is no manifest
    """
    manifest = root / agent_dir / "MANIFEST.json"
    if not manifest.exists():
        return "unversioned"
    try:
        return str(json.loads(manifest.read_text(encoding="utf-8")).get("version", "?"))
    except (json.JSONDecodeError, OSError):
        return "unreadable"


# ----------------------------------------------------------------- the plan


def build_plan(root: Path, agent_dir: str, *, remove: bool = False,
               targets: Sequence[str] = MARKDOWN_TARGETS) -> Plan:
    """Compute every change without making any.

    @param root the repository root
    @param agent_dir where the discipline was vendored, relative to the root
    @param remove when True, plan the block's removal instead of its installation
    @param targets which markdown files to manage
    @return the plan
    """
    plan = Plan()
    version = read_version(root, agent_dir)
    block = render_block(version, agent_dir)

    if not (root / agent_dir / "discipline").exists():
        plan.warnings.append(
            f"no discipline found at {agent_dir}/discipline -- run vendor.py install first"
        )

    for name in targets:
        plan.actions.append(_markdown_action(root / name, block, root, remove=remove))
    plan.actions.append(_settings_action(root / SETTINGS_PATH, remove=remove))
    plan.actions.append(_gitignore_action(root / ".gitignore", remove=remove))

    if not remove and not _is_git_repository(root):
        plan.warnings.append(
            "this is not a git repository, so there is no undo -- review the dry run first"
        )
    return plan


def _markdown_action(path: Path, block: str, root: Path, *, remove: bool) -> Action:
    """Plan one markdown target.

    @param path the file
    @param block the managed block to install
    @param root the repository root
    @param remove whether to remove rather than install
    @return the action for this file
    """
    exists = path.exists()
    before = path.read_text(encoding="utf-8") if exists else ""
    has_block = BLOCK_RE.search(before) is not None

    if remove:
        if not has_block:
            return Action(Kind.SKIP, path, before, before, "no managed block present")
        after = BLOCK_RE.sub("", before).rstrip() + "\n"
        return Action(Kind.REMOVE, path, before, after, "managed block removed")

    if not exists:
        header = f"# {root.name}\n\n"
        return Action(
            Kind.CREATE, path, "", header + block,
            "file absent; creating a minimal one -- the rest is the project's to write",
        )

    if has_block:
        after = BLOCK_RE.sub(lambda _: block, before, count=1)
        reason = ("managed block already current" if after == before
                  else "managed block replaced; everything outside it is untouched")
        kind = Kind.SKIP if after == before else Kind.REPLACE
        return Action(kind, path, before, after, reason)

    separator = "" if before.endswith("\n\n") else ("\n" if before.endswith("\n") else "\n\n")
    return Action(
        Kind.INSERT, path, before, before + separator + block,
        "appended; existing content is preserved byte for byte",
    )


def _settings_action(path: Path, *, remove: bool) -> Action:
    """Plan the permission settings, merging rather than replacing.

    The project may have its own entries and they are never removed: this adds
    only the narrow invocations the discipline's tooling needs.

    @param path the settings file
    @param remove whether to remove the discipline's entries
    @return the action for the settings file
    """
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        settings = json.loads(before) if before.strip() else {}
    except json.JSONDecodeError:
        return Action(Kind.SKIP, path, before, before,
                      "settings file is not valid JSON; left alone rather than guessed at")
    if not isinstance(settings, dict):
        return Action(Kind.SKIP, path, before, before, "settings file is not an object")

    permissions = dict(settings.get("permissions") or {})
    allow = list(permissions.get("allow") or [])

    if remove:
        kept = [entry for entry in allow if entry not in PERMISSIONS]
        if kept == allow:
            return Action(Kind.SKIP, path, before, before, "no discipline entries present")
        permissions["allow"] = kept
        settings["permissions"] = permissions
        return Action(Kind.MERGE, path, before, _dump(settings),
                      f"removed {len(allow) - len(kept)} permission entr(ies)")

    missing = [entry for entry in PERMISSIONS if entry not in allow]
    if not missing:
        return Action(Kind.SKIP, path, before, before, "all permissions already allowed")
    permissions["allow"] = [*allow, *missing]
    settings["permissions"] = permissions
    return Action(
        Kind.MERGE if before else Kind.CREATE, path, before, _dump(settings),
        f"adding {len(missing)} permission entr(ies); existing entries kept",
    )


def _gitignore_action(path: Path, *, remove: bool) -> Action:
    """Plan the ignore entries for the discipline's derived files.

    @param path the .gitignore
    @param remove whether to remove the entries
    @return the action for the ignore file
    """
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    present = set(before.splitlines())

    if remove:
        # Take the header with the entries. Leaving it behind means removal does
        # not restore the file, and the next reader inherits a comment about
        # something that is no longer there.
        kept = [
            line for line in before.splitlines()
            if line not in GITIGNORE_ENTRIES and line != GITIGNORE_HEADER
        ]
        while kept and not kept[-1].strip():
            kept.pop()
        after = "\n".join(kept) + "\n" if kept else ""
        if after == before:
            return Action(Kind.SKIP, path, before, before, "no discipline entries present")
        return Action(Kind.REMOVE, path, before, after, "removed discipline entries")

    missing = [entry for entry in GITIGNORE_ENTRIES if entry not in present]
    if not missing:
        return Action(Kind.SKIP, path, before, before, "already ignored")
    header = f"\n{GITIGNORE_HEADER}\n"
    prefix = before if not before or before.endswith("\n") else before + "\n"
    after = prefix + header + "\n".join(missing) + "\n"
    return Action(Kind.MERGE if before else Kind.CREATE, path, before, after,
                  f"ignoring {len(missing)} derived path(s)")


def _dump(settings: dict[str, object]) -> str:
    """Serialize settings the way an editor would leave them.

    @param settings the settings mapping
    @return pretty-printed JSON with a trailing newline
    """
    return json.dumps(settings, indent=2, ensure_ascii=False) + "\n"


def _is_git_repository(root: Path) -> bool:
    """Whether `root` is inside a git working tree.

    @param root the directory to test
    @return True when git reports a working tree
    """
    try:
        finished = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return finished.returncode == 0 and finished.stdout.strip() == "true"


# ---------------------------------------------------------------- the apply


def apply(plan: Plan) -> list[Action]:
    """Write every changing action. The plan is not recomputed here.

    @param plan the plan to apply
    @return the actions that were written
    """
    written: list[Action] = []
    for action in plan.changing:
        action.path.parent.mkdir(parents=True, exist_ok=True)
        action.path.write_text(action.after, encoding="utf-8")
        written.append(action)
    return written


def render_plan(plan: Plan, root: Path, *, show_diff: bool) -> Iterator[str]:
    """Format a plan for a reader.

    @param plan the plan
    @param root the repository root, for display paths
    @param show_diff whether to include unified diffs
    @return the lines to print
    """
    for action in plan.actions:
        name = action.path.relative_to(root).as_posix()
        mark = " " if action.kind is Kind.SKIP else "*"
        yield f" {mark} {action.kind.value:<8} {name:<26} {action.reason}"
        if show_diff and action.changes:
            yield from ("     " + line.rstrip("\n") for line in action.diff(root).splitlines())
    for warning in plan.warnings:
        yield f"\n   warning: {warning}"


# ---------------------------------------------------------------------- main


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    @param argv command-line arguments, defaulting to `sys.argv`
    @return the process exit status
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Announce a vendored discipline to a repository's agent configuration.",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(),
                        help="repository root (default: the working directory)")
    parser.add_argument("--agent-dir", default=".agent",
                        help="where the discipline was vendored")
    parser.add_argument("--dry-run", action="store_true", help="show the plan, write nothing")
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if the block is missing or stale")
    parser.add_argument("--remove", action="store_true", help="take the block back out")
    parser.add_argument("--only", action="append", choices=list(MARKDOWN_TARGETS),
                        help="restrict to one markdown target; repeatable")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    plan = build_plan(root, args.agent_dir, remove=args.remove,
                      targets=args.only or MARKDOWN_TARGETS)

    if args.check:
        stale = plan.changing
        for line in render_plan(plan, root, show_diff=False):
            print(line)
        print(f"\n{len(stale)} file(s) out of step." if stale
              else "\nagent configuration is in step with the discipline.")
        return 1 if stale else 0

    if args.dry_run:
        print("PLAN (nothing written)\n")
        for line in render_plan(plan, root, show_diff=True):
            print(line)
        print(f"\n{len(plan.changing)} file(s) would change. Re-run without --dry-run to apply.")
        return 0

    for line in render_plan(plan, root, show_diff=False):
        print(line)
    written = apply(plan)
    verb = "removed from" if args.remove else "integrated into"
    print(f"\ndiscipline {verb} {len(written)} file(s).")
    if not args.remove and written:
        print("Start a fresh agent session so the new configuration is loaded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
