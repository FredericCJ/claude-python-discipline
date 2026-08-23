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

# Import annotation-only protocols without adding runtime dependencies.
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
## Each element is one host instruction filename in Claude-then-Codex integration order.
MARKDOWN_TARGETS: Final[tuple[str, ...]] = ("CLAUDE.md", "AGENTS.md")

## The one skill source inside the vendored bundle. Both host entry points are
## exact copies of this file and both route back into `.agent/discipline/`.
SKILL_SOURCE_PATH: Final = "skills/python-discipline/SKILL.md"
## Repository-local discovery paths for Claude Code and Codex respectively.
## Each element is one native skill path in Claude-then-Codex integration order.
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
## Each element is one Claude permission expression in installation order.
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
## Each element is one ignore spelling in managed-block order.
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
        # Return true when before and after differ or the action is a deletion to the caller.
        return self.kind is Kind.DELETE or self.before != self.after

    def diff(self, root: Path) -> str:
        """A unified diff of the change, for the dry run.

        @param root the repository root, for display paths
        @return the diff text, empty when nothing changes
        """
        # Select the empty-or-disabled path when self.changes has no usable value.
        if not self.changes:
            # Return the diff text, empty when nothing changes to the caller.
            return ""
        # Normalize the current repository path to its portable baseline key spelling.
        name = self.path.relative_to(root).as_posix()
        # Return the diff text, empty when nothing changes to the caller.
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
    ## Each element is one planned file mutation in application order.
    actions: list[Action] = field(default_factory=list)
    ## Advisory notes; none of these block an apply.
    ## Each element is one non-blocking diagnostic in discovery order.
    warnings: list[str] = field(default_factory=list)
    ## Conflicts that prevent a complete integration but do not authorise overwriting.
    ## Each element is one blocking collision diagnostic in discovery order.
    problems: list[str] = field(default_factory=list)

    @property
    def changing(self) -> list[Action]:
        """Actions that would actually alter a file.

        @return the subset whose before and after differ
        """
        # Select a as the current element from self.actions if a.changes] while changing
        # Details: preserves traversal order.
        # Return the subset whose before and after differ to the caller.
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
    # Compute handle using "utf-8", newline="") as handle: for later read preserving logic.
    # Confine the acquired resource to this operation and release it on every exit.
    with path.open(encoding="utf-8", newline="") as handle:
        # Return the decoded text, carriage returns included to the caller.
        return handle.read()


def write_preserving(path: Path, text: str) -> None:
    """Write text with no line-ending translation of any kind.

    @param path the file to write, whose parent directory must exist
    @param text exactly the bytes to store, once encoded

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Compute handle using "utf-8", newline="") as handle: for later write preserving logic.
    # Confine the acquired resource to this operation and release it on every exit.
    with path.open("w", encoding="utf-8", newline="") as handle:
        # Publish the externally visible effect after all required inputs are ready.
        handle.write(text)


def dominant_newline(text: str) -> str:
    """Decide which line ending a file already uses.

    Ties and empty files go to LF, which is what a file the integrator creates
    itself uses and what the block is authored with.

    @param text the file as it stands
    @return CRLF when carriage returns are in the majority, LF otherwise
    """
    # Compute crlf using text.count for later dominant newline logic.
    crlf = text.count("\r\n")
    # Return cRLF when carriage returns are in the majority, LF otherwise to the caller.
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
    # Return the same text with every line ending replaced to the caller.
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
    # Return the block text, markers included, with LF line endings to the caller.
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
    # Locate the manifest whose exact content identity names the vendored discipline.
    manifest = root / agent_dir / "MANIFEST.json"
    # Select the existing-artifact path only when `not manifest.exists()` is satisfied.
    if not manifest.exists():
        # Return `release (hash)` when a release is recorded, the hash alone when it to the
        # Details: caller.
        return "unversioned"
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute recorded using json.loads for later read version logic.
        recorded = json.loads(manifest.read_text(encoding="utf-8"))
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (json.JSONDecodeError, OSError):
        # Return `release (hash)` when a release is recorded, the hash alone when it to the
        # Details: caller.
        return "unreadable"
    # Select the empty-or-disabled path when isinstance(recorded, dict) has no usable value.
    if not isinstance(recorded, dict):
        # Return `release (hash)` when a release is recorded, the hash alone when it to the
        # Details: caller.
        return "unreadable"
    # Compute stamp using str for later read version logic.
    stamp = str(recorded.get("version", "?"))
    # Compute release using recorded.get for later read version logic.
    release = recorded.get("release")
    # Return `release (hash)` when a release is recorded, the hash alone when it to the caller.
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
    # Select the existing-artifact path only when `not path.exists()` is satisfied.
    if not path.exists():
        # Return the parsed record, or None when there is none to trust to the caller.
        return None
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute parsed using json.loads for later load record logic.
        parsed = json.loads(path.read_text(encoding="utf-8"))
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        # Return the parsed record, or None when there is none to trust to the caller.
        return None
    # Return the parsed record, or None when there is none to trust to the caller.
    return parsed if isinstance(parsed, dict) else None


def recorded_entries(record: dict[str, object] | None, key: str) -> tuple[str, ...] | None:
    """One recorded list of entries the discipline added.

    @param record the record as it stands, or None when there is none
    @param key which list to read
    @return the entries, empty when the record carries no such list, and None
            when there is no record at all -- the two must not be confused, since
            one authorises removal of nothing and the other forbids removal
    """
    # Use the absence path when record has no available value.
    if record is None:
        # Return the entries, empty when the record carries no such list, and None to the
        # Details: caller.
        return None
    # Treat the current value as the candidate element consumed by the enclosing transformation.
    value = record.get(key)
    # Select the empty-or-disabled path when isinstance(value, list) has no usable value.
    if not isinstance(value, list):
        # Return the entries, empty when the record carries no such list, and None to the
        # Details: caller.
        return ()
    # Treat the current item as the candidate element consumed by the enclosing transformation.
    # Return the entries, empty when the record carries no such list, and None to the caller.
    return tuple(str(item) for item in value)


def recorded_separator(record: dict[str, object] | None, name: str) -> str | None:
    """Look up the blank space an earlier apply inserted before one file's block.

    @param record the record as it stands, or None when there is none
    @param name the markdown target, as it is keyed in the record
    @return the recorded separator, or None when nothing was recorded for it
    """
    # Compute markdown using (record or {}).get("markdown") for later recorded separator logic.
    markdown = (record or {}).get("markdown")
    # Select the empty-or-disabled path when isinstance(markdown, dict) has no usable value.
    if not isinstance(markdown, dict):
        # Return the recorded separator, or None when nothing was recorded for it to the caller.
        return None
    # Treat the current entry as the candidate element consumed by the enclosing transformation.
    entry = markdown.get(name)
    # Select the empty-or-disabled path when isinstance(entry, dict) has no usable value.
    if not isinstance(entry, dict):
        # Return the recorded separator, or None when nothing was recorded for it to the caller.
        return None
    # Compute separator using entry.get for later recorded separator logic.
    separator = entry.get("separator")
    # Return the recorded separator, or None when nothing was recorded for it to the caller.
    return separator if isinstance(separator, str) else None


def empty_record() -> dict[str, object]:
    """Build the record as it reads when nothing is installed.

    @return a record claiming no permission, ignore, markdown, or skill contribution
    """
    # Return a record claiming no permission, ignore, markdown, or skill contribution to the
    # Details: caller.
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
        Each element is one newly owned entry in caller order.
    @return the union, in recorded order first
    """
    # Compute kept using list for later merged logic.
    kept = list(recorded_entries(record, key) or ())
    # Treat the current entry as the candidate element consumed by the enclosing transformation.
    # Return the union, in recorded order first to the caller.
    return [*kept, *(entry for entry in newly if entry not in kept)]


def _skills_record(record: dict[str, object] | None) -> dict[str, dict[str, object]]:
    """Recover per-path ownership and digests for native skill entry points.

    Invalid entries grant no deletion or replacement authority and are ignored.
    This is the same conservative rule used for a missing record: unexplained
    files belong to the project.

    @param record the install record as it stands, or None
    @return valid path-to-entry mappings, empty when none can be trusted
    """
    # Retain the immutable source representation consumed by subsequent analysis.
    raw = (record or {}).get("skills")
    # Select the empty-or-disabled path when isinstance(raw, dict) has no usable value.
    if not isinstance(raw, dict):
        # Return valid path-to-entry mappings, empty when none can be trusted to the caller.
        return {}
    # Resolve the repository-confined path used by this operation before filesystem access.
    # Return valid path-to-entry mappings, empty when none can be trusted to the caller.
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
    # Return the first 16 hexadecimal characters of its SHA-256 to the caller.
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _skill_ownership(entry: dict[str, object] | None) -> tuple[bool, str | None]:
    """Read the authority an integration-record skill entry grants.

    @param entry one path's record, or None when the path was never recorded
    @return whether this installer created it, and the digest it wrote
    """
    # Use the absence path when entry has no available value.
    if entry is None:
        # Return whether this installer created it, and the digest it wrote to the caller.
        return False, None
    # Compute digest using entry.get for later skill ownership logic.
    digest = entry.get("digest")
    # Return whether this installer created it, and the digest it wrote to the caller.
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
    # Select the regular-file path only when `path.is_symlink() or (path.exists() and (not
    # Details: path.is_file()))` is satisfied.
    if path.is_symlink() or (path.exists() and not path.is_file()):
        # Compute reason using "a non-regular path already occupies the skill entry point;  for
        # Details: later install skill action logic.
        reason = "a non-regular path already occupies the skill entry point; left untouched"
        # Compute action using Action for later install skill action logic.
        action = Action(Kind.SKIP, path, "", "", reason)
        # Compute next entry using dict for later install skill action logic.
        next_entry = dict(entry) if entry is not None else {"created": False, "digest": ""}
        # Compute problem using f"cannot install the shared skill at {relative}: {reason}" for
        # Details: later install skill action logic.
        problem = f"cannot install the shared skill at {relative}: {reason}"
        # Return the action, next record entry, and a blocking problem if any to the caller.
        return action, next_entry, problem
    # Select the regular-file path only when `not path.is_file()` is satisfied.
    if not path.is_file():
        # Compute action using Action for later install skill action logic.
        action = Action(
            Kind.CREATE, path, "", source,
            "creating the native entry point from the shared vendored skill",
        )
        # Return the action, next record entry, and a blocking problem if any to the caller.
        return action, {"created": True, "digest": source_digest}, None

    # Compute before using read preserving for later install skill action logic.
    before = read_preserving(path)
    # Unpack created, expected using  skill ownership for later install skill action logic.
    created, expected = _skill_ownership(entry)
    # Select the guarded path only after `before == source` is satisfied.
    if before == source:
        # Compute action using Action for later install skill action logic.
        action = Action(
            Kind.SKIP, path, before, before,
            "native skill already matches the shared vendored source",
        )
        # Return the action, next record entry, and a blocking problem if any to the caller.
        return action, {"created": created, "digest": source_digest}, None
    # Select the guarded path only after `created and expected is not None and
    # Details: (_content_digest(before) == expected)` is satisfied.
    if created and expected is not None and _content_digest(before) == expected:
        # Compute action using Action for later install skill action logic.
        action = Action(
            Kind.REPLACE, path, before, source,
            "updating the unchanged skill file created by this install",
        )
        # Return the action, next record entry, and a blocking problem if any to the caller.
        return action, {"created": True, "digest": source_digest}, None

    # Compute reason using ( for later install skill action logic.
    reason = (
        "recorded skill was locally modified; left untouched" if created
        else "an unowned skill already exists at this path; left untouched"
    )
    # Compute action using Action for later install skill action logic.
    action = Action(Kind.SKIP, path, before, before, reason)
    # Compute next entry using (dict(entry) if entry is not None else for later install skill
    # Details: action logic.
    next_entry = (dict(entry) if entry is not None else
                  {"created": False, "digest": _content_digest(before)})
    # Return the action, next record entry, and a blocking problem if any to the caller.
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
    # Select the regular-file path only when `path.is_symlink() or (path.exists() and (not
    # Details: path.is_file()))` is satisfied.
    if path.is_symlink() or (path.exists() and not path.is_file()):
        # Compute action using Action for later remove skill action logic.
        action = Action(
            Kind.SKIP, path, "", "",
            "non-regular skill entry point is project-owned; left untouched",
        )
        # Return the action and any conservative-removal warning to the caller.
        return action, [f"{relative} is not a regular file and was not removed"]
    # Select the regular-file path only when `not path.is_file()` is satisfied.
    if not path.is_file():
        # Return the action and any conservative-removal warning to the caller.
        return Action(Kind.SKIP, path, "", "", "skill file absent"), []

    # Compute before using read preserving for later remove skill action logic.
    before = read_preserving(path)
    # Unpack created, expected using  skill ownership for later remove skill action logic.
    created, expected = _skill_ownership(entry)
    # Select the empty-or-disabled path when created has no usable value.
    if not created:
        # Compute action using Action for later remove skill action logic.
        action = Action(
            Kind.SKIP, path, before, before,
            "skill file was not created by this install; left untouched",
        )
        # Select warning as the current element from place" while remove skill action preserves
        # Details: traversal order.
        warning = (f"no {RECORD_NAME} ownership for {relative}; left it in place"
                   if entry is None else "")
        # Return the action and any conservative-removal warning to the caller.
        return action, [warning] if warning else []
    # Select the guarded path only after `expected is None or _content_digest(before) !=
    # Details: expected` is satisfied.
    if expected is None or _content_digest(before) != expected:
        # Compute action using Action for later remove skill action logic.
        action = Action(
            Kind.SKIP, path, before, before,
            "skill file changed after integration; left untouched",
        )
        # Return the action and any conservative-removal warning to the caller.
        return action, [
            (f"{relative} differs from the copy this install wrote; it now "
             "belongs to the project and was not removed"),
        ]
    # Return the action and any conservative-removal warning to the caller.
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
        True enables remove; false selects its disabled alternative.
    @return actions, next skill record, advisory warnings, and blocking conflicts
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    source_path = root / agent_dir / SKILL_SOURCE_PATH
    # Compute installed using  skills record for later skill actions logic.
    installed = _skills_record(record)
    # Compute wanted using dict for later skill actions logic.
    wanted = dict(installed)
    # Each actions element is one native-skill mutation in Claude-then-Codex target order.
    actions: list[Action] = []
    # Each warnings element is one conservative-removal note in skill-target order.
    warnings: list[str] = []
    # Each problems element is one project-owned skill collision in target order.
    problems: list[str] = []

    # Select the regular-file path only when `not remove and (not source_path.is_file())` is
    # Details: satisfied.
    if not remove and not source_path.is_file():
        warnings.append(
            f"no shared skill found at {agent_dir}/{SKILL_SOURCE_PATH}; "
            "native Claude Code and Codex skill entry points were not planned"
        )
        # Return actions, next skill record, advisory warnings, and blocking conflicts to the
        # Details: caller.
        return actions, wanted, warnings, problems

    # Retain the immutable source representation consumed by subsequent analysis.
    source = "" if remove else read_preserving(source_path)
    # Compute source digest using "" if remove else _content_digest(source) for later skill
    # Details: actions logic.
    source_digest = "" if remove else _content_digest(source)
    # Select relative as the current element from SKILL_TARGETS while skill actions preserves
    # Details: traversal order.
    # Advance skill actions through the current input element in declared order.
    for relative in SKILL_TARGETS:
        # Resolve the repository-confined path used by this operation before filesystem access.
        path = root / relative
        # Treat the current entry as the candidate element consumed by the enclosing
        # Details: transformation.
        entry = installed.get(relative)
        # Handle the non-empty or enabled remove state.
        if remove:
            # Unpack action, notes using  remove skill action for later skill actions logic.
            action, notes = _remove_skill_action(path, relative, entry)
            actions.append(action)
            warnings.extend(notes)
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Unpack action, next entry, problem using  install skill action for later skill actions
        # Details: logic.
        action, next_entry, problem = _install_skill_action(
            path, relative, source, source_digest, entry,
        )
        actions.append(action)
        # Update  skill actions state only after the required source facts are available.
        wanted[relative] = next_entry
        # Use the available-value path only when problem is present.
        if problem is not None:
            problems.append(problem)
    # Return actions, next skill record, advisory warnings, and blocking conflicts to the
    # Details: caller.
    return actions, wanted, warnings, problems


# ----------------------------------------------------------------- the plan


def build_plan(root: Path, agent_dir: str, *, remove: bool = False,
               targets: Sequence[str] = MARKDOWN_TARGETS) -> Plan:
    """Compute every change without making any.

    @param root the repository root
    @param agent_dir where the discipline was vendored, relative to the root
    @param remove when True, plan the block's removal instead of its installation
        True enables remove; false selects its disabled alternative.
    @param targets which markdown files to manage
        Each targets element represents one governed path; traversal order is preserved.
    @return the plan
    """
    # Compute plan using Plan for later build plan logic.
    plan = Plan()
    # Compute block using render block for later build plan logic.
    block = render_block(read_version(root, agent_dir), agent_dir)
    # Compute record path using root / agent_dir / RECORD_NAME for later build plan logic.
    record_path = root / agent_dir / RECORD_NAME
    # Load integration-record field keys to recorded ownership values; mapping key order is
    # deliberately unused.
    record = load_record(record_path)

    # Select the existing-artifact path only when `not (root / agent_dir /
    # Details: 'discipline').exists()` is satisfied.
    if not (root / agent_dir / "discipline").exists():
        plan.warnings.append(
            f"no discipline found at {agent_dir}/discipline -- run vendor.py install first"
        )

    # Each installed key is a managed Markdown filename and each value records its separator;
    # mapping key order is deliberately unused.
    installed: dict[str, object] = dict(_markdown_record(record))
    # Normalize the current repository path to its portable baseline key spelling.
    # Advance build plan through the current input element in declared order.
    for name in targets:
        # Compute action using  markdown action for later build plan logic.
        action = _markdown_action(root / name, block, root, remove=remove,
                                  separator=recorded_separator(record, name))
        plan.actions.append(action)
        # Select the empty-or-disabled path when remove and action.kind is Kind.INSERT has no
        # Details: usable value.
        if not remove and action.kind is Kind.INSERT:
            # Update build plan state only after the required source facts are available.
            installed[name] = {"separator": _separator(action.before)}

    # Unpack installed skills, skill actions, skill notes, skill problems using  skill actions
    # Details: for later build plan logic.
    skill_actions, installed_skills, skill_notes, skill_problems = _skill_actions(
        root, agent_dir, record, remove=remove,
    )
    # Update build plan state only after the required source facts are available.
    plan.actions += skill_actions
    # Update build plan state only after the required source facts are available.
    plan.warnings += skill_notes
    # Update build plan state only after the required source facts are available.
    plan.problems += skill_problems

    # Unpack settings, settings notes using  settings action for later build plan logic.
    settings, settings_notes = _settings_action(
        root / SETTINGS_PATH, remove=remove,
        added=recorded_entries(record, "permissions_added"))
    # Unpack ignore notes, ignores using  gitignore action for later build plan logic.
    ignores, ignore_notes = _gitignore_action(
        root / ".gitignore", remove=remove,
        added=recorded_entries(record, "gitignore_added"))
    # Update build plan state only after the required source facts are available.
    plan.actions += [settings, ignores]
    # Update build plan state only after the required source facts are available.
    plan.warnings += settings_notes + ignore_notes

    # Update build plan state only after the required source facts are available.
    plan.actions += _record_actions(record_path, record, remove=remove, wanted={
        "record_version": RECORD_VERSION,
        "permissions_added": _merged(record, "permissions_added",
                                     absent_permissions(settings.before)),
        "gitignore_added": _merged(record, "gitignore_added",
                                   absent_ignores(ignores.before)),
        "markdown": installed,
        "skills": installed_skills,
    })

    # Select the empty-or-disabled path when remove and (not  is git repository(root)) has no
    # Details: usable value.
    if not remove and not _is_git_repository(root):
        plan.warnings.append(
            "this is not a git repository, so there is no undo -- review the dry run first"
        )
    # Return the plan to the caller.
    return plan


def _markdown_record(record: dict[str, object] | None) -> dict[str, object]:
    """Recover what the record already says about the markdown targets.

    @param record the record as it stands, or None when there is none
    @return the per-file entries, empty when there are none
    """
    # Compute markdown using (record or {}).get("markdown") for later markdown record logic.
    markdown = (record or {}).get("markdown")
    # Return the per-file entries, empty when there are none to the caller.
    return dict(markdown) if isinstance(markdown, dict) else {}


def _separator(before: str) -> str:
    """Choose the blank space to insert between existing content and an appended block.

    @param before the file as it stands, never empty on this path
    @return the run of newlines leaving exactly one blank line before the block
    """
    # Compute newline using dominant newline for later separator logic.
    newline = dominant_newline(before)
    # Select the guarded path only after `before.endswith(newline * 2)` is satisfied.
    if before.endswith(newline * 2):
        # Return the run of newlines leaving exactly one blank line before the block to the
        # Details: caller.
        return ""
    # Return the run of newlines leaving exactly one blank line before the block to the caller.
    return newline if before.endswith(newline) else newline * 2


def _markdown_action(path: Path, block: str, root: Path, *, remove: bool,
                     separator: str | None) -> Action:
    """Plan one markdown target.

    @param path the file
    @param block the managed block to install, authored with LF endings
    @param root the repository root
    @param remove whether to remove rather than install
        True enables remove; false selects its disabled alternative.
    @param separator the blank space recorded as having been inserted before the
        block, or None when no record covers this file
    @return the action for this file
    """
    # Compute exists using path.exists for later markdown action logic.
    exists = path.exists()
    # Compute before using read preserving for later markdown action logic.
    before = read_preserving(path) if exists else ""
    # Preserve the optional pattern match that carries the reported analysis count.
    found = BLOCK_RE.search(before)

    # Handle the non-empty or enabled remove state.
    if remove:
        # Use the absence path when found has no available value.
        if found is None:
            # Return the action for this file to the caller.
            return Action(Kind.SKIP, path, before, before, "no managed block present")
        # Return the action for this file to the caller.
        return _removal(path, before, found, separator)

    # Compute rendered using with newline for later markdown action logic.
    rendered = with_newline(block, dominant_newline(before))
    # Select the empty-or-disabled path when exists has no usable value.
    if not exists:
        # Return the action for this file to the caller.
        return Action(
            Kind.CREATE, path, "", f"# {root.name}\n\n" + rendered,
            "file absent; creating a minimal one -- the rest is the project's to write",
        )
    # Use the available-value path only when found is present.
    if found is not None:
        # Compute after using BLOCK RE.sub for later markdown action logic.
        after = BLOCK_RE.sub(lambda _: rendered, before, count=1)
        # Compute reason using ("managed block already current" if after == before for later
        # Details: markdown action logic.
        reason = ("managed block already current" if after == before
                  else "managed block replaced; everything outside it is untouched")
        # Compute kind using Kind.SKIP if after == before else Kind.REPLACE for later markdown
        # Details: action logic.
        kind = Kind.SKIP if after == before else Kind.REPLACE
        # Return the action for this file to the caller.
        return Action(kind, path, before, after, reason)

    # Return the action for this file to the caller.
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
    # Locate the structural boundary used to parse the external result safely.
    start = found.start()
    # Select the guarded path only after `separator and before[max(start - len(separator),
    # Details: 0):start] == separator` is satisfied.
    if separator and before[max(start - len(separator), 0):start] == separator:
        # Return the action for this file to the caller.
        return Action(Kind.REMOVE, path, before,
                      before[:start - len(separator)] + before[found.end():],
                      "managed block removed, with the blank space it was inserted after")
    # Compute reason using ("managed block removed" if separator is not None else for later
    # Details: removal logic.
    reason = ("managed block removed" if separator is not None else
              "managed block removed; no install record, so any blank line inserted "
              "before it is left in place")
    # Return the action for this file to the caller.
    return Action(Kind.REMOVE, path, before, before[:start] + before[found.end():], reason)


def parse_settings(before: str) -> dict[str, object] | None:
    """Parse the settings file, or report that it cannot be used.

    @param before the file as it stands, empty when it does not exist
    @return the parsed mapping, empty for an empty file, and None when the
            content is not JSON or not an object
    """
    # Select the empty-or-disabled path when before.strip() has no usable value.
    if not before.strip():
        # Return the parsed mapping, empty for an empty file, and None when the to the caller.
        return {}
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute parsed using json.loads for later parse settings logic.
        parsed = json.loads(before)
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except json.JSONDecodeError:
        # Return the parsed mapping, empty for an empty file, and None when the to the caller.
        return None
    # Return the parsed mapping, empty for an empty file, and None when the to the caller.
    return parsed if isinstance(parsed, dict) else None


def allowed_entries(settings: dict[str, object] | None) -> list[str]:
    """Read the permissions the project currently grants.

    @param settings the parsed settings, or None when they could not be read
    @return the entries, empty when there are none to read
    """
    # Compute permissions using (settings or {}).get("permissions") for later allowed entries
    # Details: logic.
    permissions = (settings or {}).get("permissions")
    # Compute allow using permissions.get for later allowed entries logic.
    allow = permissions.get("allow") if isinstance(permissions, dict) else None
    # Treat the current entry as the candidate element consumed by the enclosing transformation.
    # Return the entries, empty when there are none to read to the caller.
    return [str(entry) for entry in allow] if isinstance(allow, list) else []


def absent_permissions(before: str) -> list[str]:
    """Which of our permission entries the project does not already have.

    This is the whole basis of the record: exactly these are added by an apply,
    so exactly these may later be taken back.

    @param before the settings file as it stands
    @return our entries that are missing, in our order
    """
    # Compute settings using parse settings for later absent permissions logic.
    settings = parse_settings(before)
    # Use the absence path when settings has no available value.
    if settings is None:
        # Return our entries that are missing, in our order to the caller.
        return []
    # Compute allow using allowed entries for later absent permissions logic.
    allow = allowed_entries(settings)
    # Treat the current entry as the candidate element consumed by the enclosing transformation.
    # Return our entries that are missing, in our order to the caller.
    return [entry for entry in PERMISSIONS if entry not in allow]


def absent_ignores(before: str) -> list[str]:
    """Which of our ignore entries the project does not already have.

    @param before the ignore file as it stands
    @return our entries that are missing, in our order
    """
    # Compute present using set for later absent ignores logic.
    present = set(before.splitlines())
    # Treat the current entry as the candidate element consumed by the enclosing transformation.
    # Return our entries that are missing, in our order to the caller.
    return [entry for entry in GITIGNORE_ENTRIES if entry not in present]


def _unrecorded(kind: str, mine: Sequence[str], present: Sequence[str]) -> list[str]:
    """Compose the warning for a removal that has no record to work from.

    @param kind what is being left behind, for the message
    @param mine the entries the discipline would ever add
        Each element is one discipline-owned spelling; order is deliberately unused for
        membership tests.
    @param present the entries the file currently has
        Each element is one currently present spelling in file order.
    @return one warning naming every entry left behind, or nothing to say
    """
    # Each leftover element is one discipline-shaped entry retained in original file order.
    leftover = [entry for entry in present if entry in mine]
    # Select the empty-or-disabled path when leftover has no usable value.
    if not leftover:
        # Return one warning naming every entry left behind, or nothing to say to the caller.
        return []
    # Compute told using ( for later unrecorded logic.
    told = (
        f"no {RECORD_NAME} from an earlier apply, so {len(leftover)} {kind} entr(ies) "
        f"were left in place: {', '.join(leftover)} -- this install predates the record, "
        f"and nothing distinguishes an entry the discipline added from one the project "
        f"already had. Remove them by hand if they are not yours."
    )
    # Return one warning naming every entry left behind, or nothing to say to the caller.
    return [told]


def _settings_action(path: Path, *, remove: bool,
                     added: Sequence[str] | None) -> tuple[Action, list[str]]:
    """Plan the permission settings, merging rather than replacing.

    The project may have its own entries and they are never removed: this adds
    only the narrow invocations the discipline's tooling needs, and takes back
    only the ones the record says were absent before it added them.

    @param path the settings file
    @param remove whether to remove the discipline's entries
        True enables remove; false selects its disabled alternative.
    @param added the entries the record says the discipline added, or None when
        there is no record to consult
    @return the action for the settings file, and any warning it raises
    """
    # Compute before using read preserving for later settings action logic.
    before = read_preserving(path) if path.exists() else ""
    # Compute settings using parse settings for later settings action logic.
    settings = parse_settings(before)
    # Use the absence path when settings has no available value.
    if settings is None:
        # Return the action for the settings file, and any warning it raises to the caller.
        return Action(Kind.SKIP, path, before, before,
                      "settings file is not valid JSON or not an object; left alone "
                      "rather than guessed at"), []

    # Compute newline using dominant newline for later settings action logic.
    newline = dominant_newline(before)
    # Compute stored using settings.get for later settings action logic.
    stored = settings.get("permissions")
    # Each permissions key is a Claude permission category and each value is its configured
    # entries; insertion order is preserved when rewriting JSON but has no policy meaning.
    permissions: dict[str, object] = dict(stored) if isinstance(stored, dict) else {}
    # Compute allow using allowed entries for later settings action logic.
    allow = allowed_entries(settings)

    # Handle the non-empty or enabled remove state.
    if remove:
        # Use the absence path when added has no available value.
        if added is None:
            # Return the action for the settings file, and any warning it raises to the caller.
            return (Action(Kind.SKIP, path, before, before,
                           "no install record; permission entries left in place"),
                    _unrecorded("permission", PERMISSIONS, allow))
        # Each kept element is one permission not owned by this install, in existing file order.
        kept = [entry for entry in allow if entry not in added]
        # Select the guarded path only after `kept == allow` is satisfied.
        if kept == allow:
            # Return the action for the settings file, and any warning it raises to the caller.
            return Action(Kind.SKIP, path, before, before,
                          "no entry the discipline added is still present"), []
        # Update  settings action state only after the required source facts are available.
        permissions["allow"] = kept
        # Update  settings action state only after the required source facts are available.
        settings["permissions"] = permissions
        # Return the action for the settings file, and any warning it raises to the caller.
        return Action(Kind.MERGE, path, before, _dump(settings, newline),
                      f"removed {len(allow) - len(kept)} permission entr(ies) this "
                      f"install added"), []

    # Each missing element is one required permission absent from the existing allow-list, in
    # discipline declaration order.
    missing = [entry for entry in PERMISSIONS if entry not in allow]
    # Select the empty-or-disabled path when missing has no usable value.
    if not missing:
        # Return the action for the settings file, and any warning it raises to the caller.
        return Action(Kind.SKIP, path, before, before, "all permissions already allowed"), []
    # Update  settings action state only after the required source facts are available.
    permissions["allow"] = [*allow, *missing]
    # Update  settings action state only after the required source facts are available.
    settings["permissions"] = permissions
    # Return the action for the settings file, and any warning it raises to the caller.
    return Action(
        Kind.MERGE if before else Kind.CREATE, path, before, _dump(settings, newline),
        f"adding {len(missing)} permission entr(ies); existing entries kept",
    ), []


def _gitignore_action(path: Path, *, remove: bool,
                      added: Sequence[str] | None) -> tuple[Action, list[str]]:
    """Plan the ignore entries for the discipline's derived files.

    @param path the .gitignore
    @param remove whether to remove the entries
        True enables remove; false selects its disabled alternative.
    @param added the entries the record says the discipline added, or None when
        there is no record to consult
    @return the action for the ignore file, and any warning it raises
    """
    # Compute before using read preserving for later gitignore action logic.
    before = read_preserving(path) if path.exists() else ""
    # Compute newline using dominant newline for later gitignore action logic.
    newline = dominant_newline(before)

    # Handle the non-empty or enabled remove state.
    if remove:
        # Use the absence path when added has no available value.
        if added is None:
            # Return the action for the ignore file, and any warning it raises to the caller.
            return (Action(Kind.SKIP, path, before, before,
                           "no install record; ignore entries left in place"),
                    _unrecorded("ignore", GITIGNORE_ENTRIES, before.splitlines()))
        # Compute after using  without ignores for later gitignore action logic.
        after = _without_ignores(before, added, newline)
        # Select the guarded path only after `after == before` is satisfied.
        if after == before:
            # Return the action for the ignore file, and any warning it raises to the caller.
            return Action(Kind.SKIP, path, before, before,
                          "no entry the discipline added is still present"), []
        # Return the action for the ignore file, and any warning it raises to the caller.
        return Action(Kind.REMOVE, path, before, after, "removed the entries this "
                      "install added, and the header introducing them"), []

    # Format the relationship labels whose generated graph count is zero.
    missing = absent_ignores(before)
    # Select the empty-or-disabled path when missing has no usable value.
    if not missing:
        # Return the action for the ignore file, and any warning it raises to the caller.
        return Action(Kind.SKIP, path, before, before, "already ignored"), []
    # Compute prefix using before if not before or before.endswith(("\n", "\r")) else b for
    # Details: later gitignore action logic.
    prefix = before if not before or before.endswith(("\n", "\r")) else before + newline
    # Retain the immutable source representation consumed by subsequent analysis.
    body = newline.join([GITIGNORE_HEADER, *missing])
    # Return the action for the ignore file, and any warning it raises to the caller.
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
        Each element is one discipline-owned ignore line; order is deliberately unused for
        membership tests.
    @param newline the ending the file uses
    @return the file as it should read after removal
    """
    # Each kept element is one project-owned source line in original file order.
    kept: list[str] = []
    # Preserve the current decoded diagnostic line before location normalization.
    # Advance without ignores through the current input element in declared order.
    for line in before.splitlines():
        # Select the guarded path only after `line in added` is satisfied.
        if line in added:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Select the guarded path only after `added and line == GITIGNORE_HEADER` is satisfied.
        if added and line == GITIGNORE_HEADER:
            # Select the guarded path only after `kept and (not kept[-1].strip())` is satisfied.
            if kept and not kept[-1].strip():
                kept.pop()
            # Advance after the current candidate has been conclusively excluded.
            continue
        kept.append(line)
    # Select the empty-or-disabled path when kept has no usable value.
    if not kept:
        # Return the file as it should read after removal to the caller.
        return ""
    # Compute trailing using newline if before.endswith(("\n", "\r")) else "" for later without
    # Details: ignores logic.
    trailing = newline if before.endswith(("\n", "\r")) else ""
    # Return the file as it should read after removal to the caller.
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
        True enables remove; false selects its disabled alternative.
    @param wanted what the record should say after an installing run
        Each key is an integration-record section and each value is its ownership state; JSON
        insertion order is preserved for stable output.
    @return the action for the record, or nothing when there is none to write
    """
    # Use the absence path when remove and record has no available value.
    if remove and record is None:
        # Return the action for the record, or nothing when there is none to write to the
        # Details: caller.
        return []
    # Compute before using read preserving for later record actions logic.
    before = read_preserving(path) if path.exists() else ""
    # Compute after using json.dumps for later record actions logic.
    after = json.dumps(empty_record() if remove else wanted, indent=2,
                       ensure_ascii=False) + "\n"
    # Select the guarded path only after `after == before` is satisfied.
    if after == before:
        # Return the action for the record, or nothing when there is none to write to the
        # Details: caller.
        return [Action(Kind.SKIP, path, before, before, "install record already accurate")]
    # Compute reason using ("install record emptied; nothing of ours is installed" if r for
    # Details: later record actions logic.
    reason = ("install record emptied; nothing of ours is installed" if remove else
              "recording which entries were absent, so --remove takes back only those")
    # Return the action for the record, or nothing when there is none to write to the caller.
    return [Action(Kind.MERGE if before else Kind.CREATE, path, before, after, reason)]


def _dump(settings: dict[str, object], newline: str) -> str:
    """Serialize settings the way an editor would leave them.

    @param settings the settings mapping
        Each key is a Claude setting name and each value is its JSON content; insertion order is
        preserved for minimally disruptive output.
    @param newline the ending the file already used
    @return pretty-printed JSON with a trailing newline
    """
    # Return pretty-printed JSON with a trailing newline to the caller.
    return with_newline(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", newline)


def _is_git_repository(root: Path) -> bool:
    """Whether `root` is inside a git working tree.

    @param root the directory to test
    @return True when git reports a working tree
    """
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Preserve the external command representation and its observed completion outcome.
        finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv, no shell
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (OSError, subprocess.SubprocessError):
        # Return true when git reports a working tree to the caller.
        return False
    # Return true when git reports a working tree to the caller.
    return finished.returncode == 0 and finished.stdout.strip() == "true"


# ---------------------------------------------------------------- the apply


def apply(plan: Plan) -> list[Action]:
    """Apply every changing action. The plan is not recomputed here.

    @param plan the plan to apply
    @return the actions that were written or deleted

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Each written element is one completed changing action in plan application order.
    written: list[Action] = []
    # Select action as the current element from plan.changing while apply preserves traversal
    # Details: order.
    # Advance apply through the current input element in declared order.
    for action in plan.changing:
        # Select the guarded path only after `action.kind is Kind.DELETE` is satisfied.
        if action.kind is Kind.DELETE:
            # Publish the externally visible effect after all required inputs are ready.
            action.path.unlink()
            written.append(action)
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Publish the externally visible effect after all required inputs are ready.
        action.path.parent.mkdir(parents=True, exist_ok=True)
        write_preserving(action.path, action.after)
        written.append(action)
    # Return the actions that were written or deleted to the caller.
    return written


def render_plan(plan: Plan, root: Path, *, show_diff: bool) -> Iterator[str]:
    """Format a plan for a reader.

    @param plan the plan
    @param root the repository root, for display paths
    @param show_diff whether to include unified diffs
        True enables show diff; false selects its disabled alternative.
    @return the lines to print
    """
    # Select action as the current element from plan.actions while render plan preserves
    # Details: traversal order.
    # Advance render plan through the current input element in declared order.
    for action in plan.actions:
        # Normalize the current repository path to its portable baseline key spelling.
        name = action.path.relative_to(root).as_posix()
        # Compute mark using " " if action.kind is Kind.SKIP else "*" for later render plan
        # Details: logic.
        mark = " " if action.kind is Kind.SKIP else "*"
        yield f" {mark} {action.kind.value:<8} {name:<26} {action.reason}"
        # Select the guarded path only after `show_diff and action.changes` is satisfied.
        if show_diff and action.changes:
            # Preserve the current decoded diagnostic line before location normalization.
            yield from ("     " + line.rstrip("\r\n")
                        for line in action.diff(root).splitlines())
    # Select warning as the current element from plan.warnings while render plan preserves
    # Details: traversal order.
    # Advance render plan through the current input element in declared order.
    for warning in plan.warnings:
        yield f"\n   warning: {warning}"
    # Select problem as the current element from plan.problems while render plan preserves
    # Details: traversal order.
    # Advance render plan through the current input element in declared order.
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
        True enables remove; false selects its disabled alternative.
    @return the lines to print, describing what was done
    @throws FileNotFoundError when the hook directory is not there, because
        pointing git at a directory with no hooks would silently disable the
        hooks a project already had
    """
    # Compute hooks using root / agent_dir / "enforce" / "templates" / "hooks" for later install
    # Details: hooks logic.
    hooks = root / agent_dir / "enforce" / "templates" / "hooks"
    # Refuse the target when its declared source directory is absent.
    if not hooks.is_dir():
        # Compute hooks using root / "enforce" / "templates" / "hooks" for later install hooks
        # Details: logic.
        hooks = root / "enforce" / "templates" / "hooks"
    # Refuse the target when its declared source directory is absent.
    if not remove and not hooks.is_dir():
        # Propagate the localized failure so callers cannot mistake it for success.
        raise FileNotFoundError(hooks)

    # Handle the non-empty or enabled remove state.
    if remove:
        subprocess.run(("git", "config", "--unset", "core.hooksPath"),  # ruff: ignore[start-process-with-partial-path]
                       cwd=root, capture_output=True, text=True, check=False)
        # Return the lines to print, describing what was done to the caller.
        return ["core.hooksPath unset; git's default hooks are in force again"]

    # Compute relative using hooks.relative to for later install hooks logic.
    relative = hooks.relative_to(root).as_posix()
    # Preserve the external command representation and its observed completion outcome.
    finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        ("git", "config", "core.hooksPath", relative),  # ruff: ignore[start-process-with-partial-path]
        cwd=root, capture_output=True, text=True, check=False)
    # Enter the failure path only when the subprocess reports a nonzero status.
    if finished.returncode != 0:
        # Return the lines to print, describing what was done to the caller.
        return [f"could not set core.hooksPath: {finished.stderr.strip()}"]
    # Select h, installed as the current element from hooks.iterdir() if h.is_file()) while
    # Details: install hooks preserves traversal order.
    installed = sorted(h.name for h in hooks.iterdir() if h.is_file())
    # Return the lines to print, describing what was done to the caller.
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
        True enables remove; false selects its disabled alternative.
    @return the process exit status
    """
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Preserve the current decoded diagnostic line before location normalization.
        # Advance hooks command through the current input element in declared order.
        for line in install_hooks(root, agent_dir, remove=remove):
            print(line)
    # Bind absent to the current value used by the next hooks command decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except FileNotFoundError as absent:
        print(f"no hook directory at {absent}; nothing was configured, and "
              f"pointing git at it would have disabled the hooks this repository "
              f"already has", file=sys.stderr)
        # Return the process exit status to the caller.
        return 1
    # Return the process exit status to the caller.
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    @param argv command-line arguments, defaulting to `sys.argv`
    @return the process exit status
    """
    # Select the guarded path only after `hasattr(sys.stdout, 'reconfigure')` is satisfied.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Configure the command-line parser that defines this tool's invocation contract.
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
    # Capture the validated invocation arguments that govern this execution.
    args = parser.parse_args(argv)

    # Resolve the repository-confined path used by this operation before filesystem access.
    root = args.root.resolve()

    # Select the guarded path only after `args.hooks` is satisfied.
    if args.hooks:
        # Return the aggregate process status to the command-line boundary.
        return _hooks_command(root, args.agent_dir, remove=args.remove)

    # Compute plan using build plan for later main logic.
    plan = build_plan(root, args.agent_dir, remove=args.remove,
                      targets=args.only or MARKDOWN_TARGETS)

    # Select the guarded path only after `args.check` is satisfied.
    if args.check:
        # Compute stale using plan.changing for later main logic.
        stale = plan.changing
        # Preserve the current decoded diagnostic line before location normalization.
        # Advance main through the current input element in declared order.
        for line in render_plan(plan, root, show_diff=False):
            print(line)
        # Compute out using len for later main logic.
        out = len(stale) + len(plan.problems)
        print(f"\n{len(stale)} file(s) out of step, "
              f"{len(plan.problems)} blocking conflict(s)." if out
              else "\nagent configuration is in step with the discipline.")
        # Return the aggregate process status to the command-line boundary.
        return 1 if out else 0

    # Select the guarded path only after `args.dry_run` is satisfied.
    if args.dry_run:
        print("PLAN (nothing written)\n")
        # Preserve the current decoded diagnostic line before location normalization.
        # Advance main through the current input element in declared order.
        for line in render_plan(plan, root, show_diff=True):
            print(line)
        print(f"\n{len(plan.changing)} file(s) would change. Re-run without --dry-run to apply.")
        # Return the aggregate process status to the command-line boundary.
        return 1 if plan.problems else 0

    # Preserve the current decoded diagnostic line before location normalization.
    # Advance main through the current input element in declared order.
    for line in render_plan(plan, root, show_diff=False):
        print(line)
    # Compute written using apply for later main logic.
    written = apply(plan)
    # Compute verb using "removed from" if args.remove else "integrated into" for later main
    # Details: logic.
    verb = "removed from" if args.remove else "integrated into"
    print(f"\ndiscipline {verb} {len(written)} file(s).")
    # Select the empty-or-disabled path when args.remove and written has no usable value.
    if not args.remove and written:
        print("Start a fresh agent session so the new configuration is loaded.")
    # Return the aggregate process status to the command-line boundary.
    return 1 if plan.problems else 0


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    sys.exit(main())
