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
## an agent definition, a learning ledger, a generated artefact. `repository`
## copies the discipline implementation itself, for a fitness mechanism whose
## proposition is wiring in the shipped gate rather than an adopter property.
BASES: Final[frozenset[str]] = frozenset({"reference", "empty", "repository"})


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
    ## Exact automated strategy observed by this entry. It may be omitted only
    ## when the rule has one automated strategy, in which case the evidence join
    ## treats it as an unambiguous rule-local witness. Rules with several
    ## mechanisms must name one here and carry a separate entry for each.
    mechanism: str = ""
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
    ## A pytest node that directly constructs a violating input, invokes the
    ## named mechanism, and asserts this exact rule diagnostic. Unlike `node`,
    ## the proof passes when rejection is observed; no duplicated fixture damage
    ## is needed in this table because the cited test contains the mutation.
    proof: str = ""
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

## Small corpus used to discriminate the v4 evidence fitness tests without
## copying the discipline repository into each mutation workspace.
_EVID_LAW: Final = (
    "---\nid: law/EVID\nkind: law\ntitle: Evidence fixture\ntokens: 0\n"
    "decay: none\n---\n\n# Evidence fixture\n\n"
    "### EVID-900 · Fixture rule  [BINDING] [fitness:test_fixture]\n"
    "The fixture MUST remain joined.\n"
    "- **Why** The negative case needs one normative ID.\n"
    "- **Check** `pytest fixture`\n"
)
## One complete evidence record, compact because mutations replace whole files.
_EVID_RECORD: Final = (
    '{"units":["application"],"capabilities":[],"failure_mode":"lost claim",'
    '"warrants":[{"source":"fixture","relation":"supports","confidence":"high"}],'
    '"strategies":[{"mechanism":"fitness:test_fixture","kind":"behavioral",'
    '"relation":"proxy","proposition":"fixture is joined","residual":"semantic gap",'
    '"must_pass":"fixture:pass","must_reject":'
    '"discrimination:EVID-900/fitness:test_fixture",'
    '"platforms":["windows"],"not_applicable":"never"}],"observations":[],'
    '"migration":{"source":"v4.0.0","disposition":"new","guidance":"none"}}'
)
## Valid one-rule registry from which each evidence mutation changes one claim.
_EVID_REGISTRY: Final = '{"schema_version":1,"rules":{"EVID-900":' + _EVID_RECORD + "}}"
## Historical fixture whose superseded disposition deliberately lacks a successor.
_EVID_RETIRED_LAW: Final = (
    "---\nid: law/EVID\nkind: law\ntitle: Evidence fixture\ntokens: 0\n"
    "decay: none\n---\n\n# Evidence fixture\n\n"
    "### EVID-900 · Fixture rule  [RETIRED]\n"
    "The fixture is retained only as history.\n"
    "- **Why** The negative case needs one retained ID.\n"
)
## Evidence half of `_EVID_RETIRED_LAW`, intentionally inconsistent in one field.
_EVID_RETIRED_REGISTRY: Final = (
    '{"schema_version":1,"rules":{"EVID-900":{"units":["application"],'
    '"capabilities":[],"failure_mode":"lost history",'
    '"warrants":[{"source":"fixture","relation":"supports","confidence":"high"}],'
    '"strategies":[],"observations":[],"migration":{"source":"v3.3.0",'
    '"disposition":"superseded","guidance":"move to the replacement"}}}}'
)
## Empty but structurally valid observation registry for evidence fixtures.
_EVID_OBSERVATIONS: Final = '{"schema_version":1,"observations":{}}'
## Projection matching `_EVID_RECORD`, used to prove a changed residual is seen.
_EVID_RULES: Final = (
    '{"rules":[{"id":"EVID-900","verification":{"state":"local-verifier",'
    '"strategies":[{"mechanism":"fitness:test_fixture","relation":"proxy",'
    '"residual":"semantic gap"}]}}]}'
)
## Loadable matrix that deliberately credits no rule in the rejection-credit case.
_EVID_MATRIX: Final = (
    '"""Evidence discrimination fixture."""\n\n\n'
    "def covered() -> frozenset[str]:\n"
    '    """Return no credited rule.\n\n    @return empty set\n    """\n'
    "    return frozenset()\n\n\n"
    "def covered_strategies() -> frozenset[tuple[str, str]]:\n"
    '    """Return no credited strategy.\n\n    @return empty set\n    """\n'
    "    return frozenset()\n"
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
    # --------------------------------------------------------------- law/EVID
    Mutation(
        rule_id="EVID-001",
        summary="a normative stable ID has no evidence record",
        source=(
            "The rule's exact set-equality proposition: EVID-900 remains in "
            "the law module while the evidence key set is empty."
        ),
        base="empty",
        write=(
            ("discipline/law/EVID.md", _EVID_LAW),
            ("discipline/meta/evidence.json", '{"schema_version":1,"rules":{}}'),
        ),
        node="enforce/fitness/test_evidence.py::test_evidence_registry_joins_rules",
    ),
    Mutation(
        rule_id="EVID-002",
        summary="a heading mechanism has no strategy record",
        source=(
            "The rule's exact join proposition: the heading still names "
            "fitness:test_fixture and its evidence strategies array is empty."
        ),
        base="empty",
        write=(
            ("discipline/law/EVID.md", _EVID_LAW),
            (
                "discipline/meta/evidence.json",
                _EVID_REGISTRY.replace("fitness:test_fixture", "fitness:other_fixture"),
            ),
        ),
        node="enforce/fitness/test_evidence.py::test_strategy_claims_are_explicit",
    ),
    Mutation(
        rule_id="EVID-003",
        summary="the generated projection changes a proxy residual",
        source=(
            "The rule's lossless-projection clause: authored semantic gap is "
            "projected as a different residual."
        ),
        base="empty",
        write=(
            ("discipline/meta/evidence.json", _EVID_REGISTRY),
            ("discipline/rules.json", _EVID_RULES.replace("semantic gap", "residual dropped")),
        ),
        node="enforce/fitness/test_evidence.py::test_proxy_claims_preserve_residuals",
    ),
    Mutation(
        rule_id="EVID-004",
        summary="an unwitnessed rule is labeled with discrimination credit",
        source=(
            "The rule's exact subset proposition: the evidence label credits "
            "EVID-900 while the loaded matrix returns an empty set."
        ),
        base="empty",
        write=(
            (
                "discipline/meta/evidence.json",
                _EVID_REGISTRY,
            ),
            ("enforce/discrimination.py", _EVID_MATRIX),
        ),
        node="enforce/fitness/test_evidence.py::test_rejection_credit_is_witnessed",
    ),
    Mutation(
        rule_id="EVID-005",
        summary="a generated build view publishes a pass outcome",
        source=(
            "The rule's exact vocabulary boundary: a build-time verification "
            "object gains outcome=pass without executing a project gate."
        ),
        base="empty",
        write=(
            (
                "discipline/rules.json",
                _EVID_RULES.replace(
                    '"state":"local-verifier"', '"state":"local-verifier","outcome":"pass"'
                ),
            ),
        ),
        node="enforce/fitness/test_evidence.py::test_generated_rules_publish_no_gate_outcome",
    ),
    Mutation(
        rule_id="EVID-006",
        summary="a normative rule carries no warrant",
        source=(
            "The rule's minimum typed-warrant proposition: the sole record's "
            "warrants array is empty."
        ),
        base="empty",
        write=(
            (
                "discipline/meta/evidence.json",
                _EVID_REGISTRY.replace(
                    '"warrants":[{"source":"fixture","relation":"supports","confidence":"high"}]',
                    '"warrants":[]',
                ),
            ),
        ),
        node="enforce/fitness/test_evidence.py::test_warrants_are_typed",
    ),
    Mutation(
        rule_id="EVID-007",
        summary="a rule cites a field observation absent from its registry",
        source=(
            "The rule's resolution proposition: V4E-999 is cited by the rule "
            "and the packaged observation registry is empty."
        ),
        base="empty",
        write=(
            (
                "discipline/meta/evidence.json",
                _EVID_REGISTRY.replace('"observations":[]', '"observations":["V4E-999"]'),
            ),
            ("discipline/meta/observations.json", _EVID_OBSERVATIONS),
        ),
        node="enforce/fitness/test_evidence.py::test_field_observations_resolve",
    ),
    Mutation(
        rule_id="EVID-008",
        summary="a superseded disposition names no successor",
        source=(
            "The rule's migration consistency proposition: the record says "
            "superseded while the retained heading names no Superseded by ID."
        ),
        base="empty",
        write=(
            ("discipline/law/EVID.md", _EVID_RETIRED_LAW),
            ("discipline/meta/evidence.json", _EVID_RETIRED_REGISTRY),
        ),
        node="enforce/fitness/test_evidence.py::test_rule_migrations_are_total",
    ),
    # ---------------------------------------------------------------- law/ARCH
    Mutation(
        rule_id="ARCH-002",
        summary="the domain imports pathlib.Path, which can read a disk",
        source=(
            "The rule's own clause -- the domain imports nothing that can "
            "perform I/O. Phase 5 narrowed this to exempt PurePosixPath, so "
            "the still-forbidden case is pinned here against that narrowing."
        ),
        mechanism="check:domain_purity",
        replace=(
            (
                "src/refpkg/domain/model.py",
                "from __future__ import annotations",
                "from __future__ import annotations\n\nfrom pathlib import Path",
            ),
        ),
    ),
    Mutation(
        rule_id="ARCH-013",
        summary="a domain class inherits pydantic.BaseModel",
        source=(
            "The Phase 5 finding. BaseModel was listed as a foreign type from "
            "the start and the check reported nothing against four domains "
            "modelled entirely in it, because it read annotations and never "
            "bases. This is the exact shape that was invisible."
        ),
        replace=(
            (
                "src/refpkg/domain/model.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n"
                    "from pydantic import BaseModel\n\n\n"
                    "class Borrowed(BaseModel):\n"
                    '    """A domain value that is really a framework value."""\n\n'
                    "    name: str"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="ARCH-012",
        summary="a production branch reads a test switch out of the environment",
        source=(
            "Phase 5 narrowed this so a domain value spelled 'test' no longer "
            "fires. The environment-signal case is what must survive that."
        ),
        replace=(
            (
                "src/refpkg/app/prune.py",
                "from __future__ import annotations",
                "from __future__ import annotations\n\nimport os",
            ),
            (
                "src/refpkg/app/prune.py",
                "def apply(",
                (
                    "def _timeout() -> int:\n"
                    '    """Behave differently under test, which is the defect."""\n'
                    '    if os.environ.get("MODE") == "test":\n'
                    "        return 0\n"
                    "    return 30\n\n\n"
                    "def apply("
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="ARCH-015",
        summary="the domain reaches an attribute by a computed name",
        source=(
            "The rule's clause: a computed name is a branch no reader can "
            "enumerate. getattr with a variable is the canonical instance."
        ),
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n\n"
                    "def _reach(obj: object, name: str) -> object:\n"
                    '    """Reach an attribute nobody can enumerate."""\n'
                    "    return getattr(obj, name)"
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- law/TYPE
    Mutation(
        rule_id="TYPE-008",
        summary="a domain function takes a mutable list as a parameter",
        source=(
            "Built during the requalification pass: TYPE-008 tagged "
            "check:domain_purity, which claimed five rules and none of them "
            "was this one, so the rule was decided by nothing while reading "
            "as decided. The mutation is the rule's own clause -- a mutable "
            "collection in a signature is an undeclared output channel."
        ),
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n\n"
                    "def absorb(names: list[str]) -> int:\n"
                    '    """Take a list the caller still owns."""\n'
                    "    return len(names)"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="TYPE-002",
        summary="a domain signature takes Any",
        source=(
            "The rule's clause. Any in the domain is the hole the whole typing "
            "track exists to close, and a signature is what every caller is "
            "held to."
        ),
        mechanism="check:domain_purity",
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n"
                    "from typing import Any\n\n\n"
                    "def widen(value: Any) -> Any:\n"
                    '    """Accept anything, promise nothing."""\n'
                    "    return value"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="TYPE-007",
        summary="a domain dataclass is neither frozen nor slotted",
        source=(
            "Found in real code: eight dataclasses were frozen and not "
            "slotted, so the two halves of the rule need separate evidence. "
            "This drops both."
        ),
        replace=(
            ("src/refpkg/domain/model.py", "@dataclass(frozen=True, slots=True)", "@dataclass()"),
        ),
    ),
    # ----------------------------------------------------------------- law/ERR
    Mutation(
        rule_id="ERR-013",
        summary="a probe with exists() before acting on the path",
        source=(
            "The Phase 5 finding, eight times over in real code: "
            "`if target.exists(): target.unlink()` is a race, and the file can "
            "vanish between the two lines."
        ),
        replace=(
            (
                "src/refpkg/adapters/files/real.py",
                "    def delete(",
                (
                    "    def delete_racy(self, path: str) -> None:\n"
                    '        """Probe, then act, which is a race."""\n'
                    "        target = self._root / path\n"
                    "        if target.exists():\n"
                    "            target.unlink()\n\n"
                    "    def delete("
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- law/DIAG
    Mutation(
        rule_id="DIAG-002",
        summary="an exception type carries no code",
        source=(
            "The Phase 5 finding: seventeen error types in real code carried "
            "structured attributes and no code, so a consumer could match only "
            "on the class or on prose."
        ),
        replace=(
            (
                "src/refpkg/domain/errors.py",
                "class InvariantViolated",
                (
                    "class Uncoded(Exception):\n"
                    '    """A failure nothing can match on."""\n\n\n'
                    "class InvariantViolated"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="DIAG-008",
        summary="an except block swallows the exception",
        source=(
            "The rule's clause -- nothing is swallowed. A bare pass in a "
            "handler is the form that destroys the diagnostic chain entirely."
        ),
        mechanism="check:raise_from",
        replace=(
            (
                "src/refpkg/app/prune.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n\n"
                    "def _swallow() -> None:\n"
                    '    """Lose the failure."""\n'
                    "    try:\n"
                    "        raise ValueError(1)\n"
                    "    except ValueError:\n"
                    "        pass"
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- law/EFCT
    Mutation(
        rule_id="EFCT-002",
        summary="the core imports os and reaches for an effect",
        source=(
            "The rule's clause: effects are parameters, never reached for. An "
            "import in the core is the reach the rule names."
        ),
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "from __future__ import annotations",
                "from __future__ import annotations\n\nimport os",
            ),
        ),
    ),
    # ----------------------------------------------------------------- law/DOC
    Mutation(
        rule_id="DOC-001",
        summary="a public function carries no docstring",
        source=(
            "The rule's clause, and the one documentation rule that stayed "
            "universal when DOC-002 and DOC-007 became conditional on a "
            "declared engine."
        ),
        mechanism="check:doc_coverage",
        replace=(
            (
                "src/refpkg/domain/model.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n\n"
                    "def undocumented(value: int) -> int:\n"
                    "    return value"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="DOC-003",
        summary="the default project gate no longer schedules discipline checks",
        source=(
            "The rule's exact ordinary-gate clause: removing the aggregate "
            "adapter leaves documentation presence available only to an explicit "
            "caller and must fail the scheduling fitness test."
        ),
        base="repository",
        replace=(
            (
                "tools/project_gate.py",
                "    DisciplineChecksAdapter(),\n    RUFF_STEP,",
                "    RUFF_STEP,",
            ),
        ),
        node="tools/test_project_gate.py::test_ordinary_gate_schedules_documentation_presence",
    ),
    Mutation(
        rule_id="DOC-008",
        summary="a parameter's signature type is repeated in its prose contract",
        source=(
            "DOC-008's exact syntax predicate: an @param record repeats the "
            "annotated int type in parentheses instead of stating only meaning."
        ),
        replace=(
            (
                "src/refpkg/domain/model.py",
                "@param epoch_seconds whole seconds since the Unix epoch",
                "@param epoch_seconds (int) whole seconds since the Unix epoch",
            ),
        ),
    ),
    Mutation(
        rule_id="DOC-014",
        summary="a source tree has no explicit documentation-engine declaration",
        source=(
            "DOC-014's direct declaration predicate: a direct check fallback "
            "must report that engine-specific obligations are undecided."
        ),
        base="empty",
        write=(("src/pkg/module.py", '"""A documented probe module."""\n'),),
    ),
    # ---------------------------------------------------------------- law/TEST
    Mutation(
        rule_id="TEST-004",
        summary="a test module declares no oracle",
        source=(
            "The rule's clause: a test whose oracle is unstated cannot be "
            "judged for whether it tests anything."
        ),
        write=(
            (
                "tests/unit/test_nothing.py",
                (
                    '"""A suite with no stated oracle."""\n\n\n'
                    "def test_it() -> None:\n"
                    '    """Assert something."""\n'
                    "    assert True\n"
                ),
            ),
        ),
        targets=("tests",),
    ),
    Mutation(
        rule_id="TEST-014",
        summary="a decision joins four operands in one condition",
        source=(
            "The rule's clause -- combinations grow as 2^n and the untested "
            "ones are invisible. Five instances were found in real code. The "
            "operands sit in an `if` rather than a `return` because the check "
            "examines conditions, and the first draft of this entry did not: "
            "the matrix rejected it, which is what it is for."
        ),
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n\n"
                    "def tangled(a: bool, b: bool, c: bool, d: bool) -> bool:\n"
                    '    """Sixteen paths in one condition."""\n'
                    "    if a and b and c and d:\n"
                    "        return True\n"
                    "    return False"
                ),
            ),
        ),
    ),
    # ----------------------------------------------------------------- ops
    Mutation(
        rule_id="ALLOC-010",
        summary="a dispatch record cites T2 with no tier mapping anywhere above it",
        source=(
            "The case OPEN-006 called unauditable: a tier that resolves to "
            "nothing names a role rather than a choice. Built on an empty "
            "base so no allocation.toml is reachable by walking upward."
        ),
        base="empty",
        write=(
            (
                ".claude/agents/thing.md",
                (
                    "---\nname: thing\n---\n\n# Thing\n\n"
                    "## Dispatch record (ops/ALLOC-002)\n\n"
                    "A3 B2 C1 D2 E2 F1 G0 = 11 -> T2/E2\n"
                ),
            ),
        ),
        targets=(".claude",),
    ),
    # ---------------------------------------------------------------- law/FLOW
    Mutation(
        rule_id="FLOW-008",
        summary="a suppression states no reason",
        source=(
            "The Phase 5 finding: thirteen unjustified suppressions in real "
            "code, four of them a block where the author wrote the reason once "
            "and omitted it on the identical lines below."
        ),
        replace=(
            (
                "src/refpkg/domain/model.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n"
                    "import json  # ruff: ignore[unused-import]"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="FLOW-002",
        summary="a test module names no oracle at all",
        source=(
            "`oracle_declared` decides FLOW-002 and TEST-004 together; the "
            "TEST-004 entry above covers a suite with no oracle heading, and "
            "this covers the same absence seen from the workflow side, where "
            "the obligation is to NAME the oracle before writing the test."
        ),
        write=(
            (
                "tests/unit/test_unstated.py",
                (
                    '"""A suite that states an oracle naming none of the five.\n\n'
                    "Oracle: the tests pass\n"
                    '"""\n\n\n'
                    "def test_something() -> None:\n"
                    '    """Assert."""\n'
                    "    assert True\n"
                ),
            ),
        ),
        targets=("tests",),
    ),
    Mutation(
        rule_id="FLOW-012",
        summary="the report silently drops prevented not-run outcomes",
        source=(
            "The rule's including-what-did-not clause: narrowing the deviation "
            "ledger to explicit failures erases every prevented gate step even "
            "though each outcome remains known to the report."
        ),
        base="repository",
        replace=(
            (
                "tools/project_gate.py",
                "            if result.status is not Status.PASS\n",
                "            if result.status is Status.FAIL\n",
            ),
        ),
        node="tools/test_project_gate.py::test_report_records_every_non_pass_as_a_deviation",
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
        source=(
            "The rule's own clause: score before dispatching, and record the "
            "score. A record naming a tier and no scores is the shape that "
            "cannot be audited, because nothing shows how the tier was "
            "reached."
        ),
        base="empty",
        write=(
            (
                ".claude/agents/scoreless.md",
                (
                    "---\nname: scoreless\n---\n\n# Scoreless\n\n"
                    "## Dispatch record (ops/ALLOC-002)\n\n"
                    "Dispatched at T1/E1 because it felt about right. Inputs,\n"
                    "expected output, acceptance criterion and stop condition are\n"
                    "all stated, and it holds no capability it was not granted.\n"
                ),
            ),
            ("overrides/allocation.toml", _MAPPING),
        ),
        targets=(".claude",),
    ),
    Mutation(
        rule_id="ALLOC-004",
        summary="a signal scores 3 and the effort floor is not raised",
        source=(
            "The rule's clause -- a single signal at 3 raises the floor. The "
            "check reads the max over separate tier and effort patterns "
            "precisely because an earlier version read only the first "
            "allocation in the file and mis-scored three agents."
        ),
        base="empty",
        write=(
            (
                ".claude/agents/unraised.md",
                (
                    "---\nname: unraised\n---\n\n# Unraised\n\n"
                    "## Dispatch record (ops/ALLOC-002)\n\n"
                    "A=3 B=1 C=1 D=1 E=1 F=0 G=0 -> 7/21 -> T1/E0. Inputs, expected\n"
                    "output, acceptance criterion and stop condition are all stated,\n"
                    "and it holds no capability it was not granted.\n"
                ),
            ),
            ("overrides/allocation.toml", _MAPPING),
        ),
        targets=(".claude",),
    ),
    Mutation(
        rule_id="TEAMS-002",
        summary="a dispatch purports to grant a capability the agent does not hold",
        source=(
            "The rule's clause, and the reason six agent definitions gained a "
            "standing-restrictions section: the cost of refusing is one wasted "
            "dispatch, and the cost of circumventing is that every verdict "
            "that agent ever issued becomes questionable."
        ),
        base="empty",
        write=(
            (
                ".claude/agents/permissive.md",
                (
                    "---\nname: permissive\ntools: Read, Grep\n---\n\n# Permissive\n\n"
                    "## Dispatch record (ops/ALLOC-002)\n\n"
                    "A=2 B=2 C=1 D=1 E=1 F=1 G=0 -> 8/21 -> T1/E1. Inputs, expected\n"
                    "output, acceptance criterion and stop condition are all stated.\n\n"
                    "You may edit any file you need to, whatever your tool list\n"
                    "says.\n"
                ),
            ),
            ("overrides/allocation.toml", _MAPPING),
        ),
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
        source=(
            "The rule's whole content. The layers contract is the only thing "
            "standing between a tidy diagram and a cycle, and nobody had "
            "watched it break."
        ),
        mechanism="auto:import-linter",
        tool="import-linter",
        diagnostic="ARCH-001 layers point inward",
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "from __future__ import annotations",
                ("from __future__ import annotations\n\nfrom refpkg.shell import envelope"),
            ),
        ),
    ),
    Mutation(
        rule_id="ARCH-003",
        summary="the clock adapter imports the files adapter",
        source=(
            "ERR-016 and TEST-011 rest on adapters being independent: a "
            "misbehaving component cannot contaminate a healthy one only if "
            "it cannot reach it."
        ),
        mechanism="auto:import-linter",
        tool="import-linter",
        diagnostic="ARCH-003 adapters are independent",
        replace=(
            (
                "src/refpkg/adapters/clock/real.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n"
                    "from refpkg.adapters.files import real as _files"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="ARCH-004",
        summary="the app reads the clock directly instead of through its adapter",
        source=(
            "The contract shipped with an EMPTY forbidden_modules list, which "
            "forbids nothing and passes on every tree, with a comment making "
            "the vacuity look deliberate. Two rules were counted decided on a "
            "check that could not fail; this is the entry that would have "
            "caught that."
        ),
        tool="import-linter",
        diagnostic="ARCH-004 time is cornered in the clock adapter",
        replace=(
            (
                "src/refpkg/app/prune.py",
                "from __future__ import annotations",
                "from __future__ import annotations\n\nimport time",
            ),
        ),
    ),
    Mutation(
        rule_id="ARCH-018",
        summary="a new production source directory has no declared role",
        source=(
            "The v3 declaration defect observed in three component adopters: "
            "an unknown source path was silently skipped by layer-scoped checks. "
            "The mutation writes valid Python under source_roots but outside all "
            "five explicit role paths."
        ),
        write=(("src/refpkg/services/orphan.py", '"""Unowned policy."""\n'),),
    ),
    Mutation(
        rule_id="ARCH-019",
        summary="application orchestration imports a concrete clock adapter",
        source=(
            "The application may invoke effects through an injected port but may "
            "not select its implementation. This mutation crosses that exact seam "
            "without importing the foreign clock technology directly."
        ),
        replace=(
            (
                "src/refpkg/app/prune.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n"
                    "from refpkg.adapters.clock.real import SystemClock"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="ARCH-020",
        summary="the files adapter directly imports technology owned by the clock adapter",
        source=(
            "The v4 successor to ARCH-004 permits several importer modules inside "
            "one boundary and shell's transitive reach, while requiring a second "
            "adapter boundary's direct import to fail by its own diagnostic."
        ),
        replace=(
            (
                "src/refpkg/adapters/files/real.py",
                "from __future__ import annotations",
                "from __future__ import annotations\n\nimport time",
            ),
        ),
    ),
    Mutation(
        rule_id="ARCH-021",
        summary="the local architecture record declares a different governed unit",
        source=(
            "The project and architecture records jointly define one unit. A model "
            "that silently changes application to component makes every conditional "
            "obligation ambiguous."
        ),
        replace=(
            (
                "architecture.json",
                '"unit": "application"',
                '"unit": "component"',
            ),
        ),
    ),
    Mutation(
        rule_id="ARCH-022",
        summary="the declared canonical local architecture model is absent",
        source=(
            "All four local views have one declared source. Removing it must fail "
            "as missing evidence, never become a successful empty traversal."
        ),
        drop=("architecture.json",),
    ),
    Mutation(
        rule_id="ARCH-023",
        summary="a component contract identifies a peer repository by name",
        source=(
            "The roadmap's adversarial acceptance case: component contracts know "
            "roles, never counterpart repository identities or deployment wiring."
        ),
        replace=(
            (
                "pyproject.toml",
                'unit = "application"',
                'unit = "component"',
            ),
            (
                "architecture.json",
                '"unit": "application"',
                '"unit": "component"',
            ),
            (
                "architecture.json",
                '"role": "command_user"',
                '"role": "sine-generator"',
            ),
        ),
    ),
    Mutation(
        rule_id="EFCT-001",
        summary="the app opens a socket, performing an effect outside the shell",
        source=(
            "Writing this entry is what found that EFCT-001 was tagged "
            "`auto:import-linter` and named by NO contract. An `auto:` tag "
            "resolves to None -- not checkable -- so V080 never reported it, "
            "and the rule was decided by a tool nobody had told about it."
        ),
        tool="import-linter",
        diagnostic="EFCT-001 effects stay in shell and adapters",
        replace=(
            (
                "src/refpkg/app/prune.py",
                "from __future__ import annotations",
                "from __future__ import annotations\n\nimport socket",
            ),
        ),
    ),
    Mutation(
        rule_id="DEP-001",
        summary="the domain imports pydantic, a third-party package",
        source=(
            "The same gap as EFCT-001, found the same way. Distinct from "
            "ARCH-013, which catches a domain type INHERITING a framework "
            "base: this catches the import itself, one layer earlier."
        ),
        tool="import-linter",
        diagnostic="DEP-001 the domain imports no third-party package",
        replace=(
            (
                "src/refpkg/domain/model.py",
                "from __future__ import annotations",
                "from __future__ import annotations\n\nimport pydantic",
            ),
        ),
    ),
    # -------------------------------------------------------- auto: ruff
    #
    # Judged against `enforce/templates/pyproject.toml`, the configuration an
    # adopter copies, because the reference carries no [tool.ruff] table of its
    # own and ruff's defaults enable none of these codes.
    Mutation(
        rule_id="ERR-008",
        summary="an except clause catches Exception and names nothing",
        source=(
            "A PROTECTED lint code -- `BLE001` may never enter the baseline. "
            "A protected code nobody has watched fire is a protection nobody "
            "has tested."
        ),
        tool="ruff",
        diagnostic="BLE001",
        replace=(
            (
                "src/refpkg/app/prune.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n\n"
                    "def swallow() -> None:\n"
                    '    """Catch everything and say nothing.\n\n'
                    '    @return nothing\n    """\n'
                    "    try:\n        pass\n"
                    "    except Exception:\n        return"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="DIAG-012",
        summary="a log call formats its argument eagerly with an f-string",
        source=(
            "`G004` is PROTECTED. DIAG-012's point is that the formatting cost "
            "is paid whether or not the record is emitted, and that the "
            "structured fields are lost to a flat string."
        ),
        tool="ruff",
        diagnostic="G004",
        replace=(
            (
                "src/refpkg/shell/cli.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\nimport logging\n\n\n"
                    "def announce(what: str) -> None:\n"
                    '    """Log eagerly.\n\n    @param what the subject\n    """\n'
                    '    logging.getLogger(__name__).info(f"saw {what}")'
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="TYPE-003",
        summary="a blanket type-ignore with no code and no justification",
        source=(
            "`PGH003` is PROTECTED. TYPE-003 asks that escape hatches be "
            "narrow, justified and counted; a bare type-ignore is none of the "
            "three and silences everything on the line forever."
        ),
        mechanism="auto:ruff:PGH003",
        tool="ruff",
        diagnostic="PGH003",
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n"
                    '_ANYTHING: int = "not an int"  # type: ignore'
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="ARCH-016",
        summary="a domain function whose branching exceeds the complexity budget",
        source=(
            "`C901` is PROTECTED, and it refused this repository's own code "
            "twice while v3.0.0 was being written -- `cmd_diagnose` and "
            "`integrate.main` both had to be decomposed. A rule that has "
            "rejected the maintainer is worth pinning."
        ),
        tool="ruff",
        diagnostic="C901",
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n\n"
                    "def tangled(n: int) -> int:\n"
                    '    """Branch past the budget.\n\n'
                    '    @param n the input\n    @return a number\n    """\n'
                    + TANGLED
                    + "    return -1"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="ERR-009",
        summary="the try body ends with the return that only runs on success",
        source=(
            "`TRY300` is PROTECTED. ERR-009's point is that a return inside "
            "the try widens what the except clause is standing guard over, so "
            "a failure in the success path is caught as though it were the "
            "operation failing."
        ),
        tool="ruff",
        diagnostic="TRY300",
        replace=(
            (
                "src/refpkg/app/prune.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n\n"
                    "def widened(value: int) -> int:\n"
                    '    """Return from inside the try.\n\n'
                    "    @param value the input\n    @return the value\n"
                    '    """\n'
                    "    try:\n        _ = 1 / value\n        return value\n"
                    "    except ZeroDivisionError:\n        return 0"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="DOC-006",
        summary="a docstring runs its summary straight into the description",
        source=(
            "`D205` is PROTECTED. DOC-006 asks for a brief statement first "
            "because the summary is what every tool -- the navigator "
            "included -- shows when it has room for one line."
        ),
        tool="ruff",
        diagnostic="D205",
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n\n"
                    "def crowded() -> int:\n"
                    '    """A summary\n'
                    "    and a description with no blank line between them.\n\n"
                    "    @return a number\n"
                    '    """\n'
                    "    return 1"
                ),
            ),
        ),
    ),
    # --------------------------------------------------------- auto: mypy
    Mutation(
        rule_id="TYPE-001",
        summary="a domain function carries no annotations at all",
        source=(
            "The first thing `mypy --strict` reports on a package adopting "
            "the typing track -- `enforce/signals.toml` indexes this exact "
            "code against this exact rule, and nothing had ever confirmed "
            "the pairing by making it happen."
        ),
        mechanism="auto:mypy",
        tool="mypy",
        diagnostic="no-untyped-def",
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n\n"
                    "def unchecked(value):\n"
                    '    """A definition mypy cannot hold anyone to.\n\n'
                    "    @param value anything\n    @return anything\n"
                    '    """\n'
                    "    return value"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="TYPE-013",
        summary="a str is returned where the signature promises an int",
        source=(
            "TYPE-013 asks that conversions across a boundary be explicit. "
            "The mechanical half is that an implicit one is a type error, "
            "and a checker that would not report this is a checker running "
            "in a mode that decides nothing."
        ),
        tool="mypy",
        diagnostic="return-value",
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n\n"
                    "def converted() -> int:\n"
                    '    """Promise an int, hand back a str.\n\n'
                    "    @return an int, allegedly\n"
                    '    """\n'
                    '    return "12"'
                ),
            ),
        ),
    ),
    # --------------------------------------- boundary-conformance model cases
    #
    # These mutations damage the canonical v4 registry, then invoke the checker
    # through the same aggregate discovery path an adopter uses. Each isolates
    # one proposition: source representation, capability union, or shared-suite
    # parameter coverage.
    Mutation(
        rule_id="ARCH-024",
        summary="a structural boundary is relabeled nominal without changing source",
        source=(
            "ARCH-024's exact representation predicate: the registry selects "
            "nominal while Clock still derives from Protocol."
        ),
        replace=(
            (
                "contract-conformance.json",
                '"representation": "structural"',
                '"representation": "nominal"',
            ),
        ),
    ),
    Mutation(
        rule_id="ARCH-025",
        summary="one internal contract loses all scheduled-fault capability",
        source=(
            "ARCH-025 permits one test implementation to combine capabilities "
            "but still requires scheduled failure to remain observable."
        ),
        replace=(
            (
                "contract-conformance.json",
                '"controllable",\n            "scheduled_fault"',
                '"controllable"',
            ),
        ),
    ),
    Mutation(
        rule_id="TEST-020",
        summary="a registered implementation names no parameter in its shared suite",
        source=(
            "TEST-020's exact registry predicate: every implementation parameter "
            "must be visible in the one declared suite."
        ),
        replace=(
            (
                "contract-conformance.json",
                '"parameter": "faulty-healthy"',
                '"parameter": "not-in-suite"',
            ),
        ),
    ),
    Mutation(
        rule_id="OPS-001",
        summary="subprocess lifecycle ownership is enabled without launch authority",
        source=(
            "OPS-001's closed relationship: lifecycle ownership is meaningful only "
            "for a repository that also declares subprocess launch."
        ),
        replace=(
            (
                "pyproject.toml",
                "owns_subprocess_lifecycle = false",
                "owns_subprocess_lifecycle = true",
            ),
        ),
    ),
    Mutation(
        rule_id="OPS-002",
        summary="filesystem behavior remains while filesystem_io is declared false",
        source=(
            "OPS-002's one-way inference predicate: the reference file adapter "
            "imports filesystem vocabulary and calls unlink."
        ),
        replace=(
            (
                "pyproject.toml",
                "filesystem_io = true",
                "filesystem_io = false",
            ),
        ),
    ),
    Mutation(
        rule_id="OPS-003",
        summary="an operational capability cites an absent architecture recovery",
        source=(
            "OPS-003's local join predicate: the capability record names a "
            "recovery identity that architecture.json does not own."
        ),
        replace=(
            (
                "operational-model.json",
                '"recoveries": ["apply_interrupted"]',
                '"recoveries": ["peer_recovers_it"]',
            ),
        ),
    ),
    Mutation(
        rule_id="OPS-004",
        summary="destructive work excuses its interruption phase",
        source=(
            "OPS-004 requires executable interruption evidence when destructive "
            "effects are active; a prose excuse cannot satisfy that phase."
        ),
        replace=(
            (
                "operational-model.json",
                (
                    '"test": "tests/fault/test_containment.py::'
                    'test_an_interrupted_apply_reports_how_far_it_got",\n'
                    '      "not_applicable": null'
                ),
                ('"test": null,\n      "not_applicable": "Interruption is delegated elsewhere."'),
            ),
        ),
    ),
    Mutation(
        rule_id="OPS-005",
        summary="every declared terminal outcome is exception-only",
        source=(
            "OPS-005's ordinary-outcome predicate: changing preview completion to "
            "exceptional leaves no observable non-exception terminal outcome."
        ),
        replace=(
            (
                "operational-model.json",
                '"id": "preview_complete",\n      "exceptional": false',
                '"id": "preview_complete",\n      "exceptional": true',
            ),
        ),
    ),
    Mutation(
        rule_id="OPS-006",
        summary="the public input surface replaces its finite limit with prose",
        source=(
            "OPS-006 requires a measured finite input-size budget because public_api "
            "is true; a not-applicable rationale cannot override activation."
        ),
        replace=(
            (
                "operational-model.json",
                (
                    '"bound": {"value": 10000, "unit": "items"},\n'
                    '      "not_applicable": null,\n'
                    '      "measurement": "tests/unit/test_plan.py::'
                    'test_planning_refuses_work_beyond_its_input_and_cleanup_budget"'
                ),
                (
                    '"bound": null,\n'
                    '      "not_applicable": "The public surface accepts every size.",\n'
                    '      "measurement": null'
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="OPS-007",
        summary="runtime identity reports a version without a build id",
        source=(
            "OPS-007's exact identity predicate requires both version and build_id; "
            "the version alone cannot distinguish two builds of one release."
        ),
        replace=(
            (
                "operational-model.json",
                '"runtime_fields": ["version", "build_id"]',
                '"runtime_fields": ["version"]',
            ),
        ),
    ),
    Mutation(
        rule_id="OPS-008",
        summary="a public capability substitutes an unknown obligation id",
        source=(
            "OPS-008's closed generated-set predicate: replacing installed_surface "
            "simultaneously leaves one required id missing and one stale id present."
        ),
        replace=(
            (
                "operational-model.json",
                '"id": "installed_surface"',
                '"id": "source_tree_surface"',
            ),
        ),
    ),
    Mutation(
        rule_id="SEC-001",
        summary="a trust boundary cites a contract absent from local architecture",
        source=(
            "SEC-001's exact coverage predicate: replacing prune_command leaves the "
            "published contract uncovered and introduces one unknown contract id."
        ),
        replace=(
            (
                "security-model.json",
                '"contracts": ["prune_command"]',
                '"contracts": ["peer_command"]',
            ),
        ),
    ),
    Mutation(
        rule_id="SEC-002",
        summary="a secret data class remains under sensitive_data false",
        source=(
            "SEC-002's capability-coherence predicate: a secret classification "
            "directly refutes the model's explicit sensitive-data absence."
        ),
        replace=(
            (
                "security-model.json",
                '"classification": "internal"',
                '"classification": "secret"',
            ),
        ),
    ),
    Mutation(
        rule_id="SEC-003",
        summary="a review substitutes another algorithm for the closed scope digest",
        source=(
            "SEC-003 fixes both the selected inputs and digest algorithm; changing "
            "sha256 means the artifact no longer matches the recomputed snapshot."
        ),
        replace=(
            (
                "adversarial-review.json",
                '"algorithm": "sha256"',
                '"algorithm": "sha1"',
            ),
        ),
    ),
    Mutation(
        rule_id="SEC-004",
        summary="the declared adversarial reviewer is also the change author",
        source=(
            "SEC-004's mechanically decidable separation predicate: the same stable "
            "identity cannot occur in both the authors list and reviewer record."
        ),
        replace=(
            (
                "adversarial-review.json",
                '"identity": "reference_adversarial_reviewer"',
                '"identity": "reference_fixture_author"',
            ),
        ),
    ),
    Mutation(
        rule_id="EFCT-015",
        summary="a writer takes a lock and never reports losing the race",
        source=(
            "Transcribed from `test_a_writer_that_blocks_silently_is_caught`. "
            "EFCT-015's point is that contention is a RESULT: a caller that "
            "blocks has been told nothing and cannot decide to do otherwise."
        ),
        node="enforce/fitness/test_concurrency.py::test_single_writer",
        write=(
            (
                "src/refpkg/adapters/files/locked.py",
                (
                    '"""A store that is thread-safe and blocks."""\n\n'
                    "import threading\n\n\nclass LockedStore:\n"
                    '    """Thread-safe by a lock order of one."""\n\n'
                    '    def __init__(self):\n        """Build it."""\n'
                    "        self._lock = threading.Lock()\n"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="EFCT-013",
        summary="a module shares state across threads and states no semantics",
        source=(
            "Transcribed from `test_undocumented_concurrency_is_caught`. "
            "EFCT-013 asks for ownership, ordering, cancellation, shutdown "
            "and stale-state behaviour to be written down BEFORE the "
            "component is."
        ),
        node="enforce/fitness/test_concurrency.py::test_concurrency_documented",
        write=(
            (
                "src/refpkg/adapters/files/pooled.py",
                (
                    '"""A store that shares state across threads and says nothing."""\n\n'
                    "import threading\n\n\nclass PooledStore:\n"
                    '    """Shares a dictionary."""\n\n'
                    '    def __init__(self):\n        """Build it."""\n'
                    "        self._entries = {}\n"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="EFCT-006",
        summary="the applier loses the plan and recomputes what it should apply",
        source=(
            "Transcribed from `test_an_applier_that_recomputes_is_caught`. "
            "This is the exact shape EFCT-006 forbids -- a second code path "
            "that predicts what the real one would do -- and the reason a dry "
            "run stops agreeing with the apply."
        ),
        node="enforce/fitness/test_effects.py::test_dry_run_matches_apply",
        replace=(
            (
                "src/refpkg/app/prune.py",
                "def apply(store: FileStore, plan: Plan) -> tuple[str, ...]:",
                "def apply(store: FileStore) -> tuple[str, ...]:",
            ),
        ),
    ),
    Mutation(
        rule_id="TEST-001",
        summary="a unit test imports pathlib and touches a disk",
        source=(
            "Transcribed from `test_an_impure_unit_test_is_caught`. A unit "
            "failure the environment can cause is a unit failure that "
            "localizes nothing, which is the whole reason the layer exists."
        ),
        node="enforce/fitness/test_layers.py::test_unit_layer_is_pure",
        write=(
            (
                "tests/unit/test_impure.py",
                (
                    '"""Tests. Oracle: example."""\n\nimport pathlib\n\n\n'
                    'def test_it():\n    """Touches a disk."""\n'
                    '    assert pathlib.Path(".").exists()\n'
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="TEST-002",
        summary="the fault layer exists and holds no test",
        source=(
            "Transcribed from `test_an_empty_layer_is_caught`. An empty layer "
            "is worse than a missing one: a missing directory prompts the "
            "question, an empty one answers it wrongly."
        ),
        node="enforce/fitness/test_layers.py::test_layers_populated",
        drop=("tests/fault/test_containment.py",),
    ),
    Mutation(
        rule_id="TEST-007",
        summary="the property layer holds hand-picked examples, not generated input",
        source=(
            "Transcribed from `test_a_property_suite_of_examples_is_caught`, "
            "which was written in v3.1 because TEST-007 had been claimed by "
            "`test_layers_populated` -- a function that counts tests per layer "
            "and cannot tell the two apart."
        ),
        node="enforce/fitness/test_layers.py::test_property_suites_are_generated",
        write=(
            (
                "tests/property/test_examples.py",
                (
                    '"""Oracle: property."""\n\n\ndef test_round_trip():\n'
                    '    """Round trip."""\n    assert 2 + 2 == 4\n'
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="TEST-009",
        summary="a failure mode is encoded as a single-purpose class",
        source=(
            "Transcribed from `test_a_bespoke_fault_class_is_caught`. "
            "TEST-009 prohibits exactly this: a fault that cannot be "
            "serialized, replayed or shrunk is a fault nobody can reproduce."
        ),
        node="enforce/fitness/test_faults.py::test_fault_schedules_are_data",
        write=(
            (
                "src/refpkg/adapters/clock/bespoke.py",
                (
                    '"""A scenario as a class."""\n\n\nclass ClockThatFailsOnce:\n'
                    '    """Fails the first time."""\n'
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="TEST-010",
        summary="a port is left with no fault test naming it",
        source=(
            "Transcribed from `test_an_uncovered_port_is_caught`. The fault "
            "catalogue is only a catalogue if every port appears in it."
        ),
        node="enforce/fitness/test_faults.py::test_fault_catalogue",
        drop=("tests/fault/test_containment.py",),
    ),
    Mutation(
        rule_id="ERR-016",
        summary="the fault layer asserts that it raised and nothing about where",
        source=(
            "Transcribed from "
            "`test_a_fault_layer_asserting_nothing_about_containment_is_caught`. "
            "A test asserting only that something raised has shown the fault "
            "escaped, not that it was contained."
        ),
        node="enforce/fitness/test_faults.py::test_fault_containment",
        write=(
            (
                "tests/fault/test_containment.py",
                (
                    '"""Tests. Oracle: contract."""\n\nimport pytest\n\n\n'
                    'def test_it_raises():\n    """Something broke."""\n'
                    "    with pytest.raises(ValueError):\n        raise ValueError\n"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="TEST-008",
        summary="a golden is compared with no deliberate regeneration path",
        source=(
            "Transcribed from `test_a_golden_with_no_deliberate_path_is_caught`. "
            "Without one, the only way to update a golden is to edit it by "
            "hand or regenerate it ambiently, and TEST-008 exists because the "
            "second stops being a review."
        ),
        node="enforce/fitness/test_goldens.py::test_goldens_reviewed",
        write=(
            ("tests/golden/expected.txt", "some output\n"),
            (
                "tests/integration/test_golden.py",
                (
                    '"""Tests. Oracle: golden."""\n\nfrom pathlib import Path\n\n\n'
                    "def test_output_matches():\n"
                    '    """Compare against the committed file."""\n'
                    '    expected = Path("tests/golden/expected.txt").read_text()\n'
                    "    assert expected\n"
                ),
            ),
        ),
    ),
    # ------------------------------------------- direct companion-test proofs
    #
    # These tests own their violating snippets and assert the exact rule ID
    # emitted by the named mechanism. Referencing them avoids copying a second,
    # drifting version of the same mutation into this table.
    Mutation(
        rule_id="ALLOC-001",
        summary="a doctrine document names a concrete model",
        source=(
            "The companion inserts a model name into governed prose and asserts "
            "that no_model_names emits ALLOC-001 for that exact textual leak."
        ),
        proof="enforce/checks/test_ledger_checks.py::test_a_model_named_in_prose_fires",
    ),
    Mutation(
        rule_id="ALLOC-003",
        summary="a named dispatch category understates its computed tier",
        source=(
            "The companion supplies a category below its mechanical score and "
            "asserts the distinct ALLOC-003 diagnostic, not merely any dispatch finding."
        ),
        proof="enforce/checks/test_phase2_checks.py::test_a_named_category_below_t2_fires",
    ),
    Mutation(
        rule_id="TEAMS-001",
        summary="a dispatch record states no verifiable contract",
        source=(
            "The companion removes the concrete dispatch contract and asserts "
            "TEAMS-001, exercising the rule's verifiable-assignment predicate."
        ),
        proof="enforce/checks/test_phase2_checks.py::test_a_dispatch_with_no_contract_fires",
    ),
    Mutation(
        rule_id="API-003",
        summary="a public signature exposes a concrete storage type",
        source=(
            "The companion puts a storage implementation in a public operation's "
            "signature and asserts API-003 from the single-wiring-point checker."
        ),
        proof="enforce/checks/test_phase2_checks.py::test_a_storage_type_in_a_public_signature_fires",
    ),
    Mutation(
        rule_id="ARCH-005",
        summary="application policy reaches directly for a system clock",
        source=(
            "The companion makes application code acquire time ambiently and "
            "asserts ARCH-005, the explicit-effect acquisition diagnostic."
        ),
        proof="enforce/checks/test_phase2_checks.py::test_the_app_reaching_for_a_clock_fires",
    ),
    Mutation(
        rule_id="ARCH-011",
        summary="application policy imports a concrete adapter",
        source=(
            "The companion reverses the application-to-adapter boundary and "
            "asserts ARCH-011 rather than crediting a generic import failure."
        ),
        proof="enforce/checks/test_phase2_checks.py::test_the_app_importing_an_adapter_fires",
    ),
    Mutation(
        rule_id="DOC-002",
        summary="a module constant has no documentation block",
        source=(
            "The companion declares Doxygen, creates an undocumented named value, "
            "and asserts the exact DOC-002 documentation-coverage finding."
        ),
        proof="enforce/checks/test_doc_checks.py::test_an_undocumented_module_constant_fires",
    ),
    Mutation(
        rule_id="DOC-004",
        summary="a hash block substitutes for a callable docstring",
        source=(
            "The companion documents a docstring-capable element with a hash block "
            "and asserts DOC-004, the form violation the rule describes."
        ),
        proof="enforce/checks/test_doc_checks.py::test_a_hash_block_where_a_docstring_belongs_fires",
    ),
    Mutation(
        rule_id="DOC-007",
        summary="a callable docstring omits one parameter",
        source=(
            "The companion supplies an otherwise documented function, omits one "
            "parameter record, and asserts DOC-007 from doc_coverage."
        ),
        proof="enforce/checks/test_doc_checks.py::test_an_undocumented_parameter_fires",
    ),
    Mutation(
        rule_id="DOC-009",
        summary="documentation merely restates the element name",
        source=(
            "The companion uses self-describing prose with no contract content and "
            "asserts DOC-009, directly exercising doc_style's detectable proxy."
        ),
        proof="enforce/checks/test_doc_checks.py::test_documentation_that_restates_the_name_fires",
    ),
    Mutation(
        rule_id="DIAG-003",
        summary="an exception formats detail into prose only",
        source=(
            "The companion defines an exception whose data is irretrievably "
            "formatted into text and asserts the DIAG-003 structural diagnostic."
        ),
        proof="enforce/checks/test_phase2_checks.py::test_an_exception_that_only_formats_fires",
    ),
    Mutation(
        rule_id="DIAG-005",
        summary="a translated exception drops its causal chain",
        source=(
            "The companion raises a replacement error without `from` and asserts "
            "DIAG-005, the exact cause-preservation syntax predicate."
        ),
        proof="enforce/checks/test_checks.py::test_raise_without_from_fires",
    ),
    Mutation(
        rule_id="DIAG-007",
        summary="cause suppression carries no documented reason",
        source=(
            "The companion uses `raise ... from None` without the required local "
            "justification and asserts the distinct DIAG-007 finding."
        ),
        proof="enforce/checks/test_checks.py::test_from_none_without_reason_fires",
    ),
    Mutation(
        rule_id="DIAG-010",
        summary="one layer logs a failure and then re-raises it",
        source=(
            "The companion logs inside an exception handler before re-raising and "
            "asserts DIAG-010, witnessing duplicate-incident detection."
        ),
        proof="enforce/checks/test_safety_checks.py::test_logging_and_reraising_fires",
    ),
    Mutation(
        rule_id="DIAG-011",
        summary="library code configures the process logging policy",
        source=(
            "The companion calls logging configuration from library-shaped code "
            "and asserts DIAG-011, the shell-ownership predicate."
        ),
        proof="enforce/checks/test_phase2_checks.py::test_library_code_configuring_logging_fires",
    ),
    Mutation(
        rule_id="DIAG-014",
        summary="a value named as a secret is passed to a logger",
        source=(
            "The companion routes a secret-classified identifier to logging and "
            "asserts DIAG-014, the static redaction-boundary proxy."
        ),
        proof="enforce/checks/test_safety_checks.py::test_a_secret_passed_to_a_logger_fires",
    ),
    Mutation(
        rule_id="DIAG-015",
        summary="a logging call interpolates an exception eagerly",
        source=(
            "The companion formats the exception into the log string and asserts "
            "DIAG-015, preserving the exact structured-logging predicate."
        ),
        mechanism="check:log_once",
        proof="enforce/checks/test_safety_checks.py::test_interpolating_the_exception_fires",
    ),
    Mutation(
        rule_id="ERR-001",
        summary="one operation mixes an explicit result union with raised failure",
        source=(
            "The companion gives a callable both a typed result channel and a raise "
            "path, then asserts ERR-001 for the mixed-channel ambiguity."
        ),
        proof="enforce/checks/test_phase2_checks.py::test_a_result_union_that_also_raises_fires",
    ),
    Mutation(
        rule_id="ERR-004",
        summary="a governed layer raises an unowned built-in exception",
        source=(
            "The companion raises a bare built-in from layer code and asserts "
            "ERR-004, the rule-specific ownership diagnostic."
        ),
        proof="enforce/checks/test_phase2_checks.py::test_a_layer_raising_a_bare_builtin_fires",
    ),
    Mutation(
        rule_id="ERR-006",
        summary="a public exception sits outside the project hierarchy",
        source=(
            "The companion defines a project exception outside its declared root "
            "hierarchy and asserts ERR-006 from exception_shape."
        ),
        proof="enforce/checks/test_phase2_checks.py::test_an_exception_outside_the_hierarchy_fires",
    ),
    Mutation(
        rule_id="ERR-010",
        summary="only the first of several collected failures is raised",
        source=(
            "The companion accumulates several failures but raises one element and "
            "asserts ERR-010, directly witnessing lost aggregate diagnostics."
        ),
        proof="enforce/checks/test_phase2_checks.py::test_raising_one_of_several_collected_failures_fires",
    ),
    Mutation(
        rule_id="ERR-012",
        summary="an assertion validates caller-controlled input",
        source=(
            "The companion asserts over a parameter and requires ERR-012, the "
            "exact boundary-validation misuse rather than any assertion finding."
        ),
        proof="enforce/checks/test_checks.py::test_assert_on_a_parameter_fires",
    ),
    Mutation(
        rule_id="TYPE-005",
        summary="NewType is presented as runtime boundary validation",
        source=(
            "The companion uses NewType where construction cannot enforce the "
            "stated constraint and asserts TYPE-005 from boundary_parsing."
        ),
        proof="enforce/checks/test_safety_checks.py::test_newtype_fires",
    ),
    Mutation(
        rule_id="TYPE-010",
        summary="isinstance against a protocol substitutes shape for parsing",
        source=(
            "The companion treats a runtime protocol check as boundary validation "
            "and asserts TYPE-010, the exact shallow-shape predicate."
        ),
        proof="enforce/checks/test_safety_checks.py::test_isinstance_against_a_protocol_fires",
    ),
    Mutation(
        rule_id="TYPE-006",
        summary="a domain Literal union substitutes for a semantic value type",
        source=(
            "The companion places a primitive Literal union in the domain and "
            "asserts TYPE-006 from the domain-purity mechanism."
        ),
        mechanism="check:domain_purity",
        proof="enforce/checks/test_checks.py::test_domain_literal_union_fires",
    ),
    Mutation(
        rule_id="EFCT-005",
        summary="application code performs destructive work without a plan gate",
        source=(
            "The companion performs an ungated destructive call in application "
            "policy and asserts EFCT-005 from the plan/apply checker."
        ),
        proof="enforce/checks/test_phase2_checks.py::test_ungated_destruction_in_the_app_fires",
    ),
    Mutation(
        rule_id="EFCT-008",
        summary="documentation makes an unqualified atomicity claim",
        source=(
            "The companion writes a bare atomicity guarantee without boundary or "
            "failure qualification and asserts EFCT-008."
        ),
        proof="enforce/checks/test_ledger_checks.py::test_a_bare_atomicity_claim_fires",
    ),
    Mutation(
        rule_id="EFCT-010",
        summary="state is compared to an open string value",
        source=(
            "The companion branches on a stringly state rather than a closed type "
            "and asserts EFCT-010 from plan_apply."
        ),
        proof="enforce/checks/test_phase2_checks.py::test_a_state_compared_to_a_string_fires",
    ),
    Mutation(
        rule_id="DEP-007",
        summary="a generated artifact names no generator",
        source=(
            "The companion marks a committed file as generated without provenance "
            "and asserts DEP-007 from generated_provenance."
        ),
        proof="enforce/checks/test_ledger_checks.py::test_a_generated_file_naming_no_generator_fires",
    ),
    Mutation(
        rule_id="DEP-008",
        summary="a generated artifact carries a generation timestamp",
        source=(
            "The companion adds an ambient generation stamp and asserts DEP-008, "
            "the byte-instability predicate implemented by generated_provenance."
        ),
        proof="enforce/checks/test_ledger_checks.py::test_a_generation_stamp_fires",
    ),
    Mutation(
        rule_id="LEARN-001",
        summary="a completed session records no learning outcome",
        source=(
            "The companion supplies a session with no record and asserts LEARN-001 "
            "from the session-recorded check."
        ),
        proof="enforce/checks/test_ledger_checks.py::test_a_session_that_recorded_nothing_fires",
    ),
    Mutation(
        rule_id="LEARN-004",
        summary="a learning entry states no applicability scope",
        source=(
            "The companion writes an unscoped learning and asserts LEARN-004, the "
            "exact retrievability-boundary diagnostic."
        ),
        proof="enforce/checks/test_ledger_checks.py::test_an_unscoped_learning_fires",
    ),
    Mutation(
        rule_id="LEARN-005",
        summary="the append-only ledger contains a sequence gap",
        source=(
            "The companion creates a missing sequence number and asserts LEARN-005, "
            "witnessing append-only identity continuity."
        ),
        proof="enforce/checks/test_ledger_checks.py::test_a_gap_in_the_sequence_fires",
    ),
    Mutation(
        rule_id="LEARN-009",
        summary="a verified high-confidence learning remains unpromoted",
        source=(
            "The companion puts an eligible verified learning over the promotion "
            "threshold and asserts LEARN-009 from promotion_due."
        ),
        proof="enforce/checks/test_ledger_checks.py::test_a_verified_learning_over_the_bar_fires",
    ),
    Mutation(
        rule_id="LEARN-010",
        summary="the active learning set exceeds its declared bound",
        source=(
            "The companion builds an oversized active set and asserts LEARN-010, "
            "the finite-context budget enforced by learning_size."
        ),
        proof="enforce/checks/test_ledger_checks.py::test_an_oversized_active_set_fires",
    ),
    Mutation(
        rule_id="TEST-016",
        summary="a skipped test supplies no reason",
        source=(
            "The companion adds an unexplained skip and asserts TEST-016, one of "
            "the rule's explicit silent-weakening shapes."
        ),
        proof="enforce/checks/test_ledger_checks.py::test_a_skip_without_a_reason_fires",
    ),
    # ---------------------------------------- damaged fitness-test references
    Mutation(
        rule_id="API-001",
        summary="a protocol docstring states no result contract",
        source=(
            "The fitness mechanism requires a non-void protocol method to state "
            "its result; this replaces that contract with a title-only docstring."
        ),
        replace=(
            (
                "src/refpkg/ports/clock.py",
                (
                    '        """The current instant.\n\n'
                    "        @return the current instant, at or after the epoch\n"
                    "        @throws ClockUnavailable when no reading can be taken\n"
                    '        """'
                ),
                '        """The current instant."""',
            ),
        ),
        node="enforce/fitness/test_api.py::test_contract_documented",
    ),
    Mutation(
        rule_id="API-002",
        summary="a protocol method acquires an implementation body",
        source=(
            "The mechanism permits documentation plus ellipsis only; replacing "
            "that ellipsis with a return makes the contract carry implementation."
        ),
        replace=(
            (
                "src/refpkg/ports/clock.py",
                (
                    "        @throws ClockUnavailable when no reading can be taken\n"
                    '        """\n        ...'
                ),
                (
                    "        @throws ClockUnavailable when no reading can be taken\n"
                    '        """\n        return Instant(0)'
                ),
            ),
        ),
        node="enforce/fitness/test_api.py::test_contract_documented",
    ),
    Mutation(
        rule_id="API-005",
        summary="the entry point exposes no recognized result renderer",
        source=(
            "The structured-output mechanism requires an explicit renderer at "
            "the boundary; renaming it removes that observable shared interface."
        ),
        replace=(
            (
                "src/refpkg/shell/cli.py",
                "def render(payload: dict[str, Any], *, as_json: bool) -> str:",
                "def display(payload: dict[str, Any], *, as_json: bool) -> str:",
            ),
        ),
        node="enforce/fitness/test_api.py::test_structured_output",
    ),
    Mutation(
        rule_id="API-006",
        summary="the human renderer no longer accepts the result object",
        source=(
            "The mechanism recognizes payload/result/data parameters as the shared "
            "object seam; renaming the renderer input removes that exact evidence."
        ),
        replace=(
            (
                "src/refpkg/shell/cli.py",
                "def render(payload: dict[str, Any], *, as_json: bool) -> str:",
                "def render(message: dict[str, Any], *, as_json: bool) -> str:",
            ),
        ),
        node="enforce/fitness/test_api.py::test_structured_output",
    ),
    Mutation(
        rule_id="API-007",
        summary="success and refusal statuses cease to be named exit constants",
        source=(
            "The fitness mechanism requires at least two published EXIT constants; "
            "renaming success and refusal leaves only the usage status discoverable."
        ),
        replace=(
            ("src/refpkg/shell/cli.py", "EXIT_OK: int = 0", "STATUS_OK: int = 0"),
            ("src/refpkg/shell/cli.py", "EXIT_REFUSED: int = 1", "STATUS_REFUSED: int = 1"),
        ),
        node="enforce/fitness/test_api.py::test_exit_codes",
    ),
    Mutation(
        rule_id="API-009",
        summary="the shell introduces an automation-specific validation branch",
        source=(
            "The mechanism rejects caller-identity branches by name; inserting an "
            "is_agent switch creates the relaxed automation path the rule forbids."
        ),
        replace=(
            (
                "src/refpkg/shell/cli.py",
                "from __future__ import annotations",
                "from __future__ import annotations\n\nis_agent = False",
            ),
        ),
        node="enforce/fitness/test_api.py::test_agent_parity",
    ),
    Mutation(
        rule_id="API-010",
        summary="the published entry point carries no schema-version field",
        source=(
            "The replacement remains an entry-point module with a renderer but "
            "contains neither a schema-version declaration nor payload field."
        ),
        write=(
            (
                "src/refpkg/shell/cli.py",
                (
                    '"""An unversioned entry point."""\n\n'
                    "from typing import Any\n\n"
                    "def render(payload: dict[str, Any], *, as_json: bool) -> str:\n"
                    '    """Render one payload."""\n'
                    "    return str(payload)\n"
                ),
            ),
        ),
        node="enforce/fitness/test_api.py::test_schema_versioned",
    ),
    Mutation(
        rule_id="API-012",
        summary="a version-two payload ships without any migration",
        source=(
            "The replacement raises the format to version two in the published "
            "entry point while the repository still contains no migration artifact."
        ),
        write=(
            (
                "src/refpkg/shell/cli.py",
                (
                    '"""A changed entry point with no migration."""\n\n'
                    'SCHEMA_VERSION = "2"\n\n'
                    "def render(payload: object) -> str:\n"
                    '    """Render one payload."""\n'
                    "    return str(payload)\n"
                ),
            ),
        ),
        node="enforce/fitness/test_api.py::test_migrations",
    ),
    Mutation(
        rule_id="DEP-002",
        summary="the domain directly imports a third-party dependency",
        source=(
            "The dependency-position mechanism classifies requests as foreign and "
            "rejects it when introduced into policy rather than an adapter."
        ),
        replace=(
            (
                "src/refpkg/domain/model.py",
                "from __future__ import annotations",
                "from __future__ import annotations\n\nimport requests",
            ),
        ),
        node="enforce/fitness/test_deps.py::test_dependency_position",
    ),
    Mutation(
        rule_id="DIAG-001",
        summary="the diagnostic producer omits its stable code field",
        source=(
            "The behavioral mechanism serializes real errors and validates them "
            "against the schema; removing code makes every case non-conformant."
        ),
        replace=(
            (
                "src/refpkg/shell/envelope.py",
                '        "code": getattr(error, "code", "refpkg.shell.unexpected"),',
                '        "broken_code": getattr(error, "code", "refpkg.shell.unexpected"),',
            ),
        ),
        node="enforce/fitness/test_diagnostics.py::test_envelope_conforms",
    ),
    Mutation(
        rule_id="FLOW-011",
        summary="a real diagnostic envelope fails its published schema",
        source=(
            "FLOW-011 requires inspection rather than assumption; the same real-error "
            "case rejects a producer that renames the required code field."
        ),
        replace=(
            (
                "src/refpkg/shell/envelope.py",
                '        "code": getattr(error, "code", "refpkg.shell.unexpected"),',
                '        "broken_code": getattr(error, "code", "refpkg.shell.unexpected"),',
            ),
        ),
        node="enforce/fitness/test_diagnostics.py::test_envelope_conforms",
    ),
    Mutation(
        rule_id="EFCT-003",
        summary="domain policy imports a random-number source",
        source=(
            "The determinism fitness test enumerates ambient nondeterminism imports; "
            "adding random to the domain makes identical inputs no longer sufficient."
        ),
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "from __future__ import annotations",
                "from __future__ import annotations\n\nimport random",
            ),
        ),
        node="enforce/fitness/test_determinism.py::test_determinism",
    ),
    Mutation(
        rule_id="EFCT-007",
        summary="the fault layer contains no interruption or recovery evidence",
        source=(
            "The journal obligation is observed through scheduled partial progress; "
            "replacing the fault suite with an unrelated assertion removes that evidence."
        ),
        write=(
            (
                "tests/fault/test_containment.py",
                (
                    '"""Tests. Oracle: contract."""\n\n\ndef test_unrelated() -> None:\n'
                    '    """Exercise no interruption."""\n    assert True\n'
                ),
            ),
        ),
        node="enforce/fitness/test_effects.py::test_interruption_recovers",
    ),
    Mutation(
        rule_id="TEST-012",
        summary="the fault layer never drives an interrupted effect boundary",
        source=(
            "The test obligation requires scheduled interruption evidence; replacing "
            "the only fault suite leaves the behavioral mechanism with no such case."
        ),
        write=(
            (
                "tests/fault/test_containment.py",
                (
                    '"""Tests. Oracle: contract."""\n\n\ndef test_unrelated() -> None:\n'
                    '    """Exercise no interruption."""\n    assert True\n'
                ),
            ),
        ),
        node="enforce/fitness/test_effects.py::test_interruption_recovers",
    ),
    Mutation(
        rule_id="EFCT-009",
        summary="the file port stops stating its non-atomic limit",
        source=(
            "The mechanism searches published port contracts for an explicit limit; "
            "removing the sole partial-progress statement makes the guarantee implicit."
        ),
        replace=(
            (
                "src/refpkg/ports/files.py",
                "* `delete` is **not** atomic across a sequence of calls, and the port says so",
                "* `delete` reports failures across a sequence of calls",
            ),
            (
                "src/refpkg/ports/files.py",
                "an interrupted\n  run leaves some entries deleted and the rest present.",
                "a failed\n  run reports an error.",
            ),
            (
                "src/refpkg/ports/errors.py",
                "report an interrupted",
                "report a failed",
            ),
        ),
        node="enforce/fitness/test_effects.py::test_what_is_not_guaranteed_is_stated",
    ),
    Mutation(
        rule_id="EFCT-014",
        summary="a module introduces shared threading state without semantics",
        source=(
            "The mechanism inventories concurrency primitives and requires lock-order "
            "or ownership prose; the new pooled adapter states neither."
        ),
        write=(
            (
                "src/refpkg/adapters/files/pooled.py",
                (
                    '"""A store sharing state across threads without semantics."""\n\n'
                    "import threading\n\n"
                    "class PooledStore:\n"
                    '    """Share a dictionary."""\n\n'
                    "    def __init__(self) -> None:\n"
                    '        """Build it."""\n'
                    "        self._entries: dict[str, str] = {}\n"
                ),
            ),
        ),
        node="enforce/fitness/test_concurrency.py::test_concurrency_documented",
    ),
    Mutation(
        rule_id="ERR-015",
        summary="the process boundary catches only ValueError",
        source=(
            "The fitness mechanism parses the entry point for a broad final handler; "
            "narrowing it permits every other unexpected exception to escape."
        ),
        replace=(
            (
                "src/refpkg/shell/cli.py",
                "except Exception as exc:",
                "except ValueError as exc:",
            ),
        ),
        node="enforce/fitness/test_diagnostics.py::test_no_unhandled_escape",
    ),
    Mutation(
        rule_id="TEST-011",
        summary="fault tests assert only that an exception was raised",
        source=(
            "The containment fitness test requires cause-chain and layer evidence; "
            "the replacement demonstrates neither and therefore cannot localize failure."
        ),
        write=(
            (
                "tests/fault/test_containment.py",
                (
                    '"""Tests. Oracle: contract."""\n\nimport pytest\n\n'
                    "def test_it_raises() -> None:\n"
                    '    """Observe only that something broke."""\n'
                    "    with pytest.raises(ValueError):\n"
                    "        raise ValueError\n"
                ),
            ),
        ),
        node="enforce/fitness/test_faults.py::test_fault_containment",
    ),
    Mutation(
        rule_id="FLOW-003",
        summary="the primary decision ledger is absent",
        source=(
            "The mechanism parameterizes every declared ledger and requires a "
            "reasoned decision; deleting OPEN.md removes that durable subject."
        ),
        base="repository",
        drop=("discipline/meta/OPEN.md",),
        node="enforce/fitness/test_decisions.py::test_decisions_recorded",
    ),
    Mutation(
        rule_id="FLOW-004",
        summary="two structural decisions reuse the same stable identifier",
        source=(
            "The append-only mechanism rejects duplicate decision identities; "
            "renaming OPEN-002 to OPEN-001 simulates rewriting historical identity."
        ),
        base="repository",
        replace=(
            (
                "discipline/meta/OPEN.md",
                "### OPEN-002",
                "### OPEN-001",
            ),
        ),
        node="enforce/fitness/test_decisions.py::test_decision_records_are_appended",
    ),
    Mutation(
        rule_id="FLOW-005",
        summary="the decision ledger retains outcomes but no objection",
        source=(
            "The reversal mechanism requires at least one record to preserve what "
            "it answered; replacing the ledger with bare decisions erases that history."
        ),
        base="repository",
        write=(
            (
                "discipline/meta/OPEN.md",
                (
                    "### OPEN-001 · Choose one\n\n"
                    "This decision has reasoning but records no contrary view.\n"
                ),
            ),
        ),
        node="enforce/fitness/test_decisions.py::test_overruled_objections_are_kept",
    ),
    Mutation(
        rule_id="FLOW-006",
        summary="a generated binding rule has neither mechanism nor strategy",
        source=(
            "The meta-mechanism joins binding headings to complete strategy records; "
            "the minimal generated rule deliberately breaks every required join field."
        ),
        base="repository",
        write=(
            (
                "discipline/rules.json",
                (
                    '{"rules":[{"id":"FIX-001","force":"BINDING","mechanisms":[],'
                    '"check":"","verification":{"strategies":[]}}]}\n'
                ),
            ),
        ),
        node="enforce/fitness/test_meta.py::test_binding_rules_have_mechanisms",
    ),
    Mutation(
        rule_id="FLOW-007",
        summary="custom check modules lose their proof-of-failure companions",
        source=(
            "The mechanism inventories checker implementations against companion "
            "test text; deleting the foundational suite leaves several checkers unproven."
        ),
        base="repository",
        drop=("enforce/checks/test_checks.py",),
        node="enforce/fitness/test_meta.py::test_checks_can_fail",
    ),
    Mutation(
        rule_id="TEST-015",
        summary="custom check modules ship without companion rejection tests",
        source=(
            "TEST-015 is the proof-of-failure obligation itself; removing the suite "
            "for raise, assertion, domain, and naming checks makes the census fail."
        ),
        base="repository",
        drop=("enforce/checks/test_checks.py",),
        node="enforce/fitness/test_meta.py::test_checks_can_fail",
    ),
    Mutation(
        rule_id="FLOW-009",
        summary="the canonical gate definition becomes empty",
        source=(
            "The gate fitness mechanism rejects a zero-entry definition, which "
            "would otherwise let every change report success without verification."
        ),
        base="repository",
        write=(
            (
                "tools/gate.py",
                (
                    '"""An intentionally empty gate fixture."""\n\n'
                    "from typing import Final\n\n"
                    "GATE: Final[tuple[tuple[str, tuple[str, ...]], ...]] = ()\n"
                ),
            ),
        ),
        node="enforce/fitness/test_meta.py::test_gate_suite_defined",
    ),
    Mutation(
        rule_id="TEAMS-003",
        summary="the installed completion hook no longer invokes the gate",
        source=(
            "The mechanism inspects the shipped hook and installer; replacing the "
            "hook with an unconditional success turns verification back into a request."
        ),
        base="repository",
        write=(
            (
                "enforce/templates/hooks/pre-push",
                "#!/bin/sh\necho pushing\nexit 0\n",
            ),
        ),
        node="enforce/fitness/test_meta.py::test_completion_hook_enforces_the_gate",
    ),
    Mutation(
        rule_id="TEST-018",
        summary="pytest is configured to rerun failures until one passes",
        source=(
            "The mechanism explicitly bans rerun switches; adding --reruns to the "
            "repository harness demonstrates the dismissal path it exists to stop."
        ),
        base="repository",
        write=(("pytest.ini", "[pytest]\naddopts = --reruns 3\n"),),
        node="enforce/fitness/test_determinism.py::test_no_rerun_dismissal",
    ),
    # -------------------------------- exact witnesses for multi-mechanism rules
    Mutation(
        rule_id="ARCH-001",
        summary="the local dependency checker sees domain importing shell",
        source=(
            "The repository-local checker and import-linter are distinct oracles; "
            "this entry runs dependency_boundaries itself against the outward edge."
        ),
        mechanism="check:dependency_boundaries",
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "from __future__ import annotations",
                "from __future__ import annotations\n\nfrom refpkg.shell import envelope",
            ),
        ),
    ),
    Mutation(
        rule_id="ARCH-002",
        summary="import-linter sees pathlib enter the domain",
        source=(
            "The ARCH-002 forbidden-import contract names pathlib explicitly; this "
            "observes that external graph mechanism independently of domain_purity."
        ),
        mechanism="auto:import-linter",
        tool="import-linter",
        diagnostic="ARCH-002 domain is pure",
        replace=(
            (
                "src/refpkg/domain/model.py",
                "from __future__ import annotations",
                "from __future__ import annotations\n\nfrom pathlib import Path",
            ),
        ),
    ),
    Mutation(
        rule_id="ARCH-003",
        summary="the local dependency checker sees one adapter import another",
        source=(
            "The direct source-edge checker has a separate predicate from the "
            "import-linter independence contract and must reject the same breach."
        ),
        mechanism="check:dependency_boundaries",
        replace=(
            (
                "src/refpkg/adapters/clock/real.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n"
                    "from refpkg.adapters.files import real as _files"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="DIAG-008",
        summary="Ruff sees a broad Exception catch outside the process boundary",
        source=(
            "BLE001 is a distinct configured verifier from raise_from; the broad "
            "catch is its exact observable predicate and must produce that code."
        ),
        mechanism="auto:ruff:BLE001",
        tool="ruff",
        diagnostic="BLE001",
        replace=(
            (
                "src/refpkg/app/prune.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n\n"
                    "def swallow() -> None:\n"
                    '    """Catch an unbounded family.\n\n    @return nothing\n    """\n'
                    "    try:\n        pass\n"
                    "    except Exception:\n        return"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="DIAG-015",
        summary="Ruff sees an exception interpolated eagerly into a log string",
        source=(
            "G004 independently observes the eager-formatting half of DIAG-015; "
            "the local log_once checker cannot lend its rejection credit here."
        ),
        mechanism="auto:ruff:G004",
        tool="ruff",
        diagnostic="G004",
        replace=(
            (
                "src/refpkg/shell/cli.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\nimport logging\n\n\n"
                    "def report(error: Exception) -> None:\n"
                    '    """Log a failure.\n\n    @param error the failure\n    """\n'
                    '    logging.getLogger(__name__).error(f"failed: {error}")'
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="DOC-001",
        summary="Ruff sees a production module without a module docstring",
        source=(
            "D100 covers the module-level subset of DOC-001 independently from "
            "doc_coverage, so a new undocumented module must emit the exact code."
        ),
        mechanism="auto:ruff:D100",
        tool="ruff",
        diagnostic="D100",
        write=(("src/refpkg/domain/undocumented.py", "VALUE: int = 1\n"),),
    ),
    Mutation(
        rule_id="TYPE-001",
        summary="pyright sees an unannotated domain function",
        source=(
            "The second strict checker must reject independently; unknown parameter "
            "typing is pyright's diagnostic for an unannotated public function."
        ),
        mechanism="auto:pyright",
        tool="pyright",
        diagnostic='Type annotation is missing for parameter "value"',
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n\n"
                    "def unchecked(value):\n"
                    '    """Return an unchecked value.\n\n'
                    '    @param value unknown input\n    @return unknown output\n    """\n'
                    "    return value"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="TYPE-002",
        summary="mypy sees explicit Any in a domain signature",
        source=(
            "The reference mypy configuration enables disallow_any_explicit for "
            "domain modules; this independently witnesses the checker-side ban."
        ),
        mechanism="auto:mypy",
        tool="mypy",
        diagnostic="[explicit-any]",
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\nfrom typing import Any\n\n\n"
                    "def widen(value: Any) -> Any:\n"
                    '    """Erase both sides.\n\n'
                    '    @param value anything\n    @return anything\n    """\n'
                    "    return value"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="TYPE-003",
        summary="mypy sees a blanket type ignore without an error code",
        source=(
            "Mypy's ignore-without-code verifier is independent from Ruff PGH003; "
            "the same escape hatch must be rejected by both configured tools."
        ),
        mechanism="auto:mypy",
        tool="mypy",
        diagnostic="[ignore-without-code]",
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "from __future__ import annotations",
                (
                    "from __future__ import annotations\n\n"
                    '_ANYTHING: int = "not an int"  # type: ignore'
                ),
            ),
        ),
    ),
    # ------------------------------------------ remaining external graph/types
    Mutation(
        rule_id="API-004",
        summary="domain code imports the private storage representation",
        source=(
            "The EFCT-012 ownership contract is the mechanism API-004 names; an "
            "unsanctioned reader makes the persistent representation public in fact."
        ),
        mechanism="auto:import-linter",
        tool="import-linter",
        diagnostic="EFCT-012 storage has one owner",
        write=(
            (
                "src/refpkg/domain/storage_breach.py",
                (
                    '"""An unsanctioned storage reader."""\n\n'
                    "from refpkg.adapters.files import raw\n\n"
                    "REPRESENTATION = raw\n"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="EFCT-012",
        summary="application code imports the private storage representation",
        source=(
            "EFCT-012's configured import contract forbids every non-owning path "
            "from reaching the raw representation directly; this seeds such a writer."
        ),
        mechanism="auto:import-linter",
        tool="import-linter",
        diagnostic="EFCT-012 storage has one owner",
        write=(
            (
                "src/refpkg/app/storage_breach.py",
                (
                    '"""An unsanctioned storage writer."""\n\n'
                    "from refpkg.adapters.files import raw\n\n"
                    "REPRESENTATION = raw\n"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="ARCH-006",
        summary="a domain result function returns None outside its declared union",
        source=(
            "Mypy cannot prove arbitrary totality, but it can reject a path whose "
            "returned value lies outside the function's explicit result union."
        ),
        mechanism="auto:mypy",
        tool="mypy",
        diagnostic="[return-value]",
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "Outcome: TypeAlias = Plan | Refusal",
                (
                    "Outcome: TypeAlias = Plan | Refusal\n\n\n"
                    "def partial(flag: bool) -> Outcome:\n"
                    '    """Return an invalid arm on one path.\n\n'
                    '    @param flag which path to take\n    @return an alleged outcome\n    """\n'
                    "    if flag:\n"
                    '        return Refusal(code="deferred", expected="now", actual="later")\n'
                    "    return None"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="ERR-002",
        summary="mypy sees a newly added result arm left unhandled",
        source=(
            "Adding Deferred at the union definition makes the shell's final "
            "Never narrowing receive Deferred, which mypy must reject by arg-type."
        ),
        mechanism="auto:mypy",
        tool="mypy",
        diagnostic="[arg-type]",
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "Outcome: TypeAlias = Plan | Refusal",
                (
                    "@dataclass(frozen=True, slots=True)\n"
                    "class Deferred:\n"
                    '    """A newly introduced unhandled result arm."""\n\n\n'
                    "Outcome: TypeAlias = Plan | Refusal | Deferred"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="ERR-002",
        summary="pyright sees a newly added result arm left unhandled",
        source=(
            "The same union extension must independently make pyright reject the "
            "Deferred value passed to the shell's Never-typed narrowing function."
        ),
        mechanism="auto:pyright",
        tool="pyright",
        diagnostic='cannot be assigned to parameter "outcome" of type "Never"',
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "Outcome: TypeAlias = Plan | Refusal",
                (
                    "@dataclass(frozen=True, slots=True)\n"
                    "class Deferred:\n"
                    '    """A newly introduced unhandled result arm."""\n\n\n'
                    "Outcome: TypeAlias = Plan | Refusal | Deferred"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="ERR-005",
        summary="a function returns an error variant absent from its result union",
        source=(
            "The declaration-site rule's mechanical predicate is return-type "
            "membership: mypy rejects a NovelFailure returned as the closed Outcome."
        ),
        mechanism="auto:mypy",
        tool="mypy",
        diagnostic="[return-value]",
        replace=(
            (
                "src/refpkg/domain/plan.py",
                "Outcome: TypeAlias = Plan | Refusal",
                (
                    "Outcome: TypeAlias = Plan | Refusal\n\n\n"
                    "@dataclass(frozen=True, slots=True)\n"
                    "class NovelFailure:\n"
                    '    """An error not declared in Outcome."""\n\n\n'
                    "def undeclared() -> Outcome:\n"
                    '    """Return the undeclared arm.\n\n    @return an invalid arm\n    """\n'
                    "    return NovelFailure()"
                ),
            ),
        ),
    ),
    Mutation(
        rule_id="DIAG-006",
        summary="a broad catch is rewrapped only to change its message",
        source=(
            "The companion constructs the exact broad single-raise shape and "
            "asserts DIAG-006 rather than borrowing another raise_from diagnostic."
        ),
        mechanism="check:raise_from",
        proof="enforce/checks/test_checks.py::test_rewrapping_only_to_add_context_fires",
    ),
    Mutation(
        rule_id="DIAG-009",
        summary="an assertion validates a caller-controlled parameter",
        source=(
            "The assertion companion now requires both sides of the prohibition; "
            "DIAG-009 is observed directly rather than inferred from ERR-012."
        ),
        mechanism="check:assert_usage",
        proof="enforce/checks/test_checks.py::test_assert_on_a_parameter_fires",
    ),
    Mutation(
        rule_id="DOC-012",
        summary="a rendered HTML page is committed beneath a site build tree",
        source=(
            "The generated-provenance companion places a real HTML subject under "
            "site and asserts DOC-012, the check's exact path predicate."
        ),
        mechanism="check:generated_provenance",
        proof=("enforce/checks/test_ledger_checks.py::test_a_rendered_documentation_tree_fires"),
    ),
    Mutation(
        rule_id="DOC-005",
        summary="Doxygen rejects a documented parameter absent from the signature",
        source=(
            "Only parsed documentation can relate @param ghost to the Python "
            "signature; the companion runs real Doxygen and requires that rejection."
        ),
        mechanism="auto:doxygen",
        proof=(
            "tools/test_doxygen_gate.py::test_a_documented_parameter_that_does_not_exist_is_caught"
        ),
    ),
    Mutation(
        rule_id="DOC-010",
        summary="a Doxygen documentation warning makes the run fail",
        source=(
            "The bogus parameter produces a real engine warning and the companion "
            "requires a failed verdict, directly witnessing warnings-as-errors."
        ),
        mechanism="auto:doxygen",
        proof=(
            "tools/test_doxygen_gate.py::test_a_documented_parameter_that_does_not_exist_is_caught"
        ),
    ),
    Mutation(
        rule_id="DOC-011",
        summary="a Doxygen run with no input cannot earn a clean verdict",
        source=(
            "The companion runs the real engine against an empty src tree and "
            "requires failure, covering both native refusal and the page-count guard."
        ),
        mechanism="auto:doxygen",
        proof="tools/test_doxygen_gate.py::test_generating_nothing_is_not_generating_cleanly",
    ),
    # --------------------------------------- real test-control tool witnesses
    Mutation(
        rule_id="TEST-003",
        summary="pytest-timeout terminates a test beyond its configured budget",
        source=(
            "The control experiment invokes the installed plugin over a sleeping "
            "test and requires its timeout diagnostic rather than wrapper timing."
        ),
        mechanism="auto:pytest-timeout",
        proof=("tools/test_toolchain_gates.py::test_pytest_timeout_terminates_a_slow_test"),
    ),
    Mutation(
        rule_id="TEST-013",
        summary="Cosmic Ray rejects a suite that executes but does not discriminate",
        source=(
            "The real engine generates a non-empty mutant set after a normal passing "
            "baseline; a type-only oracle leaves mutants alive and the adapter rejects."
        ),
        mechanism="auto:cosmic-ray",
        proof=(
            "tools/test_mutation_gate.py::"
            "test_cosmic_ray_rejects_a_suite_that_only_executes_the_core"
        ),
    ),
    Mutation(
        rule_id="TEST-017",
        summary="pytest-randomly exposes a hidden producer-consumer order dependency",
        source=(
            "The installed plugin drives bounded explicit seeds until the consumer "
            "precedes its undeclared producer and the exact dependency assertion fails."
        ),
        mechanism="auto:pytest-randomly",
        proof=("tools/test_toolchain_gates.py::test_pytest_randomly_exposes_an_order_dependency"),
    ),
    Mutation(
        rule_id="TEST-017",
        summary="pytest-socket blocks creation of an ambient network socket",
        source=(
            "The installed plugin is invoked with the canonical fail-closed option; "
            "socket construction must fail with its own SocketBlockedError diagnostic."
        ),
        mechanism="auto:pytest-socket",
        proof=("tools/test_toolchain_gates.py::test_pytest_socket_blocks_ambient_network"),
    ),
    # -------------------------------------- environment and generated products
    Mutation(
        rule_id="DEP-005",
        summary="the environment declaration loosens one exact version to a range",
        source=(
            "The cited fitness test runs the verifier over the repository lock; "
            "check_env classifies a ranged requirement as a lock defect."
        ),
        base="repository",
        replace=(("environment.yml", "      - ruff==0.16.3", "      - ruff>=0.16"),),
        node="enforce/fitness/test_deps.py::test_environment_locked",
    ),
    Mutation(
        rule_id="DEP-006",
        summary="the environment verifier ignores every detected drift",
        source=(
            "The fitness test now drives both matching and deliberately drifted "
            "locks, so forcing the problems branch false must be rejected."
        ),
        base="repository",
        replace=(("tools/check_env.py", "if problems:", "if False and problems:"),),
        node="enforce/fitness/test_deps.py::test_environment_locked",
    ),
    Mutation(
        rule_id="DEP-009",
        summary="the index generator injects the current nanosecond into its output",
        source=(
            "A time-derived byte makes unchanged-model output unstable; the exact "
            "regeneration check must reject the generated text against committed bytes."
        ),
        base="repository",
        replace=(
            ("tools/build_index.py", "import sys", "import sys\nimport time"),
            (
                "tools/build_index.py",
                "        build_index(documents, root),",
                (
                    "        Artifact(build_index(documents, root).path, "
                    "build_index(documents, root).text + str(time.time_ns())),"
                ),
            ),
        ),
        node="enforce/fitness/test_generated.py::test_regeneration_stable",
    ),
    Mutation(
        rule_id="DEP-010",
        summary="the committed index differs from what its generator produces",
        source=(
            "DEP-010 is the drift predicate itself; appending one authored-looking "
            "line to a generated artifact must make its --check form non-zero."
        ),
        base="repository",
        replace=(
            (
                "discipline/INDEX.md",
                "<!-- GENERATED by tools/build_index.py",
                "drift\n<!-- GENERATED by tools/build_index.py",
            ),
        ),
        node="enforce/fitness/test_generated.py::test_regeneration_stable",
    ),
    Mutation(
        rule_id="DEP-011",
        summary="one declared generated artifact is absent from the repository",
        source=(
            "A generated product available only after a build has no committed "
            "comparison subject; dropping INDEX.md makes the cited check reject it."
        ),
        base="repository",
        drop=("discipline/INDEX.md",),
        node="enforce/fitness/test_generated.py::test_regeneration_stable",
    ),
    # ----------------------------------------------- installer lifecycle proofs
    Mutation(
        rule_id="DEP-012",
        summary="integrate --check rejects a missing top-level announcement",
        source=(
            "The companion starts with a vendored corpus but no managed host block "
            "and requires the integrator's check mode to return a refusal."
        ),
        mechanism="auto:integrate",
        proof="tools/test_integrate.py::test_check_reports_a_missing_block",
    ),
    Mutation(
        rule_id="DEP-013",
        summary="integrate --check rejects a stale managed announcement",
        source=(
            "The auto:integrate strategy is observed on a block whose manifest "
            "version changed, independently of the replacement behavior test."
        ),
        mechanism="auto:integrate",
        proof="tools/test_integrate.py::test_check_reports_a_stale_block",
    ),
    Mutation(
        rule_id="DEP-013",
        summary="an update replaces its managed block instead of duplicating it",
        source=(
            "The behavioral strategy performs two versions of installation and "
            "requires exactly one marker block with the newer identity."
        ),
        mechanism="fitness:test_an_existing_block_is_replaced_not_duplicated",
        proof=("tools/test_integrate.py::test_an_existing_block_is_replaced_not_duplicated"),
    ),
    Mutation(
        rule_id="DEP-014",
        summary="the installer dry run leaves every owned path absent",
        source=(
            "The companion executes the public dry-run path and asserts absence of "
            "the host block, settings, and integration record after the preview."
        ),
        proof="tools/test_integrate.py::test_a_dry_run_writes_nothing",
    ),
    # ------------------------------------------------------- learning mechanisms
    Mutation(
        rule_id="LEARN-002",
        summary="the record command refuses missing claim, action, and trigger fields",
        source=(
            "The two companion nodes exercise parser-required claim/action and the "
            "write-policy trigger refusal through the public learning command."
        ),
        mechanism="auto:learn",
        proof="tools/test_learn.py::test_record_refuses_a_missing_claim_or_action",
    ),
    Mutation(
        rule_id="LEARN-002",
        summary="the record command refuses a learning with no retrieval trigger",
        source=(
            "Claim and action are present in this companion; only the trigger is "
            "omitted, and the tool must refuse without creating a ledger."
        ),
        mechanism="auto:learn",
        proof="tools/test_learn.py::test_record_refuses_a_missing_trigger",
    ),
    Mutation(
        rule_id="LEARN-003",
        summary="the public record command refuses credential-shaped content",
        source=(
            "This observes auto:learn at its CLI boundary and requires both a "
            "refusal status and an absent ledger after the credential attempt."
        ),
        mechanism="auto:learn",
        proof="tools/test_learn.py::test_record_command_refuses_a_credential",
    ),
    Mutation(
        rule_id="LEARN-003",
        summary="the ledger append guard refuses a credential before writing",
        source=(
            "The behavioral companion invokes the append boundary directly, "
            "requires LearnError, and asserts that no ledger was created."
        ),
        mechanism="fitness:test_a_credential_is_refused",
        proof="tools/test_learn.py::test_a_credential_is_refused",
    ),
    Mutation(
        rule_id="LEARN-006",
        summary="sync trusts an existing database instead of replaying the ledger",
        source=(
            "The reconstruction test deletes the index between folds; an early "
            "return for existing databases makes its before and rebuilt states diverge."
        ),
        base="repository",
        replace=(
            (
                "tools/learn.py",
                "    store.dir.mkdir(parents=True, exist_ok=True)\n    connection = connect(store)",
                (
                    "    if store.db.exists():\n"
                    "        return connect(store)\n"
                    "    store.dir.mkdir(parents=True, exist_ok=True)\n"
                    "    connection = connect(store)"
                ),
            ),
        ),
        node=("tools/test_learn.py::test_the_database_is_reconstructible_from_the_ledger"),
    ),
    Mutation(
        rule_id="LEARN-007",
        summary="retrieval reverses its answer on every other identical query",
        source=(
            "A function-local flip makes two same-state retrievals return opposite "
            "orders, the exact determinism property the cited test compares."
        ),
        base="repository",
        replace=(
            (
                "tools/learn.py",
                "    candidates.sort(key=lambda c: (-c.effective, c.id))",
                (
                    "    candidates.sort(key=lambda c: (-c.effective, c.id))\n"
                    "    flip = bool(getattr(retrieve, '_flip', False))\n"
                    "    setattr(retrieve, '_flip', not flip)\n"
                    "    if flip:\n"
                    "        candidates.reverse()"
                ),
            ),
        ),
        node="tools/test_learn.py::test_retrieval_is_reproducible",
    ),
    Mutation(
        rule_id="LEARN-008",
        summary="confidence decays by three quarters rather than one half per half-life",
        source=(
            "The cited test fixes both the starting confidence and its value at "
            "exactly one half-life, so changing the decay base must be rejected."
        ),
        base="repository",
        replace=(
            (
                "tools/learn.py",
                "return round(stored * (0.5 ** (days / half_life)), 4)",
                "return round(stored * (0.75 ** (days / half_life)), 4)",
            ),
        ),
        node="tools/test_learn.py::test_confidence_decays_with_time",
    ),
    Mutation(
        rule_id="LEARN-011",
        summary="calibration attempts to change a parameter without a reason",
        source=(
            "The public command companion omits --why and asserts refusal, byte-"
            "identical configuration, and no appended calibration event."
        ),
        mechanism="auto:learn",
        proof="tools/test_learn.py::test_calibrate_refuses_a_change_without_a_reason",
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


def covered_strategies() -> frozenset[tuple[str, str]]:
    """Which exact automated strategies have a declared rejection witness.

    An empty mechanism is an unambiguous rule-local witness and is valid only
    when the evidence registry gives that rule one automated strategy. The
    evidence validator owns that join because this table deliberately does not
    duplicate the normative registry.

    @return rule and mechanism pairs declared by the matrix
    """
    return frozenset((mutation.rule_id, mutation.mechanism) for mutation in MUTATIONS)
