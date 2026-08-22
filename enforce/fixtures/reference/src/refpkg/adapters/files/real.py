"""The real file store: the one module in this package that touches a disk.

`ARCH-020` -- filesystem effects are owned by this adapter boundary. Every
`OSError` the platform can raise is caught here and
translated into `StoreUnavailable` before it crosses inward (`ERR-004`), with
`raise ... from` so the original cause survives in the chain (`DIAG-005`).

Entries are reported by **name**, and `delete` resolves a name against the root
this store was bound to. The first version returned absolute paths and took them
back unresolved, so `delete` never read the store's own root -- the store was not
a boundary at all, only a namespace over whatever path it was handed. A lint
finding is what noticed: `PLR6301` observed that the method never used `self`,
which here named a design fault rather than a style preference.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from refpkg.domain.model import Entry, Instant
from refpkg.ports.errors import StoreOperation, StoreUnavailable

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


class LocalFileStore:
    """A store over one directory, listing its files and deleting them."""

    def __init__(self, root: Path) -> None:
        """Bind the store to a directory.

        @param root the directory whose files this store reports; not read until
            a call is made, so constructing one cannot fail
        """
        self._root = root

    def entries(self) -> Sequence[Entry]:
        """Every regular file directly under the root, by name, in path order.

        Subdirectories are not descended into: the contract is a flat store, and
        recursing would make `delete` mean something the port never promised.

        @return the entries, empty when the directory holds no regular file
        @throws StoreUnavailable when the directory cannot be listed
        """
        try:
            found = sorted(p for p in self._root.iterdir() if p.is_file())
            return [
                Entry(
                    path=path.name,
                    size_bytes=path.stat().st_size,
                    modified_at=Instant(max(0, int(path.stat().st_mtime))),
                )
                for path in found
            ]
        except OSError as exc:
            message = f"cannot list {self._root}: {exc}"
            raise StoreUnavailable(StoreOperation.ENTRIES, message) from exc

    def delete(self, path: str) -> None:
        """Remove one file, resolved against this store's root.

        @param path the entry's name, as reported by `entries`
        @throws StoreUnavailable when the name escapes the root, when the file is
            absent, or when it cannot be removed
        """
        target = (self._root / path).resolve()
        if target.parent != self._root.resolve():
            message = f"{path!r} resolves outside {self._root}"
            raise StoreUnavailable(StoreOperation.DELETE, message)
        try:
            target.unlink()
        except OSError as exc:
            message = f"cannot remove {path}: {exc}"
            raise StoreUnavailable(StoreOperation.DELETE, message) from exc
