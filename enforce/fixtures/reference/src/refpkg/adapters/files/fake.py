"""The in-memory file store: the whole destructive pipeline, with nothing at risk.

This is what makes a deletion path testable. `LocalFileStore` can only be
exercised against a real directory; this one runs the same orchestration, through
the same contract, and the worst outcome of a defect is a wrong dictionary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from refpkg.ports.errors import StoreOperation, StoreUnavailable

# Keep iterable and domain entry contracts type-only in the concrete adapter.
if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from refpkg.domain.model import Entry


class MemoryFileStore:
    """A store holding its entries in a dictionary."""

    def __init__(self, entries: Iterable[Entry] = ()) -> None:
        """Seed the store.

        @param entries the entries it starts with; duplicates by path collapse,
            since a store cannot hold one path twice
        """
        # Collapse each seed entry into a unique path index; input order is not retained.
        self._entries = {entry.path: entry for entry in entries}  ##< Current entries by path.

    def entries(self) -> Sequence[Entry]:
        """Every entry held, in path order.

        @return the entries, empty when the store is empty
        """
        # Project each indexed entry into deterministic ascending path order.
        return [self._entries[path] for path in sorted(self._entries)]

    def delete(self, path: str) -> None:
        """Remove one entry.

        @param path the entry to remove
        @throws StoreUnavailable when no entry has that path -- a store that
            shrugs at a missing path cannot report what a plan actually did
        @par Effects
        Removes exactly one indexed entry after presence validation.
        """
        # Refuse a path whose absence would make deletion progress unknowable.
        if path not in self._entries:
            # Preserve the missing identity in the store-port diagnostic.
            message = f"no entry at {path}"
            raise StoreUnavailable(StoreOperation.DELETE, message)
        # Remove the validated member from the externally visible store contents.
        del self._entries[path]
