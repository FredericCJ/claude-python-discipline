"""The faulty clock: the same contract, failing on a schedule.

`ARCH-008` requires this unconditionally, with no "if the port has meaningful
failure modes" qualifier. A clock looks like it cannot fail, which is exactly why
it needs one: the port judged to have no failure mode is the port whose failure
is discovered in production.

In healthy mode -- an empty schedule -- it must pass the port's contract suite
unchanged, which is what stops a faulty adapter from being a second, divergent
implementation nobody holds to the contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from refpkg.adapters.faults import FaultSchedule
from refpkg.ports.errors import ClockUnavailable

if TYPE_CHECKING:
    from refpkg.domain.model import Instant


class FaultyClock:
    """A clock that fails on the calls its schedule names."""

    def __init__(self, start: Instant, schedule: FaultSchedule | None = None) -> None:
        """Begin at a stated instant, failing where the schedule says.

        @param start what a successful `now` returns
        @param schedule which calls fail; healthy when omitted
        """
        self._current = start
        self._schedule = schedule if schedule is not None else FaultSchedule.healthy()
        self._calls = 0

    def now(self) -> Instant:
        """The current instant, unless this call is scheduled to fail.

        @return the instant this clock was constructed with
        @throws ClockUnavailable when the schedule names this call
        """
        self._calls += 1
        if self._schedule.fails(self._calls):
            raise ClockUnavailable(self._schedule.detail)
        return self._current
