---
id: meta/SCHEMA
kind: meta
title: Document Format Specification
tokens: 3861
load_when: ["authoring a rule", "new module", "front-matter", "rule id", "validate"]
decay: none
---

# Document Format Specification

The format contract for every file under `discipline/`. `tools/validate.py` implements
this document; where the two disagree, the validator is the defect.

Read this before authoring or editing any module. Nothing else needs it.

---

## 1. Genres

Every file declares exactly one `kind`. The genre fixes what the file is allowed to do.

| `kind` | Contains | May contain rules? | Decays |
|---|---|---|---|
| `law` | binding rules and their enforcement mechanisms | yes — this is the only genre that may | on decision |
| `fact` | verified truths about Python, its stdlib and third-party tools | no | months–quarters |
| `frame` | vocabulary, paradigm menus, reasoning scaffolds | no | none |
| `ops` | how agents are dispatched and coordinated | yes | months |
| `meta` | this document, glossary, conflict and provenance ledgers | no | none |

Two consequences, both checked:

- **`law` never pins a version.** It states a capability requirement ("a checker
  configured to reject implicit `Any`"). Every concrete pin — `mypy 2.1.0`,
  `pytest 9.1.x`, `Python 3.13` — lives in a `fact` file with a `verified:` date. A
  version literal in a `law` file is an error.
- **`frame` never prescribes.** It may describe options and their tradeoffs. `[BINDING]`
  in a `frame` file is an error; the rule belongs in `law`.

## 2. Front-matter

YAML, first thing in the file, delimited by `---`.

```yaml
---
id: law/TYPE                   # required. "<kind>/<NAME>", NAME is [A-Z][A-Z0-9]{1,7}
kind: law                      # required. law | fact | frame | ops | meta
title: Typing & Contracts      # required. Human-readable, <= 60 chars
tokens: 1840                   # required. Measured; written by build_index.py. 0 in a new file.
load_when:                     # required for law/fact/frame/ops. Router keywords, lowercase.
  - "type hint"
  - "mypy"
  - "Protocol"
applies_to: ["**/*.py"]        # optional. Globs this module governs.
requires: ["law/ARCH"]         # optional. Modules a reader must already hold.
grounds_on: ["fact/py-typing"] # optional. Facts this module's rules depend on.
verified: 2026-06-16           # required for kind: fact and kind: ops. ISO date.
decay: quarters                # required. months | quarters | years | none
python: ">=3.11"               # optional. PEP 440 specifier.
---
```

**`tokens:`** is the reason an agent can budget before reading. It is written by
`build_index.py`, never by hand, and measured by one character ratio defined in
`tools/discipline_core.py` — deliberately arithmetic rather than a real tokenizer, so the
same corpus yields the same number on every machine with nothing to install. It is a
budgeting hint, accurate to a few percent against a byte-pair encoder; it is not a
contract, and no rule is decided by its exact value.

**`load_when:`** is the router's keyword index. Terms should be what an agent would
actually have in hand at the moment it needs the module — error messages, API names,
task verbs — not topic labels. `"mypy"` and `"Protocol"` are useful; `"typing theory"`
is not.

**`verified:`/`decay:`** drive re-verification. `ops/teams` decays in months against a
Claude Code version; `frame/*` never decays. A `fact` file older than its decay window
is reported by `build_index.py`, not silently trusted.

### Retiring a rule

A rule is never deleted and its id is never reused. Retirement is: keep the heading,
add `superseded_by: NEW-ID` to the block, record the decision in `meta/OPEN.md`, and
rebuild. The id then resolves to a heading that says what replaced it, so a citation in
an old review comment or an old error payload still lands somewhere true.

**This exists because the corpus can only grow otherwise.** `SUPERSEDES` has been in the
graph model since it was written and is used zero times; every rule ever added is still
here. A corpus with no exit is a corpus that eventually breaks the budget premise its own
layered design rests on -- and that premise, that an agent operates at a few thousand
tokens, is the reason any of this is shaped the way it is.

Retire a rule when a later one subsumes it, when its mechanism has been folded into
another, or when it was always advisory and never once cited. Do not retire one because
it is inconvenient; that is a deviation, and `FLOW-008` covers those.

### Budgets

| File | Ceiling |
|---|---|
| `KERNEL.md` | 2,000 tokens |
| any module | 4,000 tokens |

Exceeding a ceiling is an error. Split the module or move detail into `examples/`.

## 3. Rule grammar

A rule is an H3 whose first token is its ID. Everything an agent needs to decide whether
a rule applies is on that one line, so `grep '^### '` over `law/` yields the complete
rule surface with no body text.

```markdown
### TYPE-012 · Domain code carries no `Any`  [BINDING] [auto:mypy]
Domain modules MUST NOT use `Any`, explicit or implicit.
- **Why** `Any` erases the guarantee the diagnostic envelope's `value` and `expected`
  fields depend on.
- **Check** `mypy --strict --disallow-any-explicit src/` · fitness `test_no_any_in_domain`
- **See** [fact/py-typing#strict-flags] · [TYPE-013] · [ARCH-020]
```

### 3.1 The heading line

```
### <ID> · <imperative title>  <force tag> [<mechanism tag> ...]
```

- **`<ID>`** — `<MODULE>-<NNN>`, where `MODULE` is the file's front-matter `id` suffix
  and `NNN` is a zero-padded three-digit ordinal. `TYPE-012`, `DIAG-004`, `ARCH-031`.
- IDs are **assigned once and never reused, never renumbered**. Deleting a rule leaves a
  gap; superseding one adds a `**Superseded by**` line, keeps the heading, and records a
  migration disposition in `meta/evidence.json`. Positional references are what the
  source corpus used, and they broke; IDs are the fix.
- IDs appear in review comments, commit messages, waiver comments, and in the
  `rule_ids` field of the diagnostic envelope. Treat them as public API.
- **`<imperative title>`** — states the rule, not the topic. "Domain code carries no
  `Any`", never "About `Any`". Under 60 characters.

### 3.2 Force tags

Exactly one per rule.

| Tag | Meaning | Requires |
|---|---|---|
| `[BINDING]` | Violation is a defect. **The default.** | at least one mechanism tag and a `**Check**` line |
| `[ADVISORY]` | A strong default; departure needs a reason recorded in the change. | a `**No mechanism**` line stating why none is possible |
| `[OPEN]` | Blocked on an undecided question. Cannot be `[BINDING]`. | an entry in `meta/OPEN.md` naming what it blocks |
| `[RETIRED]` | Historical ID with no current normative force. | no mechanism, `Check`, or `No mechanism`; migration disposition and optional successor |

Untagged prose in a `law` file is framing, not a rule, and carries no force.

**`[ADVISORY]` is an admission of failure, not a convenience.** Before a rule may take
it, a mechanism must have been attempted — a ruff rule, an import-linter contract, an AST
check in `enforce/checks/`, or a fitness test. `build_index.py` reports the `[ADVISORY]`
count as a quality metric to be driven toward zero.

### 3.3 Mechanism tags

Zero or more. They tell an agent which rules the toolchain already catches, so it need
not hold them in working memory — a direct saving of attention on every task.

| Tag | Enforced by |
|---|---|
| `[auto:ruff:<code>]` | a ruff rule, named |
| `[auto:mypy]` / `[auto:pyright]` | the type checkers as configured in `enforce/templates/pyproject.toml` |
| `[auto:import-linter]` | a contract in `enforce/importlinter.toml` |
| `[check:<name>]` | an AST check in `enforce/checks/<name>.py` |
| `[fitness:<test>]` | a test in `enforce/fitness/` |
| `[review]` | human or agent review only — permitted, but counts against the advisory metric |

### 3.4 Body

At most four lines after the heading: one normative sentence, then the fields below in
this order. Fields are optional individually; the order is not.

- **`Why`** — one sentence. Connect the rule to the Prime Directive wherever it can be
  connected: what does obeying this make diagnosable, or what does violating it make
  ambiguous? A `Why` that only restates the rule should be deleted.
- **`Check`** — the exact command or test name that decides the rule. Required for
  `[BINDING]`.
- **`No mechanism`** — required on `[ADVISORY]`, forbidden elsewhere. One sentence on why
  the rule cannot be checked. `build_index.py` collects these into
  `enforce/ENFORCEMENT.md` so the corpus's unenforceable surface is visible in one place.
- **`See`** — cross-references. `[MODULE-NNN]` for a rule, `[kind/MODULE]` for a module,
  `[kind/MODULE#anchor]` for a section. Every reference is resolved by the validator.

Rationale longer than one sentence belongs in `frame/`. Code longer than three lines
belongs in `examples/`, linked from `See`.

### 3.5 Normative keywords

`MUST`, `MUST NOT`, `SHALL`, `SHOULD`, `MAY`, in capitals, carry RFC 2119 force.
`SHALL` is a synonym for `MUST`. Lowercase "should" and "must" carry none — the source
corpus leaned on 110 lowercase "should"s and, as a result, nothing in it was
mechanically distinguishable as mandatory.

## 4. Rule evidence registry

`meta/evidence.json` is authored evidence joined one-to-one to the stable IDs in law and
ops. Markdown states the normative claim. The registry separately states why that claim
is plausible, what a mechanism can decide, and what remains possible after it accepts.
`validate.py` rejects a missing or orphan record and any disagreement with the mechanism
tags on the heading.

Every record carries exactly:

- `units`: one or both of `application` and `component`;
- `capabilities`: local capability keys that activate the rule, or an empty array for an
  unconditional rule;
- `failure_mode`: the consequence the normative rule is intended to prevent or contain;
- `warrants`: one or more sources, each with a `supports`, `motivates`, `limits`, or
  `observed-in` relation and explicit `high`, `medium`, or `low` confidence;
- `strategies`: exactly one entry per heading mechanism;
- `observations`: adopter or audit evidence IDs, never an unlabeled anecdote; and
- `migration`: source version, controlled disposition, and adopter guidance.

`meta/observations.json` resolves every field-evidence ID independently from the rule
records that cite it. Each observation states a defect/fact classification, bounded claim,
evidence kind, named evidence locations, reproduction (or explicit manual synthesis),
repository-local scope, and the source from which the packaged record was transcribed.
Observation presence does not prove generality beyond that scope.

Each strategy carries `mechanism`, `kind`, `relation`, `proposition`, `residual`,
`must_pass`, `must_reject`, `platforms`, and `not_applicable`. Kinds are `static`, `tool`,
`behavioral`, `generated-drift`, and `structured-review`. A relation is `direct` only
when the proposition is the normative condition itself; otherwise it is `proxy`, and the
residual says what semantic claim it does not decide.

Every automated strategy names a conformant reference and a deliberate case it must
reject. A `must_reject` label earns no credit until the discrimination gate witnesses the
mechanism reject it. Structured review instead verifies the review artifact's commit,
scope, freshness, reviewer, objections, conclusion, and residual; artifact integrity does
not make the judgment mechanically correct.

Generated views describe verifier availability as `local-verifier`, `external-verifier`,
`mixed-verifiers`, `structured-review`, `unbuilt`, `undeclared`, or `retired`. Those are
strategy states, not gate outcomes. Only an executed project gate may report `pass`,
`fail`, `not-applicable`, `unsupported`, or `not-run` for a particular repository and
platform.

Retiring a rule never deletes or repurposes its ID. Its heading remains resolvable, its
strategies are removed, `Superseded by` identifies the replacement when one exists, and
the registry disposition is `superseded`, `consolidated`, or `retired` with migration
guidance.

## 5. Epistemic tags (`fact` and `ops` only)

Claims in a `fact` or `ops` file carry a status tag, because these genres decay and a
reader has to know which claims to re-verify first.

| Tag | Meaning |
|---|---|
| `ESTABLISHED` | documented and stable in a cited primary source |
| `VERSION-DEPENDENT` | true of a named version; state the version |
| `OPEN` | no authoritative source; a convention someone must pin |

These grade *source authority*. They are orthogonal to `[BINDING]`/`[ADVISORY]`, which
grade *normative force* and never appear in a `fact` file.

A third scheme exists in the corpus — `STATED` / `INFERRED` / `ASSUMED` /
`ARCHITECTURAL-DECISION` / `UNRESOLVED`. It is **not** a tag for this repository. It is a
rule inside `frame/spec` about how to tag *your own* specifications, and conflating the
two is the mis-citation this format is written to prevent.

## 6. Cross-references

| Form | Target |
|---|---|
| `[TYPE-012]` | a rule, anywhere in the corpus |
| `[law/TYPE]` | a module |
| `[fact/py-typing#strict-flags]` | a section, by GitHub-style slug |
| `[examples/fault-schedules]` | a worked example |

Every reference resolves, or the validator fails. **References to files outside
`discipline/`, `enforce/` and `examples/` are errors** — the source corpus carried ~130
references to documents that do not exist, 73 of them to a single PROPOSAL.md, and that
is the failure mode this rule exists to prevent.

## 7. Generated files

`INDEX.md`, `rules.json` and `enforce/ENFORCEMENT.md` are written by
`tools/build_index.py` and carry a provenance header. Editing them by hand is an error;
the next build silently discards the edit. Change the source module and rebuild.

## 8. Glossary discipline

Terms defined in `meta/GLOSSARY.md` have exactly one meaning across the corpus. Several
are *banned in bare form* because the sources used them in incompatible senses —
`coverage` appeared in at least three, and one source declared the bare use of `atomic` a
documentation defect while another assumed it. The validator flags a bare use and
requires the qualified form.
