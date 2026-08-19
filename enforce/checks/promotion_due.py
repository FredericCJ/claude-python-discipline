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

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Evidence a verified entry needs before promotion is due, when none is
## configured. One, because the check *is* the evidence: an entry carrying a
## command that passes has already demonstrated what a mechanism would assert.
DEFAULT_MIN_EVIDENCE_VERIFIED = 1

## The configured threshold for an entry that carries a verification command.
_MIN_VERIFIED = re.compile(r"^min_evidence_verified\s*=\s*(?P<value>\d+)", re.MULTILINE)

## Statuses that have already left the candidate pool.
SETTLED = frozenset({"refuted", "superseded", "promoted"})


class PromotionDueCheck(TextCheck):
    """Reports a learning that has met the promotion bar and is still advice."""

    ## Invoked as `python -m checks.promotion_due`.
    name = "promotion_due"
    ## The law/LEARN rule this check decides.
    rules = ("LEARN-009",)
    ## The ledger is JSONL.
    suffixes = (".jsonl",)

    def visit_text(self, text: str, path: Path) -> Iterator[Finding]:
        """Yield a finding per learning that is due for promotion.

        @param text the ledger's contents
        @param path the file it was read from
        @return one finding per entry over the bar and unacted on
        """
        if not ledger.is_ledger(path):
            return

        events, _ = ledger.read(text)
        folded = ledger.learnings(events)
        threshold = _threshold(path)
        outcomes = _outcomes(events)

        for identifier, entry in sorted(folded.items()):
            if entry.get("status", "candidate") in SETTLED:
                continue
            if not entry.get("verification"):
                continue
            reported = outcomes.get(identifier, 0)
            if reported < threshold:
                continue
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
    """
    config = path.parent / "config.toml"
    if not config.is_file():
        return DEFAULT_MIN_EVIDENCE_VERIFIED
    found = _MIN_VERIFIED.search(config.read_text(encoding="utf-8"))
    return int(found.group("value")) if found else DEFAULT_MIN_EVIDENCE_VERIFIED


def _outcomes(events: list[ledger.Event]) -> dict[str, int]:
    """How many times each learning has been reported as having helped.

    @param events the ledger's events
    @return each learning id against its count of `helped` outcomes
    """
    counted: dict[str, int] = {}
    for event in events:
        if event.kind != "used" or event.payload.get("outcome") != "helped":
            continue
        identifier = str(event.payload.get("id", ""))
        counted[identifier] = counted.get(identifier, 0) + 1
    return counted


if __name__ == "__main__":
    raise SystemExit(main(PromotionDueCheck()))
