"""The gate's own runner reports what happened, and can fail.

**Oracle: differential.** The runner is driven over a substitute `GATE` whose
steps are known to pass or known to fail, and its exit status compared.

`FLOW-007` asks every mechanism to be observed failing. This one needed it more
than most: `python tools/gate.py` was documented as the way to run the gate and
did nothing at all -- the module carried the tuple and no entry point, so it
imported, printed nothing, and exited 0. At the exit status that is
indistinguishable from nine passing steps, in the one file that exists to stop
exactly this.

    pytest tools/test_gate_runner.py
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import gate

if TYPE_CHECKING:
    import pytest

## A step that always succeeds. Expressed as this interpreter running a one-line
## program, so the fixture needs no files and behaves identically on every
## platform.
_PASSES = (sys.executable, "-c", "print('fine')")

## A step that always fails, printing before it does -- so the runner has output
## to report as well as a status to act on.
_FAILS = (sys.executable, "-c", "import sys; print('broken'); sys.exit(1)")


def test_all_passing_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every step green gives a zero status.

    @param monkeypatch used to substitute the gate tuple
    """
    monkeypatch.setattr(gate, "GATE", (("first", _PASSES), ("second", _PASSES)))
    assert gate.run() == 0


def test_one_failing_step_fails_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """A single red step fails the whole gate.

    @param monkeypatch used to substitute the gate tuple
    """
    monkeypatch.setattr(gate, "GATE", (("first", _PASSES), ("second", _FAILS)))
    assert gate.run() == 1


def test_later_steps_still_run_by_default(monkeypatch: pytest.MonkeyPatch,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    """A failure early on does not hide what the later steps found.

    The default is to keep going, because a reader fixing one thing wants to know
    what else is waiting rather than discovering it one run at a time.

    @param monkeypatch used to substitute the gate tuple
    @param capsys captures what the runner printed
    """
    monkeypatch.setattr(gate, "GATE", (("first", _FAILS), ("second", _PASSES)))
    assert gate.run() == 1
    assert "second" in capsys.readouterr().out


def test_stop_early_stops(monkeypatch: pytest.MonkeyPatch,
                          capsys: pytest.CaptureFixture[str]) -> None:
    """...and `--stop-early` is honoured when a caller asks for it.

    @param monkeypatch used to substitute the gate tuple
    @param capsys captures what the runner printed
    """
    monkeypatch.setattr(gate, "GATE", (("first", _FAILS), ("second", _PASSES)))
    assert gate.run(stop_early=True) == 1
    assert "second" not in capsys.readouterr().out


def test_the_real_gate_is_not_empty() -> None:
    """The runner is pointed at something.

    A runner over an empty tuple reports "all 0 steps passed", which is the
    vacuity this whole phase exists to refuse.
    """
    assert len(gate.GATE) >= 9
