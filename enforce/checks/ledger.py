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

# Import the path contract only for static annotations.
if TYPE_CHECKING:
    from pathlib import Path

## Where the ledger lives relative to a repository root, and the name that marks
## a file as one when a check is pointed straight at it.
LEDGER_NAME = "ledger.jsonl"

## Unordered event-kind set whose each element is understood by ledger readers; an unknown
## kind means the writer advanced without its deciding checks.
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
    ## Mapping from each payload field-name key to its decoded value; field meaning depends on
    ## event kind and insertion order preserves the authored JSON object.
    payload: dict[str, Any]
    ## The line this event was read from, 1-based, for reporting a location.
    line: int


def is_ledger(path: Path) -> bool:
    """Whether a path names the learning ledger.

    @param path the file being considered
    @return true when it is a ``ledger.jsonl``; false otherwise
    """
    # Match the stable basename independently of the repository's absolute location.
    return path.name == LEDGER_NAME


def read(text: str) -> tuple[list[Event], list[tuple[int, str]]]:
    """Parse a ledger, keeping the lines that would not parse.

    A malformed line is returned rather than raised on, so a check can report it
    as a finding at its own line number instead of dying on the whole file.

    @param text the ledger's contents
    @return event elements in file order and malformed-line/reason pair elements in file order
    """
    # Accumulate parsed event-record elements in source order.
    events: list[Event] = []
    # Accumulate malformed line-number/reason pair elements in source order.
    broken: list[tuple[int, str]] = []
    # Examine each source-line element in increasing one-based order.
    for number, raw in enumerate(text.splitlines(), start=1):
        # Blank lines carry no event and do not alter sequence identity.
        if not raw.strip():
            # Advance without producing an event or malformed-line record.
            continue
        # Decode one line independently so later valid events remain inspectable.
        try:
            # Parse the line into an untrusted JSON value.
            record = json.loads(raw)
        # Preserve JSON parse failure as data for checker-owned reporting.
        except ValueError as exc:
            # Append the exact line and parser explanation in source order.
            broken.append((number, str(exc)))
            # Advance because a malformed value cannot be interpreted as an event.
            continue
        # Each append-log event must be represented by a JSON object.
        if not isinstance(record, dict):
            # Append a stable shape explanation at the exact line.
            broken.append((number, "not an object"))
            # Advance because a scalar or array cannot supply event fields.
            continue
        # Append the normalized event value while preserving source order and line identity.
        events.append(Event(
            seq=int(record.get("seq", 0)),
            kind=str(record.get("kind", "")),
            session=str(record.get("session", "")),
            payload=record.get("payload") or {},
            line=number,
        ))
    # Return both ordered sequences so callers can report syntax and semantic defects.
    return events, broken


def learnings(events: list[Event]) -> dict[str, dict[str, Any]]:
    """The current state of each learning, folded from the events in order.

    A later event about a learning replaces the earlier state, which is what
    makes a correction an append rather than an edit.

    @param events ledger event elements in file order
    @return mapping from each learning-id key to its most recent payload-field/value mapping;
        insertion order follows first learning declaration
    """
    # Map each learning-id key to its folded payload mapping value in first-seen order.
    folded: dict[str, dict[str, Any]] = {}
    # Apply each event-record element in append order.
    for event in events:
        # Normalize the referenced payload identity for stable key membership.
        identifier = str(event.payload.get("id", ""))
        # Events without a learning identity do not participate in per-learning folding.
        if not identifier.startswith("L-"):
            # Advance without inventing identity for session or calibration events.
            continue
        # A learn event establishes or, defectively, replaces the complete initial payload.
        if event.kind == "learn":
            # Copy each payload key/value pair while preserving authored mapping order.
            folded[identifier] = dict(event.payload)
        # Later recognized events update only an identity already established by learning.
        elif identifier in folded:
            # Merge payload fields and derived status while retaining first-id insertion order.
            folded[identifier] = {**folded[identifier], **event.payload,
                                  "status": _status_for(event.kind)}
    # Return the complete current-state mapping after ordered event application.
    return folded


def _status_for(kind: str) -> str:
    """The status an event of this kind leaves a learning in.

    @param kind the event kind
    @return the resulting status, or `candidate` for a kind that does not change it
    """
    # Map each terminal event-kind key to its resulting status value; mapping order is
    # deliberately irrelevant to direct key lookup.
    return {
        "refute": "refuted",
        "supersede": "superseded",
        "promote": "promoted",
    }.get(kind, "candidate")
