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

import shutil
from typing import TYPE_CHECKING

import pytest

import learn
from decides import decides
from discipline_core import REPO_ROOT, rules_declared_by
from test_validate import CONFORMANT_RULE, codes, module, run_on

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from pathlib import Path

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

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    target = root / "learning"
    # Publish the externally visible effect after all required inputs are ready.
    target.mkdir(parents=True, exist_ok=True)
    # Normalize the current repository path to its portable baseline key spelling.
    # Process each candidate element in deterministic source order.
    for name in ("schema.sql", "config.toml"):
        shutil.copy(REPO_ROOT / "learning" / name, target / name)
    # Return the store, with schema and configuration in place to the caller.
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
    """Creating the named module clears the warning, with nothing else changed.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    module(tmp_path, body=UNBUILT_RULE)
    # Derive checks dir from tmp_path / "enforce" / "checks" for the next test v080 is silent
    # Details: once the check exists decision.
    checks_dir = tmp_path / "enforce" / "checks"
    # Publish the externally visible effect after all required inputs are ready.
    checks_dir.mkdir(parents=True, exist_ok=True)
    # Publish the externally visible effect after all required inputs are ready.
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

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    module(tmp_path)
    # Compute store using seed learning for later test v096 ledger and index disagree logic.
    store = seed_learning(tmp_path)
    learn.append_event(store, "session", "S-1", {"task": "first"})
    # Publish the externally visible effect after all required inputs are ready.
    learn.sync(store).close()
    # Append without syncing: the ledger moves on, the index does not.
    learn.append_event(store, "session", "S-2", {"task": "second"})
    assert "V096" in codes(run_on(tmp_path))


def test_v096_clears_after_a_sync(tmp_path: Path) -> None:
    """Syncing is the remedy the finding names, and it works.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    module(tmp_path)
    # Compute store using seed learning for later test v096 clears after a sync logic.
    store = seed_learning(tmp_path)
    learn.append_event(store, "session", "S-1", {"task": "first"})
    learn.append_event(store, "session", "S-2", {"task": "second"})
    # Publish the externally visible effect after all required inputs are ready.
    learn.sync(store).close()
    assert "V096" not in codes(run_on(tmp_path))


def test_v096_is_silent_without_a_database(tmp_path: Path) -> None:
    """An absent index is the normal state after a clone, not drift.

    The database is derived and gitignored. Reporting its absence would fire on
    every fresh checkout, which is how a finding gets ignored.
    """
    module(tmp_path)
    # Derive store from seed learning for the next test v096 is silent without a database
    # Details: decision.
    store = seed_learning(tmp_path)
    learn.append_event(store, "session", "S-1", {"task": "first"})
    assert not store.db.exists()
    assert "V096" not in codes(run_on(tmp_path))


def test_v096_reports_an_unreadable_ledger(tmp_path: Path) -> None:
    """A ledger line that is not JSON is named by file and line number.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    module(tmp_path)
    # Derive store from seed learning for the next test v096 reports an unreadable ledger
    # Details: decision.
    store = seed_learning(tmp_path)
    learn.append_event(store, "session", "S-1", {"task": "first"})
    # Publish the externally visible effect after all required inputs are ready.
    learn.sync(store).close()
    # Derive handle from "utf-8") as handle: for the next test v096 reports an unreadable ledger
    # Details: decision.
    # Confine the acquired resource to this operation and release it on every exit.
    with store.ledger.open("a", encoding="utf-8") as handle:
        # Publish the externally visible effect after all required inputs are ready.
        handle.write("{ not json\n")
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = run_on(tmp_path)
    assert "V096" in codes(findings)
    # Select f as the current element from findings)  # type while test v096 reports an
    # Details: unreadable ledger preserves traversal order.
    assert any("ledger.jsonl:2" in f.message for f in findings)  # type: ignore[attr-defined]


def test_the_ledger_survives_a_round_trip(tmp_path: Path) -> None:
    """Guards the assumption the two tests above rest on: the fixture is honest.

    If appending and syncing did not agree in the healthy case, the drift tests
    would pass for the wrong reason.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Derive store from seed learning for the next test the ledger survives a round trip
    # Details: decision.
    store = seed_learning(tmp_path)
    # Locate the structural boundary used to parse the external result safely.
    # Process each candidate element in deterministic source order.
    for index in range(3):
        learn.append_event(store, "session", f"S-{index}", {"task": str(index)})
    # Derive connection from learn.sync for the next test the ledger survives a round trip
    # Details: decision.
    connection = learn.sync(store)
    # Derive stored from connection.execute for the next test the ledger survives a round trip
    # Details: decision.
    stored = connection.execute("SELECT COUNT(*) FROM event").fetchone()[0]
    # Publish the externally visible effect after all required inputs are ready.
    connection.close()
    assert stored == len(learn.read_ledger(store)) == 3


# --------------------------------------------------- V080, the fitness arm


## A rule resting on a fitness test rather than a check. Until v3.1 the tag was
## resolved by searching for the text `def <name>(`, so this rule counted as
## decided the moment any file anywhere defined a function by that name.
FITNESS_RULE = """\
### TYPE-001 · Domain code carries no implicit Any  [BINDING] [fitness:test_a_named_property]
Domain modules MUST NOT use `Any`, explicit or implicit.
- **Why** `Any` erases the guarantee the diagnostic envelope depends on.
- **Check** `pytest enforce/fitness/test_types.py::test_a_named_property`
"""


def write_fitness(root: Path, declaration: str = "") -> None:
    """Put a fitness function into a scratch corpus, optionally declared.

    @param root the scratch repository root
    @param declaration a `@decides(...)` line, or the empty string for none

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Compute suite using root / "enforce" / "fitness" for later write fitness logic.
    suite = root / "enforce" / "fitness"
    # Publish the externally visible effect after all required inputs are ready.
    suite.mkdir(parents=True, exist_ok=True)
    # Publish the externally visible effect after all required inputs are ready.
    (suite / "test_types.py").write_text(
        '"""A fitness suite."""\n\n\n'
        + (declaration + "\n" if declaration else "")
        + "def test_a_named_property() -> None:\n"
        '    """It holds."""\n'
        "    assert True\n",
        encoding="utf-8",
    )


def test_v080_fires_when_no_such_fitness_function_exists(tmp_path: Path) -> None:
    """A tag naming a function nobody wrote is unbuilt, as it always was."""
    module(tmp_path, body=FITNESS_RULE)
    assert "V080" in codes(run_on(tmp_path))


def test_v080_fires_for_an_undecorated_fitness_function(tmp_path: Path) -> None:
    """The defect the fitness arm was rewritten to catch.

    The function exists and the rule tags it, which is all the old resolver ever
    asked. It declares nothing, so it agrees to nothing, and the rule is reported
    undecided rather than counted decided.
    """
    module(tmp_path, body=FITNESS_RULE)
    write_fitness(tmp_path)
    assert "V080" in codes(run_on(tmp_path))


def test_v080_is_silent_once_the_function_declares_the_rule(tmp_path: Path) -> None:
    """Declaring the rule is what clears it, with nothing else changed."""
    module(tmp_path, body=FITNESS_RULE)
    write_fitness(tmp_path, declaration='@decides("TYPE-001")')
    assert "V080" not in codes(run_on(tmp_path))


def test_a_function_declaring_a_different_rule_does_not_decide_this_one(
    tmp_path: Path,
) -> None:
    """The multi-claim case, which is where the check side was wrong 23% of the time.

    Seventeen fitness functions carried more than one rule between them. A
    resolver that stops at "this function is declared" would clear every one of
    them the moment any single rule was named.
    """
    module(tmp_path, body=FITNESS_RULE)
    write_fitness(tmp_path, declaration='@decides("ARCH-002", "ARCH-003")')
    assert "V080" in codes(run_on(tmp_path))


def test_the_resolver_reports_a_missing_function_apart_from_an_undeclared_one(
    tmp_path: Path,
) -> None:
    """None and the empty set mean different things and must not be conflated.

    None is "no such function"; an empty set is "it is there and has declared
    nothing". Both make the rule undecided, but only the first is a broken tag,
    and a maintainer chasing one needs to know which they have.
    """
    assert rules_declared_by("test_a_named_property", tmp_path) is None
    write_fitness(tmp_path)
    assert rules_declared_by("test_a_named_property", tmp_path) == frozenset()


def test_the_declaration_is_read_from_tools_as_well(tmp_path: Path) -> None:
    """Six of the forty tagged functions live in `tools/`, not the suites.

    A resolver narrowed to `enforce/fitness/` would silently undecide `DEP-013`,
    `DEP-014` and the four `LEARN` rules.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Derive tools from tmp_path / "tools" for the next test the declaration is read from tools
    # Details: as well decision.
    tools = tmp_path / "tools"
    # Publish the externally visible effect after all required inputs are ready.
    tools.mkdir(parents=True, exist_ok=True)
    # Publish the externally visible effect after all required inputs are ready.
    (tools / "test_thing.py").write_text(
        '"""A suite outside enforce/fitness."""\n\n\n'
        '@decides("DEP-013")\n'
        "def test_a_block_is_replaced() -> None:\n"
        '    """It is."""\n'
        "    assert True\n",
        encoding="utf-8",
    )
    assert rules_declared_by("test_a_block_is_replaced", tmp_path) == frozenset(
        {"DEP-013"}
    )


# --------------------------------------------------- the decorator itself


def test_declaring_no_rule_is_refused() -> None:
    """`@decides()` reads as a declaration while asserting nothing.

    Worse than no decorator: it looks migrated, so nobody comes back to it.
    """
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(ValueError, match="names no rule"):
        decides()


def test_a_malformed_rule_id_is_refused() -> None:
    """A typo must fail at collection, not resolve to a rule that does not exist."""
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(ValueError, match="not rule ids"):
        decides("ARCH-2")


def test_the_decorated_function_is_returned_unchanged() -> None:
    """Nothing at runtime may depend on this, or a test would behave differently."""

    def sample() -> int:
        """A function under declaration.

        @return a constant
        """
        # Return a constant to the caller.
        return 7

    assert decides("ARCH-002")(sample) is sample
    assert sample() == 7


# ----------------------------------------------------------------------- V098


def write_matrix(root: Path, *covered: str) -> None:
    """Give a scratch corpus a discrimination matrix covering the named rules.

    @param root the scratch repository root
    @param covered rule ids the matrix should report as discriminated

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    target = root / "enforce"
    # Publish the externally visible effect after all required inputs are ready.
    target.mkdir(parents=True, exist_ok=True)
    # Select listed, rule as the current element from covered) while write matrix preserves
    # Details: traversal order.
    listed = ", ".join(f'"{rule}"' for rule in covered)
    # Publish the externally visible effect after all required inputs are ready.
    (target / "discrimination.py").write_text(
        '"""A matrix."""\n\n\n'
        "def covered():\n"
        '    """Which rules have a mutation.\n\n    @return the ids\n    """\n'
        f"    return frozenset({{{listed}}})\n",
        encoding="utf-8",
    )


def test_v098_reports_a_decided_rule_nobody_has_watched(tmp_path: Path) -> None:
    """A rule whose mechanism exists, claims it, and has never been observed.

    The third question, after "does a mechanism exist" and "does it claim this
    rule". `ARCH-013` answered yes to both and reported nothing against four
    real domains for as long as it was counted mechanized.
    """
    module(tmp_path, body=FITNESS_RULE)
    write_fitness(tmp_path, declaration='@decides("TYPE-001")')
    write_matrix(tmp_path)
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = run_on(tmp_path)
    assert "V080" not in codes(findings)
    assert "V098" in codes(findings)


def test_v098_clears_once_the_rule_has_a_mutation(tmp_path: Path) -> None:
    """Declaring a mutation is what clears it, with nothing else changed."""
    module(tmp_path, body=FITNESS_RULE)
    write_fitness(tmp_path, declaration='@decides("TYPE-001")')
    write_matrix(tmp_path, "TYPE-001")
    assert "V098" not in codes(run_on(tmp_path))


def test_v098_is_silent_when_the_rule_is_not_decided_at_all(tmp_path: Path) -> None:
    """An undecided rule is V080's finding; reporting it twice is noise.

    Two codes moving together are not two pieces of evidence.
    """
    module(tmp_path, body=FITNESS_RULE)
    write_fitness(tmp_path)
    write_matrix(tmp_path)
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = run_on(tmp_path)
    assert "V080" in codes(findings)
    assert "V098" not in codes(findings)


def test_v098_is_silent_when_the_tree_carries_no_matrix(tmp_path: Path) -> None:
    """An adopter may vendor the corpus without the matrix.

    Reporting a gap that cannot be computed would be worse than reporting none.
    """
    module(tmp_path, body=FITNESS_RULE)
    write_fitness(tmp_path, declaration='@decides("TYPE-001")')
    assert "V098" not in codes(run_on(tmp_path))


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    # Propagate the localized failure so callers cannot mistake it for success.
    raise SystemExit(pytest.main([__file__, "-q"]))
