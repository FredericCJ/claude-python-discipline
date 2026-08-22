# Python Engineering Discipline v4 roadmap

## From v3.2 adoption evidence to v4.0.0

| Field | Value |
|---|---|
| Status | Proposed roadmap |
| Target | v4.0.0 |
| Doctrine evidence baseline | v3.2.0 |
| Packaging baseline | v3.3.0 |
| Product scope | Consequential, potentially long-lived Python systems |
| Primary validation adopters | `python-doctrine-test` and `multi-components` |

This roadmap proposes a major release because it changes the meaning and scope of
several architectural rules. It does not relax the discipline into a style guide, make
small programs a target, or trade strict typing for Python idiomacy. Its purpose is to
make the existing doctrine more truthful about what its gates prove and more complete
for componentized and operational systems.

The intended v4 thesis is:

> A consequential Python system shall make its decisions, effects, failures, runtime
> topology, and recovery mechanically inspectable to the greatest extent possible; every
> mechanism shall state exactly which observable proposition it decides and what remains
> outside that decision.

The roadmap uses three evidence labels:

- **Observed** means present in a checked-out adopter, its tests, its learning ledger, or
  its git history.
- **Inferred** means a design conclusion drawn from those observations and the supplied
  software-engineering corpus.
- **Proposed** means a v4 decision to implement; it is not current doctrine.

## Executive decision

Ship the next semantic doctrine as **v4.0.0**. Do not put the changes below into a v3
minor release.

v3.3.0 has already completed the delivery change requested before this audit: one
authored skill is packaged once and exposed through byte-identical native discovery
surfaces for Claude Code and Codex. That is a v4 invariant, not unfinished v4 work.
Only correctness fixes that preserve v3 semantics should be backported to v3.3.x.

The reason for the major version is not stricter enforcement. It is that v4 must replace
four assumptions embedded in v3:

1. one Python package can be modeled as one fixed four-layer architecture;
2. an import graph adequately represents architecture;
3. a mechanism attached to a rule proves the whole rule;
4. every port, test layer, and documentation element should have one prescribed physical
   representation.

Those assumptions worked as scaffolding for a single package. They do not survive the
multi-component adopter without local workarounds, duplicated truth, or claims stronger
than the evidence.

## Non-negotiable inheritance from v3

v4 shall retain these principles without dilution:

- The discipline targets consequential, potentially long-lived applications. Small
  scripts and disposable programs remain out of scope.
- If a proposition can be mechanically verified, it shall be mechanically verified.
- Strict static typing remains mandatory. The domain admits no implicit `Any`; boundary
  parsing, exhaustive result handling, narrow escape hatches, and two independent strict
  checker verdicts remain the default assurance posture.
- The functional core remains isolated from foreign effects and transport/framework
  representations.
- Dependencies point toward policy; external technologies remain replaceable at explicit
  boundaries.
- Expected outcomes and exceptional failures use explicit, typed channels.
- Escaping failures remain structured, stable, attributable, and cause-preserving.
- Tests state their oracle and cover contracts, properties, faults, containment, and
  delivered behavior.
- Structural decisions, rejected alternatives, deviations, and session learnings remain
  durable repository evidence.
- A gate that cannot fail, does not load its configuration, silently skips a platform, or
  checks a different artifact from the one delivered is defective.
- Claude Code and Codex receive the same discipline from one package and one authored
  source.

Two additional axioms make the mechanical-verification principle safe:

1. **A mechanism shall claim no more than the observable proposition it decides.**
2. **Mechanical enforceability is not evidence that a rule is beneficial.** Benefit is
   justified separately by failure-mode analysis, source warrant, and adopter evidence.

These axioms strengthen mechanical verification. They prevent a syntactic proxy from
being mistaken for a semantic proof.

## Explicit non-goals

v4 will not:

- optimize the doctrine for toy programs or make `sumtwo` representative of normal
  project economics;
- optimize for Python idiomacy, brevity, or community convention where those conflict
  with transposable engineering principles;
- make typing optional or introduce a weakly typed profile;
- turn capability activation into an à-la-carte rule waiver system;
- prescribe microservices, processes, repositories, or network boundaries as ends in
  themselves;
- claim that passing more checks proves better architecture;
- copy the older embedded doctrines wholesale. They are design and failure evidence, not
  a normative parent of the Python discipline.

## Evidence baseline

### Version truth

The checked-out `python-doctrine-test` history vendors v3.0.0, although it has been
presented as a v3.2 adopter. Its evidence remains valuable, but it shall be classified as
the deliberately maximal **single-package conformance specimen**, not as proof of a
v3.2-specific mechanism.

The `multi-components` meta-repository and all four component repositories identify their
vendored discipline as v3.2.0. The current discipline repository is v3.3.0 because the
combined Claude/Codex packaging work landed after those adopter runs.

v4 certification shall record exact discipline release, manifest digest, adopter commit,
submodule commits, environment digest, OS, and interpreter for every result. A human
label such as “tested with v3.2” shall never override repository evidence.

### What `python-doctrine-test` establishes

**Observed strengths**

- A trivial problem can be projected through the full architecture without losing an
  exact behavioral specification.
- Typed parsing and scaled-integer arithmetic make invalid input and exact decimal
  behavior explicit.
- The same console contract is exercised against real, fake, and faulty implementations.
- Unit, application, contract, property, fault, and process tests are visibly distinct,
  and diagnostics are asserted as data.
- The git history explains why each layer, port, representation, and gate exists.

**Observed pressure points**

- The design record explicitly overrules the objection that a port around three console
  calls is ceremony because maximal conformance is the experiment's purpose. This is not
  evidence that every production port earns that cost.
- The suite described in history contains 79 tests for a 19-file source package. That is
  legitimate for the planned book, but it makes `sumtwo` a poor cost-benefit benchmark.
- A strict-typing workaround replaces `10 ** scale` with repeated multiplication because
  of a checker/typeshed result. The workaround is type-clean but makes the cost of a
  scale proportional to the input exponent.
- The accepted input grammar has no digit or scale budget, the dialogue has deliberately
  unbounded retries, and the “exact for every accepted input” claim is not paired with an
  adversarial resource bound. Strict typing cannot prove availability or bounded work.
- The process test runs `python -m sumtwo` with a source-path injection. It does not prove
  the built and installed console entry point works.
- Most recorded learnings concern tool invocation, encodings, Doxygen discovery, and type
  checker behavior. These are useful portability facts, not evidence that every
  architectural prescription pays for itself.

**v4 use of this adopter**

Keep the over-engineering. Designate the repository as a pedagogical and conformance
specimen whose purpose is to exhibit the entire doctrine on a small state space. Do not
weaken it to make v4 look lean. Instead, make its exceptional posture explicit and use it
to test traceability, migration, diagnostics, generated views, and installed-artifact
verification.

### What `multi-components` establishes

The four component repositories contain 161 Python source files and 107 Python test
files. The inspected trees contain approximately 13,557 source lines and 12,075 test
lines, 25 port modules, and 77 adapter modules. This is a genuine test of repeated
boundaries, protocol behavior, concurrency, subprocesses, networking, shutdown, and
cross-repository composition.

**Observed strengths**

- “Components know contracts, never counterparts” produced independently buildable
  components whose local source does not encode composition wiring.
- Each component has a pure domain, typed ports, technology adapters, structured error
  taxonomy, fault injection, and contract tests.
- Adversarial specification passes found 32 system-spec findings and 16 orchestration
  findings before implementation. Component-level adversarial passes then found and
  repaired additional boundary, lifecycle, taxonomy, rendering, and ordering defects.
- Failure behavior is unusually explicit: startup gates, watchdogs, backpressure,
  termination reasons, drain bounds, process groups, exit codes, and no-orphan intent are
  present in the specifications and histories.
- The allocation/refinement/verification workflow produced bounded component work without
  leaking topology into component sessions.

**Observed doctrine gaps**

- The master `IF-*` contracts are manually restated in component specifications. The
  repository learning ledger says contract changes must land in five repositories in
  step. The specification promises composition-level golden tests to catch drift, but
  the meta-repository currently has no test tree or gate that does so.
- The meta-repository vendors the discipline and announces a Python gate, yet it has no
  `pyproject.toml`, import contracts, test suite, or gate runner. Its `toybox` contains 358
  lines of operational Python outside the discipline's effective gate.
- `toybox` is explicitly a stand-in, and manual scenarios are carefully recorded, but
  observed manual runs are not a repeatable system gate. Product claims and observed
  evidence are therefore easy to conflate.
- The top-level README still says implementation has not started although all four
  components and the one-command toybox launcher are present. This is concrete
  cross-repository documentation drift.
- Three component repositories had to add project-owned check runners because the
  vendored aggregate checker ignored `[tool.agent-discipline]`. It could both emit false
  layer findings and silently disable documentation checks while reporting a clean run.
- The console component exposed a direct conflict between `ARCH-004` and `ARCH-011`:
  forbidding transitive access from the composition root to foreign modules makes the
  required root-to-real-adapter wiring impossible.
- The exception-code checker rejected hyphenated codes already published by the
  component specification. The project worked around the checker rather than changing a
  frozen vendored discipline.
- Mutation remains configured but unavailable on the supported Windows development
  machine. A configured, permanently skipped binding gate is not verification.
- `conda run` is acceptable for tooling but unsafe inside the runtime process tree:
  wrapper processes break signal ownership and PID-based teardown. v3 has no first-class
  distinction between development-tool invocation and production process topology.
- The component import graphs are checked, but the runtime communication graph, process
  ownership graph, shutdown graph, and fault-containment graph exist only in prose.

**v4 conclusion from this adopter**

v3 is effective inside a component and incomplete above it. v4 needs a composition scope,
a single-source contract mechanism, explicit runtime graphs, and a root gate that joins
component evidence without teaching components who their counterparts are.

### What the predecessor doctrines contribute

The supplied embedded, agent-operated-codebase, and real-time-audio doctrines contain
concepts that v3 lost while correcting their implementation failures:

- information hiding and change scenarios as the reason for a boundary;
- separate static-dependency and runtime-communication graphs;
- safe/degraded state, recovery ownership, escalation ladders, and bounded cleanup;
- explicit time, memory, queue, latency, and shutdown budgets;
- runtime topology, build identity, security posture, and operational observability;
- lossless generated projections, independent diffing, byte-exact gate-refactor tests,
  and adversarial acceptance;
- repairing a defect class rather than only the observed instance.

Their negative evidence matters equally: broad doctrine prose, generated confidence, and
green gates did not prevent semantic residue. v4 shall recover the concepts only after
giving each one a scope, an observable claim, a verifier, and a stated residual.

### What the SWE resource graph contributes

The typed SWE corpus supplies warrants for information hiding, dependency restriction,
hexagonal boundaries, functional-core/imperative-shell separation, contracts, dependency
inversion, static typing, and systematic testing. It does not establish that this exact
composition of rules is effective, nor does source verification equal empirical
validation.

v4 shall use the graph to answer “why is this rule plausible?” and adopter evidence to
answer “what happened when we used it?” Those are different relations in the rule model.

## The v4 doctrine model

### 1. Separate normative, decidable, and empirical claims

Every rule shall expose three layers instead of flattening them into one `mechanized`
label:

| Layer | Question | Example |
|---|---|---|
| Normative | What engineering obligation holds? | A component hides a volatile decision. |
| Decidable | What exact proposition can a mechanism observe? | A checked dependency edge does not cross the declared owner. |
| Empirical | What happened in a named adopter? | A composition-root contract rejected a valid transitive edge. |

The v4 rule schema shall carry at least:

- stable rule id and normative force;
- applicability scope and capability activation;
- failure mode the rule is intended to prevent;
- source warrants, with relation type and confidence;
- exact observable proposition for every mechanism;
- mechanism kind: static, tool, behavioral, generated-drift, or structured review;
- known residual: what can still be wrong after the mechanism passes;
- positive reference and must-reject discrimination case;
- supported platforms and explicit not-applicable conditions;
- adopter observations, kept distinct from sources and rationale;
- supersession and migration metadata.

A structured review may decide a semantic obligation that syntax cannot. The gate can
mechanically verify the review artifact's scope, freshness, reviewer independence,
verdict, and closure of findings; it shall not claim that file presence proves the review
was insightful.

`FLOW-006` and `FLOW-007` shall be revised around this model. A binding semantic rule
needs a declared verification strategy, but a presence check is not allowed to masquerade
as a semantic decision.

Rule ids shall not be silently repurposed. A clarification that preserves the obligation
may retain an id. A change of subject or meaning shall introduce a new id, retain the old
id as a resolvable retired record, and provide `superseded_by` plus migration guidance.

### 2. Make information hiding primary

The v4 architectural unit is a **decision-hiding component**, not a directory named after
a layer. Every component shall state:

- the volatile decisions it owns;
- the change scenarios it is intended to absorb;
- the contracts it publishes or consumes;
- the state and resources it owns;
- the failures it contains, translates, or escalates;
- the runtime roles it can occupy.

The familiar roles remain useful, but they become roles in a partial order rather than a
command that every repository contain exactly four directories:

| Role | Responsibility |
|---|---|
| Domain | Pure policy, values, invariants, and typed outcomes |
| Application | Orchestration, sequencing, recovery decisions, and calls through injected ports |
| Port/contract | Stable boundary vocabulary and behavioral terms |
| Adapter | Translation and foreign technology effects |
| Shell/composition | Concrete wiring, process lifecycle, final rendering, and escape handling |

Ports are contracts, not a fifth layer. A multi-component repository may repeat these
roles inside each component. A composition repository may contain little or no domain
logic and still be governed because its policies concern wiring and lifecycle.

### 3. Resolve effect semantics

v4 shall replace the current ambiguity between a pure application layer and the adopter
reality in which application services call ports:

- Domain code performs no effects and imports no effect-capable technology.
- Application code may invoke injected ports. It owns policy-level sequencing and
  recovery but cannot name concrete adapters or foreign APIs.
- Adapters perform foreign effects and translate foreign representations and failures.
- The shell selects adapters, owns process/runtime setup, and handles the final escaping
  failure.
- A destructive or multi-effect capability activates plan/apply, journaling,
  interruption, and recovery obligations. Simple idempotent port calls do not acquire a
  fake command-plan layer merely to satisfy a folder model.

This preserves functional-core/imperative-shell reasoning while describing the code the
adopters actually contain.

### 4. Model four distinct graphs

Every componentized system shall have mechanically derived or checked views of:

1. **Source dependency graph** — imports and build dependencies.
2. **Runtime communication graph** — which role sends what contract to which role.
3. **Resource and ownership graph** — processes, threads, sockets, files, queues, state,
   and their owner.
4. **Failure and recovery graph** — detection boundary, containment boundary, recovery
   owner, escalation path, and terminal safe/degraded state.

The component repository declares role-facing endpoints and contracts. Only the
composition repository binds roles to concrete components. A gate shall reject peer names
or topology in a component, while the composition gate shall reject an unbound required
role, incompatible contract version, ownership cycle, or recovery path with no owner.

### 5. Activate obligations by capability, not taste

All v4 projects remain under the consequential-system kernel. A checked project manifest
declares facts that activate additional obligations; it does not waive core rules.

An illustrative, non-final shape is:

```toml
[discipline]
scope = "component"          # component | composition | contract-library | specimen
assurance = "consequential"

[capabilities]
public_api = true
persistent_state = false
generated_artifacts = false
network_ipc = true
subprocess_tree = true
concurrency = true
destructive_effects = false
real_time_or_bounded_latency = false
sensitive_data = false
```

The gate shall infer capabilities from imports, build metadata, and declared topology and
fail on an undeclared observed capability. A declaration may activate more rules than
inference can discover, never fewer.

Examples:

- `network_ipc` activates protocol framing, malformed-message, timeout, backpressure,
  disconnect, correlation, and shutdown obligations.
- `subprocess_tree` activates group/job ownership, wrapper-free launch, signal routing,
  bounded reap, and no-orphan tests.
- `persistent_state` activates schema compatibility, migration, single-writer, recovery,
  and corruption tests.
- `generated_artifacts` activates source-of-truth, provenance, lossless round-trip,
  independent drift, and byte-stability checks.
- `sensitive_data` activates data classification, redaction, least exposure, and security
  review rather than pretending a keyword regex proves no secret can escape.
- `real_time_or_bounded_latency` activates explicit budgets and measurement at the
  relevant percentile and platform.

`sumtwo` shall use `scope = "specimen"`; that scope deliberately exercises the maximal
teaching projection and is not a lightweight profile for ordinary small programs.

### 6. Make contracts single-source and role-neutral

v4 shall define a machine-readable, versioned contract catalog from which human
documentation, schemas, typed carriers/codecs where appropriate, compatibility fixtures,
and component-local normative projections can be generated or checked.

The solution must preserve component isolation:

- contracts name roles, never counterpart repositories;
- component projections can be vendored and verified by digest so a component remains
  independently buildable;
- the composition manifest alone maps role endpoints to component versions;
- generation is lossless or independently diffed against the canonical model;
- an edited projection fails locally, and incompatible catalog/component revisions fail
  at the composition root;
- contract evolution carries compatibility policy, migration when relevant, and fixtures
  for the previous supported version.

The specific catalog representation shall be selected by a prototype, not by aesthetic
preference. The selection gate is round-trip fidelity, diff quality, typed-codec support,
and independence from a particular transport.

### 7. Add operational completeness to the kernel

The embedded doctrines correctly treated operational behavior as architecture. v4 shall
introduce binding, capability-aware obligations for:

- safe and degraded states;
- recovery owner and escalation ladder;
- startup, steady-state, interruption, drain, shutdown, and forced-teardown phases;
- time, memory, queue, retry, input-size, and cleanup budgets;
- resource acquisition/release ownership;
- non-exception outcomes and state transitions as observable events;
- runtime and build identity in diagnostics;
- security assumptions and the boundary at which they stop being valid;
- environmental portability, including signal, encoding, filesystem, and process-model
  differences.

A type-correct program with unbounded work, an ownerless recovery path, or a clean local
import graph but an unsafe runtime topology is not conformant.

## High-impact rule migrations

The v4 authoring phase shall audit every rule, but these migrations are already justified
by adopter evidence:

| v3 surface | v4 direction |
|---|---|
| `ARCH-001` fixed inward layers | Supersede with declared roles and a checked dependency partial order per component. Do not assert an exact layer count. |
| `ARCH-004` one foreign dependency per module | Supersede with one owning adapter boundary/package. Check direct ownership; allow the shell's intentional transitive reach through the selected adapter. |
| `ARCH-007`, `TYPE-009` structural `Protocol` | Require an explicit typed boundary contract. Structural versus nominal representation is a local decision whose enforcement must match the chosen form. |
| `ARCH-008` real/fake/faulty triad | Require real conformance, a contract-verified controllable test implementation, and fault-schedule coverage. Permit one implementation to realize multiple test capabilities; do not require three files or classes. |
| `ARCH-009`, `TEST-005`, `TEST-006` | Consolidate overlapping claims into semantic conformance: all implementations used as substitutes run the same observable contract suite; the suite's coverage is declared against contract terms and failure modes. |
| `ARCH-010` port justification | Base justification on a volatile decision, effect boundary, fault-containment boundary, or independently variable contract—not on a generic “may replace” statement. |
| `EFCT-001` effects only in shell/adapters | Clarify that application orchestration invokes effects through ports while foreign I/O remains in adapters and process concerns remain in the shell. |
| `DEP-001` standard-library-only domain | Preserve as an activatable high-assurance constraint. The universal rule is that domain dependencies are pure, explicitly allowed, versioned, and isolated from framework/transport ownership. |
| `TYPE-006` every closed set is an enum | Require an exhaustively checkable closed representation. Enum, literal union, and tagged data union are valid when their semantics fit. Strict exhaustiveness remains mandatory. |
| `DOC-001`, `DOC-002`, `DOC-007` universal element prose | Require documentation for public contracts, boundary terms, invariants, non-obvious policy, failure semantics, and operational assumptions. Do not reward filler that merely restates a private name or type. The specimen may retain maximal element coverage. |
| `DOC-014` engine declaration | Make declaration loading part of the canonical gate API and its discrimination suite; a missing declaration may never narrow checks silently. |
| `DIAG-002` code regex | Define code grammar once in the error-taxonomy model and generate validator, docs, and fixtures from it. |
| `DIAG-010`, `DIAG-016` exception-centric observability | Extend to typed refusal results, dropped work, retries, transitions, recovery, and terminal reason. “Logged once” is subordinate to complete event semantics. |
| `API-015` delivered artifact advisory | Make built-wheel/sdist installation and public-entry-point tests binding for a published package or CLI capability. |
| `TEST-002` every named test layer populated | Activate suites from obligations and capabilities. An empty irrelevant directory is not quality; an untested active contract is a release blocker. |
| `TEST-013` mutation on the core | Retain mutation as a preferred mechanism, but require an executable supported-platform gate or an explicitly equivalent discrimination strategy. Permanent local skip is not green. |
| `FLOW-006`, `FLOW-007`, `TEST-015` | Apply to each exact decidable proposition, with a must-pass reference, a must-reject mutation, configuration-load proof, and stated residual. |

New rule families should be introduced rather than overloading unrelated ids:

- `EVID-*` — claim typing, warrants, residuals, discrimination, and field evidence;
- `COMP-*` — component scope, contract catalogs, role binding, topology, and root gates;
- `OPS-*` — lifecycle, resources, budgets, safe state, recovery, and build identity;
- `SEC-*` — security assumptions, data classification, trust boundaries, and redaction
  evidence.

Exact ids and statements are an alpha deliverable. They shall pass the same adversarial
review required of product contracts before becoming binding.

## Enforcement architecture

v4 enforcement shall have one programmatic gate API and generated command entry point.
Adopters shall not need repository-owned clones of the vendored aggregate runner.

Every mechanism declaration shall name:

- the rule and exact proposition decided;
- paths and scope inspected;
- project declaration fields consumed;
- tool version and supported platforms;
- stable diagnostic id;
- reference case expected to pass;
- one or more mutations expected to fail by that diagnostic id;
- residual cases it does not decide.

The gate shall distinguish `pass`, `fail`, `not-applicable`, `unsupported`, and
`not-run`. Only `pass` and valid `not-applicable` can contribute to a green verdict.
`unsupported` and `not-run` remain visible failures for a required release platform.

The root gate for a composition shall:

1. verify exact component revisions and discipline manifests;
2. run or consume signed/digested component gate reports;
3. validate the contract catalog and every component projection;
4. validate role binding, version compatibility, runtime/resource/recovery graphs, and
   configuration single-sourcing;
5. build and install deliverables in clean environments;
6. run composition-level startup, steady-state, fault, interruption, recovery, and
   no-orphan scenarios;
7. emit one machine-readable system verdict that retains every child verdict.

The existing adopter baseline/ratchet remains, extended with v4 rule revisions, scope,
capabilities, and mechanism version. An upgrade preview shall show newly applicable,
superseded, cleared, and still-baselined findings before it writes anything. Protected
evidence-destruction rules remain unwaivable.

## Delivery workstreams

### Phase 0 — Freeze and reproduce the evidence

**Purpose:** prevent v4 from being designed against anecdotes or mislabeled versions.

Deliverables:

- an adopter manifest containing repository commit, submodule commits, discipline
  manifest, environment digest, platform, and supported gate commands;
- a structured harvest of all discipline-scoped adopter learnings, including the
  declaration-loading defect, `ARCH-004` conflict, code-grammar conflict, Windows
  mutation gap, and `conda run` process-chain failure;
- reproducible baseline reports for the discipline repository, `sumtwo`, each of the four
  components, and the meta-repository;
- a classification for every finding: doctrine defect, mechanism defect, project defect,
  specification defect, tool fact, or unsupported-platform fact;
- baseline measurements for gate duration, findings, false positives, skipped steps,
  discrimination, documentation volume, and generated drift.

Exit criteria:

- every reported number is reproducible from a named commit;
- manual observations are labeled manual and cannot satisfy automated gates;
- the original adopter worktrees remain unmodified;
- the baseline runs on Windows and one independent Linux environment.

### Phase 1 — Author the v4 constitution and evidence schema

**Purpose:** make every later rule honest before adding more rules.

Deliverables:

- v4 rule schema and validator;
- `EVID-*` law and revised `FLOW-006`/`FLOW-007` semantics;
- stable-id retirement and supersession model;
- generated index views separating normative force, decidable status, discrimination,
  portability, residual, and field evidence;
- migration mapping for every v3 rule, including unchanged, clarified, superseded,
  consolidated, profile-activated, and retired states;
- proof-of-failure tests for every schema validator.

Exit criteria:

- no rule is described merely as `mechanized`;
- every binding rule has a verification strategy;
- every mechanical mechanism has a must-reject case;
- every proxy states its residual and cannot be presented as deciding the parent semantic
  claim;
- generated views round-trip without loss and fail on drift.

Suggested release: **v4.0.0-alpha.1**.

### Phase 2 — Replace the package-layer model with component architecture

**Purpose:** support one package, many components in one repository, git submodules, and
multi-repository compositions with the same doctrine.

Deliverables:

- decision-hiding component specification and change-scenario record;
- role-based dependency partial order and revised effect semantics;
- component/composition/contract-library/specimen scopes;
- four-graph model and machine-readable topology manifest;
- neutral contract catalog prototype and generated/digested component projections;
- composition-root gate that can aggregate child reports without leaking counterpart
  knowledge into components;
- v3 import-contract migration generator and diagnostics.

Exit criteria:

- the console-sink composition-root import is conformant without a checker workaround;
- a seeded peer-name leak fails in a component;
- a seeded catalog/restatement divergence fails locally and at the root;
- an unbound role, incompatible contract version, ownership cycle, and ownerless recovery
  path each fail by distinct diagnostic id;
- the same model works for ordinary package layout and all four SIGSIM components.

Suggested release: **v4.0.0-alpha.2**.

### Phase 3 — Add capability-driven operational law

**Purpose:** cover the failure modes that strict local package architecture cannot see.

Deliverables:

- checked capability manifest with inference and under-declaration failure;
- `OPS-*` and `SEC-*` modules;
- lifecycle, resource ownership, safe/degraded state, recovery, budget, build-identity,
  and trust-boundary models;
- capability-specific test-obligation generator;
- structured review artifact for semantic hazards and adversarial acceptance;
- platform support matrix that distinguishes tooling from runtime topology.

Exit criteria:

- seeded unbounded retry/input/queue/cleanup paths are reported where their capability
  requires a bound;
- subprocess tests prove first interrupt, graceful drain, timeout escalation, second
  interrupt, and zero orphans on Windows and Linux;
- network tests cover malformed frames, timeout, backpressure, disconnect, and duplicate
  or reordered events as declared by the contract;
- non-exception terminal outcomes are correlated and observable;
- a missing or stale adversarial review artifact fails without claiming that its mere
  presence proves semantic correctness.

Suggested release: **v4.0.0-beta.1**.

### Phase 4 — Rebuild gates and packaging around the v4 model

**Purpose:** remove adopter-owned enforcement forks and preserve the one-package,
two-agent delivery contract.

Deliverables:

- one generated project gate and one composition gate;
- configuration-load probes for every check;
- direct, proxy, external-tool, behavioral, and review mechanism adapters;
- v4 discrimination matrix with full coverage of every claimed decidable proposition;
- installed wheel/sdist smoke tests and public-entry-point checks;
- v3-to-v4 dry-run migration tool and scope-aware conformance ratchet;
- one authored `python-discipline` skill mirrored byte-for-byte to Claude Code and Codex;
- install, collision, upgrade, check, and conservative removal tests for both hosts.

Exit criteria:

- no adopter-owned wrapper is needed to obtain the intended declaration or rule set;
- missing configuration cannot produce a narrower green scan;
- no binding required step is `unbuilt`, `unsupported`, or silently skipped on a release
  platform;
- all claimed decidable propositions have discrimination coverage;
- fresh build, install, invocation, update, and removal are reproducible and leave
  project-owned host files untouched;
- Claude and Codex read identical skill bytes backed by the same vendored corpus.

Suggested release: **v4.0.0-beta.2**.

### Phase 5 — Migrate and adversarially audit the adopters

#### `python-doctrine-test`

- Upgrade from its repository-recorded v3.0.0 directly to v4 using the migration tool.
- Declare specimen scope and preserve the deliberately maximal architecture and
  documentation posture.
- Add a built-wheel/install/public-entry-point test without `PYTHONPATH` substitution.
- Decide and specify numeral length, scale, retry, and work budgets, or explicitly prove
  why a chosen unbounded behavior is safe for the interactive contract.
- Generate a requirement → decision → code → test → diagnostic trace view and prove its
  drift gate.
- Record doctrine overhead separately from product complexity so the future book can
  explain the cost honestly.

The migration succeeds only if v4 can describe why this specimen is maximal without
making maximal ceremony universal.

#### `multi-components`

- Add a composition-scope manifest and canonical root gate to the meta-repository.
- Convert `INTERFACES.md` into, or derive it from, the selected single-source contract
  catalog; generate or verify component-local projections.
- Migrate all four components to the role/partial-order model and capability declarations.
- Replace custom discipline-check wrappers with the canonical gate.
- Put `toybox` under typing, lint, import/topology, diagnostics, fault, and lifecycle
  gates. It may remain explicitly a stand-in; v4 certification shall not pretend it is
  the unimplemented `sigsimrun` product.
- Turn the recorded success, startup-failure, interrupt, force, and no-orphan scenarios
  into repeatable composition tests.
- Generate the top-level status section from component pins and gate reports so the README
  cannot say “implementation not started” after implementation lands.
- Verify clean component replacement with a contract-compatible substitute and no peer
  repository changes.

The migration succeeds only when local component gates and the system gate are both
necessary: seeding a defect visible only at composition altitude must leave every local
component green and make the root red.

#### Independent adopter

Repeat the v3.2 scratch adoption against the previously used 124-module codebase or a
comparably independent consequential repository. This guards against fitting v4 only to
the two doctrine-designed exemplars.

Exit criteria for the phase:

- all migrations are performed by preview, explicit apply, and reviewable commits;
- baseline debt survives upgrade and still catches a new instance of a baselined rule;
- all seeded local, cross-component, operational, and mechanism-self-test defects are
  caught at the intended altitude;
- an independent adversarial audit has no unresolved blocker or major finding;
- every accepted fix includes a test for the defect class, not only the observed fixture.

Suggested release: **v4.0.0-rc.1**.

### Phase 6 — Release certification

v4.0.0 may ship only when all of the following are true:

- The discipline repository's complete gate passes in the `claude` environment on
  Windows and in a clean independent Linux environment.
- Two clean builds are byte-identical and their manifest, archive membership, and digests
  agree.
- There are zero unbuilt binding verification strategies.
- Every claimed mechanical proposition has a must-reject discrimination case; the v3
  V098 gap is zero under the narrower, honest definition.
- No known mechanism ignores project configuration, checks only file existence for a
  semantic claim, or reports an unsupported/not-run step as green.
- `sumtwo`, all four SIGSIM components, and the SIGSIM composition root pass their v4
  gates at pinned commits.
- The SIGSIM root catches catalog drift, bad binding, lifecycle failure, and orphans that
  component-local gates cannot see.
- Built and installed artifacts, not source-tree imports alone, pass public behavior and
  diagnostic tests.
- The v3-to-v4 migrator is dry-run pure, idempotent, conservative around project-owned
  files, and covered by lossless round-trip tests.
- Claude Code and Codex installation, upgrade, collision, check, and removal scenarios
  pass from the same archive.
- Release notes enumerate every superseded rule, changed default, new capability, and
  required adopter action.
- An adversarial release audit reports no unresolved blocker or major; accepted minor
  residue is entered in the open ledger with owner and closure evidence.

Suggested release: **v4.0.0**.

## Quantitative release scorecard

Numbers are gates only where the quantity is meaningful. They are not proxies for overall
design quality.

| Measure | Known v3 baseline | v4 release requirement |
|---|---:|---:|
| Binding rules marked `unbuilt` | 14 | 0 |
| Decided binding rules without a witnessed rejection | 93 | 0, after claims are narrowed to exact decidable propositions |
| Adopter-owned aggregate-check workarounds | 3 component repositories | 0 |
| Composition-level gate in SIGSIM meta-repository | absent | present and required |
| Manually duplicated contract truth | catalog plus component restatements | one source plus verified projections |
| Release platforms with full gate evidence | one demonstrated development machine | Windows plus independent Linux |
| Native agent packages | one source mirrored to Claude and Codex in v3.3 | preserve byte identity and lifecycle tests |

False-positive and gate-duration budgets shall be set from Phase 0 measurements, not
invented here. Any accepted false positive must have a reproducer, classification,
owner, and ratcheted count. A known silent false negative is a release blocker.

## Risks and controls

| Risk | Control |
|---|---|
| Capability manifests become new boilerplate | Infer facts, generate the initial manifest, and require humans only for intent and limits the code cannot reveal. |
| Profiles become loopholes | Keep one consequential-system kernel; capabilities only add obligations, and under-declaration fails. |
| A contract generator centralizes component knowledge | Keep contract text role-neutral; topology stays only in the composition manifest; component projections carry no peer mapping. |
| v4 overfits SIGSIM | Require the independent adopter and retain `sumtwo` as a different-shaped specimen. |
| Documentation reform is mistaken for weaker documentation | Measure actionable contract/invariant/failure coverage and drift; stop counting prose on private obvious names as semantic evidence. |
| Strict typing produces tool-specific contortions | Preserve strictness, pin checker facts, discriminate both checkers, and require resource/complexity review of workarounds. A green type result cannot override an operational defect. |
| Cross-platform gates become permanently red | Make support an explicit release decision, provide equivalent executable mechanisms where tools differ, and never relabel unsupported as pass. |
| Generated views become another source of truth | Require canonical model identity, provenance, byte stability, lossless round-trip or independent diff, and edit detection. |
| The migration is too large for existing adopters | Provide preview, supersession map, scope-aware baseline ratchet, and staged commits; never reset project-owned debt during upgrade. |

## Decisions required before alpha.2

These are design questions the prototypes must answer with evidence:

1. Which neutral contract model gives the best lossless round-trip and diff quality across
   local call, JSON/NDJSON, CLI, and persisted formats?
2. How are structured semantic-review verdicts bound to a diff and reviewer role without
   hard-coding a particular agent product or model name?
3. Which facts belong in one project manifest versus generated per-component reports?
4. What is the executable Windows equivalent for every POSIX-only verifier, especially
   mutation and process-tree teardown?
5. Which v3 documentation requirements remain universally valuable after filler and
   false-positive data are measured?
6. Which exact v3 ids can be clarified and which must be superseded to keep historical
   citations truthful?

Each decision shall be recorded with alternatives, objections, prototype evidence, and
the failure mode it controls before the first beta.

## Definition of success

v4 succeeds if it can make all of these statements true at once:

- `sumtwo` remains intentionally, transparently over-engineered and becomes a better
  conformance specimen.
- Each SIGSIM component remains ignorant of its counterparts and independently verifiable.
- The SIGSIM composition root can prove properties no component can prove alone.
- Strict typing and mechanical verification are stronger, because their claims are more
  precise rather than broader.
- Operational failure modes—bounds, shutdown, recovery, topology, and safe state—are part
  of architecture rather than optional product prose.
- A green gate means every required mechanism actually ran against the intended subject,
  with its configuration loaded, and has been observed rejecting the defect it claims to
  detect.
- Claude Code and Codex install and use the same discipline from the same package, even
  when both work in the same repository.

That is the threshold for v4.0.0: not a larger rule count, but a doctrine whose scope,
architecture, and evidence model match the consequential systems it is meant to govern.
