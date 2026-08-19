"""The benchmark reports a miss as a miss, and its subject stays frozen.

**Oracle: contract.** The harness is held against the properties that make a
measurement worth recording, and the defect set against the promise that it does
not grow.

A benchmark has two failure modes and both are quiet. It can report success it did
not earn — counting a defect as reached when the navigator returned nothing. And
its subject can drift, so a number that looks like progress is a different question
being asked. Neither shows up in the number itself.

`R` is deliberately not gated, so nothing else in the repository will notice if
this file stops being true. That makes these tests the only thing standing behind
it.

    pytest tools/test_bench.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import bench
import defects

if TYPE_CHECKING:
    import pytest

## The size the frozen set was recorded at. This number is allowed to change only
## when a deliberate decision is taken to re-baseline the whole benchmark, and a
## test failing here is the prompt to have that conversation rather than to edit
## the expectation.
FROZEN_SIZE: Final = 12


def test_the_defect_set_is_frozen() -> None:
    """A benchmark whose subject grows measures the subject, not the tooling.

    The cheapest way to improve `R` is to add defects the navigator already
    handles. This refuses that without a deliberate re-baseline.
    """
    assert len(defects.DEFECTS) == FROZEN_SIZE, (
        f"the frozen set holds {len(defects.DEFECTS)} defects, not {FROZEN_SIZE}. "
        f"Adding one changes the question `R` answers; if that is intended, move "
        f"FROZEN_SIZE and re-record the baseline in the same change."
    )


def test_every_defect_is_identified_and_sourced() -> None:
    """Each entry says what it is and where it came from.

    Every defect here is drawn from real code. An entry that cannot name its
    origin is one somebody invented to be easy, which is how a benchmark stops
    resembling the work.
    """
    seen: set[str] = set()
    for defect in defects.DEFECTS:
        assert defect.defect_id not in seen, f"{defect.defect_id} appears twice"
        seen.add(defect.defect_id)
        assert defect.governs, f"{defect.defect_id} names no governing rule"
        assert len(defect.source) > 40, (
            f"{defect.defect_id} does not say where it came from"
        )
        assert defect.output.strip(), f"{defect.defect_id} carries no output"


def test_the_derived_set_is_the_larger_half() -> None:
    """The measurement is the outputs that name no rule.

    An output quoting `ARCH-002` resolves by string match and measures nothing.
    If the control set ever outgrew the derived one, `R` would mostly be
    reporting that string matching works.
    """
    assert len(defects.derived()) > len(defects.control()), (
        "the control set is no longer the smaller half; R would be measuring "
        "quoted-id lookup rather than derivation"
    )


def test_a_defect_that_reaches_nothing_is_reported_as_a_miss() -> None:
    """The failure mode that would make every number a lie.

    A harness that counted an empty plan as a hit would report a rising `R` while
    the navigator answered nothing at all. Driven with an output no trigger can
    possibly match.
    """
    nowhere = defects.Defect(
        defect_id="D-00",
        summary="an output nothing in the corpus indexes",
        source="A synthetic miss, so the harness is watched reporting one.",
        output="qzzx: unrecognisable output from a tool that does not exist",
        governs=("ARCH-002",),
    )
    result = bench.measure(nowhere)
    assert result["found"] is False
    assert result["hops"] is None


def test_a_defect_that_names_its_rule_is_reached(monkeypatch: pytest.MonkeyPatch) -> None:
    """The positive case: a quoted id resolves at zero hops.

    Asserted so a wholesale navigator failure is distinguishable from the derived
    set getting harder -- which is the reason the control set exists at all.

    @param monkeypatch unused; present so the signature matches the suite's shape
    """
    del monkeypatch
    result = bench.measure(defects.control()[0])
    assert result["found"] is True
    assert result["hops"] == bench.NAMED_OUTRIGHT


def test_the_summary_keeps_the_two_sets_apart() -> None:
    """Averaging the control set into the derived one would flatter the result.

    Four trivially-resolved outputs carrying eight hard ones is exactly how a
    benchmark reports progress it has not made.
    """
    summary = bench.summarize([
        {"defect": "a", "names_a_rule": False, "found": False, "hops": None,
         "tokens": 0, "summary": ""},
        {"defect": "b", "names_a_rule": True, "found": True, "hops": 0,
         "tokens": 100, "summary": ""},
    ])
    assert summary["derived"]["found"] == 0      # type: ignore[index]
    assert summary["control"]["found"] == 1      # type: ignore[index]
