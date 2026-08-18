"""Tests for the learning database.

Three concerns. **Durability**: the ledger is the record, and the database must
be reconstructible from it exactly. **Discipline**: the guards that stop the
database filling with junk or leaking credentials must be shown to fire.
**Determinism**: retrieval and the generated views must be reproducible, because
an unreproducible retrieval cannot be calibrated.

    pytest tools/test_learn.py
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import sqlite3
from collections.abc import Sequence
from pathlib import Path

import pytest

import learn
from discipline_core import REPO_ROOT


@pytest.fixture
def store(tmp_path: Path) -> learn.Store:
    """A private learning database, with this repository's schema and config.

    @param tmp_path the root the store is built under; `learning/` is created inside it
    @return a store rooted there, so no test touches the repository's own ledger
    """
    target = tmp_path / "learning"
    target.mkdir(parents=True)
    for name in ("schema.sql", "config.toml"):
        shutil.copy(REPO_ROOT / "learning" / name, target / name)
    return learn.Store(tmp_path)


def record(store: learn.Store, **overrides: object) -> str:
    """Append one learning, returning its id.

    The default payload is a minimal valid entry, so a test names only the field
    whose effect it is pinning.

    @param store the database to append to
    @param overrides payload fields to replace; `session` and `ts` additionally
        select the event's session and timestamp, which default to one fixed
        session on one fixed date so the fold stays reproducible
    @return the id the entry was allocated
    """
    connection = learn.sync(store)
    learning_id = learn.next_learning_id(connection)
    connection.close()
    payload = {
        "id": learning_id,
        "kind": "diagnostic",
        "scope": "project",
        "claim": "a claim",
        "action": "do the thing",
        "evidence": "observed",
        "triggers": [{"type": "glob", "pattern": "src/**/*.py"}],
        "links": [],
        **overrides,
    }
    learn.append_event(store, "learn", overrides.pop("session", "S-1"), payload,  # type: ignore[arg-type]
                       ts=str(overrides.get("ts", "2026-08-01T00:00:00+00:00")))
    return learning_id


def states(store: learn.Store) -> dict[str, str]:
    """The lifecycle status the fold assigned to each entry.

    Syncs first, so a caller sees the effect of events appended since the last
    fold without having to remember to rebuild.

    @param store the database to read
    @return every learning id mapped to its status
    """
    connection = learn.sync(store)
    rows = {r["id"]: r["status"] for r in connection.execute("SELECT id, status FROM learning")}
    connection.close()
    return rows


# ------------------------------------------------------------------ durability


def test_the_database_is_reconstructible_from_the_ledger(store: learn.Store) -> None:
    """The ledger is the record; the database is a query index over it."""
    first = record(store)
    learn.append_event(store, "use", "S-2", {"ref": first, "outcome": "helped"})
    connection = learn.sync(store)
    before = [tuple(r) for r in connection.execute("SELECT * FROM learning ORDER BY id")]
    connection.close()

    store.db.unlink()
    connection = learn.sync(store)
    after = [tuple(r) for r in connection.execute("SELECT * FROM learning ORDER BY id")]
    connection.close()
    assert after == before


def test_sync_is_idempotent(store: learn.Store) -> None:
    """Folding twice yields the same rows as folding once."""
    record(store)
    connection = learn.sync(store)
    first = [tuple(r) for r in connection.execute("SELECT * FROM learning")]
    connection.close()
    connection = learn.sync(store)
    second = [tuple(r) for r in connection.execute("SELECT * FROM learning")]
    connection.close()
    assert first == second


def test_the_ledger_is_append_only_and_line_oriented(store: learn.Store) -> None:
    """One self-contained line per event, numbered from one.

    That shape is what lets a merge conflict be resolved by keeping both sides.
    """
    record(store)
    record(store)
    lines = store.ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["seq"] for line in lines] == [1, 2]


def test_a_corrupt_ledger_line_names_itself(store: learn.Store) -> None:
    """The refusal carries file and line number, not a bare parse error.

    A hand-edited ledger is the likely cause, and the reader needs to be sent to
    the offending line rather than to the whole file.
    """
    record(store)
    with store.ledger.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    with pytest.raises(learn.LearnError, match=r"ledger\.jsonl:2"):
        learn.read_ledger(store)


# ------------------------------------------------------------------ discipline


def test_a_credential_is_refused(store: learn.Store) -> None:
    """DIAG-014 applied to the ledger: it is designed to be read widely."""
    with pytest.raises(learn.LearnError, match="credential"):
        learn.append_event(
            store, "learn", "S-1",
            {"id": "L-0001", "claim": "token=ghp_abcdefghijklmnopqrstuvwxyz0123"},
        )
    assert not store.ledger.exists()


@pytest.mark.parametrize(
    "secret",
    [
        "AKIAIOSFODNN7EXAMPLE",
        "-----BEGIN RSA PRIVATE KEY-----",
        "password: hunter2000",
        "/home/someone/private/",
    ],
)
def test_each_secret_shape_is_refused(store: learn.Store, secret: str) -> None:
    """Four differently-shaped secrets are refused, not only the token form above.

    An AWS key id, a private key header, a key/value credential and a home
    directory path each trip a separate pattern, so the guard is shown to be a
    family of shapes rather than one regex.
    """
    with pytest.raises(learn.LearnError):
        learn.append_event(store, "learn", "S-1", {"claim": secret})


def test_a_learning_without_a_trigger_can_never_be_found(store: learn.Store) -> None:
    """Guarded at the CLI, because such an entry is invisible by construction."""
    config = store.config()
    assert config["write"]["require_trigger"] is True


def test_an_unknown_trigger_type_is_rejected() -> None:
    """A misspelled type is refused with the valid ones named in the message.

    The accepting half is pinned too: a valid argument splits at the first colon
    into the two-field form the payload stores.
    """
    with pytest.raises(learn.LearnError, match="trigger must be one of"):
        learn.parse_trigger("nonsense:whatever")
    assert learn.parse_trigger("glob:src/**") == {"type": "glob", "pattern": "src/**"}


# ------------------------------------------------------------------- retrieval


def test_a_glob_trigger_matches_a_path(store: learn.Store) -> None:
    """The candidate carries the pattern that surfaced it.

    Retrieval that cannot say why it offered something cannot be reviewed.
    """
    record(store, triggers=[{"type": "glob", "pattern": "src/**/adapters/*.py"}])
    connection = learn.sync(store)
    found = learn.retrieve(store, connection, file="src/pkg/adapters/fs.py",
                           today=dt.date(2026, 8, 1))
    connection.close()
    assert [c.id for c in found] == ["L-0001"]
    assert found[0].matched == ("path ~ src/**/adapters/*.py",)


def test_an_error_signature_ignores_separator_style(store: learn.Store) -> None:
    """Hyphens, underscores and spaces are one signature.

    A failure line is pasted in whatever form the emitting tool chose, and a
    learning recorded against one spelling must still be found from another.
    """
    record(store, triggers=[{"type": "error", "pattern": "adapters are independent"}])
    connection = learn.sync(store)
    for text in ("contract adapters-are-independent FAILED",
                 "adapters_are_independent broke"):
        found = learn.retrieve(store, connection, error=text, today=dt.date(2026, 8, 1))
        assert [c.id for c in found] == ["L-0001"], text
    connection.close()


def test_a_rule_trigger_matches_a_selected_rule(store: learn.Store) -> None:
    """A rule id in the caller's reading plan is enough; no error text is needed."""
    record(store, triggers=[{"type": "rule", "pattern": "ARCH-003"}])
    connection = learn.sync(store)
    found = learn.retrieve(store, connection, rules=["ARCH-003"], today=dt.date(2026, 8, 1))
    connection.close()
    assert [c.id for c in found] == ["L-0001"]


def test_nothing_matches_an_unrelated_situation(store: learn.Store) -> None:
    """Retrieval stays empty rather than offering the nearest entry it has.

    A near miss presented as advice is worse than silence: it spends context and
    trains the reader to stop believing the output.
    """
    record(store, triggers=[{"type": "glob", "pattern": "docs/**"}])
    connection = learn.sync(store)
    found = learn.retrieve(store, connection, file="src/pkg/domain/x.py",
                           today=dt.date(2026, 8, 1))
    connection.close()
    assert found == []


def test_retrieval_is_reproducible(store: learn.Store) -> None:
    """The same query returns the same candidates in the same order.

    Ordering is part of the result: entries tied on confidence are broken by id,
    so nothing depends on how the rows happened to come back.
    """
    for _ in range(3):
        record(store)
    connection = learn.sync(store)
    first = learn.retrieve(store, connection, file="src/a.py", today=dt.date(2026, 8, 1))
    second = learn.retrieve(store, connection, file="src/a.py", today=dt.date(2026, 8, 1))
    connection.close()
    assert first == second


def test_retrieval_respects_the_budget(store: learn.Store) -> None:
    """Matching entries are dropped once the token budget is spent.

    The ceiling is approximate rather than hard -- the first candidate is always
    kept, so one oversized entry can exceed it alone.
    """
    for _ in range(6):
        record(store, claim="a long claim " * 40, action="a long action " * 40)
    connection = learn.sync(store)
    found = learn.retrieve(store, connection, file="src/a.py", today=dt.date(2026, 8, 1))
    connection.close()
    budget = store.config()["retrieval"]["budget_tokens"]
    assert len(found) < 6, "nothing was dropped despite each entry being large"
    assert sum(len(c.render()) for c in found) // 4 <= budget * 1.5


def test_a_retired_learning_is_not_offered(store: learn.Store) -> None:
    """Refuted entries stay in the log for audit, not for advice."""
    first = record(store)
    learn.append_event(store, "refute", "S-2", {"ref": first, "why": "wrong here"})
    connection = learn.sync(store)
    found = learn.retrieve(store, connection, file="src/a.py", today=dt.date(2026, 8, 1))
    connection.close()
    assert found == []
    assert states(store)[first] == "refuted"


def test_confidence_decays_with_time(store: learn.Store) -> None:
    """Confidence halves once per half-life since the entry was last seen.

    Pinned at zero days and at exactly one half-life -- 90 days for a diagnostic,
    the fastest-rotting kind -- which is the pair that fixes both the starting
    value and the rate.
    """
    config = store.config()
    fresh = learn.effective_confidence(0.5, "2026-08-01T00:00:00+00:00", "diagnostic",
                                       config, dt.date(2026, 8, 1))
    one_half_life = learn.effective_confidence(0.5, "2026-08-01T00:00:00+00:00",
                                               "diagnostic", config, dt.date(2026, 10, 30))
    assert fresh == 0.5
    assert one_half_life == pytest.approx(0.25, abs=0.01)


def test_a_decayed_learning_falls_below_the_floor(store: learn.Store) -> None:
    """An entry untouched for years stops being offered.

    Nothing retires it: decay alone carries it under the retrieval threshold, so
    a database nobody prunes still shrinks what it proposes.
    """
    record(store)
    connection = learn.sync(store)
    found = learn.retrieve(store, connection, file="src/a.py", today=dt.date(2030, 1, 1))
    connection.close()
    assert found == [], "an entry untouched for years should stop being offered"


# ------------------------------------------------------------------- lifecycle


def test_a_candidate_becomes_active_on_evidence(store: learn.Store) -> None:
    """A new entry starts as a candidate and is promoted only by reported use.

    Two helped outcomes from two sessions clear the unverified threshold.
    """
    first = record(store)
    assert states(store)[first] == "candidate"
    learn.append_event(store, "use", "S-2", {"ref": first, "outcome": "helped"})
    learn.append_event(store, "use", "S-3", {"ref": first, "outcome": "helped"})
    assert states(store)[first] == "active"


def test_one_session_repeated_is_not_two_observations(store: learn.Store) -> None:
    """min_sessions exists because three outcomes in one session is one datum."""
    first = record(store)
    for _ in range(3):
        learn.append_event(store, "use", "S-2", {"ref": first, "outcome": "helped"})
    assert states(store)[first] == "candidate"


def test_a_verified_learning_needs_less_evidence(store: learn.Store) -> None:
    """The check is the evidence -- the axiom, applied to learnings."""
    first = record(store, verification="pytest -k contract")
    learn.append_event(store, "use", "S-2", {"ref": first, "outcome": "helped"})
    assert states(store)[first] == "active"


def test_noise_lowers_confidence_more_than_help_raises_it(store: learn.Store) -> None:
    """One help and one complaint leave the entry below where it started.

    The asymmetry is deliberate: an entry that wastes a reader's attention should
    fall out faster than it climbed in.
    """
    first = record(store)
    learn.append_event(store, "use", "S-2", {"ref": first, "outcome": "helped"})
    learn.append_event(store, "use", "S-3", {"ref": first, "outcome": "noise"})
    connection = learn.sync(store)
    row = connection.execute("SELECT confidence FROM learning WHERE id = ?", (first,)).fetchone()
    connection.close()
    assert row["confidence"] < 0.5


def test_promotion_retires_a_learning(store: learn.Store) -> None:
    """A learning that became a mechanism stops competing for attention."""
    first = record(store)
    learn.append_event(store, "promote", "S-2",
                       {"ref": first, "mechanism": "check:whatever"})
    assert states(store)[first] == "promoted"
    connection = learn.sync(store)
    found = learn.retrieve(store, connection, file="src/a.py", today=dt.date(2026, 8, 1))
    connection.close()
    assert found == []


def test_supersession_points_at_the_replacement(store: learn.Store) -> None:
    """The retired entry records which one replaced it, so an old citation leads on."""
    first = record(store)
    second = record(store)
    learn.append_event(store, "supersede", "S-2", {"ref": first, "by": second})
    connection = learn.sync(store)
    row = connection.execute(
        "SELECT status, superseded_by FROM learning WHERE id = ?", (first,)
    ).fetchone()
    connection.close()
    assert (row["status"], row["superseded_by"]) == ("superseded", second)


def test_an_outcome_for_an_unknown_learning_is_ignored(store: learn.Store) -> None:
    """An event about an id that was never recorded folds to nothing.

    The event stays in the ledger; what it must not do is conjure a row, because
    the fold has to survive a ledger merged from two branches.
    """
    learn.append_event(store, "use", "S-1", {"ref": "L-9999", "outcome": "helped"})
    assert states(store) == {}


# ------------------------------------------------------------ generated views


def test_the_views_are_deterministic(store: learn.Store) -> None:
    """Rendering twice from one state produces identical text.

    The views are committed, so any wall-clock or set-ordering leak would show up
    as a diff nobody caused.
    """
    record(store)
    connection = learn.sync(store)
    config = store.config()
    as_of = dt.date(2026, 8, 18)
    assert learn.render_index(connection, config) == learn.render_index(connection, config)
    assert (learn.render_calibration(connection, config, as_of)
            == learn.render_calibration(connection, config, as_of))
    connection.close()


def test_an_empty_database_explains_the_first_run(store: learn.Store) -> None:
    """With nothing recorded, the report gives the bootstrap protocol.

    Precision cannot be measured before anything was retrieved, so the empty
    report has to say what to measure instead rather than print a zero.
    """
    connection = learn.sync(store)
    report = learn.render_calibration(connection, store.config(), dt.date(2026, 8, 18))
    connection.close()
    assert "First-run protocol" in report
    assert "would have helped at the start" in report


def test_calibration_reports_precision(store: learn.Store) -> None:
    """Precision is helped outcomes over all reported outcomes.

    One of each gives 50%, which pins both the ratio and the rendering.
    """
    first = record(store)
    learn.append_event(store, "use", "S-2", {"ref": first, "outcome": "helped"})
    learn.append_event(store, "use", "S-3", {"ref": first, "outcome": "noise"})
    connection = learn.sync(store)
    report = learn.render_calibration(connection, store.config(), dt.date(2026, 8, 18))
    connection.close()
    assert "**50%**" in report


def test_a_parameter_change_needs_a_reason(store: learn.Store) -> None:
    """A setting edit reports the value it displaced beside the new one.

    That pair is what the audit event carries; without the old value a recorded
    reason cannot be checked against what actually changed.
    """
    changed = learn._apply_settings(store, ["retrieval.max_learnings=3"])
    assert changed["retrieval.max_learnings"] == ["8", "3"]
    assert store.config()["retrieval"]["max_learnings"] == 3


def test_an_unknown_parameter_is_refused(store: learn.Store) -> None:
    """A name matching no line in config.toml raises rather than moving nothing."""
    with pytest.raises(learn.LearnError, match="no setting named"):
        learn._apply_settings(store, ["retrieval.nonsense=1"])


# ---------------------------------------------------------------- graph layer


def test_learnings_surface_as_graph_edges(store: learn.Store) -> None:
    """A link becomes an edge from the entry to the rule it is about.

    That is how a reading plan picks up what was learned about the rules it
    already selected, without the static graph being rewritten.
    """
    record(store, links=[{"relation": "learned_about", "node": "ARCH-003"}])
    learn.sync(store).close()
    overlay = list(learn.graph_overlay(store))
    assert [(o[0], o[2], o[3]) for o in overlay] == [("L-0001", "learned_about", "ARCH-003")]


def test_a_retired_learning_leaves_the_overlay(store: learn.Store) -> None:
    """Refuting an entry withdraws its edges, so navigation stops citing it."""
    first = record(store, links=[{"relation": "learned_about", "node": "ARCH-003"}])
    learn.append_event(store, "refute", "S-2", {"ref": first, "why": "no"})
    learn.sync(store).close()
    assert list(learn.graph_overlay(store)) == []


def test_the_overlay_is_silent_without_a_database(tmp_path: Path) -> None:
    """No database yields no edges rather than an error.

    The overlay is optional to its callers: navigation must work in a checkout
    where nobody has run sync.
    """
    assert list(learn.graph_overlay(learn.Store(tmp_path))) == []


# ------------------------------------------------------------------- schema


def test_the_schema_records_its_version(store: learn.Store) -> None:
    """A freshly built database stamps the version it was built under.

    Without the stamp there is no way to tell a current database from one left
    behind by an older checkout.
    """
    connection = learn.sync(store)
    row = connection.execute("SELECT version, applied_ledger_seq FROM schema_version").fetchone()
    connection.close()
    assert row["version"] == learn.SCHEMA_VERSION


def test_a_prior_version_database_is_rebuilt_not_patched(store: learn.Store) -> None:
    """A database at an older version is discarded and rebuilt, not migrated.

    This is the whole migration story. The database is derived, so it holds
    nothing worth preserving; the ledger is what a schema change must stay
    compatible with (API-012).
    """
    record(store)
    learn.sync(store).close()
    connection = sqlite3.connect(store.db)
    connection.execute("UPDATE schema_version SET version = 0")
    connection.execute("DELETE FROM learning")
    connection.commit()
    connection.close()

    connection = learn.sync(store)
    row = connection.execute("SELECT COUNT(*) n FROM learning").fetchone()
    version = connection.execute("SELECT version FROM schema_version").fetchone()[0]
    connection.close()
    assert row["n"] == 1
    assert version == learn.SCHEMA_VERSION


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
