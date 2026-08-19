# Python Engineering Discipline — v3.2.0

**v3.0.0 corrected half of a measurement. This release corrects the other half, and then
makes the result usable by a repository that already exists.**

That release found `V080` — the count of binding rules decided by nothing — had been
resolving a `check:foo` tag by asking whether `enforce/checks/foo.py` **exists**, never
whether that check claimed the rule. The number went from a claimed 0 to a true 14.

The same defect was still live on the other 64 rules, and a repository with any history at
all still could not adopt any of this.

```bash
python .agent/tools/integrate.py                    # apply
python .agent/tools/conformance.py report           # new: how conformant am I?
python .agent/tools/conformance.py --update-baseline --why "adoption"
```

## Two releases' work, one archive

This ships v3.1's and v3.2's bodies of work together. There is no separate `v3.1.0` tag: it
would point at a tree whose own `vendor.RELEASE` reads `v3.0.0` and for which no archive was
ever built, which is a version claim with nothing behind it.

---

# Part one — a `V080` that is a count

## A fitness test now declares what it decides

A `fitness:` tag was resolved by searching for the text `def <name>(` and answering yes if it
was found anywhere. Sixty-four binding rules rested on that. Seventeen fitness functions
carried more than one rule between them — the same one-mechanism-many-claims shape that was
wrong 23% of the time on the check side.

`enforce/decides.py` gives a fitness function what a check already had:

```python
@decides("ARCH-009", "TEST-005", "TEST-006")
def test_contract_suite_per_adapter() -> None:
```

Read by parsing the source, never by importing — `build_index.py` takes the census and must
not execute a test suite to find out what it claims.

**The two arms differ in one place, deliberately.** A check with no `rules` tuple gets the
benefit of the doubt; a fitness test with no `@decides` does not. Treating a missing
declaration as consent is precisely how sixty-four rules came to rest on a tag that only ever
asked whether some file contained a `def`.

## What reading all forty functions found

**Sixteen claims did not hold — 20%, against the check side's 23%.**

Three were mistags where the right function already existed. `FLOW-004` ("records are
appended, never rewritten") was tagged to `test_decisions_recorded`, which checks that
decisions carry reasoning; `test_decision_records_are_appended`, sitting in the same file,
is what actually decides it.

Four were real gaps, now mechanized:

| | was claimed by | which |
|---|---|---|
| `API-001` | `test_contract_documented` | asserted a docstring was *truthy* and claimed a rule requiring seven stated things. A method documented as `"x"` passed. |
| `TEST-007` | `test_layers_populated` | counts named tests per layer, and cannot tell a generated-input property suite from three hand-picked examples. |
| `TEST-018` | `test_seeds_recorded` | asserts the randomising plugins are *present*, which says nothing about whether a failure can be re-run away. |
| `TEAMS-003` | `test_gate_suite_defined` | asserts the GATE tuple is well-formed, and nothing about whether anything runs it unasked. |

Nine had no mechanism and now say so, each with a written justification and a closing
condition. Two are about *when* a thing was written and a tree carries no record of order.
`DIAG-013`'s test asserted `correlation_id` is **not required** — the opposite of what the
rule says every envelope must carry.

**`V080` is still 14, and the ratchet was never touched.** The sixteen exposed claims
resolved as four built, three retagged, nine made advisory. Every remaining one is
check-side. Binding 164 → 155, advisory 19 → 28.

## `D` — the third question

`V080` asks whether a mechanism exists. `V098`, new here, asks whether anyone has watched it
**work**. `D` went 20 → 49.

**Twenty-seven rules were uncoverable, not merely uncovered.** They are decided by `auto:`
alone — a ruff code, a mypy error, an import-linter contract — and the matrix could express
only two kinds of mutation: provoke a check finding, or fail a pytest node. No amount of
writing entries would have moved the number.

The `auto` kind asserts the diagnostic **by name**, never by the tool exiting non-zero: a
syntax error also exits non-zero, and one unparseable file would otherwise certify the whole
table. That is pinned by a test which damages a file into `def (` and requires the entry to
be refused.

Writing those entries found the sharpest thing in this release. **Four of the eight rules
tagged `auto:import-linter` were named by no contract that runs.** An `auto:` tag resolves to
`None` — not checkable — so `V080` never reported it, and those rules were decided by a tool
nobody had told about them. `EFCT-001` and `DEP-001` now have a contract each.

Sixteen more entries were **transcribed, not invented**: the fitness suites already carried
twenty-two negative cases building a `broken_copy`. The transcription is stronger than what
it came from — a negative case re-implements the assertion beside the real one, while these
point `DISCIPLINE_REFERENCE` at the damaged tree and require **the tagged function itself**
to fail.

**93 of 142 decided rules remain undiscriminated**, and `V098` prints the number every run.
It is a warning, not an error: a gate that fails for a reason nobody can clear that afternoon
is a gate people learn to run with `--no-verify`.

---

# Part two — adoptable by a repository that already exists

## The problem, stated as a number

`python -m checks` printed every finding and exited 1. No baseline, no ratchet. Against four
independently written hexagonal packages it produced **1,082 findings**. The only tree that
could ever go green was one written against the rules from its first commit.

`tools/conformance.py` is the ratchet `lint_gate.py` has held this repository's own findings
under since v1.1.0, pointed outward. Two things differ, both load-bearing:

**The baseline lives in `overrides/conformance.json`.** `vendor.py` copies `discipline/`,
`enforce/` and `tools/` — not `overrides/`. An adopter's baseline survives every upgrade,
which it must: one silently reset by an upgrade would re-open every finding the adopter had
accepted, and the next upgrade would be declined. A test asserts it rather than trusting the
comment.

**`PROTECTED` is checked before the baseline is read at all**, so no ratcheting switches off
a rule whose violation destroys the evidence.

## Validated against a real codebase, and corrected by it

A copy of a 124-module repository was taken through the whole trip. **117 findings**, none
protected, so it adopts. Baseline minted, tree green — and then the assertion that matters:

- a new violation of an already-baselined rule failed **by name**;
- an `assert` used as validation failed as `ERR-012` and `DIAG-009` **with the baseline in
  place**.

A baseline that goes green is easy. One that still catches the next regression is the
feature.

The run corrected `PROTECTED` twice, and both corrections are why it was worth doing:

- **`DIAG-002` produced 17 violations on day one** — every one an error class that did not
  yet name a rule id. Annotation work, not a destroyed diagnosis, and it meant the repository
  most in need of the discipline was the one that could not adopt it.
- **`DIAG-001` and `ERR-008` could never have fired.** Neither is decided by an AST check —
  one by a fitness test, one by a ruff code — and this tool runs only the checks. Two of four
  guards were inert: the vacuity this repository exists to remove, reproduced inside the
  guard against it.

What remains is `DIAG-008`, `DIAG-009`, `ERR-012` and `DIAG-014`, and the line is stated in
the module: rules about **evidence being destroyed** belong there; rules about **structure an
adopter has yet to build** belong in the baseline. A secret in a log cannot be undone by a
later commit. A missing docstring can.

## The report

`conformance.py report` answers *how conformant am I, and is it improving* — cleared, new and
unchanged against the baseline; protected violations listed separately and never summarised
away; and the **cheapest next target**, the rule whose remaining findings are most
concentrated in one module. Adoption stalls when a thousand findings look like one wall.

## Upgrading from v3.0.0

Nothing breaks. `V080` is unchanged at 14, no rule id was renumbered or removed, and nine
rules moved `[BINDING]` → `[ADVISORY]`, which an adopter sees as **fewer** findings.
`MINIMUM_CONTRACTS` moves 7 → 9; a tree using the reference contract file gains two.

## Known gaps

- **`OPEN-019` — 93 of 142 decided rules are undiscriminated.** The new headline number.
- **`OPEN-011` — narrowed, not closed.** A copy driven through a script by its author is not
  a repository depending on this in daily use. Nothing here has met an update landing on a
  tree with local history, or a disagreement about a baselined finding.
- **`OPEN-009` — no CI has ever run.** Every verdict still comes from one machine: win32,
  cp932.

Four warnings fire on every run and are meant to: `V051`, `V080`, `V097`, `V098`.

## By the numbers

| | v3.0.0 | v3.2.0 |
|---|---|---|
| Binding rules | 164 | **155** |
| `V080` | 14 | **14**, and now a count on both sides |
| `D` — rules watched rejecting something | 20 | **49** |
| Mutation kinds | 2 | **3** |
| Import contracts run | 7 | **9** |
| Advisory rules | 19 | **28** |
| Tests | 696 | **736** |
| Findings an existing repository can adopt with | — | **117, ratcheted** |

The two numbers that fell are the two that were overstated. Nothing in the corpus regressed;
the measurement did, and now measures.
