"""Deciding what to delete, as a total function over values.

This is the functional core. It performs no effect, reads no clock and opens no
file: the current instant and the entries are handed in, so the same inputs give
the same plan on every machine and in every replay (`EFCT-003`).

Its outcome is a discriminated union rather than an exception (`ARCH-006`,
`ERR-001`). A refusal is an expected result the caller must handle, not an
exceptional condition -- and `mypy --strict` will not let a caller forget an arm,
because `narrow` closes the union against `Never` (`ERR-002`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Never, TypeAlias

# Keep type-only port and value dependencies out of the runtime domain graph.
if TYPE_CHECKING:
    from collections.abc import Sequence

    from refpkg.domain.model import Entry, Instant, Policy

## Maximum entries accepted by one planning operation. This is both the input
## and worst-case destructive-cleanup work budget in operational-model.json.
MAX_PLAN_ENTRIES = 10_000


@dataclass(frozen=True, slots=True)
class Plan:
    """What a prune would do, computed and not yet performed.

    Held as a value so it can be shown to a person, compared against a later
    apply, or discarded -- which is what makes a dry run the same pipeline
    truncated rather than a second implementation (`EFCT-006`).
    """

    ## Each entry the policy condemns, ordered newest first so the least-obvious
    ## deletion appears at the top rather than buried.
    doomed: tuple[Entry, ...]
    ## Each spared entry, ordered newest first to mirror the condemned partition.
    kept: tuple[Entry, ...]

    @property
    def reclaimed_bytes(self) -> int:
        """How much space applying this plan would free.

        @return the total size of every doomed entry, zero for an empty plan
        """
        # Fold each condemned entry's byte count without changing plan order.
        return sum(entry.size_bytes for entry in self.doomed)


@dataclass(frozen=True, slots=True)
class Refusal:
    """The planner declining to produce a plan, with everything needed to fix it.

    Carries the same four fields the diagnostic envelope publishes -- code,
    expected, actual and the offending value -- because a refusal that escapes
    the process becomes one, and translating between two shapes at that boundary
    is where detail gets lost (`DIAG-003`).
    """

    ## Stable and namespaced, like every other code in the package.
    code: str
    ## The predicate that was violated, phrased so it can be compared to `actual`.
    expected: str
    ## What was seen instead.
    actual: str


## Every way planning can end. Closed on purpose: adding an arm here is a
## breaking change to the callers that narrow it (`ERR-005`, `API-011`).
Outcome: TypeAlias = Plan | Refusal


def plan_prune(entries: Sequence[Entry], policy: Policy, now: Instant) -> Outcome:
    """Decide which entries a policy condemns at a given moment.

    Total for its argument types: every combination either yields a plan or a
    refusal, and neither raises.

    @param entries each file under consideration; input order is deliberately irrelevant
    @param policy what the caller considers stale
    @param now the instant to measure age against, supplied rather than read
    @return the plan, or a refusal naming what made planning impossible
    """
    # Enforce the declared work bound before sorting or inspecting any entry.
    if len(entries) > MAX_PLAN_ENTRIES:
        # Return the expected input ceiling and the observed population together.
        return Refusal(
            code="refpkg.domain.plan_too_large",
            expected=f"at most {MAX_PLAN_ENTRIES} entries per plan",
            actual=f"{len(entries)} entries",
        )

    # Establish the one newest-first order used by every later partition.
    newest_first = sorted(entries, key=lambda e: e.modified_at.epoch_seconds, reverse=True)

    # Isolate each future-dated entry while preserving the established newest-first order.
    future = [e for e in newest_first if e.modified_at.epoch_seconds > now.epoch_seconds]
    if future:
        # Refuse the inconsistent time frame and identify its newest offending element.
        return Refusal(
            code="refpkg.domain.entry_from_the_future",
            expected="every entry was modified at or before the current instant",
            actual=f"{len(future)} entr(ies) are newer than now, the first being {future[0].path}",
        )

    # Partitioned by POSITION, not by value membership. The first version built
    # `kept` as "every entry not in `doomed`", which is wrong the moment two
    # entries are equal: one spared by `keep_newest` and an identical one past
    # the cutoff would make the spared copy test as `in doomed` and vanish from
    # `kept`. The property suite found it on a seed that generated a duplicate.
    # Nothing else would have -- the store cannot hold one path twice, so no
    # example anyone writes by hand exercises it.
    spared = newest_first[: policy.keep_newest]
    candidates = newest_first[policy.keep_newest :]
    cutoff = now.minus_days(policy.max_age_days)

    # Partition each candidate at the cutoff, preserving newest-first order in both results.
    doomed = tuple(e for e in candidates if e.modified_at.epoch_seconds < cutoff.epoch_seconds)
    surviving = tuple(
        e for e in candidates if e.modified_at.epoch_seconds >= cutoff.epoch_seconds
    )
    return Plan(doomed=doomed, kept=tuple(spared) + surviving)


def narrow(outcome: Never) -> Never:
    """Fail to compile if a new arm is added to `Outcome` and not handled.

    Called from the `else` of an exhaustive match. `mypy --strict` narrows the
    union to `Never` at that point, so this body is unreachable in a correct
    program and a type error in an incorrect one -- the whole value of a closed
    union, and the reason `ERR-002` asks for it.

    @param outcome the value the caller failed to handle
    @return never; it always raises
    @throws AssertionError always, if the impossible happens at runtime
    """
    # Render the impossible residual arm before terminating the runtime fallback.
    message = f"unhandled outcome arm: {outcome!r}"
    raise AssertionError(message)
