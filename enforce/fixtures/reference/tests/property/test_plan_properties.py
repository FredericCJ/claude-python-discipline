"""Property tests: the algebraic facts planning must satisfy for any input.

**Oracle: stated invariants** (`TEST-004`, `TEST-007`). Each property below is a
sentence from `plan_prune`'s contract, quantified over generated input rather
than over the handful of cases someone thought of.

The generator is deliberately narrow -- non-negative instants, non-negative
policies -- because the constructors refuse anything else (`ERR-011`), so a
generator producing them would be testing the parser and not the planner.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st
from refpkg.domain.model import Entry, Instant, Policy
from refpkg.domain.plan import Plan, Refusal, plan_prune

## Instants comfortably inside the representable range, so arithmetic in the
## planner cannot clamp and make a property vacuously true.
INSTANTS = st.integers(min_value=0, max_value=10**9)

## One entry, with a path unique enough that a partition property is meaningful.
ENTRIES = st.builds(
    Entry,
    path=st.text(min_size=1, max_size=8,
                 alphabet=st.characters(min_codepoint=97, max_codepoint=122)),
    size_bytes=st.integers(min_value=0, max_value=10**6),
    modified_at=st.builds(Instant, INSTANTS),
)

## Policies inside what the constructor admits.
POLICIES = st.builds(
    Policy,
    max_age_days=st.integers(min_value=0, max_value=3650),
    keep_newest=st.integers(min_value=0, max_value=20),
)


@given(entries=st.lists(ENTRIES, max_size=12), policy=POLICIES, now=INSTANTS)
def test_planning_is_total(entries: list[Entry], policy: Policy, now: int) -> None:
    """It always returns one arm of the union and never raises.

    @param entries the generated store contents
    @param policy the generated policy
    @param now the generated instant
    """
    assert isinstance(plan_prune(entries, policy, Instant(now)), (Plan, Refusal))


@given(entries=st.lists(ENTRIES, max_size=12), policy=POLICIES, now=INSTANTS)
def test_a_plan_partitions_its_input(entries: list[Entry], policy: Policy,
                                     now: int) -> None:
    """Every entry is doomed or kept, never both and never neither.

    @param entries the generated store contents
    @param policy the generated policy
    @param now the generated instant
    """
    outcome = plan_prune(entries, policy, Instant(now))
    if isinstance(outcome, Refusal):
        return
    # Compared as multisets: two entries may be equal, and a partition that
    # silently collapsed them is the defect this suite found in the planner.
    assert sorted(outcome.doomed + outcome.kept, key=repr) == sorted(entries, key=repr)


@given(entries=st.lists(ENTRIES, max_size=12), policy=POLICIES, now=INSTANTS)
def test_keep_newest_is_never_exceeded(entries: list[Entry], policy: Policy,
                                       now: int) -> None:
    """At least `min(keep_newest, len(entries))` entries survive.

    The clause that makes an aggressive age policy safe to run.

    @param entries the generated store contents
    @param policy the generated policy
    @param now the generated instant
    """
    outcome = plan_prune(entries, policy, Instant(now))
    if isinstance(outcome, Refusal):
        return
    assert len(outcome.kept) >= min(policy.keep_newest, len(entries))


@given(entries=st.lists(ENTRIES, max_size=12), policy=POLICIES, now=INSTANTS)
def test_planning_is_deterministic(entries: list[Entry], policy: Policy,
                                   now: int) -> None:
    """`EFCT-003`: the same inputs give the same plan, every time.

    @param entries the generated store contents
    @param policy the generated policy
    @param now the generated instant
    """
    first = plan_prune(entries, policy, Instant(now))
    second = plan_prune(entries, policy, Instant(now))
    assert first == second
