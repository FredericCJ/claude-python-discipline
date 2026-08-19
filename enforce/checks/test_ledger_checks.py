"""Proof-of-failure tests for the five ledger checks and the four record checks.

`FLOW-007` and `TEST-015`. All nine reported nothing against this repository's own
ledger, agent definitions and generated files on their first run, which is the
result that most needs a must-fire case beside it: a clean tree and a dead check
produce identical output.

Two of the accepting cases record a calibration that already happened. A bare
date in generated output is *data*, not a generation stamp, and a rule module
about generation is not itself generated -- both were reported before the checks
were narrowed, and both are pinned here so the narrowing cannot be undone by
someone re-deriving the obvious pattern.

    pytest enforce/checks/test_ledger_checks.py
"""

from __future__ import annotations

import json
from textwrap import dedent
from typing import TYPE_CHECKING

from checks import project
from checks.atomicity_qualified import AtomicityQualifiedCheck
from checks.compound_gate import CompoundGateCheck
from checks.deviation_recorded import DeviationRecordedCheck
from checks.generated_provenance import GeneratedProvenanceCheck
from checks.learning_scope import LearningScopeCheck
from checks.learning_size import LearningSizeCheck
from checks.ledger_append_only import LedgerAppendOnlyCheck
from checks.no_model_names import NoModelNamesCheck
from checks.promotion_due import PromotionDueCheck
from checks.session_recorded import SessionRecordedCheck
from checks.test_weakening import TestWeakeningCheck

if TYPE_CHECKING:
    from pathlib import Path

    from checks import Check


def ledger_of(tmp_path: Path, *events: dict[str, object]) -> Path:
    """Write a ledger holding the given events, numbered in order.

    @param tmp_path the directory to write into
    @param events the event payloads, in order; `seq` is filled in unless given
    @return the written ledger
    """
    path = tmp_path / "ledger.jsonl"
    lines = []
    for number, event in enumerate(events, start=1):
        record = {"seq": number, "session": "S-1", "payload": {}, **event}
        lines.append(json.dumps(record))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def found(check: Check, path: Path) -> set[str]:
    """Rule ids a check reports for one file.

    @param check the mechanism under test
    @param path the file to run it over
    @return every rule id reported
    """
    check.declaration = project.DEFAULT
    return {f.rule_id for f in check.run([path])}


def written(tmp_path: Path, name: str, body: str) -> Path:
    """Write one file with dedented contents.

    @param tmp_path the directory to write into
    @param name the file's name, whose suffix decides which checks see it
    @param body the contents
    @return the written file
    """
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(body), encoding="utf-8")
    return path


# ------------------------------------------------------------------ LEARN-005


def test_a_gap_in_the_sequence_fires(tmp_path: Path) -> None:
    """A gap means a line was removed, and with it the evidence it carried.

    @param tmp_path the fixture directory
    """
    path = ledger_of(tmp_path, {"kind": "session"}, {"kind": "learn", "seq": 5})
    assert "LEARN-005" in found(LedgerAppendOnlyCheck(), path)


def test_a_contiguous_ledger_is_silent(tmp_path: Path) -> None:
    """The accepting case.

    @param tmp_path the fixture directory
    """
    path = ledger_of(tmp_path, {"kind": "session"},
                     {"kind": "learn", "payload": {"id": "L-1"}})
    assert found(LedgerAppendOnlyCheck(), path) == set()


def test_a_duplicated_learning_id_fires(tmp_path: Path) -> None:
    """A second entry makes the first one's text unreachable.

    @param tmp_path the fixture directory
    """
    path = ledger_of(tmp_path,
                     {"kind": "learn", "payload": {"id": "L-1"}},
                     {"kind": "learn", "payload": {"id": "L-1"}})
    assert "LEARN-005" in found(LedgerAppendOnlyCheck(), path)


# ------------------------------------------------------------------ LEARN-004


def test_an_unscoped_learning_fires(tmp_path: Path) -> None:
    """An unscoped discipline finding is invisible to the harvest.

    @param tmp_path the fixture directory
    """
    path = ledger_of(tmp_path, {"kind": "learn", "payload": {
        "id": "L-1", "claim": "c", "action": "a", "kind": "defect"}})
    assert "LEARN-004" in found(LearningScopeCheck(), path)


def test_a_learning_with_no_action_fires(tmp_path: Path) -> None:
    """A claim without an action is an observation.

    @param tmp_path the fixture directory
    """
    path = ledger_of(tmp_path, {"kind": "learn", "payload": {
        "id": "L-1", "claim": "c", "kind": "defect", "scope": "project"}})
    assert "LEARN-004" in found(LearningScopeCheck(), path)


def test_a_complete_learning_is_silent(tmp_path: Path) -> None:
    """The accepting case.

    @param tmp_path the fixture directory
    """
    path = ledger_of(tmp_path, {"kind": "learn", "payload": {
        "id": "L-1", "claim": "c", "action": "a", "kind": "defect",
        "scope": "discipline"}})
    assert found(LearningScopeCheck(), path) == set()


# ------------------------------------------------------------------ LEARN-001


def test_a_session_that_recorded_nothing_fires(tmp_path: Path) -> None:
    """A session that spent its discovery and wrote none of it down.

    @param tmp_path the fixture directory
    """
    path = ledger_of(tmp_path, {"kind": "session", "session": "S-quiet"})
    assert "LEARN-001" in found(SessionRecordedCheck(), path)


def test_a_session_that_reported_an_outcome_is_silent(tmp_path: Path) -> None:
    """Reporting an outcome is as much a record as making a claim.

    @param tmp_path the fixture directory
    """
    path = ledger_of(tmp_path, {"kind": "session", "session": "S-1"},
                     {"kind": "used", "session": "S-1",
                      "payload": {"id": "L-1", "outcome": "noise"}})
    assert found(SessionRecordedCheck(), path) == set()


# --------------------------------------------------------- LEARN-010 / LEARN-009


def test_an_oversized_active_set_fires(tmp_path: Path) -> None:
    """A set nobody prunes becomes a set nobody reads.

    @param tmp_path the fixture directory
    """
    events = [{"kind": "learn", "payload": {"id": f"L-{n}"}} for n in range(5)]
    path = ledger_of(tmp_path, *events)
    (tmp_path / "config.toml").write_text("max_active = 2\n", encoding="utf-8")
    assert "LEARN-010" in found(LearningSizeCheck(), path)


def test_a_set_inside_the_ceiling_is_silent(tmp_path: Path) -> None:
    """The accepting case, with the ceiling read from configuration.

    @param tmp_path the fixture directory
    """
    path = ledger_of(tmp_path, {"kind": "learn", "payload": {"id": "L-1"}})
    (tmp_path / "config.toml").write_text("max_active = 200\n", encoding="utf-8")
    assert found(LearningSizeCheck(), path) == set()


def test_a_verified_learning_over_the_bar_fires(tmp_path: Path) -> None:
    """A learning that can be enforced once should not be re-read every session.

    @param tmp_path the fixture directory
    """
    path = ledger_of(
        tmp_path,
        {"kind": "learn", "payload": {"id": "L-1", "verification": "pytest -q"}},
        {"kind": "used", "payload": {"id": "L-1", "outcome": "helped"}},
    )
    (tmp_path / "config.toml").write_text("min_evidence_verified = 1\n", encoding="utf-8")
    assert "LEARN-009" in found(PromotionDueCheck(), path)


def test_a_learning_with_no_verification_is_silent(tmp_path: Path) -> None:
    """Without a command that decides it, there is no mechanism to promote to.

    @param tmp_path the fixture directory
    """
    path = ledger_of(tmp_path, {"kind": "learn", "payload": {"id": "L-1"}},
                     {"kind": "used", "payload": {"id": "L-1", "outcome": "helped"}})
    assert found(PromotionDueCheck(), path) == set()


# ------------------------------------------------- DEP-007 / DEP-008 / DOC-012


def test_a_generated_file_naming_no_generator_fires(tmp_path: Path) -> None:
    """A reader who cannot regenerate a file will eventually edit it instead.

    @param tmp_path the fixture directory
    """
    path = written(tmp_path, "out.md", """
        <!-- GENERATED -->

        A table.
    """)
    assert "DEP-007" in found(GeneratedProvenanceCheck(), path)


def test_a_generation_stamp_fires(tmp_path: Path) -> None:
    """A stamp makes every rebuild differ, so no staleness check can mean anything.

    @param tmp_path the fixture directory
    """
    path = written(tmp_path, "out.md", """
        <!-- GENERATED by `tools/build.py` -->

        Generated at 2026-08-19 by the builder.
    """)
    assert "DEP-008" in found(GeneratedProvenanceCheck(), path)


def test_a_bare_date_in_generated_output_is_silent(tmp_path: Path) -> None:
    """A date that is *data* reproduces identically on every run.

    Calibration case: this reported three correct files here -- a quoted
    `verified:` date, a calibration `--as-of` parameter, a `last seen` field --
    before the pattern was narrowed to generation stamps.

    @param tmp_path the fixture directory
    """
    path = written(tmp_path, "out.md", """
        <!-- GENERATED by `tools/build.py` -->

        | verified | 2026-06-16 |
    """)
    assert found(GeneratedProvenanceCheck(), path) == set()


def test_a_document_about_generation_is_not_generated_output(tmp_path: Path) -> None:
    """Calibration case: `law/DEP.md` was reported for its own router keywords.

    @param tmp_path the fixture directory
    """
    path = written(tmp_path, "rule.md", """
        ---
        id: law/DEP
        load_when: ["code generation", "generated file"]
        ---

        Generated output is committed.
    """)
    assert found(GeneratedProvenanceCheck(), path) == set()


# ------------------------------------------------------------------ ALLOC-001


def test_a_model_named_in_prose_fires(tmp_path: Path) -> None:
    """A tier is a role and survives procurement; a model name does not.

    @param tmp_path the fixture directory
    """
    path = written(tmp_path, "doc.md", """
        # A document

        Dispatch the hard cases to claude-opus-4 and the rest elsewhere.
    """)
    assert "ALLOC-001" in found(NoModelNamesCheck(), path)


def test_a_configuration_binding_is_silent(tmp_path: Path) -> None:
    """Something has to bind a tier to a model, and one declared place is the point.

    @param tmp_path the fixture directory
    """
    path = written(tmp_path, "agent.md", """
        ---
        name: an-agent
        model: sonnet
        ---

        Dispatched at T2/E2.
    """)
    assert found(NoModelNamesCheck(), path) == set()


def test_the_mapping_document_is_exempt(tmp_path: Path) -> None:
    """Forbidding the mapping to exist would scatter the coupling, not remove it.

    @param tmp_path the fixture directory
    """
    path = written(tmp_path, "map.md", """
        ## Tier to model

        `T0 -> haiku`, `T1 -> sonnet`, `T2 -> opus`.
    """)
    assert found(NoModelNamesCheck(), path) == set()


# --------------------------------------- FLOW-008 / EFCT-008 / TEST-014 / TEST-016


def test_a_bare_suppression_fires(tmp_path: Path) -> None:
    """An unexplained suppression leaves the next reader three bad choices.

    @param tmp_path the fixture directory
    """
    path = written(tmp_path, "mod.py", '''
        """M."""
        import os  # noqa: F401
    ''')
    assert "FLOW-008" in found(DeviationRecordedCheck(), path)


def test_a_suppression_with_a_reason_is_silent(tmp_path: Path) -> None:
    """The accepting case, and this repository's own convention.

    @param tmp_path the fixture directory
    """
    path = written(tmp_path, "mod.py", '''
        """M."""
        import os  # noqa: F401 - re-exported for the package surface
    ''')
    assert found(DeviationRecordedCheck(), path) == set()


def test_a_bare_atomicity_claim_fires(tmp_path: Path) -> None:
    """Four guarantees at four costs, and the bare word is identical for all.

    @param tmp_path the fixture directory
    """
    path = written(tmp_path, "mod.py", '''
        """M."""
        def save(data):
            """Write the data atomically."""
            return data
    ''')
    assert "EFCT-008" in found(AtomicityQualifiedCheck(), path)


def test_a_qualified_atomicity_claim_is_silent(tmp_path: Path) -> None:
    """Saying what it is atomic with respect to is the whole requirement.

    @param tmp_path the fixture directory
    """
    path = written(tmp_path, "mod.py", '''
        """M."""
        def save(data):
            """Write the data atomically with respect to a concurrent reader."""
            return data
    ''')
    assert found(AtomicityQualifiedCheck(), path) == set()


def test_an_over_compound_decision_fires(tmp_path: Path) -> None:
    """Three operands is eight combinations; a suite usually covers two.

    @param tmp_path the fixture directory
    """
    path = written(tmp_path, "mod.py", '''
        """M."""
        def decide(a, b, c):
            """Join three."""
            if a and b and c:
                return 1
            return 0
    ''')
    assert "TEST-014" in found(CompoundGateCheck(), path)


def test_two_operands_are_silent(tmp_path: Path) -> None:
    """Four cases are usually tested exhaustively without anyone deciding to.

    @param tmp_path the fixture directory
    """
    path = written(tmp_path, "mod.py", '''
        """M."""
        def decide(a, b):
            """Join two."""
            if a and b:
                return 1
            return 0
    ''')
    assert found(CompoundGateCheck(), path) == set()


def test_a_skip_without_a_reason_fires(tmp_path: Path) -> None:
    """A skip removes a test and leaves nobody a way to know if it still applies.

    @param tmp_path the fixture directory
    """
    path = written(tmp_path, "test_thing.py", '''
        """Tests. Oracle: contract."""
        import pytest
        @pytest.mark.skip
        def test_it():
            """Skipped."""
            assert 1 == 1
    ''')
    assert "TEST-016" in found(TestWeakeningCheck(), path)


def test_a_tautological_assertion_fires(tmp_path: Path) -> None:
    """It moves the pass count up while checking nothing.

    @param tmp_path the fixture directory
    """
    path = written(tmp_path, "test_thing.py", '''
        """Tests. Oracle: contract."""
        def test_it():
            """Asserts nothing at all."""
            assert True
    ''')
    assert "TEST-016" in found(TestWeakeningCheck(), path)


def test_a_skip_with_a_reason_is_silent(tmp_path: Path) -> None:
    """A stated reason is the difference between a decision and an erosion.

    @param tmp_path the fixture directory
    """
    path = written(tmp_path, "test_thing.py", '''
        """Tests. Oracle: contract."""
        import pytest
        @pytest.mark.skip(reason="doxygen is not installed in this environment")
        def test_it():
            """Skipped deliberately."""
            assert 1 == 1
    ''')
    assert found(TestWeakeningCheck(), path) == set()
