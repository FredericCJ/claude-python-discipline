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
