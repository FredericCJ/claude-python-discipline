"""Which rules have been observed rejecting something, and what it was.

`V080` reached 0: every binding rule names a mechanism, and every named mechanism
exists. That answers *does a mechanism exist*. It does not answer **does the
mechanism discriminate** — whether anything it would reject has ever been put in
front of it.

The distinction is not academic. `ARCH-013` listed `BaseModel` among the framework
types a domain may not borrow, was counted as `mechanized`, and reported **nothing**
against four real domains modelled entirely in pydantic. It examined annotations
and never inheritance. It was found by an unrelated tool approaching from the graph
side, not by its own census, because a check that finds nothing reads exactly like
a check that finds nothing wrong.

So this file declares, per rule, **one concrete thing that must make it fire**. The
runner applies each mutation to a throwaway tree and asserts the rule is reported.
A rule with no entry here is *undiscriminated*: its mechanism exists and nobody has
watched it work.

## The entries are the point, not the count

`D` — how many rules are covered — is a ratchet, and a ratchet invites gaming. One
trivial mutation per rule would raise `D` and prove nothing, so every entry carries
a `source`: the real finding it came from, or the clause of the rule it exercises.
`test_discrimination.py` asserts the mutation shapes are not all the same. `D`
rising is necessary and nowhere near sufficient; the entries are meant to be read.

    python tools/discrimination_gate.py
    python -m pytest -q enforce/test_discrimination.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

## Where a mutation is applied. `reference` copies the conformant package and
## damages it, which is right for anything scoped to a source tree. `empty` builds
## a tree from `write` alone, for rules whose subject is not a package at all --
## an agent definition, a learning ledger, a generated artefact.
BASES: Final[frozenset[str]] = frozenset({"reference", "empty"})


@dataclass(frozen=True, slots=True)
class Mutation:
    """One concrete change that must make one rule fire.

    Exactly one rule per entry. A mutation that provokes two rules cannot say
    which of them was discriminating and which merely happened to be nearby --
    the same reason `broken_copy` breaks one thing at a time.
    """

    ## The rule this must provoke. One id; see the class docstring.
    rule_id: str
    ## What the mutation does, in a line a reader can check against the tree.
    summary: str
    ## Why THIS mutation tests THIS rule: the finding it came from, or the clause
    ## of the rule it exercises. An entry that cannot answer this is a rubber
    ## stamp and should not be here.
    source: str
    ## Which tree to damage. See `BASES`.
    base: str = "reference"
    ## Paths to delete, relative to the tree root.
    drop: tuple[str, ...] = ()
    ## `(path, contents)` pairs to create or overwrite. Held as pairs rather than
    ## a mapping so the entry stays hashable and cannot be edited in place.
    write: tuple[tuple[str, str], ...] = ()
    ## `(path, old, new)` literal substitutions.
    replace: tuple[tuple[str, str, str], ...] = ()
    ## Paths the runner points the checks at, relative to the tree root. The
    ## default suits a package; a rule about a ledger or an agent file names its
    ## own subject.
    targets: tuple[str, ...] = field(default=("src",))
    ## A pytest node id, for a rule decided by a fitness test rather than an AST
    ## check. The runner points `DISCIPLINE_REFERENCE` at the damaged tree and
    ## requires this node to FAIL. Empty means the rule is decided by a check and
    ## the finding is looked for in what the checks report.
    ##
    ## Both kinds are the same claim -- *this mechanism rejects this thing* -- and
    ## they differ only in how the rejection is observed.
    node: str = ""
    ## The tool that must report this mutation, for a rule decided by an `auto:`
    ## tag rather than by a check or a fitness test. One of `TOOLS`. Twenty-seven
    ## binding rules are decided by a configured tool alone, and until this field
    ## existed not one of them could enter the matrix at all: `D` was structurally
    ## incapable of covering them, which is a worse gap than a missing entry
    ## because no amount of writing entries would close it.
    tool: str = ""
    ## The diagnostic that tool must emit -- a ruff code, a mypy error code, an
    ## import-linter contract name. Asserted BY NAME rather than by the tool
    ## merely exiting non-zero: a syntax error also exits non-zero, and crediting
    ## a rule for one would let a single unparseable file certify the whole table.
    diagnostic: str = ""


## A filled-in allocation mapping, written beside the dispatch mutations so
## `ALLOC-010` is satisfied and the rule under test is the only one that can
## fire. Without it every dispatch mutation reported two rules, and a
## mutation provoking two cannot say which one discriminated.
_MAPPING: Final = (
    '[tiers]\nT0 = "a"\nT1 = "b"\nT2 = "c"\n\n'
    '[meta]\nverified = "2026-08-19"\nowner = "the maintainer"\n'
)


## Fourteen branches, which is past the complexity budget `ARCH-016` sets. Built
## as a constant rather than inline so the mutation entry stays a plain literal.
TANGLED: Final = "".join(
    f"    if n == {branch}:\n        return {branch}\n" for branch in range(14)
)


## The declared table: one concrete mutation per rule, each of which the runner
## applies and then insists the rule is reported. Grouped by the law module the
## rule belongs to, so a reader can see at a glance which tracks are covered and
## which are still taking the mechanism's word for it.
MUTATIONS: Final[tuple[Mutation, ...]] = (
    # ---------------------------------------------------------------- law/ARCH
    Mutation(
        rule_id="ARCH-002",
        summary="the domain imports pathlib.Path, which can read a disk",
        source=("The rule's own clause -- the domain imports nothing that can "
               "perform I/O. Phase 5 narrowed this to exempt PurePosixPath, so "
               "the still-forbidden case is pinned here against that narrowing."),
        replace=(("src/refpkg/domain/model.py",
                  "from __future__ import annotations",
                  "from __future__ import annotations\n\nfrom pathlib import Path"),),
    ),
    Mutation(
        rule_id="ARCH-013",
        summary="a domain class inherits pydantic.BaseModel",
        source=("The Phase 5 finding. BaseModel was listed as a foreign type from "
               "the start and the check reported nothing against four domains "
               "modelled entirely in it, because it read annotations and never "
               "bases. This is the exact shape that was invisible."),
        replace=(("src/refpkg/domain/model.py",
                  "from __future__ import annotations",
                  ("from __future__ import annotations\n\n"
                  "from pydantic import BaseModel\n\n\n"
                  "class Borrowed(BaseModel):\n"
                  '    """A domain value that is really a framework value."""\n\n'
                  "    name: str")),),
    ),
    Mutation(
        rule_id="ARCH-012",
        summary="a production branch reads a test switch out of the environment",
        source=("Phase 5 narrowed this so a domain value spelled 'test' no longer "
               "fires. The environment-signal case is what must survive that."),
        replace=(("src/refpkg/app/prune.py",
                  "from __future__ import annotations",
                  "from __future__ import annotations\n\nimport os"),
                 ("src/refpkg/app/prune.py",
                  "def apply(",
                  ("def _timeout() -> int:\n"
                  '    """Behave differently under test, which is the defect."""\n'
                  '    if os.environ.get("MODE") == "test":\n'
                  "        return 0\n"
                  "    return 30\n\n\n"
                  "def apply("))),
    ),
    Mutation(
        rule_id="ARCH-015",
        summary="the domain reaches an attribute by a computed name",
        source=("The rule's clause: a computed name is a branch no reader can "
               "enumerate. getattr with a variable is the canonical instance."),
        replace=(("src/refpkg/domain/plan.py",
                  "from __future__ import annotations",
                  ("from __future__ import annotations\n\n\n"
                  "def _reach(obj: object, name: str) -> object:\n"
                  '    """Reach an attribute nobody can enumerate."""\n'
                  "    return getattr(obj, name)")),),
    ),
    # ---------------------------------------------------------------- law/TYPE
    Mutation(
        rule_id="TYPE-008",
        summary="a domain function takes a mutable list as a parameter",
        source=("Built during the requalification pass: TYPE-008 tagged "
                "check:domain_purity, which claimed five rules and none of them "
                "was this one, so the rule was decided by nothing while reading "
                "as decided. The mutation is the rule's own clause -- a mutable "
                "collection in a signature is an undeclared output channel."),
        replace=(("src/refpkg/domain/plan.py",
                  "from __future__ import annotations",
                  ("from __future__ import annotations\n\n\n"
                   "def absorb(names: list[str]) -> int:\n"
                   '    """Take a list the caller still owns."""\n'
                   "    return len(names)")),),
    ),
    Mutation(
        rule_id="TYPE-002",
        summary="a domain signature takes Any",
        source=("The rule's clause. Any in the domain is the hole the whole typing "
               "track exists to close, and a signature is what every caller is "
               "held to."),
        replace=(("src/refpkg/domain/plan.py",
                  "from __future__ import annotations",
                  ("from __future__ import annotations\n\n"
                  "from typing import Any\n\n\n"
                  "def widen(value: Any) -> Any:\n"
                  '    """Accept anything, promise nothing."""\n'
                  "    return value")),),
    ),
    Mutation(
        rule_id="TYPE-007",
        summary="a domain dataclass is neither frozen nor slotted",
        source=("Found in real code: eight dataclasses were frozen and not "
               "slotted, so the two halves of the rule need separate evidence. "
               "This drops both."),
        replace=(("src/refpkg/domain/model.py",
                  "@dataclass(frozen=True, slots=True)",
                  "@dataclass()"),),
    ),
    # ----------------------------------------------------------------- law/ERR
    Mutation(
        rule_id="ERR-013",
        summary="a probe with exists() before acting on the path",
        source=("The Phase 5 finding, eight times over in real code: "
               "`if target.exists(): target.unlink()` is a race, and the file can "
               "vanish between the two lines."),
        replace=(("src/refpkg/adapters/files/real.py",
                  "    def delete(",
                  ("    def delete_racy(self, path: str) -> None:\n"
                  '        """Probe, then act, which is a race."""\n'
                  "        target = self._root / path\n"
                  "        if target.exists():\n"
                  "            target.unlink()\n\n"
                  "    def delete(")),),
    ),
    # ---------------------------------------------------------------- law/DIAG
    Mutation(
        rule_id="DIAG-002",
        summary="an exception type carries no code",
        source=("The Phase 5 finding: seventeen error types in real code carried "
               "structured attributes and no code, so a consumer could match only "
               "on the class or on prose."),
        replace=(("src/refpkg/domain/errors.py",
                  "class InvariantViolated",
                  ("class Uncoded(Exception):\n"
                  '    """A failure nothing can match on."""\n\n\n'
                  "class InvariantViolated")),),
    ),
    Mutation(
        rule_id="DIAG-008",
        summary="an except block swallows the exception",
        source=("The rule's clause -- nothing is swallowed. A bare pass in a "
               "handler is the form that destroys the diagnostic chain entirely."),
        replace=(("src/refpkg/app/prune.py",
                  "from __future__ import annotations",
                  ("from __future__ import annotations\n\n\n"
                  "def _swallow() -> None:\n"
                  '    """Lose the failure."""\n'
                  "    try:\n"
                  "        raise ValueError(1)\n"
                  "    except ValueError:\n"
                  "        pass")),),
    ),
    # ---------------------------------------------------------------- law/EFCT
    Mutation(
        rule_id="EFCT-002",
        summary="the core imports os and reaches for an effect",
        source=("The rule's clause: effects are parameters, never reached for. An "
               "import in the core is the reach the rule names."),
        replace=(("src/refpkg/domain/plan.py",
                  "from __future__ import annotations",
                  "from __future__ import annotations\n\nimport os"),),
    ),
    # ----------------------------------------------------------------- law/DOC
    Mutation(
        rule_id="DOC-001",
        summary="a public function carries no docstring",
        source=("The rule's clause, and the one documentation rule that stayed "
               "universal when DOC-002 and DOC-007 became conditional on a "
               "declared engine."),
        replace=(("src/refpkg/domain/model.py",
                  "from __future__ import annotations",
                  ("from __future__ import annotations\n\n\n"
                  "def undocumented(value: int) -> int:\n"
                  "    return value")),),
    ),
    # ---------------------------------------------------------------- law/TEST
    Mutation(
        rule_id="TEST-004",
        summary="a test module declares no oracle",
        source=("The rule's clause: a test whose oracle is unstated cannot be "
               "judged for whether it tests anything."),
        write=(("tests/unit/test_nothing.py",
                ('"""A suite with no stated oracle."""\n\n\n'
                "def test_it() -> None:\n"
                '    """Assert something."""\n'
                "    assert True\n")),),
        targets=("tests",),
    ),
    Mutation(
        rule_id="TEST-014",
        summary="a decision joins four operands in one condition",
        source=("The rule's clause -- combinations grow as 2^n and the untested "
               "ones are invisible. Five instances were found in real code. The "
               "operands sit in an `if` rather than a `return` because the check "
               "examines conditions, and the first draft of this entry did not: "
               "the matrix rejected it, which is what it is for."),
        replace=(("src/refpkg/domain/plan.py",
                  "from __future__ import annotations",
                  ("from __future__ import annotations\n\n\n"
                  "def tangled(a: bool, b: bool, c: bool, d: bool) -> bool:\n"
                  '    """Sixteen paths in one condition."""\n'
                  "    if a and b and c and d:\n"
                  "        return True\n"
                  "    return False")),),
    ),
    # ----------------------------------------------------------------- ops
    Mutation(
        rule_id="ALLOC-010",
        summary="a dispatch record cites T2 with no tier mapping anywhere above it",
        source=("The case OPEN-006 called unauditable: a tier that resolves to "
                "nothing names a role rather than a choice. Built on an empty "
                "base so no allocation.toml is reachable by walking upward."),
        base="empty",
        write=((".claude/agents/thing.md",
                ("---\nname: thing\n---\n\n# Thing\n\n"
                 "## Dispatch record (ops/ALLOC-002)\n\n"
                 "A3 B2 C1 D2 E2 F1 G0 = 11 -> T2/E2\n")),),
        targets=(".claude",),
    ),
    # ---------------------------------------------------------------- law/FLOW
    Mutation(
        rule_id="FLOW-008",
        summary="a suppression states no reason",
        source=("The Phase 5 finding: thirteen unjustified suppressions in real "
               "code, four of them a block where the author wrote the reason once "
               "and omitted it on the identical lines below."),
        replace=(("src/refpkg/domain/model.py",
                  "from __future__ import annotations",
                  ("from __future__ import annotations\n\n"
                  "import json  # ruff: ignore[unused-import]")),),
    ),
    Mutation(
        rule_id="FLOW-002",
        summary="a test module names no oracle at all",
        source=("`oracle_declared` decides FLOW-002 and TEST-004 together; the "
                "TEST-004 entry above covers a suite with no oracle heading, and "
                "this covers the same absence seen from the workflow side, where "
                "the obligation is to NAME the oracle before writing the test."),
        write=(("tests/unit/test_unstated.py",
                ('"""A suite that states an oracle naming none of the five.\n\n'
                 "Oracle: the tests pass\n"
                 '"""\n\n\n'
                 "def test_something() -> None:\n"
                 '    """Assert."""\n'
                 "    assert True\n")),),
        targets=("tests",),
    ),
    # ------------------------------------------------------------------- ops
    #
    # `dispatch_recorded` claimed ten rules and emitted five. Now that the claim
    # is honest, each of the five gets its own mutation -- because one mechanism
    # carrying five claims is still five claims, and a single entry would leave
    # four of them resting on the other's evidence.
    #
    # Each of these trees carries an `overrides/allocation.toml`, so `ALLOC-010`
    # is satisfied and the rule under test is the only one that can fire. Without
    # it every dispatch mutation reported ALLOC-010 as well, and a mutation that
    # provokes two rules cannot say which one discriminated.
    Mutation(
        rule_id="ALLOC-002",
        summary="a dispatch record carries no signal scores at all",
        source=("The rule's own clause: score before dispatching, and record the "
                "score. A record naming a tier and no scores is the shape that "
                "cannot be audited, because nothing shows how the tier was "
                "reached."),
        base="empty",
        write=((".claude/agents/scoreless.md",
                ("---\nname: scoreless\n---\n\n# Scoreless\n\n"
                 "## Dispatch record (ops/ALLOC-002)\n\n"
                 "Dispatched at T1/E1 because it felt about right. Inputs,\n"
                 "expected output, acceptance criterion and stop condition are\n"
                 "all stated, and it holds no capability it was not granted.\n")),
               ("overrides/allocation.toml", _MAPPING)),
        targets=(".claude",),
    ),
    Mutation(
        rule_id="ALLOC-004",
        summary="a signal scores 3 and the effort floor is not raised",
        source=("The rule's clause -- a single signal at 3 raises the floor. The "
                "check reads the max over separate tier and effort patterns "
                "precisely because an earlier version read only the first "
                "allocation in the file and mis-scored three agents."),
        base="empty",
        write=((".claude/agents/unraised.md",
                ("---\nname: unraised\n---\n\n# Unraised\n\n"
                 "## Dispatch record (ops/ALLOC-002)\n\n"
                 "A=3 B=1 C=1 D=1 E=1 F=0 G=0 -> 7/21 -> T1/E0. Inputs, expected\n"
                 "output, acceptance criterion and stop condition are all stated,\n"
                 "and it holds no capability it was not granted.\n")),
               ("overrides/allocation.toml", _MAPPING)),
        targets=(".claude",),
    ),
    Mutation(
        rule_id="TEAMS-002",
        summary="a dispatch purports to grant a capability the agent does not hold",
        source=("The rule's clause, and the reason six agent definitions gained a "
                "standing-restrictions section: the cost of refusing is one wasted "
                "dispatch, and the cost of circumventing is that every verdict "
                "that agent ever issued becomes questionable."),
        base="empty",
        write=((".claude/agents/permissive.md",
                ("---\nname: permissive\ntools: Read, Grep\n---\n\n# Permissive\n\n"
                 "## Dispatch record (ops/ALLOC-002)\n\n"
                 "A=2 B=2 C=1 D=1 E=1 F=1 G=0 -> 8/21 -> T1/E1. Inputs, expected\n"
                 "output, acceptance criterion and stop condition are all stated.\n\n"
                 "You may edit any file you need to, whatever your tool list\n"
                 "says.\n")),
               ("overrides/allocation.toml", _MAPPING)),
        targets=(".claude",),
    ),

    # ------------------------------------------------- auto: import-linter
    #
    # Twenty-seven binding rules are decided by a configured tool alone. Until
    # v3.1 the matrix had no way to express one, so `D` could not cover them at
    # all -- a worse gap than a missing entry, because no amount of writing
    # entries would have closed it.
    Mutation(
        rule_id="ARCH-001",
        summary="the domain imports the shell, reversing the dependency arrow",
        source=("The rule's whole content. The layers contract is the only thing "
                "standing between a tidy diagram and a cycle, and nobody had "
                "watched it break."),
        tool="import-linter",
        diagnostic="ARCH-001 layers point inward",
        replace=(("src/refpkg/domain/plan.py",
                  "from __future__ import annotations",
                  ("from __future__ import annotations\n\n"
                   "from refpkg.shell import envelope")),),
    ),
    Mutation(
        rule_id="ARCH-003",
        summary="the clock adapter imports the files adapter",
        source=("ERR-016 and TEST-011 rest on adapters being independent: a "
                "misbehaving component cannot contaminate a healthy one only if "
                "it cannot reach it."),
        tool="import-linter",
        diagnostic="ARCH-003 adapters are independent",
        replace=(("src/refpkg/adapters/clock/real.py",
                  "from __future__ import annotations",
                  ("from __future__ import annotations\n\n"
                   "from refpkg.adapters.files import real as _files")),),
    ),
    Mutation(
        rule_id="ARCH-004",
        summary="the app reads the clock directly instead of through its adapter",
        source=("The contract shipped with an EMPTY forbidden_modules list, which "
                "forbids nothing and passes on every tree, with a comment making "
                "the vacuity look deliberate. Two rules were counted decided on a "
                "check that could not fail; this is the entry that would have "
                "caught that."),
        tool="import-linter",
        diagnostic="ARCH-004 time is cornered in the clock adapter",
        replace=(("src/refpkg/app/prune.py",
                  "from __future__ import annotations",
                  "from __future__ import annotations\n\nimport time"),),
    ),
    Mutation(
        rule_id="EFCT-001",
        summary="the app opens a socket, performing an effect outside the shell",
        source=("Writing this entry is what found that EFCT-001 was tagged "
                "`auto:import-linter` and named by NO contract. An `auto:` tag "
                "resolves to None -- not checkable -- so V080 never reported it, "
                "and the rule was decided by a tool nobody had told about it."),
        tool="import-linter",
        diagnostic="EFCT-001 effects stay in shell and adapters",
        replace=(("src/refpkg/app/prune.py",
                  "from __future__ import annotations",
                  "from __future__ import annotations\n\nimport socket"),),
    ),
    Mutation(
        rule_id="DEP-001",
        summary="the domain imports pydantic, a third-party package",
        source=("The same gap as EFCT-001, found the same way. Distinct from "
                "ARCH-013, which catches a domain type INHERITING a framework "
                "base: this catches the import itself, one layer earlier."),
        tool="import-linter",
        diagnostic="DEP-001 the domain imports no third-party package",
        replace=(("src/refpkg/domain/model.py",
                  "from __future__ import annotations",
                  "from __future__ import annotations\n\nimport pydantic"),),
    ),

    # -------------------------------------------------------- auto: ruff
    #
    # Judged against `enforce/templates/pyproject.toml`, the configuration an
    # adopter copies, because the reference carries no [tool.ruff] table of its
    # own and ruff's defaults enable none of these codes.
    Mutation(
        rule_id="ERR-008",
        summary="an except clause catches Exception and names nothing",
        source=("A PROTECTED lint code -- `BLE001` may never enter the baseline. "
                "A protected code nobody has watched fire is a protection nobody "
                "has tested."),
        tool="ruff",
        diagnostic="BLE001",
        replace=(("src/refpkg/app/prune.py",
                  "from __future__ import annotations",
                  ("from __future__ import annotations\n\n\n"
                   "def swallow() -> None:\n"
                   '    """Catch everything and say nothing.\n\n'
                   '    @return nothing\n    """\n'
                   "    try:\n        pass\n"
                   "    except Exception:\n        return")),),
    ),
    Mutation(
        rule_id="DIAG-012",
        summary="a log call formats its argument eagerly with an f-string",
        source=("`G004` is PROTECTED. DIAG-012's point is that the formatting cost "
                "is paid whether or not the record is emitted, and that the "
                "structured fields are lost to a flat string."),
        tool="ruff",
        diagnostic="G004",
        replace=(("src/refpkg/shell/cli.py",
                  "from __future__ import annotations",
                  ("from __future__ import annotations\n\nimport logging\n\n\n"
                   "def announce(what: str) -> None:\n"
                   '    """Log eagerly.\n\n    @param what the subject\n    """\n'
                   '    logging.getLogger(__name__).info(f"saw {what}")')),),
    ),
    Mutation(
        rule_id="TYPE-003",
        summary="a blanket type-ignore with no code and no justification",
        source=("`PGH003` is PROTECTED. TYPE-003 asks that escape hatches be "
                "narrow, justified and counted; a bare type-ignore is none of the "
                "three and silences everything on the line forever."),
        tool="ruff",
        diagnostic="PGH003",
        replace=(("src/refpkg/domain/plan.py",
                  "from __future__ import annotations",
                  ("from __future__ import annotations\n\n"
                   '_ANYTHING: int = "not an int"  # type: ignore')),),
    ),
    Mutation(
        rule_id="ARCH-016",
        summary="a domain function whose branching exceeds the complexity budget",
        source=("`C901` is PROTECTED, and it refused this repository's own code "
                "twice while v3.0.0 was being written -- `cmd_diagnose` and "
                "`integrate.main` both had to be decomposed. A rule that has "
                "rejected the maintainer is worth pinning."),
        tool="ruff",
        diagnostic="C901",
        replace=(("src/refpkg/domain/plan.py",
                  "from __future__ import annotations",
                  ("from __future__ import annotations\n\n\n"
                   "def tangled(n: int) -> int:\n"
                   '    """Branch past the budget.\n\n'
                   '    @param n the input\n    @return a number\n    """\n'
                   + TANGLED
                   + "    return -1")),),
    ),
    Mutation(
        rule_id="ERR-009",
        summary="the try body ends with the return that only runs on success",
        source=("`TRY300` is PROTECTED. ERR-009's point is that a return inside "
                "the try widens what the except clause is standing guard over, so "
                "a failure in the success path is caught as though it were the "
                "operation failing."),
        tool="ruff",
        diagnostic="TRY300",
        replace=(("src/refpkg/app/prune.py",
                  "from __future__ import annotations",
                  ("from __future__ import annotations\n\n\n"
                   "def widened(value: int) -> int:\n"
                   '    """Return from inside the try.\n\n'
                   "    @param value the input\n    @return the value\n"
                   '    """\n'
                   "    try:\n        _ = 1 / value\n        return value\n"
                   "    except ZeroDivisionError:\n        return 0")),),
    ),
    Mutation(
        rule_id="DOC-006",
        summary="a docstring runs its summary straight into the description",
        source=("`D205` is PROTECTED. DOC-006 asks for a brief statement first "
                "because the summary is what every tool -- the navigator "
                "included -- shows when it has room for one line."),
        tool="ruff",
        diagnostic="D205",
        replace=(("src/refpkg/domain/plan.py",
                  "from __future__ import annotations",
                  ("from __future__ import annotations\n\n\n"
                   "def crowded() -> int:\n"
                   '    """A summary\n'
                   "    and a description with no blank line between them.\n\n"
                   "    @return a number\n"
                   '    """\n'
                   "    return 1")),),
    ),

    # --------------------------------------------------------- auto: mypy
    Mutation(
        rule_id="TYPE-001",
        summary="a domain function carries no annotations at all",
        source=("The first thing `mypy --strict` reports on a package adopting "
                "the typing track -- `enforce/signals.toml` indexes this exact "
                "code against this exact rule, and nothing had ever confirmed "
                "the pairing by making it happen."),
        tool="mypy",
        diagnostic="no-untyped-def",
        replace=(("src/refpkg/domain/plan.py",
                  "from __future__ import annotations",
                  ("from __future__ import annotations\n\n\n"
                   "def unchecked(value):\n"
                   '    """A definition mypy cannot hold anyone to.\n\n'
                   "    @param value anything\n    @return anything\n"
                   '    """\n'
                   "    return value")),),
    ),
    Mutation(
        rule_id="TYPE-013",
        summary="a str is returned where the signature promises an int",
        source=("TYPE-013 asks that conversions across a boundary be explicit. "
                "The mechanical half is that an implicit one is a type error, "
                "and a checker that would not report this is a checker running "
                "in a mode that decides nothing."),
        tool="mypy",
        diagnostic="return-value",
        replace=(("src/refpkg/domain/plan.py",
                  "from __future__ import annotations",
                  ("from __future__ import annotations\n\n\n"
                   "def converted() -> int:\n"
                   '    """Promise an int, hand back a str.\n\n'
                   "    @return an int, allegedly\n"
                   '    """\n'
                   '    return "12"')),),
    ),

    # ------------------------------------------------- harvested fitness cases
    #
    # Twenty-two negative-case functions already existed across eleven suites --
    # `test_a_missing_faulty_adapter_is_caught` and its kin -- each building a
    # `broken_copy` and asserting the damage is visible. They were mutations in
    # all but name, so these entries are TRANSCRIBED rather than invented.
    #
    # The transcription is strictly stronger than the test it came from. A
    # negative case re-implements the assertion beside the real one and asserts
    # the damage landed; these point `DISCIPLINE_REFERENCE` at the damaged tree
    # and require THE TAGGED FUNCTION ITSELF to fail. A suite whose negative case
    # passes while the function it guards would not have noticed is exactly the
    # gap this matrix exists to close.
    Mutation(
        rule_id="TYPE-009",
        summary="a port publishes an ordinary class instead of a Protocol",
        source=("Transcribed from `test_a_port_without_a_protocol_is_caught`. "
                "TYPE-009's whole content is that conformance is structural: an "
                "adapter satisfying a base class must import the core to do it."),
        node="enforce/fitness/test_ports.py::test_every_port_is_a_protocol",
        write=(("src/refpkg/ports/clock.py",
                ('"""A port with no contract."""\n\n\nclass Clock:\n'
                 '    """Not a Protocol."""\n')),),
    ),
    Mutation(
        rule_id="ARCH-007",
        summary="a port is a Protocol whose docstring states no contract at all",
        source=("The other half of `test_every_port_is_a_protocol`, given its own "
                "damage so the two rules it decides are discriminated separately. "
                "ARCH-007 asks for the terms, not merely the shape."),
        node="enforce/fitness/test_ports.py::test_every_port_is_a_protocol",
        write=(("src/refpkg/ports/clock.py",
                ('"""A port that says nothing about its terms."""\n\n'
                 "from typing import Protocol\n\n\nclass Clock(Protocol):\n"
                 '    """A clock."""\n')),),
    ),
    Mutation(
        rule_id="ARCH-008",
        summary="a port loses its faulty adapter",
        source=("Transcribed from `test_a_missing_faulty_adapter_is_caught`, and "
                "the case an UNCONDITIONAL rule exists to catch: the faulty "
                "adapter is the one people argue is unnecessary."),
        node="enforce/fitness/test_ports.py::test_port_triad",
        drop=("src/refpkg/adapters/clock/faulty.py",),
    ),
    Mutation(
        rule_id="ARCH-009",
        summary="the contract suite exercises the fake and neither other adapter",
        source=("Transcribed from `test_a_suite_covering_one_adapter_is_caught`. "
                "A suite run against the fake alone tests the fake."),
        node="enforce/fitness/test_ports.py::test_contract_suite_per_adapter",
        write=(("tests/contract/test_clock_contract.py",
                ('"""Tests. Oracle: contract."""\n\n\ndef test_it():\n'
                 '    """Only the fake."""\n    assert True\n')),),
    ),
    Mutation(
        rule_id="TEST-005",
        summary="a port has no contract suite at all",
        source=("TEST-005 states ARCH-009 almost word for word, so it is given "
                "DIFFERENT damage rather than a duplicate entry: the suite is "
                "absent rather than narrow. Two rules this alike are a "
                "supersession candidate, and recording both mutations is what "
                "makes the overlap visible."),
        node="enforce/fitness/test_ports.py::test_contract_suite_per_adapter",
        drop=("tests/contract/test_clock_contract.py",),
    ),
    Mutation(
        rule_id="ARCH-010",
        summary="a port names none of the eight reasons it might exist",
        source=("Transcribed from `test_a_port_with_no_justification_is_caught`. "
                "A port with no stated justification is an indirection nobody can "
                "argue with, which is how a codebase acquires ports it does not "
                "need."),
        node="enforce/fitness/test_ports.py::test_port_justification",
        write=(("src/refpkg/ports/clock.py",
                ('"""A port that says nothing about why it exists."""\n\n'
                 "from typing import Protocol\n\n\nclass Clock(Protocol):\n"
                 '    """A clock.\n\n    Raises an error on failure.\n    """\n')),),
    ),
    Mutation(
        rule_id="EFCT-015",
        summary="a writer takes a lock and never reports losing the race",
        source=("Transcribed from `test_a_writer_that_blocks_silently_is_caught`. "
                "EFCT-015's point is that contention is a RESULT: a caller that "
                "blocks has been told nothing and cannot decide to do otherwise."),
        node="enforce/fitness/test_concurrency.py::test_single_writer",
        write=(("src/refpkg/adapters/files/locked.py",
                ('"""A store that is thread-safe and blocks."""\n\n'
                 "import threading\n\n\nclass LockedStore:\n"
                 '    """Thread-safe by a lock order of one."""\n\n'
                 '    def __init__(self):\n        """Build it."""\n'
                 "        self._lock = threading.Lock()\n")),),
    ),
    Mutation(
        rule_id="EFCT-013",
        summary="a module shares state across threads and states no semantics",
        source=("Transcribed from `test_undocumented_concurrency_is_caught`. "
                "EFCT-013 asks for ownership, ordering, cancellation, shutdown "
                "and stale-state behaviour to be written down BEFORE the "
                "component is."),
        node="enforce/fitness/test_concurrency.py::test_concurrency_documented",
        write=(("src/refpkg/adapters/files/pooled.py",
                ('"""A store that shares state across threads and says nothing."""\n\n'
                 "import threading\n\n\nclass PooledStore:\n"
                 '    """Shares a dictionary."""\n\n'
                 '    def __init__(self):\n        """Build it."""\n'
                 "        self._entries = {}\n")),),
    ),
    Mutation(
        rule_id="EFCT-006",
        summary="the applier loses the plan and recomputes what it should apply",
        source=("Transcribed from `test_an_applier_that_recomputes_is_caught`. "
                "This is the exact shape EFCT-006 forbids -- a second code path "
                "that predicts what the real one would do -- and the reason a dry "
                "run stops agreeing with the apply."),
        node="enforce/fitness/test_effects.py::test_dry_run_matches_apply",
        replace=(("src/refpkg/app/prune.py",
                  "def apply(store: FileStore, plan: Plan) -> tuple[str, ...]:",
                  "def apply(store: FileStore) -> tuple[str, ...]:"),),
    ),
    Mutation(
        rule_id="TEST-001",
        summary="a unit test imports pathlib and touches a disk",
        source=("Transcribed from `test_an_impure_unit_test_is_caught`. A unit "
                "failure the environment can cause is a unit failure that "
                "localizes nothing, which is the whole reason the layer exists."),
        node="enforce/fitness/test_layers.py::test_unit_layer_is_pure",
        write=(("tests/unit/test_impure.py",
                ('"""Tests. Oracle: example."""\n\nimport pathlib\n\n\n'
                 'def test_it():\n    """Touches a disk."""\n'
                 '    assert pathlib.Path(".").exists()\n')),),
    ),
    Mutation(
        rule_id="TEST-002",
        summary="the fault layer exists and holds no test",
        source=("Transcribed from `test_an_empty_layer_is_caught`. An empty layer "
                "is worse than a missing one: a missing directory prompts the "
                "question, an empty one answers it wrongly."),
        node="enforce/fitness/test_layers.py::test_layers_populated",
        drop=("tests/fault/test_containment.py",),
    ),
    Mutation(
        rule_id="TEST-007",
        summary="the property layer holds hand-picked examples, not generated input",
        source=("Transcribed from `test_a_property_suite_of_examples_is_caught`, "
                "which was written in v3.1 because TEST-007 had been claimed by "
                "`test_layers_populated` -- a function that counts tests per layer "
                "and cannot tell the two apart."),
        node="enforce/fitness/test_layers.py::test_property_suites_are_generated",
        write=(("tests/property/test_examples.py",
                ('"""Oracle: property."""\n\n\ndef test_round_trip():\n'
                 '    """Round trip."""\n    assert 2 + 2 == 4\n')),),
    ),
    Mutation(
        rule_id="TEST-009",
        summary="a failure mode is encoded as a single-purpose class",
        source=("Transcribed from `test_a_bespoke_fault_class_is_caught`. "
                "TEST-009 prohibits exactly this: a fault that cannot be "
                "serialized, replayed or shrunk is a fault nobody can reproduce."),
        node="enforce/fitness/test_faults.py::test_fault_schedules_are_data",
        write=(("src/refpkg/adapters/clock/bespoke.py",
                ('"""A scenario as a class."""\n\n\nclass ClockThatFailsOnce:\n'
                 '    """Fails the first time."""\n')),),
    ),
    Mutation(
        rule_id="TEST-010",
        summary="a port is left with no fault test naming it",
        source=("Transcribed from `test_an_uncovered_port_is_caught`. The fault "
                "catalogue is only a catalogue if every port appears in it."),
        node="enforce/fitness/test_faults.py::test_fault_catalogue",
        drop=("tests/fault/test_containment.py",),
    ),
    Mutation(
        rule_id="ERR-016",
        summary="the fault layer asserts that it raised and nothing about where",
        source=("Transcribed from "
                "`test_a_fault_layer_asserting_nothing_about_containment_is_caught`. "
                "A test asserting only that something raised has shown the fault "
                "escaped, not that it was contained."),
        node="enforce/fitness/test_faults.py::test_fault_containment",
        write=(("tests/fault/test_containment.py",
                ('"""Tests. Oracle: contract."""\n\nimport pytest\n\n\n'
                 'def test_it_raises():\n    """Something broke."""\n'
                 "    with pytest.raises(ValueError):\n        raise ValueError\n")),),
    ),
    Mutation(
        rule_id="TEST-008",
        summary="a golden is compared with no deliberate regeneration path",
        source=("Transcribed from `test_a_golden_with_no_deliberate_path_is_caught`. "
                "Without one, the only way to update a golden is to edit it by "
                "hand or regenerate it ambiently, and TEST-008 exists because the "
                "second stops being a review."),
        node="enforce/fitness/test_goldens.py::test_goldens_reviewed",
        write=(("tests/golden/expected.txt", "some output\n"),
               ("tests/integration/test_golden.py",
                ('"""Tests. Oracle: golden."""\n\nfrom pathlib import Path\n\n\n'
                 "def test_output_matches():\n"
                 '    """Compare against the committed file."""\n'
                 '    expected = Path("tests/golden/expected.txt").read_text()\n'
                 "    assert expected\n"))),
    ),
)


def by_rule() -> dict[str, list[Mutation]]:
    """Every mutation, grouped by the rule it must provoke.

    @return each rule id against its mutations, in declaration order
    """
    grouped: dict[str, list[Mutation]] = {}
    for mutation in MUTATIONS:
        grouped.setdefault(mutation.rule_id, []).append(mutation)
    return grouped


def covered() -> frozenset[str]:
    """Which rules have at least one declared mutation.

    @return the rule ids `D` counts
    """
    return frozenset(mutation.rule_id for mutation in MUTATIONS)
