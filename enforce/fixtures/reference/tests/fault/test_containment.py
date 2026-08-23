"""Fault tests: what happens when an adapter fails, and where the failure stops.

**Oracle: contract.** The containment and propagation rules (`TEST-004`,
`TEST-011`) are clauses of the ports' published contracts --
each layer produces its own error family (`ERR-004`), a fault is contained at the
boundary that detected it (`ERR-016`), and an interrupted apply reports exactly
how far it got (`EFCT-007`, `EFCT-009`).

Every fault here is a `FaultSchedule` value rather than a bespoke class
(`TEST-009`), so the failing call is a number in a table and the case can be
parameterised rather than hand-written.
"""

from __future__ import annotations

import pytest
from refpkg.adapters.clock.faulty import FaultyClock
from refpkg.adapters.faults import FaultSchedule
from refpkg.adapters.files.faulty import FaultyFileStore
from refpkg.app.errors import PruneInterrupted
from refpkg.app.prune import apply, survey
from refpkg.domain.model import SECONDS_PER_DAY, Entry, Instant, Policy
from refpkg.domain.plan import Plan
from refpkg.ports.errors import ClockUnavailable, PortError, StoreUnavailable
from refpkg.shell import envelope

## Three entries, all far past any age limit used here, so every one is doomed
## and the only thing deciding the outcome is where the injected fault lands.
NOW: Instant = Instant(100 * SECONDS_PER_DAY)
## Each stale entry used by this suite, ordered by increasing numeric path so a
## failure message and deletion prefix identify exactly which call was reached.
STALE: tuple[Entry, ...] = tuple(
    Entry(path=f"{n}.log", size_bytes=n, modified_at=Instant(1))
    for n in (1, 2, 3)
)


def doomed_plan() -> Plan:
    """A plan condemning all three entries, computed with healthy adapters.

    @return the plan every test in this module then tries to apply
    """
    # Compose healthy scheduled adapters and compute the shared all-doomed plan.
    store = FaultyFileStore(STALE, FaultSchedule.healthy())
    clock = FaultyClock(NOW, FaultSchedule.healthy())
    outcome = survey(store, clock, Policy.parse(1, 0))
    assert isinstance(outcome, Plan)
    return outcome


def test_a_clock_fault_surfaces_as_the_adapter_family() -> None:
    """`ERR-004`: the layer that failed owns the error, and says so."""
    # Pair a healthy store with a first-call clock fault at the survey boundary.
    store = FaultyFileStore(STALE, FaultSchedule.healthy())
    clock = FaultyClock(NOW, FaultSchedule.failing_on(1, detail="no rtc"))
    with pytest.raises(ClockUnavailable) as caught:
        survey(store, clock, Policy.parse(1, 0))
    assert caught.value.code == "refpkg.port.clock_unavailable"
    assert caught.value.port == "Clock"


def test_a_store_fault_during_listing_surfaces_as_the_adapter_family() -> None:
    """The other port, same rule."""
    # Select a first-call store fault and require its published port error family.
    store = FaultyFileStore(STALE, FaultSchedule.failing_on(1))
    with pytest.raises(StoreUnavailable):
        store.delete("1.log")


@pytest.mark.parametrize("failing_call", [1, 2, 3])
def test_an_interrupted_apply_reports_how_far_it_got(failing_call: int) -> None:
    """`EFCT-009`: what is not guaranteed is stated, with the numbers.

    @param failing_call which deletion fails, one-based
    """
    # Apply the shared plan against a store failing at the parameterized call index.
    plan = doomed_plan()
    store = FaultyFileStore(STALE, FaultSchedule.failing_on(failing_call))
    with pytest.raises(PruneInterrupted) as caught:
        apply(store, plan)
    assert len(caught.value.deleted) == failing_call - 1
    assert len(caught.value.remaining) == len(plan.doomed) - (failing_call - 1)


def test_an_interrupted_apply_chains_the_adapter_error_it_came_from() -> None:
    """`DIAG-005`: the cause survives; the app error does not replace it."""
    # Trigger a second-deletion failure so one completed effect precedes the cause.
    plan = doomed_plan()
    store = FaultyFileStore(STALE, FaultSchedule.failing_on(2, detail="disk gone"))
    with pytest.raises(PruneInterrupted) as caught:
        apply(store, plan)
    assert isinstance(caught.value.__cause__, PortError)
    assert "disk gone" in str(caught.value.__cause__)


def test_the_envelope_of_an_interrupted_apply_localizes_it() -> None:
    """`DIAG-001`: the record names the layer, the cause and what to do next.

    This is the fixture's whole thesis in one assertion. The `layer` field is
    derived from the error's family rather than passed in, which is only sound
    because `ERR-004` holds.
    """
    # Capture a known partial apply and project its chained failure through the shell.
    plan = doomed_plan()
    store = FaultyFileStore(STALE, FaultSchedule.failing_on(2, detail="disk gone"))
    with pytest.raises(PruneInterrupted) as caught:
        apply(store, plan)

    # Inspect each envelope field, preserving cause-chain element order in the oracle.
    record = envelope.from_error(caught.value)
    assert record["layer"] == "app"
    assert record["code"] == "refpkg.app.prune_interrupted"
    # Project each cause record to the layer identity asserted by containment.
    assert [c["layer"] for c in record["cause_chain"]] == ["adapter"]
    assert "already happened" in record["remediation"]
