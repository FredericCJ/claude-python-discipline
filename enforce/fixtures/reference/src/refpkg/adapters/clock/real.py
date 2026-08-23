"""The real clock: the one module in this package that reads wall time.

`ARCH-020` -- the clock adapter boundary owns direct imports of `time`. The
repository-local shell may import this adapter for wiring without becoming a
second technology owner, so the clock still has one containment boundary.
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
        @par Effects
        Reads the host wall clock once and publishes no state change.
        """
        # Convert one host-clock reading to the domain's whole-second representation.
        seconds = int(time.time())
        if seconds < 0:
            # Translate an unusable host epoch reading into the clock port's error family.
            message = f"host clock reports {seconds}, which is before the epoch"
            raise ClockUnavailable(message)
        # Expose the validated reading as the domain's instant value.
        return Instant(seconds)
