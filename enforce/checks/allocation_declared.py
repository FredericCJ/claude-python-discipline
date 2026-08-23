"""The tier-to-model mapping exists, and every dispatch cites a tier it resolves.

Decides `ALLOC-010`, which was `[OPEN]` from the day it was written. Its blocker
was real: the rule needs a tier-to-model table, `ALLOC-001` forbids naming a model
in a project document, and `OPEN-006` recorded the deadlock rather than pretending
either half away.

The way out is the one `[tool.agent-discipline]` already established -- **declare
it, then be checked on it**. The corpus still names no model. What is checked is
that a mapping EXISTS in project-owned space and that every dispatch record cites
a tier the mapping resolves, which is exactly what `OPEN-006` said was missing:
without it "a tier names a role rather than a verifiable choice, and a dispatch
under this rule cannot be audited after the fact."

**What this does not check.** Whether the mapping is *good* -- whether T2 really is
your strongest model -- is unknowable from here and belongs to whoever owns the
file. What is knowable is whether a dispatch cites a tier that means anything, and
that is the half that was unauditable.

A tree with no dispatch records and no mapping is silent: a repository that
dispatches nothing needs no allocation table, and demanding one would be the
over-reporting that made five `ARCH-002` findings wrong against real code.

    python -m checks.allocation_declared
"""

from __future__ import annotations

import re
import tomllib
from typing import TYPE_CHECKING, Final

from . import Finding, TextCheck, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Where an adopter's mapping lives. Project-owned, created once by the installer
## and never overwritten, so a declaration survives every update.
DECLARATION: Final = "allocation.toml"

## Search-directory elements in nearest-first precedence order for the allocation declaration.
SEARCH: Final[tuple[str, ...]] = ("overrides", ".agent/overrides")

## Unordered placeholder-value set whose each element means nobody filled the mapping in.
## A mapping carrying one of these is a
## copied template, not a declaration, and the rule it would otherwise satisfy is
## the one about a tier resolving to a real choice.
##
## THIS LIST EXISTS BECAUSE THE FIRST VERSION SHIPPED WITHOUT IT. The template
## offered "your-strongest-model", which resolves, so an adopter who changed
## nothing passed `ALLOC-010` -- a check satisfied by a file nobody had read, in
## the repository whose whole subject is checks that decide nothing.
UNFILLED: Final[frozenset[str]] = frozenset({
    "unset", "unassigned", "todo", "tbd", "changeme", "xxx", "",
})

## A `verified` date that nobody set. The epoch is what a placeholder looks like.
EPOCH: Final = "1970-01-01"

## A tier cited in a dispatch record, as `ops/ALLOC-002` writes them.
_TIER = re.compile(r"\bT([0-2])\b")

## The heading that marks a file as carrying a dispatch record at all. Only such
## files are examined: a document that dispatches nothing has no tier to resolve.
_DISPATCH = re.compile(r"##\s*Dispatch record", re.IGNORECASE)


class AllocationDeclaredCheck(TextCheck):
    """Rejects a dispatch citing a tier no mapping resolves.

    Silent on a tree that dispatches nothing, and silent on the tiers themselves:
    which model a tier names is the operating organization's business and cannot
    be judged from here.
    """

    ## Invoked as `python -m checks.allocation_declared`.
    name = "allocation_declared"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("ALLOC-010",)
    ## File-suffix elements in deterministic matching order for Markdown dispatch records.
    suffixes = (".md",)

    def visit_text(self, text: str, path: Path) -> Iterator[Finding]:
        """Yield a finding for each dispatch citing an unresolvable tier.

        @param text the file's contents
        @param path the file it was read from
        @return finding elements in template then sorted unresolved-tier order
        """
        # Markdown without the dispatch heading has no allocation resolution obligation.
        if not _DISPATCH.search(text):
            # Stop iteration without treating ordinary prose as a dispatch record.
            return
        # Build an unordered set whose each element is one cited normalized tier identity.
        cited = {f"T{m.group(1)}" for m in _TIER.finditer(text)}
        # A dispatch heading with no tier citation provides nothing this mechanism can resolve.
        if not cited:
            # Stop without inventing an allocation choice.
            return

        # Resolve the nearest mapping, its source label, and ordered placeholder descriptions.
        mapping, source, unfilled = self._mapping(path)
        # An existing mapping with placeholder values is an unedited template, not authority.
        if mapping is not None and unfilled:
            # Yield one aggregate placeholder finding in deterministic discovery order.
            yield Finding(
                "ALLOC-010", path, 1,
                f"{source} is an unedited template: {', '.join(unfilled)}",
                "Fill the mapping in. A tier resolving to a placeholder resolves "
                "to nothing a dispatch can be audited against, which is the "
                "condition this rule exists to end.",
            )
            # Stop because unresolved template content supersedes missing-tier details.
            return
        # Complete absence makes every cited tier unauditable through one root cause.
        if mapping is None:
            # Yield one aggregate missing-mapping finding with tier elements sorted.
            yield Finding(
                "ALLOC-010", path, 1,
                f"dispatches at {', '.join(sorted(cited))} and no tier mapping "
                f"was found",
                f"Copy enforce/templates/{DECLARATION} to overrides/{DECLARATION} "
                f"and fill it in. Until a tier resolves to something, it names a "
                f"role rather than a choice, and the dispatch cannot be audited.",
            )
            # Stop because no per-tier comparison is possible without a mapping.
            return

        # Report each cited tier absent from mapping keys in lexical order.
        for tier in sorted(cited - set(mapping)):
            # Yield the unresolved-tier finding at the dispatch record head.
            yield Finding(
                "ALLOC-010", path, 1,
                f"dispatches at {tier}, which {source} does not resolve",
                f"Add {tier} to the [tiers] table, or dispatch at a tier that "
                f"exists. A cited tier nothing resolves is unauditable.",
            )

    def _mapping(self, path: Path) -> tuple[dict[str, str] | None, str, list[str]]:
        """The nearest allocation declaration above `path`, and what it leaves unset.

        Walked upward rather than read from a fixed location, for the same reason
        the project declaration is: the check runs against a vendored `.agent/`
        as readily as against this repository.

        @param path the file being examined
        @return mapping from each tier key to model-name value preserving TOML order, source
            filename, and placeholder-description elements in detection order; no mapping
            returns ``(None, "", [])``

        @par Effects
        Searches ancestor directories and reads the first allocation declaration found.
        """
        # Search each ancestor-path element from the file itself outward to filesystem root.
        for parent in [path.resolve(), *path.resolve().parents]:
            # Search each declaration-directory element in nearest-first precedence order.
            for where in SEARCH:
                # Compose the exact candidate allocation declaration path.
                candidate = parent / where / DECLARATION
                # Only an existing regular declaration file can terminate discovery.
                if candidate.is_file():
                    # Decode one immutable TOML declaration snapshot.
                    try:
                        # Parse strict UTF-8 text into an untrusted table mapping.
                        document = tomllib.loads(
                            candidate.read_text(encoding="utf-8"))
                    # Treat unreadable or malformed declaration as unresolved authority.
                    except (OSError, tomllib.TOMLDecodeError):
                        # Return the stable absence triple without scanning farther authority.
                        return None, "", []
                    # Map each authored tier key to its model spelling value in TOML order.
                    tiers = {str(k): str(v)
                             for k, v in document.get("tiers", {}).items()}
                    # Select the metadata key/value mapping, preserving authored order.
                    meta = document.get("meta", {})
                    # Collect placeholder-description elements in authored tier order.
                    unfilled = [
                        f"{name} is {value!r}" for name, value in tiers.items()
                        if str(value).strip().lower() in UNFILLED
                    ]
                    # Only when the key is PRESENT and unfilled. An absent
                    # `[meta]` block is a shorter file, not a placeholder, and
                    # rejecting one would be the over-reporting that made five
                    # ARCH-002 findings wrong against real code.
                    # A present epoch verification date proves the template was not reviewed.
                    if str(meta.get("verified", "")).strip() == EPOCH:
                        # Append the verification placeholder after tier placeholders.
                        unfilled.append("verified is the epoch")
                    # A present owner key with placeholder content likewise remains unassigned.
                    if ("owner" in meta
                            and str(meta["owner"]).strip().lower() in UNFILLED):
                        # Append the owner placeholder last in deterministic metadata order.
                        unfilled.append("owner is unassigned")
                    # Return the first declaration under the nearest-first search contract.
                    return tiers, str(candidate.name), unfilled
        # No ancestor and search-directory combination supplied an allocation declaration.
        return None, "", []


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(AllocationDeclaredCheck()))
