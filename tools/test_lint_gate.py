"""Proof-of-failure tests for the lint ratchet.

A ratchet that only ever passes is a green light wired to nothing, so every way
this one is meant to fail has a case here (`FLOW-007`, `TEST-015`). The case that
matters most is the last group: a protected code must fail the gate even when it
is sitting in the baseline, because that is the single way a ratchet could
silently switch off a rule's mechanism.

    pytest tools/test_lint_gate.py
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import lint_gate

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from pathlib import Path


# ------------------------------------------------------------------ the ratchet


def test_a_new_pair_fails() -> None:
    """The thing the gate is for: a finding that was not there before."""
    # Preserve finding-record elements in checker emission order for the final verdict.
    errors, _ = lint_gate.judge({("a.py", "E501")}, 1, set(), 0)
    assert errors == ["new finding -- a.py: E501"]


def test_a_recorded_pair_passes() -> None:
    """Existing debt must not fail the gate, or nobody keeps the gate on."""
    # Preserve finding-record elements in checker emission order for the final verdict.
    errors, _ = lint_gate.judge({("a.py", "E501")}, 1, {("a.py", "E501")}, 1)
    assert errors == []


def test_more_instances_of_a_recorded_code_fail() -> None:
    """Pairs alone would let a file accumulate the same finding indefinitely."""
    # Preserve finding-record elements in checker emission order for the final verdict.
    errors, _ = lint_gate.judge({("a.py", "E501")}, 3, {("a.py", "E501")}, 1)
    assert len(errors) == 1
    assert "rose from 1 to 3" in errors[0]


def test_shrinking_is_a_notice_and_not_a_failure() -> None:
    """Progress must never fail the build; it invites the ceiling down."""
    # Preserve finding-record elements in checker emission order for the final verdict.
    errors, notices = lint_gate.judge(set(), 0, {("a.py", "E501")}, 1)
    assert errors == []
    assert notices


# ---------------------------------------------------- the protected-code guard


def test_a_protected_code_fails_even_when_it_is_in_the_baseline() -> None:
    """The one way a ratchet could switch a binding rule off. It must not.

    C901 is the mechanism behind ARCH-016. A baseline entry for it would leave
    the rule reading as enforced while nothing decided it.
    """
    # Preserve finding-record elements in checker emission order for the final verdict.
    errors, _ = lint_gate.judge({("a.py", "C901")}, 1, {("a.py", "C901")}, 1)
    assert errors == ["protected code, never baselined -- a.py: C901"]


def test_a_protected_code_is_reported_once_not_twice() -> None:
    """A protected code is not also reported as a new finding; one defect, one line."""
    # Preserve finding-record elements in checker emission order for the final verdict.
    errors, _ = lint_gate.judge({("a.py", "C901")}, 1, set(), 0)
    assert len(errors) == 1


def test_every_protected_code_names_a_rule_mechanism() -> None:
    """The guard list must stay tied to the corpus rather than drifting into taste.

    Three places may tie a code to a rule, and a code needs only one of them. A
    mechanism tag is the narrowest -- `DOC-006` is tagged `auto:ruff:D205` while
    its `Check` line names D205, D400 and D415, and all three decide it. That
    authored `Check` line survives in `rules.json`, which is why it counts here.
    """
    # Each rule element supplies the authored mechanisms checked against protected Ruff codes.
    rules = json.loads(
        (lint_gate.REPO_ROOT / "discipline" / "rules.json").read_text(encoding="utf-8")
    )
    # Collect unique tagged element values; their order is deliberately unordered.
    tagged = {
        mechanism.rsplit(":", 1)[-1]
        for rule in rules["rules"]
        for mechanism in rule.get("mechanisms", [])
        if mechanism.startswith("auto:ruff:")
    }
    template = (lint_gate.REPO_ROOT / "enforce" / "templates" / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    checks = "\n".join(str(rule.get("check") or "") for rule in rules["rules"])
    for code in lint_gate.PROTECTED:
        assert code in tagged or code in template or code in checks, (
            f"{code} is protected but nothing ties it to a rule -- no mechanism tag, "
            f"no mention in the template, none in a rule Check. Either wire it to a "
            f"rule or stop protecting it; an unexplained guard is taste in disguise."
        )


# ------------------------------------------------------------- the baseline file


def test_the_baseline_refuses_to_move_without_a_reason(tmp_path: Path) -> None:
    """An untraced ceiling is indistinguishable from drift."""
    assert lint_gate.main(["--update-baseline", "--root", str(tmp_path)]) == 2


def test_an_absent_baseline_reads_as_empty(tmp_path: Path) -> None:
    """A missing ceiling must demand a clean tree, never accept whatever is there."""
    # Preserve the observed item count used by the non-vacuity verdict.
    count, pairs = lint_gate.load_baseline(tmp_path / "nothing.json")
    assert (count, pairs) == (0, set())


def test_a_baseline_round_trips(tmp_path: Path) -> None:
    """What the tool writes is what it reads back; the file is not hand-edited."""
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = tmp_path / "lint_baseline.json"
    lint_gate.write_baseline(2, {("a.py", "E501"), ("b.py", "TC003")}, "because", path)
    assert lint_gate.load_baseline(path) == (2, {("a.py", "E501"), ("b.py", "TC003")})
    assert json.loads(path.read_text(encoding="utf-8"))["why"] == "because"


def test_the_committed_baseline_holds_no_protected_code() -> None:
    """The live claim, checked rather than asserted in prose."""
    # Each pair identifies one accepted file/code combination in the committed debt ledger.
    _, pairs = lint_gate.load_baseline()
    # Offenders are protected codes that absolute policy forbids the baseline from masking.
    offenders = sorted({code for _, code in pairs if code in lint_gate.PROTECTED})
    assert offenders == [], f"protected code(s) in the committed baseline: {offenders}"


# ------------------------------------------------------------------- the reader


def test_line_numbers_are_dropped_from_the_pair(tmp_path: Path) -> None:
    """Line numbers are not part of the pair.

    They churn on every edit above a finding and would make the baseline
    unreviewable; the count is what catches a second instance instead.
    """
    # Each ordered element repeats one file/code identity at a deliberately different row.
    findings = [
        {"filename": str(tmp_path / "a.py"), "code": "E501", "location": {"row": 1}},
        {"filename": str(tmp_path / "a.py"), "code": "E501", "location": {"row": 99}},
    ]
    assert lint_gate.pairs_of(findings, tmp_path) == {("a.py", "E501")}


def test_a_finding_with_no_code_is_ignored(tmp_path: Path) -> None:
    """Ruff emits syntax errors with a null code; they are not ratchet material."""
    assert lint_gate.pairs_of([{"filename": "a.py", "code": None}], tmp_path) == set()
