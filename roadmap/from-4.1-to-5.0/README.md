# Python Engineering Discipline v5.0 roadmap

## From documented entities to evident source

| Field | Value |
|---|---|
| Status | Implementation, content audit and both-leg qualification complete; final content-bound review precedes the annotated tag |
| Baseline | v4.1.0 at `40466474ac91c5152f58a3fb20b7a93601c4016d` |
| Target | v5.0.0 |
| Governed unit | Exactly one application repository or one independently developed component repository |
| Distribution | One combined Claude Code and Codex discipline package |
| Input | [`inputs/python-commenting-and-documentation-discipline.md`](inputs/python-commenting-and-documentation-discipline.md) |
| Input SHA-256 | `23509318ef92d79240a931539eba0c57b4367f345f06c74ad99225bbd989fa72` |
| Qualified candidate | `58ae30f04ce5c3806bbba464ca562ff75aa79cc4` |
| Qualification evidence | [`evidence/release-qualification.json`](evidence/release-qualification.json) |

## Why this is v5

The supplied doctrine is not a formatting refinement. It makes three previously
conforming project shapes non-conforming:

- a project selecting `sphinx` or `none` as its documentation engine;
- Python whose modules, classes and callables are documented but whose local bindings are
  not; and
- source whose contracts are documented but whose execution is not narrated as semantic
  steps.

It also introduces a project-owned naming vocabulary and changes the pinned native
documentation tool. Those are adopter-visible contract, configuration and migration
changes. They therefore require v5.0.0 rather than a v4 minor release.

## Goal

Integrate the supplied commenting and documentation doctrine without flattening its two
different information layers:

1. Doxygen owns the structured meaning and contract of every program entity it can
   represent.
2. Ordinary implementation comments own control flow, data flow, sequencing,
   transformations, local reasoning and other execution detail that Doxygen cannot attach
   correctly.

The resulting source shall be readable structurally through generated documentation and
procedurally in the editor. A reader should not have to reconstruct what a named value
represents or translate an implementation from Python syntax into an unstated technical
procedure.

The existing prime directive remains unchanged. Documentation is useful here because it
reduces the inference needed to localize and repair a failure; it does not replace typed
contracts, diagnostic envelopes, executable tests or architecture boundaries.

## Scope

This roadmap governs repository-owned Python in one complete application repository or one
standalone component repository. The governed surface includes production code, tests and
repository-owned maintenance code selected by the project declaration. Generated Python
must be emitted conformantly by its generator. Third-party or vendored code is outside the
surface only when its foreign ownership is declared, never merely because a path is
inconvenient to migrate.

The following remain out of scope:

- parent-level orchestration of a multi-component application;
- implementation work in adopter or demonstration repositories outside this discipline
  repository;
- documentation hosting, publication infrastructure or a committed rendered site;
- a parallel Sphinx, pydoc or second docstring contract;
- non-Python source-language commenting rules; and
- automatic generation of semantic prose from identifiers or syntax.

Application and component fixtures created inside this repository are the release-deciding
round trips. The later implementation task expressly authorized one bounded field test of
`python-doctrine-test` and prohibited every other external adopter. That application was
used only through a disposable detached worktree: the v5 package was installed, integrated,
structurally migrated, and allowed to fail closed on its unauthored documentation debt. No
adopter source was repaired or committed, and its primary checkout remained clean. This
field observation is recorded separately and is not substituted for the synthetic release
fixtures.

## What v4.1 already provides

v4.1 is not starting from an undocumented codebase. It already has:

- `DOC-001` through `DOC-014`;
- docstrings for modules, classes and callables;
- Doxygen `##` blocks for module and class values that have no Python docstring slot;
- parameter, result and exception documentation checks;
- a Doxygen build with warnings as errors and a non-vacuity guard;
- checks for missing, misplaced, syntactically redundant and malformed documentation;
- proof-of-failure cases for every automated DOC mechanism; and
- exact Windows Conda and Linux Docker development legs.

Those mechanisms should be extended, not replaced wholesale.

## Baseline gap analysis

| Concern | v4.1 state | v5 obligation |
|---|---|---|
| Structured engine | Explicit `doxygen`, `sphinx` or `none` declaration | Doxygen is the sole structured engine |
| Engine version | Doxygen 1.10.0 pinned and empirically characterized | Doxygen 1.17.0 pinned and re-characterized on both development legs |
| Modules, types and callables | Covered by docstrings | Retain and strengthen semantic content checks |
| Module and class values | Covered by `##` blocks | Retain Doxygen ownership and broaden applicable semantic properties |
| Local bindings | Not inspected by `doc_coverage` | Every local binding has an associated semantic explanation |
| Implementation procedure | Ordinary comments are not governed | Logical operations and important execution paths are narrated |
| Units and representations | Required only indirectly by general contract prose | Explicit whenever interpretation depends on them |
| Booleans and collections | No specialized completeness rule | Both boolean states and collection semantics are explicit when applicable |
| Purity, effects and lifecycle | Distributed across API, EFCT and OPS rules | Their documentation obligation is explicit and cross-referenced, without duplicating behavioral rules |
| Naming vocabulary | No general project naming model | Domain-specific dimensions, ordering and abbreviations are declared and checked where decidable |
| Doxygen relationships | Basic source browsing and member extraction | Applicable cross-references, call relationships and dependency relationships are generated and proved non-vacuous |
| Synchronization | Signature shape and current parseability are checked | Detectable drift fails mechanically; semantic agreement is challenged by structured review |
| Tests | Coverage runs, while `doc_style` deliberately skips test content | Test implementation documentation follows the same allocation rules, with test-oracle documentation kept distinct |

The current kernel phrase “every element” is broader than the current checker: `DOC-002`
only walks module and class assignments. v5 must close that mismatch rather than declaring
the existing mechanism sufficient.

## Decisions fixed by this roadmap

### One structured documentation system

v5 projects select Doxygen. Python docstrings remain the storage location for elements
that have a docstring slot, and the project Doxyfile makes those docstrings Doxygen input.
This is one documentation system with a Python-native storage form, not parallel Doxygen
and Python-docstring contracts.

`##` remains reserved for Doxygen documentation of named entities without a docstring
slot. Ordinary single-hash comments remain non-extracted implementation narration.

### Doxygen 1.17.0 is an exact tooling target, not a law literal

The input names Doxygen 1.17. [Doxygen's release
ledger](https://github.com/doxygen/doxygen/blob/master/doc_internal/releases.md) records
1.17.0 and the [conda-forge package](https://anaconda.org/conda-forge/doxygen) publishes it
for the required Windows and Linux platforms. v5 shall pin and execute-check `1.17.0` in
`environment.yml`; the normative law shall state the required capabilities without a
version literal, as required by `meta/SCHEMA`.

Upstream has released newer versions. That does not silently change this roadmap. Moving
from 1.17.0 requires a separate fact refresh and compatibility decision.

### Comments attach to semantic steps

The target is not one comment per physical line. One implementation comment may own a
coherent logical operation spanning several statements, but every local binding and every
governed control-flow operation must resolve to exactly one nearby explanation. Linter
directives, type comments, commented-out code and section separators do not count as
documentation.

The association grammar must be defined before enforcement is enabled. It must cover at
least assignments, destructuring, loop and comprehension targets, context-manager aliases,
exception aliases, assignment expressions and pattern captures. Parameters remain owned by
the callable's Doxygen contract.

### Naming policy is project-owned data

The discipline shall not impose one application's domain tokens on another. Each governed
repository will declare its controlled abbreviations, generated-name boundaries and any
scope-specific semantic-dimension grammar in a versioned documentation model. Generic
schema checks and identifier checks enforce that declaration.

Semantic judgments that cannot be derived from syntax remain explicit structured-review
questions. A proxy must never be described as proving that a name or comment is true.

## Conflict resolutions to encode

| Tension | Resolution |
|---|---|
| Source permits semantic restatement; `DOC-009` rejects implementation narration in documentation | `DOC-009` continues to govern Doxygen entity contracts. A new narration family governs ordinary comments and explicitly permits semantic restatement while rejecting token-by-token paraphrase. |
| Source favors narrative completeness; `DOC-013` favors a short sentence | `DOC-013` remains the minimum for a simple entity contract. Narrative completeness applies to execution steps. Short and complete is acceptable; ceremonial filler is not. |
| Source says every variable is documented; Doxygen cannot necessarily attach documentation to every Python local | Doxygen owns only the entities proved representable by the 1.17 probe. Ordinary implementation comments own local bindings and temporary representations. |
| Source mandates Doxygen; `DOC-014` currently accepts three engines | Keep `DOC-014`'s stable meaning—selection is explicit—and add a v5 rule requiring the selected engine to be Doxygen. The v5 gate rejects `sphinx` and `none` with a migration diagnostic. |
| Source asks for all applicable Doxygen features; v4.1 disables two warning classes after measured false positives | Re-run the minimal reproducers against 1.17.0. The most accurate mechanism owns each proposition, even when that is the AST checker rather than Doxygen itself. |
| Source requires controlled abbreviations but says concrete grammars are domain-specific | Require a project documentation model; do not bake a universal vocabulary into the package. |
| Source requires synchronized truth; semantic truth is not generally statically decidable | Mechanize presence, association, signature agreement, structured fields and generated output. Bind the remaining semantic agreement to content-scoped adversarial review and state its residual honestly. |
| Source names generated elements; generated code may be regenerated | The generator owns the comments. Generated Python with missing documentation fails; hand-editing generated output is not the remedy. |

These resolutions must be entered in `discipline/meta/CONFLICTS.md` before dependent rules
land.

## Target corpus shape

The DOC family will exceed the 4,000-token module ceiling if the input is copied into one
law file. Split it while retaining the `DOC` rule family:

- `discipline/law/DOC.md` — allocation, entity coverage, Doxygen form and contract content;
- `discipline/law/DOC-NARRATION.md` — local bindings, semantic steps, control/data flow,
  algorithms, errors, state and resource sequencing;
- `discipline/law/DOC-NAMING.md` — semantic dimensions, deterministic ordering,
  controlled abbreviations, representation boundaries and generated names;
- `discipline/fact/doxygen.md` — dated 1.17.0 behavior and configuration truth;
- `discipline/frame/documentation.md` — non-prescriptive reasoning about evident source,
  comment granularity and unavoidable semantic judgment; and
- `discipline/examples/documentation.md` — positive and negative Python examples for both
  layers.

The exact new rule identifiers are assigned only when their mechanisms and evidence land.
Likely obligation families are:

| Family | Required proposition |
|---|---|
| Engine ownership | Every structured entity uses the one Doxygen-readable form allocated to it |
| Local bindings | Every locally bound name resolves to semantic documentation |
| Narrative operations | Governed control flow, transformations and sequencing resolve to implementation narration |
| Semantic properties | Applicable units, ranges, encodings, states, ownership and lifecycle are explicit |
| Callable effects | Purity, side effects, failures and externally visible state changes are documented |
| Naming model | Declared scope grammars and controlled abbreviations are internally consistent and obeyed |
| Generated names | Generated vocabulary stays distinguishable from canonical domain vocabulary |
| Synchronization | Detectable documentation drift fails and semantic agreement is reviewed against exact content |
| Doxygen projection | Required entity and relationship pages are generated and non-vacuous |

Existing IDs are not silently repurposed or renumbered. A broadened rule gets a new ID when
the old proposition would otherwise change meaning; superseded IDs remain resolvable with
migration guidance.

## Implementation phases

### Phase 0 — Freeze and account for the source

The byte-identical input copy is already complete in commit `613571d`.

Next:

1. assign the input a provenance tag;
2. enumerate every normative claim, not merely its 33 top-level sections;
3. create a machine-readable disposition ledger mapping each claim to retained,
   strengthened, split, superseded or rejected-with-reason;
4. teach the provenance builder to reject an unreviewed or multiply claimed source item;
   and
5. keep the input immutable—corrections belong in the target corpus or conflict ledger.

Exit: the copied hash still matches, every source claim has exactly one disposition, and
the generated provenance view reports zero unreviewed claims.

### Phase 1 — Qualify Doxygen 1.17.0 empirically

Build a minimal Python probe suite and run it through both shipped development legs. It
must decide:

- ordinary docstrings under `PYTHON_DOCSTRING = NO`;
- `##` and trailing `##<` entity comments;
- modules, private members, dataclasses, properties, enums and nested definitions;
- parameter, result, exception, precondition, postcondition and invariant commands;
- local-variable extraction limits;
- cross-references, call/caller relationships and dependency relationships;
- malformed-command and undocumented-element warning behavior;
- the three 1.10.0 defects currently recorded in `fact/doxygen`;
- HTML non-vacuity and deterministic local output; and
- offline output with no undeclared CDN or first-view network dependency.

Pin `doxygen=1.17.0` only after the Windows Conda and Linux Docker probes pass. Add and pin
Graphviz or another native helper only when a proven required relationship feature needs
it, then execution-check it like every other native tool.

Exit: a dated qualification artifact records commands, platform, package builds, versions,
fixture hashes, expected output and observed output. A failure blocks the phase; 1.18 or a
silent downgrade is not an automatic substitute.

### Phase 2 — Author the v5 doctrine and evidence

1. write the conflict decisions above;
2. split the DOC corpus under the measured module budgets;
3. preserve existing stable IDs and add new IDs only for new propositions;
4. update the kernel and skill router only after the target modules and mechanisms exist;
5. add one evidence-registry record per rule, with exact residuals and both application and
   component applicability;
6. cross-reference API, TYPE, EFCT, OPS, TEST and DEP rather than duplicating their
   behavioral obligations; and
7. regenerate the index, rule graph, enforcement matrix and both skill mirrors.

Exit: schema validation passes; every binding rule names exact strategies; every automated
strategy names a conformant control and a concrete counterexample.

### Phase 3 — Define project declarations and comment association

Introduce a versioned project-owned documentation model referenced from
`[tool.agent-discipline]`. Its schema shall cover:

- Doxygen as the selected engine;
- source scopes and explicit foreign/generated exclusions;
- controlled abbreviations with one meaning per declared scope;
- optional scope-specific identifier grammars and semantic-dimension ordering;
- generated identifier markers and mappings back to canonical terms; and
- any project-declared semantic properties that syntax alone cannot infer safely.

Define the comment-to-AST association grammar with fixtures before implementing a gate.
One narrative block may cover one semantic step and its bindings; a distant file-level
paragraph may not satisfy every later local. The grammar must remain stable under ordinary
formatting and must report ambiguity rather than selecting an arbitrary comment.

Exit: application and component fixture declarations round-trip through a strict schema,
unknown fields fail, paths cannot escape the repository, ambiguous comment ownership fails,
and a v4 declaration receives one actionable migration diagnostic.

### Phase 4 — Build the deciding mechanisms

Extend or add narrowly owned checks:

- `doc_coverage` discovers every governed binding shape and reports its exact missing
  documentation owner;
- a narration check associates ordinary comments with logical operations and rejects
  uncovered branches, loops, early exits, translations, state transitions and effect
  sequences;
- a semantic-content check verifies mechanically inferable obligations such as documented
  boolean states, collection element semantics and declared units without pretending to
  judge their truth;
- a naming check validates declared grammars, abbreviation mappings, generated-name
  boundaries and deterministic token ordering;
- the Doxygen gate proves required pages and relationships were actually generated, not
  merely enabled in configuration; and
- the adversarial-review checker requires content-bound challenges for comment truth,
  allocation, obsolete narration and domain naming judgments.

Each finding must identify the rule, file, element or logical operation, expected comment
owner and concrete remediation. Each mechanism lands with unit tests, property tests where
association is combinatorial, and one discrimination mutation for every proposition it
claims.

No permanent baseline may convert existing violations into acceptance. An inventory mode
may report migration work, but the release mode requires zero findings.

Exit: deleting an entity comment, local-binding explanation, branch narrative, unit,
boolean-state meaning, required abbreviation entry or Doxygen relation independently turns
the gate red with the expected rule ID.

### Phase 5 — Migrate this repository and its internal fixtures

1. inventory the complete governed Python surface by missing entity, binding and semantic
   step;
2. migrate in bounded module groups, keeping each commit internally consistent;
3. write semantic comments from the actual contract and implementation—never synthesize
   filler from identifiers;
4. refactor overly dense expressions when a stable comment owner cannot be assigned;
5. update comments in existing checks, tests and generated fixtures to the new allocation
   rules; and
6. make generators emit conforming comments rather than patching their outputs.

The implementation migration uses only this repository and synthetic in-repository
fixtures. The separately authorized `python-doctrine-test` field observation may exercise
the public package and migration commands in a disposable worktree, but shall not repair or
commit adopter source and shall not expand to another external repository.

Exit: the v5 mechanisms report zero undocumented entities, zero undocumented local
bindings, zero uncovered governed operations and zero undeclared naming-policy violations
over the discipline source and reference fixtures.

### Phase 6 — Ship the discipline through both agent hosts

Update:

- `environment.yml`, the Windows launcher verification and Docker image;
- canonical Doxyfile and project templates;
- project integration and migration tooling;
- README, integration guide, maintenance guide and v5 release notes;
- the authored `skills/python-discipline/SKILL.md`, followed by generated Claude and Codex
  mirrors; and
- vendoring and archive membership tests.

The archive remains one package. Claude Code and Codex discover mirrored entry points but
read the same vendored DOC corpus, examples, checks, templates and tool facts.

Exit: an extracted package installs into fresh synthetic application and component
repositories, produces identical host integrations, rejects a v4 documentation declaration
with migration guidance, and passes after that synthetic repository is migrated.

### Phase 7 — Qualify and release v5.0.0

Run the complete qualification matrix:

| Leg | Required proof |
|---|---|
| Windows | Fresh Conda environment resolves the exact lock, reports Doxygen 1.17.0 and passes the source gate |
| Linux | Clean Docker build resolves the exact lock, remains non-root at runtime and passes the same gate |
| WSL fallback | Linux launcher reaches Docker Desktop through its existing fallback and runs the documentation gate |
| Application fixture | Packaged discipline installs, finds the complete governed surface and builds non-vacuous documentation |
| Component fixture | The same package and rules work without assuming a parent repository or counterpart component |
| Negative fixtures | Every new automated DOC proposition rejects its independent counterexample |
| Archive | Two independently staged archives are byte-identical and leak-clean |

Refresh the content-bound adversarial review after all target files are frozen. It must
challenge comment truth, Doxygen/implementation-comment allocation, stale narration,
local-binding coverage, naming-model sufficiency, generated code and both platform legs.

Exit: the eleven-step gate and release command pass, validation reports zero errors, the
review concludes with no unresolved blocker, and the annotated `v5.0.0` tag points at the
exact reviewed commit.

## Proof matrix

| Requirement | Primary mechanism | Required counterexample |
|---|---|---|
| Doxygen is the structured engine | Declaration/schema check | A project declaring `sphinx` |
| Every Doxygen-capable entity is documented | Extended `doc_coverage` plus Doxygen | An undocumented private field and an undocumented generated field |
| Every local binding is documented | Binding-association check | One missing name in a destructuring assignment |
| Execution is narrated by semantic step | Narration check | An uncommented early return and an uncommented exception translation |
| Comments are not directives or syntactic filler | Comment classifier plus structured review | A `# noqa` and “increment i” used as the only comment |
| Units, states and collection semantics are explicit | Semantic-content check | A declared unit-bearing value without its unit and a Boolean with one state only |
| Abbreviations are controlled | Documentation-model schema plus naming check | One undeclared abbreviation in a governed scope |
| Semantic dimensions obey project order | Naming grammar check | Two independently valid tokens in the wrong declared order |
| Generated names do not define domain terms | Generated-name mapping check | A generated prefix used as a canonical project term |
| Doxygen relationships are real | Generated-output inspection | Configuration enables a relation but the fixture generates none |
| Comments remain truthful | Content-bound adversarial review | A syntactically complete comment that narrates the previous behavior |

The last row is deliberately not labeled static verification. General semantic truth is a
program-understanding problem; the mechanically verifiable surrounding propositions still
shall be enforced.

## Commit train

Implementation should retain the repository's Conventional Commit history and land as
small, self-consistent changes. The expected sequence is:

1. `docs(provenance)` — claim-level disposition ledger and conflict decisions;
2. `test(doxygen)` — 1.17.0 behavior probes and recorded expectations;
3. `feat(env)` — exact native pins and both-leg execution checks;
4. `docs(discipline)` — split DOC modules, evidence and worked examples;
5. `feat(enforce)` — project documentation model and declaration migration diagnostic;
6. `feat(enforce)` — local-binding and semantic-step checks;
7. `feat(enforce)` — semantic-content and naming checks;
8. `test(discrimination)` — independent proof-of-failure cases;
9. `refactor(documentation)` — bounded migration commits by module group;
10. `feat(package)` — combined-package delivery and round-trip fixtures;
11. `docs(review)` — frozen qualification and adversarial acceptance; and
12. `docs(release)` — migration guide and v5.0.0 release record.

A rule, its evidence, its deciding mechanism and its counterexample should land together.
Environment changes and empirical facts should precede laws that depend on them.

## Principal risks and controls

| Risk | Control |
|---|---|
| Narrative comments become ceremonial noise | Enforce semantic-step granularity, reject known filler shapes, retain content review and permit concise accurate comments |
| Comments drift while code changes | Check signature/field agreement mechanically and require content-bound review of changed behavior |
| Local-binding association produces false positives | Specify ownership before implementation; test every Python binding form and fail on ambiguous ownership |
| Doxygen 1.17 changes known Python parser behavior | Re-run reduced 1.10 reproducers and assign each proposition to the most accurate mechanism |
| Relationship generation adds undeclared native dependencies | Add only dependencies proved necessary, pin them on both legs and execution-check them |
| Generated HTML attempts network access | Qualify offline output and configure locally rendered features; no CDN dependency is accepted silently |
| Domain naming rules leak into the generic package | Keep vocabulary and dimension grammar project-owned; package only the schema and checker |
| Naming checks overclaim semantic correctness | State exact syntactic propositions and residuals; use structured review for meaning |
| Migration is too large for review | Inventory first, migrate by module group and forbid mass-generated semantic prose |
| The new gate becomes prohibitively slow | Measure each mechanism on Windows and Docker, retain static single-pass parsing and set explicit build budgets |

## Implementation outcome

The roadmap was executed as one breaking v5 release rather than split across a minor
series:

- all 365 imported normative claims have exactly one disposition: 106 retained, 114 split,
  and 145 strengthened, with zero unreviewed or multiply claimed items;
- Doxygen 1.17.0 and Graphviz 14.1.2 were empirically qualified on Windows Conda and Linux
  Docker, including extraction limits, warning behavior, relationships, offline output and
  deterministic generation;
- `DOC-015` through `DOC-019` and `DOC-022` through `DOC-029` carry exact mechanisms,
  residuals and independent discrimination witnesses without repurposing the earlier IDs;
- a strict project documentation model, comment-association grammar, four complementary
  source checks and a generated-output gate now decide the mechanically expressible layer;
- all 180 governed repository Python files are clean under the v5 documentation gate, and
  the behavior oracle distinguishes prose-only work from intentional executable change;
- the public v4-to-v5 migrator and one combined Claude Code/Codex package round-trip both
  application and single-component repositories through synthetic release fixtures;
- the one authorized `python-doctrine-test` field exercise proved conservative migration
  and fail-closed authorship debt without modifying its primary checkout;
- the complete 11-step source gate passed through both shipped development legs; and
- the non-skipped Windows release command produced the deterministic, leak-clean archive
  recorded in `evidence/release-qualification.json`.

The implementation exposed qualification defects rather than ratcheting them away. Earlier
passes repaired a stale textual target, NTFS executable-mode and metadata distortion,
Docker Desktop's unavailable WSL-directory mount service, and a leak-scanner self-match.
The final content audit additionally repaired eleven new Ruff file/code pairs, removed a
LEARN-006 mutation's dependency on generated narration, and raised the finite Windows
meta-test budget after the expanded 194-case census exceeded its inherited 420-second
ceiling. Two already-running legacy-package launchers also rewrote the shared `claude`
environment during qualification; the v5 launcher detected and repaired that drift, and
the final runs were made without a concurrent legacy writer. The qualification artifact
binds each product failure to its repair and retains the shared-environment race as an
explicit operational residual.

## Release acceptance

v5.0.0 may be tagged only when all of the following are true:

- the input hash still matches the frozen copy;
- every input claim has exactly one disposition and no source material is silently lost;
- Doxygen 1.17.0 is locked and execution-verified on Windows and Linux;
- the applicable Doxygen feature matrix is proved against generated output;
- every new binding rule has exact evidence, residuals and a witnessed counterexample;
- all governed repository-owned Python and generated fixtures satisfy both documentation
  layers;
- application and component package round trips pass without external repositories;
- the canonical skill and both host mirrors agree;
- the full source and project gates pass on both development legs;
- the final adversarial review is content-bound and current; and
- the release archive is deterministic, leak-clean and built by the non-skipped release
  command.
