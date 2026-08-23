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

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Unordered deciding-event set whose each element proves a session recorded an outcome;
## refutation and use count as decisions just as a new learning does.
DECIDING = frozenset({"learn", "used", "refute", "supersede", "promote", "calibrate"})


class SessionRecordedCheck(TextCheck):
    """Reports a session that opened the ledger and recorded nothing at all."""

    ## Invoked as `python -m checks.session_recorded`.
    name = "session_recorded"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("LEARN-001",)
    ## File-suffix elements in deterministic matching order for JSONL ledgers.
    suffixes = (".jsonl",)

    def visit_text(self, text: str, path: Path) -> Iterator[Finding]:
        """Yield a finding for each session that decided nothing.

        @param text the ledger's contents
        @param path the file it was read from
        @return finding elements in ledger session order, one per silent session
        """
        # Ignore JSONL files that do not declare the learning-ledger schema.
        if not ledger.is_ledger(path):
            # Stop iteration without presenting unrelated JSONL as conforming ledger data.
            return

        # Decode event elements in append order; parsing diagnostics are owned by ``ledger``.
        events, _ = ledger.read(text)
        # Map each opened session-id key to its opening-event value in append order.
        opened = {e.session: e for e in events if e.kind == "session"}
        # Build an unordered set whose each element is a session id with a deciding event.
        decided = {e.session for e in events if e.kind in DECIDING}
        # Examine each opened session key/value pair in ledger insertion order.
        for session, event in opened.items():
            # An opened session absent from the deciding set spent knowledge without closure.
            if session not in decided:
                # Yield the silent-session finding at its opening event line.
                yield Finding(
                    "LEARN-001", path, event.line,
                    f"session {session!r} recorded nothing",
                    "Record what the session learned, or record that it learned "
                    "nothing. A session that spent its discovery and wrote none of "
                    "it down makes the next session pay for it again.",
                )


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(SessionRecordedCheck()))
