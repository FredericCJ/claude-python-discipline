"""Announce a vendored discipline to a repository's top-level agent configuration.

    python .agent/tools/integrate.py --dry-run     # what would change, and why
    python .agent/tools/integrate.py               # apply it
    python .agent/tools/integrate.py --check       # exit non-zero if absent or stale
    python .agent/tools/integrate.py --remove      # take it back out cleanly

Vendoring puts the discipline in `.agent/`. Nothing there is loaded by an agent
session on its own: what an agent reads first is `CLAUDE.md` or `AGENTS.md`, plus
skills below its native discovery root. This writes a **managed block** into both
instruction files and exposes the same vendored skill through `.claude/skills/`
and `.agents/skills/`, so the discipline is announced rather than merely present.

Two situations, one mechanism:

* **Greenfield** -- the file does not exist. A minimal file is created carrying the
  block and nothing else, because the rest of that file is the project's to write.
* **Existing configuration** -- the file exists. The block is inserted, or an
  earlier one replaced, and **every byte outside the markers is preserved** --
  trailing blank lines and CRLF line endings included.

Two properties make that claim true rather than merely intended, and both are
easy to break by accident:

* Host files are read and written with newline translation switched off.
  `Path.read_text` folds CRLF to LF and `Path.write_text` expands LF back to the
  platform separator, so the obvious round trip rewrites every line ending in a
  file the project owns -- silently, and on Windows only.
* The block is rendered with whichever ending already dominates the host file,
  so installing into a CRLF file does not leave it mixed.

What the integrator adds it can take back, and nothing else. An entry the
project already had is identical in value to one the discipline would have
added, so value alone cannot tell them apart. At apply time it therefore records
in `<agent-dir>/integration-record.json` which permission and ignore entries
were genuinely absent beforehand, and which blank space it inserted before each
block; `--remove` takes back only what is recorded there. An install predating
that record removes no permission or ignore entry at all and names what it left
behind, because leftover configuration is recoverable and deleted configuration
is not.

Structured as plan-then-apply (EFCT-005, EFCT-006) because it edits files the
project owns. `--dry-run` truncates the same pipeline rather than predicting what
a different code path would do, so what it shows is what runs.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

## Opens the managed region. The version lets `--check` see a stale block.
BEGIN: Final = "<!-- BEGIN AGENT DISCIPLINE"
## Closes the managed region.
END: Final = "<!-- END AGENT DISCIPLINE -->"
## Matches a whole managed region, however old, so it can be replaced wholesale.
## The trailing group takes the region's own line ending with it, in either form:
## a bare `\n` would leave the CR of a CRLF file stranded on its own line.
BLOCK_RE: Final = re.compile(
    re.escape(BEGIN) + r".*?" + re.escape(END) + r"(?:\r?\n)?", re.DOTALL
)

## Markdown files that an agent session reads without being told to.
MARKDOWN_TARGETS: Final[tuple[str, ...]] = ("CLAUDE.md", "AGENTS.md")

## The one skill source inside the vendored bundle. Both host entry points are
## exact copies of this file and both route back into `.agent/discipline/`.
SKILL_SOURCE_PATH: Final = "skills/python-discipline/SKILL.md"
## Repository-local discovery paths for Claude Code and Codex respectively.
SKILL_TARGETS: Final[tuple[str, ...]] = (
    ".claude/skills/python-discipline/SKILL.md",
    ".agents/skills/python-discipline/SKILL.md",
)

## Where Claude Code keeps project-shared settings.
SETTINGS_PATH: Final = ".claude/settings.json"

## Where the integrator records what it added, inside the vendored directory.
## It sits at the top of `.agent/` and not under `tools/` deliberately:
## `vendor.py` replaces the upstream directories wholesale on an upgrade, so a
## record kept inside one would not survive the next `vendor.py install`.
RECORD_NAME: Final = "integration-record.json"

## The record format's version, so a later shape can be told apart from this one.
RECORD_VERSION: Final = 2

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

    ## The file did not exist; a minimal one is written.
    CREATE = "create"
    ## The file existed with no managed block; the block is appended.
    INSERT = "insert"
    ## An earlier block was found and is swapped for the current one.
    REPLACE = "replace"
    ## Structured content updated entry by entry rather than rewritten.
    MERGE = "merge"
    ## Our contribution is taken back out, leaving the rest.
    REMOVE = "remove"
    ## A whole file created by the discipline is safely deleted.
    DELETE = "delete"
    ## Nothing to do; recorded anyway so the plan accounts for every target.
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
        """Whether applying this action would alter or delete the file.

        @return True when before and after differ or the action is a deletion
        """
        return self.kind is Kind.DELETE or self.before != self.after

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
    ## Conflicts that prevent a complete integration but do not authorise overwriting.
    problems: list[str] = field(default_factory=list)

    @property
    def changing(self) -> list[Action]:
        """Actions that would actually alter a file.

        @return the subset whose before and after differ
        """
        return [a for a in self.actions if a.changes]


# --------------------------------------------------------------- line endings


def read_preserving(path: Path) -> str:
    """Read a file with its line endings left exactly as they are on disk.

    `Path.read_text` opens in universal-newline mode, which turns every CRLF
    into a bare LF. Writing that text back expands each LF to the platform
    separator, so on Windows the obvious round trip rewrites every line ending
    in a file the project owns while reporting that it preserved them. Disabling
    the translation on both sides is what makes the round trip a no-op.

    @param path the file to read
    @return the decoded text, carriage returns included
    """
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def write_preserving(path: Path, text: str) -> None:
    """Write text with no line-ending translation of any kind.

    @param path the file to write, whose parent directory must exist
    @param text exactly the bytes to store, once encoded
    """
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def dominant_newline(text: str) -> str:
    """Decide which line ending a file already uses.

    Ties and empty files go to LF, which is what a file the integrator creates
    itself uses and what the block is authored with.

    @param text the file as it stands
    @return CRLF when carriage returns are in the majority, LF otherwise
    """
    crlf = text.count("\r\n")
    return "\r\n" if crlf > text.count("\n") - crlf else "\n"


def with_newline(text: str, newline: str) -> str:
    """Re-render generated text with a chosen line ending.

    Applied only to text this module produces. Host content is never passed
    through it, because normalising a project's own line endings is precisely
    the damage the rest of this module exists to avoid.

    @param text the generated text, authored with LF
    @param newline the ending to use
    @return the same text with every line ending replaced
    """
    return text.replace("\r\n", "\n").replace("\n", newline)


# ------------------------------------------------------------------ the block


def render_block(version: str, agent_dir: str) -> str:
    """The managed block, as it will appear in every target.

    Kept deliberately short: it is loaded into every session, so it points at the
    kernel rather than restating it.

    @param version the vendored discipline's content hash, so staleness is visible
    @param agent_dir where the discipline was vendored, relative to the root
    @return the block text, markers included, with LF line endings
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

    Two things are being named at once and both belong in the block. The content
    hash is what `--check` compares, and it is the only one that cannot be
    claimed falsely; the release name is what a reader recognises. When the
    manifest carries a release the two are printed together, so a human can see
    which release this is and a tool can still see the exact corpus.

    @param root the repository root
    @param agent_dir where the discipline was vendored
    @return `release (hash)` when a release is recorded, the hash alone when it
            is not, or one of "unversioned" / "unreadable" when the manifest is
            missing or cannot be parsed
    """
    manifest = root / agent_dir / "MANIFEST.json"
    if not manifest.exists():
        return "unversioned"
    try:
        recorded = json.loads(manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "unreadable"
    if not isinstance(recorded, dict):
        return "unreadable"
    stamp = str(recorded.get("version", "?"))
    release = recorded.get("release")
    return f"{release} ({stamp})" if release else stamp


# ----------------------------------------------------------------- the record


def load_record(path: Path) -> dict[str, object] | None:
    """Recover what an earlier apply noted about this repository.

    A record that cannot be read is reported as absent rather than guessed at.
    Both answers lead to the conservative removal path, which is the point: the
    only thing a damaged record could do is authorise deleting something.

    @param path the record file
    @return the parsed record, or None when there is none to trust
    """
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def recorded_entries(record: dict[str, object] | None, key: str) -> tuple[str, ...] | None:
    """One recorded list of entries the discipline added.

    @param record the record as it stands, or None when there is none
    @param key which list to read
    @return the entries, empty when the record carries no such list, and None
            when there is no record at all -- the two must not be confused, since
            one authorises removal of nothing and the other forbids removal
    """
    if record is None:
        return None
    value = record.get(key)
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def recorded_separator(record: dict[str, object] | None, name: str) -> str | None:
    """Look up the blank space an earlier apply inserted before one file's block.

    @param record the record as it stands, or None when there is none
    @param name the markdown target, as it is keyed in the record
    @return the recorded separator, or None when nothing was recorded for it
    """
    markdown = (record or {}).get("markdown")
    if not isinstance(markdown, dict):
        return None
    entry = markdown.get(name)
    if not isinstance(entry, dict):
        return None
    separator = entry.get("separator")
    return separator if isinstance(separator, str) else None


def empty_record() -> dict[str, object]:
    """Build the record as it reads when nothing is installed.

    @return a record claiming no permission, ignore, markdown, or skill contribution
    """
    return {
        "record_version": RECORD_VERSION,
        "permissions_added": [],
        "gitignore_added": [],
        "markdown": {},
        "skills": {},
    }


def _merged(record: dict[str, object] | None, key: str, newly: Sequence[str]) -> list[str]:
    """Everything already recorded, plus what this run is adding for the first time.

    A union rather than a replacement: a re-run after the project deleted one of
    our entries adds that entry again, and must not thereby forget the eight it
    added the first time.

    @param record the record as it stands, or None when there is none
    @param key which list to extend
    @param newly the entries this run found absent and will add
    @return the union, in recorded order first
    """
    kept = list(recorded_entries(record, key) or ())
    return [*kept, *(entry for entry in newly if entry not in kept)]


def _skills_record(record: dict[str, object] | None) -> dict[str, dict[str, object]]:
    """Recover per-path ownership and digests for native skill entry points.

    Invalid entries grant no deletion or replacement authority and are ignored.
    This is the same conservative rule used for a missing record: unexplained
    files belong to the project.

    @param record the install record as it stands, or None
    @return valid path-to-entry mappings, empty when none can be trusted
    """
    raw = (record or {}).get("skills")
    if not isinstance(raw, dict):
        return {}
    return {
        str(path): dict(entry)
        for path, entry in raw.items()
        if isinstance(path, str) and isinstance(entry, dict)
    }


def _content_digest(text: str) -> str:
    """A short digest used to distinguish our skill file from a local edit.

    @param text exact decoded file contents, line endings included
    @return the first 16 hexadecimal characters of its SHA-256
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _skill_ownership(entry: dict[str, object] | None) -> tuple[bool, str | None]:
    """Read the authority an integration-record skill entry grants.

    @param entry one path's record, or None when the path was never recorded
    @return whether this installer created it, and the digest it wrote
    """
    if entry is None:
        return False, None
    digest = entry.get("digest")
    return entry.get("created") is True, digest if isinstance(digest, str) else None


def _install_skill_action(
    path: Path, relative: str, source: str, source_digest: str,
    entry: dict[str, object] | None,
) -> tuple[Action, dict[str, object], str | None]:
    """Plan one native skill install or safe upgrade.

    @param path the host discovery path
    @param relative its repository-relative display and record key
    @param source exact contents of the shared vendored skill
    @param source_digest digest of `source`
    @param entry prior ownership and digest, if recorded
    @return the action, next record entry, and a blocking problem if any
    """
    if path.is_symlink() or (path.exists() and not path.is_file()):
        reason = "a non-regular path already occupies the skill entry point; left untouched"
        action = Action(Kind.SKIP, path, "", "", reason)
        next_entry = dict(entry) if entry is not None else {"created": False, "digest": ""}
        problem = f"cannot install the shared skill at {relative}: {reason}"
        return action, next_entry, problem
    if not path.is_file():
        action = Action(
            Kind.CREATE, path, "", source,
            "creating the native entry point from the shared vendored skill",
        )
        return action, {"created": True, "digest": source_digest}, None

    before = read_preserving(path)
    created, expected = _skill_ownership(entry)
    if before == source:
        action = Action(
            Kind.SKIP, path, before, before,
            "native skill already matches the shared vendored source",
        )
        return action, {"created": created, "digest": source_digest}, None
    if created and expected is not None and _content_digest(before) == expected:
        action = Action(
            Kind.REPLACE, path, before, source,
            "updating the unchanged skill file created by this install",
        )
        return action, {"created": True, "digest": source_digest}, None

    reason = (
        "recorded skill was locally modified; left untouched" if created
        else "an unowned skill already exists at this path; left untouched"
    )
    action = Action(Kind.SKIP, path, before, before, reason)
    next_entry = (dict(entry) if entry is not None else
                  {"created": False, "digest": _content_digest(before)})
    return action, next_entry, f"cannot install the shared skill at {relative}: {reason}"


def _remove_skill_action(
    path: Path, relative: str, entry: dict[str, object] | None,
) -> tuple[Action, list[str]]:
    """Plan removal of one native skill only when its provenance is intact.

    @param path the host discovery path
    @param relative its repository-relative display and record key
    @param entry prior ownership and digest, if recorded
    @return the action and any conservative-removal warning
    """
    if path.is_symlink() or (path.exists() and not path.is_file()):
        action = Action(
            Kind.SKIP, path, "", "",
            "non-regular skill entry point is project-owned; left untouched",
        )
        return action, [f"{relative} is not a regular file and was not removed"]
    if not path.is_file():
        return Action(Kind.SKIP, path, "", "", "skill file absent"), []

    before = read_preserving(path)
    created, expected = _skill_ownership(entry)
    if not created:
        action = Action(
            Kind.SKIP, path, before, before,
            "skill file was not created by this install; left untouched",
        )
        warning = (f"no {RECORD_NAME} ownership for {relative}; left it in place"
                   if entry is None else "")
        return action, [warning] if warning else []
    if expected is None or _content_digest(before) != expected:
        action = Action(
            Kind.SKIP, path, before, before,
            "skill file changed after integration; left untouched",
        )
        return action, [
            (f"{relative} differs from the copy this install wrote; it now "
             "belongs to the project and was not removed"),
        ]
    return Action(
        Kind.DELETE, path, before, "",
        "unchanged skill file created by this install",
    ), []


def _skill_actions(
    root: Path, agent_dir: str, record: dict[str, object] | None, *, remove: bool,
) -> tuple[list[Action], dict[str, dict[str, object]], list[str], list[str]]:
    """Plan safe copies of the shared skill into both host discovery roots.

    @param root the consuming repository root
    @param agent_dir where the canonical vendored skill lives
    @param record the prior integration record, or None
    @param remove whether to uninstall instead of expose the skill
    @return actions, next skill record, advisory warnings, and blocking conflicts
    """
    source_path = root / agent_dir / SKILL_SOURCE_PATH
    installed = _skills_record(record)
    wanted = dict(installed)
    actions: list[Action] = []
    warnings: list[str] = []
    problems: list[str] = []

    if not remove and not source_path.is_file():
        warnings.append(
            f"no shared skill found at {agent_dir}/{SKILL_SOURCE_PATH}; "
            "native Claude Code and Codex skill entry points were not planned"
        )
        return actions, wanted, warnings, problems

    source = "" if remove else read_preserving(source_path)
    source_digest = "" if remove else _content_digest(source)
    for relative in SKILL_TARGETS:
        path = root / relative
        entry = installed.get(relative)
        if remove:
            action, notes = _remove_skill_action(path, relative, entry)
            actions.append(action)
            warnings.extend(notes)
            continue
        action, next_entry, problem = _install_skill_action(
            path, relative, source, source_digest, entry,
        )
        actions.append(action)
        wanted[relative] = next_entry
        if problem is not None:
            problems.append(problem)
    return actions, wanted, warnings, problems


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
    block = render_block(read_version(root, agent_dir), agent_dir)
    record_path = root / agent_dir / RECORD_NAME
    record = load_record(record_path)

    if not (root / agent_dir / "discipline").exists():
        plan.warnings.append(
            f"no discipline found at {agent_dir}/discipline -- run vendor.py install first"
        )

    installed: dict[str, object] = dict(_markdown_record(record))
    for name in targets:
        action = _markdown_action(root / name, block, root, remove=remove,
                                  separator=recorded_separator(record, name))
        plan.actions.append(action)
        if not remove and action.kind is Kind.INSERT:
            installed[name] = {"separator": _separator(action.before)}

    skill_actions, installed_skills, skill_notes, skill_problems = _skill_actions(
        root, agent_dir, record, remove=remove,
    )
    plan.actions += skill_actions
    plan.warnings += skill_notes
    plan.problems += skill_problems

    settings, settings_notes = _settings_action(
        root / SETTINGS_PATH, remove=remove,
        added=recorded_entries(record, "permissions_added"))
    ignores, ignore_notes = _gitignore_action(
        root / ".gitignore", remove=remove,
        added=recorded_entries(record, "gitignore_added"))
    plan.actions += [settings, ignores]
    plan.warnings += settings_notes + ignore_notes

    plan.actions += _record_actions(record_path, record, remove=remove, wanted={
        "record_version": RECORD_VERSION,
        "permissions_added": _merged(record, "permissions_added",
                                     absent_permissions(settings.before)),
        "gitignore_added": _merged(record, "gitignore_added",
                                   absent_ignores(ignores.before)),
        "markdown": installed,
        "skills": installed_skills,
    })

    if not remove and not _is_git_repository(root):
        plan.warnings.append(
            "this is not a git repository, so there is no undo -- review the dry run first"
        )
    return plan


def _markdown_record(record: dict[str, object] | None) -> dict[str, object]:
    """Recover what the record already says about the markdown targets.

    @param record the record as it stands, or None when there is none
    @return the per-file entries, empty when there are none
    """
    markdown = (record or {}).get("markdown")
    return dict(markdown) if isinstance(markdown, dict) else {}


def _separator(before: str) -> str:
    """Choose the blank space to insert between existing content and an appended block.

    @param before the file as it stands, never empty on this path
    @return the run of newlines leaving exactly one blank line before the block
    """
    newline = dominant_newline(before)
    if before.endswith(newline * 2):
        return ""
    return newline if before.endswith(newline) else newline * 2


def _markdown_action(path: Path, block: str, root: Path, *, remove: bool,
                     separator: str | None) -> Action:
    """Plan one markdown target.

    @param path the file
    @param block the managed block to install, authored with LF endings
    @param root the repository root
    @param remove whether to remove rather than install
    @param separator the blank space recorded as having been inserted before the
        block, or None when no record covers this file
    @return the action for this file
    """
    exists = path.exists()
    before = read_preserving(path) if exists else ""
    found = BLOCK_RE.search(before)

    if remove:
        if found is None:
            return Action(Kind.SKIP, path, before, before, "no managed block present")
        return _removal(path, before, found, separator)

    rendered = with_newline(block, dominant_newline(before))
    if not exists:
        return Action(
            Kind.CREATE, path, "", f"# {root.name}\n\n" + rendered,
            "file absent; creating a minimal one -- the rest is the project's to write",
        )
    if found is not None:
        after = BLOCK_RE.sub(lambda _: rendered, before, count=1)
        reason = ("managed block already current" if after == before
                  else "managed block replaced; everything outside it is untouched")
        kind = Kind.SKIP if after == before else Kind.REPLACE
        return Action(kind, path, before, after, reason)

    return Action(
        Kind.INSERT, path, before, before + _separator(before) + rendered,
        "appended; every byte already in the file is left exactly as it was",
    )


def _removal(path: Path, before: str, found: re.Match[str], separator: str | None) -> Action:
    """Plan the excision of one managed block.

    Removing the markers is unambiguous -- they say who owns that text. The
    blank space in front of them is not: it is indistinguishable from blank
    space the project wrote. So it comes out only when the record says the
    integrator put it there, and stays otherwise.

    @param path the file
    @param before the file as it stands
    @param found where the managed block sits
    @param separator the recorded blank space, or None when no record covers it
    @return the action for this file
    """
    start = found.start()
    if separator and before[max(start - len(separator), 0):start] == separator:
        return Action(Kind.REMOVE, path, before,
                      before[:start - len(separator)] + before[found.end():],
                      "managed block removed, with the blank space it was inserted after")
    reason = ("managed block removed" if separator is not None else
              "managed block removed; no install record, so any blank line inserted "
              "before it is left in place")
    return Action(Kind.REMOVE, path, before, before[:start] + before[found.end():], reason)


def parse_settings(before: str) -> dict[str, object] | None:
    """Parse the settings file, or report that it cannot be used.

    @param before the file as it stands, empty when it does not exist
    @return the parsed mapping, empty for an empty file, and None when the
            content is not JSON or not an object
    """
    if not before.strip():
        return {}
    try:
        parsed = json.loads(before)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def allowed_entries(settings: dict[str, object] | None) -> list[str]:
    """Read the permissions the project currently grants.

    @param settings the parsed settings, or None when they could not be read
    @return the entries, empty when there are none to read
    """
    permissions = (settings or {}).get("permissions")
    allow = permissions.get("allow") if isinstance(permissions, dict) else None
    return [str(entry) for entry in allow] if isinstance(allow, list) else []


def absent_permissions(before: str) -> list[str]:
    """Which of our permission entries the project does not already have.

    This is the whole basis of the record: exactly these are added by an apply,
    so exactly these may later be taken back.

    @param before the settings file as it stands
    @return our entries that are missing, in our order
    """
    settings = parse_settings(before)
    if settings is None:
        return []
    allow = allowed_entries(settings)
    return [entry for entry in PERMISSIONS if entry not in allow]


def absent_ignores(before: str) -> list[str]:
    """Which of our ignore entries the project does not already have.

    @param before the ignore file as it stands
    @return our entries that are missing, in our order
    """
    present = set(before.splitlines())
    return [entry for entry in GITIGNORE_ENTRIES if entry not in present]


def _unrecorded(kind: str, mine: Sequence[str], present: Sequence[str]) -> list[str]:
    """Compose the warning for a removal that has no record to work from.

    @param kind what is being left behind, for the message
    @param mine the entries the discipline would ever add
    @param present the entries the file currently has
    @return one warning naming every entry left behind, or nothing to say
    """
    leftover = [entry for entry in present if entry in mine]
    if not leftover:
        return []
    told = (
        f"no {RECORD_NAME} from an earlier apply, so {len(leftover)} {kind} entr(ies) "
        f"were left in place: {', '.join(leftover)} -- this install predates the record, "
        f"and nothing distinguishes an entry the discipline added from one the project "
        f"already had. Remove them by hand if they are not yours."
    )
    return [told]


def _settings_action(path: Path, *, remove: bool,
                     added: Sequence[str] | None) -> tuple[Action, list[str]]:
    """Plan the permission settings, merging rather than replacing.

    The project may have its own entries and they are never removed: this adds
    only the narrow invocations the discipline's tooling needs, and takes back
    only the ones the record says were absent before it added them.

    @param path the settings file
    @param remove whether to remove the discipline's entries
    @param added the entries the record says the discipline added, or None when
        there is no record to consult
    @return the action for the settings file, and any warning it raises
    """
    before = read_preserving(path) if path.exists() else ""
    settings = parse_settings(before)
    if settings is None:
        return Action(Kind.SKIP, path, before, before,
                      "settings file is not valid JSON or not an object; left alone "
                      "rather than guessed at"), []

    newline = dominant_newline(before)
    stored = settings.get("permissions")
    permissions: dict[str, object] = dict(stored) if isinstance(stored, dict) else {}
    allow = allowed_entries(settings)

    if remove:
        if added is None:
            return (Action(Kind.SKIP, path, before, before,
                           "no install record; permission entries left in place"),
                    _unrecorded("permission", PERMISSIONS, allow))
        kept = [entry for entry in allow if entry not in added]
        if kept == allow:
            return Action(Kind.SKIP, path, before, before,
                          "no entry the discipline added is still present"), []
        permissions["allow"] = kept
        settings["permissions"] = permissions
        return Action(Kind.MERGE, path, before, _dump(settings, newline),
                      f"removed {len(allow) - len(kept)} permission entr(ies) this "
                      f"install added"), []

    missing = [entry for entry in PERMISSIONS if entry not in allow]
    if not missing:
        return Action(Kind.SKIP, path, before, before, "all permissions already allowed"), []
    permissions["allow"] = [*allow, *missing]
    settings["permissions"] = permissions
    return Action(
        Kind.MERGE if before else Kind.CREATE, path, before, _dump(settings, newline),
        f"adding {len(missing)} permission entr(ies); existing entries kept",
    ), []


def _gitignore_action(path: Path, *, remove: bool,
                      added: Sequence[str] | None) -> tuple[Action, list[str]]:
    """Plan the ignore entries for the discipline's derived files.

    @param path the .gitignore
    @param remove whether to remove the entries
    @param added the entries the record says the discipline added, or None when
        there is no record to consult
    @return the action for the ignore file, and any warning it raises
    """
    before = read_preserving(path) if path.exists() else ""
    newline = dominant_newline(before)

    if remove:
        if added is None:
            return (Action(Kind.SKIP, path, before, before,
                           "no install record; ignore entries left in place"),
                    _unrecorded("ignore", GITIGNORE_ENTRIES, before.splitlines()))
        after = _without_ignores(before, added, newline)
        if after == before:
            return Action(Kind.SKIP, path, before, before,
                          "no entry the discipline added is still present"), []
        return Action(Kind.REMOVE, path, before, after, "removed the entries this "
                      "install added, and the header introducing them"), []

    missing = absent_ignores(before)
    if not missing:
        return Action(Kind.SKIP, path, before, before, "already ignored"), []
    prefix = before if not before or before.endswith(("\n", "\r")) else before + newline
    body = newline.join([GITIGNORE_HEADER, *missing])
    return Action(Kind.MERGE if before else Kind.CREATE, path, before,
                  prefix + newline + body + newline,
                  f"ignoring {len(missing)} derived path(s)"), []


def _without_ignores(before: str, added: Sequence[str], newline: str) -> str:
    """Strip our recorded entries and our header from the ignore file.

    Only the blank line immediately above the header goes with it. Leaving the
    header behind would mean removal does not restore the file and the next
    reader inherits a comment about something no longer there; taking any
    further blank line would edit spacing the project owns.

    @param before the file as it stands
    @param added the entries the record says the discipline added
    @param newline the ending the file uses
    @return the file as it should read after removal
    """
    kept: list[str] = []
    for line in before.splitlines():
        if line in added:
            continue
        if added and line == GITIGNORE_HEADER:
            if kept and not kept[-1].strip():
                kept.pop()
            continue
        kept.append(line)
    if not kept:
        return ""
    trailing = newline if before.endswith(("\n", "\r")) else ""
    return newline.join(kept) + trailing


def _record_actions(path: Path, record: dict[str, object] | None, *, remove: bool,
                    wanted: dict[str, object]) -> list[Action]:
    """Plan the install record itself.

    On removal the record is emptied rather than deleted, so that removing twice
    is a no-op and a later install has somewhere to write. A repository that
    never had a record does not gain one from `--remove`.

    @param path the record file
    @param record the record as it stands, or None when there is none
    @param remove whether this run is taking the discipline back out
    @param wanted what the record should say after an installing run
    @return the action for the record, or nothing when there is none to write
    """
    if remove and record is None:
        return []
    before = read_preserving(path) if path.exists() else ""
    after = json.dumps(empty_record() if remove else wanted, indent=2,
                       ensure_ascii=False) + "\n"
    if after == before:
        return [Action(Kind.SKIP, path, before, before, "install record already accurate")]
    reason = ("install record emptied; nothing of ours is installed" if remove else
              "recording which entries were absent, so --remove takes back only those")
    return [Action(Kind.MERGE if before else Kind.CREATE, path, before, after, reason)]


def _dump(settings: dict[str, object], newline: str) -> str:
    """Serialize settings the way an editor would leave them.

    @param settings the settings mapping
    @param newline the ending the file already used
    @return pretty-printed JSON with a trailing newline
    """
    return with_newline(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", newline)


def _is_git_repository(root: Path) -> bool:
    """Whether `root` is inside a git working tree.

    @param root the directory to test
    @return True when git reports a working tree
    """
    try:
        finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv, no shell
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return finished.returncode == 0 and finished.stdout.strip() == "true"


# ---------------------------------------------------------------- the apply


def apply(plan: Plan) -> list[Action]:
    """Apply every changing action. The plan is not recomputed here.

    @param plan the plan to apply
    @return the actions that were written or deleted
    """
    written: list[Action] = []
    for action in plan.changing:
        if action.kind is Kind.DELETE:
            action.path.unlink()
            written.append(action)
            continue
        action.path.parent.mkdir(parents=True, exist_ok=True)
        write_preserving(action.path, action.after)
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
            yield from ("     " + line.rstrip("\r\n")
                        for line in action.diff(root).splitlines())
    for warning in plan.warnings:
        yield f"\n   warning: {warning}"
    for problem in plan.problems:
        yield f"\n   ERROR: {problem}"


# ---------------------------------------------------------------------- main


def install_hooks(root: Path, agent_dir: str, *, remove: bool = False) -> list[str]:
    """Point git's `core.hooksPath` at the vendored hook directory.

    Pointed at, not copied into `.git/hooks`. A copy is a fork: the moment the
    vendored discipline updates, the installed hook is a stale duplicate nobody
    diffs. A pointer means an update to the discipline updates the hook, and
    `git config --unset core.hooksPath` removes it completely with no residue.

    `FLOW-009` -- the gates pass before a change is offered -- was enforced by
    memory until this existed, which by this corpus's own standard means it was
    not binding at all.

    @param root the repository to configure
    @param agent_dir where the discipline was vendored
    @param remove whether to unset the setting instead of setting it
    @return the lines to print, describing what was done
    @throws FileNotFoundError when the hook directory is not there, because
        pointing git at a directory with no hooks would silently disable the
        hooks a project already had
    """
    hooks = root / agent_dir / "enforce" / "templates" / "hooks"
    if not hooks.is_dir():
        hooks = root / "enforce" / "templates" / "hooks"
    if not remove and not hooks.is_dir():
        raise FileNotFoundError(hooks)

    if remove:
        subprocess.run(("git", "config", "--unset", "core.hooksPath"),  # ruff: ignore[start-process-with-partial-path]
                       cwd=root, capture_output=True, text=True, check=False)
        return ["core.hooksPath unset; git's default hooks are in force again"]

    relative = hooks.relative_to(root).as_posix()
    finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        ("git", "config", "core.hooksPath", relative),  # ruff: ignore[start-process-with-partial-path]
        cwd=root, capture_output=True, text=True, check=False)
    if finished.returncode != 0:
        return [f"could not set core.hooksPath: {finished.stderr.strip()}"]
    installed = sorted(h.name for h in hooks.iterdir() if h.is_file())
    return [
        f"core.hooksPath -> {relative}",
        f"  active: {', '.join(installed)}",
        "  pre-push runs the full gate; `git push --no-verify` bypasses it.",
        "  remove with: git config --unset core.hooksPath",
    ]


def _hooks_command(root: Path, agent_dir: str, *, remove: bool) -> int:
    """Run the `--hooks` path and report, lifted out of `main`.

    `main` crossed `C901`'s ceiling when this branch joined it, and `C901` is the
    code `ARCH-016` is enforced through -- so the rule refused this change for the
    same reason it would refuse an adopter's.

    @param root the repository to configure
    @param agent_dir where the discipline was vendored
    @param remove whether to unset rather than set
    @return the process exit status
    """
    try:
        for line in install_hooks(root, agent_dir, remove=remove):
            print(line)
    except FileNotFoundError as absent:
        print(f"no hook directory at {absent}; nothing was configured, and "
              f"pointing git at it would have disabled the hooks this repository "
              f"already has", file=sys.stderr)
        return 1
    return 0


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
    parser.add_argument("--hooks", action="store_true",
                        help="point core.hooksPath at the vendored hooks, so the "
                             "gate runs before a push (FLOW-009)")
    parser.add_argument("--only", action="append", choices=list(MARKDOWN_TARGETS),
                        help="restrict to one markdown target; repeatable")
    args = parser.parse_args(argv)

    root = args.root.resolve()

    if args.hooks:
        return _hooks_command(root, args.agent_dir, remove=args.remove)

    plan = build_plan(root, args.agent_dir, remove=args.remove,
                      targets=args.only or MARKDOWN_TARGETS)

    if args.check:
        stale = plan.changing
        for line in render_plan(plan, root, show_diff=False):
            print(line)
        out = len(stale) + len(plan.problems)
        print(f"\n{len(stale)} file(s) out of step, "
              f"{len(plan.problems)} blocking conflict(s)." if out
              else "\nagent configuration is in step with the discipline.")
        return 1 if out else 0

    if args.dry_run:
        print("PLAN (nothing written)\n")
        for line in render_plan(plan, root, show_diff=True):
            print(line)
        print(f"\n{len(plan.changing)} file(s) would change. Re-run without --dry-run to apply.")
        return 1 if plan.problems else 0

    for line in render_plan(plan, root, show_diff=False):
        print(line)
    written = apply(plan)
    verb = "removed from" if args.remove else "integrated into"
    print(f"\ndiscipline {verb} {len(written)} file(s).")
    if not args.remove and written:
        print("Start a fresh agent session so the new configuration is loaded.")
    return 1 if plan.problems else 0


if __name__ == "__main__":
    sys.exit(main())
