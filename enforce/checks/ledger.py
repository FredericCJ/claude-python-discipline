"""Reading the learning ledger, shared by the five checks that examine it.

`LEARN-001`, `-004`, `-005`, `-009` and `-010` each name their own mechanism, so
each is its own module. All five read the same file, and duplicating the parse
five times would guarantee that four of them eventually disagree with the fifth
about what an event is.

Defines no `Check` subclass, so the discovery in `checks/__main__.py`,
`build_graph.py` and `test_meta.py` correctly does not treat it as a mechanism --
the same reason `project.py` is not one.

**The ledger is the durable record; the SQLite index is derived.** These checks
read the JSONL and never the database, so they decide what is committed rather
than what someone's working copy happens to have folded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

## Where the ledger lives relative to a repository root, and the name that marks
## a file as one when a check is pointed straight at it.
LEDGER_NAME = "ledger.jsonl"

## Event kinds the ledger records. A check reading an unknown kind says so rather
## than ignoring it: an unrecognised event means the writer moved on and the
## reader did not.
KNOWN_KINDS = frozenset({"session", "learn", "used", "refute", "supersede",
                         "promote", "calibrate"})


@dataclass(frozen=True, slots=True)
class Event:
    """One appended record, as the ledger holds it."""

    ## Position in the ledger, 1-based and contiguous. A gap means a line was
    ## removed, which an append-only log forbids.
    seq: int
    ## What happened: one of `KNOWN_KINDS`.
    kind: str
    ## The session that appended it.
    session: str
    ## The event's body, whose shape depends on the kind.
    payload: dict[str, Any]
    ## The line this event was read from, 1-based, for reporting a location.
    line: int


def is_ledger(path: Path) -> bool:
    """Whether a path names the learning ledger.

    @param path the file being considered
    @return True when it is a `ledger.jsonl`
    """
    return path.name == LEDGER_NAME


def read(text: str) -> tuple[list[Event], list[tuple[int, str]]]:
    """Parse a ledger, keeping the lines that would not parse.

    A malformed line is returned rather than raised on, so a check can report it
    as a finding at its own line number instead of dying on the whole file.

    @param text the ledger's contents
    @return the events in file order, and one (line, reason) per unparsable line
    """
    events: list[Event] = []
    broken: list[tuple[int, str]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except ValueError as exc:
            broken.append((number, str(exc)))
            continue
        if not isinstance(record, dict):
            broken.append((number, "not an object"))
            continue
        events.append(Event(
            seq=int(record.get("seq", 0)),
            kind=str(record.get("kind", "")),
            session=str(record.get("session", "")),
            payload=record.get("payload") or {},
            line=number,
        ))
    return events, broken


def learnings(events: list[Event]) -> dict[str, dict[str, Any]]:
    """The current state of each learning, folded from the events in order.

    A later event about a learning replaces the earlier state, which is what
    makes a correction an append rather than an edit.

    @param events the ledger's events, in file order
    @return each learning id against its most recent recorded payload
    """
    folded: dict[str, dict[str, Any]] = {}
    for event in events:
        identifier = str(event.payload.get("id", ""))
        if not identifier.startswith("L-"):
            continue
        if event.kind == "learn":
            folded[identifier] = dict(event.payload)
        elif identifier in folded:
            folded[identifier] = {**folded[identifier], **event.payload,
                                  "status": _status_for(event.kind)}
    return folded


def _status_for(kind: str) -> str:
    """The status an event of this kind leaves a learning in.

    @param kind the event kind
    @return the resulting status, or `candidate` for a kind that does not change it
    """
    return {
        "refute": "refuted",
        "supersede": "superseded",
        "promote": "promoted",
    }.get(kind, "candidate")
