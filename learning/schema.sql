-- Learning database schema.
--
-- `event` is the only authoritative table. Every other table is a projection,
-- rebuilt by folding the event log, so a correction is an appended event rather
-- than an edit and nothing that was once known is ever silently lost.
--
-- The durable form is `learning/ledger.jsonl`, which is what git carries. This
-- database is a query index rebuilt from it: fast joins over triggers and
-- confidence, and nothing a reviewer has to take on trust. `learn.py sync`
-- rebuilds it; drift between the two is a validation error (V096).
--
-- Migrations are numbered below and applied in order. A schema change ships
-- with its migration and a test against a prior-version fixture (API-012).

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- migration 1

CREATE TABLE IF NOT EXISTS schema_version (
    version            INTEGER NOT NULL,
    applied_ledger_seq INTEGER NOT NULL DEFAULT 0
);

-- The log. Append-only by contract: nothing updates or deletes a row here.
CREATE TABLE IF NOT EXISTS event (
    seq     INTEGER PRIMARY KEY,   -- position in the ledger, 1-based
    id      TEXT    NOT NULL UNIQUE,
    session TEXT    NOT NULL,
    ts      TEXT    NOT NULL,      -- ISO-8601, from the data not the clock
    kind    TEXT    NOT NULL
        CHECK (kind IN ('learn','use','refute','supersede','promote','session','calibrate')),
    actor   TEXT    NOT NULL,
    payload TEXT    NOT NULL       -- JSON
);

CREATE INDEX IF NOT EXISTS event_by_kind    ON event(kind);
CREATE INDEX IF NOT EXISTS event_by_session ON event(session);

-- Folded state. Dropped and rebuilt wholesale by `sync`.
CREATE TABLE IF NOT EXISTS learning (
    id              TEXT    PRIMARY KEY,
    kind            TEXT    NOT NULL
        CHECK (kind IN ('diagnostic','constraint','procedure','rule-application','defect')),
    scope           TEXT    NOT NULL CHECK (scope IN ('project','discipline')),
    claim           TEXT    NOT NULL,
    action          TEXT    NOT NULL,
    evidence        TEXT    NOT NULL CHECK (evidence IN ('observed','inferred','told')),
    verification    TEXT,
    status          TEXT    NOT NULL
        CHECK (status IN ('candidate','active','promoted','superseded','refuted')),
    confidence      REAL    NOT NULL,
    helped          INTEGER NOT NULL DEFAULT 0,
    noise           INTEGER NOT NULL DEFAULT 0,
    sessions        INTEGER NOT NULL DEFAULT 0,
    created_seq     INTEGER NOT NULL,
    created_session TEXT    NOT NULL,
    created_ts      TEXT    NOT NULL,
    last_seen_ts    TEXT    NOT NULL,
    superseded_by   TEXT,
    promoted_to     TEXT,
    note            TEXT
);

CREATE INDEX IF NOT EXISTS learning_by_status ON learning(status);
CREATE INDEX IF NOT EXISTS learning_by_scope  ON learning(scope);

-- What makes a learning surface. Deterministic matching only: a pattern either
-- matches or it does not, so a retrieval can be reproduced and reviewed.
CREATE TABLE IF NOT EXISTS trigger (
    learning_id TEXT NOT NULL REFERENCES learning(id) ON DELETE CASCADE,
    type        TEXT NOT NULL CHECK (type IN ('glob','error','rule','command','term')),
    pattern     TEXT NOT NULL,
    PRIMARY KEY (learning_id, type, pattern)
);

CREATE INDEX IF NOT EXISTS trigger_by_type ON trigger(type);

-- The overlay onto the navigation graph: a learning is a node, and these are
-- its typed edges to rules, mechanisms, modules and layers.
CREATE TABLE IF NOT EXISTS link (
    learning_id TEXT NOT NULL REFERENCES learning(id) ON DELETE CASCADE,
    relation    TEXT NOT NULL
        CHECK (relation IN ('learned_about','contradicts','evidences')),
    node        TEXT NOT NULL,
    PRIMARY KEY (learning_id, relation, node)
);

-- Every time a learning was offered and what came of it. This is the raw
-- material of calibration: precision cannot be computed without it.
CREATE TABLE IF NOT EXISTS usage (
    seq         INTEGER PRIMARY KEY,
    learning_id TEXT    NOT NULL REFERENCES learning(id) ON DELETE CASCADE,
    session     TEXT    NOT NULL,
    ts          TEXT    NOT NULL,
    outcome     TEXT    NOT NULL CHECK (outcome IN ('helped','noise','contradicted')),
    note        TEXT
);

CREATE TABLE IF NOT EXISTS session (
    id                 TEXT PRIMARY KEY,
    started_ts         TEXT NOT NULL,
    task               TEXT,
    discipline_version TEXT,
    retrieved          INTEGER NOT NULL DEFAULT 0,
    recorded           INTEGER NOT NULL DEFAULT 0
);
