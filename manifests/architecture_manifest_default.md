# Software Architecture Manifest — Default (Domain-Agnostic)

## Purpose

This manifest is grounding context, not a rulebook. It establishes shared
vocabulary, lays out the paradigm menu with accepted tradeoffs, and names
common patterns for cross-cutting concerns. It does not prescribe answers.

The architect reasons from first principles. The manifest exists to make
that reasoning legible, check priors against accumulated practice, and
surface tradeoffs that are easy to forget in the moment.

---

## 1. Vocabulary

- **Component.** A unit with a single stated responsibility, a defined
  interface, and an independent lifecycle in testing.
- **Interface / contract.** The observable surface of a component:
  inputs, outputs, invariants, error modes, ordering constraints.
- **Invariant.** A property that must always hold at a named boundary
  (entry, exit, between calls). Invariants are design artifacts;
  they are checked, asserted, or enforced by types.
- **Seam.** A point in existing code where behavior can be altered
  without editing it — typically an interface, a dispatch, a parameter.
  Seams are the primary lever for refactoring and testing legacy code.
- **Coupling.** The degree to which two components depend on each
  other's internals. Lower is usually better, but not always — some
  couplings are necessary, and making them implicit is worse than
  making them direct.
- **Cohesion.** The degree to which a component's contents serve one
  purpose. High cohesion tends to correlate with low coupling but is
  not the same property.
- **State ownership.** Which component has authority to mutate a piece
  of state. Unclear ownership is a recurring source of bugs that are
  hard to localize.
- **Pure function.** Same inputs → same outputs, no side effects.
  Trivially testable, trivially debuggable, trivially parallelizable.
- **Side effect.** Any interaction with state outside the function's
  return value: I/O, mutation of shared state, exceptions that skip
  the return path.
- **Observability.** The degree to which a running component's
  behavior can be inspected from outside — logs, traces, exposed
  metrics, typed return values that carry diagnostic context.

---

## 2. The Paradigm Menu

Each paradigm has conditions where it fits and conditions where it
degrades. The menu is not exhaustive and not exclusive — components
within one system can use different paradigms.

### Structured / procedural

- **Fit:** Linear transformations, command-line tools, scripts with a
  clear beginning and end. Code that reads top-to-bottom.
- **Degrades when:** The problem has non-trivial state that must
  persist across calls; when multiple entry points share logic.
- **Watch for:** Deep nesting; implicit shared state via module-level
  variables.

### Modular

- **Fit:** Any non-trivial system. The baseline discipline.
- **Degrades when:** Module boundaries are drawn along technology lines
  (controllers / services / models) rather than responsibility lines
  (features, subdomains, capabilities).
- **Watch for:** God-modules; circular imports; utility modules that
  accumulate unrelated helpers.

### Object-oriented

- **Fit:** Domains with natural entity identity; behavior bound to
  data; polymorphism over a closed set of variants; frameworks that
  demand it.
- **Degrades when:** Data is anemic and logic lives elsewhere;
  inheritance is used for code reuse rather than subtyping; every
  verb becomes a class.
- **Watch for:** Deep inheritance hierarchies; "manager" and "service"
  classes that mostly hold static-ish methods; implicit state via
  long-lived instance fields.

### Functional

- **Fit:** Transformation pipelines, data processing, concurrency
  without shared mutable state, business rules expressible as pure
  functions.
- **Degrades when:** The problem is fundamentally stateful or
  side-effect-heavy and forcing purity produces elaborate plumbing
  without commensurate benefit.
- **Watch for:** Cleverness in the name of purity; currying and
  point-free style that obscures intent.

### Contract-based / design-by-contract

- **Fit:** Components with non-trivial invariants; inter-module
  boundaries where violations must be caught immediately; safety- or
  security-relevant code.
- **Degrades when:** Contracts are aspirational rather than checked at
  runtime or enforced by types — they become comments.
- **Watch for:** Contracts that duplicate the type system; contracts
  that leak implementation details.

### Event-driven

- **Fit:** Asynchronous integration; loose coupling between producers
  and consumers; domains with genuine temporal semantics (user actions,
  external signals, long-running processes).
- **Degrades when:** Control flow matters but is hidden by dispatch;
  event ordering is important but not enforced; handlers silently drop
  events.
- **Watch for:** "Event storms" where one logical operation spawns
  many events; debugging by grep across handler files.

### Actor / message-passing

- **Fit:** Concurrent systems with independent units of state;
  isolation of failure domains; distributed systems where location
  transparency matters.
- **Degrades when:** The problem does not need isolation and message
  passing introduces latency and ceremony for no gain.
- **Watch for:** Request-response encoded as two one-way messages;
  back-pressure ignored; mailboxes that grow unbounded.

### Dataflow / pipeline

- **Fit:** Problems naturally expressed as stages over streaming data;
  signal processing, compiler-style transformations, analyzers.
- **Degrades when:** Stages have backward dependencies or need to
  share state; the graph becomes too large to reason about as a whole.
- **Watch for:** Stages that mutate shared state as a side channel;
  implicit ordering constraints not expressed in the graph.

### Type-driven / declarative

- **Fit:** Parsers, validators, schema-governed code; domains where
  "illegal states unrepresentable" is achievable and valuable.
- **Degrades when:** Types become load-bearing for logic they cannot
  actually encode; the type system's expressiveness limits dominate
  the design.
- **Watch for:** Phantom types and type-level programming that makes
  signatures unreadable; over-reliance on structural typing where
  nominal typing would prevent real bugs.

---

## 3. Cross-Cutting Concerns

### 3.1 Coupling and cohesion

Draw module boundaries by responsibility, not by technology. A "database"
module that every feature touches has low cohesion and couples everyone
to a shared implementation. A "billing" module that owns its own
persistence has high cohesion and localizes change.

Coupling is not uniformly bad. A type explicitly imported is better than
a type implicitly shared via duck typing, even though both create a
dependency. Direct, visible coupling is easier to reason about than
diffuse, implicit coupling.

### 3.2 State and ownership

For any piece of state, one component owns mutation; others observe.
The owner is named. Shared ownership is an anti-pattern that surfaces
as reproducibility problems and non-local bugs.

Prefer immutable data for anything that crosses a boundary; mutability
is an ownership statement.

Global state (module-level mutables, singletons, "environment" objects
populated at startup) defeats unit-testability because test isolation
becomes an infrastructure problem rather than a parameter-passing
problem.

### 3.3 Error handling

Four consistent styles; pick one per module boundary and hold it.

- **Exceptions.** Natural in Python; fine for truly exceptional
  conditions. Poor for control flow; poor across process / RPC
  boundaries.
- **Typed results** (`Result<T, E>`, `Either`, tagged unions,
  `Optional` with explicit handling). Forces callers to acknowledge
  failure modes at the type level; reads as normal control flow.
- **Error codes.** Common in C and in cross-language boundaries.
  Requires discipline: every call site checks, or a linter enforces it.
- **Panic / abort.** For invariant violations the program cannot
  recover from. Not for recoverable conditions.

Mixing styles within a module hides the contract. Converting at module
boundaries is fine and often necessary.

### 3.4 Concurrency

Choose a concurrency model before choosing primitives.

- **Shared-memory, locks.** Highest performance, lowest debuggability.
  Reserve for hot paths where other models measured slower.
- **Message-passing.** Each unit of state is owned by one task; others
  send messages. Easier to reason about, easier to test.
- **Single-threaded event loop.** One thread, many pending I/O
  operations. Simplest; limited by the single thread.
- **Parallel pure transformations.** No shared state;
  embarrassingly parallel. Use when the problem shape allows.

Locks without a documented lock order are a recurring source of
deadlocks that take weeks to find. If locks are necessary, the lock
order is part of the design.

### 3.5 Interfaces and contracts

An interface is the decision the component has frozen. Everything else
is implementation and may change.

- Small interfaces with tight contracts are easier to test, substitute,
  and double than large ones.
- A function with five parameters is an interface with five coupling
  surfaces; consider whether some belong together.
- Error modes are part of the interface. A function that can fail in
  three ways but declares none fails its contract as soon as the
  caller gets one of them wrong.
- Invariants should be stated at the interface, even when not enforced
  in the language — a docstring invariant is better than an unstated
  one.

### 3.6 Observability

A component is observable if its behavior can be understood from
outside during a failure. Design for this; do not retrofit.

- Return values carry diagnostic context when they can. "Found / not
  found" beats silently returning `None`; a typed error beats an
  exception message that loses structure.
- Logging is structured and correlated; unstructured logs do not
  survive production.
- State transitions are loggable events. A state machine that does
  not log transitions is a debugging hazard.

---

## 4. Testability Patterns

### 4.1 The test pyramid, in architectural terms

- **Unit tests** verify a component against its own contract. They
  require the component to be instantiable in isolation — a design
  property, not a testing property.
- **Integration tests** verify that two or more components compose
  correctly. They require each component's interface to be honest
  about what it needs and what it promises.
- **System tests** verify end-to-end behavior. They are the last line
  of defense; if they are the first line, the unit and integration
  levels are under-designed.

### 4.2 Seams

Seams are where test doubles substitute for real collaborators. A
component without seams is a component without testability. Common
seams:

- Dependency injection via constructor parameter.
- Higher-order functions (pass the collaborator as a parameter).
- Protocol / interface types that have multiple implementations.

An object that constructs its own collaborators via direct
instantiation is a testing obstacle.

### 4.3 Test doubles

- **Stub.** Returns canned data. Use when the collaborator's behavior
  does not matter, only its presence.
- **Fake.** A working implementation suitable only for tests (in-memory
  store, null logger). Use for collaborators whose real
  implementations are slow or stateful.
- **Mock.** An object that asserts it was called in a specific way.
  Use sparingly; mock-heavy tests become brittle and change-averse.

### 4.4 Determinism

Flaky tests erode trust. Common sources of flakiness:

- Time (`now()`, sleep, timeouts) — inject time.
- Randomness — seed it or inject it.
- Concurrency — test pure logic sequentially; test concurrency
  explicitly at specific seams.
- I/O ordering (file system, network) — fake or isolate.

---

## 5. Debuggability Patterns

Debuggability at integration and system level is a design outcome,
not an afterthought.

### 5.1 Fault isolation topology

Every failure mode should have a component it can be localized to.

- Ask of every component: "if this component is broken, how does the
  system present?" If the answer is "many different symptoms," the
  component has too many responsibilities or its failure modes leak
  upward without structure.
- Circuit breakers, bulkheads, and timeouts are topology decisions,
  not infrastructure concerns. They determine whether a component's
  failure stays local or propagates.

### 5.2 Observable boundaries

Between components, log the boundary crossing:

- Inputs (post-validation, so the value the component actually got is
  visible).
- Outputs (return value or outgoing message).
- Duration (enough to correlate slow paths with failures).

Debugging an integration failure means reconstructing what crossed
the boundary. If the boundary is opaque, the investigation starts by
adding the observability that should have been there.

### 5.3 Error propagation discipline

Errors should acquire context as they propagate, not lose it.

- Re-raising `except Exception: raise` loses the call site.
- Re-raising with context (`raise X from Y`, or wrapping a typed
  error with a containing one) preserves the chain.
- Errors that cross process boundaries need to carry their origin —
  a stringified traceback on one side, a typed error code on the
  other is a common pattern.

### 5.4 State transition tracing

For components with non-trivial state machines, log transitions
unconditionally in debug mode. The "how did we get here?" question
is the most common integration-debugging question; it is answered
cheaply in advance.

---

## 6. Refactoring Patterns

In order of increasing invasiveness:

- **Rename / extract / inline.** Local, reversible, cheap. Should be
  automated by tooling.
- **Extract seam.** Introduce an interface between two components
  that were previously directly coupled, without changing behavior.
  Enables testing and subsequent substitution.
- **Parallel change.** Introduce the new API alongside the old;
  migrate callers incrementally; remove the old. The only safe way
  to change a widely-used interface.
- **Branch by abstraction.** For large internal refactors: introduce
  an abstraction layer, migrate uses to it, replace the
  implementation behind it, collapse the abstraction if no longer
  needed.
- **Strangler fig.** For replacing an entire subsystem: route new
  functionality to the replacement, migrate old functionality piece
  by piece, decommission the original when empty.
- **Characterization tests.** For legacy code without tests: write
  tests that capture current behavior (correct or not), then
  refactor with those tests as a safety net.

Rewrites from scratch are occasionally the right call but are
structurally risky. They discard production knowledge encoded in the
current code. Prefer incremental paths until the evidence for a
rewrite is overwhelming.

---

## 7. Common Tradeoff Axes

Architectural decisions rarely have a single "right" answer; they live
on axes. Naming the axis is half the decision.

- **Generality vs. specificity.** A general solution handles more
  cases but carries more cognitive load. Specific solutions are
  cheaper now, more expensive to change later.
- **Consistency vs. contextual fit.** A pattern applied uniformly is
  learnable; a pattern bent to each context is optimal locally but
  costly system-wide.
- **Explicit vs. convention.** Explicit wiring is verbose but
  discoverable. Convention is compact but depends on the reader
  knowing the convention.
- **Flexibility vs. constraint.** A flexible design accommodates more
  futures but is harder to reason about. Constrained designs are
  easier to understand but cannot be bent when requirements shift.
- **Performance vs. readability.** Usually overstated. In hot paths,
  real. Elsewhere, optimize the readable version and measure.
- **Early abstraction vs. concrete duplication.** Abstracting from two
  examples usually produces the wrong abstraction. Three is the
  common threshold. Duplication with differences is more honest than
  an abstraction with exceptions.

Each tradeoff has a default; none has a universal answer. Name the
axis, name the default, name why the current decision deviates (or
does not).