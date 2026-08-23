"""The domain's own error family, and nothing that can be raised from elsewhere.

`ERR-004` requires that a layer produce only its own errors, which is what makes
the `layer` field of a diagnostic envelope derivable rather than guessed. A
`DomainError` therefore means one thing: a logic defect or a violated invariant.
It can never mean the disk was full.

These are *raised* errors, for the exceptional. The expected outcomes of planning
are carried in the result union instead -- see `refpkg.domain.result` and
`ERR-001`, which admits exactly two propagation channels.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base of the domain's error family; never raised directly.

    Every subclass carries a stable, namespaced code and the values that
    provoked it as attributes, so a handler can compare `expected` against
    `actual` rather than parsing a sentence (`DIAG-002`, `DIAG-003`).
    """

    ## Namespaced, greppable, and part of the published surface: renaming one is
    ## a breaking change (`DIAG-004`, `API-011`).
    code: str = "refpkg.domain.error"
    ## Each rule identifier a domain failure defends, ordered by error-family
    ## ownership before total-function behavior. Carried into the envelope so
    ## the failure names its own contract (`DIAG-001`).
    rule_ids: tuple[str, ...] = ("ERR-004", "ARCH-006")

    def __init__(self, message: str) -> None:
        """Record the rendered message.

        @param message the human-readable rendering; the structured values live
            on the subclass as attributes
        """
        super().__init__(message)


class InvariantViolated(DomainError):
    """A value reached the domain that its own constructor should have refused.

    Raised rather than returned because it is not an outcome a caller can
    sensibly handle: it means something upstream skipped a parsing boundary
    (`ERR-011`), and the fix is in that boundary and not here.
    """

    ## Distinguishes this arm from every other in the family.
    code = "refpkg.domain.invariant_violated"
    ## Each defended rule identifier, ordered from contract violation to layer
    ## totality; this is not an unordered classification set.
    rule_ids: tuple[str, ...] = ("ERR-014", "ARCH-006")

    def __init__(self, invariant: str, actual: object) -> None:
        """Record which invariant failed and what was seen instead.

        @param invariant the predicate that was supposed to hold
        @param actual the offending value, as received
        """
        super().__init__(f"{invariant}; got {actual!r}")
        ## Human-readable predicate that the rejected value violated.
        self.invariant = invariant  # Preserve the exact predicate for structured handling.
        ## Original value that failed the predicate.
        self.actual = actual  # Preserve the rejected representation without string parsing.
