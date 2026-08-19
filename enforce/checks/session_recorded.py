"""A session records what it learned before reporting done.

Enforces `LEARN-001`. The obligation is small and the failure it prevents is
large: a session that solved something and wrote nothing down has spent its
discovery, and the next session pays for it again. This repository has already
watched that happen -- the first calibration run found the database held a defect
that a later session rediscovered independently, because nothing prompted a
retrieval before the work started.

The rule admits recording *nothing*, which is honest and common: many sessions
learn nothing worth a durable entry. What it does not admit is a session that
opened the ledger, did work, and closed without deciding either way. This check
reports exactly that -- a `session` event with no event of its own after it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import Finding, TextCheck, ledger, main

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Event kinds that count as a session having decided something. Reporting an
## outcome or a refutation is as much a record as making a claim -- arguably
## more, since it is the half the calibration numbers are computed from.
DECIDING = frozenset({"learn", "used", "refute", "supersede", "promote", "calibrate"})


class SessionRecordedCheck(TextCheck):
    """Reports a session that opened the ledger and recorded nothing at all."""

    ## Invoked as `python -m checks.session_recorded`.
    name = "session_recorded"
    ## The law/LEARN rule this check decides.
    rules = ("LEARN-001",)
    ## The ledger is JSONL.
    suffixes = (".jsonl",)

    def visit_text(self, text: str, path: Path) -> Iterator[Finding]:
        """Yield a finding for each session that decided nothing.

        @param text the ledger's contents
        @param path the file it was read from
        @return one finding per silent session
        """
        if not ledger.is_ledger(path):
            return

        events, _ = ledger.read(text)
        opened = {e.session: e for e in events if e.kind == "session"}
        decided = {e.session for e in events if e.kind in DECIDING}
        for session, event in opened.items():
            if session not in decided:
                yield Finding(
                    "LEARN-001", path, event.line,
                    f"session {session!r} recorded nothing",
                    "Record what the session learned, or record that it learned "
                    "nothing. A session that spent its discovery and wrote none of "
                    "it down makes the next session pay for it again.",
                )


if __name__ == "__main__":
    raise SystemExit(main(SessionRecordedCheck()))
