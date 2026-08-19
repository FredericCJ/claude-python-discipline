"""The values the domain reasons over, each parsed once at its constructor.

Every type here is frozen and slotted (`TYPE-007`): a value that can drift
between the moment it is validated and the moment it is used cannot honestly be
named in an error message. Constrained values are wrappers with a parsing
constructor rather than bare `int`s (`TYPE-005`), so an out-of-range policy is
impossible to hold rather than merely discouraged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from refpkg.domain.errors import InvariantViolated

## Seconds in a day, for turning a policy's age limit into an instant comparison.
## Named because a bare 86400 in an expression states nothing.
SECONDS_PER_DAY: int = 86_400


@dataclass(frozen=True, slots=True)
class Instant:
    """A point in time, as whole seconds since the Unix epoch.

    A distinct type rather than a bare `int` (`TYPE-004`), so a duration can
    never be passed where an instant is meant.
    """

    ## Whole seconds since 1970-01-01T00:00:00Z. Never negative: the domain has
    ## no meaning for an instant before the epoch.
    epoch_seconds: int

    @classmethod
    def parse(cls, epoch_seconds: int) -> Self:
        """Build an instant, refusing anything the domain cannot mean.

        @param epoch_seconds whole seconds since the Unix epoch
        @return the validated instant
        @throws InvariantViolated when the value is negative
        """
        if epoch_seconds < 0:
            message = "an instant is at or after the epoch"
            raise InvariantViolated(message, epoch_seconds)
        return cls(epoch_seconds)

    def minus_days(self, days: int) -> Self:
        """The instant `days` earlier, clamped at the epoch.

        Clamping rather than refusing, because "everything older than the epoch"
        is a meaningful cutoff and an empty one, which is the correct answer.

        @param days how many whole days to subtract
        @return the earlier instant, never before the epoch
        """
        return type(self)(max(0, self.epoch_seconds - days * SECONDS_PER_DAY))


@dataclass(frozen=True, slots=True)
class Entry:
    """One file the pruner may consider, described without touching a disk.

    The domain never opens a file; an adapter reads these three facts and hands
    them in, which is what keeps planning pure and therefore replayable.
    """

    ## The file's path, as the adapter reported it. Opaque to the domain: it is
    ## carried into the plan and compared for identity, never interpreted.
    path: str
    ## The file's size, used only to total what a plan would reclaim.
    size_bytes: int
    ## When the file was last modified, which is what the age policy reads.
    modified_at: Instant


@dataclass(frozen=True, slots=True)
class Policy:
    """What the caller considers stale, and how much to spare regardless.

    The two settings interact deliberately: `keep_newest` wins over
    `max_age_days`, so a policy can be aggressive about age without ever
    emptying a directory.
    """

    ## Files older than this many days are candidates for deletion.
    max_age_days: int
    ## How many of the newest entries are spared whatever their age. Zero means
    ## spare none, which is legitimate and is why this is not a truthiness test.
    keep_newest: int

    @classmethod
    def parse(cls, max_age_days: int, keep_newest: int) -> Self:
        """Build a policy, refusing values that have no meaning.

        @param max_age_days the age past which an entry is a candidate
        @param keep_newest how many newest entries to spare unconditionally
        @return the validated policy
        @throws InvariantViolated when either value is negative
        """
        if max_age_days < 0:
            message = "max_age_days is not negative"
            raise InvariantViolated(message, max_age_days)
        if keep_newest < 0:
            message = "keep_newest is not negative"
            raise InvariantViolated(message, keep_newest)
        return cls(max_age_days, keep_newest)
