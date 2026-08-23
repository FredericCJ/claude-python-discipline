"""The fake clock: a clock the test moves by hand.

A fake, not a mock. It implements the contract rather than recording calls, so
the same suite that holds `SystemClock` to the contract holds this one
(`TEST-020`). A test substitute that can drift from its real counterpart without
a test failing is worthless, and every unit test standing on it is worth as
little -- which is why the shared suite is the point and this class is not.
"""

from __future__ import annotations

from refpkg.domain.model import Instant


class FakeClock:
    """A clock returning what it was last set to.

    Non-decreasing by construction: `advance` only moves forward, and there is no
    way to move it back. The contract requires that, so the fake enforces it
    rather than trusting a test not to violate it.
    """

    def __init__(self, start: Instant) -> None:
        """Begin at a stated instant.

        @param start what `now` returns until the clock is advanced
        """
        ## The last instant supplied to callers of `now`.
        self._current = start  # Establish the first published instant.

    def now(self) -> Instant:
        """The instant this clock was last set to.

        @return the current instant; never raises, since nothing can fail here
        """
        # Expose the last explicitly established instant without consulting a host clock.
        return self._current

    def advance(self, seconds: int) -> None:
        """Move the clock forward.

        @param seconds how far forward to move; must not be negative, because a
            clock that can go backwards would satisfy no contract worth having
        @throws ValueError when asked to move backwards
        @par Effects
        Advances this clock's published instant exactly once after validation.
        """
        # Guard the port's non-decreasing-time invariant before changing state.
        if seconds < 0:
            # Preserve the invalid signed displacement in the boundary diagnostic.
            message = f"a clock does not run backwards; got {seconds}"
            raise ValueError(message)
        # Advance the published instant by the validated whole-second displacement.
        self._current = Instant(self._current.epoch_seconds + seconds)
