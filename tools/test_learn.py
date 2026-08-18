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
    """A private learning database, with this repository's schema and config."""
    target = tmp_path / "learning"
    target.mkdir(parents=True)
    for name in ("schema.sql", "config.toml"):
        shutil.copy(REPO_ROOT / "learning" / name, target / name)
    return learn.Store(tmp_path)


def record(store: learn.Store, **overrides: object) -> str:
    """Append one learning, returning its id."""
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
    record(store)
    connection = learn.sync(store)
    first = [tuple(r) for r in connection.execute("SELECT * FROM learning")]
    connection.close()
    connection = learn.sync(store)
    second = [tuple(r) for r in connection.execute("SELECT * FROM learning")]
    connection.close()
    assert first == second


def test_the_ledger_is_append_only_and_line_oriented(store: learn.Store) -> None:
    record(store)
    record(store)
    lines = store.ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["seq"] for line in lines] == [1, 2]


def test_a_corrupt_ledger_line_names_itself(store: learn.Store) -> None:
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
    with pytest.raises(learn.LearnError):
        learn.append_event(store, "learn", "S-1", {"claim": secret})


def test_a_learning_without_a_trigger_can_never_be_found(store: learn.Store) -> None:
    """Guarded at the CLI, because such an entry is invisible by construction."""
    config = store.config()
    assert config["write"]["require_trigger"] is True


def test_an_unknown_trigger_type_is_rejected() -> None:
    with pytest.raises(learn.LearnError, match="trigger must be one of"):
        learn.parse_trigger("nonsense:whatever")
    assert learn.parse_trigger("glob:src/**") == {"type": "glob", "pattern": "src/**"}


# ------------------------------------------------------------------- retrieval


def test_a_glob_trigger_matches_a_path(store: learn.Store) -> None:
    record(store, triggers=[{"type": "glob", "pattern": "src/**/adapters/*.py"}])
    connection = learn.sync(store)
    found = learn.retrieve(store, connection, file="src/pkg/adapters/fs.py",
                           today=dt.date(2026, 8, 1))
    connection.close()
    assert [c.id for c in found] == ["L-0001"]
    assert found[0].matched == ("path ~ src/**/adapters/*.py",)


def test_an_error_signature_ignores_separator_style(store: learn.Store) -> None:
    record(store, triggers=[{"type": "error", "pattern": "adapters are independent"}])
    connection = learn.sync(store)
    for text in ("contract adapters-are-independent FAILED",
                 "adapters_are_independent broke"):
        found = learn.retrieve(store, connection, error=text, today=dt.date(2026, 8, 1))
        assert [c.id for c in found] == ["L-0001"], text
    connection.close()


def test_a_rule_trigger_matches_a_selected_rule(store: learn.Store) -> None:
    record(store, triggers=[{"type": "rule", "pattern": "ARCH-003"}])
    connection = learn.sync(store)
    found = learn.retrieve(store, connection, rules=["ARCH-003"], today=dt.date(2026, 8, 1))
    connection.close()
    assert [c.id for c in found] == ["L-0001"]


def test_nothing_matches_an_unrelated_situation(store: learn.Store) -> None:
    record(store, triggers=[{"type": "glob", "pattern": "docs/**"}])
    connection = learn.sync(store)
    found = learn.retrieve(store, connection, file="src/pkg/domain/x.py",
                           today=dt.date(2026, 8, 1))
    connection.close()
    assert found == []


def test_retrieval_is_reproducible(store: learn.Store) -> None:
    for _ in range(3):
        record(store)
    connection = learn.sync(store)
    first = learn.retrieve(store, connection, file="src/a.py", today=dt.date(2026, 8, 1))
    second = learn.retrieve(store, connection, file="src/a.py", today=dt.date(2026, 8, 1))
    connection.close()
    assert first == second


def test_retrieval_respects_the_budget(store: learn.Store) -> None:
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
    config = store.config()
    fresh = learn.effective_confidence(0.5, "2026-08-01T00:00:00+00:00", "diagnostic",
                                       config, dt.date(2026, 8, 1))
    one_half_life = learn.effective_confidence(0.5, "2026-08-01T00:00:00+00:00",
                                               "diagnostic", config, dt.date(2026, 10, 30))
    assert fresh == 0.5
    assert one_half_life == pytest.approx(0.25, abs=0.01)


def test_a_decayed_learning_falls_below_the_floor(store: learn.Store) -> None:
    record(store)
    connection = learn.sync(store)
    found = learn.retrieve(store, connection, file="src/a.py", today=dt.date(2030, 1, 1))
    connection.close()
    assert found == [], "an entry untouched for years should stop being offered"


# ------------------------------------------------------------------- lifecycle


def test_a_candidate_becomes_active_on_evidence(store: learn.Store) -> None:
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
    learn.append_event(store, "use", "S-1", {"ref": "L-9999", "outcome": "helped"})
    assert states(store) == {}


# ------------------------------------------------------------ generated views


def test_the_views_are_deterministic(store: learn.Store) -> None:
    record(store)
    connection = learn.sync(store)
    config = store.config()
    as_of = dt.date(2026, 8, 18)
    assert learn.render_index(connection, config) == learn.render_index(connection, config)
    assert (learn.render_calibration(connection, config, as_of)
            == learn.render_calibration(connection, config, as_of))
    connection.close()


def test_an_empty_database_explains_the_first_run(store: learn.Store) -> None:
    connection = learn.sync(store)
    report = learn.render_calibration(connection, store.config(), dt.date(2026, 8, 18))
    connection.close()
    assert "First-run protocol" in report
    assert "would have helped at the start" in report


def test_calibration_reports_precision(store: learn.Store) -> None:
    first = record(store)
    learn.append_event(store, "use", "S-2", {"ref": first, "outcome": "helped"})
    learn.append_event(store, "use", "S-3", {"ref": first, "outcome": "noise"})
    connection = learn.sync(store)
    report = learn.render_calibration(connection, store.config(), dt.date(2026, 8, 18))
    connection.close()
    assert "**50%**" in report


def test_a_parameter_change_needs_a_reason(store: learn.Store) -> None:
    changed = learn._apply_settings(store, ["retrieval.max_learnings=3"])
    assert changed["retrieval.max_learnings"] == ["8", "3"]
    assert store.config()["retrieval"]["max_learnings"] == 3


def test_an_unknown_parameter_is_refused(store: learn.Store) -> None:
    with pytest.raises(learn.LearnError, match="no setting named"):
        learn._apply_settings(store, ["retrieval.nonsense=1"])


# ---------------------------------------------------------------- graph layer


def test_learnings_surface_as_graph_edges(store: learn.Store) -> None:
    record(store, links=[{"relation": "learned_about", "node": "ARCH-003"}])
    learn.sync(store).close()
    overlay = list(learn.graph_overlay(store))
    assert [(o[0], o[2], o[3]) for o in overlay] == [("L-0001", "learned_about", "ARCH-003")]


def test_a_retired_learning_leaves_the_overlay(store: learn.Store) -> None:
    first = record(store, links=[{"relation": "learned_about", "node": "ARCH-003"}])
    learn.append_event(store, "refute", "S-2", {"ref": first, "why": "no"})
    learn.sync(store).close()
    assert list(learn.graph_overlay(store)) == []


def test_the_overlay_is_silent_without_a_database(tmp_path: Path) -> None:
    assert list(learn.graph_overlay(learn.Store(tmp_path))) == []


# ------------------------------------------------------------------- schema


def test_the_schema_records_its_version(store: learn.Store) -> None:
    connection = learn.sync(store)
    row = connection.execute("SELECT version, applied_ledger_seq FROM schema_version").fetchone()
    connection.close()
    assert row["version"] == learn.SCHEMA_VERSION


def test_a_prior_version_database_is_rebuilt_not_patched(store: learn.Store) -> None:
    """Migration story: the database is derived, so an old one is discarded and
    rebuilt from the ledger rather than migrated in place. The ledger is what a
    schema change must stay compatible with (API-012)."""
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
