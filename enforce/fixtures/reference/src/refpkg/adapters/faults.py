"""Fault injection as data, so a failure mode is a value and not a subclass.

`TEST-009` requires this shape. The alternative -- a bespoke `ClockThatFailsOnce`
class per scenario -- puts the interesting part of a fault test in a class name,
where it cannot be enumerated, parameterised or compared. A schedule is a value:
a test can build one from a table, print it in a failure message, and generate it.

A schedule says *which call fails*, counting from one, and nothing else. Ordering
by call index rather than by wall time is what keeps a fault test deterministic
(`EFCT-003`); a fault that arrives "after 50ms" is a fault that arrives somewhere
else on a slower machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class FaultSchedule:
    """Which calls to a faulty adapter fail, and what they report when they do.

    An empty schedule is the healthy case, which is deliberate: `TEST-020`
    requires the shared contract suite to run against the faulty adapter *in
    healthy mode*, and that is only possible if healthy is a configuration of the
    same object rather than a different object.
    """

    ## Each one-based call index that fails; membership is deliberately unordered.
    ## A call not named here succeeds. Held as a frozenset so equal schedules compare equal.
    ## The factory is subscripted because a bare `frozenset` gives pyright a
    ## `frozenset[Unknown]` to infer from, and an element type nobody knows is
    ## the hole `TYPE-001` exists to close.
    failing_calls: frozenset[int] = field(default_factory=frozenset[int])
    ## What a failing call reports as its detail, carried into the resulting
    ## error so a fault test can assert on the message it engineered.
    detail: str = "injected fault"

    @classmethod
    def healthy(cls) -> FaultSchedule:
        """A schedule under which nothing fails.

        @return the empty schedule
        """
        # Construct the canonical empty, deliberately unordered failure set.
        return cls()

    @classmethod
    def failing_on(cls, *calls: int, detail: str = "injected fault") -> FaultSchedule:
        """A schedule failing exactly the named calls.

        @param calls the one-based call indices that fail
        @param detail what each failing call reports
        @return the schedule
        """
        # Collapse the named indices into unordered membership with one shared detail.
        return cls(failing_calls=frozenset(calls), detail=detail)

    def fails(self, call_index: int) -> bool:
        """Whether the call at this index is scheduled to fail.

        @param call_index the one-based index of the call about to be made
        @return True when this call must fail
        """
        # Decide the deterministic outcome by membership rather than elapsed time.
        return call_index in self.failing_calls
