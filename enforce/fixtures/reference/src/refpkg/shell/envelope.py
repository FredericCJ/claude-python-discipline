"""Turning an escaping error into the diagnostic envelope, at the one boundary.

`DIAG-001`: every error reaching a process boundary serializes to a record
conforming to `enforce/schema/diagnostic.schema.json`. This is the whole thesis
made concrete -- the record names what broke, where, against which contract, with
which value, and what to do, so an agent meeting the failure can act without
reading this source.

The `layer` field is *derived from the error's family*, not passed in. That is
only possible because `ERR-004` holds: each layer produces its own errors, so the
type of the exception determines where it came from. If the families were mixed
this function would have to guess, and the field would be worth nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from refpkg.app.errors import AppError, PruneInterrupted
from refpkg.domain.errors import DomainError, InvariantViolated
from refpkg.ports.errors import PortError

if TYPE_CHECKING:
    from refpkg.domain.plan import Refusal

## Which family means which layer. The mapping is exhaustive over the three
## families the package defines; anything else is an escape the shell did not
## anticipate, and is reported as such rather than silently attributed.
_LAYER_OF: dict[type[Exception], str] = {
    DomainError: "domain",
    AppError: "app",
    PortError: "adapter",
}


def layer_of(error: BaseException) -> str:
    """Which layer an error came from, derived from its family.

    @param error the escaping exception
    @return the canonical layer name, or `shell` for anything outside the three
        families -- an unattributed error is reported honestly, never guessed
    """
    for family, layer in _LAYER_OF.items():
        if isinstance(error, family):
            return layer
    return "shell"


def causes(error: BaseException) -> list[dict[str, str]]:
    """The `__cause__` chain, innermost first.

    @param error the escaping exception
    @return one record per chained cause; empty when nothing was chained, which
        is a claim that nothing was, not that nobody looked
    """
    chain: list[dict[str, str]] = []
    current = error.__cause__
    while current is not None:
        chain.append({
            "type": type(current).__name__,
            "message": str(current),
            "code": getattr(current, "code", ""),
            "layer": layer_of(current),
        })
        current = current.__cause__
    chain.reverse()
    return chain


def from_error(error: BaseException) -> dict[str, Any]:
    """Serialize an escaping error to the diagnostic envelope.

    @param error the exception about to leave the process
    @return a record conforming to the published schema
    """
    layer = layer_of(error)
    envelope: dict[str, Any] = {
        "code": getattr(error, "code", "refpkg.shell.unexpected"),
        "layer": layer,
        "expected": _expected(error),
        "actual": str(error),
        "cause_chain": causes(error),
        "notes": list(getattr(error, "__notes__", [])),
        "remediation": _remediation(error),
        # The field that turns a diagnosis into a lookup. An error family says
        # which contracts it defends; carrying that outward is what lets a
        # consumer -- `python -m nav diagnose`, or a person -- go straight to the
        # rule instead of inferring it from a message.
        "rule_ids": list(getattr(error, "rule_ids", ())),
    }
    if isinstance(error, PortError):
        # The schema requires both of these for an adapter fault, and only an
        # adapter knows them; deriving them further out would be inventing them.
        envelope["port"] = error.port
        envelope["operation"] = error.operation
    if isinstance(error, InvariantViolated):
        envelope["value"] = repr(error.actual)
    return envelope


def from_refusal(refusal: Refusal) -> dict[str, Any]:
    """Serialize a domain refusal, which is a result rather than an exception.

    A refusal escaping the process must produce the same record shape as a raised
    error, because a consumer parsing the envelope should not have to know which
    of the two channels (`ERR-001`) the failure travelled on.

    @param refusal the planner's refusal
    @return a record conforming to the published schema
    """
    return {
        "code": refusal.code,
        "layer": "domain",
        "expected": refusal.expected,
        "actual": refusal.actual,
        "cause_chain": [],
        "notes": [],
        "remediation": "Correct the input the planner refused, then re-run.",
    }


def _expected(error: BaseException) -> str:
    """The predicate the error says was violated.

    @param error the escaping exception
    @return the predicate, phrased so it can be compared against `actual`
    """
    if isinstance(error, InvariantViolated):
        return error.invariant
    if isinstance(error, PruneInterrupted):
        return "every entry named by the plan was deleted"
    if isinstance(error, PortError):
        return f"{error.port}.{error.operation} completed"
    return "the operation completed"


def _remediation(error: BaseException) -> str:
    """One line the reader can act on.

    The field that makes the envelope machine-*repairable* and not merely
    machine-diagnosable; without it the record says what broke and leaves the
    next step to be inferred.

    @param error the escaping exception
    @return the remediation line
    """
    if isinstance(error, PruneInterrupted):
        return (
            f"{len(error.deleted)} deletion(s) already happened and are not undone. "
            f"Re-run to retry the {len(error.remaining)} that remain."
        )
    if isinstance(error, PortError):
        return f"Check the {error.port} adapter's dependency, then re-run."
    if isinstance(error, DomainError):
        return "Fix the value at the boundary that admitted it; the domain is not at fault."
    return "Unhandled at the shell boundary; this is a defect in refpkg."
