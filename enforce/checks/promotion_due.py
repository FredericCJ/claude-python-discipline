"""A learning that can be checked becomes a check.

Enforces `LEARN-009`, the rule that makes the learning database a staging area
for mechanisms rather than a notes pile. An entry carrying a command that decides
it is a mechanism waiting to be written; leaving it as advice means every session
re-reads a paragraph a gate could have enforced once and then forgotten about.

**What this decides.** An entry is *due* when it carries a verification command,
has met the configured evidence threshold, and is still a candidate. Those are
the corpus's own terms, read from `learning/config.toml` rather than restated
here, so the check and the writer cannot disagree about the bar.

**What it does not decide.** Whether the resulting check would be worth its false
positives -- which, on the evidence of the last two batches, is the part that
actually takes judgement.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from . import Finding, TextCheck, ledger, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Evidence a verified entry needs before promotion is due, when none is
## configured. One, because the check *is* the evidence: an entry carrying a
## command that passes has already demonstrated what a mechanism would assert.
DEFAULT_MIN_EVIDENCE_VERIFIED = 1

## The configured threshold for an entry that carries a verification command.
_MIN_VERIFIED = re.compile(r"^min_evidence_verified\s*=\s*(?P<value>\d+)", re.MULTILINE)

## Unordered settled-status set whose each element has already left the candidate pool.
SETTLED = frozenset({"refuted", "superseded", "promoted"})


class PromotionDueCheck(TextCheck):
    """Reports a learning that has met the promotion bar and is still advice."""

    ## Invoked as `python -m checks.promotion_due`.
    name = "promotion_due"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("LEARN-009",)
    ## File-suffix elements in deterministic matching order for JSONL ledgers.
    suffixes = (".jsonl",)

    def visit_text(self, text: str, path: Path) -> Iterator[Finding]:
        """Yield a finding per learning that is due for promotion.

        @param text the ledger's contents
        @param path the file it was read from
        @return finding elements sorted by learning id, one per due unacted entry
        """
        # Ignore JSONL files that do not declare the learning-ledger schema.
        if not ledger.is_ledger(path):
            # Stop iteration without presenting unrelated JSONL as conforming ledger data.
            return

        # Decode event elements in append order; parsing diagnostics are owned by ``ledger``.
        events, _ = ledger.read(text)
        # Fold events into a mapping from each learning-id key to current-state value.
        folded = ledger.learnings(events)
        # Resolve the local evidence threshold or its stable fallback.
        threshold = _threshold(path)
        # Map each helped learning-id key to its reported-outcome count value.
        outcomes = _outcomes(events)

        # Examine each learning key/value pair in sorted identifier order.
        for identifier, entry in sorted(folded.items()):
            # Settled entries no longer await promotion from candidate advice.
            if entry.get("status", "candidate") in SETTLED:
                # Advance without reopening a resolved lifecycle state.
                continue
            # Advice without a verification command is not mechanically promotable.
            if not entry.get("verification"):
                # Advance because semantic judgment still owns its possible promotion.
                continue
            # Select the observed helped-outcome count, defaulting an unseen id to zero.
            reported = outcomes.get(identifier, 0)
            # Evidence below the configured threshold has not yet earned promotion.
            if reported < threshold:
                # Advance until future append events supply enough outcomes.
                continue
            # Yield the due-promotion finding for the sorted learning identity.
            yield Finding(
                "LEARN-009", path, 1,
                f"{identifier} carries a verification command and has {reported} "
                f"reported outcome(s), at or over the threshold of {threshold}",
                "Turn it into a check and retire the entry. A learning that can be "
                "enforced once should not be re-read every session.",
            )


def _threshold(path: Path) -> int:
    """The evidence a verified entry needs before promotion is due.

    @param path the ledger, whose directory is searched for `config.toml`
    @return the configured threshold, or the default

    @par Effects
    Reads the adjacent ``config.toml`` when it exists.
    """
    # Derive the one configuration path adjacent to the selected ledger.
    config = path.parent / "config.toml"
    # Absence selects the stable default without treating configuration as required.
    if not config.is_file():
        # Return the package fallback evidence threshold.
        return DEFAULT_MIN_EVIDENCE_VERIFIED
    # Search the decoded configuration snapshot for the authored numeric threshold.
    found = _MIN_VERIFIED.search(config.read_text(encoding="utf-8"))
    # Return the configured integer when present, otherwise the stable fallback.
    return int(found.group("value")) if found else DEFAULT_MIN_EVIDENCE_VERIFIED


def _outcomes(events: list[ledger.Event]) -> dict[str, int]:
    """How many times each learning has been reported as having helped.

    @param events ledger event elements in append order
    @return mapping from each learning-id key to its helped-outcome count value;
        insertion order follows first helped use
    """
    # Map each helped learning-id key to its running outcome-count value; insertion order
    # follows the first helped use for that identity.
    counted: dict[str, int] = {}
    # Examine each event-record element in append order.
    for event in events:
        # Only helped use events contribute evidence toward promotion.
        if event.kind != "used" or event.payload.get("outcome") != "helped":
            # Advance without counting neutral or harmful outcomes.
            continue
        # Normalize the referenced learning identity for dictionary membership.
        identifier = str(event.payload.get("id", ""))
        # Increment the count while preserving first-helped insertion order.
        counted[identifier] = counted.get(identifier, 0) + 1
    # Return the complete per-learning outcome mapping.
    return counted


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(PromotionDueCheck()))
