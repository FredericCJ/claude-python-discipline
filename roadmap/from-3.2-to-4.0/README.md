# Python Engineering Discipline v4 roadmap

## From v3.2 adoption evidence to v4.0.0

| Field | Value |
|---|---|
| Status | Released on 2026-08-23 |
| Target | v4.0.0 |
| Doctrine evidence baseline | v3.2.0 |
| Packaging baseline | v3.3.0 |
| Governed unit | Exactly one repository |
| Supported product shapes | One complete application, or one component of a larger application |
| Product class | Consequential, potentially long-lived Python software |
| Primary validation adopters | `python-doctrine-test` and the four standalone SIGSIM component repositories |

## Release outcome

All six phases are complete. The discipline source passed its complete gate on native
Windows and from a clean independent Linux checkout. Two independently staged release
archives were byte-identical. The complete-application specimen and all four component
repositories passed every required project-gate step on both platforms, including real
Cosmic Ray mutation, wheel and source-distribution construction, clean installation, and
public entry-point probes.

The exact adopter commits, environments, report digests, durations, test totals, mutation
totals, and negative scope attestation are frozen in
`evidence/adopter-certification.json`. That certificate records 10 green repository/platform
verdicts, 2,731 passing test executions, and 5,052 killed mutant executions. It makes no
claim about the excluded SIGSIM parent or about multi-repository composition.

## Scope boundary

The discipline governs exactly one repository containing either:

1. a complete, deployable application; or
2. one independently developed component that participates in a larger application.

For the second shape, the component's external contracts are in scope. The application
that combines it with other components is not. The discipline therefore governs what the
component promises, consumes, emits, owns, diagnoses, and cleans up; it does not govern
which counterpart is connected to it or whether the larger application is correctly
assembled.

The following distinction is binding on this roadmap:

| In scope for a component repository | Outside the discipline's scope |
|---|---|
| Its domain, application logic, ports, adapters, and repository-local shell | A parent or meta-repository |
| Its published inputs, outputs, errors, ordering, idempotency, and versioning | Cross-repository wiring and deployment topology |
| Its reaction to timeout, disconnect, malformed input, cancellation, and termination | Global startup order or whole-application liveness |
| Resources and subprocesses that it owns, plus explicit ownership transfers | Processes and resources owned by other components |
| Its standalone tests, deliverable, diagnostics, and recovery behavior | End-to-end tests spanning several component repositories |
| A counterpart-neutral copy of the contract it implements | Synchronizing a master catalog across repositories |
| Proof that its own test doubles conform to its own port contracts | Proof that an independently developed counterpart is compatible |

The SIGSIM meta-repository is consequently **not a v4 adopter or certification target**.
Its specifications and history may explain where component requirements came from and
which failures appeared during integration, but v4 shall neither modify it nor require it
to run a discipline gate. Only `sine-generator`, `signal-invocator`, `sim-scheduler`, and
`console-sink` are adopter subjects, each in isolation.

This boundary does not make operational behavior optional. If a component opens sockets,
starts threads, launches child processes, persists state, or handles termination, the
effect and its ownership or ownership-transfer contract remain in scope. A resource may
leave the component's lifecycle only through an explicit handoff. What stops at the
repository boundary is system integration responsibility, not engineering rigor.

## Executive decision

Ship the next semantic doctrine as **v4.0.0**, not as a v3 minor release.

v3.3.0 has already completed the host-delivery change: one authored skill is packaged
once and exposed through byte-identical native discovery surfaces for Claude Code and
Codex. v4 shall preserve that result. Only correctness fixes that retain v3 semantics
belong in v3.3.x.

The major release is justified because v4 must change several rule meanings while keeping
the intended strictness:

1. v3 treats an exact four-directory stack as architecture even though ports sit outside
   that stack in real adopters;
2. v3 sometimes treats a syntactic proxy as proof of a broader semantic rule;
3. v3 prescribes physical forms—one module per dependency, exactly three adapter classes,
   every test layer populated, prose on every element—where the desired property is
   ownership, conformance, behavioral evidence, or durable knowledge;
4. v3 incompletely specifies component-owned lifecycle, resource, recovery, and budget
   obligations.

The intended v4 thesis is:

> A consequential Python repository shall make its decisions, effects, failures,
> resource ownership, recovery, and public contracts mechanically inspectable to the
> greatest extent possible; every mechanism shall state exactly which observable
> proposition it decides and what remains outside that decision.

## Non-negotiable inheritance from v3

v4 shall retain these principles without dilution:

- Small scripts and disposable programs remain out of scope.
- If a proposition can be mechanically verified, it shall be mechanically verified.
- Strict static typing remains mandatory. The domain admits no implicit `Any`; boundary
  parsing, exhaustive result handling, narrow escape hatches, and two independent strict
  checker verdicts remain the default assurance posture.
- The functional core remains isolated from foreign effects and transport/framework
  representations.
- Dependencies point toward policy; external technologies remain behind explicit
  boundaries.
- Expected outcomes and exceptional failures use explicit, typed channels.
- Escaping failures remain structured, stable, attributable, and cause-preserving.
- Tests state their oracle and cover contracts, properties, faults, containment, and
  delivered behavior.
- Structural decisions, rejected alternatives, deviations, and session learnings remain
  durable repository evidence.
- A gate that cannot fail, ignores project configuration, silently skips a platform, or
  checks a different artifact from the one delivered is defective.
- Claude Code and Codex receive the same discipline from one package and one authored
  source.

Two additional axioms make the mechanical-verification principle more exact:

1. **A mechanism shall claim no more than the observable proposition it decides.**
2. **Mechanical enforceability is not evidence that a rule is beneficial.** Benefit is
   justified separately by failure-mode analysis, source warrant, and adopter evidence.

These do not weaken the authoring axiom. They prevent an easy-to-count proxy from being
mistaken for a semantic guarantee.

## Explicit non-goals

v4 will not:

- govern a multi-component application's parent repository, global topology, or
  cross-component integration;
- make a component aware of counterpart names, repositories, deployment endpoints, or
  system wiring;
- guarantee compatibility between separately developed components;
- optimize the doctrine for toy programs or make `sumtwo` representative of normal
  project economics;
- optimize for Python idiomacy, brevity, or community convention where those conflict
  with transposable engineering principles;
- make typing optional or introduce a weakly typed profile;
- turn capability declarations into an à-la-carte rule waiver system;
- claim that passing more checks proves better architecture;
- copy the older embedded doctrines wholesale. They are design and failure evidence, not
  a normative parent of the Python discipline.

## Evidence baseline

The roadmap uses three evidence labels:

- **Observed** means present in a checked-out adopter, its tests, learning ledger, or git
  history.
- **Inferred** means a conclusion drawn from those observations and the supplied
  software-engineering corpus.
- **Proposed** means a v4 decision to implement; it is not current doctrine.

### Version truth

The checked-out `python-doctrine-test` history vendors v3.0.0, although it was presented
as a v3.2 adopter. Its evidence remains valuable, but it shall be classified as the
deliberately maximal single-application conformance specimen, not as proof of a
v3.2-specific mechanism.

The four SIGSIM component repositories identify their vendored discipline as v3.2.0. The
current discipline repository is v3.3.0 because combined Claude/Codex packaging landed
after those adopter runs.

Every v4 adopter result shall record repository commit, discipline release and manifest
digest, environment digest, OS, and interpreter. Parent-repository pins may be recorded
as provenance, but they do not become a gate input. A component must be verifiable from
its own checkout.

### What `python-doctrine-test` establishes

`python-doctrine-test` is a complete application in one repository. Its trivial problem
was deliberately projected through the entire doctrine for pedagogical use.

**Observed strengths**

- A small state space can carry an exact behavioral specification through domain,
  application, port, adapter, and shell boundaries.
- Typed parsing and scaled-integer arithmetic make invalid input and exact decimal
  behavior explicit.
- The same console contract is exercised against real, fake, and faulty implementations.
- Unit, application, contract, property, fault, and process tests remain visibly
  distinct, and diagnostics are asserted as data.
- The git history explains why each boundary, representation, and gate exists.

**Observed pressure points**

- Its decision record explicitly overrules the objection that a port around three console
  calls is ceremony because maximal conformance is the experiment's purpose. This cannot
  justify universal production ceremony.
- The history records 79 tests for a 19-file source package. That is appropriate for the
  planned book but makes the project a poor cost-benefit benchmark.
- A checker/typeshed result replaces `10 ** scale` with repeated multiplication. The
  workaround is type-clean but makes work proportional to the input exponent.
- The accepted numeral grammar has no digit or scale budget, retries are intentionally
  unbounded, and the “exact for every accepted input” claim is not paired with an
  adversarial resource bound. Strict typing cannot prove bounded work or availability.
- The process test invokes `python -m sumtwo` using a source-path injection. It does not
  prove that the built and installed console entry point works.
- Most recorded learnings concern tool invocation, encodings, Doxygen discovery, and type
  checker behavior. These are portability facts, not evidence that every architectural
  prescription is beneficial.

**v4 use of this adopter**

Keep the over-engineering. Model the repository as `unit = "application"` with an explicit
pedagogical full-projection declaration. Use it to test traceability, migration,
diagnostics, generated views, and installed-artifact verification. Do not create a
small-program profile or simplify the specimen to make v4 look lean.

### What the four SIGSIM components establish

Across the inspected component checkouts there are 161 Python source files and 107 Python
test files, approximately 13,557 source lines and 12,075 test lines, 25 port modules, and
77 adapter modules. The four repositories independently exercise networking,
subprocesses, concurrency, simulation-time policy, rendering, shutdown, backpressure,
error taxonomies, and contract-driven testing.

The numbers are aggregate evidence only. v4 treats them as four independent governed
units, never as one governed system.

**Observed strengths**

- “Components know contracts, never counterparts” produced repositories whose source and
  tests do not require peer component implementations.
- Each repository has a pure domain, typed ports, technology adapters, structured errors,
  fault injection, and contract tests.
- Component-level adversarial verification found and repaired boundary overflow,
  non-strict JSON diagnostics, regressing protocol windows, ordering races, sticky
  abnormal-state errors, rendering-budget mismatches, taxonomy drift, and test-oracle
  weaknesses.
- The components state behavior for malformed input, timeout, disconnect, termination,
  drain, blocked writes, and their own exit status.
- The refinement/verification workflow produced detailed standalone specifications
  without leaking counterpart identity into component sessions.

**Observed v3 gaps inside the component repositories**

- Three repositories added project-owned check runners because the vendored aggregate
  checker ignored `[tool.agent-discipline]`. It could emit false layer findings and
  silently disable documentation checks while reporting a clean aggregate run.
- `console-sink` exposed a direct conflict between `ARCH-004` and `ARCH-011`: a transitive
  foreign-module ban on the repository-local shell makes the shell's required wiring of
  real adapters impossible.
- The exception-code checker rejected hyphenated codes already published by a component
  specification. The repository had to route around the frozen checker.
- Mutation was configured but unavailable on the supported Windows development machine.
  A configured, permanently skipped binding gate is not verification.
- Strict type checking exposed several checker/stub integration constraints, while some
  workarounds increased runtime or code complexity. The doctrine records the former but
  does not require an explicit review of the latter.
- The physical real/fake/faulty triad multiplied adapter surface even where a reusable
  scheduled-fault decorator could express the same evidence more directly.
- Universal documentation gates surfaced large volumes of missing-comment findings, but
  presence mechanisms could not distinguish a useful contract from prose that restated a
  name or type.

**Explicitly excluded observations**

Contract synchronization across the SIGSIM repositories, global process startup and
shutdown, system wiring, whole-system status documentation, and parent-repository tests
are not doctrine gaps under the corrected scope. They belong to the system integrator.
They shall not generate v4 rules, milestones, or release gates.

**v4 conclusion from these adopters**

v3 is a strong local component discipline whose physical architecture and enforcement
claims need refinement. v4 must make each component more truthful, portable, and
operationally complete while preserving standalone verification and counterpart
ignorance.

### What the predecessor doctrines contribute

The supplied embedded, agent-operated-codebase, and real-time-audio doctrines contain
repository-local concepts that v3 lost while correcting their implementation failures:

- information hiding and change scenarios as the reason for an internal boundary;
- separation of source dependencies from runtime interactions at the component's own
  ports;
- safe/degraded state, recovery ownership, escalation, and bounded cleanup for resources
  the repository owns;
- explicit time, memory, queue, input-size, latency, and shutdown budgets;
- build identity, security assumptions, and operational observability;
- lossless generated projections, independent diffing, byte-exact gate-refactor tests,
  and adversarial acceptance;
- repair of a defect class rather than only the observed instance.

Their negative evidence matters equally: broad prose and green gates did not prevent
semantic residue. v4 shall recover a concept only after assigning it to the governed
repository, naming an observable claim, supplying a verifier, and stating the residual.

### What the SWE resource graph contributes

The typed SWE corpus supplies warrants for information hiding, dependency restriction,
hexagonal boundaries, functional-core/imperative-shell separation, contracts, dependency
inversion, static typing, and systematic testing. It does not establish that this exact
combination of rules is effective, nor does source verification equal empirical
validation.

v4 shall use the graph to answer “why is this rule plausible?” and adopter evidence to
answer “what happened when one repository used it?” Those are distinct relations in the
rule model.

## The v4 doctrine model

### 1. Define one governed repository

Every installation shall declare exactly one unit kind:

- **application** — the repository owns the complete deliverable and its external entry
  points;
- **component** — the repository owns one independently testable deliverable and its
  counterpart-neutral boundary contracts.

Both receive the same kernel. The distinction affects only external obligations:

- an application verifies its installed user/API entry points and all runtime resources
  it creates;
- a component verifies its packaged artifact and every published/consumed port from its
  own side, without needing a counterpart repository.

A repository shall not declare several governed components, traverse sibling checkouts,
or aggregate another repository's verdict. Internally it may contain many cohesive
modules and subpackages; they remain implementation structure inside one governed unit.

### 2. Separate normative, decidable, and empirical claims

Every rule shall expose three layers instead of flattening them into one `mechanized`
label:

| Layer | Question | Example |
|---|---|---|
| Normative | What engineering obligation holds? | One boundary owns a foreign dependency. |
| Decidable | What exact proposition can a mechanism observe? | Only modules under the declared adapter package import that dependency directly. |
| Empirical | What happened in a named adopter? | A transitive shell ban rejected valid repository-local wiring. |

The v4 rule schema shall carry at least:

- stable rule id and normative force;
- applicable unit kind and capability activation;
- failure mode the rule is intended to prevent;
- source warrants, with relation type and confidence;
- exact observable proposition for every mechanism;
- mechanism kind: static, tool, behavioral, generated-drift, or structured review;
- known residual: what can still be wrong after the mechanism passes;
- positive reference and must-reject discrimination case;
- supported platforms and explicit not-applicable conditions;
- adopter observations, distinct from sources and rationale;
- supersession and migration metadata.

A structured review may decide a semantic obligation that syntax cannot. The gate can
mechanically verify the review artifact's repository commit, scope, freshness, reviewer
independence, verdict, and closure of findings; it shall not claim that file presence
proves the review was insightful.

`FLOW-006` and `FLOW-007` shall be revised around this model. A binding semantic rule
needs a declared verification strategy, but a presence check may not masquerade as a
semantic decision.

Rule ids shall not be silently repurposed. A clarification that preserves an obligation
may retain its id. A change of subject or meaning shall introduce a new id, retain the old
id as a resolvable retired record, and provide `superseded_by` plus migration guidance.

### 3. Make information hiding primary inside the unit

The governed repository shall state:

- the volatile decisions it owns;
- the change scenarios its internal boundaries are intended to absorb;
- the public contracts it publishes or consumes;
- the state and resources it owns;
- the failures it contains, translates, or reports;
- its externally observable lifecycle.

The familiar hexagonal roles remain, but v4 shall describe their actual relationship
instead of claiming that ports are an impossible fifth layer:

| Role | Responsibility |
|---|---|
| Domain | Pure policy, values, invariants, and typed outcomes |
| Application | Orchestration, sequencing, recovery decisions, and calls through injected ports |
| Port/contract | Typed, counterpart-neutral boundary vocabulary and behavioral terms |
| Adapter | Translation and foreign technology effects |
| Shell | Repository-local wiring, process lifecycle, final rendering, and escape handling |

Domain, application, adapters, and shell form the executable dependency order. Ports are
contract declarations used by the application and implemented by adapters; they are not
an extra executable layer. Projects may map directory names to these roles, but an
undeclared path may never disappear silently from layer-scoped checks.

### 4. Resolve effect semantics

v4 shall replace the ambiguity between a pure application layer and adopter code in which
application services call ports:

- Domain code performs no effects and imports no effect-capable technology.
- Application code may invoke injected ports. It owns policy-level sequencing and
  recovery but cannot name concrete adapters or foreign APIs.
- Adapters perform foreign effects and translate foreign representations and failures.
- The repository-local shell selects adapters, owns process/runtime setup, and handles
  the final escaping failure.
- A destructive or multi-effect capability activates plan/apply, journaling,
  interruption, and recovery obligations. Simple idempotent port calls do not acquire a
  fake command-plan layer merely to satisfy a folder model.

This preserves functional-core/imperative-shell reasoning while describing the code in
both the complete application and component adopters.

### 5. Model only repository-owned runtime behavior

v4 shall distinguish, within the one repository:

1. **Source dependency view** — imports and build dependencies.
2. **Port interaction view** — operations the unit invokes or serves, including ordering,
   concurrency, idempotency, timeout, and failure semantics.
3. **Resource ownership view** — files, sockets, threads, subprocesses, queues, and state
   owned by the unit, including explicit transfer points for resources it creates but does
   not retain.
4. **Failure and recovery view** — local detection boundary, containment boundary,
   recovery owner, escalation, and terminal safe/degraded state.

These are local views, not a system topology. An external actor is identified only by its
contract role. The gate shall reject counterpart repository names, deployment wiring, or
assumptions about a peer's implementation inside a component repository.

For example, `signal-invocator` must specify and test its launch operation and the point at
which subprocess lifecycle ownership leaves the component. Its contract explicitly says
that it does not monitor or terminate successfully launched units; v4 must preserve that
handoff rather than incorrectly require local reaping. It need not prove that the entire
SIGSIM process fleet terminates.

### 6. Activate local obligations by capability

All projects remain under the consequential-software kernel. A checked manifest declares
facts that activate additional obligations; it does not waive core rules.

An illustrative, non-final shape is:

```toml
[discipline]
unit = "component"                 # application | component
assurance = "consequential"
pedagogical_full_projection = false

[capabilities]
public_api = true
persistent_state = false
generated_artifacts = false
network_io = true
launches_subprocesses = true
owns_subprocess_lifecycle = false
concurrency = true
destructive_effects = false
bounded_latency = false
sensitive_data = false
```

The gate shall infer capabilities from this repository's imports, build metadata, and
source patterns and fail on an undeclared observed capability. A declaration may activate
more rules than inference can discover, never fewer.

Examples:

- `network_io` activates framing, malformed-message, timeout, backpressure, disconnect,
  correlation, and local shutdown obligations.
- `launches_subprocesses` activates command identity, launch-failure translation, and an
  explicit lifecycle-ownership or transfer contract.
- `owns_subprocess_lifecycle` additionally activates signal routing, bounded reap, and
  tests that the unit leaves none of its own children behind.
- `persistent_state` activates schema compatibility, migration, single-writer, recovery,
  and corruption tests for state this repository owns.
- `generated_artifacts` activates source-of-truth, provenance, lossless round-trip,
  independent drift, and byte-stability checks inside this repository.
- `sensitive_data` activates data classification, redaction, least exposure, and security
  review instead of pretending a keyword regex proves that no secret can escape.
- `bounded_latency` activates explicit budgets and measurement on declared supported
  platforms.

`sumtwo` shall declare `unit = "application"` and
`pedagogical_full_projection = true`. That flag adds teaching evidence; it is not a
lightweight or small-program profile.

### 7. Make each repository's contract internally single-source

For a component, the local published contract is authoritative for its implementation and
tests. It must name roles and behaviors, never a concrete counterpart. v4 shall support a
machine-readable, versioned local contract model from which documentation, schemas, typed
carriers/codecs where appropriate, compatibility fixtures, and test parameters can be
generated or checked.

The guarantee stops at the repository boundary:

- local code, documentation, schemas, taxonomy, and tests shall not drift from the local
  contract source;
- a vendored external contract snapshot shall carry version and digest provenance;
- the component shall be testable against a local harness, fake, or protocol peer owned by
  its tests;
- the discipline shall not locate a master catalog elsewhere, update other repositories,
  bind a role to a counterpart, or certify cross-repository compatibility.

The concrete contract representation shall be chosen by prototypes based on local
round-trip fidelity, diff quality, typed-codec support, and transport independence—not by
a requirement to serve a multi-repository catalog.

### 8. Add repository-local operational completeness

The predecessor doctrines correctly treated operational behavior as architecture. v4
shall introduce capability-aware obligations for the governed unit's:

- safe and degraded states;
- recovery owner and escalation ladder;
- startup, steady-state, interruption, drain, shutdown, and forced cleanup;
- time, memory, queue, retry, input-size, and cleanup budgets;
- resource acquisition and release ownership;
- non-exception outcomes and state transitions as observable events;
- runtime and build identity in diagnostics;
- security assumptions and the boundary at which they stop being valid;
- portability across supported signal, encoding, filesystem, and process models.

A type-correct component with unbounded work, an ownerless local resource, or an unsafe
shutdown path is not conformant. A global failure with no local component obligation is
not judged by this discipline.

## High-impact rule migrations

The v4 authoring phase shall audit every rule, but these migrations are already justified
by adopter evidence:

| v3 surface | v4 direction |
|---|---|
| `ARCH-001` exact four layers, no fifth | Clarify four executable roles and ports as contract declarations. Enforce a declared dependency order inside one repository without silently skipping unmapped paths. |
| `ARCH-004` one foreign dependency per module | Supersede with one owning adapter boundary/package. Check direct ownership; allow the shell's intentional transitive reach through the selected adapter. |
| `ARCH-007`, `TYPE-009` structural `Protocol` | Require an explicit typed boundary contract. Structural versus nominal representation is a repository decision whose enforcement must match the chosen form. |
| `ARCH-008` real/fake/faulty triad | Require real conformance, a contract-verified controllable test implementation, and scheduled fault coverage. Permit one implementation to realize several test capabilities; do not require three files or classes. |
| `ARCH-009`, `TEST-005`, `TEST-006` | Consolidate overlapping claims into semantic conformance: every substitute used by tests runs the same observable contract suite, whose cases trace to contract terms and failure modes. |
| `ARCH-010` port justification | Base justification on a volatile decision, effect boundary, fault-containment boundary, or independently variable contract—not a generic “may replace” statement. |
| `ARCH-011` composition root | Rename its subject unambiguously as the **repository-local wiring root** so it cannot be read as a multi-repository composition obligation. |
| `EFCT-001` effects only in shell/adapters | Clarify that application orchestration invokes effects through ports while foreign I/O remains in adapters and process concerns remain in the repository-local shell. |
| `DEP-001` standard-library-only domain | Preserve as an activatable high-assurance constraint. The universal obligation is that domain dependencies are pure, explicitly allowed, pinned, and isolated from framework/transport ownership. |
| `TYPE-006` every closed set is an enum | Require an exhaustively checkable closed representation. Enum, literal union, and tagged data union are valid when their semantics fit. Strict exhaustiveness remains mandatory. |
| `DOC-001`, `DOC-002`, `DOC-007` universal element prose | Require documentation for public contracts, boundary terms, invariants, non-obvious policy, failure semantics, and operational assumptions. Do not reward filler that only restates a private name or type. The pedagogical flag may retain maximal coverage. |
| `DOC-014` engine declaration | Make declaration loading part of the canonical gate API and discrimination suite; a missing declaration may never narrow checks silently. |
| `DIAG-002` code regex | Define code grammar once in the local error-taxonomy model and generate validator, docs, and fixtures from it. |
| `DIAG-010`, `DIAG-016` exception-centric observability | Extend to typed refusals, dropped work, retries, transitions, recovery, and terminal reason for this unit. “Logged once” is subordinate to complete event semantics. |
| `API-015` delivered artifact advisory | Make build, clean installation, and public-entry-point tests binding for a published application or component package. |
| `TEST-002` every named test layer populated | Activate suites from local obligations and capabilities. An empty irrelevant directory is not quality; an untested active contract is a release blocker. |
| `TEST-013` mutation on the core | Retain mutation as preferred evidence, but require an executable supported-platform gate or an explicitly equivalent discrimination strategy. Permanent local skip is not green. |
| `FLOW-006`, `FLOW-007`, `TEST-015` | Apply to each exact decidable proposition, with a must-pass reference, must-reject mutation, configuration-load proof, and stated residual. |

New rule families should be introduced only where the subject cannot be expressed
truthfully by an existing family:

- `EVID-*` — claim typing, warrants, residuals, discrimination, and field evidence;
- `OPS-*` — local lifecycle, resources, budgets, safe state, recovery, and build identity;
- `SEC-*` — local trust boundary, data classification, redaction, and security evidence.

Do not introduce a system-composition or multi-repository rule family. Component boundary
rules belong in `ARCH-*`, `API-*`, `ERR-*`, and `TEST-*`.

Exact ids and statements are an alpha deliverable. They shall pass adversarial review
before becoming binding.

## Enforcement architecture

v4 enforcement shall have one programmatic **project gate** and one generated command
entry point per governed repository. Adopters shall not need local clones of the vendored
aggregate runner.

Every mechanism declaration shall name:

- the rule and exact proposition decided;
- repository paths and unit kind inspected;
- project declaration fields consumed;
- tool version and supported platforms;
- stable diagnostic id;
- reference case expected to pass;
- one or more mutations expected to fail by that diagnostic id;
- residual cases it does not decide.

The gate shall distinguish `pass`, `fail`, `not-applicable`, `unsupported`, and
`not-run`. Only `pass` and valid `not-applicable` can contribute to a green verdict.
`unsupported` and `not-run` remain visible failures for a required release platform.

For `unit = "component"`, the gate shall additionally prove that:

1. the repository builds and tests without a parent checkout or sibling component;
2. published ports and consumed contracts are present locally and counterpart-neutral;
3. real adapters and test substitutes satisfy the locally stated observable contract;
4. fault cases cover locally declared foreign failure modes;
5. source, tests, documentation, schemas, and error taxonomies do not name a peer
   repository or deployment wiring;
6. the built component artifact can be installed and its supported standalone probes or
   entry points execute.

It shall not discover siblings, read parent configuration, consume another component's
gate report, or produce a whole-application verdict.

The existing adopter baseline/ratchet remains, extended with v4 rule revisions, unit
kind, capabilities, and mechanism version. An upgrade preview shall show newly applicable,
superseded, cleared, and still-baselined findings before writing anything. Protected
evidence-destruction rules remain unwaivable.

## Delivery workstreams

### Phase 0 — Freeze and reproduce the in-scope evidence

**Purpose:** prevent v4 from being designed against anecdotes, mislabeled versions, or
out-of-scope integration concerns.

Deliverables:

- an adopter manifest for the discipline repository, `python-doctrine-test`, and each of
  the four component repositories, containing commit, discipline manifest, environment
  digest, platform, and standalone gate command;
- an explicit scope matrix marking the SIGSIM parent/meta-repository and every
  cross-repository integration claim out of scope;
- a structured harvest of discipline-scoped component learnings, including the
  declaration-loading defect, `ARCH-004` conflict, code-grammar conflict, and Windows
  mutation gap;
- a classification for every in-scope finding: doctrine defect, mechanism defect, project
  defect, specification defect, tool fact, or unsupported-platform fact;
- baseline measurements for gate duration, findings, false positives, skipped steps,
  discrimination, documentation volume, and generated drift.

Exit criteria:

- every reported number is reproducible from a named standalone repository commit;
- each component gate runs with the component checked out alone;
- no result depends on a sibling, parent checkout, or system-wide test;
- manual observations are labeled manual and cannot satisfy an automated gate;
- the original adopter worktrees remain unmodified;
- baseline gates run on Windows and one independent Linux environment.

### Phase 1 — Author the v4 constitution and evidence schema

**Purpose:** make every later rule honest before changing architecture or adding law.

Deliverables:

- a one-repository scope statement enforced across the kernel, frames, templates, skill,
  install guide, and examples;
- v4 rule schema and validator;
- `EVID-*` law and revised `FLOW-006`/`FLOW-007` semantics;
- stable-id retirement and supersession model;
- generated index views separating normative force, decidable status, discrimination,
  portability, residual, and field evidence;
- migration mapping for every v3 rule: unchanged, clarified, superseded, consolidated,
  capability-activated, or retired;
- proof-of-failure tests for every schema validator.

Exit criteria:

- no doctrine rule imposes an obligation on a parent/meta-repository or system
  integrator;
- no rule is described merely as `mechanized`;
- every binding rule has a verification strategy;
- every mechanical mechanism has a must-reject case;
- every proxy states its residual and cannot be presented as deciding its parent semantic
  claim;
- generated views round-trip without loss and fail on drift.

Suggested release: **v4.0.0-alpha.1**.

### Phase 2 — Correct the one-unit hexagonal architecture

**Purpose:** make the architecture internally coherent for a complete application and for
one standalone component.

Deliverables:

- `application` and `component` unit declarations;
- information-hiding and change-scenario record for internal boundaries;
- clarified domain/application/port/adapter/shell roles and dependency order;
- revised application-port effect semantics;
- counterpart-neutral external contract obligations for component repositories;
- repository-local dependency, port-interaction, resource-ownership, and recovery views;
- v3 import-contract migration generator and diagnostics.

Exit criteria:

- `console-sink`'s shell-to-real-adapter wiring is conformant without weakening foreign
  dependency ownership;
- a seeded peer repository name or deployment endpoint fails in a component repository;
- a seeded undeclared source directory cannot disappear from layer-scoped checks;
- a seeded adapter ownership breach and application-to-concrete-adapter import fail by
  distinct diagnostics;
- all four SIGSIM components pass independently with no parent checkout;
- `sumtwo` passes as a complete application under the same role model.

Suggested release: **v4.0.0-alpha.2**.

### Phase 3 — Add capability-driven local operational law

**Purpose:** cover component-owned failure modes that strict typing and import structure
cannot see.

Deliverables:

- checked capability manifest with inference and under-declaration failure;
- `OPS-*` and `SEC-*` modules constrained to repository-owned behavior;
- lifecycle, resource ownership, safe/degraded state, recovery, budget, build-identity,
  and trust-boundary models;
- capability-specific test-obligation generator;
- structured review artifact for semantic hazards and adversarial acceptance;
- platform support matrix distinguishing development tooling from component runtime.

Exit criteria:

- seeded unbounded retry/input/queue/cleanup paths are reported where a local capability
  requires a bound;
- a repository that launches subprocesses tests failure translation and explicit
  lifecycle handoff; one that retains lifecycle ownership additionally tests interruption,
  graceful stop, timeout escalation, and absence of its own orphan children on Windows
  and Linux;
- a repository that owns network I/O tests malformed frames, timeout, backpressure,
  disconnect, and declared ordering behavior using local protocol harnesses;
- non-exception terminal outcomes are correlated and observable;
- missing local resource ownership or recovery responsibility fails;
- a missing or stale adversarial review artifact fails without claiming that its mere
  presence proves semantic correctness.

Suggested release: **v4.0.0-beta.1**.

### Phase 4 — Rebuild the project gate and package

**Purpose:** remove adopter-owned enforcement forks and preserve the one-package,
two-agent delivery contract.

Deliverables:

- one generated project gate for either unit kind;
- configuration-load probes for every check;
- direct, proxy, external-tool, behavioral, and review mechanism adapters;
- v4 discrimination matrix covering every claimed decidable proposition;
- installed wheel/sdist smoke tests and public-entry-point/probe checks;
- v3-to-v4 dry-run migration tool and unit-aware conformance ratchet;
- one authored `python-discipline` skill mirrored byte-for-byte to Claude Code and Codex;
- install, collision, upgrade, check, and conservative removal tests for both hosts.

Exit criteria:

- no adopter-owned wrapper is needed to obtain the intended declaration or rule set;
- missing configuration cannot produce a narrower green scan;
- no binding required step is `unbuilt`, `unsupported`, or silently skipped on a release
  platform;
- every claimed decidable proposition has discrimination coverage;
- a component gate demonstrably refuses to read a configured parent or sibling path;
- fresh build, install, invocation/probe, update, and removal are reproducible and leave
  project-owned host files untouched;
- Claude and Codex read identical skill bytes backed by the same vendored corpus.

Suggested release: **v4.0.0-beta.2**.

### Phase 5 — Migrate and adversarially audit the adopters

#### Complete-application adopter: `python-doctrine-test`

- Upgrade from its repository-recorded v3.0.0 directly to v4 using the migration tool.
- Declare `unit = "application"` and preserve the deliberately maximal architecture and
  documentation posture through `pedagogical_full_projection = true`.
- Add a built-wheel/install/public-entry-point test without `PYTHONPATH` substitution.
- Decide and specify numeral length, scale, retry, and work budgets, or explicitly justify
  a deliberately unbounded interactive behavior.
- Generate a requirement → decision → code → test → diagnostic trace view and prove its
  local drift gate.
- Record doctrine overhead separately from product complexity so the future book can
  explain the cost honestly.

The migration succeeds only if v4 can describe why this application is intentionally
maximal without making maximal ceremony universal.

#### Component adopters: four independent migrations

Migrate the repositories separately. Do not change or gate the SIGSIM parent repository
as part of v4 validation.

- **`sine-generator`** — exercise typed numeric policy, network ports, concurrent readers,
  backpressure, grant ordering, bounded flush, and standalone artifact behavior.
- **`signal-invocator`** — exercise validation, all-or-nothing local policy, subprocess
  launch, explicit transfer of lifecycle ownership, status delivery, and fault schedules.
- **`sim-scheduler`** — exercise explicit state machines, clocks, network listeners,
  timeout/watchdog policy, local control handling, and termination output without naming
  the components that may consume it.
- **`console-sink`** — exercise several independent ports, ordering, drain behavior,
  rendering budgets, sticky abnormal outcomes, and valid repository-local shell wiring.

For every component:

- declare `unit = "component"` and local capabilities;
- replace project-owned discipline-check wrappers with the canonical gate;
- migrate ports and adapter evidence to the revised semantic conformance model;
- build and install the package in a clean environment;
- run all contract tests against local harnesses without a sibling repository;
- scan source, specifications, tests, and generated artifacts for counterpart identity or
  deployment wiring;
- perform an adversarial review from the component's own published contract and grant fix
  authority for confirmed local defects.

A component migration succeeds when it is independently diagnosable, testable, and
installable. It is neither required nor permitted to prove that SIGSIM as a whole works.

#### Independent adopter

Repeat the v3.2 scratch adoption against the previously used 124-module codebase or a
comparably independent consequential single-repository application/component. This guards
against fitting v4 only to doctrine-designed exemplars.

Exit criteria for the phase:

- all migrations use preview, explicit apply, and reviewable commits;
- baseline debt survives upgrade and still catches a new instance of a baselined rule;
- every adopter passes from its own checkout with no external repository path;
- local architecture, operational, and mechanism-self-test defects are caught at the
  intended boundary;
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
- `sumtwo` and all four SIGSIM components pass v4 independently at named commits.
- No adopter gate reads the SIGSIM parent, a sibling component, or any other repository
  to decide conformance.
- Component fixtures and documentation name roles/contracts but not counterpart
  repositories or deployment wiring.
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
| In-scope adopters with standalone v4 gate | 0 of 5 | 5 of 5 |
| Component gates requiring parent/sibling checkout | Not measured | 0 |
| Published artifacts tested after clean installation | Incomplete | Every application/component adopter |
| Release platforms with full gate evidence | One demonstrated development machine | Windows plus independent Linux |
| Native agent packages | One source mirrored to Claude and Codex in v3.3 | Preserve byte identity and lifecycle tests |

There is deliberately no score for system integration, cross-repository contract drift,
global topology, or end-to-end multi-component behavior.

False-positive and gate-duration budgets shall be set from Phase 0 measurements, not
invented here. Any accepted false positive must have a reproducer, classification,
owner, and ratcheted count. A known silent false negative is a release blocker.

## Risks and controls

| Risk | Control |
|---|---|
| Scope grows back toward the parent application | Maintain an explicit scope matrix, test every component from an isolated checkout, and reject any mechanism that reads parent/sibling paths. |
| The discipline is blamed for incompatible counterpart contracts | State the local contract and its provenance precisely; document that cross-repository compatibility is an integrator responsibility. |
| Capability manifests become new boilerplate | Infer facts, generate the initial manifest, and require humans only for intent and limits the code cannot reveal. |
| Capabilities become loopholes | Keep one consequential-software kernel; capabilities only add obligations, and under-declaration fails. |
| v4 overfits the four SIGSIM components | Require the independent adopter and retain `sumtwo` as a different-shaped complete application. |
| Documentation reform is mistaken for weaker documentation | Measure actionable contract, invariant, failure, and operational coverage; stop counting prose on private obvious names as semantic evidence. |
| Strict typing produces tool-specific contortions | Preserve strictness, pin checker facts, discriminate both checkers, and review runtime/resource consequences of workarounds. A green type result cannot override an operational defect. |
| Cross-platform gates become permanently red | Make support an explicit release decision, provide executable alternatives where tools differ, and never relabel unsupported as pass. |
| Generated local views become another source of truth | Require canonical local model identity, provenance, byte stability, lossless round-trip or independent diff, and edit detection. |
| Migration is too large for existing adopters | Provide preview, supersession map, unit-aware baseline ratchet, and staged commits; never reset project-owned debt during upgrade. |

## Questions resolved during implementation

The alpha questions were resolved with repository-local mechanisms and adopter evidence:

1. Applications own the complete installed entry-point behavior. Components own one
   deliverable and their counterpart-neutral side of every local contract; they never gain
   parent, sibling, topology, or composition obligations.
2. Canonical JSON architecture, contract-conformance, operational, and security models
   provide stable joins across Python calls, streams, CLI surfaces, and persisted formats.
   Structural checks decide their exact joins; content-bound review decides semantic
   adequacy and states its residual.
3. A component records a contract role, origin, version, representation, terms, and local
   evidence. Counterpart identity is neither required nor admitted as conformance input.
4. Reviews bind an authored scope digest and file count to a reviewed commit while naming
   author and reviewer roles independently of agent products. The artifact explicitly
   concedes that fields cannot authenticate personal or organizational independence.
5. Cosmic Ray 8.7.0 now runs natively on Windows and Linux through one adapter that rejects
   zero work, incompetent outcomes, abnormal results, and survivors. Cross-platform adopter
   certification also repaired real signal, socket-teardown, selector, and typing defects.
6. Documentation remains binding for public behavior, contracts, invariants, failures,
   ownership, recovery, budgets, and non-obvious decisions. Presence and generated output
   are mechanically checked without being misrepresented as proof that prose is true.
7. The v4 rule registry preserves old IDs as resolvable superseded, consolidated, or
   retired records. The exact disposition and adopter action for every changed v3 ID is in
   the v4 release notes.

## Definition of success

v4 succeeds if all of these statements are true at once:

- `sumtwo` remains intentionally, transparently over-engineered and becomes a better
  complete-application conformance specimen.
- Each SIGSIM component remains ignorant of its counterparts and is independently
  installable, testable, diagnosable, and repairable.
- The SIGSIM parent repository is neither modified nor required to certify v4.
- The discipline makes no claim about cross-component wiring, compatibility, or global
  application behavior.
- Strict typing and mechanical verification are stronger because their claims are more
  precise, not because their scope is broader.
- Component-owned bounds, resources, shutdown, recovery, safe state, and explicit resource
  handoffs are part of architecture rather than optional prose.
- A green gate means every required mechanism ran against the intended repository, with
  its configuration loaded, and was observed rejecting the defect it claims to detect.
- Claude Code and Codex install and use the same discipline from the same package, even
  when both work in the same repository.

That is the threshold for v4.0.0: not a larger rule count and not a system-integration
framework, but a doctrine whose evidence and architecture precisely fit one consequential
Python application or one consequential Python component.
