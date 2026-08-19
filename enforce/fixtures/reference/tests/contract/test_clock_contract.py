"""Contract suite for the `Clock` port, run unchanged against all three adapters.

**Oracle: the port's published contract** (`TEST-004`). Not the implementation --
these assertions come from the docstring of `refpkg.ports.clock`, and any adapter
satisfying them is substitutable for any other.

`ARCH-009` requires exactly this: one suite, parameterised over real, fake and
faulty-in-healthy-mode. A fake tested by its own separate suite can drift from
the real adapter without anything failing, and every unit test standing on that
fake is then worth as little as the fake.

`TEST-001` -- this layer touches no external resource. `SystemClock` reads the
host clock, which is the one unavoidable exception and the reason the assertions
here are about *shape and ordering* rather than about any particular value.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from refpkg.adapters.clock.fake import FakeClock
from refpkg.adapters.clock.faulty import FaultyClock
from refpkg.adapters.clock.real import SystemClock
from refpkg.adapters.faults import FaultSchedule
from refpkg.domain.model import Instant
from refpkg.ports.clock import Clock

if TYPE_CHECKING:
    from collections.abc import Callable

## Every adapter for this port, named for the failure message. The faulty one
## appears in healthy mode, which is what `ARCH-009` demands and what stops it
## from being a second implementation nobody holds to the contract.
ADAPTERS: tuple[tuple[str, Callable[[], Clock]], ...] = (
    ("real", SystemClock),
    ("fake", lambda: FakeClock(Instant(1_700_000_000))),
    ("faulty-healthy", lambda: FaultyClock(Instant(1_700_000_000), FaultSchedule.healthy())),
)


@pytest.fixture(params=list(ADAPTERS), ids=[name for name, _ in ADAPTERS])
def clock(request: pytest.FixtureRequest) -> Clock:
    """One adapter under test, one per parameterisation.

    @param request pytest's request object, carrying the parameter
    @return a freshly constructed adapter
    """
    _, build = request.param
    return build()


def test_it_satisfies_the_protocol(clock: Clock) -> None:
    """Structural conformance, checked at runtime as well as by the checker.

    @param clock the adapter under test
    """
    assert isinstance(clock, Clock)


def test_now_returns_an_instant_at_or_after_the_epoch(clock: Clock) -> None:
    """The contract's first clause.

    @param clock the adapter under test
    """
    assert clock.now().epoch_seconds >= 0


def test_now_is_non_decreasing(clock: Clock) -> None:
    """The contract's second clause: never smaller on a later call.

    Stated as non-decreasing rather than increasing on purpose -- a clock with
    one-second resolution read twice quickly returns the same value, and a suite
    demanding strict increase would fail the real adapter intermittently.

    @param clock the adapter under test
    """
    first = clock.now()
    second = clock.now()
    assert second.epoch_seconds >= first.epoch_seconds
