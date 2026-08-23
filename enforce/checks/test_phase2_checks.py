"""Proof-of-failure tests for the checks built to close the mechanization gap.

`FLOW-007` and `TEST-015`: a check never observed to fail has not been shown to
check anything, and its silence is indistinguishable from correctness.

**Every check here gets both directions.** A companion that only drives the
failing case is how an over-reporting check ships -- it fires on the violation
and on everything else, and nobody notices until the findings are ignored
wholesale. Three of these checks reported nothing at all across 6,700 lines of
independently written code, which is a suspect result and not a good one; the
must-fire cases below are what distinguish "the code was clean" from "the check
does nothing".

    pytest enforce/checks/test_phase2_checks.py
"""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from checks import Check, project
from checks.dispatch_recorded import DispatchRecordedCheck
from checks.domain_purity import DomainPurityCheck
from checks.error_channels import ErrorChannelsCheck
from checks.exception_has_code import ExceptionHasCodeCheck
from checks.exception_shape import ExceptionShapeCheck
from checks.explicit_effects import ExplicitEffectsCheck
from checks.library_logging import LibraryLoggingCheck
from checks.no_test_branches import NoTestBranchesCheck
from checks.oracle_declared import OracleDeclaredCheck
from checks.plan_apply import PlanApplyCheck
from checks.single_wiring_point import SingleWiringPointCheck

# Import path typing only while static analyzers evaluate fixture contracts.
if TYPE_CHECKING:
    from pathlib import Path


def fired(check: Check, tmp_path: Path, source: str, *,
          layer: str = "domain", name: str = "mod.py") -> set[str]:
    """Rule ids a check reports for one synthetic module.

    @param check the mechanism under test
    @param tmp_path pytest's per-test directory, used as the root of a fake tree
    @param source the module text, dedented before writing
    @param layer the segment under `src/mypkg/`, which decides layer scoping
    @param name the file's name; a `test_` prefix makes most checks skip it
    @return unordered reported rule-id string elements, empty when conformant

    @par Effects
    Creates one isolated source module, then attaches the default declaration to
    the supplied checker before executing it.
    """
    # Resolve the synthetic module path within the requested architectural layer.
    target = tmp_path / "src" / "mypkg" / layer / name
    # Materialize the package directory and dedented source before checker execution.
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dedent(source), encoding="utf-8")
    # Configure the checker with the canonical synthetic-project declaration.
    check.declaration = project.DEFAULT
    # Collapse emitted finding records to unordered governing rule-id elements.
    return {f.rule_id for f in check.run([target])}


# ------------------------------------------------------- DIAG-002 / DIAG-003


def test_an_exception_without_a_code_fires(tmp_path: Path) -> None:
    """The principal case: a type a consumer cannot match on except by prose.

    @param tmp_path the fixture directory
    """
    assert "DIAG-002" in fired(ExceptionHasCodeCheck(), tmp_path, '''
        """M."""
        class Boom(Exception):
            """No code."""
    ''')


def test_an_unnamespaced_code_fires(tmp_path: Path) -> None:
    """A bare word collides the moment two packages are combined.

    @param tmp_path the fixture directory
    """
    assert "DIAG-002" in fired(ExceptionHasCodeCheck(), tmp_path, '''
        """M."""
        class Boom(Exception):
            """Bare."""
            code = "boom"
    ''')


def test_an_exception_that_only_formats_fires(tmp_path: Path) -> None:
    """DIAG-003: detail interpolated away cannot be compared by a handler.

    @param tmp_path the fixture directory
    """
    assert "DIAG-003" in fired(ExceptionHasCodeCheck(), tmp_path, '''
        """M."""
        class Boom(Exception):
            """Formats and keeps nothing."""
            code = "pkg.domain.boom"
            def __init__(self, expected, actual):
                """Build a message."""
                super().__init__(f"wanted {expected}, got {actual}")
    ''')


def test_a_conformant_exception_is_silent(tmp_path: Path) -> None:
    """The accepting case, without which the check is merely noisy.

    @param tmp_path the fixture directory
    """
    assert fired(ExceptionHasCodeCheck(), tmp_path, '''
        """M."""
        class Boom(Exception):
            """Carries its detail."""
            code = "pkg.domain.boom"
            def __init__(self, expected, actual):
                """Keep the values."""
                super().__init__(f"wanted {expected}, got {actual}")
                self.expected = expected
                self.actual = actual
    ''') == set()


# ------------------------------------------------------- ERR-006 / ERR-010


def test_an_exception_outside_the_hierarchy_fires(tmp_path: Path) -> None:
    """A package raising a bare ValueError gives a caller nothing to catch.

    @param tmp_path the fixture directory
    """
    assert "ERR-006" in fired(ExceptionShapeCheck(), tmp_path, '''
        """M."""
        class PkgError(Exception):
            """The root."""
            code = "pkg.error"
        class Stray(ValueError):
            """Outside it."""
            code = "pkg.stray"
    ''')


def test_one_hierarchy_is_silent(tmp_path: Path) -> None:
    """Deriving from the local root is the shape the rule asks for.

    @param tmp_path the fixture directory
    """
    assert fired(ExceptionShapeCheck(), tmp_path, '''
        """M."""
        class PkgError(Exception):
            """The root."""
            code = "pkg.error"
        class Narrow(PkgError):
            """Inside it."""
            code = "pkg.narrow"
    ''') == set()


def test_raising_one_of_several_collected_failures_fires(tmp_path: Path) -> None:
    """ERR-010: reporting the first of several hides the rest until it is fixed.

    @param tmp_path the fixture directory
    """
    assert "ERR-010" in fired(ExceptionShapeCheck(), tmp_path, '''
        """M."""
        def check_all(items):
            """Gather and raise one."""
            problems = []
            for item in items:
                problems.append(ValueError(item))
            if problems:
                raise problems[0]
    ''')


# ------------------------------------------------------ ARCH-005 / EFCT-002


def test_the_domain_importing_an_effect_fires(tmp_path: Path) -> None:
    """The case found in real code: a domain module importing `os`.

    @param tmp_path the fixture directory
    """
    assert "EFCT-002" in fired(ExplicitEffectsCheck(), tmp_path, '''
        """M."""
        import os
        def where():
            """Read the environment."""
            return os.getcwd()
    ''')


def test_the_app_reaching_for_a_clock_fires(tmp_path: Path) -> None:
    """The other case found in real code: `datetime.now()` in orchestration.

    @param tmp_path the fixture directory
    """
    assert "ARCH-005" in fired(ExplicitEffectsCheck(), tmp_path, '''
        """M."""
        import datetime
        def stamp():
            """Take a reading."""
            return datetime.now()
    ''', layer="app")


def test_an_adapter_reaching_for_an_effect_is_silent(tmp_path: Path) -> None:
    """An adapter reaching for an effect is the design working, not failing.

    Without this case the check would report the entire adapter layer, which is
    the fastest way to have a rule switched off.

    @param tmp_path the fixture directory
    """
    assert fired(ExplicitEffectsCheck(), tmp_path, '''
        """M."""
        import time
        def now():
            """Read the clock."""
            return time.time()
    ''', layer="adapters") == set()


def test_a_port_taken_as_a_parameter_is_silent(tmp_path: Path) -> None:
    """The conformant shape: the effect arrives, it is not acquired.

    @param tmp_path the fixture directory
    """
    assert fired(ExplicitEffectsCheck(), tmp_path, '''
        """M."""
        def stamp(clock):
            """Take a reading through the port."""
            return clock.now()
    ''', layer="app") == set()


# ------------------------------------------------------ ARCH-011 / API-003


def test_the_app_importing_an_adapter_fires(tmp_path: Path) -> None:
    """Selection outside the composition root is selection in several places.

    @param tmp_path the fixture directory
    """
    assert "ARCH-011" in fired(SingleWiringPointCheck(), tmp_path, '''
        """M."""
        from mypkg.adapters.files import LocalStore
        def build():
            """Wire it here, wrongly."""
            return LocalStore()
    ''', layer="app")


def test_the_composition_root_may_name_adapters(tmp_path: Path) -> None:
    """The root's whole job is naming them; reporting it would be absurd.

    @param tmp_path the fixture directory
    """
    assert fired(SingleWiringPointCheck(), tmp_path, '''
        """M."""
        from mypkg.adapters.files import LocalStore
        def production():
            """Wire it here, rightly."""
            return LocalStore()
    ''', layer="shell", name="composition.py") == set()


def test_a_storage_type_in_a_public_signature_fires(tmp_path: Path) -> None:
    """API-003: a public operation speaking the store couples every caller to it.

    @param tmp_path the fixture directory
    """
    assert "API-003" in fired(SingleWiringPointCheck(), tmp_path, '''
        """M."""
        def load(cursor: Cursor) -> Row:
            """Speak the store."""
            return cursor.fetchone()
    ''', layer="app")


# ---------------------------------------------------------------- DIAG-011


def test_library_code_configuring_logging_fires(tmp_path: Path) -> None:
    """Importing a package must not change how the application logs.

    @param tmp_path the fixture directory
    """
    assert "DIAG-011" in fired(LibraryLoggingCheck(), tmp_path, '''
        """M."""
        import logging
        logging.basicConfig(level=logging.DEBUG)
    ''', layer="app")


def test_attaching_a_null_handler_is_silent(tmp_path: Path) -> None:
    """The one configuration a library may do: deciding nothing, quietly.

    @param tmp_path the fixture directory
    """
    assert fired(LibraryLoggingCheck(), tmp_path, '''
        """M."""
        import logging
        logging.getLogger(__name__).addHandler(logging.NullHandler())
    ''', layer="app") == set()


def test_the_shell_configuring_logging_is_silent(tmp_path: Path) -> None:
    """The process boundary is the layer whose job this is.

    @param tmp_path the fixture directory
    """
    assert fired(LibraryLoggingCheck(), tmp_path, '''
        """M."""
        import logging
        logging.basicConfig(level=logging.INFO)
    ''', layer="shell") == set()


# ------------------------------------------------------ TEST-004 / FLOW-002


def test_a_test_module_with_no_oracle_fires(tmp_path: Path) -> None:
    """The commonest real finding: 28 of 29 files in one real suite.

    @param tmp_path the fixture directory
    """
    assert "TEST-004" in fired(OracleDeclaredCheck(), tmp_path, '''
        """Tests for the thing."""
        def test_it_works():
            """It works."""
            assert True
    ''', name="test_thing.py")


def test_an_oracle_naming_none_of_the_five_fires(tmp_path: Path) -> None:
    """A described oracle is not a declared one; the list is closed on purpose.

    @param tmp_path the fixture directory
    """
    assert "FLOW-002" in fired(OracleDeclaredCheck(), tmp_path, '''
        """Tests.

        Oracle: whatever the implementation produced when this was written.
        """
        def test_it_works():
            """It works."""
            assert True
    ''', name="test_thing.py")


def test_a_declared_oracle_is_silent(tmp_path: Path) -> None:
    """The conformant case.

    @param tmp_path the fixture directory
    """
    assert fired(OracleDeclaredCheck(), tmp_path, '''
        """Tests.

        Oracle: the port's published contract.
        """
        def test_it_works():
            """It works."""
            assert True
    ''', name="test_thing.py") == set()


def test_a_helper_module_with_no_tests_is_silent(tmp_path: Path) -> None:
    """A conftest has no oracle to declare; demanding one demands prose about nothing.

    @param tmp_path the fixture directory
    """
    assert fired(OracleDeclaredCheck(), tmp_path, '''
        """Fixtures."""
        def build_thing():
            """Make one."""
            return 1
    ''', name="test_helpers.py") == set()


@pytest.mark.parametrize("check", [
    ExceptionHasCodeCheck(), ExceptionShapeCheck(), ExplicitEffectsCheck(),
    SingleWiringPointCheck(), LibraryLoggingCheck(), OracleDeclaredCheck(),
    ErrorChannelsCheck(), PlanApplyCheck(),
], ids=lambda c: c.name)
def test_every_check_names_the_rules_it_decides(check: Check) -> None:
    """A finding must be actionable without looking the mechanism up first.

    @param check the mechanism under test
    """
    # Require a non-empty declared rule set before validating each identifier family.
    assert check.rules
    # Require every rule-id element to begin with a normalized uppercase family.
    assert all(rule[:3].isupper() for rule in check.rules)


# ------------------------------------------ ERR-001 / ERR-003 / ERR-004 / ERR-014


def test_a_layer_raising_a_bare_builtin_fires(tmp_path: Path) -> None:
    """ERR-004: a built-in raised here makes the envelope's layer unknowable.

    @param tmp_path the fixture directory
    """
    assert "ERR-004" in fired(ErrorChannelsCheck(), tmp_path, '''
        """M."""
        def load(x):
            """Fail without a family."""
            raise RuntimeError("no")
    ''', layer="app")


def test_a_result_union_that_also_raises_fires(tmp_path: Path) -> None:
    """ERR-001: a caller cannot know whether to narrow or to handle.

    @param tmp_path the fixture directory
    """
    assert "ERR-001" in fired(ErrorChannelsCheck(), tmp_path, '''
        """M."""
        class PkgError(Exception):
            """The family."""
            code = "pkg.err"
        def load(x) -> Plan | Refusal:
            """Return a union and raise as well."""
            if x:
                raise PkgError("no")
            return Plan()
    ''')


def test_raising_the_layers_own_family_is_silent(tmp_path: Path) -> None:
    """The conformant shape: one family, one channel.

    @param tmp_path the fixture directory
    """
    assert fired(ErrorChannelsCheck(), tmp_path, '''
        """M."""
        class PkgError(Exception):
            """The family."""
            code = "pkg.err"
        def load(x):
            """Fail within the family."""
            raise PkgError("no")
    ''') == set()


def test_an_admitted_builtin_is_silent(tmp_path: Path) -> None:
    """NotImplementedError says something no package family says better.

    @param tmp_path the fixture directory
    """
    assert fired(ErrorChannelsCheck(), tmp_path, '''
        """M."""
        def load(x):
            """Not written yet."""
            raise NotImplementedError
    ''') == set()


# ------------------------------------ EFCT-004 / EFCT-005 / EFCT-010 / EFCT-011


def test_ungated_destruction_in_the_app_fires(tmp_path: Path) -> None:
    """The recorded incident: 8,023 files destroyed while reporting success.

    @param tmp_path the fixture directory
    """
    assert "EFCT-005" in fired(PlanApplyCheck(), tmp_path, '''
        """M."""
        def tidy(root):
            """Destroy without a plan."""
            for child in root.iterdir():
                child.unlink()
    ''', layer="app")


def test_destruction_behind_a_plan_is_silent(tmp_path: Path) -> None:
    """Taking a plan is exactly the seam the rule asks for.

    @param tmp_path the fixture directory
    """
    assert fired(PlanApplyCheck(), tmp_path, '''
        """M."""
        def tidy(root, plan):
            """Perform a plan the caller inspected."""
            for child in plan.doomed:
                child.unlink()
    ''', layer="app") == set()


def test_an_adapter_primitive_is_silent(tmp_path: Path) -> None:
    """The calibration case: an adapter IS the apply half of plan/apply.

    Reported six correct functions across three real packages before the check
    was scoped to the deciding layers. Requiring a plan parameter of a port's
    `delete` would mean no conformant implementation could pass.

    @param tmp_path the fixture directory
    """
    assert fired(PlanApplyCheck(), tmp_path, '''
        """M."""
        class LocalStore:
            """A store."""
            def delete_file(self, path):
                """Remove one file."""
                path.unlink()
    ''', layer="adapters") == set()


def test_a_state_compared_to_a_string_fires(tmp_path: Path) -> None:
    """EFCT-010: an open set admits every typo and refuses none of them.

    @param tmp_path the fixture directory
    """
    assert "EFCT-010" in fired(PlanApplyCheck(), tmp_path, '''
        """M."""
        def advance(job):
            """Branch on a stringly-typed state."""
            if job.status == "running":
                return 1
            return 0
    ''', layer="app")


def test_a_state_compared_to_an_enum_is_silent(tmp_path: Path) -> None:
    """The closed form the rule asks for.

    @param tmp_path the fixture directory
    """
    assert fired(PlanApplyCheck(), tmp_path, '''
        """M."""
        def advance(job):
            """Branch on a closed state."""
            if job.status == Status.RUNNING:
                return 1
            return 0
    ''', layer="app") == set()


# --------------------------------------------------- ALLOC-002..009 / TEAMS-001..002


def dispatched(tmp_path: Path, body: str, *, name: str = "an-agent.md") -> set[str]:
    """Rule ids the dispatch check reports for one synthetic record.

    @param tmp_path pytest's per-test directory
    @param body the record's markdown, dedented before writing
    @param name the file's name inside the `agents/` directory
    @return unordered reported rule-id string elements, empty when conformant

    @par Effects
    Creates one isolated agent record, then attaches the default declaration to
    a new dispatch checker before executing it.
    """
    # Resolve the synthetic dispatch path beneath the Claude agent directory.
    target = tmp_path / ".claude" / "agents" / name
    # Materialize the agent directory and dedented markdown before checker execution.
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dedent(body), encoding="utf-8")
    # Construct and configure the dispatch checker for the synthetic project.
    check = DispatchRecordedCheck()
    check.declaration = project.DEFAULT
    # Collapse emitted finding records to unordered governing rule-id elements.
    return {f.rule_id for f in check.run([target])}


## A record satisfying every clause, which each failing case below breaks in
## exactly one way -- so a failure names the clause that caused it.
CONFORMANT_DISPATCH = """
    # An agent

    Contract - it does the thing and proves it.

    ## Dispatch record (ops/ALLOC-002)

    A=0 B=0 C=1 D=1 E=1 F=0 G=1 -> **4/21 -> T0/E1**.

    ## Standing restrictions

    Never commit.
"""


def test_a_conformant_dispatch_is_silent(tmp_path: Path) -> None:
    """The accepting case; without it the check is only noise.

    @param tmp_path the fixture directory
    """
    assert dispatched(tmp_path, CONFORMANT_DISPATCH) == set()


def test_a_dispatch_missing_signals_fires(tmp_path: Path) -> None:
    """ALLOC-002: an unrecorded allocation cannot be audited after a failure.

    @param tmp_path the fixture directory
    """
    assert "ALLOC-002" in dispatched(tmp_path, """
        # An agent

        Contract - it does the thing.

        ## Dispatch record

        A=1 B=2 -> **3/21 -> T0/E0**.

        ## Standing restrictions

        Never commit.
    """)


def test_a_signal_at_three_below_e2_fires(tmp_path: Path) -> None:
    """ALLOC-004: one dimension at its maximum makes the work deliberative.

    @param tmp_path the fixture directory
    """
    assert "ALLOC-004" in dispatched(tmp_path, """
        # An agent

        Contract - it does the thing.

        ## Dispatch record

        A=0 B=0 C=3 D=0 E=0 F=0 G=0 -> **3/21 -> T0/E0**.

        ## Standing restrictions

        Never commit.
    """)


def test_an_escalation_stated_after_the_score_is_honoured(tmp_path: Path) -> None:
    """The check's own first defect: reading only the first allocation.

    A conformant record states the mechanical result and then the escalation that
    overrides it. Reading `T1/E1` and stopping reported three correct records as
    under-allocated, and the bare `E2` that follows is not in `T/E` form at all.

    @param tmp_path the fixture directory
    """
    assert dispatched(tmp_path, """
        # An agent

        Contract - it does the thing.

        ## Dispatch record

        A=0 B=0 C=3 D=0 E=0 F=0 G=0 -> **3/21 -> T0/E1**, floor raised to **E2**
        by ALLOC-004.

        ## Standing restrictions

        Never commit.
    """) == set()


def test_a_named_category_below_t2_fires(tmp_path: Path) -> None:
    """ALLOC-003: a named category beats the mechanical permit.

    @param tmp_path the fixture directory
    """
    assert "ALLOC-003" in dispatched(tmp_path, """
        # An agent

        Contract - it changes a published contract.

        ## Dispatch record

        A=0 B=0 C=1 D=0 E=0 F=0 G=0 -> **1/21 -> T0/E0**.

        ## Standing restrictions

        Never commit.
    """)


def test_a_dispatch_with_no_contract_fires(tmp_path: Path) -> None:
    """TEAMS-001: an intention cannot be verified.

    @param tmp_path the fixture directory
    """
    assert "TEAMS-001" in dispatched(tmp_path, """
        # An agent

        It should try to be helpful.

        ## Dispatch record

        A=0 B=0 C=1 D=1 E=1 F=0 G=1 -> **4/21 -> T0/E1**.

        ## Standing restrictions

        Never commit.
    """)


def test_a_dispatch_with_no_restrictions_fires(tmp_path: Path) -> None:
    """TEAMS-002: an unwritten restriction is one an instruction can appear to lift.

    Six of this repository's own nine agent definitions failed this on the
    check's first run -- they stated their restrictions as a trailing sentence
    rather than a named section.

    @param tmp_path the fixture directory
    """
    assert "TEAMS-002" in dispatched(tmp_path, """
        # An agent

        Contract - it does the thing.

        ## Dispatch record

        A=0 B=0 C=1 D=1 E=1 F=0 G=1 -> **4/21 -> T0/E1**.
    """)


def test_markdown_outside_an_agents_directory_is_ignored(tmp_path: Path) -> None:
    """A check cannot guess which markdown is a dispatch; the directory says so.

    @param tmp_path the fixture directory

    @par Effects
    Creates one isolated markdown file outside every recognized agent directory.
    """
    # Resolve and materialize an ordinary documentation path outside dispatch scope.
    target = tmp_path / "docs" / "notes.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    # Persist inert prose before constructing the dispatch mechanism.
    target.write_text("# Just prose\n", encoding="utf-8")
    check = DispatchRecordedCheck()
    # Require an out-of-scope markdown file to produce no dispatch finding.
    assert check.run([target]) == []


# ---------------------------------------- Phase 5 regressions: over-reporting
#
# Three mechanisms fired on correct code the first time they met a codebase
# written by someone who had never read these rules. Each pin below comes in a
# pair: the case that must stay silent, and the case that must still fire. A
# narrowing with only the first half is how a check gets quietly disarmed.


def test_a_pure_path_is_not_an_effect(tmp_path: Path) -> None:
    """ARCH-002 stays silent on `PurePosixPath` and on `date` as a type.

    The Pure path variants exist in the standard library precisely because they
    cannot touch a disk, and `date` in an annotation reads no clock. Flagging
    either told a careful author to stop using the tool built for their
    situation, which is how a check loses the reader it needs.

    @param tmp_path the fixture directory
    """
    assert "ARCH-002" not in fired(DomainPurityCheck(), tmp_path, '''
        """Classify a path by name alone."""
        from pathlib import PurePosixPath
        from datetime import date

        def suffix_of(path: str) -> str:
            """The suffix, as a string."""
            return PurePosixPath(path).suffix

        def seeded_on(day: date) -> date:
            """Echo the day."""
            return day
    ''')


def test_an_io_capable_path_still_fires(tmp_path: Path) -> None:
    """...and the exemption did not disarm the rule.

    An exemption list nobody has watched stay narrow is an exemption list that
    grows.

    @param tmp_path the fixture directory
    """
    assert "ARCH-002" in fired(DomainPurityCheck(), tmp_path, '''
        """Read a file from the domain, which it must not do."""
        from pathlib import Path

        def read(path: str) -> str:
            """Read it."""
            return Path(path).read_text(encoding="utf-8")
    ''')


def test_a_domain_value_spelled_test_is_not_a_test_signal(tmp_path: Path) -> None:
    """ARCH-012 stays silent on a taxonomy whose values include "test".

    Found against a codebase that classifies source files into zones -- `ports`,
    `test`, and so on. That string is a value the program reasons ABOUT, not a
    signal about the process it runs IN, and the rule is about the second.

    @param tmp_path the fixture directory
    """
    assert "ARCH-012" not in fired(NoTestBranchesCheck(), tmp_path, '''
        """Name the relation between two zones."""

        def relation(zone: str, other: str) -> str:
            """The relation."""
            if zone == "test" and other != "test":
                return "tests"
            return "includes"
    ''')


def test_an_environment_test_switch_still_fires(tmp_path: Path) -> None:
    """...and a signal the environment actually carries is still caught.

    @param tmp_path the fixture directory
    """
    assert "ARCH-012" in fired(NoTestBranchesCheck(), tmp_path, '''
        """Behave differently under test, which is the defect."""
        import os

        def timeout() -> int:
            """How long to wait."""
            if os.environ.get("MODE") == "test":
                return 0
            return 30
    ''', layer="app")


def test_a_domain_class_inheriting_a_framework_fires(tmp_path: Path) -> None:
    """ARCH-013 catches inheritance, not only annotations.

    The under-reporting case, and the more dangerous of the two failure modes.
    `BaseModel` was in FOREIGN_TYPES from the start and the check reported
    nothing against four real domains modelled entirely in pydantic, because it
    only ever looked at signatures.

    @param tmp_path the fixture directory
    """
    assert "ARCH-013" in fired(DomainPurityCheck(), tmp_path, '''
        """A domain modelled in a validation framework."""
        from pydantic import BaseModel

        class Issue(BaseModel):
            """Every instance carries pydantic's semantics."""

            identifier: str
    ''')


def test_a_plain_domain_class_does_not_fire(tmp_path: Path) -> None:
    """...and an ordinary base class is left alone.

    @param tmp_path the fixture directory
    """
    assert "ARCH-013" not in fired(DomainPurityCheck(), tmp_path, '''
        """A domain modelled in itself."""
        from dataclasses import dataclass

        class Thing:
            """A base of this project's own."""

        @dataclass(frozen=True, slots=True)
        class Issue(Thing):
            """A value."""

            identifier: str
    ''')


def test_a_mutable_collection_parameter_fires(tmp_path: Path) -> None:
    """TYPE-008: a mutable collection in a signature is an undeclared output.

    The caller cannot tell from the type whether their list comes back changed,
    and the day it does the defect is attributed to whoever read it rather than
    whoever wrote it.

    @param tmp_path the fixture directory
    """
    assert "TYPE-008" in fired(DomainPurityCheck(), tmp_path, '''
        """M."""

        def widen(names: list[str]) -> tuple[str, ...]:
            """Take a mutable list the caller still owns."""
            return tuple(names)
    ''')


def test_a_mutable_return_does_not_fire(tmp_path: Path) -> None:
    """...and handing back a fresh list owns nothing of the caller's.

    Load-bearing. The rule is about a parameter the callee does not own; a check
    that reported every `-> list[str]` would report most correct code, and a
    check that noisy is switched off within a day.

    @param tmp_path the fixture directory
    """
    assert "TYPE-008" not in fired(DomainPurityCheck(), tmp_path, '''
        """M."""

        def collect(names: tuple[str, ...]) -> list[str]:
            """Return a fresh list nobody else holds."""
            return list(names)
    ''')
