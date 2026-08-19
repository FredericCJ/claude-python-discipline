"""The failure modes the ports publish, declared with the contracts they belong to.

These lived under `adapters/` until the architecture contracts were run against
this package for the first time, and `ARCH-001` immediately caught what that
implied: `app.prune` has to catch an adapter failure to report an interrupted
apply, so it was importing `refpkg.adapters` -- an outward import, from a layer
that is supposed to know nothing about implementations.

The import was a symptom. `ARCH-007` requires a port to state its **error modes**
alongside its inputs and outputs, which means a failure type is part of the
contract and not of any one implementation of it. Declared here, every adapter
raises the same type and the core catches it without knowing that adapters exist.

`ERR-004` still holds and is what makes the envelope's `layer` field derivable:
an error of this family means *an adapter failed*, whichever adapter it was.
Ports sit outside the layer stack precisely so both sides may name them.
"""

from __future__ import annotations

from enum import StrEnum


class StoreOperation(StrEnum):
    """The calls the `FileStore` contract publishes.

    A closed set, so it is an enumeration and not a string (`TYPE-006`). It began
    as a literal passed at each raise site, which `EM101` flagged as a message --
    correctly, in the sense that a bare literal in an exception call is usually
    prose. Here it was a structured field, and the fix `DIAG-003` implies is to
    make it a value with a type rather than to suppress the finding.
    """

    ## Listing the store's contents.
    ENTRIES = "entries"
    ## Removing one entry.
    DELETE = "delete"


class PortError(Exception):
    """Base of the failure modes a port publishes; never raised directly.

    Every subclass carries the port and the operation being attempted, because
    those are two of the fields the diagnostic envelope publishes for an adapter
    fault and nothing further out has the context to supply them (`DIAG-003`).
    """

    ## Namespaced, greppable, and part of the published surface (`DIAG-002`).
    code: str = "refpkg.port.error"
    ## The rules this family defends, carried into the envelope so a consumer --
    ## or an agent -- can go from the failure to the contract it broke without
    ## guessing. `DIAG-001`'s envelope has carried a `rule_ids` field since it was
    ## published; until something populated it, the field was specified, shipped
    ## and dead, and the last hop of the Prime Directive stayed manual.
    rule_ids: tuple[str, ...] = ("ERR-004", "ARCH-008")

    def __init__(self, port: str, operation: str, detail: str) -> None:
        """Record which contract was crossed, doing what, and what went wrong.

        @param port the port whose contract was being honoured
        @param operation the call on that contract
        @param detail what the underlying dependency reported
        """
        super().__init__(f"{port}.{operation}: {detail}")
        self.port = port
        self.operation = operation
        self.detail = detail


class ClockUnavailable(PortError):
    """No reading could be taken from the clock."""

    ## Distinguishes this arm from every other in the family.
    code = "refpkg.port.clock_unavailable"

    def __init__(self, detail: str) -> None:
        """Record why the clock could not be read.

        @param detail what the underlying source reported
        """
        super().__init__("Clock", "now", detail)


class StoreUnavailable(PortError):
    """The file store could not be read, or an entry could not be removed."""

    ## Distinguishes this arm from every other in the family.
    code = "refpkg.port.store_unavailable"

    def __init__(self, operation: StoreOperation, detail: str) -> None:
        """Record which store operation failed and why.

        @param operation the call on the contract
        @param detail what the underlying store reported
        """
        super().__init__("FileStore", str(operation), detail)
