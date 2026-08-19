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

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Where an adopter's mapping lives. Project-owned, created once by the installer
## and never overwritten, so a declaration survives every update.
DECLARATION: Final = "allocation.toml"

## Directories the declaration may sit in, nearest first.
SEARCH: Final[tuple[str, ...]] = ("overrides", ".agent/overrides")

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
    ## The law/ops rule this mechanism decides.
    rules = ("ALLOC-010",)
    ## Dispatch records are written in markdown, beside the agents they describe.
    suffixes = (".md",)

    def visit_text(self, text: str, path: Path) -> Iterator[Finding]:
        """Yield a finding for each dispatch citing an unresolvable tier.

        @param text the file's contents
        @param path the file it was read from
        @return one ALLOC-010 finding per unresolved tier, at the file's head
        """
        if not _DISPATCH.search(text):
            return
        cited = {f"T{m.group(1)}" for m in _TIER.finditer(text)}
        if not cited:
            return

        mapping, source = self._mapping(path)
        if mapping is None:
            yield Finding(
                "ALLOC-010", path, 1,
                f"dispatches at {', '.join(sorted(cited))} and no tier mapping "
                f"was found",
                f"Copy enforce/templates/{DECLARATION} to overrides/{DECLARATION} "
                f"and fill it in. Until a tier resolves to something, it names a "
                f"role rather than a choice, and the dispatch cannot be audited.",
            )
            return

        for tier in sorted(cited - set(mapping)):
            yield Finding(
                "ALLOC-010", path, 1,
                f"dispatches at {tier}, which {source} does not resolve",
                f"Add {tier} to the [tiers] table, or dispatch at a tier that "
                f"exists. A cited tier nothing resolves is unauditable.",
            )

    def _mapping(self, path: Path) -> tuple[dict[str, str] | None, str]:
        """The nearest allocation declaration above `path`, and where it was found.

        Walked upward rather than read from a fixed location, for the same reason
        the project declaration is: the check runs against a vendored `.agent/`
        as readily as against this repository.

        @param path the file being examined
        @return the `[tiers]` table and the file it came from, or `(None, "")`
        """
        for parent in [path.resolve(), *path.resolve().parents]:
            for where in SEARCH:
                candidate = parent / where / DECLARATION
                if candidate.is_file():
                    try:
                        document = tomllib.loads(
                            candidate.read_text(encoding="utf-8"))
                    except (OSError, tomllib.TOMLDecodeError):
                        return None, ""
                    tiers = document.get("tiers", {})
                    return ({str(k): str(v) for k, v in tiers.items()},
                            str(candidate.name))
        return None, ""


if __name__ == "__main__":
    raise SystemExit(main(AllocationDeclaredCheck()))
