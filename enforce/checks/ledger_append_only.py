"""A contradicted learning is refuted, never deleted.

Enforces `LEARN-005`. The ledger is append-only by contract, and this is what
makes that contract checkable rather than merely stated: sequence numbers run
from one without gaps, so a removed line is visible as arithmetic.

The rule matters because of what a deletion destroys. A learning that turned out
to be wrong is *evidence* -- it says something looked true to a session that had
reason to believe it. Deleting the entry deletes the reason it was believed, and
the next session is free to rediscover it. Refuting keeps both the claim and its
refutation, which is the only form in which either is useful.

A second defect is checked here for the same reason: a learning appearing twice
under one id means two `learn` events were appended for the same entry, so the
first one's text is silently unreachable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import Finding, TextCheck, ledger, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class LedgerAppendOnlyCheck(TextCheck):
    """Reports a gap, a reordering or a duplicate in the ledger's sequence."""

    ## Invoked as `python -m checks.ledger_append_only`.
    name = "ledger_append_only"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("LEARN-005",)
    ## File-suffix elements in deterministic matching order for JSONL ledgers.
    suffixes = (".jsonl",)

    def visit_text(self, text: str, path: Path) -> Iterator[Finding]:
        """Yield findings for any break in the append-only sequence.

        @param text the ledger's contents
        @param path the file it was read from
        @return finding elements in validation order for malformed lines, sequence breaks,
            and duplicate learning ids
        """
        # Ignore JSONL files that do not declare the learning-ledger schema.
        if not ledger.is_ledger(path):
            # Stop iteration without presenting unrelated JSONL as conforming ledger data.
            return

        # Decode event and malformed-line elements in append order.
        events, broken = ledger.read(text)
        # Report each malformed-line pair in source order before semantic sequence checks.
        for line, reason in broken:
            # Yield the parse finding at the exact malformed line.
            yield Finding(
                "LEARN-005", path, line,
                f"line does not parse as an event: {reason}",
                "Every line is one appended JSON object. A line that will not "
                "parse is a line something edited by hand.",
            )

        # Track the next contiguous sequence number expected from append-only history.
        expected = 1
        # Examine each parsed event element in append order.
        for event in events:
            # Any mismatch proves deletion, reordering, or an invalid starting sequence.
            if event.seq != expected:
                # Yield the discontinuity finding at the observed event line.
                yield Finding(
                    "LEARN-005", path, event.line,
                    f"sequence jumps from {expected} to {event.seq}",
                    "The ledger is append-only: a gap means a line was removed, "
                    "and with it the evidence for whatever it recorded. A "
                    "contradicted learning is refuted, never deleted.",
                )
                # Resynchronize so one gap produces one localized diagnostic.
                expected = event.seq
            # Advance to the sequence number required after the observed event.
            expected += 1

        # Map each learned identifier key to the line of its first learn-event value;
        # insertion order follows first appearance in the ledger.
        seen: dict[str, int] = {}
        # Examine every event element again in append order for duplicate learning identity.
        for event in events:
            # Only original learn events establish identities; later event kinds reference them.
            if event.kind != "learn":
                # Advance without treating a refutation or use as a duplicate declaration.
                continue
            # Normalize the payload identity to diagnostic text.
            identifier = str(event.payload.get("id", ""))
            # A repeated learn identity makes the earlier payload unreachable when folded.
            if identifier in seen:
                # Yield the duplicate at its later declaration and cite the first line.
                yield Finding(
                    "LEARN-005", path, event.line,
                    f"{identifier} is recorded a second time, first at line "
                    f"{seen[identifier]}",
                    "Append a correction or a refutation rather than a second "
                    "entry; the first one's text is otherwise unreachable.",
                )
            # The first declaration becomes the stable comparison origin.
            else:
                # Record the line value under its identifier key in insertion order.
                seen[identifier] = event.line


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(LedgerAppendOnlyCheck()))
