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

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class LedgerAppendOnlyCheck(TextCheck):
    """Reports a gap, a reordering or a duplicate in the ledger's sequence."""

    ## Invoked as `python -m checks.ledger_append_only`.
    name = "ledger_append_only"
    ## The law/LEARN rule this check decides.
    rules = ("LEARN-005",)
    ## The ledger is JSONL.
    suffixes = (".jsonl",)

    def visit_text(self, text: str, path: Path) -> Iterator[Finding]:
        """Yield findings for any break in the append-only sequence.

        @param text the ledger's contents
        @param path the file it was read from
        @return one finding per gap, reordering, malformed line or duplicate id
        """
        if not ledger.is_ledger(path):
            return

        events, broken = ledger.read(text)
        for line, reason in broken:
            yield Finding(
                "LEARN-005", path, line,
                f"line does not parse as an event: {reason}",
                "Every line is one appended JSON object. A line that will not "
                "parse is a line something edited by hand.",
            )

        expected = 1
        for event in events:
            if event.seq != expected:
                yield Finding(
                    "LEARN-005", path, event.line,
                    f"sequence jumps from {expected} to {event.seq}",
                    "The ledger is append-only: a gap means a line was removed, "
                    "and with it the evidence for whatever it recorded. A "
                    "contradicted learning is refuted, never deleted.",
                )
                expected = event.seq
            expected += 1

        seen: dict[str, int] = {}
        for event in events:
            if event.kind != "learn":
                continue
            identifier = str(event.payload.get("id", ""))
            if identifier in seen:
                yield Finding(
                    "LEARN-005", path, event.line,
                    f"{identifier} is recorded a second time, first at line "
                    f"{seen[identifier]}",
                    "Append a correction or a refutation rather than a second "
                    "entry; the first one's text is otherwise unreachable.",
                )
            else:
                seen[identifier] = event.line


if __name__ == "__main__":
    raise SystemExit(main(LedgerAppendOnlyCheck()))
