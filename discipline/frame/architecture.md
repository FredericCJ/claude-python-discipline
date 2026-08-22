---
id: frame/architecture
kind: frame
title: Architectural Vocabulary and Paradigms
tokens: 2338
load_when:
  - "which paradigm"
  - "tradeoff"
  - "refactoring"
  - "legacy code"
  - "coupling"
  - "cohesion"
  - "seam"
  - "design options"
  - "inheritance"
  - "composition"
decay: none
---

# Architectural Vocabulary and Paradigms

Grounding, not rules. It fixes vocabulary, lays out the paradigm menu with its tradeoffs,
and names patterns worth remembering. It prescribes nothing — [law/ARCH] does that, and
where the two appear to disagree, the law wins.

Reason from first principles. This exists to make that reasoning legible and to surface
tradeoffs that are easy to forget under time pressure.

The vocabulary applies inside the one repository governed by [meta/SCOPE]. A repository is
either a complete application or one component; a multi-component parent and sibling
repositories are not an additional architectural altitude in this corpus.

---

## Vocabulary

- **Component** — the one governed repository when it participates in a larger
  application: one stated responsibility, a defined counterpart-neutral interface and an
  independent lifecycle in testing. Internal modules do not become separately governed
  components.
- **Interface / contract** — the observable surface: inputs, outputs, invariants, error
  modes, ordering constraints. An interface is the decision a component has frozen.
- **Invariant** — a property that must hold at a named boundary. Invariants are design
  artifacts: checked, asserted, or enforced by types.
- **Seam** — a point where behaviour can be altered without editing the code around it.
  The primary lever for testing and for changing code you did not write.
- **Coupling** — the degree to which two components depend on each other's internals.
  Lower is usually better, but not always: some couplings are necessary, and making a
  necessary one implicit is worse than making it direct.
- **Cohesion** — the degree to which a component's contents serve one purpose. Correlates
  with low coupling but is not the same property.
- **State ownership** — which component has authority to mutate a piece of state. Unclear
  ownership is a recurring source of defects that are hard to localize.
- **Pure function** — same inputs, same outputs, no side effects.

## The paradigm menu

Each entry: where it fits, where it degrades, what to watch.

**Structured / procedural.** Fits computation with a clear sequence. Degrades when state
threading between steps becomes the bulk of the code. Watch for parameter lists growing to
carry context.

**Modular.** Fits any system large enough to need boundaries. Degrades when modules are
drawn by artifact type rather than responsibility. Watch for a module everything imports.

**Object-oriented.** Fits domains with genuine entities carrying identity and behaviour.
Degrades into anaemic data holders plus service classes, which is procedural with extra
indirection. Watch for inheritance used for code reuse rather than substitutability.

**Functional.** Fits transformation pipelines and rule evaluation. Degrades when effects
are pushed so far out that the shell becomes the complicated part. Watch for purity
maintained by threading a growing context object.

**Contract-based.** Fits components with sharp, checkable obligations. Degrades when
contracts describe implementations rather than promises. Watch for preconditions that
merely restate the parameter types.

**Event-driven.** Fits decoupling producers from an unknown set of consumers. Degrades
when the control flow exists only in the reader's head. Watch for ordering assumptions
nobody wrote down.

**Actor / message-passing.** Fits concurrency with clear ownership boundaries. Degrades
when messages carry shared mutable references anyway. Watch for request-response modelled
as two one-way messages with an implicit correlation.

**Dataflow / pipeline.** Fits staged transformation with uniform elements. Degrades when
a stage needs context from three stages back. Watch for the pipeline growing side channels.

**Type-driven / declarative.** Fits invariants expressible in the type system. Degrades
when the types become the hardest part of the codebase to read. Watch for signatures only
their author can follow.

## Cross-cutting concerns

**Coupling and cohesion.** Coupling is not uniformly bad. A type explicitly imported is
better than one implicitly shared by structural coincidence, even though both create a
dependency. Direct, visible coupling is easier to reason about than diffuse, implicit
coupling. Draw module boundaries by responsibility, not by artifact type.

**State and ownership.** Name the owner of every mutable piece of state. Prefer
immutability across boundaries; the cost is copying, the benefit is that a value cannot
change under a reader.

**Error handling.** Several styles exist across the industry — exceptions, typed results,
error codes, panic-and-abort. This discipline has already chosen: exactly two channels,
per [law/ERR]. The menu is recorded here because it is useful to recognize the others when
reading foreign code, not because the choice is open.

**Concurrency.** Choose a model and hold it. Locks without a documented acquisition order
are a recurring source of deadlocks that take weeks to find. If locks are necessary, the
lock order is part of the design.

**Interfaces.** Keep them small. A long parameter list is a coupling surface. Error modes
are part of the interface; an interface that documents its happy path only has documented
half of itself. State invariants at the interface even when the language cannot enforce
them — a documented invariant is better than an unstated one.

**Observability.** Logs are structured and correlated; unstructured logs do not survive
production. State transitions are loggable events. At an external port, the governed
unit's validated input, output and duration are worth recording without naming or
diagnosing a counterpart implementation.

## Testability patterns

**The pyramid, architecturally.** Its shape is a consequence of where the effects are, not
a target to hit. A core that is pure inverts it naturally; a core that is not cannot be
made to fit it by writing more unit tests.

**Seams.** Constructor injection, higher-order functions, and structural protocols are the
three that cost least. A seam introduced for testing that has no other justification is
usually a sign the boundary was real and undiscovered.

**Determinism.** The four recurring sources of nondeterminism are time, randomness,
concurrency, and I/O ordering. Each is controllable; each is expensive to retrofit.

## Debuggability patterns

**Fault isolation boundary.** Ask what the governed unit promises at each port when a local
operation or external role fails. Timeouts and containment are contract terms; the
counterpart's reaction and the larger application's topology are outside this analysis.

**Observable boundaries.** A failure crossing the governed unit's boundary silently is
harder to attribute than one recorded with the local role, operation and contract.

**Error context accretion.** Errors should acquire context as they propagate, not lose it.
The mechanics are in [law/DIAG]; the principle is that the innermost cause and the
outermost context are both needed, and only one of them survives by default.

**State transition tracing.** For a non-trivial state machine, the transition history is
usually a faster diagnosis than the final state.

## Refactoring patterns

Rename, extract and inline are the cheap ones and are almost always worth doing on sight.
**Extract seam** is the one that unlocks the others in code that resists testing.
**Parallel change** — add the new form, migrate callers, remove the old — is how a contract
changes without a flag day. **Branch by abstraction** and the **strangler fig** are the same
idea at larger scale. **Characterization tests** come first when the existing behaviour is
unknown: you cannot preserve what you have not pinned down.

Rewrites carry a specific risk: they discard the accumulated fixes for defects nobody
remembers, and rediscover them one at a time in production.

## Tradeoff axes

Generality against specificity. Consistency against contextual fit. Explicit against
conventional. Flexibility against constraint. Performance against readability. Early
abstraction against duplication.

None of these has a correct default. What they have in common is that the cost of the wrong
choice is paid by whoever reads the code next — increasingly, an agent trying to repair it
without the context in which the choice was made.
