"""The faulty file store: failing partway through a deletion, on purpose.

The case this exists for is the one the port's contract warns about: `delete` is
not atomic across a sequence of calls, so an interrupted run leaves some entries
gone and the rest present. Nothing else can produce that state on demand, and
`EFCT-007`'s journalling requirement is unfalsifiable without it.

Healthy mode -- an empty schedule -- passes the shared contract suite unchanged
(`TEST-020`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from refpkg.adapters.faults import FaultSchedule
from refpkg.ports.errors import StoreOperation, StoreUnavailable

# Keep iterable and domain entry contracts type-only in the concrete adapter.
if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from refpkg.domain.model import Entry


class FaultyFileStore:
    """A store that fails on the calls its schedule names.

    The schedule counts `delete` calls only. Listing is not scheduled because a
    store that cannot be listed fails before any deletion, which is the
    uninteresting half of the failure space -- the interesting half is failing
    with some deletions already done.
    """

    def __init__(self, entries: Iterable[Entry] = (),
                 schedule: FaultSchedule | None = None) -> None:
        """Seed the store and its failure schedule.

        @param entries the entries it starts with
        @param schedule which `delete` calls fail; healthy when omitted
        """
        ## Current entries keyed by their unique repository-relative path.
        self._entries = {  # Collapse duplicates into the path-identity boundary.
            entry.path: entry for entry in entries
        }
        ## Deterministic deletion indexes at which the fake raises.
        self._schedule = (  # Resolve omission to the explicit healthy schedule.
            schedule if schedule is not None else FaultSchedule.healthy()
        )
        ## Number of deletion calls already attempted against this fake.
        self._deletes = 0  # Start the one-based fault index before any deletion.

    def entries(self) -> Sequence[Entry]:
        """Every entry held, in path order.

        @return the entries, empty when the store is empty
        """
        # Project each indexed entry into deterministic ascending path order.
        return [self._entries[path] for path in sorted(self._entries)]

    def delete(self, path: str) -> None:
        """Remove one entry, unless this call is scheduled to fail.

        A scheduled failure happens **before** the removal, so the entry is still
        present afterwards. That is what makes the interrupted state reproducible
        rather than ambiguous.

        @param path the entry to remove
        @throws StoreUnavailable when the schedule names this call, or when no
            entry has that path
        @par Effects
        Increments the deletion-attempt counter and removes the entry only when
        neither scheduled failure nor absence interrupts the call.
        """
        # Advance the deterministic attempt index before any scheduled outcome.
        self._deletes += 1
        if self._schedule.fails(self._deletes):
            # Surface the injected failure before altering the indexed contents.
            raise StoreUnavailable(StoreOperation.DELETE, self._schedule.detail)
        # Preserve explicit absence failure instead of treating it as completed work.
        if path not in self._entries:
            # Retain the missing path in the stable port error representation.
            message = f"no entry at {path}"
            raise StoreUnavailable(StoreOperation.DELETE, message)
        # Remove the validated entry after every earlier failure point has passed.
        del self._entries[path]
