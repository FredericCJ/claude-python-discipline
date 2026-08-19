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


## A minimal conformant module, used as the unmutated half of an `empty` entry so
## the damage is the only thing present that a check could object to.
_CLEAN_MODULE: Final = '"""A module."""\n'


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
