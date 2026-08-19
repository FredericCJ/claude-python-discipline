"""The real clock: the one module in this package that reads wall time.

`ARCH-004` -- a foreign dependency appears in exactly one adapter. `time` is
imported here and nowhere else in `refpkg`, so the blast radius of the process
clock is this file, and a stack frame naming it is unambiguous about where the
non-determinism entered.
"""

from __future__ import annotations

import time

from refpkg.domain.model import Instant
from refpkg.ports.errors import ClockUnavailable


class SystemClock:
    """Reads the host's wall clock.

    Satisfies `refpkg.ports.clock.Clock` structurally; it does not inherit from
    it, which is what keeps the dependency pointing inward (`ARCH-001`).
    """

    def now(self) -> Instant:
        """The host's current instant, truncated to whole seconds.

        @return the current instant
        @throws ClockUnavailable when the host clock reports a time before the
            epoch, which a misconfigured or unset real-time clock does
        """
        seconds = int(time.time())
        if seconds < 0:
            message = f"host clock reports {seconds}, which is before the epoch"
            raise ClockUnavailable(message)
        return Instant(seconds)
