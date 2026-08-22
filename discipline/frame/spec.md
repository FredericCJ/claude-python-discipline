---
id: frame/spec
kind: frame
title: Specification Discipline
tokens: 1972
load_when:
  - "write a spec"
  - "requirements"
  - "elicitation"
  - "design document"
  - "traceability"
  - "reusability"
  - "what should this component do"
decay: none
---

# Specification Discipline

Grounding for producing implementation-agnostic specifications. Non-prescriptive: this is
how to reason, not a set of rules. The binding obligations that come out of it live in
[law/FLOW] and [law/API].

The source document this is drawn from carried the corpus's only genuine per-rule
identifiers, and its structure is preserved here because it was already the best-organized
material in the set.

This frame specifies the one repository governed by [meta/SCOPE]: either a complete
application or one independently developed component. For a component, the incoming
contract is the top of the local cascade; allocating and verifying the wider application
belongs elsewhere.

---

## A. The specification boundary

**Specify the contract, not the computation.** A specification states inputs, outputs,
invariants, error modes, ordering constraints and observable behaviour. It does not state
the algorithm, the control flow, the internal data structure, or code. The implementer owns
*how*; the spec owns *what* and *how well*.

**Type-level scaffolding is in scope; bodies are not.** A typed signature, a protocol, a
field set, an invariant expressed as a type — these pin a contract. A function body, a
loop, a branch — these do not belong. When a snippet disambiguates a contract, it is a
signature, never an implementation.

**Implementation-agnostic is not language-agnostic.** The spec targets Python and may lean
on the type system to carry a contract. That reliance is a platform constraint the spec is
entitled to assume, not an implementation decision — but say which is which when it matters.

**Test obligations are part of the spec.** An obligation names the observable contract
under test, the input partitions and boundary values, and the expected observable. It
contains no assertions and no test bodies.

## B. The cascade

Three altitudes, one direction of flow, two directions of pressure:

```text
needs or incoming contract  ->  repository requirements  ->  architecture  ->  design specs
                                      <-  falsification pressure  <-
```

**Falsification before acceptance.** No downstream role accepts an upstream artifact until
it has tried to break it from its own vantage point and the objection has been answered.
The architect tries to break the requirement set — untestable, conflicting, missing. The
designer tries to break the architecture — a component that will not decompose, a contract
too loose to implement against, a coupling that blocks standalone reuse, a seam that cannot
be tested. Silent assent is a failure; so is theatrical dissent.

**Allocation completeness.** Every repository requirement allocates to at least one local
module or boundary, and every local module or boundary traces to a requirement or
architectural decision. Cross-repository allocation is outside this frame.

**Requirements are solution-free.** A requirement that names a mechanism has already made
the architect's decision, and usually made it worse.

**Scale ceremony to reuse ambition, not to line count.** Size the problem first. The full
cascade is earned by reuse goals and integration risk, not by the existence of a task.

## C. Reusability

**Atomic reusability** — the unit works standalone, given its declared dependencies.
**Integrated reusability** — it composes without dragging its host's assumptions along.

**The dependency surface is the reuse tax.** Every dependency a unit needs is a
precondition for reusing it. Inject at the contract; do not reach for it internally. This is
the same discipline [law/ARCH] enforces mechanically, seen from the specification side.

**No speculative reuse.** Generality added for an unnamed second consumer is generality
paid for and unverified. Abstracting from two examples usually produces the wrong
abstraction; three is the common threshold. Duplication with differences is more honest
than an abstraction with exceptions.

**A reuse claim needs a trace.** A unit claimed reusable, with no standalone contract and
no dependency surface written down, is unverified.

## D. Elicitation

Restate the objective, the consumer of the output, the hard constraints, and the runtime
inputs the system will actually receive. Name each ambiguity together with its downstream
consequence — an ambiguity with no consequence does not need resolving.

**Tag every claim with its provenance:** `STATED` (from the requester), `INFERRED`
(reasoned from stated needs), `ASSUMED` (a default chosen without blocking, cheaply
revisitable), `ARCHITECTURAL-DECISION`, `UNRESOLVED`. Never let an inference masquerade as
a stated need.

This scheme applies to *your specifications*. It is not the tagging scheme used inside this
corpus — that distinction is the mis-citation recorded in [meta/CONFLICTS], and it is worth
keeping straight.

**Triage explicitly:** included, deferred, rejected — each with a reason.

**One clarifying question at a time, and only when the answer changes the design.**
Otherwise decide, tag it `ASSUMED`, and proceed.

## E. Writing requirements

One claim per requirement, numbered, individually verifiable. One identifier scheme,
traceable downstream.
Separate functional from non-functional from architectural-decision. State the negative
space — what the system will *not* do is as load-bearing as what it will.

A requirement that cannot be verified is not a requirement; it is a preference with
formatting.

## F. Testability reasoning

**Pure core, imperative shell**, with dependency inversion at every side-effect boundary.
Prefer observable contracts over hidden state. Prefer a fake implementing the real contract
to a tower of mock expectations that end up testing the test.

Integration-test strategy is decided at the architecture altitude, not left to whoever
writes the first test. Which seams to cut is a design decision with test consequences, and
deferring it is how a suite ends up testing the seams that happened to be easy.

## G. Output and traceability

The spine runs **repository requirement -> local boundary/module -> design spec ->
verification**, navigable in both directions. A reader should be able to answer "why does
this local element exist?" and "what verifies this requirement?" without guessing.

Required artifacts:

- **Design specs** — signature-level and complete: typed contract, invariants, error modes,
  nomenclature. Enough that a developer implements with no further questions, and stopping
  at the body.
- **A reusability ledger** — each reusable unit with its standalone contract and dependency
  surface.
- **A decision log** — each contested call, who objected and from which vantage point, how
  it resolved, and its provenance tag. Overruled dissent is recorded, not deleted.
- **Open items**, split into `ASSUMED` and `NEEDS-INPUT`.

The decision log and the open-items split are what a later agent reads when the spec turns
out to be wrong. They are the cheapest debugging asset a project has, and the first thing
that gets dropped under time pressure.
