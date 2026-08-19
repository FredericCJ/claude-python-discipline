"""A frozen set of real defects, and what the program said when each one failed.

The Prime Directive claims an agent meeting a defect "determines what broke,
where, in which layer, against which contract, with which value **from the
program's own output**, and derives the fix without re-reading the codebase."

Nothing has ever tested that. Every number this repository produces measures
conformance to itself -- `V080`, the mechanism census, lint findings, coverage.
This file is the subject of the one measurement that asks whether the corpus
*helps*: given only what a failing program printed, is the governing rule reached,
and at what reading cost.

## Why most of these outputs name no rule

An output that quotes `ARCH-002` is found by `nav.py`'s quoted-id seeding at zero
hops, and measures nothing but string matching. The interesting cases are the ones
an agent actually meets: a bare `FileNotFoundError`, a mypy line, a pytest
assertion. Those must be *derived*, and the derivation is what the corpus is for.

Both kinds are present and the harness reports them apart, because the honest
number is the one over outputs that name nothing.

## Frozen

This set does not grow. A benchmark whose subject expands as the tooling improves
measures the subject, not the tooling. Entries may be corrected if one misreports
what a program prints; entries may not be added to make a number move.

Every entry is drawn from a defect found in real code -- most from holding the
mechanisms against an unrelated codebase whose author had never read this corpus.
None was invented to be easy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class Defect:
    """One real failure, and the output an agent would have to work from."""

    ## Stable identifier, so a result can be compared across releases.
    defect_id: str
    ## What is actually wrong, in a line.
    summary: str
    ## Where this came from. Every entry is a real finding; this says which.
    source: str
    ## Exactly what the program or tool printed. The ONLY input the harness gives
    ## the navigator -- anything else would be the measurement helping itself.
    output: str
    ## The rules that must be reached before the defect can be fixed. Reaching any
    ## of them counts: a reader who lands on the governing rule has arrived.
    governs: tuple[str, ...]
    ## Whether `output` quotes a rule id outright. Reported separately, because a
    ## quoted id makes the lookup trivial and averaging the two together would
    ## flatter the result.
    names_a_rule: bool = False


## The frozen set. Twelve defects: eight whose output names no rule and must be
## derived, four whose output names one and are kept as the control -- if the
## named ones ever stop resolving, the navigator is broken in a way the derived
## ones would not isolate.
DEFECTS: Final[tuple[Defect, ...]] = (
    Defect(
        defect_id="D-01",
        summary="a probe with exists() before unlink races, and loses",
        source=(
            "Found eight times over in an unrelated codebase: `if target.exists(): "
            "target.unlink()` across four packages' deletion paths."
        ),
        output=(
            "Traceback (most recent call last):\n"
            '  File "vsep_cleanup/adapters/local_fs.py", line 47, in delete_file\n'
            "    target.unlink()\n"
            "    ~~~~~~~~~~~~~^^\n"
            'FileNotFoundError: [Errno 2] No such file or directory: '
            "'C:/tmp/leftover.log'"
        ),
        governs=("ERR-013",),
    ),
    Defect(
        defect_id="D-02",
        summary="a domain modelled in pydantic, so the framework is the domain",
        source=(
            "Found across four domains in an unrelated codebase. ARCH-013 listed "
            "BaseModel and reported nothing, because it read annotations only."
        ),
        output=(
            "Contracts: 6 kept, 1 broken.\n\n"
            "ARCH-004 foreign dependencies are cornered BROKEN\n"
            "- vsep_issuedb.domain.models is not allowed to import pydantic"
        ),
        governs=("ARCH-004", "ARCH-013", "DEP-002"),
    ),
    Defect(
        defect_id="D-03",
        summary="the domain reaches for a clock, so the same input gives two answers",
        source=(
            "The shape EFCT-003 and ARCH-005 exist for. A property suite that "
            "passes on Monday and fails on Tuesday is the usual first symptom."
        ),
        output=(
            "FAILED tests/property/test_plan.py::test_deterministic - "
            "AssertionError: assert Plan(doomed=('a.log',)) == "
            "Plan(doomed=('a.log', 'b.log'))"
        ),
        governs=("EFCT-003", "ARCH-005", "EFCT-002"),
    ),
    Defect(
        defect_id="D-04",
        summary="an unannotated function in a strictly-typed package",
        source="What `mypy --strict` prints first on a package adopting TYPE-001.",
        output=(
            "src/pkg/domain/plan.py:44: error: Function is missing a type "
            "annotation  [no-untyped-def]\n"
            "Found 1 error in 1 file (checked 26 source files)"
        ),
        governs=("TYPE-001", "TYPE-004"),
    ),
    Defect(
        defect_id="D-05",
        summary="a bare except that swallows the failure entirely",
        source=(
            "The ruff code DIAG-008 is enforced through. A swallowed exception "
            "destroys the chain the whole diagnostic contract rests on."
        ),
        output=(
            "src/pkg/app/run.py:88:5: BLE001 Do not catch blind exception: "
            "`Exception`"
        ),
        governs=("DIAG-008", "ERR-008"),
    ),
    Defect(
        defect_id="D-06",
        summary="an f-string built into a log call, so the message cannot be grouped",
        source=(
            "DIAG-012 and DIAG-015 are enforced through ruff G004. An interpolated "
            "log line has no stable identity for a log aggregator to group on."
        ),
        output="src/pkg/adapters/store.py:31:9: G004 Logging statement uses f-string",
        governs=("DIAG-012", "DIAG-015"),
    ),
    Defect(
        defect_id="D-07",
        summary="a boundary parsed with assert, which vanishes under python -O",
        source=(
            "OPEN-002's reasoning names this exactly: pydantic validation survives "
            "python -O where an assert does not, so an assert is not validation."
        ),
        output=(
            "src/pkg/adapters/api.py:19:5: S101 Use of `assert` detected"
        ),
        governs=("ERR-012", "ERR-011"),
    ),
    Defect(
        defect_id="D-08",
        summary="a domain function whose signature admits Any",
        source=(
            "Found three times in an unrelated codebase, in domain modules doing "
            "YAML serialisation that arguably belonged in an adapter."
        ),
        output=(
            'src/pkg/domain/store.py:57: error: Explicit "Any" is not allowed  '
            "[misc]"
        ),
        governs=("TYPE-002",),
    ),
    # -------------------------------------------------------------- the control
    #
    # Four outputs that DO name a rule. These should always resolve at zero hops.
    # They are not the measurement -- they are what tells a reader that a fall in
    # the derived set above is a real regression and not the navigator breaking
    # wholesale.
    Defect(
        defect_id="D-09",
        summary="a custom exception with no code, reported by this repository's check",
        source="Seventeen instances found in an unrelated codebase.",
        output=(
            "src/pkg/domain/errors.py:62: DIAG-002 exception GitError defines no "
            "`code`"
        ),
        governs=("DIAG-002",),
        names_a_rule=True,
    ),
    Defect(
        defect_id="D-10",
        summary="the domain importing something that can perform I/O",
        source="Two instances found in an unrelated codebase's safety module.",
        output=(
            "src/pkg/domain/safety.py:21: ARCH-002 domain imports `os`, which can "
            "perform I/O"
        ),
        governs=("ARCH-002",),
        names_a_rule=True,
    ),
    Defect(
        defect_id="D-11",
        summary="an unjustified suppression",
        source=(
            "Thirteen instances found in an unrelated codebase, four of them a "
            "block where the reason was written once and omitted on the identical "
            "lines below."
        ),
        output="src/pkg/adapters/win.py:24: FLOW-008 `noqa` suppression states no reason",
        governs=("FLOW-008",),
        names_a_rule=True,
    ),
    Defect(
        defect_id="D-12",
        summary="a dataclass in the domain that is neither frozen nor slotted",
        source="Eight instances found in an unrelated codebase, all frozen and none slotted.",
        output=(
            "src/pkg/domain/inventory.py:42: TYPE-007 domain dataclass "
            "`LeftoverSource` is not slots"
        ),
        governs=("TYPE-007",),
        names_a_rule=True,
    ),
)


def derived() -> tuple[Defect, ...]:
    """The defects whose output names no rule, which is the real measurement.

    @return the entries an agent would have to reason from
    """
    return tuple(d for d in DEFECTS if not d.names_a_rule)


def control() -> tuple[Defect, ...]:
    """The defects whose output names a rule outright.

    @return the entries that should always resolve, and isolate a broken navigator
    """
    return tuple(d for d in DEFECTS if d.names_a_rule)
