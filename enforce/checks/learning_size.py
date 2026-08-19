"""The active set is triaged before it outgrows its ceiling.

Enforces `LEARN-010`. A database nobody prunes becomes a database nobody reads,
and the decay is gradual enough that no single session notices it: retrieval
returns more, each result is worth less, and at some point an agent stops asking.

The ceiling is a parameter rather than a constant because it is meant to be
calibrated. It is read from `learning/config.toml` when that file sits beside the
ledger, so this check and the writer cannot disagree about what the ceiling is --
the same reason the promotion thresholds are read rather than restated.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from . import Finding, TextCheck, ledger, main

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## The ceiling in force when no configuration is found beside the ledger.
DEFAULT_MAX_ACTIVE = 200

## The configured ceiling, as `config.toml` writes it.
_MAX_ACTIVE = re.compile(r"^max_active\s*=\s*(?P<value>\d+)", re.MULTILINE)

## Statuses that have left the active set. They stay in the log for audit, not
## for advice, so they do not count against the ceiling.
RETIRED = frozenset({"refuted", "superseded", "promoted"})


class LearningSizeCheck(TextCheck):
    """Reports an active set that has grown past the ceiling without triage."""

    ## Invoked as `python -m checks.learning_size`.
    name = "learning_size"
    ## The law/LEARN rule this check decides.
    rules = ("LEARN-010",)
    ## The ledger is JSONL.
    suffixes = (".jsonl",)

    def visit_text(self, text: str, path: Path) -> Iterator[Finding]:
        """Yield a finding when the active set exceeds the configured ceiling.

        @param text the ledger's contents
        @param path the file it was read from
        @return one finding when the ceiling is passed
        """
        if not ledger.is_ledger(path):
            return

        events, _ = ledger.read(text)
        folded = ledger.learnings(events)
        active = [i for i, entry in folded.items()
                  if entry.get("status", "candidate") not in RETIRED]
        ceiling = _ceiling(path)
        if len(active) > ceiling:
            yield Finding(
                "LEARN-010", path, 1,
                f"{len(active)} active learnings against a ceiling of {ceiling}",
                "Triage before accumulating further: promote what can become a "
                "check, refute what is wrong, supersede what has been replaced. A "
                "set nobody prunes becomes a set nobody reads.",
            )


def _ceiling(path: Path) -> int:
    """The configured ceiling, or the default when none is declared.

    @param path the ledger, whose directory is searched for `config.toml`
    @return the maximum active-set size
    """
    config = path.parent / "config.toml"
    if not config.is_file():
        return DEFAULT_MAX_ACTIVE
    found = _MAX_ACTIVE.search(config.read_text(encoding="utf-8"))
    return int(found.group("value")) if found else DEFAULT_MAX_ACTIVE


if __name__ == "__main__":
    raise SystemExit(main(LearningSizeCheck()))
