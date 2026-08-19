"""The composition root: the only module in `refpkg` that names a concrete adapter.

`ARCH-011`. Replaceability that requires edits in several places is not
replaceability, and the single root is what makes substituting a fake in a test
identical to substituting one in production -- the same function, a different
argument.

Grep for `SystemClock` or `LocalFileStore` anywhere else under `src/` and the
answer should be nothing. That is the property `check:single_wiring_point` exists
to hold.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from refpkg.adapters.clock.real import SystemClock
from refpkg.adapters.files.real import LocalFileStore

if TYPE_CHECKING:
    from pathlib import Path

    from refpkg.ports.clock import Clock
    from refpkg.ports.files import FileStore


@dataclass(frozen=True, slots=True)
class Wiring:
    """The ports an operation needs, already bound to implementations.

    Passed as one value rather than as loose arguments so that adding a port
    changes one signature instead of every call site.
    """

    ## Where entries are read from and deleted.
    store: FileStore
    ## What the age policy is measured against.
    clock: Clock


def production(root: Path) -> Wiring:
    """The wiring a real run uses.

    @param root the directory the store is bound to
    @return the wiring, with every port bound to its real adapter
    """
    return Wiring(store=LocalFileStore(root), clock=SystemClock())
