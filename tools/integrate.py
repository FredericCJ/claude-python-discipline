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
        # Deletion changes filesystem state even though its after-content is empty.
        return self.kind is Kind.DELETE or self.before != self.after

    def diff(self, root: Path) -> str:
        """A unified diff of the change, for the dry run.

        @param root the repository root, for display paths
        @return the diff text, empty when nothing changes
        """
        # Skip diff construction for actions whose before/after contract is identical.
        if not self.changes:
            # Empty text keeps no-op actions visible in the plan without a fake patch.
            return ""
        # Express the target from the repository root using portable patch-path separators.
        name = self.path.relative_to(root).as_posix()
        # Diff exact preserved lines so CRLF changes, if any, remain reviewable.
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
        # Preserve application order while selecting only actions with a filesystem effect.
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
    # Disable universal-newline translation for the complete read lifetime.
    with path.open(encoding="utf-8", newline="") as handle:
        # Decode UTF-8 while preserving every original carriage return.
        return handle.read()


def write_preserving(path: Path, text: str) -> None:
    """Write text with no line-ending translation of any kind.

    @param path the file to write, whose parent directory must exist
    @param text exactly the bytes to store, once encoded

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Disable output newline expansion so the planned text is the text stored on disk.
    with path.open("w", encoding="utf-8", newline="") as handle:
        # Commit the already-rendered content without host-dependent transformation.
        handle.write(text)


def dominant_newline(text: str) -> str:
    """Decide which line ending a file already uses.

    Ties and empty files go to LF, which is what a file the integrator creates
    itself uses and what the block is authored with.

    @param text the file as it stands
    @return CRLF when carriage returns are in the majority, LF otherwise
    """
    # Count CRLF pairs separately from the total newline count used to derive bare LF count.
    crlf = text.count("\r\n")
    # Choose CRLF only on a strict majority; ties and empty content retain the LF default.
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
    # Collapse authored endings to LF before expanding them uniformly to the host choice.
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
    # Render one compact session bootstrap whose marker carries exact package identity.
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
    # Absence means the vendored content predates or bypassed versioned packaging.
    if not manifest.exists():
        # Distinguish missing provenance from an unreadable manifest.
        return "unversioned"
    # Decode the manifest defensively because integration must still produce an actionable block.
    try:
        # Retain decoded manifest fields until the required object shape is established.
        recorded = json.loads(manifest.read_text(encoding="utf-8"))
    # Filesystem and JSON failures share the honest unreadable identity.
    except (json.JSONDecodeError, OSError):
        # Do not invent a hash or release from untrusted manifest bytes.
        return "unreadable"
    # Non-object JSON cannot carry named version and release fields.
    if not isinstance(recorded, dict):
        # Report the same unusable-manifest state as malformed JSON.
        return "unreadable"
    # Preserve the exact content stamp and add the optional human release label.
    stamp = str(recorded.get("version", "?"))
    release = recorded.get("release")
    # Keep the machine-comparable stamp present in both labeled and unlabeled forms.
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
    # No record grants no removal authority and therefore maps to the conservative None state.
    if not path.exists():
        # Preserve the explicit untrusted-absence result for every removal planner.
        return None
    # Parse provenance only when the complete UTF-8 JSON artifact is trustworthy.
    try:
        # Retain the decoded value until its required object shape is checked below.
        parsed = json.loads(path.read_text(encoding="utf-8"))
    # Any read, decode, or parse failure removes authority rather than guessing ownership.
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        # Treat damaged provenance exactly like no provenance: delete nothing automatically.
        return None
    # Only a mapping can carry versioned ownership fields; other JSON types grant nothing.
    return parsed if isinstance(parsed, dict) else None


def recorded_entries(record: dict[str, object] | None, key: str) -> tuple[str, ...] | None:
    """One recorded list of entries the discipline added.

    @param record the record as it stands, or None when there is none
    @param key which list to read
    @return the entries, empty when the record carries no such list, and None
            when there is no record at all -- the two must not be confused, since
            one authorises removal of nothing and the other forbids removal
    """
    # Preserve missing-record semantics because they explicitly forbid entry deletion.
    if record is None:
        # None remains distinct from a present record containing an empty owned list.
        return None
    # Read the named ownership list without trusting arbitrary record value types.
    value = record.get(key)
    # A present but invalid or absent list authorizes removal of no entries.
    if not isinstance(value, list):
        # Empty tuple represents the trusted zero-owned-entry state.
        return ()
    # Normalize each persisted entry to text while retaining recorded removal order.
    return tuple(str(item) for item in value)


def recorded_separator(record: dict[str, object] | None, name: str) -> str | None:
    """Look up the blank space an earlier apply inserted before one file's block.

    @param record the record as it stands, or None when there is none
    @param name the markdown target, as it is keyed in the record
    @return the recorded separator, or None when nothing was recorded for it
    """
    # Read the markdown ownership section from a present record or neutral empty mapping.
    markdown = (record or {}).get("markdown")
    # Invalid section shape grants no separator-removal authority.
    if not isinstance(markdown, dict):
        # Leave every target's surrounding whitespace project-owned.
        return None
    # Resolve the exact target entry before reading its separator contribution.
    entry = markdown.get(name)
    # Missing or malformed target provenance leaves surrounding whitespace project-owned.
    if not isinstance(entry, dict):
        # Return no separator rather than inferring ownership from current file layout.
        return None
    # Admit only textual separator bytes to the later conservative removal operation.
    separator = entry.get("separator")
    return separator if isinstance(separator, str) else None


def empty_record() -> dict[str, object]:
    """Build the record as it reads when nothing is installed.

    @return a record claiming no permission, ignore, markdown, or skill contribution
    """
    # Materialize every ownership section so trusted empty and missing remain distinguishable.
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
    # Begin with trusted prior ownership, treating no record as an empty installation history.
    kept = list(recorded_entries(record, key) or ())
    # Append genuinely new entries once while preserving historical removal order first.
    return [*kept, *(entry for entry in newly if entry not in kept)]


def _skills_record(record: dict[str, object] | None) -> dict[str, dict[str, object]]:
    """Recover per-path ownership and digests for native skill entry points.

    Invalid entries grant no deletion or replacement authority and are ignored.
    This is the same conservative rule used for a missing record: unexplained
    files belong to the project.

    @param record the install record as it stands, or None
    @return valid path-to-entry mappings, empty when none can be trusted
    """
    # Read the skill-ownership section without granting authority from non-mapping data.
    raw = (record or {}).get("skills")
    if not isinstance(raw, dict):
        # Empty mapping represents no trustworthy native-skill provenance.
        return {}
    # Copy only string path keys with mapping entries so callers cannot mutate the loaded record.
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
    # Hash exact UTF-8 contents, including line endings, before shortening display/storage width.
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _skill_ownership(entry: dict[str, object] | None) -> tuple[bool, str | None]:
    """Read the authority an integration-record skill entry grants.

    @param entry one path's record, or None when the path was never recorded
    @return whether this installer created it, and the digest it wrote
    """
    # An unrecorded path is project-owned and carries no expected installer digest.
    if entry is None:
        # Deny both creation authority and any digest-based replacement or deletion authority.
        return False, None
    # Read the recorded digest only when it has the textual shape produced by this installer.
    digest = entry.get("digest")
    # Creation authority requires an explicit true flag; all other values are conservative false.
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
    # Never replace symlinks, directories, or other non-regular project-owned entry points.
    if path.is_symlink() or (path.exists() and not path.is_file()):
        # Describe both the skipped action and blocking collision from the same observed shape.
        reason = "a non-regular path already occupies the skill entry point; left untouched"
        action = Action(Kind.SKIP, path, "", "", reason)
        next_entry = dict(entry) if entry is not None else {"created": False, "digest": ""}
        problem = f"cannot install the shared skill at {relative}: {reason}"
        # Preserve prior provenance while preventing an incomplete install from looking clean.
        return action, next_entry, problem
    # An absent regular file can be created safely and grants future deletion authority.
    if not path.is_file():
        # Plan exact canonical skill contents and record installer ownership plus digest.
        action = Action(
            Kind.CREATE, path, "", source,
            "creating the native entry point from the shared vendored skill",
        )
        return action, {"created": True, "digest": source_digest}, None

    # Compare existing bytes against both current source and the last installer-owned digest.
    before = read_preserving(path)
    created, expected = _skill_ownership(entry)
    # An already-current file needs no write but retains its established ownership status.
    if before == source:
        # Refresh the recorded digest even when content requires no mutation.
        action = Action(
            Kind.SKIP, path, before, before,
            "native skill already matches the shared vendored source",
        )
        return action, {"created": created, "digest": source_digest}, None
    # Replace only a file this installer created and whose bytes still match its prior digest.
    if created and expected is not None and _content_digest(before) == expected:
        # Upgrade the untouched owned copy to the new canonical shared skill.
        action = Action(
            Kind.REPLACE, path, before, source,
            "updating the unchanged skill file created by this install",
        )
        return action, {"created": True, "digest": source_digest}, None

    # Distinguish local edits to an owned file from a collision that was never installer-owned.
    reason = (
        "recorded skill was locally modified; left untouched" if created
        else "an unowned skill already exists at this path; left untouched"
    )
    # Preserve existing bytes and whatever trustworthy provenance was already recorded.
    action = Action(Kind.SKIP, path, before, before, reason)
    next_entry = (dict(entry) if entry is not None else
                  {"created": False, "digest": _content_digest(before)})
    # Surface the unresolved collision so callers cannot mistake partial integration for success.
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
    # Non-regular entry points are always project-owned regardless of stale record metadata.
    if path.is_symlink() or (path.exists() and not path.is_file()):
        # Plan no mutation and explain why provenance cannot authorize deletion.
        action = Action(
            Kind.SKIP, path, "", "",
            "non-regular skill entry point is project-owned; left untouched",
        )
        return action, [f"{relative} is not a regular file and was not removed"]
    # Absence already satisfies removal and needs neither warning nor filesystem action.
    if not path.is_file():
        # Keep the target accounted for explicitly in the uninstall plan.
        return Action(Kind.SKIP, path, "", "", "skill file absent"), []

    # Compare present bytes with the only record that could authorize deleting them.
    before = read_preserving(path)
    created, expected = _skill_ownership(entry)
    # A file not explicitly created by this installer belongs to the project.
    if not created:
        # Preserve it and warn only when ownership provenance is completely absent.
        action = Action(
            Kind.SKIP, path, before, before,
            "skill file was not created by this install; left untouched",
        )
        warning = (f"no {RECORD_NAME} ownership for {relative}; left it in place"
                   if entry is None else "")
        return action, [warning] if warning else []
    # Local edits revoke deletion authority even for a path originally created by integration.
    if expected is None or _content_digest(before) != expected:
        # Plan no mutation and disclose the digest/provenance mismatch.
        action = Action(
            Kind.SKIP, path, before, before,
            "skill file changed after integration; left untouched",
        )
        return action, [
            (f"{relative} differs from the copy this install wrote; it now "
             "belongs to the project and was not removed"),
        ]
    # Delete only an unchanged regular file whose creation and exact bytes are both recorded.
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
    # Bind the canonical skill source and recovered per-target ownership to this repository.
    source_path = root / agent_dir / SKILL_SOURCE_PATH
    installed = _skills_record(record)
    wanted = dict(installed)
    # Each actions element is one native-skill mutation in Claude-then-Codex target order.
    actions: list[Action] = []
    # Each warnings element is one conservative-removal note in skill-target order.
    warnings: list[str] = []
    # Each problems element is one project-owned skill collision in target order.
    problems: list[str] = []

    # Installation cannot expose a canonical skill that the vendored package does not carry.
    if not remove and not source_path.is_file():
        warnings.append(
            f"no shared skill found at {agent_dir}/{SKILL_SOURCE_PATH}; "
            "native Claude Code and Codex skill entry points were not planned"
        )
        # Return an empty skill plan while leaving Markdown and other integration work available.
        return actions, wanted, warnings, problems

    # Read and digest canonical contents once; uninstall needs neither value.
    source = "" if remove else read_preserving(source_path)
    source_digest = "" if remove else _content_digest(source)
    # Plan Claude then Codex native entry points in declared deterministic order.
    for relative in SKILL_TARGETS:
        # Resolve the repository-local discovery path and its prior provenance entry.
        path = root / relative
        entry = installed.get(relative)
        # Removal and installation have distinct authority decisions but share result aggregation.
        if remove:
            # Uninstall only provenance-intact skill copies and collect conservative warnings.
            action, notes = _remove_skill_action(path, relative, entry)
            actions.append(action)
            warnings.extend(notes)
            # Do not run installation planning for a removal target.
            continue
        # Install, refresh, or surface a collision for the current host discovery path.
        action, next_entry, problem = _install_skill_action(
            path, relative, source, source_digest, entry,
        )
        actions.append(action)
        wanted[relative] = next_entry
        # Blocking collisions are retained separately from non-blocking removal notes.
        if problem is not None:
            problems.append(problem)
    # Return ordered mutations, next ownership state, advisories, and blockers as one result.
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
    # Start an effect-free plan and render the exact versioned Markdown block once.
    plan = Plan()
    block = render_block(read_version(root, agent_dir), agent_dir)
    record_path = root / agent_dir / RECORD_NAME
    # Load integration-record field keys to recorded ownership values; mapping key order is
    # deliberately unused.
    record = load_record(record_path)

    # Warn when integration is being planned before the discipline corpus is actually vendored.
    if not (root / agent_dir / "discipline").exists():
        # Keep planning so dry-run output still explains every other target.
        plan.warnings.append(
            f"no discipline found at {agent_dir}/discipline -- run vendor.py install first"
        )

    # Each installed key is a managed Markdown filename and each value records its separator;
    # mapping key order is deliberately unused.
    installed: dict[str, object] = dict(_markdown_record(record))
    # Plan each host instruction file while preserving its recorded separator contribution.
    for name in targets:
        # Compute the Markdown mutation without touching the host file.
        action = _markdown_action(root / name, block, root, remove=remove,
                                  separator=recorded_separator(record, name))
        plan.actions.append(action)
        # Record only separators newly introduced by an insertion this run owns.
        if not remove and action.kind is Kind.INSERT:
            # Persist exact blank-space ownership needed for byte-preserving uninstall.
            installed[name] = {"separator": _separator(action.before)}

    # Plan both native skill mirrors and merge their ownership diagnostics into the main plan.
    skill_actions, installed_skills, skill_notes, skill_problems = _skill_actions(
        root, agent_dir, record, remove=remove,
    )
    plan.actions += skill_actions
    plan.warnings += skill_notes
    plan.problems += skill_problems

    # Plan structured Claude permissions and derived-artifact ignore entries independently.
    settings, settings_notes = _settings_action(
        root / SETTINGS_PATH, remove=remove,
        added=recorded_entries(record, "permissions_added"))
    ignores, ignore_notes = _gitignore_action(
        root / ".gitignore", remove=remove,
        added=recorded_entries(record, "gitignore_added"))
    plan.actions += [settings, ignores]
    plan.warnings += settings_notes + ignore_notes

    # Plan the provenance record last from ownership actually observed by all earlier actions.
    plan.actions += _record_actions(record_path, record, remove=remove, wanted={
        "record_version": RECORD_VERSION,
        "permissions_added": _merged(record, "permissions_added",
                                     absent_permissions(settings.before)),
        "gitignore_added": _merged(record, "gitignore_added",
                                   absent_ignores(ignores.before)),
        "markdown": installed,
        "skills": installed_skills,
    })

    # Installation outside Git has no history-based undo, so make that risk visible before apply.
    if not remove and not _is_git_repository(root):
        plan.warnings.append(
            "this is not a git repository, so there is no undo -- review the dry run first"
        )
    # Expose the complete effect-free plan in exact application order.
    return plan


def _markdown_record(record: dict[str, object] | None) -> dict[str, object]:
    """Recover what the record already says about the markdown targets.

    @param record the record as it stands, or None when there is none
    @return the per-file entries, empty when there are none
    """
    # Copy the Markdown ownership section only when the record carries a mapping.
    markdown = (record or {}).get("markdown")
    return dict(markdown) if isinstance(markdown, dict) else {}


def _separator(before: str) -> str:
    """Choose the blank space to insert between existing content and an appended block.

    @param before the file as it stands, never empty on this path
    @return the run of newlines leaving exactly one blank line before the block
    """
    # Match the host file's dominant ending when calculating the inserted blank-line run.
    newline = dominant_newline(before)
    # Existing blank separation needs no additional bytes owned by the integrator.
    if before.endswith(newline * 2):
        # Record an empty separator so removal leaves all existing whitespace untouched.
        return ""
    # Add one or two endings according to whether the host already terminates its final line.
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
    # Snapshot existence and exact bytes before deciding create, replace, insert, or removal.
    exists = path.exists()
    before = read_preserving(path) if exists else ""
    # Locate any prior managed region independently of its embedded discipline version.
    found = BLOCK_RE.search(before)

    # Removal touches only marker-owned content and any explicitly recorded separator.
    if remove:
        # A host with no managed region is already in the requested state.
        if found is None:
            # Account for the target without changing its project-owned bytes.
            return Action(Kind.SKIP, path, before, before, "no managed block present")
        # Delegate byte-exact excision because separator provenance affects its boundary.
        return _removal(path, before, found, separator)

    # Render generated block endings to match the existing host before any comparison.
    rendered = with_newline(block, dominant_newline(before))
    # Greenfield integration creates only a title and the managed bootstrap block.
    if not exists:
        # Preserve the host's future ownership by generating no additional project policy.
        return Action(
            Kind.CREATE, path, "", f"# {root.name}\n\n" + rendered,
            "file absent; creating a minimal one -- the rest is the project's to write",
        )
    # Existing managed regions are replaced wholesale, leaving every outside byte unchanged.
    if found is not None:
        # Substitute exactly one region and classify equality separately from stale replacement.
        after = BLOCK_RE.sub(lambda _: rendered, before, count=1)
        reason = ("managed block already current" if after == before
                  else "managed block replaced; everything outside it is untouched")
        kind = Kind.SKIP if after == before else Kind.REPLACE
        return Action(kind, path, before, after, reason)

    # Append a first managed region with exactly the separator this installation records.
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
    # Start from the exact marker match boundary before considering separately owned whitespace.
    start = found.start()
    # Remove the preceding separator only when record and current bytes agree exactly.
    if separator and before[max(start - len(separator), 0):start] == separator:
        # Excision restores the host prefix to the byte preceding integration-owned whitespace.
        return Action(Kind.REMOVE, path, before,
                      before[:start - len(separator)] + before[found.end():],
                      "managed block removed, with the blank space it was inserted after")
    # Explain whether retained whitespace was known project content or lacked ownership evidence.
    reason = ("managed block removed" if separator is not None else
              "managed block removed; no install record, so any blank line inserted "
              "before it is left in place")
    # Remove only marker-owned bytes when separator provenance is absent or no longer matches.
    return Action(Kind.REMOVE, path, before, before[:start] + before[found.end():], reason)


def parse_settings(before: str) -> dict[str, object] | None:
    """Parse the settings file, or report that it cannot be used.

    @param before the file as it stands, empty when it does not exist
    @return the parsed mapping, empty for an empty file, and None when the
            content is not JSON or not an object
    """
    # Empty or whitespace-only settings are the valid empty-object bootstrap state.
    if not before.strip():
        # Return a mutable empty mapping ready for structured permission merge.
        return {}
    # Parse complete JSON before granting structured merge authority.
    try:
        # Retain the decoded value until top-level object shape is validated below.
        parsed = json.loads(before)
    # Invalid JSON makes the file project-owned opaque text rather than a merge target.
    except json.JSONDecodeError:
        # None tells the caller to skip rather than overwrite an unparseable host file.
        return None
    # Only an object supports the named ``permissions`` section this integrator edits.
    return parsed if isinstance(parsed, dict) else None


def allowed_entries(settings: dict[str, object] | None) -> list[str]:
    """Read the permissions the project currently grants.

    @param settings the parsed settings, or None when they could not be read
    @return the entries, empty when there are none to read
    """
    # Resolve the nested permissions object from a valid mapping or neutral empty state.
    permissions = (settings or {}).get("permissions")
    # Read ``allow`` only from a structured permissions object.
    allow = permissions.get("allow") if isinstance(permissions, dict) else None
    # Normalize list entries to strings in host order; malformed values grant no entries.
    return [str(entry) for entry in allow] if isinstance(allow, list) else []


def absent_permissions(before: str) -> list[str]:
    """Which of our permission entries the project does not already have.

    This is the whole basis of the record: exactly these are added by an apply,
    so exactly these may later be taken back.

    @param before the settings file as it stands
    @return our entries that are missing, in our order
    """
    # Determine absence only from safely parsed structured settings.
    settings = parse_settings(before)
    # Opaque settings cannot justify any planned addition or later ownership claim.
    if settings is None:
        # Report no absent entries because the integrator cannot safely add any.
        return []
    # Compare existing allowances against the fixed discipline permission order.
    allow = allowed_entries(settings)
    return [entry for entry in PERMISSIONS if entry not in allow]


def absent_ignores(before: str) -> list[str]:
    """Which of our ignore entries the project does not already have.

    @param before the ignore file as it stands
    @return our entries that are missing, in our order
    """
    # Compare exact ignore lines as a set while emitting missing entries in declaration order.
    present = set(before.splitlines())
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
    # Silence the conservative warning when no discipline-shaped entries remain present.
    if not leftover:
        # Empty warning list keeps a clean removal plan quiet.
        return []
    # Explain precisely why value equality cannot establish removal ownership.
    told = (
        f"no {RECORD_NAME} from an earlier apply, so {len(leftover)} {kind} entr(ies) "
        f"were left in place: {', '.join(leftover)} -- this install predates the record, "
        f"and nothing distinguishes an entry the discipline added from one the project "
        f"already had. Remove them by hand if they are not yours."
    )
    # Return one consolidated warning naming every deliberately retained ambiguous entry.
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
    # Snapshot exact host bytes and parse structured settings before any merge decision.
    before = read_preserving(path) if path.exists() else ""
    settings = parse_settings(before)
    # Opaque or non-object JSON is left untouched rather than reconstructed by guesswork.
    if settings is None:
        # Plan an explicit skip so dry run exposes the unmodified opaque settings file.
        return Action(Kind.SKIP, path, before, before,
                      "settings file is not valid JSON or not an object; left alone "
                      "rather than guessed at"), []

    # Preserve host newline style and all permission categories outside the allow-list.
    newline = dominant_newline(before)
    stored = settings.get("permissions")
    # Each permissions key is a Claude permission category and each value is its configured
    # entries; insertion order is preserved when rewriting JSON but has no policy meaning.
    permissions: dict[str, object] = dict(stored) if isinstance(stored, dict) else {}
    allow = allowed_entries(settings)

    # Removal is governed exclusively by recorded ownership, never by matching values alone.
    if remove:
        # No record means no entry is safe to remove automatically.
        if added is None:
            # Retain every allowance and explain any discipline-shaped values left behind.
            return (Action(Kind.SKIP, path, before, before,
                           "no install record; permission entries left in place"),
                    _unrecorded("permission", PERMISSIONS, allow))
        # Each kept element is one permission not owned by this install, in existing file order.
        kept = [entry for entry in allow if entry not in added]
        # Equality means every recorded contribution was already absent.
        if kept == allow:
            # Preserve settings bytes when uninstall has no remaining owned allowance to remove.
            return Action(Kind.SKIP, path, before, before,
                          "no entry the discipline added is still present"), []
        # Replace only the allow-list with its project-owned ordered remainder.
        permissions["allow"] = kept
        settings["permissions"] = permissions
        # Serialize the minimally changed settings object with the host's newline style.
        return Action(Kind.MERGE, path, before, _dump(settings, newline),
                      f"removed {len(allow) - len(kept)} permission entr(ies) this "
                      f"install added"), []

    # Each missing element is one required permission absent from the existing allow-list, in
    # discipline declaration order.
    missing = [entry for entry in PERMISSIONS if entry not in allow]
    # A complete permission set requires no rewrite or new ownership claim.
    if not missing:
        # Preserve exact settings formatting when policy already contains every required entry.
        return Action(Kind.SKIP, path, before, before, "all permissions already allowed"), []
    # Append only absent discipline entries after every existing project allowance.
    permissions["allow"] = [*allow, *missing]
    settings["permissions"] = permissions
    # Create or merge according to prior file presence while preserving unrelated settings.
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
    # Snapshot exact ignore bytes and choose the same newline style for generated additions.
    before = read_preserving(path) if path.exists() else ""
    newline = dominant_newline(before)

    # Removal takes back only ignore lines named by the installation record.
    if remove:
        # Without provenance, retain all matching lines and report the ambiguous residue.
        if added is None:
            # Plan no mutation and attach the conservative ownership warning.
            return (Action(Kind.SKIP, path, before, before,
                           "no install record; ignore entries left in place"),
                    _unrecorded("ignore", GITIGNORE_ENTRIES, before.splitlines()))
        # Remove recorded lines and their installer-owned header while retaining host order.
        after = _without_ignores(before, added, newline)
        # An already-clean file requires no write.
        if after == before:
            # Preserve bytes when no recorded ignore contribution remains present.
            return Action(Kind.SKIP, path, before, before,
                          "no entry the discipline added is still present"), []
        # Publish the exact byte-preserving removal planned by the helper.
        return Action(Kind.REMOVE, path, before, after, "removed the entries this "
                      "install added, and the header introducing them"), []

    # Identify only discipline-derived paths not already ignored by the project.
    missing = absent_ignores(before)
    # A complete ignore set requires no new block or ownership entry.
    if not missing:
        # Preserve exact ignore formatting when all required paths are already covered.
        return Action(Kind.SKIP, path, before, before, "already ignored"), []
    # Terminate preexisting content before appending the discipline-owned block.
    prefix = before if not before or before.endswith(("\n", "\r")) else before + newline
    # Render the header followed by missing paths in declaration order.
    body = newline.join([GITIGNORE_HEADER, *missing])
    # Add one separating newline and a final terminator in the host style.
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
    # Inspect source lines in original order, retaining only project-owned or unrelated content.
    for line in before.splitlines():
        # Drop exact ignore entries whose installation ownership is recorded.
        if line in added:
            # Continue without copying this installer-owned line.
            continue
        # Remove the installer header only when at least one owned entry set was supplied.
        if added and line == GITIGNORE_HEADER:
            # Take back at most the single blank separator immediately preceding the header.
            if kept and not kept[-1].strip():
                kept.pop()
            # Continue without retaining the now-obsolete installer header.
            continue
        kept.append(line)
    # An empty remainder produces an actually empty ignore file.
    if not kept:
        # Avoid retaining a newline or header after the last project-owned line disappears.
        return ""
    # Preserve whether the original file ended with a newline after joining retained lines.
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
        True enables remove; false selects its disabled alternative.
    @param wanted what the record should say after an installing run
        Each key is an integration-record section and each value is its ownership state; JSON
        insertion order is preserved for stable output.
    @return the action for the record, or nothing when there is none to write
    """
    # Removing an installation that never had a record must not create provenance debris.
    if remove and record is None:
        # Empty action list represents the deliberate no-record no-op.
        return []
    # Snapshot existing record bytes and render the complete desired ownership state.
    before = read_preserving(path) if path.exists() else ""
    after = json.dumps(empty_record() if remove else wanted, indent=2,
                       ensure_ascii=False) + "\n"
    # Avoid rewriting an already exact ownership record.
    if after == before:
        # Retain the record as an accounted-for skip action in the plan.
        return [Action(Kind.SKIP, path, before, before, "install record already accurate")]
    # Explain whether the record is relinquishing or establishing removal authority.
    reason = ("install record emptied; nothing of ours is installed" if remove else
              "recording which entries were absent, so --remove takes back only those")
    # Create the first record or replace the existing one as the final planned action.
    return [Action(Kind.MERGE if before else Kind.CREATE, path, before, after, reason)]


def _dump(settings: dict[str, object], newline: str) -> str:
    """Serialize settings the way an editor would leave them.

    @param settings the settings mapping
        Each key is a Claude setting name and each value is its JSON content; insertion order is
        preserved for minimally disruptive output.
    @param newline the ending the file already used
    @return pretty-printed JSON with a trailing newline
    """
    # Pretty-print stable mapping order, add one terminator, then adopt the host newline style.
    return with_newline(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", newline)


def _is_git_repository(root: Path) -> bool:
    """Whether `root` is inside a git working tree.

    @param root the directory to test
    @return True when git reports a working tree
    """
    # Ask Git directly without inheriting shell parsing or emitting its diagnostic output.
    try:
        # Retain the completed probe for both exit-status and exact affirmative-output checks.
        finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv, no shell
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    # Missing Git, timeout, or startup failure all mean no available history-backed undo.
    except (OSError, subprocess.SubprocessError):
        # Report the conservative non-repository verdict instead of propagating probe failure.
        return False
    # Require both successful completion and Git's canonical affirmative answer.
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
    # Execute the immutable plan in declared order without recomputing any decisions.
    for action in plan.changing:
        # Deletion is authorized only for actions whose planning phase proved ownership.
        if action.kind is Kind.DELETE:
            # Remove the exact planned file, then record completion before advancing.
            action.path.unlink()
            written.append(action)
            # Skip creation/write handling for the completed deletion.
            continue
        # Materialize parent directories only for actions that will write a file.
        action.path.parent.mkdir(parents=True, exist_ok=True)
        # Store the exact planned bytes with newline translation disabled.
        write_preserving(action.path, action.after)
        written.append(action)
    # Expose only successfully completed mutations in application order.
    return written


def render_plan(plan: Plan, root: Path, *, show_diff: bool) -> Iterator[str]:
    """Format a plan for a reader.

    @param plan the plan
    @param root the repository root, for display paths
    @param show_diff whether to include unified diffs
        True enables show diff; false selects its disabled alternative.
    @return the lines to print
    """
    # Render every target, including skips, so the plan accounts for the complete integration.
    for action in plan.actions:
        # Express target paths relative to the repository with portable separators.
        name = action.path.relative_to(root).as_posix()
        # Distinguish no-op accounting from filesystem mutations at a glance.
        mark = " " if action.kind is Kind.SKIP else "*"
        yield f" {mark} {action.kind.value:<8} {name:<26} {action.reason}"
        # Dry-run detail uses the exact action diff only for effective changes.
        if show_diff and action.changes:
            # Indent unified-diff lines without retaining their transport newline terminators.
            yield from ("     " + line.rstrip("\r\n")
                        for line in action.diff(root).splitlines())
    # Append advisory notes after all target actions in discovery order.
    for warning in plan.warnings:
        yield f"\n   warning: {warning}"
    # Append blocking collisions last so incomplete integration cannot be overlooked.
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
    # Prefer hooks inside a vendored agent directory, with source-repository layout as fallback.
    hooks = root / agent_dir / "enforce" / "templates" / "hooks"
    if not hooks.is_dir():
        # Resolve the source-tree hook location used when running integration before vendoring.
        hooks = root / "enforce" / "templates" / "hooks"
    # Installation must not redirect Git to an empty directory that disables existing hooks.
    if not remove and not hooks.is_dir():
        # Fail before changing configuration and name the absent directory as the repair subject.
        raise FileNotFoundError(hooks)

    # Removal restores Git's default hook discovery without requiring the old directory to exist.
    if remove:
        # Unset is idempotent; a missing value is not a failure for uninstall semantics.
        subprocess.run(("git", "config", "--unset", "core.hooksPath"),  # ruff: ignore[start-process-with-partial-path]
                       cwd=root, capture_output=True, text=True, check=False)
        # Report the effective default-hook state after the best-effort unset.
        return ["core.hooksPath unset; git's default hooks are in force again"]

    # Store a repository-relative portable path so the configured checkout remains relocatable.
    relative = hooks.relative_to(root).as_posix()
    # Apply the local Git configuration and retain diagnostics instead of raising generically.
    finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        ("git", "config", "core.hooksPath", relative),  # ruff: ignore[start-process-with-partial-path]
        cwd=root, capture_output=True, text=True, check=False)
    # Return Git's concrete diagnostic when the configuration mutation did not complete.
    if finished.returncode != 0:
        # Keep command failure recoverable by returning stderr as operator-facing output.
        return [f"could not set core.hooksPath: {finished.stderr.strip()}"]
    # Enumerate regular hook files now active through the configured pointer.
    installed = sorted(h.name for h in hooks.iterdir() if h.is_file())
    # Explain pointer, active hooks, bypass, and explicit removal as one operator handoff.
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
    # Configure or remove hooks and translate only the expected missing-directory condition.
    try:
        # Print each operator-facing hook result line in the order installation produced it.
        for line in install_hooks(root, agent_dir, remove=remove):
            print(line)
    # Explain why refusing configuration preserves any hooks the repository already owns.
    except FileNotFoundError as absent:
        print(f"no hook directory at {absent}; nothing was configured, and "
              f"pointing git at it would have disabled the hooks this repository "
              f"already has", file=sys.stderr)
        # Status one distinguishes safe refusal from successful hook configuration.
        return 1
    # All hook configuration output was published successfully.
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    @param argv command-line arguments, defaulting to `sys.argv`
    @return the process exit status
    """
    # Prefer UTF-8 replacement output where the host stream supports reconfiguration.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Define the mutually composable plan, check, removal, hook, and target controls.
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
    # Parse one validated invocation before resolving repository paths or planning effects.
    args = parser.parse_args(argv)

    # Canonicalize the selected repository root once for every subsequent target calculation.
    root = args.root.resolve()

    # Hook configuration is an independent explicit mode and bypasses file integration planning.
    if args.hooks:
        # Return the dedicated hook-path status directly to the process boundary.
        return _hooks_command(root, args.agent_dir, remove=args.remove)

    # Compute the complete immutable plan before check, dry-run, or application branches diverge.
    plan = build_plan(root, args.agent_dir, remove=args.remove,
                      targets=args.only or MARKDOWN_TARGETS)

    # Check mode reports stale targets and blockers without writing any path.
    if args.check:
        # Snapshot effective mutations so counting and status derive from the same plan.
        stale = plan.changing
        # Render the complete no-diff accounting before the aggregate verdict.
        for line in render_plan(plan, root, show_diff=False):
            print(line)
        out = len(stale) + len(plan.problems)
        print(f"\n{len(stale)} file(s) out of step, "
              f"{len(plan.problems)} blocking conflict(s)." if out
              else "\nagent configuration is in step with the discipline.")
        # Any stale file or blocking collision makes integration check fail closed.
        return 1 if out else 0

    # Dry-run mode renders exact diffs from the same plan apply would execute.
    if args.dry_run:
        print("PLAN (nothing written)\n")
        # Show all actions and effective unified diffs without invoking the apply boundary.
        for line in render_plan(plan, root, show_diff=True):
            print(line)
        print(f"\n{len(plan.changing)} file(s) would change. Re-run without --dry-run to apply.")
        # Blocking collisions fail dry run even though recoverable planned changes remain visible.
        return 1 if plan.problems else 0

    # Apply mode first publishes the no-diff plan, then executes exactly its changing actions.
    for line in render_plan(plan, root, show_diff=False):
        print(line)
    written = apply(plan)
    verb = "removed from" if args.remove else "integrated into"
    print(f"\ndiscipline {verb} {len(written)} file(s).")
    # A successful nonempty installation requires a fresh session to load host instructions.
    if not args.remove and written:
        print("Start a fresh agent session so the new configuration is loaded.")
    # Completed recoverable actions do not hide any blocking partial-integration conflicts.
    return 1 if plan.problems else 0


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    sys.exit(main())
