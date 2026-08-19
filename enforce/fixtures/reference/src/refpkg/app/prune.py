"""Orchestration: scan, plan, and -- only if asked -- apply.

Every effect this module performs arrives as a parameter (`ARCH-005`,
`EFCT-002`). It imports no adapter and names no concrete class; it knows a
`Clock` and a `FileStore` by their contracts alone, which is what lets the whole
pipeline run against the in-memory store with the destructive step intact.

**The dry run is this pipeline truncated, not a second path** (`EFCT-006`).
`survey` computes the plan. `apply` takes a plan `survey` produced and performs
it. A caller wanting a dry run calls the first and stops, so what it reports is
by construction what an apply would do -- there is no second implementation to
drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from refpkg.app.errors import PruneInterrupted
from refpkg.domain.plan import Outcome, Plan, plan_prune
from refpkg.ports.errors import PortError

if TYPE_CHECKING:
    from refpkg.domain.model import Policy
    from refpkg.ports.clock import Clock
    from refpkg.ports.files import FileStore


def survey(store: FileStore, clock: Clock, policy: Policy) -> Outcome:
    """Read the store and compute what a prune would do. Changes nothing.

    @param store where the entries are read from
    @param clock what the age policy is measured against
    @param policy what the caller considers stale
    @return the plan, or the domain's refusal to produce one
    @throws PortError when the store cannot be listed or the clock read; both
        are left to propagate, because the caller's boundary is where an error is
        logged and rendered, not here (`DIAG-010`)
    """
    entries = store.entries()
    now = clock.now()
    return plan_prune(entries, policy, now)


def apply(store: FileStore, plan: Plan) -> tuple[str, ...]:
    """Perform a plan, deleting each doomed entry in turn.

    Deletions happen in plan order and the progress is accumulated as it goes, so
    an interruption reports exactly how far it got rather than leaving the store
    in a state nobody can describe (`EFCT-007`, `EFCT-009`).

    @param store the store to delete from
    @param plan a plan produced by `survey` against this same store
    @return the paths deleted, in the order they were deleted
    @throws PruneInterrupted when a deletion fails partway, carrying what was
        already done and what remains
    """
    deleted: list[str] = []
    for entry in plan.doomed:
        try:
            store.delete(entry.path)
        except PortError as exc:
            remaining = tuple(e.path for e in plan.doomed if e.path not in deleted)
            raise PruneInterrupted(tuple(deleted), remaining) from exc
        deleted.append(entry.path)
    return tuple(deleted)
