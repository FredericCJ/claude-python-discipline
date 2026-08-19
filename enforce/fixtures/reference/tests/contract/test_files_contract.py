"""Contract suite for the `FileStore` port, run unchanged against all three adapters.

**Oracle: the port's published contract** (`TEST-004`). Every assertion here
restates a clause from the docstring of `refpkg.ports.files`, including the ones
that are easy to get wrong in a fake -- path ordering, and deleting an absent
path being an error rather than a shrug.

The real adapter is bound to a `tmp_path`, which makes this layer touch the
filesystem. That is deliberate and is why these live under `contract/` and not
`unit/`: `TEST-001` keeps the unit layer pure, and a contract suite that must
also hold the real adapter cannot be.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from refpkg.adapters.faults import FaultSchedule
from refpkg.adapters.files.fake import MemoryFileStore
from refpkg.adapters.files.faulty import FaultyFileStore
from refpkg.adapters.files.real import LocalFileStore
from refpkg.domain.model import Entry, Instant
from refpkg.ports.errors import StoreUnavailable
from refpkg.ports.files import FileStore

if TYPE_CHECKING:
    from pathlib import Path

## Two entries, deliberately seeded out of path order so a store that returns
## insertion order instead of path order fails rather than passing by luck.
SEED: tuple[Entry, ...] = (
    Entry(path="b.log", size_bytes=20, modified_at=Instant(1_700_000_100)),
    Entry(path="a.log", size_bytes=10, modified_at=Instant(1_700_000_000)),
)


@pytest.fixture(params=["real", "fake", "faulty-healthy"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> FileStore:
    """One adapter under test, seeded with the same two entries.

    @param request pytest's request object, carrying the parameter
    @param tmp_path a directory for the real adapter to be bound to
    @return a freshly constructed adapter holding `SEED`
    """
    if request.param == "real":
        for entry in SEED:
            (tmp_path / entry.path).write_bytes(b"x" * entry.size_bytes)
        return LocalFileStore(tmp_path)
    if request.param == "fake":
        return MemoryFileStore(SEED)
    return FaultyFileStore(SEED, FaultSchedule.healthy())


def names(store: FileStore) -> list[str]:
    """The store's entries, in the order it reported them.

    Every adapter reports bare names -- the real one resolves them against its
    own root -- so this suite compares what the contract is actually about:
    order and membership. It used to strip a path prefix here, which was the
    suite quietly compensating for an adapter that leaked absolute paths.

    @param store the adapter under test
    @return each entry's path, in the order the store reported them
    """
    return [entry.path for entry in store.entries()]


def test_it_satisfies_the_protocol(store: FileStore) -> None:
    """Structural conformance, checked at runtime as well as by the checker.

    @param store the adapter under test
    """
    assert isinstance(store, FileStore)


def test_entries_are_returned_in_path_order(store: FileStore) -> None:
    """The contract's ordering clause, which the seed is arranged to catch.

    @param store the adapter under test
    """
    assert names(store) == ["a.log", "b.log"]


def test_entries_is_stable_between_calls(store: FileStore) -> None:
    """Two calls with no intervening change agree.

    @param store the adapter under test
    """
    assert names(store) == names(store)


def test_delete_removes_exactly_one_entry(store: FileStore) -> None:
    """The deletion clause: one entry goes, the rest stay.

    @param store the adapter under test
    """
    target = store.entries()[0]
    store.delete(target.path)
    assert names(store) == ["b.log"]


def test_deleting_an_absent_path_is_an_error(store: FileStore) -> None:
    """A store that shrugs cannot report what a plan actually did.

    @param store the adapter under test
    """
    with pytest.raises(StoreUnavailable):
        store.delete("no-such-entry.log")
