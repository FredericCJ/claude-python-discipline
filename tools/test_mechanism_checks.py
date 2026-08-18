"""Proof-of-failure tests for the two validator codes that had none.

`enforce/fitness/test_meta.py` compares every finding code the validator can
emit against the codes any test drives, and reported `V080` and `V096` as
branches nobody had ever seen taken. This closes that gap.

They live in their own file rather than in `test_validate.py` because they need
a different fixture: V080 asks whether a named mechanism exists on disk, and
V096 asks whether the learning ledger and its derived index agree.

    pytest tools/test_mechanism_checks.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import learn
from discipline_core import REPO_ROOT
from test_validate import CONFORMANT_RULE, codes, module, run_on

## A rule naming a mechanism that will never exist on disk.
UNBUILT_RULE = """\
### TYPE-001 · Domain code carries no implicit Any  [BINDING] [check:nothing_built_here]
Domain modules MUST NOT use `Any`, explicit or implicit.
- **Why** `Any` erases the guarantee the diagnostic envelope depends on.
- **Check** `python -m checks.nothing_built_here`
"""


def seed_learning(root: Path) -> learn.Store:
    """Give a scratch corpus a working learning database.

    @param root the scratch repository root
    @return the store, with schema and configuration in place
    """
    target = root / "learning"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("schema.sql", "config.toml"):
        shutil.copy(REPO_ROOT / "learning" / name, target / name)
    return learn.Store(root)


# ----------------------------------------------------------------------- V080


def test_v080_mechanism_named_but_not_built(tmp_path: Path) -> None:
    """A rule may name a mechanism before it exists, but not silently.

    The gap is reported as a warning rather than an error on purpose: the corpus
    is allowed to declare a mechanism ahead of building it, and never allowed to
    hide that it has not been built.
    """
    module(tmp_path, body=UNBUILT_RULE)
    assert "V080" in codes(run_on(tmp_path))


def test_v080_is_silent_once_the_check_exists(tmp_path: Path) -> None:
    """Creating the named module clears the warning, with nothing else changed."""
    module(tmp_path, body=UNBUILT_RULE)
    checks_dir = tmp_path / "enforce" / "checks"
    checks_dir.mkdir(parents=True, exist_ok=True)
    (checks_dir / "nothing_built_here.py").write_text(
        '"""A check that now exists."""\n', encoding="utf-8"
    )
    assert "V080" not in codes(run_on(tmp_path))


def test_v080_does_not_fire_for_an_external_tool(tmp_path: Path) -> None:
    """`auto:` names another tool's rule, which is not a file to look for.

    Reporting those as unbuilt would drown the real gaps in noise.
    """
    module(tmp_path, body=CONFORMANT_RULE)
    assert "V080" not in codes(run_on(tmp_path))


# ----------------------------------------------------------------------- V096


def test_v096_ledger_and_index_disagree(tmp_path: Path) -> None:
    """An index holding fewer events than the ledger is answering from stale data.

    The ledger is the record. The moment the derived store can disagree with it,
    the record stops being the record.
    """
    module(tmp_path)
    store = seed_learning(tmp_path)
    learn.append_event(store, "session", "S-1", {"task": "first"})
    learn.sync(store).close()
    # Append without syncing: the ledger moves on, the index does not.
    learn.append_event(store, "session", "S-2", {"task": "second"})
    assert "V096" in codes(run_on(tmp_path))


def test_v096_clears_after_a_sync(tmp_path: Path) -> None:
    """Syncing is the remedy the finding names, and it works."""
    module(tmp_path)
    store = seed_learning(tmp_path)
    learn.append_event(store, "session", "S-1", {"task": "first"})
    learn.append_event(store, "session", "S-2", {"task": "second"})
    learn.sync(store).close()
    assert "V096" not in codes(run_on(tmp_path))


def test_v096_is_silent_without_a_database(tmp_path: Path) -> None:
    """An absent index is the normal state after a clone, not drift.

    The database is derived and gitignored. Reporting its absence would fire on
    every fresh checkout, which is how a finding gets ignored.
    """
    module(tmp_path)
    store = seed_learning(tmp_path)
    learn.append_event(store, "session", "S-1", {"task": "first"})
    assert not store.db.exists()
    assert "V096" not in codes(run_on(tmp_path))


def test_v096_reports_an_unreadable_ledger(tmp_path: Path) -> None:
    """A ledger line that is not JSON is named by file and line number."""
    module(tmp_path)
    store = seed_learning(tmp_path)
    learn.append_event(store, "session", "S-1", {"task": "first"})
    learn.sync(store).close()
    with store.ledger.open("a", encoding="utf-8") as handle:
        handle.write("{ not json\n")
    findings = run_on(tmp_path)
    assert "V096" in codes(findings)
    assert any("ledger.jsonl:2" in f.message for f in findings)  # type: ignore[attr-defined]


def test_the_ledger_survives_a_round_trip(tmp_path: Path) -> None:
    """Guards the assumption the two tests above rest on: the fixture is honest.

    If appending and syncing did not agree in the healthy case, the drift tests
    would pass for the wrong reason.
    """
    store = seed_learning(tmp_path)
    for index in range(3):
        learn.append_event(store, "session", f"S-{index}", {"task": str(index)})
    connection = learn.sync(store)
    stored = connection.execute("SELECT COUNT(*) FROM event").fetchone()[0]
    connection.close()
    assert stored == len(learn.read_ledger(store)) == 3


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
