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

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## The ceiling in force when no configuration is found beside the ledger.
DEFAULT_MAX_ACTIVE = 200

## The configured ceiling, as `config.toml` writes it.
_MAX_ACTIVE = re.compile(r"^max_active\s*=\s*(?P<value>\d+)", re.MULTILINE)

## Unordered retired-status set whose each element keeps an entry for audit but excludes it
## from active advice and the configured ceiling.
RETIRED = frozenset({"refuted", "superseded", "promoted"})


class LearningSizeCheck(TextCheck):
    """Reports an active set that has grown past the ceiling without triage."""

    ## Invoked as `python -m checks.learning_size`.
    name = "learning_size"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("LEARN-010",)
    ## File-suffix elements in deterministic matching order for JSONL ledgers.
    suffixes = (".jsonl",)

    def visit_text(self, text: str, path: Path) -> Iterator[Finding]:
        """Yield a finding when the active set exceeds the configured ceiling.

        @param text the ledger's contents
        @param path the file it was read from
        @return zero or one finding element when the ceiling is passed
        """
        # Ignore JSONL files that do not declare the learning-ledger schema.
        if not ledger.is_ledger(path):
            # Stop iteration without presenting unrelated JSONL as conforming ledger data.
            return

        # Decode event elements in append order; parsing diagnostics are owned by ``ledger``.
        events, _ = ledger.read(text)
        # Fold the append log into a mapping from each learning-id key to current-state value.
        folded = ledger.learnings(events)
        # Preserve mapping order while selecting each entry not carrying a retired status.
        active = [i for i, entry in folded.items()
                  if entry.get("status", "candidate") not in RETIRED]
        # Resolve the local configured ceiling or its stable fallback.
        ceiling = _ceiling(path)
        # Report only when active learning cardinality exceeds the selected bound.
        if len(active) > ceiling:
            # Yield the aggregate size finding at the ledger root.
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

    @par Effects
    Reads the adjacent ``config.toml`` when it exists.
    """
    # Derive the one configuration path adjacent to the selected ledger.
    config = path.parent / "config.toml"
    # Absence selects the stable default without treating configuration as required.
    if not config.is_file():
        # Return the package fallback ceiling.
        return DEFAULT_MAX_ACTIVE
    # Search the decoded configuration snapshot for the authored numeric ceiling.
    found = _MAX_ACTIVE.search(config.read_text(encoding="utf-8"))
    # Return the configured integer when present, otherwise the stable fallback.
    return int(found.group("value")) if found else DEFAULT_MAX_ACTIVE


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(LearningSizeCheck()))
