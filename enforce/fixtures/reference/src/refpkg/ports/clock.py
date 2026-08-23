"""The clock port: the current instant, supplied rather than read.

**Boundary decision (`ARCH-021`): control a specific effect and its failure.**
The wall clock is the one input that changes without anyone
changing it. Behind a port it can be pinned, so a plan computed today is the
plan computed in a replay tomorrow (`EFCT-003`); and it can be made to fail,
which is the only way to find out what the app does when it cannot tell the
time.

Contract, which every registered implementation shares under [TEST-020]:

* `now()` returns an `Instant` at or after the epoch.
* It is **non-decreasing** within a single process: two calls in order never
  return a smaller value the second time. It is not required to advance.
* It raises `ClockUnavailable` and nothing else. Any adapter-specific failure is
  translated at the adapter boundary (`ERR-004`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

# Keep the domain instant dependency type-only at the abstract port boundary.
if TYPE_CHECKING:
    from refpkg.domain.model import Instant


@runtime_checkable
class Clock(Protocol):
    """A source of the current instant.

    Structural by the explicit [ARCH-024] record: an adapter satisfies this by
    having the method, not by inheriting, so nothing in `adapters/` needs to
    import anything from the core in order to be usable by it.
    """

    def now(self) -> Instant:
        """The current instant.

        @return the current instant, at or after the epoch
        @throws ClockUnavailable when no reading can be taken
        """
        ...
