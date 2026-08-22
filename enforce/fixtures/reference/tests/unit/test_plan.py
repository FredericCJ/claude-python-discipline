"""Unit tests for planning: pure domain, no external resource of any kind.

**Oracle: contract.** The stated obligations of `plan_prune` (`TEST-004`) -- the sentences
in its docstring and in `Policy`, turned into assertions one at a time.

`TEST-001`: nothing here imports a filesystem, a clock, a socket or an adapter.
The instant is a value handed in, which is the whole point of `ARCH-005` and is
what makes these tests identical on every machine.
"""

from __future__ import annotations

import pytest
from refpkg.domain.errors import InvariantViolated
from refpkg.domain.model import SECONDS_PER_DAY, Entry, Instant, Policy
from refpkg.domain.plan import MAX_PLAN_ENTRIES, Plan, Refusal, plan_prune

## A fixed reference point, so every age in this module is stated relative to one
## instant a reader can hold in their head.
NOW: Instant = Instant(100 * SECONDS_PER_DAY)


def aged(days: int, *, name: str = "f", size: int = 1) -> Entry:
    """An entry last modified a whole number of days before `NOW`.

    @param days how many days old the entry is
    @param name the entry's path
    @param size the entry's size in bytes
    @return the entry
    """
    return Entry(path=name, size_bytes=size,
                 modified_at=Instant(NOW.epoch_seconds - days * SECONDS_PER_DAY))


def test_an_empty_store_yields_an_empty_plan() -> None:
    """Nothing to consider is a plan, not a refusal."""
    outcome = plan_prune([], Policy.parse(30, 0), NOW)
    assert outcome == Plan(doomed=(), kept=())


def test_an_entry_older_than_the_limit_is_doomed() -> None:
    """The rule's principal clause."""
    old = aged(60, name="old")
    outcome = plan_prune([old], Policy.parse(30, 0), NOW)
    assert isinstance(outcome, Plan)
    assert outcome.doomed == (old,)


def test_an_entry_younger_than_the_limit_is_kept() -> None:
    """The complement, which a check that only tested doom would miss."""
    fresh = aged(5, name="fresh")
    outcome = plan_prune([fresh], Policy.parse(30, 0), NOW)
    assert isinstance(outcome, Plan)
    assert outcome.doomed == ()
    assert outcome.kept == (fresh,)


def test_an_entry_exactly_at_the_limit_is_kept() -> None:
    """The boundary, stated so the comparison cannot silently become `<=`."""
    edge = aged(30, name="edge")
    outcome = plan_prune([edge], Policy.parse(30, 0), NOW)
    assert isinstance(outcome, Plan)
    assert outcome.doomed == ()


def test_keep_newest_spares_entries_the_age_policy_condemns() -> None:
    """The interaction the two settings exist to have.

    Every entry here is far past the age limit, so anything spared is spared by
    `keep_newest` alone.
    """
    entries = [aged(days, name=f"f{days}") for days in (90, 80, 70)]
    outcome = plan_prune(entries, Policy.parse(30, 2), NOW)
    assert isinstance(outcome, Plan)
    assert [e.path for e in outcome.doomed] == ["f90"]


def test_keep_newest_larger_than_the_store_dooms_nothing() -> None:
    """A policy that spares more than exists must not index past the end."""
    entries = [aged(90, name="a"), aged(80, name="b")]
    outcome = plan_prune(entries, Policy.parse(30, 10), NOW)
    assert isinstance(outcome, Plan)
    assert outcome.doomed == ()


def test_an_entry_from_the_future_is_refused() -> None:
    """The refusal arm: a result the caller handles, never an exception."""
    outcome = plan_prune([aged(-1, name="tomorrow")], Policy.parse(30, 0), NOW)
    assert isinstance(outcome, Refusal)
    assert outcome.code == "refpkg.domain.entry_from_the_future"
    assert "tomorrow" in outcome.actual


def test_reclaimed_bytes_totals_only_the_doomed() -> None:
    """The figure a caller decides on; counting the kept would overstate it."""
    outcome = plan_prune(
        [aged(90, name="old", size=100), aged(1, name="new", size=7)],
        Policy.parse(30, 0), NOW,
    )
    assert isinstance(outcome, Plan)
    assert outcome.reclaimed_bytes == 100


def test_every_entry_appears_exactly_once() -> None:
    """A plan partitions its input; an entry both doomed and kept is nonsense."""
    entries = [aged(days, name=f"f{days}") for days in (90, 10, 50)]
    outcome = plan_prune(entries, Policy.parse(30, 1), NOW)
    assert isinstance(outcome, Plan)
    assert sorted(e.path for e in outcome.doomed + outcome.kept) == ["f10", "f50", "f90"]
    assert not set(outcome.doomed) & set(outcome.kept)


def test_planning_refuses_work_beyond_its_input_and_cleanup_budget() -> None:
    """The operational bound is enforced before sorting or destructive planning."""
    entry = aged(90, name="same_value")
    outcome = plan_prune([entry] * (MAX_PLAN_ENTRIES + 1), Policy.parse(30, 0), NOW)
    assert isinstance(outcome, Refusal)
    assert outcome.code == "refpkg.domain.plan_too_large"
    assert str(MAX_PLAN_ENTRIES) in outcome.expected


@pytest.mark.parametrize(("max_age", "keep"), [(-1, 0), (0, -1)])
def test_a_negative_policy_is_refused_at_its_constructor(max_age: int, keep: int) -> None:
    """Parsing at the boundary (`ERR-011`): the value never reaches the planner.

    @param max_age the age limit under test
    @param keep the spare count under test
    """
    with pytest.raises(InvariantViolated):
        Policy.parse(max_age, keep)
