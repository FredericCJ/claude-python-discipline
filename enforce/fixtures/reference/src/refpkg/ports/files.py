"""The file store port: listing, describing and deleting, behind one contract.

**Justification (`ARCH-010`): testing the core against a fake, fault injection,
and controlling a specific effect.** Deletion is irreversible, so the ability to
run the whole pipeline against an in-memory store is what makes the destructive
path testable at all; and a store that fails halfway through a deletion is the
case that decides whether `EFCT-007`'s journalling actually works.

Contract, enforced against every adapter by one shared suite (`ARCH-009`):

* `entries()` returns every entry currently in the store, in **path order**, so
  two calls with no intervening change return the same sequence.
* `delete(path)` removes exactly one entry and returns nothing. Deleting a path
  that is not present is an error, not a silent success -- a store that shrugs
  cannot report what a plan actually did.
* Both raise `StoreUnavailable` and nothing else.
* `delete` is **not** atomic across a sequence of calls, and the port says so
  rather than leaving it to be assumed (`EFCT-008`, `EFCT-009`): an interrupted
  run leaves some entries deleted and the rest present.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence

    from refpkg.domain.model import Entry


@runtime_checkable
class FileStore(Protocol):
    """A flat store of entries that can be listed and deleted one at a time."""

    def entries(self) -> Sequence[Entry]:
        """Every entry currently held, in path order.

        @return the entries, empty when the store holds none
        @throws StoreUnavailable when the store cannot be read
        """
        ...

    def delete(self, path: str) -> None:
        """Remove one entry.

        @param path the entry to remove, as reported by `entries`
        @throws StoreUnavailable when the entry is absent or cannot be removed
        """
        ...
