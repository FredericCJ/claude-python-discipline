"""The learning database: what using the discipline in this repository taught.

    python tools/learn.py record --kind diagnostic --claim "..." --action "..." \
        --trigger error:"adapters are independent" --link ARCH-003
    python tools/learn.py retrieve --file src/pkg/adapters/fs.py --error "..."
    python tools/learn.py used L-0001 --outcome helped
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
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import re
import sqlite3
import sys
import tomllib
import uuid
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from discipline_core import REPO_ROOT, count_tokens

SCHEMA_VERSION: Final = 1

TRIGGER_TYPES: Final = ("glob", "error", "rule", "command", "term")
LEARNING_KINDS: Final = ("diagnostic", "constraint", "procedure", "rule-application", "defect")
RETIRED: Final = ("superseded", "refuted", "promoted")

## Material that must never enter the ledger. The ledger is designed to be read
## widely and machine-processed, which is exactly what makes a credential in it
## expensive. DIAG-014 applied to ourselves.
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


class LearnError(RuntimeError):
    """A refusal the caller can act on: the message says what to change."""


# ------------------------------------------------------------------- layout


@dataclass(frozen=True, slots=True)
class Store:
    """Where the learning database lives. Injected so tests get their own."""

    root: Path

    @property
    def dir(self) -> Path:
        return self.root / "learning"

    @property
    def ledger(self) -> Path:
        return self.dir / "ledger.jsonl"

    @property
    def db(self) -> Path:
        return self.dir / "learning.db"

    @property
    def schema(self) -> Path:
        # The schema is upstream-owned; a vendored copy falls back to this repo's.
        local = self.dir / "schema.sql"
        return local if local.exists() else REPO_ROOT / "learning" / "schema.sql"

    @property
    def config_path(self) -> Path:
        local = self.dir / "config.toml"
        return local if local.exists() else REPO_ROOT / "learning" / "config.toml"

    @property
    def index(self) -> Path:
        return self.dir / "INDEX.md"

    @property
    def calibration(self) -> Path:
        return self.dir / "calibration.md"

    def config(self) -> dict[str, Any]:
        return tomllib.loads(self.config_path.read_text(encoding="utf-8"))


def now_iso() -> str:
    """Wall clock, in one place so a test can replace it."""
    return dt.datetime.now(tz=dt.UTC).replace(microsecond=0).isoformat()


# ------------------------------------------------------------------- the log


def read_ledger(store: Store) -> list[dict[str, Any]]:
    """Every event, in order. The ledger is the record; the database is derived."""
    if not store.ledger.exists():
        return []
    events: list[dict[str, Any]] = []
    for number, line in enumerate(store.ledger.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            events.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            message = f"{store.ledger}:{number}: not valid JSON: {exc}"
            raise LearnError(message) from exc
    return events


def append_event(store: Store, kind: str, session: str, payload: dict[str, Any],
                 *, actor: str = "agent", ts: str | None = None) -> dict[str, Any]:
    """Append one event to the ledger and return it.

    Written as a single line so a concurrent appender cannot interleave, and so
    a merge conflict is resolvable by keeping both sides.
    """
    guard_secrets(payload)
    events = read_ledger(store)
    seq = len(events) + 1
    event = {
        "seq": seq,
        "id": f"E-{seq:06d}",
        "session": session,
        "ts": ts or now_iso(),
        "kind": kind,
        "actor": actor,
        "payload": payload,
    }
    store.dir.mkdir(parents=True, exist_ok=True)
    with store.ledger.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def guard_secrets(payload: dict[str, Any]) -> None:
    """Refuse to record anything credential-shaped."""
    blob = json.dumps(payload, ensure_ascii=False)
    for pattern, description in SECRET_PATTERNS:
        found = re.search(pattern, blob)
        if found is not None:
            message = (
                f"refusing to record: the entry contains {description} "
                f"({found.group(0)[:24]}...). Redact it and record the shape of the "
                f"problem, not the value."
            )
            raise LearnError(message)


# ------------------------------------------------------------------ the fold


def connect(store: Store) -> sqlite3.Connection:
    connection = sqlite3.connect(store.db)
    connection.row_factory = sqlite3.Row
    connection.executescript(store.schema.read_text(encoding="utf-8"))
    if not connection.execute("SELECT 1 FROM schema_version").fetchone():
        connection.execute(
            "INSERT INTO schema_version(version, applied_ledger_seq) VALUES (?, 0)",
            (SCHEMA_VERSION,),
        )
    return connection


def sync(store: Store) -> sqlite3.Connection:
    """Rebuild every projection by folding the ledger. Idempotent by construction."""
    store.dir.mkdir(parents=True, exist_ok=True)
    connection = connect(store)
    with connection:
        for table in ("usage", "link", "trigger", "learning", "session", "event"):
            connection.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed table names
        events = read_ledger(store)
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
    return connection


def _apply(connection: sqlite3.Connection, event: dict[str, Any],
           config: dict[str, Any]) -> None:
    """Fold one event into the projections."""
    kind, payload, seq = event["kind"], event["payload"], event["seq"]

    if kind == "session":
        connection.execute(
            "INSERT OR REPLACE INTO session(id, started_ts, task, discipline_version) "
            "VALUES (?, ?, ?, ?)",
            (event["session"], event["ts"], payload.get("task"),
             payload.get("discipline_version")),
        )
        return

    if kind == "learn":
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
        for trigger in payload.get("triggers", []):
            connection.execute(
                "INSERT OR IGNORE INTO trigger(learning_id, type, pattern) VALUES (?,?,?)",
                (payload["id"], trigger["type"], trigger["pattern"]),
            )
        connection.execute("DELETE FROM link WHERE learning_id = ?", (payload["id"],))
        for link in payload.get("links", []):
            connection.execute(
                "INSERT OR IGNORE INTO link(learning_id, relation, node) VALUES (?,?,?)",
                (payload["id"], link.get("relation", "learned_about"), link["node"]),
            )
        connection.execute(
            "UPDATE session SET recorded = recorded + 1 WHERE id = ?", (event["session"],)
        )
        _restatus(connection, payload["id"], config)
        return

    ref = payload.get("ref")
    if ref is None or not _exists(connection, ref):
        return

    if kind == "use":
        outcome = payload.get("outcome", "helped")
        connection.execute(
            "INSERT INTO usage(seq, learning_id, session, ts, outcome, note) VALUES (?,?,?,?,?,?)",
            (seq, ref, event["session"], event["ts"], outcome, payload.get("note")),
        )
        column = {"helped": "helped", "noise": "noise", "contradicted": "noise"}[outcome]
        delta = config["confidence"][
            "helped_delta" if outcome == "helped" else "noise_delta"
        ]
        connection.execute(
            f"UPDATE learning SET {column} = {column} + 1, "  # noqa: S608 - column from a fixed map
            "confidence = MAX(?, MIN(?, confidence + ?)), "
            "sessions = (SELECT COUNT(DISTINCT session) FROM usage WHERE learning_id = ?), "
            "last_seen_ts = ? WHERE id = ?",
            (config["confidence"]["floor"], config["confidence"]["ceiling"], delta,
             ref, event["ts"], ref),
        )
        _restatus(connection, ref, config)
    elif kind == "refute":
        connection.execute(
            "UPDATE learning SET status = 'refuted', note = ?, last_seen_ts = ? WHERE id = ?",
            (payload.get("why"), event["ts"], ref),
        )
    elif kind == "supersede":
        connection.execute(
            "UPDATE learning SET status = 'superseded', superseded_by = ?, last_seen_ts = ? "
            "WHERE id = ?",
            (payload.get("by"), event["ts"], ref),
        )
    elif kind == "promote":
        connection.execute(
            "UPDATE learning SET status = 'promoted', promoted_to = ?, note = ?, "
            "last_seen_ts = ? WHERE id = ?",
            (payload.get("mechanism"), payload.get("note"), event["ts"], ref),
        )


def _exists(connection: sqlite3.Connection, learning_id: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM learning WHERE id = ?", (learning_id,)
    ).fetchone() is not None


def _base_confidence(evidence: str, config: dict[str, Any]) -> float:
    return float(config["confidence"][f"base_{evidence}"])


def _restatus(connection: sqlite3.Connection, learning_id: str,
              config: dict[str, Any]) -> None:
    """Candidate becomes active once the evidence threshold is met.

    A verification command counts for more than a report: the check is the
    evidence, which is the axiom applied to learnings.
    """
    row = connection.execute(
        "SELECT helped, noise, sessions, verification, status FROM learning WHERE id = ?",
        (learning_id,),
    ).fetchone()
    if row is None or row["status"] in RETIRED:
        return
    promotion = config["promotion"]
    evidence = row["helped"]
    needed = (promotion["min_evidence_verified"] if row["verification"]
              else promotion["min_evidence"])
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

    id: str
    kind: str
    scope: str
    claim: str
    action: str
    status: str
    confidence: float
    effective: float
    matched: tuple[str, ...]
    links: tuple[str, ...]
    verification: str | None
    last_seen: str
    stale: bool

    def render(self) -> str:
        flag = " STALE" if self.stale else ""
        verify = f"\n      verify: {self.verification}" if self.verification else ""
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
    a function of the log alone and the generated views stay byte-stable.
    """
    half_life = float(config["decay"].get(kind, 365))
    try:
        seen = dt.datetime.fromisoformat(last_seen).date()
    except ValueError:
        return stored
    days = max((today - seen).days, 0)
    return round(stored * (0.5 ** (days / half_life)), 4)


def retrieve(store: Store, connection: sqlite3.Connection, *, file: str | None = None,
             error: str | None = None, task: str | None = None,
             rules: Sequence[str] = (), today: dt.date | None = None) -> list[Candidate]:
    """Learnings whose triggers match the situation, best first."""
    config = store.config()
    settings = config["retrieval"]
    day = today or dt.date.today()
    matches: dict[str, set[str]] = {}

    for row in connection.execute("SELECT learning_id, type, pattern FROM trigger"):
        why = _trigger_matches(row["type"], row["pattern"], file, error, task, rules)
        if why is not None:
            matches.setdefault(row["learning_id"], set()).add(why)

    candidates: list[Candidate] = []
    for learning_id, reasons in matches.items():
        row = connection.execute(
            "SELECT * FROM learning WHERE id = ?", (learning_id,)
        ).fetchone()
        if row is None:
            continue
        if row["status"] in RETIRED and not settings["include_retired"]:
            continue
        effective = effective_confidence(
            row["confidence"], row["last_seen_ts"], row["kind"], config, day
        )
        if effective < settings["min_confidence"]:
            continue
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
    return _fit_budget(candidates, settings)


def _fit_budget(candidates: Sequence[Candidate], settings: dict[str, Any]) -> list[Candidate]:
    kept: list[Candidate] = []
    spent = 0
    for candidate in candidates[: settings["max_learnings"]]:
        cost = count_tokens(candidate.render())
        if kept and spent + cost > settings["budget_tokens"]:
            break
        spent += cost
        kept.append(candidate)
    return kept


def _trigger_matches(trigger_type: str, pattern: str, file: str | None, error: str | None,
                     task: str | None, rules: Sequence[str]) -> str | None:
    """Whether one trigger fires, and a short reason if it does."""
    if trigger_type == "glob" and file and fnmatch.fnmatch(Path(file).as_posix(), pattern):
        return f"path ~ {pattern}"
    if trigger_type == "error" and error and _signature_in(pattern, error):
        return f"error ~ {pattern}"
    if trigger_type == "rule":
        haystack = " ".join([*rules, error or "", task or ""])
        if pattern in haystack:
            return f"rule {pattern}"
    if trigger_type == "command" and task and pattern.lower() in task.lower():
        return f"command ~ {pattern}"
    if trigger_type == "term":
        for text in (task, error):
            if text and pattern.lower() in text.lower():
                return f"term {pattern}"
    return None


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text.lower().replace("-", " ").replace("_", " ")))


def _signature_in(pattern: str, text: str) -> bool:
    """Separator style must not decide whether an error signature matches."""
    if pattern.lower() in text.lower():
        return True
    signature = _words(pattern)
    return len(signature) > 1 and signature <= _words(text)


# ------------------------------------------------------------------- writing


def next_learning_id(connection: sqlite3.Connection) -> str:
    row = connection.execute("SELECT MAX(id) AS top FROM learning").fetchone()
    top = int(row["top"].split("-")[1]) if row and row["top"] else 0
    return f"L-{top + 1:04d}"


def parse_trigger(raw: str) -> dict[str, str]:
    """`glob:src/**/*.py` or `error:adapters are independent`."""
    trigger_type, separator, pattern = raw.partition(":")
    if not separator or trigger_type not in TRIGGER_TYPES:
        message = (
            f"trigger must be one of {', '.join(TRIGGER_TYPES)} followed by ':' "
            f"and a pattern; got {raw!r}"
        )
        raise LearnError(message)
    return {"type": trigger_type, "pattern": pattern.strip()}


def session_id(explicit: str | None) -> str:
    if explicit:
        return explicit
    stamp = dt.datetime.now(tz=dt.UTC).strftime("%Y%m%d")
    return f"S-{stamp}-{uuid.uuid4().hex[:6]}"


# ------------------------------------------------------------ generated views


GENERATED = "<!-- GENERATED by tools/learn.py sync -- do not edit; append an event instead. -->"


def render_index(connection: sqlite3.Connection, config: dict[str, Any]) -> str:
    """The readable state. Deterministic: ordering and content come from the log."""
    rows = list(connection.execute("SELECT * FROM learning ORDER BY id"))
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
    if not rows:
        lines += [
            "*Empty.* Nothing has been recorded yet. The first task to use the database "
            "is also its first calibration datum: see `calibration.md`.",
            "",
        ]
        return "\n".join(lines)

    by_status: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        by_status.setdefault(row["status"], []).append(row)

    lines += ["| Status | Count |", "|---|---|"]
    lines += [f"| {status} | {len(items)} |" for status, items in sorted(by_status.items())]
    lines.append("")

    for status in ("active", "candidate", "promoted", "superseded", "refuted"):
        items = by_status.get(status)
        if not items:
            continue
        lines += [f"## {status}", ""]
        for row in items:
            triggers = [
                f"`{t['type']}:{t['pattern']}`" for t in connection.execute(
                    "SELECT type, pattern FROM trigger WHERE learning_id = ? "
                    "ORDER BY type, pattern", (row["id"],)
                )
            ]
            links = [
                l["node"] for l in connection.execute(  # noqa: E741 - row alias
                    "SELECT node FROM link WHERE learning_id = ? ORDER BY node", (row["id"],)
                )
            ]
            lines += [
                f"### {row['id']} · {row['claim']}",
                "",
                f"- **Do** {row['action']}",
                f"- **Kind** {row['kind']} · **scope** {row['scope']} · "
                f"**evidence** {row['evidence']} "
                f"(+{row['helped']}/-{row['noise']} over {row['sessions']} session(s))",
                f"- **Confidence** {row['confidence']:.2f}, last seen {row['last_seen_ts'][:10]}",
                f"- **Triggers** {', '.join(triggers) or 'none'}",
            ]
            if links:
                lines.append(f"- **About** {', '.join(links)}")
            if row["verification"]:
                lines.append(f"- **Verify** `{row['verification']}`")
            if row["promoted_to"]:
                lines.append(f"- **Promoted to** `{row['promoted_to']}` — retired from retrieval")
            if row["superseded_by"]:
                lines.append(f"- **Superseded by** {row['superseded_by']}")
            if row["note"]:
                lines.append(f"- **Note** {row['note']}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_calibration(connection: sqlite3.Connection, config: dict[str, Any],
                       as_of: dt.date) -> str:
    """The metrics a calibration pass reads.

    The date appears because the subject is time — staleness cannot be reported
    without one. It is a parameter, not a wall-clock stamp, so regenerating with
    the same `--as-of` reproduces the file byte for byte.
    """
    learnings = list(connection.execute("SELECT * FROM learning"))
    usages = list(connection.execute("SELECT * FROM usage"))
    sessions = list(connection.execute("SELECT * FROM session"))
    helped = sum(1 for u in usages if u["outcome"] == "helped")
    noise = sum(1 for u in usages if u["outcome"] == "noise")
    contradicted = sum(1 for u in usages if u["outcome"] == "contradicted")
    offered = len(usages)
    precision = f"{helped / offered:.0%}" if offered else "n/a"

    kinds: dict[str, int] = {}
    for row in learnings:
        kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1

    stale = sum(
        1 for row in learnings
        if effective_confidence(row["confidence"], row["last_seen_ts"], row["kind"],
                                config, as_of) < row["confidence"] / 2
    )

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

    if kinds:
        lines += ["## Kinds", "", "| Kind | Count |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in sorted(kinds.items())]
        lines.append("")

    if not learnings:
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

    lines += [
        "## Parameters in force",
        "",
        "| Setting | Value |",
        "|---|---|",
    ]
    for section in ("retrieval", "promotion"):
        for key, value in sorted(config[section].items()):
            lines.append(f"| `{section}.{key}` | {value} |")
    lines += [
        "",
        "Change one with `python tools/learn.py calibrate --set retrieval.max_learnings=8 "
        "--why \"...\"`, which edits `config.toml` and appends a `calibrate` event. A "
        "parameter changed without that event is indistinguishable from drift.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def write_views(store: Store, connection: sqlite3.Connection, as_of: dt.date) -> None:
    config = store.config()
    store.index.write_text(render_index(connection, config), encoding="utf-8")
    store.calibration.write_text(
        render_calibration(connection, config, as_of), encoding="utf-8"
    )


# ---------------------------------------------------------------- graph layer


def graph_overlay(store: Store) -> Iterator[tuple[str, str, str, str, float]]:
    """Learnings as graph nodes and edges: (id, label, relation, node, weight).

    Consumed by `nav.py` so a reading plan can carry what was learned about the
    rules it selected. Overlaid at query time; the static graph stays untouched.
    """
    if not store.db.exists():
        return
    connection = sqlite3.connect(store.db)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT l.id, l.claim, l.confidence, k.relation, k.node "
            "FROM learning l JOIN link k ON k.learning_id = l.id "
            "WHERE l.status IN ('candidate','active') ORDER BY l.id, k.node"
        ).fetchall()
    except sqlite3.DatabaseError:
        return
    finally:
        connection.close()
    for row in rows:
        yield row["id"], row["claim"], row["relation"], row["node"], row["confidence"]


# ------------------------------------------------------------------ commands


def cmd_record(store: Store, args: argparse.Namespace) -> int:
    config = store.config()
    if args.kind not in config["write"]["kinds_enabled"]:
        message = f"kind {args.kind!r} is not enabled; see learning/config.toml"
        raise LearnError(message)
    if config["write"]["require_action"] and not args.action:
        message = "a learning must say what to do differently, not only what is true"
        raise LearnError(message)
    triggers = [parse_trigger(t) for t in args.trigger or []]
    if config["write"]["require_trigger"] and not triggers:
        message = (
            "a learning with no trigger can never be retrieved. Add at least one "
            "--trigger glob:... / error:... / rule:... / command:... / term:..."
        )
        raise LearnError(message)

    connection = sync(store)
    learning_id = next_learning_id(connection)
    connection.close()

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
    if args.verify:
        payload["verification"] = args.verify
    append_event(store, "learn", session_id(args.session), payload)
    connection = sync(store)
    write_views(store, connection, dt.date.today())
    connection.close()
    print(f"recorded {learning_id}")
    return 0


def cmd_retrieve(store: Store, args: argparse.Namespace) -> int:
    connection = sync(store)
    found = retrieve(
        store, connection, file=args.file, error=args.error, task=args.task,
        rules=args.rule or [],
    )
    connection.close()
    if args.json:
        print(json.dumps([c.__dict__ for c in found], indent=1, ensure_ascii=False))
        return 0
    if not found:
        print("LEARNED  nothing recorded matches this situation")
        return 0
    print(f"LEARNED ({len(found)})")
    for candidate in found:
        print(candidate.render())
    print(f"\n  cost {sum(count_tokens(c.render()) for c in found)} tok")
    print("  report what came of these:  learn.py used <id> --outcome helped|noise")
    return 0


def cmd_outcome(store: Store, args: argparse.Namespace) -> int:
    kind = {"used": "use", "refute": "refute", "supersede": "supersede",
            "promote": "promote"}[args.command]
    payload: dict[str, Any] = {"ref": args.id}
    if args.command == "used":
        payload["outcome"] = args.outcome
        payload["note"] = args.note
    elif args.command == "refute":
        payload["why"] = args.why
    elif args.command == "supersede":
        payload["by"] = args.by
    else:
        payload["mechanism"] = args.mechanism
        payload["note"] = args.note
    append_event(store, kind, session_id(args.session), payload)
    connection = sync(store)
    write_views(store, connection, dt.date.today())
    connection.close()
    print(f"{kind} recorded for {args.id}")
    return 0


def cmd_session(store: Store, args: argparse.Namespace) -> int:
    identifier = session_id(args.session)
    append_event(store, "session", identifier,
                 {"task": args.task, "discipline_version": args.discipline_version})
    connection = sync(store)
    write_views(store, connection, dt.date.today())
    connection.close()
    print(identifier)
    return 0


def cmd_sync(store: Store, args: argparse.Namespace) -> int:
    connection = sync(store)
    write_views(store, connection, args.as_of or dt.date.today())
    counts = connection.execute(
        "SELECT (SELECT COUNT(*) FROM event) e, (SELECT COUNT(*) FROM learning) l, "
        "(SELECT COUNT(*) FROM usage) u"
    ).fetchone()
    connection.close()
    print(f"synced {counts['e']} event(s) -> {counts['l']} learning(s), {counts['u']} outcome(s)")
    return 0


def cmd_status(store: Store, args: argparse.Namespace) -> int:
    connection = sync(store)
    rows = list(connection.execute(
        "SELECT status, COUNT(*) n FROM learning GROUP BY status ORDER BY status"
    ))
    events = connection.execute("SELECT COUNT(*) n FROM event").fetchone()["n"]
    connection.close()
    print(f"{events} event(s) in {store.ledger.name}")
    for row in rows:
        print(f"  {row['status']:<12} {row['n']}")
    if not rows:
        print("  (no learnings yet)")
    return 0


def cmd_calibrate(store: Store, args: argparse.Namespace) -> int:
    as_of = args.as_of or dt.date.today()
    if args.set:
        if not args.why:
            message = "a parameter change needs --why; an untraced change is drift"
            raise LearnError(message)
        changed = _apply_settings(store, args.set)
        append_event(store, "calibrate", session_id(args.session),
                     {"changed": changed, "why": args.why})
    connection = sync(store)
    write_views(store, connection, as_of)
    report = store.calibration.read_text(encoding="utf-8")
    connection.close()
    print(report)
    return 0


def _apply_settings(store: Store, assignments: Sequence[str]) -> dict[str, list[str]]:
    """Edit config.toml in place, one `section.key=value` at a time."""
    text = store.config_path.read_text(encoding="utf-8")
    changed: dict[str, list[str]] = {}
    for assignment in assignments:
        dotted, separator, value = assignment.partition("=")
        if not separator:
            message = f"expected section.key=value, got {assignment!r}"
            raise LearnError(message)
        section, _, key = dotted.strip().rpartition(".")
        pattern = re.compile(rf"^({re.escape(key)}\s*=\s*)(.+)$", re.MULTILINE)
        found = pattern.search(text)
        if found is None:
            message = f"no setting named {dotted!r} in {store.config_path.name}"
            raise LearnError(message)
        changed[dotted.strip()] = [found.group(2).strip(), value.strip()]
        text = pattern.sub(lambda m: m.group(1) + value.strip(), text, count=1)
    store.config_path.write_text(text, encoding="utf-8")
    return changed


# ---------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record and retrieve session learnings.")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--session", help="session id; one is generated if omitted")
    sub = parser.add_subparsers(dest="command", required=True)

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

    ret = sub.add_parser("retrieve", help="what is known about this situation")
    ret.add_argument("--file")
    ret.add_argument("--error")
    ret.add_argument("--task")
    ret.add_argument("--rule", action="append")
    ret.add_argument("--json", action="store_true")

    used = sub.add_parser("used", help="report what came of a retrieved learning")
    used.add_argument("id")
    used.add_argument("--outcome", required=True,
                      choices=("helped", "noise", "contradicted"))
    used.add_argument("--note")

    ref = sub.add_parser("refute", help="record that a learning is wrong")
    ref.add_argument("id")
    ref.add_argument("--why", required=True)

    sup = sub.add_parser("supersede", help="replace one learning with another")
    sup.add_argument("id")
    sup.add_argument("--by", required=True)

    pro = sub.add_parser("promote", help="retire a learning into a mechanism")
    pro.add_argument("id")
    pro.add_argument("--mechanism", required=True)
    pro.add_argument("--note")

    ses = sub.add_parser("session", help="open a session")
    ses.add_argument("--task")
    ses.add_argument("--discipline-version")

    syn = sub.add_parser("sync", help="rebuild the index and the views from the ledger")
    syn.add_argument("--as-of", type=dt.date.fromisoformat)

    sub.add_parser("status", help="a one-screen summary")

    cal = sub.add_parser("calibrate", help="the metrics, and the dials")
    cal.add_argument("--as-of", type=dt.date.fromisoformat)
    cal.add_argument("--set", action="append", metavar="SECTION.KEY=VALUE")
    cal.add_argument("--why")
    return parser


COMMANDS = {
    "record": cmd_record, "retrieve": cmd_retrieve, "used": cmd_outcome,
    "refute": cmd_outcome, "supersede": cmd_outcome, "promote": cmd_outcome,
    "session": cmd_session, "sync": cmd_sync, "status": cmd_status,
    "calibrate": cmd_calibrate,
}


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    store = Store(args.root.resolve())
    try:
        return COMMANDS[args.command](store, args)
    except LearnError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
