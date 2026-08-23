"""The app layer's error family: orchestration failed, not logic and not I/O.

The third of the three families (`ERR-004`). An `AppError` means the sequence
could not be completed -- typically because an adapter refused partway through --
and it always carries the adapter error that caused it as `__cause__`, never
instead of it (`DIAG-005`).
"""

from __future__ import annotations


class AppError(Exception):
    """Base of the app family; never raised directly."""

    ## Namespaced and stable, like every other code in the package.
    code: str = "refpkg.app.error"
    ## The rules an app failure defends.
    rule_ids: tuple[str, ...] = ("ERR-004",)


class PruneInterrupted(AppError):
    """An apply stopped partway, leaving the store in a stated intermediate state.

    Carries what was already done, because that is the difference between a
    recoverable interruption and an unknown one. `EFCT-009` requires that what is
    not guaranteed be stated; this is where the fixture states it.
    """

    ## Distinguishes this arm from every other in the family.
    code = "refpkg.app.prune_interrupted"
    ## An interrupted multi-effect apply is exactly what `EFCT-007` journals
    ## and `EFCT-009` requires be stated rather than quietly hoped past.
    rule_ids: tuple[str, ...] = ("EFCT-007", "EFCT-009")

    def __init__(self, deleted: tuple[str, ...], remaining: tuple[str, ...]) -> None:
        """Record how far the apply got.

        @param deleted the paths already removed, in the order they were removed
        @param remaining the paths the plan named that are still present
        """
        super().__init__(
            f"apply stopped after {len(deleted)} deletion(s); "
            f"{len(remaining)} entr(ies) from the plan remain"
        )
        ## Paths already removed, in their execution order.
        self.deleted = deleted
        ## Planned paths that were not removed when execution stopped.
        self.remaining = remaining
