"""The `D` ratchet is watched failing in each of the ways it must.

**Oracle: differential.** The gate is driven over substituted tables whose outcome
is known, and its verdict compared.

`FLOW-007` asks every mechanism to be observed failing, and this one guards the
number that certifies all the others. A ratchet nobody has watched refuse
something is a ratchet that may only ever have said yes.

Three refusals matter, and the third is the subtle one:

* a declared mutation that does not provoke its rule — a broken claim;
* `D` falling — a mechanism that used to discriminate and stopped;
* **the conformant reference already reporting findings** — because then every
  "provoked" result is a finding the mutation did not earn, and the whole run is
  crediting mechanisms for noise.

    pytest tools/test_discrimination_gate.py
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import discrimination
import discrimination_gate

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

## A mutation known to provoke its rule: an undocumented function in the domain.
_WORKS = discrimination.Mutation(
    rule_id="DOC-001",
    summary="a public function carries no docstring",
    source=("A known-good entry, used here to prove the runner reports success "
            "when the claim holds rather than only when it fails."),
    replace=(("src/refpkg/domain/model.py",
              "from __future__ import annotations",
              ("from __future__ import annotations\n\n\n"
               "def undocumented(value: int) -> int:\n"
               "    return value")),),
)

## A mutation that changes nothing any check objects to, so the rule it claims
## will not fire. The claim is false and the gate must say so.
_HOLLOW = discrimination.Mutation(
    rule_id="ARCH-002",
    summary="a comment is added and nothing else",
    source="A deliberately false claim, so the runner is observed rejecting one.",
    replace=(("src/refpkg/domain/model.py",
              "from __future__ import annotations",
              "from __future__ import annotations\n\n# a comment"),),
)


def test_a_true_claim_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The positive case: a mutation that provokes its rule is counted.

    Asserted first, because a gate that fails on a correct claim is not stricter,
    it is broken, and every refusal below would then mean nothing.

    @param monkeypatch used to substitute the declared table
    """
    monkeypatch.setattr(discrimination, "MUTATIONS", (_WORKS,))
    status, complaints, provoked = discrimination_gate.run()
    assert status == discrimination_gate.EXIT_OK, complaints
    assert provoked == {"DOC-001"}


def test_a_claim_that_provokes_nothing_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mutation the mechanism does not catch is a broken claim, not a pass.

    @param monkeypatch used to substitute the declared table
    """
    monkeypatch.setattr(discrimination, "MUTATIONS", (_HOLLOW,))
    status, complaints, provoked = discrimination_gate.run()
    assert status == discrimination_gate.EXIT_FAILED
    assert provoked == set()
    assert "ARCH-002" in complaints[0]


def test_a_mutation_naming_a_missing_path_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An entry that has drifted from the fixture fails loudly.

    `broken_copy` raises rather than leaving the tree intact, so a stale entry
    cannot quietly assert against an unbroken package.

    @param monkeypatch used to substitute the declared table
    """
    stale = discrimination.Mutation(
        rule_id="DOC-001",
        summary="damage a file that is not there any more",
        source="Pins the drift case: an entry naming a path the reference no "
               "longer carries must fail rather than pass vacuously.",
        drop=("src/refpkg/domain/gone.py",),
    )
    monkeypatch.setattr(discrimination, "MUTATIONS", (stale,))
    status, complaints, _ = discrimination_gate.run()
    assert status == discrimination_gate.EXIT_FAILED
    assert "drifted" in complaints[0]


def test_a_dirty_reference_stops_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard that keeps every other result honest.

    If the conformant tree already reports findings, a mutation that "provokes"
    its rule may simply be seeing the pre-existing noise. The run stops rather
    than crediting mechanisms with findings they did not earn.

    @param monkeypatch used to make the reference look dirty
    """
    monkeypatch.setattr(discrimination_gate, "findings_for",
                        lambda *_args, **_kw: {"ARCH-002"})
    status, complaints, provoked = discrimination_gate.run()
    assert status == discrimination_gate.EXIT_FAILED
    assert provoked == set()
    assert "did not earn" in complaints[0]


def test_the_floor_may_not_fall(monkeypatch: pytest.MonkeyPatch,
                                tmp_path: Path) -> None:
    """A rule that used to discriminate and stopped fails the gate.

    @param monkeypatch used to substitute the table and the baseline path
    @param tmp_path holds a baseline claiming more coverage than the table gives
    """
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"count": 5, "rules": ["DOC-001", "ARCH-002", "ERR-013",
                                          "TYPE-002", "DIAG-002"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(discrimination_gate, "BASELINE_PATH", baseline)
    monkeypatch.setattr(discrimination, "MUTATIONS", (_WORKS,))
    assert discrimination_gate.main([]) == discrimination_gate.EXIT_FAILED


def test_the_floor_will_not_move_while_a_claim_is_broken(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`--update-baseline` refuses to record a floor over a failing table.

    Recording one would freeze a broken claim as the standard, which is how a
    ratchet stops meaning anything.

    @param monkeypatch used to substitute the table and the baseline path
    @param tmp_path holds the baseline that must not be written
    """
    baseline = tmp_path / "baseline.json"
    monkeypatch.setattr(discrimination_gate, "BASELINE_PATH", baseline)
    monkeypatch.setattr(discrimination, "MUTATIONS", (_HOLLOW,))
    assert discrimination_gate.main(
        ["--update-baseline", "--why", "should not be recorded"]
    ) == discrimination_gate.EXIT_FAILED
    assert not baseline.exists()


def test_moving_the_floor_requires_a_reason(monkeypatch: pytest.MonkeyPatch,
                                            tmp_path: Path) -> None:
    """A ratchet moved without a written reason is indistinguishable from drift.

    @param monkeypatch used to substitute the baseline path
    @param tmp_path holds the baseline that must not be written
    """
    baseline = tmp_path / "baseline.json"
    monkeypatch.setattr(discrimination_gate, "BASELINE_PATH", baseline)
    assert discrimination_gate.main(["--update-baseline"]) == \
        discrimination_gate.EXIT_FAILED
    assert not baseline.exists()


def test_the_committed_table_holds() -> None:
    """The real table, against the real reference, with nothing substituted.

    Every test above substitutes something. This one asserts the shipped matrix
    is currently true, which is the claim the recorded floor rests on.
    """
    status, complaints, provoked = discrimination_gate.run()
    assert status == discrimination_gate.EXIT_OK, "; ".join(complaints)
    assert provoked == discrimination.covered()


## An `auto` mutation whose tool genuinely reports the code it claims.
_AUTO_WORKS = discrimination.Mutation(
    rule_id="ERR-008",
    summary="an except clause catches Exception and names nothing",
    source="A known-good auto entry, to prove the runner credits a true claim.",
    tool="ruff",
    diagnostic="BLE001",
    replace=(("src/refpkg/app/prune.py",
              "from __future__ import annotations",
              ("from __future__ import annotations\n\n\ndef swallow() -> None:\n"
               '    """Catch everything.\n\n    @return nothing\n    """\n'
               "    try:\n        pass\n    except Exception:\n        return")),),
)

## An `auto` mutation claiming a code the damage cannot produce.
_AUTO_HOLLOW = discrimination.Mutation(
    rule_id="ERR-008",
    summary="a comment is added and BLE001 is claimed anyway",
    source="A deliberately false auto claim, so the runner is watched rejecting one.",
    tool="ruff",
    diagnostic="BLE001",
    replace=(("src/refpkg/app/prune.py",
              "from __future__ import annotations",
              "from __future__ import annotations\n\n# a comment"),),
)


def test_a_true_auto_claim_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mutation whose tool reports the declared diagnostic is counted.

    @param monkeypatch used to substitute the declared table
    """
    monkeypatch.setattr(discrimination, "MUTATIONS", (_AUTO_WORKS,))
    status, complaints, provoked = discrimination_gate.run()
    assert status == discrimination_gate.EXIT_OK, complaints
    assert provoked == {"ERR-008"}


def test_an_auto_claim_the_tool_does_not_report_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Damage that does not produce the declared code is a broken claim.

    @param monkeypatch used to substitute the declared table
    """
    monkeypatch.setattr(discrimination, "MUTATIONS", (_AUTO_HOLLOW,))
    status, _, provoked = discrimination_gate.run()
    assert status == discrimination_gate.EXIT_FAILED
    assert provoked == set()


def test_a_diagnostic_the_reference_already_emits_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard that keeps every auto result honest.

    If the conformant reference already emits the code, seeing it after the
    damage proves nothing -- the mutation would be credited with a finding that
    was there before it ran. Asked per DIAGNOSTIC rather than per tool: requiring
    ruff to be entirely silent over the reference would be a stronger claim than
    this gate needs and a flakier one.

    @param monkeypatch used to make the reference look like it already reports
    """
    monkeypatch.setattr(discrimination, "MUTATIONS", (_AUTO_WORKS,))
    monkeypatch.setitem(discrimination_gate.TOOLS, "ruff",
                        lambda _root: {"BLE001"})
    status, complaints, provoked = discrimination_gate.run()
    assert status == discrimination_gate.EXIT_FAILED
    assert provoked == set()
    assert "already reports" in complaints[0]


def test_a_syntax_error_does_not_credit_an_auto_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reason the diagnostic is asserted by name rather than by exit status.

    An unparseable file makes every tool exit non-zero. A runner that read the
    status alone would let one broken file certify the whole table, which is the
    vacuity this repository has caught in five separate tools.

    @param monkeypatch used to substitute the declared table
    """
    broken = discrimination.Mutation(
        rule_id="ERR-008",
        summary="the file no longer parses, which is not the rule being tested",
        source="Pins that a non-zero exit is not on its own evidence of anything.",
        tool="ruff",
        diagnostic="BLE001",
        replace=(("src/refpkg/app/prune.py",
                  "from __future__ import annotations",
                  "from __future__ import annotations\n\ndef ("),),
    )
    monkeypatch.setattr(discrimination, "MUTATIONS", (broken,))
    status, _, provoked = discrimination_gate.run()
    assert status == discrimination_gate.EXIT_FAILED
    assert provoked == set()


def test_a_rule_arriving_with_no_mutation_breaks_the_ceiling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The direction `D` alone cannot see.

    A release adding four decided rules and one mutation has raised `D` by one
    and widened the gap by three. `D` may only rise, so it reports progress; the
    ceiling is what reports the truth.

    @param monkeypatch used to substitute the table and the baseline path
    @param tmp_path holds a baseline recording a narrower gap than now exists
    """
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"count": 1, "rules": ["DOC-001"], "gap": 0}),
        encoding="utf-8",
    )
    monkeypatch.setattr(discrimination_gate, "BASELINE_PATH", baseline)
    monkeypatch.setattr(discrimination, "MUTATIONS", (_WORKS,))
    assert discrimination_gate.main([]) == discrimination_gate.EXIT_FAILED


def test_a_baseline_with_no_ceiling_is_not_treated_as_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A baseline recorded before the ceiling existed must not fail every run.

    The field is absent rather than zero in that case, and reading absent as
    zero would fail the gate on every tree that had ever recorded a floor -- the
    upgrade hazard that makes a new ratchet field worth a test of its own.

    @param monkeypatch used to substitute the table and the baseline path
    @param tmp_path holds a baseline in the pre-ceiling shape
    """
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"count": 1, "rules": ["DOC-001"]}), encoding="utf-8",
    )
    monkeypatch.setattr(discrimination_gate, "BASELINE_PATH", baseline)
    monkeypatch.setattr(discrimination, "MUTATIONS", (_WORKS,))
    assert discrimination_gate.main([]) == discrimination_gate.EXIT_OK


def test_the_gap_counts_only_rules_a_mechanism_actually_decides() -> None:
    """A rule with no working mechanism is V080's business, not this one.

    Counting it here would report the same defect twice under two names, and
    the second count would move whenever the first did -- which is how two
    numbers stop being independent evidence.
    """
    gap = set(discrimination_gate.undiscriminated(set(discrimination.covered())))
    assert "ALLOC-005" not in gap, (
        "ALLOC-005 is reported by V080 as undecided; it must not also be counted "
        "as decided-but-undiscriminated"
    )
    assert gap, "the gap is empty, so this assertion proves nothing"
