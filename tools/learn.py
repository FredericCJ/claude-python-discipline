"""The learning database: what using the discipline in this repository taught.

    python tools/learn.py record --kind diagnostic --claim "..." --action "..." \
        --trigger error:"adapters are independent" --link ARCH-003
    python tools/learn.py retrieve --file src/pkg/adapters/fs.py --error "..."
    python tools/learn.py used L-0001 --outcome helped
    python tools/learn.py verify --execute
    python tools/learn.py sync
    python tools/learn.py calibrate

Two stores with different jobs. `learning/ledger.jsonl` is append-only, sorted
and committed: it is the durable record, reviewable in a diff and mergeable
without conflict. `learning/learning.db` is a query index rebuilt from it, never
committed. Drift between them is a validation error, not a nuisance.

Everything is an event. A correction, a refutation, a usage outcome and a
calibration change are all appended, so history is never lost and the material
calibration needs is a by-product of ordinary use rather than extra bookkeeping.

Retrieval is deterministic: triggers either match or they do not. An
unreproducible retrieval could not be reviewed, and could not be calibrated.

`verify` replays the commands entries recorded against themselves, which is the
one staleness signal here that needs nobody's honesty. It executes strings that
came out of a data file, so it is deliberately awkward: nothing runs without
`--execute`, no shell is ever involved, and only an allowlisted entry point is
started at all.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tomllib
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from discipline_core import REPO_ROOT, count_tokens

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

## The version this build stamps on the index it writes. Nothing ever compares
## it: a sync rebuilds from the ledger unconditionally, so an index left by an
## older tool is discarded rather than migrated, and the stamp only says what
## wrote the file that is there now.
SCHEMA_VERSION: Final = 1

## The ways a situation may be recognised. A trigger outside this set is refused
## at parse time, because it would produce an entry nothing could ever retrieve.
## Each element is one accepted trigger-kind spelling; declaration order is preserved.
TRIGGER_TYPES: Final = ("glob", "error", "rule", "command", "term")
## The taxonomy a recorded claim must fall into, and the key each entry's decay
## half-life is looked up by. `write.kinds_enabled` may narrow it further. Kept
## short because a list nobody can choose from quickly collapses into one bucket.
## Each element is one claim-kind spelling in command-line presentation order.
LEARNING_KINDS: Final = ("diagnostic", "constraint", "procedure", "rule-application", "defect")
## Statuses that end an entry's working life: `_restatus` never revisits one, and
## retrieval drops it whatever its confidence unless `retrieval.include_retired`
## asks for it back.
## Each element is one terminal status; order is deliberately unused for membership tests.
RETIRED: Final = ("superseded", "refuted", "promoted")

## Material that must never enter the ledger. The ledger is designed to be read
## widely and machine-processed, which is exactly what makes a credential in it
## expensive. DIAG-014 applied to ourselves.
## Each element pairs a credential regex with its refusal description, in scan order.
SECRET_PATTERNS: Final[tuple[tuple[str, str], ...]] = (
    (r"(?i)\b(api[_-]?key|secret|token|password|passwd|bearer|authorization)\b\s*[:=]\s*\S{6,}",
     "a key/value pair naming a credential"),
    (r"\bAKIA[0-9A-Z]{16}\b", "an AWS access key id"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "a private key block"),
    (r"\bgh[pousr]_[A-Za-z0-9]{16,}\b", "a GitHub token"),
    (r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", "a Slack token"),
    (r"\b[0-9a-f]{40,}\b", "a long hex string, which may be a secret"),
    (r"(?i)[/\\](?:home|users)[/\\][A-Za-z0-9._-]+[/\\]", "an absolute home-directory path"),
)

## The executable names that mean "the interpreter". A command naming one of
## these is run under `sys.executable` instead, so a verification cannot pick up
## whichever interpreter happens to be first on PATH.
## Each element is one admitted Python launcher spelling in declaration order.
PYTHON_EXECUTABLES: Final[tuple[str, ...]] = ("python", "python3", "py")
## The only programs a verification command may start. A ledger can arrive from
## another repository through `vendor` and `harvest`, so the entry point is
## treated as untrusted input: anything outside this list is refused by name and
## counted, never quietly skipped.
## Each element is one admitted verification executable spelling; declaration order is retained.
VERIFY_EXECUTABLES: Final[tuple[str, ...]] = (*PYTHON_EXECUTABLES, "pytest", "ruff", "doxygen")
## The top-level packages `python -m` may launch. Narrower than the executable
## list because `-m` reaches anything importable, including the standard library.
## Each element is one admitted top-level module spelling; declaration order is retained.
VERIFY_MODULES: Final[tuple[str, ...]] = (
    "pytest", "ruff", "mypy", "pyright", "checks", "tools", "enforce",
)
## Executables run through the interpreter rather than found on PATH, mapped to
## the module that provides them. `python -m ruff` and the `ruff` on PATH are the
## same program, and going through the interpreter means one fewer path to trust.
## Each key is an executable spelling and each value is its interpreter module; mapping key order
## is deliberately unused.
VERIFY_AS_MODULE: Final[dict[str, str]] = {"pytest": "pytest", "ruff": "ruff"}
## Seconds a single verification command is given before it is killed. A
## verification is a check someone expected to run in a gate; one that outlives
## this has stopped being a check and would hang the report.
VERIFY_TIMEOUT: Final = 120.0
## Every outcome one verification can have, in the order the summary counts them.
## `skipped` is what a dry run reports for a command it would have run.
## Each element is one verification outcome in summary-report order.
VERIFY_OUTCOMES: Final[tuple[str, ...]] = (
    "passed", "failed", "refused", "timeout", "unavailable", "skipped",
)
## Terminal colour codes, stripped out of a captured stream before it is quoted
## back. ruff emits them into a pipe even with NO_COLOR set, so removing them
## after the fact is the only reliable move.
_ANSI: Final = re.compile("\x1b\\[[0-9;]*m")
## How much of a command's last output line is quoted in the report. Enough to
## carry a failure message, short enough to keep one entry to two lines.
_TAIL_WIDTH: Final = 150
## What a passing verification does and does not establish, printed with every
## report so the number is never read as more than it is.
VERIFY_CAVEAT: Final = (
    "A command that passes does not prove the claim -- it shows only that the "
    "check the entry named still succeeds. This finds some staleness, not all."
)


class LearnError(RuntimeError):
    """A refusal the caller can act on: the message says what to change."""


# ------------------------------------------------------------------- layout


@dataclass(frozen=True, slots=True)
class Store:
    """Where the learning database lives.

    Injected rather than read from a global so a test gets its own tree and two
    runs cannot silently share state.
    """

    ## The tree the store hangs off. Ledger, database and both views live under
    ## it; the schema and the configuration fall back to this repository's own
    ## copies when the tree carries none.
    root: Path

    @property
    def dir(self) -> Path:
        """Where the ledger, the database and both views live, created by the first write.

        @return the `learning` directory under the root
        """
        # Return the `learning` directory under the root to the caller.
        return self.root / "learning"

    @property
    def ledger(self) -> Path:
        """The durable record: one line per event, append-only, reviewable in a diff.

        @return the path to `ledger.jsonl`, which need not exist yet
        """
        # Return the path to `ledger.jsonl`, which need not exist yet to the caller.
        return self.dir / "ledger.jsonl"

    @property
    def db(self) -> Path:
        """The query index, safe to delete because a sync rebuilds it from the ledger.

        @return the path to `learning.db`, which git ignores
        """
        # Return the path to `learning.db`, which git ignores to the caller.
        return self.dir / "learning.db"

    @property
    def schema(self) -> Path:
        """The SQL executed on every connect, taken from the store when it carries a copy.

        @return the store's own `schema.sql`, or this repository's when it has none
        """
        # The schema is upstream-owned; a vendored copy falls back to this repo's.
        local = self.dir / "schema.sql"
        return local if local.exists() else REPO_ROOT / "learning" / "schema.sql"

    @property
    def config_path(self) -> Path:
        """The tunables in force, and the file `calibrate --set` rewrites in place.

        @return the store's own `config.toml`, or this repository's when it has none
        """
        # Compute local using self.dir / "config.toml" for later config path logic.
        local = self.dir / "config.toml"
        # Return the store's own `config.toml`, or this repository's when it has none to the
        # Details: caller.
        return local if local.exists() else REPO_ROOT / "learning" / "config.toml"

    @property
    def index(self) -> Path:
        """The readable roll-up of every learning, rewritten after each command that writes.

        @return the path to `INDEX.md`
        """
        # Return the path to `INDEX.md` to the caller.
        return self.dir / "INDEX.md"

    @property
    def calibration(self) -> Path:
        """The metrics report, rewritten beside `INDEX.md` and dated by `--as-of`.

        @return the path to `calibration.md`
        """
        # Return the path to `calibration.md` to the caller.
        return self.dir / "calibration.md"

    def config(self) -> dict[str, Any]:
        """Read the tunables afresh, so an edit to them applies from the next call on.

        @return the `write`, `retrieval`, `confidence`, `decay` and `promotion` sections
        """
        # Return the `write`, `retrieval`, `confidence`, `decay` and `promotion` sections to the
        # Details: caller.
        return tomllib.loads(self.config_path.read_text(encoding="utf-8"))


def now_iso() -> str:
    """Wall clock, in one place so a test can replace it.

    @return the current UTC time, truncated to whole seconds, in ISO form
    """
    # Return the current UTC time, truncated to whole seconds, in ISO form to the caller.
    return dt.datetime.now(tz=dt.UTC).replace(microsecond=0).isoformat()


# ------------------------------------------------------------------- the log


def read_ledger(store: Store) -> list[dict[str, Any]]:
    """Every event in the ledger, in the order it was appended.

    The ledger is the record and the database is only derived from it, so a
    caller that needs the truth rather than a fast answer reads here. A single
    malformed line stops the read: a partially understood log is worse than none.

    @param store where the ledger lives
    @return the parsed events, empty when nothing has been recorded yet
    @throws LearnError when a line is not valid JSON, naming the file and line
    """
    # Select the existing-artifact path only when `not store.ledger.exists()` is satisfied.
    if not store.ledger.exists():
        # Return the parsed events, empty when nothing has been recorded yet to the caller.
        return []
    # Each events element is one decoded ledger event in append sequence order.
    events: list[dict[str, Any]] = []
    # Preserve the current decoded diagnostic line before location normalization.
    # Advance read ledger through the current input element in declared order.
    for number, line in enumerate(store.ledger.read_text(encoding="utf-8").splitlines(), 1):
        # Compute stripped using line.strip for later read ledger logic.
        stripped = line.strip()
        # Select the empty-or-disabled path when stripped has no usable value.
        if not stripped:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            events.append(json.loads(stripped))
        # Preserve the caught failure that explains why the external result is unusable.
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except json.JSONDecodeError as exc:
            # Compute message using f"{store.ledger}:{number}: not valid JSON: {exc}" for later
            # Details: read ledger logic.
            message = f"{store.ledger}:{number}: not valid JSON: {exc}"
            # Propagate the localized failure so callers cannot mistake it for success.
            raise LearnError(message) from exc
    # Return the parsed events, empty when nothing has been recorded yet to the caller.
    return events


def append_event(store: Store, kind: str, session: str, payload: dict[str, Any],
                 *, actor: str = "agent", ts: str | None = None) -> dict[str, Any]:
    """Add one event to the end of the ledger, stamped with the next sequence number.

    Written as a single line so a concurrent appender cannot interleave, and so
    a merge conflict is resolvable by keeping both sides. The secret guard runs
    before the file is touched, so a rejected payload leaves no trace.

    @param store where the ledger lives; its directory is created if needed
    @param kind the event verb the fold dispatches on
    @param session the session the event belongs to
    @param payload the event body
        Each key is an event-body field and each value is its content; mapping key order is
        deliberately unused.
    @param actor who is appending, which distinguishes agent writes from human ones
    @param ts an explicit timestamp; the current time is used when omitted
    @return the event exactly as written, including its assigned seq and id
    @throws LearnError when the payload contains anything credential-shaped

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    guard_secrets(payload)
    # Compute events using read ledger for later append event logic.
    events = read_ledger(store)
    # Compute seq using len for later append event logic.
    seq = len(events) + 1
    # Each event key is an envelope or payload field and each value is its serialized content;
    # insertion order defines stable ledger JSON.
    event = {
        "seq": seq,
        "id": f"E-{seq:06d}",
        "session": session,
        "ts": ts or now_iso(),
        "kind": kind,
        "actor": actor,
        "payload": payload,
    }
    # Publish the externally visible effect after all required inputs are ready.
    store.dir.mkdir(parents=True, exist_ok=True)
    # Compute handle using "utf-8", newline="\n") as handle: for later append event logic.
    # Confine the acquired resource to this operation and release it on every exit.
    with store.ledger.open("a", encoding="utf-8", newline="\n") as handle:
        # Publish the externally visible effect after all required inputs are ready.
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    # Return the event exactly as written, including its assigned seq and id to the caller.
    return event


def guard_secrets(payload: dict[str, Any]) -> None:
    """Refuse to record anything credential-shaped.

    The refusal names which pattern matched and quotes the first 24 characters of
    the match, which is enough to find the offending field. That excerpt is a
    compromise rather than a redaction: the start of a short value can appear in
    it, so the message is not safe to paste anywhere the entry was not.

    @param payload the event body about to be serialised
        Each key is an event-body field and each value is its content; mapping key order is
        deliberately unused.
    @throws LearnError when any secret pattern matches the serialised payload
    """
    # Compute blob using json.dumps for later guard secrets logic.
    blob = json.dumps(payload, ensure_ascii=False)
    # Select description, pattern as the current element from SECRET_PATTERNS while guard
    # Details: secrets preserves traversal order.
    # Advance guard secrets through the current input element in declared order.
    for pattern, description in SECRET_PATTERNS:
        # Preserve the optional pattern match that carries the reported analysis count.
        found = re.search(pattern, blob)
        # Use the available-value path only when found is present.
        if found is not None:
            # Compute message using ( for later guard secrets logic.
            message = (
                f"refusing to record: the entry contains {description} "
                f"({found.group(0)[:24]}...). Redact it and record the shape of the "
                f"problem, not the value."
            )
            # Propagate the localized failure so callers cannot mistake it for success.
            raise LearnError(message)


# ------------------------------------------------------------------ the fold


def connect(store: Store) -> sqlite3.Connection:
    """Open the index, creating its tables and its version row when they are absent.

    The schema script is idempotent, so opening an existing database is the same
    call as creating a new one.

    @param store where the database and its schema live
    @return an open connection whose rows come back as `sqlite3.Row`
    """
    # Compute connection using sqlite3.connect for later connect logic.
    connection = sqlite3.connect(store.db)
    # Update connect state only after the required source facts are available.
    connection.row_factory = sqlite3.Row
    connection.executescript(store.schema.read_text(encoding="utf-8"))
    # Select the empty-or-disabled path when connection.execute('SELECT 1 FROM schema
    # Details: version').fetchone() has no usable value.
    if not connection.execute("SELECT 1 FROM schema_version").fetchone():
        connection.execute(
            "INSERT INTO schema_version(version, applied_ledger_seq) VALUES (?, 0)",
            (SCHEMA_VERSION,),
        )
    # Return an open connection whose rows come back as `sqlite3.Row` to the caller.
    return connection


def sync(store: Store) -> sqlite3.Connection:
    """Rebuild every projection by folding the ledger from its first event.

    Idempotent by construction: the tables are emptied first, so the result is a
    function of the log alone and a lost or stale database costs nothing but time.

    @param store where the ledger and the database live
    @return the open connection, which the caller closes
    @throws LearnError when the ledger cannot be read

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    store.dir.mkdir(parents=True, exist_ok=True)
    # Compute connection using connect for later sync logic.
    connection = connect(store)
    # Confine the acquired resource to this operation and release it on every exit.
    with connection:
        # Select table as the current element from ("usage", "link", "trigger", "learning",
        # Details: "session", "event") while sync preserves traversal order.
        # Advance sync through the current input element in declared order.
        for table in ("usage", "link", "trigger", "learning", "session", "event"):
            connection.execute(f"DELETE FROM {table}")  # ruff: ignore[hardcoded-sql-expression] - fixed table names
        # Compute events using read ledger for later sync logic.
        events = read_ledger(store)
        # Select event as the current element from events while sync preserves traversal order.
        # Advance sync through the current input element in declared order.
        for event in events:
            connection.execute(
                "INSERT INTO event(seq, id, session, ts, kind, actor, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (event["seq"], event["id"], event["session"], event["ts"],
                 event["kind"], event.get("actor", "agent"),
                 json.dumps(event["payload"], ensure_ascii=False, sort_keys=True)),
            )
            _apply(connection, event, store.config())
        connection.execute(
            "UPDATE schema_version SET version = ?, applied_ledger_seq = ?",
            (SCHEMA_VERSION, len(events)),
        )
    # Return the open connection, which the caller closes to the caller.
    return connection


def _apply(connection: sqlite3.Connection, event: dict[str, Any],
           config: dict[str, Any]) -> None:
    """Fold one event into the projections.

    An unrecognised verb, and any feedback event naming a learning that is not
    projected, is passed over rather than rejected: a ledger written by a newer
    tool must still fold, and the ledger keeps the event either way.

    @param connection the open index, inside the caller's transaction
    @param event the event to apply
        Each key is an event-envelope field and each value is its decoded content; mapping key
        order is deliberately unused.
    @param config the tunables governing base confidence, deltas and promotion
        Each key is a configuration section and each value is its tunable mapping; mapping key
        order is deliberately unused.
    """
    # The three assigned elements are ordered event kind, payload mapping, then ledger sequence.
    kind, payload, seq = event["kind"], event["payload"], event["seq"]

    # Select the guarded path only after `kind == 'session'` is satisfied.
    if kind == "session":
        connection.execute(
            "INSERT OR REPLACE INTO session(id, started_ts, task, discipline_version) "
            "VALUES (?, ?, ?, ?)",
            (event["session"], event["ts"], payload.get("task"),
             payload.get("discipline_version")),
        )
        # Return the completed  apply result to its caller.
        return

    # Select the guarded path only after `kind == 'learn'` is satisfied.
    if kind == "learn":
        # Compute base using  base confidence for later apply logic.
        base = _base_confidence(payload.get("evidence", "observed"), config)
        connection.execute(
            "INSERT OR REPLACE INTO learning(id, kind, scope, claim, action, evidence, "
            "verification, status, confidence, helped, noise, sessions, created_seq, "
            "created_session, created_ts, last_seen_ts) "
            "VALUES (?,?,?,?,?,?,?,'candidate',?,0,0,1,?,?,?,?)",
            (payload["id"], payload["kind"], payload.get("scope", "project"),
             payload["claim"], payload["action"], payload.get("evidence", "observed"),
             payload.get("verification"), base, seq, event["session"], event["ts"],
             event["ts"]),
        )
        connection.execute("DELETE FROM trigger WHERE learning_id = ?", (payload["id"],))
        # Select trigger as the current element from payload.get("triggers", []) while apply
        # Details: preserves traversal order.
        # Advance apply through the current input element in declared order.
        for trigger in payload.get("triggers", []):
            connection.execute(
                "INSERT OR IGNORE INTO trigger(learning_id, type, pattern) VALUES (?,?,?)",
                (payload["id"], trigger["type"], trigger["pattern"]),
            )
        connection.execute("DELETE FROM link WHERE learning_id = ?", (payload["id"],))
        # Select link as the current element from payload.get("links", []) while apply preserves
        # Details: traversal order.
        # Advance apply through the current input element in declared order.
        for link in payload.get("links", []):
            connection.execute(
                "INSERT OR IGNORE INTO link(learning_id, relation, node) VALUES (?,?,?)",
                (payload["id"], link.get("relation", "learned_about"), link["node"]),
            )
        connection.execute(
            "UPDATE session SET recorded = recorded + 1 WHERE id = ?", (event["session"],)
        )
        _restatus(connection, payload["id"], config)
        # Return the completed  apply result to its caller.
        return

    # Preserve the immutable revision identity used as provenance for this comparison.
    ref = payload.get("ref")
    # Select the guarded path only after `ref is None or not _exists(connection, ref)` is
    # Details: satisfied.
    if ref is None or not _exists(connection, ref):
        # Return the completed  apply result to its caller.
        return

    # Select the guarded path only after `kind == 'use'` is satisfied.
    if kind == "use":
        # Capture outcome as the completed apply outcome for subsequent validation or
        # Details: publication.
        outcome = payload.get("outcome", "helped")
        connection.execute(
            "INSERT INTO usage(seq, learning_id, session, ts, outcome, note) VALUES (?,?,?,?,?,?)",
            (seq, ref, event["session"], event["ts"], outcome, payload.get("note")),
        )
        # Compute column using {"helped": "helped", "noise": "noise", "contradicted": "nois for
        # Details: later apply logic.
        column = {"helped": "helped", "noise": "noise", "contradicted": "noise"}[outcome]
        # Compute delta using config["confidence"][ for later apply logic.
        delta = config["confidence"][
            "helped_delta" if outcome == "helped" else "noise_delta"
        ]
        connection.execute(
            f"UPDATE learning SET {column} = {column} + 1, "  # ruff: ignore[hardcoded-sql-expression] - column from a fixed map
            "confidence = MAX(?, MIN(?, confidence + ?)), "
            "sessions = (SELECT COUNT(DISTINCT session) FROM usage WHERE learning_id = ?), "
            "last_seen_ts = ? WHERE id = ?",
            (config["confidence"]["floor"], config["confidence"]["ceiling"], delta,
             ref, event["ts"], ref),
        )
        _restatus(connection, ref, config)
    # Select the guarded path only after `kind == 'refute'` is satisfied.
    elif kind == "refute":
        connection.execute(
            "UPDATE learning SET status = 'refuted', note = ?, last_seen_ts = ? WHERE id = ?",
            (payload.get("why"), event["ts"], ref),
        )
    # Select the guarded path only after `kind == 'supersede'` is satisfied.
    elif kind == "supersede":
        connection.execute(
            "UPDATE learning SET status = 'superseded', superseded_by = ?, last_seen_ts = ? "
            "WHERE id = ?",
            (payload.get("by"), event["ts"], ref),
        )
    # Select the guarded path only after `kind == 'promote'` is satisfied.
    elif kind == "promote":
        connection.execute(
            "UPDATE learning SET status = 'promoted', promoted_to = ?, note = ?, "
            "last_seen_ts = ? WHERE id = ?",
            (payload.get("mechanism"), payload.get("note"), event["ts"], ref),
        )


def _exists(connection: sqlite3.Connection, learning_id: str) -> bool:
    """Whether a row is projected, which decides if a feedback event has a subject.

    @param connection the open index
    @param learning_id the id an event refers to
    @return True when the learning has been folded already
    """
    # Return true when the learning has been folded already to the caller.
    return connection.execute(
        "SELECT 1 FROM learning WHERE id = ?", (learning_id,)
    ).fetchone() is not None


def _base_confidence(evidence: str, config: dict[str, Any]) -> float:
    """Where a claim starts, set by how firmly it was established.

    @param evidence how the claim was come by: observed, inferred or told
    @param config the tunables, which carry one starting value per evidence kind
        Each key is a configuration section and each value is its tunable mapping; mapping key
        order is deliberately unused.
    @return the configured starting confidence
    """
    # Return the configured starting confidence to the caller.
    return float(config["confidence"][f"base_{evidence}"])


def _restatus(connection: sqlite3.Connection, learning_id: str,
              config: dict[str, Any]) -> None:
    """Candidate becomes active once the evidence threshold is met.

    A verification command counts for more than a report: the check is the
    evidence, which is the axiom applied to learnings. A retired entry is left
    alone, so a refutation cannot be undone by further use.

    @param connection the open index
    @param learning_id the entry whose status is to be re-decided
    @param config the tunables carrying the promotion thresholds
        Each key is a configuration section and each value is its tunable mapping; mapping key
        order is deliberately unused.
    """
    # Compute row using connection.execute for later restatus logic.
    row = connection.execute(
        "SELECT helped, noise, sessions, verification, status FROM learning WHERE id = ?",
        (learning_id,),
    ).fetchone()
    # Select the guarded path only after `row is None or row['status'] in RETIRED` is satisfied.
    if row is None or row["status"] in RETIRED:
        # Return the completed  restatus result to its caller.
        return
    # Compute promotion using config["promotion"] for later restatus logic.
    promotion = config["promotion"]
    # Compute evidence using row["helped"] for later restatus logic.
    evidence = row["helped"]
    # Compute needed using (promotion["min_evidence_verified"] if row["verification"] for later
    # Details: restatus logic.
    needed = (promotion["min_evidence_verified"] if row["verification"]
              else promotion["min_evidence"])
    # Compute active using evidence >= needed and ( for later restatus logic.
    active = evidence >= needed and (
        row["sessions"] >= promotion["min_sessions"] or bool(row["verification"])
    )
    connection.execute(
        "UPDATE learning SET status = ? WHERE id = ?",
        ("active" if active else "candidate", learning_id),
    )


# ----------------------------------------------------------------- retrieval


@dataclass(frozen=True, slots=True)
class Candidate:
    """One learning offered to a caller, with why it surfaced."""

    ## The entry's identifier, as it appears in the ledger and in `INDEX.md`.
    id: str
    ## One of `LEARNING_KINDS`, which is also the key its half-life is read by.
    kind: str
    ## Whether the claim is about this project or about the discipline itself.
    scope: str
    ## One sentence saying what was found to be true.
    claim: str
    ## The imperative: what to do differently because of the claim.
    action: str
    ## `candidate` or `active`; a retired entry is offered only when
    ## `retrieval.include_retired` is set.
    status: str
    ## The evidence-derived value the fold produced, before any decay.
    confidence: float
    ## Confidence after decay, and the number that ordered and filtered this list.
    effective: float
    ## Why it surfaced: one short phrase per trigger that fired, sorted.
    ## Each element is one trigger-match explanation in lexical order.
    matched: tuple[str, ...]
    ## Rule and module ids the claim is about, sorted.
    ## Each element is one related rule or module id in lexical order.
    links: tuple[str, ...]
    ## A command that re-establishes the claim, when one was recorded.
    verification: str | None
    ## When the entry was last touched, which is what decay is measured from.
    last_seen: str
    ## True once decay has cost more than half the stored confidence.
    ## True enables stale; false selects its disabled alternative.
    stale: bool

    def render(self) -> str:
        """The terminal form, whose token count is also the unit of the retrieval budget.

        @return the block shown for one entry, with no trailing newline
        """
        # Compute flag using " STALE" if self.stale else "" for later render logic.
        flag = " STALE" if self.stale else ""
        # Compute verify using f"\n      verify: {self.verification}" if self.verification  for
        # Details: later render logic.
        verify = f"\n      verify: {self.verification}" if self.verification else ""
        # Return the block shown for one entry, with no trailing newline to the caller.
        return (
            f"  {self.id} [{self.status} {self.effective:.2f}{flag}] {self.kind}\n"
            f"      {self.claim}\n"
            f"      -> {self.action}"
            f"{verify}\n"
            f"      matched: {', '.join(self.matched)}"
        )


def effective_confidence(stored: float, last_seen: str, kind: str,
                         config: dict[str, Any], today: dt.date) -> float:
    """Stored confidence, halved once per half-life since it was last seen.

    Decay is computed at read time rather than stored, so the folded state stays
    a function of the log alone and the generated views stay byte-stable. A
    timestamp in the future is treated as today rather than decaying backwards.

    @param stored the confidence the fold produced
    @param last_seen when the entry was last touched, in ISO form
    @param kind the entry's kind, which selects the half-life; 365 days if the table has none
    @param config the tunables carrying the decay table
        Each key is a configuration section and each value is its tunable mapping; mapping key
        order is deliberately unused.
    @param today the date the age is measured to
    @return the decayed value, or `stored` unchanged when the timestamp will not parse
    """
    # Compute half life using float for later effective confidence logic.
    half_life = float(config["decay"].get(kind, 365))
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute seen using dt.datetime.fromisoformat for later effective confidence logic.
        seen = dt.datetime.fromisoformat(last_seen).date()
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except ValueError:
        # Return the decayed value, or `stored` unchanged when the timestamp will not parse to
        # Details: the caller.
        return stored
    # Compute days using max for later effective confidence logic.
    days = max((today - seen).days, 0)
    # Return the decayed value, or `stored` unchanged when the timestamp will not parse to the
    # Details: caller.
    return round(stored * (0.5 ** (days / half_life)), 4)


def retrieve(store: Store, connection: sqlite3.Connection, *, file: str | None = None,
             error: str | None = None, task: str | None = None,
             rules: Sequence[str] = (), today: dt.date | None = None) -> list[Candidate]:
    """Learnings whose triggers match the situation, best first.

    A trigger fires or it does not, so the same situation always yields the same
    answer and a bad retrieval can be argued with. What decayed below
    `retrieval.min_confidence` is dropped, and so is anything retired unless
    `retrieval.include_retired` is set; what remains is cut to the budget.

    @param store where the configuration lives
    @param connection an index already folded from the ledger
    @param file the path being worked on, matched against glob triggers
    @param error the failure at hand, matched against error, term and rule triggers
    @param task what the caller is doing, matched against command, term and rule triggers
    @param rules rule ids already in play, matched against rule triggers only
        Each element is one selected rule id; order is deliberately unused for trigger matching.
    @param today the date decay is measured to; the system date when omitted
    @return the entries that survived filtering and the budget, most confident first
    """
    # Compute config using store.config for later retrieve logic.
    config = store.config()
    # Compute settings using config["retrieval"] for later retrieve logic.
    settings = config["retrieval"]
    # Compute day using today or dt.date.today() for later retrieve logic.
    day = today or dt.date.today()
    # Each matches key is a learning id and each value is its unordered trigger-reason set;
    # mapping insertion order follows the trigger query but final candidates are explicitly sorted.
    matches: dict[str, set[str]] = {}

    # Select row as the current element from connection.execute("SELECT learning_id, type,
    # Details: pattern FROM trigger") while retrieve preserves traversal order.
    # Advance retrieve through the current input element in declared order.
    for row in connection.execute("SELECT learning_id, type, pattern FROM trigger"):
        # Compute why using  trigger matches for later retrieve logic.
        why = _trigger_matches(row["type"], row["pattern"], file, error, task, rules)
        # Use the available-value path only when why is present.
        if why is not None:
            matches.setdefault(row["learning_id"], set()).add(why)

    # Each candidates element is one retrievable learning in initial query order before the
    # explicit confidence ranking.
    candidates: list[Candidate] = []
    # Select learning id, reasons as the current element from matches.items() while retrieve
    # Details: preserves traversal order.
    # Advance retrieve through the current input element in declared order.
    for learning_id, reasons in matches.items():
        # Compute row using connection.execute for later retrieve logic.
        row = connection.execute(
            "SELECT * FROM learning WHERE id = ?", (learning_id,)
        ).fetchone()
        # Use the absence path when row has no available value.
        if row is None:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Select the guarded path only after `row['status'] in RETIRED and (not
        # Details: settings['include_retired'])` is satisfied.
        if row["status"] in RETIRED and not settings["include_retired"]:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Compute effective using effective confidence for later retrieve logic.
        effective = effective_confidence(
            row["confidence"], row["last_seen_ts"], row["kind"], config, day
        )
        # Select the guarded path only after `effective < settings['min_confidence']` is
        # Details: satisfied.
        if effective < settings["min_confidence"]:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Each links element is one related node id in SQL lexical order.
        links = [
            r["node"] for r in connection.execute(
                "SELECT node FROM link WHERE learning_id = ? ORDER BY node", (learning_id,)
            )
        ]
        candidates.append(
            Candidate(
                id=row["id"], kind=row["kind"], scope=row["scope"], claim=row["claim"],
                action=row["action"], status=row["status"], confidence=row["confidence"],
                effective=effective, matched=tuple(sorted(reasons)), links=tuple(links),
                verification=row["verification"], last_seen=row["last_seen_ts"],
                stale=effective < row["confidence"] / 2,
            )
        )

    candidates.sort(key=lambda c: (-c.effective, c.id))
    # Return the entries that survived filtering and the budget, most confident first to the
    # Details: caller.
    return _fit_budget(candidates, settings)


def _fit_budget(candidates: Sequence[Candidate], settings: dict[str, Any]) -> list[Candidate]:
    """Take entries in order until the next one would exceed the context allowance.

    The first entry is always kept however large it is: returning nothing would
    withhold the very thing the caller asked for to save a budget that only
    exists to make the answer readable.

    @param candidates the ordered entries, best first
        Each element is one ranked learning candidate in descending usefulness order.
    @param settings the retrieval section of the configuration
        Each key is a retrieval-tunable name and each value is its configured limit; mapping key
        order is deliberately unused.
    @return the leading run that fits both limits, except that the first is kept regardless
    """
    # Each kept element is one leading ranked candidate retained in input order.
    kept: list[Candidate] = []
    # Compute spent using 0 for later fit budget logic.
    spent = 0
    # Treat the current candidate as the candidate element consumed by the enclosing
    # Details: transformation.
    # Advance fit budget through the current input element in declared order.
    for candidate in candidates[: settings["max_learnings"]]:
        # Compute cost using count tokens for later fit budget logic.
        cost = count_tokens(candidate.render())
        # Select the guarded path only after `kept and spent + cost > settings['budget_tokens']`
        # Details: is satisfied.
        if kept and spent + cost > settings["budget_tokens"]:
            # Stop the scan once the decisive match has been established.
            break
        # Compute spent using cost for later fit budget logic.
        spent += cost
        kept.append(candidate)
    # Return the leading run that fits both limits, except that the first is kept regardless to
    # Details: the caller.
    return kept


def _trigger_matches(trigger_type: str, pattern: str, file: str | None, error: str | None,
                     task: str | None, rules: Sequence[str]) -> str | None:
    """Whether one trigger fires, and a short reason if it does.

    The reason is carried back rather than recomputed because it is what makes a
    retrieval reviewable: the caller can see which pattern brought each entry.

    @param trigger_type one of the accepted trigger kinds
    @param pattern the trigger's pattern, interpreted according to its kind
    @param file the path in play, if any
    @param error the failure text in play, if any
    @param task the task description in play, if any
    @param rules the rule ids in play
        Each element is one selected rule id; order is deliberately unused for matching.
    @return a phrase naming why it fired, or None when it did not
    """
    # Select the guarded path only after `trigger_type == 'glob' and file and
    # Details: fnmatch.fnmatch(Path(file).as_posix(), pattern)` is satisfied.
    if trigger_type == "glob" and file and fnmatch.fnmatch(Path(file).as_posix(), pattern):
        # Return a phrase naming why it fired, or None when it did not to the caller.
        return f"path ~ {pattern}"
    # Select the guarded path only after `trigger_type == 'error' and error and
    # Details: _signature_in(pattern, error)` is satisfied.
    if trigger_type == "error" and error and _signature_in(pattern, error):
        # Return a phrase naming why it fired, or None when it did not to the caller.
        return f"error ~ {pattern}"
    # Select the guarded path only after `trigger_type == 'rule'` is satisfied.
    if trigger_type == "rule":
        # Compute haystack using " ".join([*rules, error or "", task or ""]) for later trigger
        # Details: matches logic.
        haystack = " ".join([*rules, error or "", task or ""])
        # Select the guarded path only after `pattern in haystack` is satisfied.
        if pattern in haystack:
            # Return a phrase naming why it fired, or None when it did not to the caller.
            return f"rule {pattern}"
    # Select the guarded path only after `trigger_type == 'command' and task and
    # Details: (pattern.lower() in task.lower())` is satisfied.
    if trigger_type == "command" and task and pattern.lower() in task.lower():
        # Return a phrase naming why it fired, or None when it did not to the caller.
        return f"command ~ {pattern}"
    # Select the guarded path only after `trigger_type == 'term'` is satisfied.
    if trigger_type == "term":
        # Retain the immutable source representation consumed by subsequent analysis.
        # Advance trigger matches through the current input element in declared order.
        for text in (task, error):
            # Select the guarded path only after `text and pattern.lower() in text.lower()` is
            # Details: satisfied.
            if text and pattern.lower() in text.lower():
                # Return a phrase naming why it fired, or None when it did not to the caller.
                return f"term {pattern}"
    # Return a phrase naming why it fired, or None when it did not to the caller.
    return None


def _words(text: str) -> set[str]:
    """The distinct tokens of a text, with hyphen and underscore treated as spaces.

    @param text any text
    @return its lowercase alphanumeric tokens, deduplicated
    """
    # Return its lowercase alphanumeric tokens, deduplicated to the caller.
    return set(re.findall(r"[a-z0-9_]+", text.lower().replace("-", " ").replace("_", " ")))


def _signature_in(pattern: str, text: str) -> bool:
    """Separator style must not decide whether an error signature matches.

    A single word is required to appear literally; only a multi-word signature
    earns the looser set comparison, since one common word matching by accident
    would surface an entry for every unrelated failure.

    @param pattern the recorded signature
    @param text the failure at hand
    @return True on a substring hit, or when every word of a multi-word signature
        appears somewhere in the text, in any order and not necessarily adjacent
    """
    # Select the guarded path only after `pattern.lower() in text.lower()` is satisfied.
    if pattern.lower() in text.lower():
        # Return true on a substring hit, or when every word of a multi-word signature to the
        # Details: caller.
        return True
    # Compute signature using  words for later signature in logic.
    signature = _words(pattern)
    # Return true on a substring hit, or when every word of a multi-word signature to the
    # Details: caller.
    return len(signature) > 1 and signature <= _words(text)


# ------------------------------------------------------------------- writing


def next_learning_id(connection: sqlite3.Connection) -> str:
    """One past the highest id yet projected, so a fresh entry cannot collide.

    Read from the fold rather than kept in a counter, so the ledger remains the
    only thing that has to be preserved.

    @param connection an index already folded from the ledger
    @return the next identifier, in `L-nnnn` form
    """
    # Compute row using connection.execute for later next learning id logic.
    row = connection.execute("SELECT MAX(id) AS top FROM learning").fetchone()
    # Compute top using int for later next learning id logic.
    top = int(row["top"].split("-")[1]) if row and row["top"] else 0
    # Return the next identifier, in `L-nnnn` form to the caller.
    return f"L-{top + 1:04d}"


def parse_trigger(raw: str) -> dict[str, str]:
    """Split a `type:pattern` argument, refusing a type retrieval could never use.

    Written as `glob:src/**/*.py` or `error:adapters are independent`. Only the
    first colon separates, so a pattern may contain colons of its own.

    @param raw the argument as it was typed
    @return the type and the pattern, the pattern stripped of surrounding space
    @throws LearnError when the colon is missing or the type is not a known one
    """
    # Unpack pattern, separator, trigger type using raw.partition for later parse trigger logic.
    trigger_type, separator, pattern = raw.partition(":")
    # Select the empty-or-disabled path when separator or trigger type not in TRIGGER TYPES has
    # Details: no usable value.
    if not separator or trigger_type not in TRIGGER_TYPES:
        # Compute message using ( for later parse trigger logic.
        message = (
            f"trigger must be one of {', '.join(TRIGGER_TYPES)} followed by ':' "
            f"and a pattern; got {raw!r}"
        )
        # Propagate the localized failure so callers cannot mistake it for success.
        raise LearnError(message)
    # Return the type and the pattern, the pattern stripped of surrounding space to the caller.
    return {"type": trigger_type, "pattern": pattern.strip()}


def session_id(explicit: str | None) -> str:
    """The caller's own id, or a fresh dated one so unrelated work stays separable.

    A generated id is new on every call, so a caller wanting several commands
    attributed to one sitting has to take the id `session` printed and pass it
    back with `--session`. Sessions are what the promotion rule counts: an entry
    that helped twice in one sitting is weaker evidence than one that helped in two.

    @param explicit an id supplied on the command line, if any
    @return the identifier to stamp on the events that follow
    """
    # Handle the non-empty or enabled explicit state.
    if explicit:
        # Return the identifier to stamp on the events that follow to the caller.
        return explicit
    # Compute stamp using dt.datetime.now for later session id logic.
    stamp = dt.datetime.now(tz=dt.UTC).strftime("%Y%m%d")
    # Return the identifier to stamp on the events that follow to the caller.
    return f"S-{stamp}-{uuid.uuid4().hex[:6]}"


# -------------------------------------------------------------- verification


@dataclass(frozen=True, slots=True)
class VerifyResult:
    """What became of one learning's verification command."""

    ## The entry whose command this was, as it appears in the ledger.
    learning_id: str
    ## The command exactly as the ledger records it, quoted back so a refusal
    ## names the thing that was refused rather than a normalised version of it.
    command: str
    ## One of `VERIFY_OUTCOMES`. Only `failed` is evidence against the claim;
    ## `refused`, `timeout` and `unavailable` say the check could not be run,
    ## which is a fact about this machine rather than about the entry.
    outcome: str
    ## What happened, in one line: the exit status and the last line of output,
    ## or the reason the command was never started.
    detail: str
    ## The exit status, when the command ran far enough to have one.
    code: int | None = None

    def render(self) -> str:
        """The terminal form, one entry to a block.

        @return two lines: the verdict with the command, and the detail beneath it
        """
        # Return two lines: the verdict with the command, and the detail beneath it to the
        # Details: caller.
        return (
            f"  {self.learning_id}  {self.outcome.upper():<12} {self.command}\n"
            f"      {self.detail}"
        )


def verification_argv(command: str) -> list[str]:
    """Split a recorded command into an argument vector, with no shell involved.

    The vector is handed to the operating system as a list, so a recorded `&&`,
    `|` or `$(...)` arrives at the program as a literal argument and never as
    syntax. Splitting is POSIX-style: a recorded command is written with forward
    slashes, and a Windows-style backslash path would lose its separators here.

    @param command the command as the ledger records it
    @return the argument vector, empty when the command is blank
    @throws LearnError when the quoting is unbalanced, so no vector can be derived
    """
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Return the argument vector, empty when the command is blank to the caller.
        return shlex.split(command, posix=True)
    # Preserve the caught failure that explains why the external result is unusable.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except ValueError as exc:
        # Compute message using f"the verification command cannot be parsed: {exc}" for later
        # Details: verification argv logic.
        message = f"the verification command cannot be parsed: {exc}"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise LearnError(message) from exc


def verification_refusal(argv: Sequence[str], root: Path) -> str | None:
    """Why this command will not be run, or nothing when it is inside the allowlist.

    The allowlist bounds the *entry point*, not everything a permitted entry
    point can then be asked to do: `python tools/x.py` is admitted on the
    strength of the script living in this repository, and what that script does
    is the repository's own business. What it stops is a ledger naming an
    arbitrary program, an interpreter flag that carries its own code, or any
    argument pointing outside the tree -- the shapes a ledger arriving from
    elsewhere would use to get something of its own executed.

    The bound on arguments is not decoration. Every admitted entry point except
    `ruff` will execute code it is handed a path to: `pytest ../next-door/test_x.py`
    runs that file, and `doxygen ../next-door/Doxyfile` runs whatever its
    `INPUT_FILTER` names. A harvested ledger's own repository sits exactly there,
    one directory up, so an argument that leaves the tree is the same breach as
    an entry point that was never on the list.

    @param argv the parsed vector
        Each arguments element is one process argument string; invocation order is preserved.
    @param root the tree the command would run in
    @return one sentence naming what was refused, or None when the command is admitted
    """
    # Select the empty-or-disabled path when argv has no usable value.
    if not argv:
        # Return one sentence naming what was refused, or None when the command is admitted to
        # Details: the caller.
        return "the command is empty"
    # Select the guarded path only after `Path(argv[0]).name != argv[0]` is satisfied.
    if Path(argv[0]).name != argv[0]:
        # Return one sentence naming what was refused, or None when the command is admitted to
        # Details: the caller.
        return f"the executable is path-qualified ({argv[0]!r}); only a bare name is run"
    # Normalize the current repository path to its portable baseline key spelling.
    name = argv[0].lower().removesuffix(".exe")
    # Select the guarded path only after `name not in VERIFY_EXECUTABLES` is satisfied.
    if name not in VERIFY_EXECUTABLES:
        # Return one sentence naming what was refused, or None when the command is admitted to
        # Details: the caller.
        return f"{argv[0]!r} is not one of: {', '.join(VERIFY_EXECUTABLES)}"
    # Compute escape using  argument outside root for later verification refusal logic.
    escape = _argument_outside_root(argv[1:], root)
    # Use the available-value path only when escape is present.
    if escape is not None:
        # Return one sentence naming what was refused, or None when the command is admitted to
        # Details: the caller.
        return escape
    # Select the guarded path only after `name not in PYTHON_EXECUTABLES` is satisfied.
    if name not in PYTHON_EXECUTABLES:
        # Return one sentence naming what was refused, or None when the command is admitted to
        # Details: the caller.
        return None
    # Return one sentence naming what was refused, or None when the command is admitted to the
    # Details: caller.
    return _interpreter_refusal(list(argv[1:]), root)


def _interpreter_refusal(rest: Sequence[str], root: Path) -> str | None:
    """Why an admitted interpreter will not be given these arguments.

    An interpreter is the one entry point on the list that will run whatever it
    is handed, so what follows it is the allowlist's real subject: either `-m`
    naming a package from a short list, or a script inside this repository.
    Everything else -- `-c`, a bare `-`, an empty tail -- is a way of supplying a
    program rather than naming one.

    @param rest the arguments after the interpreter
        Each element is one interpreter argument in command-line order.
    @param root the tree the command would run in
    @return one sentence naming what was refused, or None when the tail is admitted
    """
    # Select the empty-or-disabled path when rest has no usable value.
    if not rest:
        # Return one sentence naming what was refused, or None when the tail is admitted to the
        # Details: caller.
        return "a bare interpreter takes its program from stdin, which is not a check"
    # Select the guarded path only after `rest[0] == '-m'` is satisfied.
    if rest[0] == "-m":
        # Compute module using rest[1] if len(rest) > 1 else "" for later interpreter refusal
        # Details: logic.
        module = rest[1] if len(rest) > 1 else ""
        # Select the guarded path only after `module.split('.')[0] not in VERIFY_MODULES` is
        # Details: satisfied.
        if module.split(".")[0] not in VERIFY_MODULES:
            # Return one sentence naming what was refused, or None when the tail is admitted to
            # Details: the caller.
            return f"module {module!r} is not one of: {', '.join(VERIFY_MODULES)}"
        # Return one sentence naming what was refused, or None when the tail is admitted to the
        # Details: caller.
        return None
    # Select the empty-or-disabled path when rest[0].endswith('.py') has no usable value.
    if not rest[0].endswith(".py"):
        # Return one sentence naming what was refused, or None when the tail is admitted to the
        # Details: caller.
        return (
            f"{rest[0]!r} is neither -m nor a script in this repository; an "
            f"interpreter flag such as -c carries its own program"
        )
    # Return one sentence naming what was refused, or None when the tail is admitted to the
    # Details: caller.
    return _outside_root(rest[0], root)


def _argument_outside_root(rest: Sequence[str], root: Path) -> str | None:
    """Why an argument will not be passed on: it names a place outside the tree.

    Only arguments that look like paths are weighed -- one carrying a separator,
    or a bare parent-directory reference -- and the value half of a
    `--flag=value` is weighed in place of the whole. A word with no separator is
    left alone: it is a flag, a test id or a module name, and treating it as a
    path would refuse ordinary commands to no purpose.

    This is deliberately blunt about what a path is. A refusal here costs an
    entry its staleness signal and says so by name; admitting an argument that
    leaves the tree costs the repository whatever the file it points at does.

    @param rest the arguments after the entry point
        Each element is one entry-point argument in command-line order.
    @param root the tree the command would run in
    @return one sentence naming the first argument that escapes, or None when none does
    """
    # Select argument as the current element from rest while argument outside root preserves
    # Details: traversal order.
    # Advance argument outside root through the current input element in declared order.
    for argument in rest:
        # Treat the current candidate as the candidate element consumed by the enclosing
        # Details: transformation.
        candidate = argument
        # Select the guarded path only after `candidate.startswith('-') and '=' in candidate` is
        # Details: satisfied.
        if candidate.startswith("-") and "=" in candidate:
            # Treat the current candidate as the candidate element consumed by the enclosing
            # Details: transformation.
            candidate = candidate.partition("=")[2]
        # Select the empty-or-disabled path when candidate has no usable value.
        if not candidate:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Compute looks like path using "/" in candidate or "\\" in candidate or candidate ==
        # Details: ".." for later argument outside root logic.
        looks_like_path = "/" in candidate or "\\" in candidate or candidate == ".."
        # Select the empty-or-disabled path when looks like path has no usable value.
        if not looks_like_path:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Use the available-value path only when  outside root(candidate, root) is present.
        if _outside_root(candidate, root) is not None:
            # Return one sentence naming the first argument that escapes, or None when none does
            # Details: to the caller.
            return (
                f"the argument {argument!r} points outside the repository; an "
                f"admitted program will run what it is handed"
            )
    # Return one sentence naming the first argument that escapes, or None when none does to the
    # Details: caller.
    return None


def _outside_root(script: str, root: Path) -> str | None:
    """Refuse a script that does not resolve inside the tree being verified.

    Existence is not required: a command naming a file that has since been
    deleted must be allowed to run and fail, because that failure is exactly the
    staleness this subcommand looks for.

    @param script the path as it was recorded
    @param root the tree the command would run in
    @return one sentence when the path escapes the tree, or None when it stays inside
    """
    # Treat the current candidate as the candidate element consumed by the enclosing
    # Details: transformation.
    candidate = Path(script)
    # Resolve the repository-confined path used by this operation before filesystem access.
    target = candidate if candidate.is_absolute() else root / candidate
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute resolved using target.resolve for later outside root logic.
        resolved = target.resolve()
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except OSError:
        # Return one sentence when the path escapes the tree, or None when it stays inside to
        # Details: the caller.
        return f"the script path {script!r} cannot be resolved"
    # Select the empty-or-disabled path when resolved.is relative to(root.resolve()) has no
    # Details: usable value.
    if not resolved.is_relative_to(root.resolve()):
        # Return one sentence when the path escapes the tree, or None when it stays inside to
        # Details: the caller.
        return f"the script {script!r} lies outside the repository"
    # Return one sentence when the path escapes the tree, or None when it stays inside to the
    # Details: caller.
    return None


def verification_vector(argv: Sequence[str], root: Path) -> tuple[list[str], str | None]:
    """The vector as it will actually be started, with the executable pinned.

    Interpreted commands are rewritten onto `sys.executable`, so the verification
    runs under the interpreter this tool is running under rather than whatever
    PATH offers. Only a program with no module form is looked up on PATH, and one
    that resolves inside the tree being verified is refused: a repository
    shipping its own `doxygen` beside the ledger that names it is the supply
    chain this whole subcommand is defending against.

    @param argv the admitted vector
        Each arguments element is one process argument string; invocation order is preserved.
    @param root the tree the command would run in
    @return the vector to start, and a refusal when the executable cannot be trusted
    @throws LearnError when the vector is empty, which the allowlist rejects first
    """
    # Select the empty-or-disabled path when argv has no usable value.
    if not argv:
        # Compute message using "an empty command has no executable" for later verification
        # Details: vector logic.
        message = "an empty command has no executable"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise LearnError(message)
    # Normalize the current repository path to its portable baseline key spelling.
    name = argv[0].lower().removesuffix(".exe")
    # Select the guarded path only after `name in PYTHON_EXECUTABLES` is satisfied.
    if name in PYTHON_EXECUTABLES:
        # Return the vector to start, and a refusal when the executable cannot be trusted to the
        # Details: caller.
        return [sys.executable, *argv[1:]], None
    # Select the guarded path only after `name in VERIFY_AS_MODULE` is satisfied.
    if name in VERIFY_AS_MODULE:
        # Return the vector to start, and a refusal when the executable cannot be trusted to the
        # Details: caller.
        return [sys.executable, "-m", VERIFY_AS_MODULE[name], *argv[1:]], None
    # Preserve the optional pattern match that carries the reported analysis count.
    found = shutil.which(argv[0])
    # Use the absence path when found has no available value.
    if found is None:
        # Return the vector to start, and a refusal when the executable cannot be trusted to the
        # Details: caller.
        return list(argv), None
    # Select the guarded path only after `Path(found).resolve().is_relative_to(root.resolve())`
    # Details: is satisfied.
    if Path(found).resolve().is_relative_to(root.resolve()):
        # Return the vector to start, and a refusal when the executable cannot be trusted to the
        # Details: caller.
        return list(argv), f"{argv[0]!r} resolves to {found}, inside the tree being verified"
    # Return the vector to start, and a refusal when the executable cannot be trusted to the
    # Details: caller.
    return [found, *argv[1:]], None


def run_verification(argv: Sequence[str], root: Path,
                     timeout: float = VERIFY_TIMEOUT) -> tuple[str, int | None, str]:
    """Start one admitted command and say what became of it.

    Nothing the command does raises: a non-zero exit, a timeout and a missing
    program are all results, because what is being measured is whether the check
    still passes. Output is decoded as UTF-8 with replacement rather than by the
    console codec, which is cp932 here and has already killed one gate mid-run by
    raising on a character it could not encode.

    @param argv the vector to start, already rewritten by `verification_vector`
        Each arguments element is one process argument string; invocation order is preserved.
    @param root the working directory, which is the tree the ledger belongs to
    @param timeout seconds before the command is killed
    @return the outcome word, the exit status when there was one, and one line of detail
    """
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Preserve the external command representation and its observed completion outcome.
        finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - allowlisted argv, list form, never a shell
            list(argv), cwd=root, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except subprocess.TimeoutExpired:
        # Return the outcome word, the exit status when there was one, and one line of detail to
        # Details: the caller.
        return "timeout", None, f"killed after {timeout:g}s without finishing"
    # Preserve the caught failure that explains why the external result is unusable.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except OSError as exc:
        # Return the outcome word, the exit status when there was one, and one line of detail to
        # Details: the caller.
        return "unavailable", None, f"could not be started: {exc.strerror or exc}"
    # Enter the failure path only when the subprocess reports a nonzero status.
    if finished.returncode == 0:
        # Return the outcome word, the exit status when there was one, and one line of detail to
        # Details: the caller.
        return "passed", 0, "exit 0"
    # Compute tail using  last line for later run verification logic.
    tail = _last_line(finished.stderr) or _last_line(finished.stdout) or "no output"
    # Return the outcome word, the exit status when there was one, and one line of detail to the
    # Details: caller.
    return "failed", finished.returncode, f"exit {finished.returncode}: {tail}"


def _last_line(text: str) -> str:
    """The last line worth quoting from a command's output.

    Colour codes are stripped first. Tools here emit them even into a pipe and
    even with `NO_COLOR` set, and an escape sequence in a report is noise in
    every reader that is not a terminal.

    @param text one captured stream
    @return the final non-blank line, truncated to fit a terminal and marked when
        it was cut, or empty when the stream carried nothing
    """
    # Each lines element represents one decoded record; lexical order is preserved.
    lines = [_ANSI.sub("", line).strip() for line in text.splitlines()]
    # Each kept element is one nonblank normalized output line in stream order.
    kept = [line for line in lines if line]
    # Select the empty-or-disabled path when kept has no usable value.
    if not kept:
        # Return the final non-blank line, truncated to fit a terminal and marked when to the
        # Details: caller.
        return ""
    # Compute last using kept[-1] for later last line logic.
    last = kept[-1]
    # Return the final non-blank line, truncated to fit a terminal and marked when to the
    # Details: caller.
    return last if len(last) <= _TAIL_WIDTH else last[:_TAIL_WIDTH] + "..."


def verify(store: Store, connection: sqlite3.Connection, *, execute: bool = False,
           timeout: float = VERIFY_TIMEOUT) -> list[VerifyResult]:
    """Replay what each live learning recorded as its own check.

    This is the one staleness signal the database has that depends on nobody's
    honesty. It is also partial, and saying so is part of the contract: a command
    that passes shows that the check it names still succeeds, which is weaker
    than the claim the entry makes. `doxygen enforce/Doxyfile` exiting 0 does not
    establish anything about how the engine reads a particular annotation.

    Retired entries are left alone. They are not offered to anyone, so their
    staleness is not a fact about anything, and re-refuting a refuted entry would
    add a ledger event that changes nothing.

    @param store the tree the commands run in, which is also where the ledger lives
    @param connection an index already folded from the ledger
    @param execute whether to start the commands; without it every admitted
        command is reported as `skipped` together with the vector that would have
        been started, which is what makes dry running the default
        True enables execute; false selects its disabled alternative.
    @param timeout seconds each command is given before it is killed
    @return one result per live entry carrying a verification command, ordered by id
    """
    # Preserve rows element values in deterministic source order.
    rows = connection.execute(
        "SELECT id, verification FROM learning "  # ruff: ignore[hardcoded-sql-expression] - placeholders, not values
        "WHERE verification IS NOT NULL AND verification != '' "
        f"AND status NOT IN ({','.join('?' * len(RETIRED))}) ORDER BY id",
        RETIRED,
    ).fetchall()

    # Each results element is one verification observation in learning-id query order.
    results: list[VerifyResult] = []
    # Select row as the current element from rows while verify preserves traversal order.
    # Advance verify through the current input element in declared order.
    for row in rows:
        # Preserve the external command representation and its observed completion outcome.
        command = row["verification"]
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            # Compute argv using verification argv for later verify logic.
            argv = verification_argv(command)
        # Preserve the caught failure that explains why the external result is unusable.
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except LearnError as exc:
            results.append(VerifyResult(row["id"], command, "refused", str(exc)))
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Compute refusal using verification refusal for later verify logic.
        refusal = verification_refusal(argv, store.root)
        # Use the available-value path only when refusal is present.
        if refusal is not None:
            results.append(VerifyResult(row["id"], command, "refused", refusal))
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Unpack unsafe, vector using verification vector for later verify logic.
        vector, unsafe = verification_vector(argv, store.root)
        # Use the available-value path only when unsafe is present.
        if unsafe is not None:
            results.append(VerifyResult(row["id"], command, "refused", unsafe))
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Select the empty-or-disabled path when execute has no usable value.
        if not execute:
            results.append(
                VerifyResult(row["id"], command, "skipped",
                             f"would run: {shlex.join(vector)}")
            )
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Capture code, detail, outcome as the completed verify outcome for subsequent
        # Details: validation or publication.
        outcome, code, detail = run_verification(vector, store.root, timeout)
        results.append(VerifyResult(row["id"], command, outcome, detail, code))
    # Return one result per live entry carrying a verification command, ordered by id to the
    # Details: caller.
    return results


def refute_failures(store: Store, results: Sequence[VerifyResult],
                    session: str) -> list[VerifyResult]:
    """Append one refutation per command that ran and failed.

    Only `failed` counts. A refusal, a timeout or a missing program says the
    check could not be run here, which is a fact about this machine and must not
    retire an entry. The event kind is the existing `refute`, so the fold, the
    schema and everything reading the ledger are untouched: a verification
    failure is a contradiction found by a machine rather than by an agent, and
    [LEARN-005] already says a contradicted learning is refuted, never deleted.

    Refuting is a one-way door -- the fold never revisits a retired entry -- which
    is why it is behind its own flag rather than done automatically. A refutation
    that turns out to have been an environment problem is corrected the way
    everything here is corrected: by recording a fresh entry, not by editing.

    @param store where the ledger lives
    @param results what `verify` found
        Each element is one verification observation in learning-id order.
    @param session the session the refutations are attributed to
    @return the results a refutation was appended for
    @throws LearnError never for a command's own behaviour; the secret guard's
        refusal is caught per entry and reported rather than abandoning the rest
    """
    # Each written element is one failed verification whose refutation event was appended, in
    # input result order.
    written: list[VerifyResult] = []
    # Capture result as the completed refute failures outcome for subsequent validation or
    # Details: publication.
    # Advance refute failures through the current input element in declared order.
    for result in results:
        # Select the guarded path only after `result.outcome != 'failed'` is satisfied.
        if result.outcome != "failed":
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Compute why using (f"verification failed: `{result.command}` exited {result.co for
        # Details: later refute failures logic.
        why = (f"verification failed: `{result.command}` exited {result.code}. "
               f"{result.detail}")
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            append_event(store, "refute", session, {"ref": result.learning_id, "why": why})
        # Preserve the caught failure that explains why the external result is unusable.
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except LearnError as exc:
            print(f"  {result.learning_id}  NOT REFUTED  {exc}", file=sys.stderr)
            # Advance after the current candidate has been conclusively excluded.
            continue
        written.append(result)
    # Return the results a refutation was appended for to the caller.
    return written


# ------------------------------------------------------------ generated views


## The banner both generated files open with, so an edit made by hand is visibly
## a mistake: the next sync overwrites the file without asking.
GENERATED = "<!-- GENERATED by tools/learn.py sync -- do not edit; append an event instead. -->"


def render_index(connection: sqlite3.Connection, config: dict[str, Any]) -> str:
    """Every learning, grouped by status, as a page a person can read in a diff.

    Deterministic: ordering and content are functions of the log, so two syncs of
    the same ledger produce the same bytes and a review sees only real change.
    The confidence shown is the stored value, not the decayed one retrieval uses.

    @param connection an index already folded from the ledger
    @param config accepted for symmetry with `render_calibration`; nothing here reads it
        Each key is a configuration section and each value is its tunable mapping; mapping key
        order is deliberately unused.
    @return the full text of `INDEX.md`, ending in a single newline
    """
    # Preserve rows element values in deterministic source order.
    rows = list(connection.execute("SELECT * FROM learning ORDER BY id"))
    # Each lines element represents one decoded record; lexical order is preserved.
    lines = [
        GENERATED,
        "",
        "# Learnings",
        "",
        "What using this discipline in this repository has taught. Written by agents, "
        "folded from `ledger.jsonl`, and read back through `tools/learn.py retrieve`.",
        "",
        "Confidence here is the stored, evidence-derived value. What retrieval uses is "
        "that number decayed by time since the entry was last seen, so an old entry is "
        "offered more quietly than this table suggests.",
        "",
    ]
    # Select the empty-or-disabled path when rows has no usable value.
    if not rows:
        # Preserve lines element values in deterministic source order.
        lines += [
            "*Empty.* Nothing has been recorded yet. The first task to use the database "
            "is also its first calibration datum: see `calibration.md`.",
            "",
        ]
        # Return the full text of `INDEX.md`, ending in a single newline to the caller.
        return "\n".join(lines)

    # Each by-status key is a learning status and each value lists id-ordered rows; first-seen
    # status order is preserved in the rendered view.
    by_status: dict[str, list[sqlite3.Row]] = {}
    # Select row as the current element from rows while render index preserves traversal order.
    # Advance render index through the current input element in declared order.
    for row in rows:
        by_status.setdefault(row["status"], []).append(row)

    # Preserve lines element values in deterministic source order.
    lines += ["| Status | Count |", "|---|---|"]
    # Preserve items, lines, status element values in deterministic source order.
    lines += [f"| {status} | {len(items)} |" for status, items in sorted(by_status.items())]
    lines.append("")

    # Capture status as the completed render index outcome for subsequent validation or
    # Details: publication.
    # Advance render index through the current input element in declared order.
    for status in ("active", "candidate", "promoted", "superseded", "refuted"):
        # Preserve items element values in deterministic source order.
        items = by_status.get(status)
        # Select the empty-or-disabled path when items has no usable value.
        if not items:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Preserve lines element values in deterministic source order.
        lines += [f"## {status}", ""]
        # Select row as the current element from items while render index preserves traversal
        # Details: order.
        # Advance render index through the current input element in declared order.
        for row in items:
            # Preserve lines element values in deterministic source order.
            lines += _render_learning_entry(connection, row)
    # Return the full text of `INDEX.md`, ending in a single newline to the caller.
    return "\n".join(lines).rstrip() + "\n"


def _render_learning_entry(connection: sqlite3.Connection, row: sqlite3.Row) -> list[str]:
    """One learning as a readable block, with only the fields it actually has.

    The optional lines are omitted rather than emitted empty, so a diff of this
    file shows a learning gaining a verification command or a promotion as an
    added line instead of a changed one.

    @param connection an index already folded from the ledger
    @param row the learning's folded state
    @return the block's lines, ending in one blank
    """
    # Each triggers element is one rendered type/pattern pair in SQL lexical order.
    triggers = [
        f"`{t['type']}:{t['pattern']}`" for t in connection.execute(
            "SELECT type, pattern FROM trigger WHERE learning_id = ? "
            "ORDER BY type, pattern", (row["id"],)
        )
    ]
    # Each links element is one related node id in SQL lexical order.
    links = [
        l["node"] for l in connection.execute(  # ruff: ignore[ambiguous-variable-name] - row alias
            "SELECT node FROM link WHERE learning_id = ? ORDER BY node", (row["id"],)
        )
    ]
    # Each lines element represents one decoded record; lexical order is preserved.
    lines = [
        f"### {row['id']} · {row['claim']}",
        "",
        f"- **Do** {row['action']}",
        f"- **Kind** {row['kind']} · **scope** {row['scope']} · "
        f"**evidence** {row['evidence']} "
        f"(+{row['helped']}/-{row['noise']} over {row['sessions']} session(s))",
        f"- **Confidence** {row['confidence']:.2f}, last seen {row['last_seen_ts'][:10]}",
        f"- **Triggers** {', '.join(triggers) or 'none'}",
    ]
    # Each optional element pairs a presence value with its rendered line, in about, verify,
    # promotion, then supersession order.
    optional = (
        (links, f"- **About** {', '.join(links)}"),
        (row["verification"], f"- **Verify** `{row['verification']}`"),
        (row["promoted_to"],
         f"- **Promoted to** `{row['promoted_to']}` — retired from retrieval"),
        (row["superseded_by"], f"- **Superseded by** {row['superseded_by']}"),
        (row["note"], f"- **Note** {row['note']}"),
    )
    # Retain the immutable source representation consumed by subsequent analysis.
    lines += [text for present, text in optional if present]
    lines.append("")
    # Return the block's lines, ending in one blank to the caller.
    return lines


def render_calibration(connection: sqlite3.Connection, config: dict[str, Any],
                       as_of: dt.date) -> str:
    """The metrics a calibration pass reads.

    The date appears because the subject is time — staleness cannot be reported
    without one. It is a parameter, not a wall-clock stamp, so regenerating with
    the same `--as-of` reproduces the file byte for byte.

    With nothing recorded the totals are still printed, precision reading `n/a`
    because nothing has been offered yet, and a first-run protocol is appended
    saying what to measure in place of a number that does not exist.

    @param connection an index already folded from the ledger
    @param config the tunables: its retrieval and promotion sections are tabulated
        verbatim, and its decay table decides how many entries count as stale
        Each key is a configuration section and each value is its tunable mapping; declared TOML
        order is preserved when tabulating settings.
    @param as_of the date staleness and decay are measured to
    @return the full text of `calibration.md`, ending in a single newline
    """
    # Compute learnings using list for later render calibration logic.
    learnings = list(connection.execute("SELECT * FROM learning"))
    # Compute usages using list for later render calibration logic.
    usages = list(connection.execute("SELECT * FROM usage"))
    # Compute sessions using list for later render calibration logic.
    sessions = list(connection.execute("SELECT * FROM session"))
    # Select helped, u as the current element from usages if u["outcome"] == "helped") while
    # Details: render calibration preserves traversal order.
    helped = sum(1 for u in usages if u["outcome"] == "helped")
    # Select the captured Doxygen diagnostics that explain the failed build.
    noise = sum(1 for u in usages if u["outcome"] == "noise")
    # Select contradicted, u as the current element from usages if u["outcome"] ==
    # Details: "contradicted") while render calibration preserves traversal order.
    contradicted = sum(1 for u in usages if u["outcome"] == "contradicted")
    # Compute offered using len for later render calibration logic.
    offered = len(usages)
    # Compute precision using f"{helped / offered:.0%}" if offered else "n/a" for later render
    # Details: calibration logic.
    precision = f"{helped / offered:.0%}" if offered else "n/a"

    # Each kinds key is a learning kind and each value is its count; first-seen row order is
    # preserved in the calibration table.
    kinds: dict[str, int] = {}
    # Select row as the current element from learnings while render calibration preserves
    # Details: traversal order.
    # Advance render calibration through the current input element in declared order.
    for row in learnings:
        # Update render calibration state only after the required source facts are available.
        kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1

    # Unpack stale, row using sum for later render calibration logic.
    stale = sum(
        1 for row in learnings
        if effective_confidence(row["confidence"], row["last_seen_ts"], row["kind"],
                                config, as_of) < row["confidence"] / 2
    )

    # Each lines element represents one decoded record; lexical order is preserved.
    lines = [
        GENERATED,
        "",
        "# Calibration",
        "",
        f"As of **{as_of.isoformat()}**. Regenerate with "
        f"`python tools/learn.py calibrate --as-of {as_of.isoformat()}`.",
        "",
        "## Totals",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| sessions recorded | {len(sessions)} |",
        f"| learnings recorded | {len(learnings)} |",
        f"| outcomes reported | {offered} |",
        f"| of those, helped | {helped} |",
        f"| of those, noise | {noise} |",
        f"| of those, contradicted | {contradicted} |",
        f"| **retrieval precision** | **{precision}** |",
        f"| active | {sum(1 for r in learnings if r['status'] == 'active')} |",
        f"| promoted into a mechanism | {sum(1 for r in learnings if r['status'] == 'promoted')} |",
        f"| refuted | {sum(1 for r in learnings if r['status'] == 'refuted')} |",
        f"| stale (past one half-life) | {stale} |",
        "",
    ]

    # Handle the non-empty or enabled kinds state.
    if kinds:
        # Preserve lines element values in deterministic source order.
        lines += ["## Kinds", "", "| Kind | Count |", "|---|---|"]
        # Preserve k, lines, v element values in deterministic source order.
        lines += [f"| {k} | {v} |" for k, v in sorted(kinds.items())]
        lines.append("")

    # Select the empty-or-disabled path when learnings has no usable value.
    if not learnings:
        # Preserve lines element values in deterministic source order.
        lines += [
            "## First-run protocol",
            "",
            "The database is empty, so retrieval precision cannot be measured yet — there",
            "was nothing to retrieve. The first task that uses it measures the bootstrap",
            "instead:",
            "",
            "1. **How many learnings were recorded, and of which kinds?** If one kind takes",
            "   nearly all of them, the taxonomy is wrong and calibration should narrow it.",
            "2. **What did the write step cost?** Recording must stay cheap enough that it",
            "   survives a busy session; if it does not, nothing else here matters.",
            "3. **Which of the entries recorded at the end would have helped at the start?**",
            "   That count is the first real signal of whether the database is worth its",
            "   cost, and it is the number to carry into the next pass.",
            "",
        ]

    # Preserve lines element values in deterministic source order.
    lines += [
        "## Parameters in force",
        "",
        "| Setting | Value |",
        "|---|---|",
    ]
    # Select section as the current element from ("retrieval", "promotion") while render
    # Details: calibration preserves traversal order.
    # Advance render calibration through the current input element in declared order.
    for section in ("retrieval", "promotion"):
        # Treat the current key, value as the candidate element consumed by the enclosing
        # Details: transformation.
        # Advance render calibration through the current input element in declared order.
        for key, value in sorted(config[section].items()):
            lines.append(f"| `{section}.{key}` | {value} |")
    # Preserve lines element values in deterministic source order.
    lines += [
        "",
        "Change one with `python tools/learn.py calibrate --set retrieval.max_learnings=8 "
        '--why "..."`, which edits `config.toml` and appends a `calibrate` event. A '
        "parameter changed without that event is indistinguishable from drift.",
    ]
    # Return the full text of `calibration.md`, ending in a single newline to the caller.
    return "\n".join(lines).rstrip() + "\n"


def write_views(store: Store, connection: sqlite3.Connection, as_of: dt.date) -> None:
    """Overwrite both generated files, so the readable state cannot lag the log.

    Called after every write rather than on demand: a view that is only current
    when someone remembers to refresh it is a view nobody can cite.

    @param store where the two files are written
    @param connection an index already folded from the ledger
    @param as_of the date the calibration report is measured to

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Compute config using store.config for later write views logic.
    config = store.config()
    # Publish the externally visible effect after all required inputs are ready.
    store.index.write_text(
        render_index(connection, config), encoding="utf-8", newline="\n"
    )
    # Publish the externally visible effect after all required inputs are ready.
    store.calibration.write_text(
        render_calibration(connection, config, as_of), encoding="utf-8", newline="\n"
    )


# ---------------------------------------------------------------- graph layer


def graph_overlay(store: Store) -> Iterator[tuple[str, str, str, str, float]]:
    """Learnings as graph nodes and edges: (id, label, relation, node, weight).

    Consumed by `nav.py` so a reading plan can carry what was learned about the
    rules it selected. Overlaid at query time; the static graph stays untouched.

    A missing or unreadable database yields nothing rather than failing. The
    overlay is an enrichment, and navigation has to work before anything has
    been learned.

    @param store where the database lives
    @return one tuple per link of every candidate or active entry, ordered by id then
        node, weighted by the stored confidence rather than the decayed one

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Select the existing-artifact path only when `not store.db.exists()` is satisfied.
    if not store.db.exists():
        # Return one tuple per link of every candidate or active entry, ordered by id then to
        # Details: the caller.
        return
    # Compute connection using sqlite3.connect for later graph overlay logic.
    connection = sqlite3.connect(store.db)
    # Update graph overlay state only after the required source facts are available.
    connection.row_factory = sqlite3.Row
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Preserve rows element values in deterministic source order.
        rows = connection.execute(
            "SELECT l.id, l.claim, l.confidence, k.relation, k.node "
            "FROM learning l JOIN link k ON k.learning_id = l.id "
            "WHERE l.status IN ('candidate','active') ORDER BY l.id, k.node"
        ).fetchall()
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except sqlite3.DatabaseError:
        # Return one tuple per link of every candidate or active entry, ordered by id then to
        # Details: the caller.
        return
    finally:
        # Publish the externally visible effect after all required inputs are ready.
        connection.close()
    # Select row as the current element from rows while graph overlay preserves traversal order.
    # Advance graph overlay through the current input element in declared order.
    for row in rows:
        yield row["id"], row["claim"], row["relation"], row["node"], row["confidence"]


# ------------------------------------------------------------------ commands


def cmd_record(store: Store, args: argparse.Namespace) -> int:
    """Check one entry against the write policy, append it, and republish the views.

    Every policy check runs before the append, so a rejected entry leaves no
    trace in the record. An entry with no trigger is refused outright: nothing
    could ever retrieve it, so writing it would be pure cost.

    @param store where the ledger and the configuration live
    @param args the parsed `record` arguments
    @return 0 once the entry is written and the views regenerated
    @throws LearnError when the kind is disabled, a required action or trigger is absent,
        a trigger is malformed, or the entry carries something credential-shaped

    @par Effects
    Writes the completed diagnostic or result representation to standard output.
    """
    # Compute config using store.config for later cmd record logic.
    config = store.config()
    # Select the guarded path only after `args.kind not in config['write']['kinds_enabled']` is
    # Details: satisfied.
    if args.kind not in config["write"]["kinds_enabled"]:
        # Compute message using f"kind {args.kind!r} is not enabled; see learning/config.tom for
        # Details: later cmd record logic.
        message = f"kind {args.kind!r} is not enabled; see learning/config.toml"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise LearnError(message)
    # Select the guarded path only after `config['write']['require_action'] and (not
    # Details: args.action)` is satisfied.
    if config["write"]["require_action"] and not args.action:
        # Compute message using "a learning must say what to do differently, not only what i for
        # Details: later cmd record logic.
        message = "a learning must say what to do differently, not only what is true"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise LearnError(message)
    # Each triggers element is one parsed trigger in command-line order.
    triggers = [parse_trigger(t) for t in args.trigger or []]
    # Select the guarded path only after `config['write']['require_trigger'] and (not triggers)`
    # Details: is satisfied.
    if config["write"]["require_trigger"] and not triggers:
        # Compute message using ( for later cmd record logic.
        message = (
            "a learning with no trigger can never be retrieved. Add at least one "
            "--trigger glob:... / error:... / rule:... / command:... / term:..."
        )
        # Propagate the localized failure so callers cannot mistake it for success.
        raise LearnError(message)

    # Compute connection using sync for later cmd record logic.
    connection = sync(store)
    # Compute learning id using next learning id for later cmd record logic.
    learning_id = next_learning_id(connection)
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()

    # Each payload key is a learn-event field and each value is caller-supplied content;
    # insertion order defines stable ledger JSON.
    payload = {
        "id": learning_id,
        "kind": args.kind,
        "scope": args.scope,
        "claim": args.claim,
        "action": args.action,
        "evidence": args.evidence,
        "triggers": triggers,
        "links": [{"relation": "learned_about", "node": n} for n in args.link or []],
    }
    # Select the guarded path only after `args.verify` is satisfied.
    if args.verify:
        # Update cmd record state only after the required source facts are available.
        payload["verification"] = args.verify
    append_event(store, "learn", session_id(args.session), payload)
    # Compute connection using sync for later cmd record logic.
    connection = sync(store)
    write_views(store, connection, dt.date.today())
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    print(f"recorded {learning_id}")
    # Return 0 once the entry is written and the views regenerated to the caller.
    return 0


def cmd_retrieve(store: Store, args: argparse.Namespace) -> int:
    """Print what is known about a situation, its context cost, and how to report back.

    `--json` prints the same candidates as data instead, without the cost line or
    the reminder, for a caller that is not a person reading a terminal.

    @param store where the ledger and the configuration live
    @param args the parsed `retrieve` arguments
    @return 0, including when nothing matched; an empty answer is a valid one

    @par Effects
    Writes the completed diagnostic or result representation to standard output.
    """
    # Compute connection using sync for later cmd retrieve logic.
    connection = sync(store)
    # Preserve the optional pattern match that carries the reported analysis count.
    found = retrieve(
        store, connection, file=args.file, error=args.error, task=args.task,
        rules=args.rule or [],
    )
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    # Select the guarded path only after `args.json` is satisfied.
    if args.json:
        # asdict, not __dict__: these are slotted dataclasses and have no instance
        # dictionary at all, so reading one raises rather than returning the fields.
        print(json.dumps([asdict(c) for c in found], indent=1, ensure_ascii=False))
        return 0
    # Select the empty-or-disabled path when found has no usable value.
    if not found:
        print("LEARNED  nothing recorded matches this situation")
        # Return 0, including when nothing matched; an empty answer is a valid one to the
        # Details: caller.
        return 0
    print(f"LEARNED ({len(found)})")
    # Treat the current candidate as the candidate element consumed by the enclosing
    # Details: transformation.
    # Advance cmd retrieve through the current input element in declared order.
    for candidate in found:
        print(candidate.render())
    # Select c as the current element from found)} tok") while cmd retrieve preserves traversal
    # Details: order.
    print(f"\n  cost {sum(count_tokens(c.render()) for c in found)} tok")
    print("  report what came of these:  learn.py used <id> --outcome helped|noise")
    # Return 0, including when nothing matched; an empty answer is a valid one to the caller.
    return 0


def cmd_outcome(store: Store, args: argparse.Namespace) -> int:
    """Append the feedback event behind `used`, `refute`, `supersede` and `promote`.

    One function for four subcommands because they differ only in the payload
    they carry; what each one means to confidence and status is the fold's
    business, not the command's.

    @param store where the ledger lives
    @param args the parsed arguments, whose `command` selects the event kind
    @return 0 once the event is written and the views regenerated

    @par Effects
    Writes the completed diagnostic or result representation to standard output.
    """
    # Compute kind using {"used": "use", "refute": "refute", "supersede": "supersede" for later
    # Details: cmd outcome logic.
    kind = {"used": "use", "refute": "refute", "supersede": "supersede",
            "promote": "promote"}[args.command]
    # Each payload key is an outcome-event field and each value is caller-supplied content;
    # insertion order defines stable ledger JSON.
    payload: dict[str, Any] = {"ref": args.id}
    # Select the guarded path only after `args.command == 'used'` is satisfied.
    if args.command == "used":
        # Update cmd outcome state only after the required source facts are available.
        payload["outcome"] = args.outcome
        # Update cmd outcome state only after the required source facts are available.
        payload["note"] = args.note
    # Select the guarded path only after `args.command == 'refute'` is satisfied.
    elif args.command == "refute":
        # Update cmd outcome state only after the required source facts are available.
        payload["why"] = args.why
    # Select the guarded path only after `args.command == 'supersede'` is satisfied.
    elif args.command == "supersede":
        # Update cmd outcome state only after the required source facts are available.
        payload["by"] = args.by
    else:
        # Update cmd outcome state only after the required source facts are available.
        payload["mechanism"] = args.mechanism
        # Update cmd outcome state only after the required source facts are available.
        payload["note"] = args.note
    append_event(store, kind, session_id(args.session), payload)
    # Compute connection using sync for later cmd outcome logic.
    connection = sync(store)
    write_views(store, connection, dt.date.today())
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    print(f"{kind} recorded for {args.id}")
    # Return 0 once the event is written and the views regenerated to the caller.
    return 0


def cmd_verify(store: Store, args: argparse.Namespace) -> int:
    """Replay the recorded verification commands and report which no longer pass.

    Dry by default. Without `--execute` nothing is started: each admitted command
    is printed as what *would* run, and each refused one is refused just the
    same, so the security posture can be read off a run that does nothing.

    Every refusal is printed twice -- in the body and again on stderr -- because
    the case it exists for is a ledger that arrived from another repository, and
    a refusal nobody notices is the same as no allowlist at all. `--json` is no
    exception: stdout stays parsable, so the stderr copy of each refusal and the
    caveat about what a pass proves are what a machine-read run gets, and neither
    is dropped merely because nobody is watching the terminal.

    @param store where the ledger lives and where the commands are run
    @param args the parsed `verify` arguments
    @return 0; a failing verification is the measurement, not an error in taking it
    @throws LearnError when refutations are asked for without `--execute`, which
        would record failures that were never observed

    @par Effects
    Writes the completed diagnostic or result representation to standard output.
    """
    # Select the guarded path only after `args.refute_failures and (not args.execute)` is
    # Details: satisfied.
    if args.refute_failures and not args.execute:
        # Compute message using "--refute-failures needs --execute; nothing has been run to  for
        # Details: later cmd verify logic.
        message = "--refute-failures needs --execute; nothing has been run to refute"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise LearnError(message)

    # Compute connection using sync for later cmd verify logic.
    connection = sync(store)
    # Compute results using verify for later cmd verify logic.
    results = verify(store, connection, execute=args.execute, timeout=args.timeout)
    # Compute total using connection.execute for later cmd verify logic.
    total = connection.execute("SELECT COUNT(*) n FROM learning").fetchone()["n"]
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()

    # Capture result as the completed cmd verify outcome for subsequent validation or
    # Details: publication.
    # Advance cmd verify through the current input element in declared order.
    for result in results:
        # Select the guarded path only after `result.outcome == 'refused'` is satisfied.
        if result.outcome == "refused":
            print(f"REFUSED {result.learning_id}: {result.command}\n  {result.detail}",
                  file=sys.stderr)

    # Select the guarded path only after `args.json` is satisfied.
    if args.json:
        # Select r as the current element from results], indent=1, ensure_ascii=False)) while
        # Details: cmd verify preserves traversal order.
        print(json.dumps([asdict(r) for r in results], indent=1, ensure_ascii=False))
        print(VERIFY_CAVEAT, file=sys.stderr)
        # Return 0; a failing verification is the measurement, not an error in taking it to the
        # Details: caller.
        return 0

    # Compute mode using "ran" if args.execute else "dry run: nothing was started" for later cmd
    # Details: verify logic.
    mode = "ran" if args.execute else "dry run: nothing was started"
    print(f"VERIFY ({len(results)} live command(s) across {total} learning(s); {mode})")
    # Capture result as the completed cmd verify outcome for subsequent validation or
    # Details: publication.
    # Advance cmd verify through the current input element in declared order.
    for result in results:
        print(result.render())

    # Each tally key is a verification outcome and each value is its count; summary order follows
    # ``VERIFY_OUTCOMES``.
    tally = {outcome: sum(1 for r in results if r.outcome == outcome)
             for outcome in VERIFY_OUTCOMES}
    # Normalize the current repository path to its portable baseline key spelling.
    print("\n  " + ", ".join(f"{n} {name}" for name, n in tally.items() if n))
    print(f"  {VERIFY_CAVEAT}")

    # Select the guarded path only after `args.refute_failures` is satisfied.
    if args.refute_failures:
        # Compute written using refute failures for later cmd verify logic.
        written = refute_failures(store, results, session_id(args.session))
        # Compute connection using sync for later cmd verify logic.
        connection = sync(store)
        write_views(store, connection, dt.date.today())
        # Publish the externally visible effect after all required inputs are ready.
        connection.close()
        # Bind r to the current value used by the next cmd verify decision.
        print(f"  refuted {len(written)} learning(s): "
              f"{', '.join(r.learning_id for r in written) or 'none'}")
    # Return 0; a failing verification is the measurement, not an error in taking it to the
    # Details: caller.
    return 0


def cmd_session(store: Store, args: argparse.Namespace) -> int:
    """Open a session and print its id, so what follows can be attributed to one sitting.

    @param store where the ledger lives
    @param args the parsed `session` arguments
    @return 0; the id goes to stdout for later commands to pass back

    @par Effects
    Writes the completed diagnostic or result representation to standard output.
    """
    # Compute identifier using session id for later cmd session logic.
    identifier = session_id(args.session)
    append_event(store, "session", identifier,
                 {"task": args.task, "discipline_version": args.discipline_version})
    # Compute connection using sync for later cmd session logic.
    connection = sync(store)
    write_views(store, connection, dt.date.today())
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    print(identifier)
    # Return 0; the id goes to stdout for later commands to pass back to the caller.
    return 0


def cmd_sync(store: Store, args: argparse.Namespace) -> int:
    """Rebuild the index and both views, reporting what the ledger folded into.

    The counts are printed so drift is visible: a ledger that grew without the
    learning count moving says the fold ignored something.

    @param store where the ledger lives
    @param args the parsed `sync` arguments; `--as-of` dates the calibration report
    @return 0 once the projections match the ledger

    @par Effects
    Writes the completed diagnostic or result representation to standard output.
    """
    # Compute connection using sync for later cmd sync logic.
    connection = sync(store)
    write_views(store, connection, args.as_of or dt.date.today())
    # Compute counts using connection.execute for later cmd sync logic.
    counts = connection.execute(
        "SELECT (SELECT COUNT(*) FROM event) e, (SELECT COUNT(*) FROM learning) l, "
        "(SELECT COUNT(*) FROM usage) u"
    ).fetchone()
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    print(f"synced {counts['e']} event(s) -> {counts['l']} learning(s), {counts['u']} outcome(s)")
    # Return 0 once the projections match the ledger to the caller.
    return 0


def cmd_status(store: Store, args: argparse.Namespace) -> int:
    """Print the ledger's size and the tally of entries by status, in one screen.

    @param store where the ledger lives
    @param args the parsed arguments, unused beyond selecting this command
    @return 0, whether or not anything has been recorded

    @par Effects
    Writes the completed diagnostic or result representation to standard output.
    """
    # Compute connection using sync for later cmd status logic.
    connection = sync(store)
    # Preserve rows element values in deterministic source order.
    rows = list(connection.execute(
        "SELECT status, COUNT(*) n FROM learning GROUP BY status ORDER BY status"
    ))
    # Compute events using connection.execute for later cmd status logic.
    events = connection.execute("SELECT COUNT(*) n FROM event").fetchone()["n"]
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    print(f"{events} event(s) in {store.ledger.name}")
    # Select row as the current element from rows while cmd status preserves traversal order.
    # Advance cmd status through the current input element in declared order.
    for row in rows:
        print(f"  {row['status']:<12} {row['n']}")
    # Select the empty-or-disabled path when rows has no usable value.
    if not rows:
        print("  (no learnings yet)")
    # Return 0, whether or not anything has been recorded to the caller.
    return 0


def cmd_calibrate(store: Store, args: argparse.Namespace) -> int:
    """Print the metrics, and move a dial only with the reason recorded beside it.

    A `--set` without a `--why` is refused, and every accepted change is appended
    as an event: a parameter that moved for no stated reason is indistinguishable
    from drift when someone later asks why retrieval behaves as it does.

    @param store where the ledger and the configuration live
    @param args the parsed `calibrate` arguments
    @return 0 once the report has been printed
    @throws LearnError when a setting is changed without a reason, or names nothing

    @par Effects
    Writes the completed diagnostic or result representation to standard output.
    """
    # Compute as of using args.as_of or dt.date.today() for later cmd calibrate logic.
    as_of = args.as_of or dt.date.today()
    # Select the guarded path only after `args.set` is satisfied.
    if args.set:
        # Select the empty-or-disabled path when args.why has no usable value.
        if not args.why:
            # Compute message using "a parameter change needs --why; an untraced change is drift
            # Details: for later cmd calibrate logic.
            message = "a parameter change needs --why; an untraced change is drift"
            # Propagate the localized failure so callers cannot mistake it for success.
            raise LearnError(message)
        # Compute changed using  apply settings for later cmd calibrate logic.
        changed = _apply_settings(store, args.set)
        append_event(store, "calibrate", session_id(args.session),
                     {"changed": changed, "why": args.why})
    # Compute connection using sync for later cmd calibrate logic.
    connection = sync(store)
    write_views(store, connection, as_of)
    # Hold the decoded checker report mapping for typed summary and diagnostic extraction.
    report = store.calibration.read_text(encoding="utf-8")
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    print(report)
    # Return 0 once the report has been printed to the caller.
    return 0


def _apply_settings(store: Store, assignments: Sequence[str]) -> dict[str, list[str]]:
    """Edit config.toml in place, one `section.key=value` at a time.

    The matching line is rewritten rather than the file reserialised, so the
    comments explaining each dial survive the change that most needs them. Only
    the bare key is matched and only the first line carrying it is rewritten, so
    two sections sharing a key name would collide on whichever comes first.

    @param store where the configuration lives
    @param assignments the raw assignments as they were typed
        Each element is one ``section.key=value`` spelling in command-line order.
    @return each dotted key mapped to its old and new value, for the event to carry
    @throws LearnError when an assignment has no `=`, or names no setting in the file

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Retain the immutable source representation consumed by subsequent analysis.
    text = store.config_path.read_text(encoding="utf-8")
    # Each changed key is a dotted setting and each value is ordered old then new text; mapping
    # insertion order follows assignment order.
    changed: dict[str, list[str]] = {}
    # Select assignment as the current element from assignments while apply settings preserves
    # Details: traversal order.
    # Advance apply settings through the current input element in declared order.
    for assignment in assignments:
        # Treat the current dotted, separator, value as the candidate element consumed by the
        # Details: enclosing transformation.
        dotted, separator, value = assignment.partition("=")
        # Select the empty-or-disabled path when separator has no usable value.
        if not separator:
            # Compute message using f"expected section.key=value, got {assignment!r}" for later
            # Details: apply settings logic.
            message = f"expected section.key=value, got {assignment!r}"
            # Propagate the localized failure so callers cannot mistake it for success.
            raise LearnError(message)
        # Treat the current key, section as the candidate element consumed by the enclosing
        # Details: transformation.
        section, _, key = dotted.strip().rpartition(".")
        # Compute pattern using re.compile for later apply settings logic.
        pattern = re.compile(rf"^({re.escape(key)}\s*=\s*)(.+)$", re.MULTILINE)
        # Preserve the optional pattern match that carries the reported analysis count.
        found = pattern.search(text)
        # Use the absence path when found has no available value.
        if found is None:
            # Compute message using f"no setting named {dotted!r} in {store.config_path.name}"
            # Details: for later apply settings logic.
            message = f"no setting named {dotted!r} in {store.config_path.name}"
            # Propagate the localized failure so callers cannot mistake it for success.
            raise LearnError(message)
        # Update  apply settings state only after the required source facts are available.
        changed[dotted.strip()] = [found.group(2).strip(), value.strip()]
        # Retain the immutable source representation consumed by subsequent analysis.
        text = pattern.sub(lambda m: m.group(1) + value.strip(), text, count=1)
    # Publish the externally visible effect after all required inputs are ready.
    store.config_path.write_text(text, encoding="utf-8", newline="\n")
    # Return each dotted key mapped to its old and new value, for the event to carry to the
    # Details: caller.
    return changed


# ---------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    """The whole command-line surface, and which half of it writes to the ledger.

    `record`, `used`, `refute`, `supersede`, `promote` and `session` each append
    an event; `calibrate` appends one when `--set` moves a dial, and `verify`
    appends one per failure when `--refute-failures` is given. The other three —
    `retrieve`, `sync` and `status` — only read and rebuild the derived files;
    the ledger they leave exactly as they found it.

    Two flags on `verify` are opt-ins rather than conveniences: `--execute`,
    because the commands come out of a data file, and `--refute-failures`,
    because a refutation cannot be taken back.

    @return a parser that rejects an invocation naming no subcommand
    """
    # Configure the command-line parser that defines this tool's invocation contract.
    parser = argparse.ArgumentParser(description="Record and retrieve session learnings.")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--session", help="session id; one is generated if omitted")
    # Compute sub using parser.add subparsers for later build parser logic.
    sub = parser.add_subparsers(dest="command", required=True)

    # Compute rec using sub.add parser for later build parser logic.
    rec = sub.add_parser("record", help="record one learning")
    rec.add_argument("--kind", required=True, choices=LEARNING_KINDS)
    rec.add_argument("--claim", required=True, help="one sentence: what is true")
    rec.add_argument("--action", required=True, help="imperative: what to do differently")
    rec.add_argument("--trigger", action="append", metavar="TYPE:PATTERN")
    rec.add_argument("--link", action="append", metavar="NODE", help="a rule or module id")
    rec.add_argument("--verify", help="a command that confirms the claim still holds")
    rec.add_argument("--scope", default="project", choices=("project", "discipline"))
    rec.add_argument("--evidence", default="observed",
                     choices=("observed", "inferred", "told"))

    # Compute ret using sub.add parser for later build parser logic.
    ret = sub.add_parser("retrieve", help="what is known about this situation")
    ret.add_argument("--file")
    ret.add_argument("--error")
    ret.add_argument("--task")
    ret.add_argument("--rule", action="append")
    ret.add_argument("--json", action="store_true")

    # Compute used using sub.add parser for later build parser logic.
    used = sub.add_parser("used", help="report what came of a retrieved learning")
    used.add_argument("id")
    used.add_argument("--outcome", required=True,
                      choices=("helped", "noise", "contradicted"))
    used.add_argument("--note")

    # Preserve the immutable revision identity used as provenance for this comparison.
    ref = sub.add_parser("refute", help="record that a learning is wrong")
    ref.add_argument("id")
    ref.add_argument("--why", required=True)

    # Compute sup using sub.add parser for later build parser logic.
    sup = sub.add_parser("supersede", help="replace one learning with another")
    sup.add_argument("id")
    sup.add_argument("--by", required=True)

    # Compute pro using sub.add parser for later build parser logic.
    pro = sub.add_parser("promote", help="retire a learning into a mechanism")
    pro.add_argument("id")
    pro.add_argument("--mechanism", required=True)
    pro.add_argument("--note")

    # Compute ver using sub.add parser for later build parser logic.
    ver = sub.add_parser("verify", help="replay the recorded verification commands")
    ver.add_argument("--execute", action="store_true",
                     help="actually run them; without this nothing is started")
    ver.add_argument("--refute-failures", action="store_true",
                     help="with --execute, append a refutation for each command that failed")
    ver.add_argument("--timeout", type=float, default=VERIFY_TIMEOUT, metavar="SECONDS")
    ver.add_argument("--json", action="store_true")

    # Compute ses using sub.add parser for later build parser logic.
    ses = sub.add_parser("session", help="open a session")
    ses.add_argument("--task")
    ses.add_argument("--discipline-version")

    # Compute syn using sub.add parser for later build parser logic.
    syn = sub.add_parser("sync", help="rebuild the index and the views from the ledger")
    syn.add_argument("--as-of", type=dt.date.fromisoformat)

    sub.add_parser("status", help="a one-screen summary")

    # Compute cal using sub.add parser for later build parser logic.
    cal = sub.add_parser("calibrate", help="the metrics, and the dials")
    cal.add_argument("--as-of", type=dt.date.fromisoformat)
    cal.add_argument("--set", action="append", metavar="SECTION.KEY=VALUE")
    cal.add_argument("--why")
    # Return a parser that rejects an invocation naming no subcommand to the caller.
    return parser


## Subcommand name to the function that runs it. Four names share one function
## because they differ only in the payload they append.
## Each key is an accepted subcommand and each value is its handler; mapping key order is
## deliberately unused.
COMMANDS = {
    "record": cmd_record, "retrieve": cmd_retrieve, "used": cmd_outcome,
    "refute": cmd_outcome, "supersede": cmd_outcome, "promote": cmd_outcome,
    "session": cmd_session, "sync": cmd_sync, "status": cmd_status,
    "calibrate": cmd_calibrate, "verify": cmd_verify,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Run one subcommand, turning a refusal into a message rather than a traceback.

    Only LearnError is caught, because only it carries a message the caller can
    act on; anything else is a defect and keeps its traceback. Stdout is switched
    to UTF-8 first, so a console that cannot encode a character substitutes one
    rather than failing a command that had already done its work.

    @param argv the command line, defaulting to the process arguments
    @return 0 on success, 1 when the tool refused with its reason on stderr
    """
    # Select the guarded path only after `hasattr(sys.stdout, 'reconfigure')` is satisfied.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Capture the validated invocation arguments that govern this execution.
    args = build_parser().parse_args(argv)
    # Compute store using Store for later main logic.
    store = Store(args.root.resolve())
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Return the aggregate process status to the command-line boundary.
        return COMMANDS[args.command](store, args)
    # Preserve the caught failure that explains why the external result is unusable.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except LearnError as exc:
        print(f"error: {exc}", file=sys.stderr)
        # Return the aggregate process status to the command-line boundary.
        return 1


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    sys.exit(main())
