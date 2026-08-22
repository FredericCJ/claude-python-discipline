---
id: meta/CONFLICTS
kind: meta
title: Conflict Ledger
tokens: 3295
load_when: ["contradiction", "which source wins", "why was this decided", "precedence"]
decay: none
---

# Conflict Ledger

Every contradiction found between the source documents, resolved once here so it is not
re-argued per task. Resolutions are decisions, not discoveries; where one source was
simply **wrong**, that is marked, because a merge that averages a correct and an incorrect
claim produces a third, worse one.

## Precedence

1. The doctrine (`SE`, `TD`, `CA`) beats the style guidelines (`SG`). The doctrine is the
   later, Python-aware adaptation and names the supersession itself in its section 3.1.
2. More specific beats more general. `TD` sets thresholds; `SE` section 23 says outright
   that it binds the requirement, not the number.
3. `law/` never pins a version; pins live in `fact/` with a `verified:` date.
4. A consuming project's `CLAUDE.md` beats this discipline.

## Legend

`SG` style guidelines · `SE` doctrine/SOFTWARE-ENGINEERING · `TD` doctrine/TESTING ·
`CA` doctrine/CHEAPEST-ABLE · `AR` architecture manifest · `ET` error-tracing manifest ·
`LO` logging manifest · `TY` typing manifest · `TT` testing-tooling manifest ·
`SP` spec-discipline manifest

---

## Headline resolutions

### CONF-001 · Compiled core vs Python core

`SG` section 3 requires application cores to be compiled binaries and warns against
dynamic languages for long-lived cores. `SE` section 3 mandates Python for the same core
and spends a whole section calling this a deliberate departure with compensations owed.

**Resolved:** Python is the *premise*, not a departure. This is a Python discipline; a rule
framed as an apology for the language is noise on every read. `SG`'s underlying concerns —
exhaustiveness, a single deployable artifact, failure moved earlier — survive as the
*motivation* for strict typing, environment pinning and mutation testing, and are recorded
once in `frame/` rather than argued in `law/`.

### CONF-002 · Two error taxonomies

`SG` gives one flat list (`NotFound`, `InvalidCommand`, `InvariantViolation`, `Conflict`,
`PersistenceFailure`, `ProtocolViolation`, `UnsupportedVersion`, `CorruptState`). `SE`
splits it into two disjoint hierarchies with a layer-ownership rule, renaming four
variants (`CorruptState`→`CorruptModel`, `UnsupportedVersion`→`UnsupportedSchema`,
`PersistenceFailure`→`PortFailure`, `ProtocolViolation`→`ContractViolation`) and reusing
the freed name `ProtocolViolation` for a fault-model category.

**Resolved:** `SE`'s two-hierarchy form wins. Layer ownership is what makes an error's
`layer` field derivable, which the diagnostic envelope depends on. The freed name is
retired rather than reused; a name that means two things defeats the purpose of a code.

### CONF-003 · How many error channels

`AR` section 3.3 lists four permitted styles — exceptions, typed results, error codes,
panic/abort — and says "pick one per module boundary and hold it". `ET` section 3 says
"exactly two channels exist" and mandates a hybrid *within* a module: typed results for
contract outcomes, raised exceptions for the genuinely exceptional.

**Resolved:** `ET` wins on substance. The two-channel split is the one that makes "who
handles which failure" statically checkable, which is the whole point. `AR`'s four-style
menu moves to `frame/` as a description of what other systems do, stripped of its
"pick one and hold it" instruction, which would forbid the mandated hybrid.

### CONF-004 · Bare `raise` — a factual error, corrected

`AR` section 5.3 states that re-raising with a bare `raise` "loses the call site". `ET`
section 10 states, with a primary source, that a bare `raise` inside a handler *preserves*
the original traceback.

**Resolved:** `ET` is correct; `AR` is wrong and the claim is dropped, not merged. `AR`
was presumably reaching for "catching broadly and re-raising adds no context", which is a
different and true statement, and is what the rule now says.

### CONF-005 · Three clashing tag vocabularies

`doctrine/` grades normative force (`[BINDING]`/`[ADVISORY]`); four manifests grade source
authority (`ESTABLISHED`/`VERSION-DEPENDENT`/`OPEN`/`CC-FACT`); `SP` mandates a fifth,
different scheme (`STATED`/`INFERRED`/`ASSUMED`/`ARCHITECTURAL-DECISION`/`UNRESOLVED`).
`ET` section 6 then instructs the reader to apply the *second* scheme "per the
epistemic-tagging discipline of" the document defining the *third*.

**Resolved:** made orthogonal rather than merged. Force tags apply to rules in any genre;
epistemic tags apply only in `fact/` and `ops/`; `SP`'s scheme is not a tag for this
repository at all but a rule *inside* `frame/spec` about tagging one's own specifications.
The mis-citation is corrected in passing.

### CONF-006 · Version pinning vs version neutrality

`TT` pins `pytest`, `coverage.py` and `Hypothesis` to exact minor versions and stamps itself with an
access date. `CA` forbids naming a product anywhere in project documents, on the grounds
that the document must survive procurement changes. `SE` and `TD` mandate mutation testing,
MC/DC and fuzzing while deliberately naming no tool at all — and are, as a result,
unenforceable.

**Resolved:** the genre split settles all three. `law/` states the capability and never
pins; `fact/` carries every pin with a `verified:` date and a decay window; a rule's
mechanism names a concrete tool, which is what makes it runnable, but the tool can be
swapped without touching the rule.

---

## Remaining conflicts

| Id | Conflict | Sources | Resolution |
|---|---|---|---|
| CONF-007 | Faulty adapters for "important" ports vs every port unconditionally | SG / SE | Unconditional. A port judged to have no failure mode is the one whose failure is found in production. |
| CONF-008 | Contract suites for "every important port" vs every port | SG / SE | Superseded in v4: every declared internal contract registers real, controllable and scheduled-fault capabilities under one term-traced suite; no physical triad is required. |
| CONF-009 | `FaultSchedule(fail_write=3)` keyword form vs the structured `rules=(...)` form | SG / SE, TD | Structured form only; `SE` already declared the keyword form retired and incompatible. |
| CONF-010 | Port justification list of 9 items vs 8 | SG / SE | 8, and the list is closed and mandatory. The dropped ninth ("decoupling the domain from infrastructure") was subsumed. |
| CONF-011 | Techniques as a menu ("not every technique everywhere") vs each one binding with a CI gate | SG / SE, TD | Binding, with gates. A menu of verification techniques is how a suite ends up with none of them. |
| CONF-012 | `"Operations should normally be atomic"` vs `"a contract that says atomic without qualification is a documentation defect"` | SG / SE | The bare word is banned; see `meta/GLOSSARY.md`. |
| CONF-013 | Clients must not touch persistent state vs a sanctioned hand-editable authoring surface | SG / SE | `SE`: some files are a genuine authoring surface, with full validation re-run on next load. Never a weaker path, just a different entry. |
| CONF-014 | Metaprogramming permitted vs excluded unless four questions are answerable by reading | SG / SE | `SE`'s four-question test, as a hard exclusion inside the core. |
| CONF-015 | Distinct types "where practical" vs binding, with `NewType` and `Literal` banned | SG / SE, TY | Binding. A `NewType` has no constructor and validates nothing; a wrapper with a parsing constructor does. |
| CONF-016 | Flaky test "preferably reproducible" vs an unreproducible failure being a harness defect | SG / SE, TD | A defect, investigated at the priority of a domain bug. Never rerun-and-dismissed. |
| CONF-017 | Relational schema preferred vs a system with no database at all | SG / SE | Both were substrate-specific examples of one simplicity rule; the rule is kept, the examples are not. |
| CONF-018 | Test-double taxonomy: dummy/fake/stub/spy/mock vs real/fake/faulty | TT / TD | `real`/`fake`/`faulty`; Meszaros' terms are mapped onto it in the glossary. "Faulty" has no equivalent in the older taxonomy, which is why it is needed. |
| CONF-019 | Mocks permitted with `autospec`/`spec_set` vs silently excluded | TT / TD | Fakes implementing the contract. Mocks are permitted only where no contract exists to implement, and spies only inside fault tests. |
| CONF-020 | `monkeypatch` for clock and network vs both being ports with contract suites | TT / TD | Ports. A monkeypatched clock has no contract and cannot be fault-injected. |
| CONF-021 | `tmp_path` recommended generally vs forbidden at the unit layer | TT / TD | Layer-restricted: the unit layer touches no filesystem, so the general advice would license what a fitness test rejects. |
| CONF-022 | The word `coverage` used in at least three incompatible senses | TT, TD | Bare use banned; qualified forms defined in `meta/GLOSSARY.md`. |
| CONF-023 | Percentage as diagnostic vs unstated gate philosophy | TT / TD | A diagnostic. Gates are on **obligation coverage** and **artifact coverage**, never on a percentage. |
| CONF-024 | Strategy owned by "the team" vs mandated with executable gates | TT / TD | Mandated. Two documents cannot be concatenated when one declines to decide what the other requires. |
| CONF-025 | Unit-suite wall-clock total listed as a budget, then argued against as flaky and gameable | TD internal | Per-test budget is enforced; the total is reported, never gated. |
| CONF-026 | pydantic v1 vs v2 left open vs already mandated as v2 | ET / TY | v2. See `meta/OPEN.md`. |
| CONF-027 | Minimum Python 3.11 vs 3.12–3.14 vs unpinned | ET / TY / LO | Floor 3.11, target 3.13. See `meta/OPEN.md`. |
| CONF-028 | Logging rules restated in the error manifest despite its explicit non-duplication pledge | ET / LO | Logging mechanics live in `law/DIAG` once; the error-side obligations cite them rather than repeating them. |
| CONF-029 | Distributed tracing deferred to a document that declines it | ET / LO | Out of scope for single-process work, stated once rather than deferred in a circle. |
| CONF-030 | Lazy `%`-args mandated vs a pinned lint set that rewrites them to f-strings | LO / TY | Lazy args win; the ruff rule is configured explicitly rather than left to collide in CI. |
| CONF-031 | "Grounding, not a rulebook" disclaimers alongside hard mandates ("reject on sight", "treat any deviation as a spec violation") | AR, ET, LO, SP / TY | Dissolved by genre: mandates live in `law/`, grounding in `frame/`. No document has to be both. |
| CONF-032 | Error-context accretion stated without sources vs with them | AR / ET | `ET`'s sourced version, plus its preference for `add_note` over re-wrapping. |
| CONF-033 | Boundary-crossing logging triple and unconditional state-transition logging vs cost discipline | AR / LO | Kept, scoped to debug level and guarded, so the cost rule is not violated. |
| CONF-034 | Four vocabularies for one reuse objective (`atomic/integrated reusability`, goal3, reusability discipline, cohesion) | SP, LO, ET, AR | One vocabulary in `meta/GLOSSARY.md`; substitution evidence is the declared boundary representation, registered capabilities and shared contract suite, not a file triad. |
| CONF-035 | Agent-teams mechanics decaying in months, mixed with doctrine that decays in years or not at all | AT / rest | Separated into `ops/`, with `verified:` and `decay: months`, so its staleness is visible instead of inherited. |

---

## Dangling references

The source corpus carried roughly 130 references to documents that do not exist in it —
73 to a single PROPOSAL.md, plus TYPES.md, ARCHITECTURE.md, FAILURE-MODES.md, MIGRATION.md,
FEATURE-PARITY.md, `architecture/adr/`, prompt_discovery_partner.md, and failure-mode and
ADR identifiers.

**Resolved:** severed. Where a reference carried information, the information is inlined
and the pointer dropped — the recorded incident in which a directory-cleanup routine
destroyed 8,023 files while reporting success is kept as the justification for the
plan/apply rule, because the rule is not persuasive without it. Where a reference was
bookkeeping, it is deleted. `tools/validate.py` rejects any new one.
