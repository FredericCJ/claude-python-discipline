"""A dispatch records its score, its allocation and the contract it hands over.

Enforces `ALLOC-002` (the seven signal scores, the resulting allocation, any
override, and a rationale where the two differ), `ALLOC-003` (named categories
force escalation), `ALLOC-004` (a single signal at 3 raises the floor),
`ALLOC-005` to `ALLOC-009` (the escalation and coordination rules the record
makes auditable), and `TEAMS-001` and `TEAMS-002` (a dispatch states a contract,
and a restriction is not lifted by an instruction).

**Why a text check.** A dispatch record is markdown -- an agent definition, not
Python. Ten binding rules were unmechanizable purely because the check framework
could only parse source. They are not rules about source.

**What this decides and what it does not.** It decides that the record exists and
is complete: seven signals, a total, an allocation, a stated contract, and the
standing restrictions. It decides the two arithmetic escalations -- a signal at 3
forcing `E2`, and a named category forcing `T2`. It cannot decide `ALLOC-006`
through `ALLOC-009`, which are about what the coordinator did *before* writing
the record: whether the contract was sharpened before the tier was raised,
whether the work was split before being upgraded, and who owned a
misclassification. Those remain judgement. What the record does is make them
auditable after a failure, which is the only moment the classification's quality
can actually be assessed -- and that is why the recording obligation is the part
worth mechanizing.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from . import Finding, TextCheck, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Path segment that marks a file as a dispatch record. A check cannot guess
## which markdown is a dispatch, so the convention is the directory.
DISPATCH_DIR = "agents"

## The score at which one signal alone raises the effort floor (`ALLOC-004`).
MAX_SIGNAL = 3

## The capability tier a named escalation category forces (`ALLOC-003`).
TOP_TIER = 2

## Signal-name elements in canonical scoring order, each ranging from zero through three.
SIGNALS: tuple[str, ...] = ("A", "B", "C", "D", "E", "F", "G")

## One signal and its score, as a record writes them: `A=2`.
_SCORE = re.compile(r"\b(?P<signal>[A-G])\s*=\s*(?P<value>[0-3])\b")

## The allocation: a capability tier and an effort tier.
_ALLOCATION = re.compile(r"\bT(?P<tier>[0-2])\s*/\s*E(?P<effort>[0-2])\b")

## A tier or an effort named anywhere in the record. Both are read separately and
## taken at their MAXIMUM, because a conformant record states the mechanical
## result and then the escalation that overrides it -- "12/21 -> T1/E1, floor
## raised to E2 by ALLOC-004". Reading only the first allocation reported three
## correct records as under-allocated on this check's first run, and the bare
## `E2` in that sentence is not in `T/E` form at all. The word boundary is what
## keeps `E=2`, a signal score, from being read as an effort tier.
_TIER = re.compile(r"\bT([0-2])\b")
## The effort tier, read separately from the capability tier and for the same
## reason: an escalation may raise one without restating the other.
_EFFORT = re.compile(r"\bE([0-2])\b")

## The total out of 21, which a reader checks the arithmetic against.
_TOTAL = re.compile(r"\b(?P<total>\d{1,2})\s*/\s*21\b")

## Mapping from each trigger-phrase key to its escalation-rationale value; insertion order is
## deterministic match precedence when several categories appear.
ESCALATING = {
    "published contract": "changing a published contract",
    "supply chain": "anything touching the supply chain",
    "adversarial verification": "the adversarial verification before a change lands",
    "irreversible": "designing an irreversible or destructive operation",
    "destructive": "designing an irreversible or destructive operation",
    "arbitration": "arbitration between conflicting positions",
    "root-cause": "root-cause analysis after a defect escaped",
    "security": "anything touching security",
}

## The heading a dispatch uses to state what it hands over, rather than what it
## hopes for. `TEAMS-001`: a dispatch states the contract, not the intention.
_CONTRACT = re.compile(r"\bcontract\b", re.IGNORECASE)

## Evidence that the standing restrictions were carried over rather than assumed.
_RESTRICTIONS = re.compile(r"\brestrictions?\b", re.IGNORECASE)


class DispatchRecordedCheck(TextCheck):
    """Reports a dispatch whose record is absent, incomplete or self-contradictory."""

    ## Invoked as `python -m checks.dispatch_recorded`.
    name = "dispatch_recorded"
    ## The ops/ALLOC and ops/teams rules this check decides.
    ## Narrowed to what this check can actually REPORT. ALLOC-005 through ALLOC-009
    ## were named here and never emitted, so they counted as `mechanized` while
    ## being decided by nothing -- and this module's own docstring said so in
    ## prose. `V080` rises as a result, which is the true number.
    ## Rule-id elements in deterministic reporting order actually decided here.
    rules = ("ALLOC-002", "ALLOC-003", "ALLOC-004", "TEAMS-001", "TEAMS-002")
    ## File-suffix elements in deterministic matching order for Markdown dispatch records.
    suffixes = (".md",)

    def visit_text(self, text: str, path: Path) -> Iterator[Finding]:
        """Yield findings for one dispatch record.

        @param text the file's contents
        @param path the file it was read from
        @return finding elements in score, allocation, total, contract, and restriction order
        """
        # Only Markdown beneath the conventional agents directory is a dispatch record.
        if DISPATCH_DIR not in path.parts:
            # Stop iteration without treating unrelated prose as an incomplete dispatch.
            return

        # Map each scored signal-name key to its integer value in first-match order.
        scores = {m.group("signal"): int(m.group("value")) for m in _SCORE.finditer(text)}
        # Preserve canonical signal order while collecting each missing score element.
        missing = [s for s in SIGNALS if s not in scores]
        # Incomplete scoring makes the mechanical allocation unauditable.
        if missing:
            # Yield one aggregate missing-score finding in canonical signal order.
            yield Finding(
                "ALLOC-002", path, 1,
                f"dispatch record scores {len(scores)} of 7 signals; missing "
                f"{', '.join(missing)}",
                "Score all seven (A determinism, B specification, C blast radius, "
                "D failure visibility, E context breadth, F novelty, G specialist "
                "competence). An unrecorded allocation cannot be audited after a "
                "failure, which is the only moment its quality can be assessed.",
            )

        # Locate at least one complete capability/effort allocation spelling.
        allocation = _ALLOCATION.search(text)
        # Absence prevents escalation arithmetic from having a declared base allocation.
        if allocation is None:
            # Yield the missing-allocation finding at the record head.
            yield Finding(
                "ALLOC-002", path, 1,
                "dispatch record states no allocation",
                "State the resulting tier and effort as `T<n>/E<n>`.",
            )
        # A declared allocation can be checked against arithmetic and category floors.
        else:
            # Yield any escalation findings after structural score/allocation defects.
            yield from self._escalations(text, path, scores)

        # A scored dispatch must state its independently checkable total out of 21.
        if _TOTAL.search(text) is None and scores:
            # Yield the missing-total finding at the record head.
            yield Finding(
                "ALLOC-002", path, 1,
                "dispatch record states no total out of 21",
                "State the total, so a reader can check the arithmetic against "
                "the band the allocation claims.",
            )

        # Every dispatch must name a deliverable contract rather than only intention.
        if not _CONTRACT.search(text):
            # Yield the missing-contract finding at the record head.
            yield Finding(
                "TEAMS-001", path, 1,
                "dispatch states no contract",
                "Say what the agent must deliver, not what it should try to do. "
                "An intention cannot be verified; a contract can.",
            )

        # Every dispatch must carry standing restrictions into the delegated context.
        if not _RESTRICTIONS.search(text):
            # Yield the missing-restrictions finding at the record head.
            yield Finding(
                "TEAMS-002", path, 1,
                "dispatch states no standing restrictions",
                "Carry them explicitly. A restriction that is not written down is "
                "one an instruction can appear to lift.",
            )

    def _escalations(self, text: str, path: Path,
                     scores: dict[str, int]) -> Iterator[Finding]:
        """Report an allocation the escalation rules should have raised.

        The tier and the effort are each taken at their maximum over the whole
        record, so a record that states its mechanical result and then escalates
        is read at what it escalated to.

        @param text the file's contents, searched for escalating categories
        @param path the file it was read from
        @param scores mapping from each signal-name key to its score value; insertion order
            follows first textual match and is deliberately irrelevant to arithmetic
        @return finding elements in effort-floor then category-precedence order
        """
        # Select the highest capability tier mentioned anywhere in the record.
        tier = max((int(m) for m in _TIER.findall(text)), default=0)
        # Select the highest effort tier mentioned anywhere in the record.
        effort = max((int(m) for m in _EFFORT.findall(text)), default=0)

        # Any maximum signal score requires the top deliberative effort floor.
        if scores and max(scores.values()) == 3 and effort < 2:  # ruff: ignore[magic-value-comparison] - E2 is the ceiling
            # Sort each signal-name element scored at the maximum for deterministic wording.
            at_three = sorted(s for s, v in scores.items() if v == MAX_SIGNAL)
            # Yield the under-effort finding before category-based tier findings.
            yield Finding(
                "ALLOC-004", path, 1,
                f"signal {', '.join(at_three)} scores 3 but the effort is E{effort}",
                "A single signal at 3 raises the floor to E2. One dimension at its "
                "maximum is enough to make the work deliberative, whatever the total.",
            )

        # Normalize the complete record once for case-insensitive category matching.
        lowered = text.lower()
        # Inspect each trigger-phrase/rationale pair in declared precedence order.
        for phrase, category in ESCALATING.items():
            # Any named escalation category requires the highest capability tier.
            if phrase in lowered and tier < 2:  # ruff: ignore[magic-value-comparison] - T2 is the top tier
                # Yield one category escalation finding using its rationale value.
                yield Finding(
                    "ALLOC-003", path, 1,
                    f"the dispatch names {phrase!r} but allocates T{tier}",
                    f"{category.capitalize()} forces T2 regardless of score. A "
                    f"named category beats the mechanical permit (ALLOC-005).",
                )
                # Stop after the first declared trigger so one under-tier dispatch reports once.
                break


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(DispatchRecordedCheck()))
