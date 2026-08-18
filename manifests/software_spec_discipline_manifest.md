# Software Specification Discipline — Manifest

Scope: durable discipline for producing implementation-agnostic architectural and design
specifications for small-scale Python applications, optimized for component reusability. This file
is GROUNDING, not a rulebook: cite a principle only when it materially shapes a decision; reason
beyond it when the situation does not match. Architecture principles, the paradigm menu, the quality
criteria, and verification patterns live in `architecture_manifest_default.md` and are not repeated
here. Python type-system and test-tooling FACTS live in `python_typing_contract_manifest.md` and
`python_testing_tooling_manifest.md`.

## A. The implementation-agnostic specification boundary

A1. **Specify the contract, not the computation.** A specification states inputs, outputs,
    invariants, error modes, ordering constraints, and observable behavior. It does not state the
    algorithm, the control flow, the internal data-structure choice, or code. The implementer owns
    HOW; the spec owns WHAT and HOW-WELL.

A2. **Type-level scaffolding is allowed; bodies are not.** A typed signature, a Protocol, a
    dataclass field set, an invariant expressed as a type — these pin a contract and are in scope. A
    function body, a loop, a branch, a concrete algorithm — out of scope. When a snippet is needed to
    disambiguate a contract, it is a signature or a type, never an implementation.

A3. **Implementation-agnostic is not Python-agnostic.** The spec targets Python and may rely on the
    type system to carry a contract (static typing, structural Protocols, immutability markers). That
    reliance is a platform CONSTRAINT the spec is entitled to assume; it is not an implementation
    decision. Distinguish the two explicitly when it matters.

A4. **Test obligations, not test code.** A unit-test design names the observable contract under test,
    the input partitions / equivalence classes / boundary values, and the expected observable. It
    does not write assertions or test bodies. (Tooling facts: `python_testing_tooling_manifest.md`.)

## B. The requirements cascade (roles, altitudes, feedback)

B1. **Three altitudes, one direction of flow, two directions of pressure.** Needs → system
    requirements (systems engineer) → architecture (architect) → design specs (designer). Work flows
    down; falsification pressure flows up.

B2. **Falsification before acceptance.** No downstream role accepts an upstream artifact until it has
    tried to break it from its own lens and the objection has been answered. The architect tries to
    break the requirement set (untestable, conflicting, missing — surfaced when allocating to
    components). The designer tries to break the architecture (a component that will not go atomic, a
    contract too loose to implement against, a coupling that blocks standalone reuse, a seam that
    cannot be unit-tested). Silent assent is a failure; theatrical dissent is equally a failure.

B3. **Allocation completeness is an invariant.** Every system requirement allocates to at least one
    component; every component justifies itself by at least one requirement. No orphan requirements,
    no unjustified components.

B4. **Requirements are solution-free.** Keep typing, coupling, purity, and other global quality rules
    out of the requirement statements — they are solution constraints, recorded separately as
    architectural-decision requirements with rationale, never buried inside a functional requirement.

B5. **Adaptive depth.** Scale ceremony to reuse ambition, not to line count. Size the problem first;
    for a trivially small, single-use script, compress the cascade and say so. The full ceremony is
    earned by reuse goals and integration risk, not by the existence of a task.

## C. Reusability as a first-class objective

C1. **Two targets.** ATOMIC reusability: a unit is liftable and reusable with no caller knowledge of
    its internals. INTEGRATED reusability: an assembly is reusable as one coherent component. Specify
    for both.

C2. **Reusability is earned by boundaries and contracts, not asserted.** It is bought with clean
    boundary cuts, contracts tight enough that reuse needs no internals, a minimized dependency
    surface, and purity wherever the problem allows. A pure function is the most reusable unit there
    is; an effectful one carries its environment as a reuse tax.

C3. **The dependency surface is the reuse tax — minimize and declare it.** Every dependency a unit
    needs to function is a precondition for reusing it. Inject dependencies at the contract; do not
    reach for them internally. A reusable unit's contract states exactly what it needs from the
    outside.

C4. **Resist speculative reusability (YAGNI).** Do not add parameters, abstraction layers, or
    indirection for hypothetical future callers; that buys coupling against an unproven need. Earn
    reusability through separation of concerns, not premature generalization. When the call is
    contested, record it as an architectural decision with the tradeoff named.

C5. **Demonstrate, don't claim.** Each unit asserted reusable carries, in the output, its standalone
    contract and its dependency surface — a reuse trace. "Reusable" without that trace is unverified.

## D. Requirements elicitation discipline

D1. **Stated needs are the evidence.** Profile what the user actually states before specifying.
    Restate the objective, the consumer of the output, hard constraints, and the runtime inputs the
    application will receive. Name each ambiguity with its downstream consequence.

D2. **Epistemic tagging is mandatory.** Tag every claim and requirement: STATED (from the user),
    INFERRED (reasoned from the stated needs), ASSUMED (panel default chosen without blocking, cheaply
    revisitable), ARCHITECTURAL-DECISION, UNRESOLVED. Never let an inference masquerade as a stated
    need.

D3. **Specify for what will arrive, not only what is stated.** Infer likely future inputs and growth
    from the stated purpose; shape contracts for the horizon, mark the inferences. Balance against C4
    — anticipate inputs, do not invent features.

D4. **Triage explicitly: included / deferred / rejected, each with a reason.** Deferred = leave room,
    do not build now. Rejected = out of scope or no demonstrated need. This is the main guard against
    spec sprawl.

D5. **One clarifying question at a time, only when it changes the design.** Otherwise decide, tag
    ASSUMED, and proceed. (Aligns with `prompt_discovery_partner.md`.)

## E. Requirements writing discipline

E1. **Atomic, numbered, individually verifiable.** One requirement = one testable claim. If it needs
    "and", split it. Identifier scheme: SR-n for system requirements, traceable downstream.

E2. **Each requirement is tagged (per D2) and traces to a verification.** Every requirement maps to a
    test, a contract, or a constraint. Untestable requirements are reworded or dropped.

E3. **Use a disciplined syntax for behavioral requirements.** EARS patterns (ubiquitous /
    event-driven "When <trigger>, the system shall…" / state-driven "While <state>…" / unwanted "If
    <condition>, then…" / optional "Where <feature>…") keep requirements unambiguous. Apply INVEST
    (independent, negotiable, valuable, estimable, small, testable) and the quality characteristics of
    ISO/IEC/IEEE 29148 (necessary, unambiguous, complete, consistent, feasible, verifiable,
    traceable) as the review checklist.

E4. **Separate functional, non-functional, and architectural-decision requirements.** Do not bury an
    architectural decision inside a functional requirement; record it as such, with rationale.

E5. **State the negative space.** Record what is explicitly out of scope and what is deferred, with
    reasons — absence of a requirement is a decision, not an omission.

## F. Testability reasoning framework (judgment half)

F1. **Pure core, imperative shell.** Push logic into pure functions; isolate side effects (I/O,
    clocks, randomness, network, filesystem) into a thin edge. The pure core is unit-testable with no
    doubles; the shell is thin enough to cover with integration tests. This is also the primary
    reusability lever (C2).

F2. **Dependency inversion at every side-effect boundary.** A component declares what it needs from
    the outside (a Protocol, a callable, a typed dependency) rather than reaching for a concrete
    resource. This is what makes a fake possible and a unit testable in isolation.

F3. **Observable contracts over hidden state.** Prefer return values that carry diagnostic context
    over mutation of shared state. A contract observable at the boundary is testable without
    test-only hatches. (Connects to debuggability in `architecture_manifest_default.md`.)

F4. **Fakes over mocks-on-mocks.** Prefer a simple fake implementing the real contract to a tower of
    mock expectations that test the test. (Double taxonomy & tooling: `python_testing_tooling_manifest.md`.)

F5. **Integration-test strategy is owned at architecture altitude and reflected down.** The architect
    decides which seams are integration-tested with which fakes; the designer expresses those seams as
    testable contracts. Host-side testing is preferred where the boundary is honest.

F6. **Property-based testing for pure functions and invariants.** Where a pure function has an
    algebraic property or an invariant over a domain, specify it as a property obligation, not a table
    of examples. (Generator/strategy facts: `python_testing_tooling_manifest.md`.)

## G. Spec output and traceability discipline

G1. **One traceable spine.** SR-n (system requirement) → component → design spec → verification. The
    chain is navigable in both directions; a reader can answer "why does this component exist?" and
    "what verifies this requirement?" without guessing.

G2. **Contracts are signature-level and complete.** A design spec gives the typed contract,
    invariants, error modes, and nomenclature — enough that a developer implements with no further
    questions — and stops at the body.

G3. **The reusability ledger is a required artifact** (per C5): each reusable unit with its standalone
    contract and dependency surface.

G4. **Record contested decisions, do not erase dissent.** A decision log captures each contested
    call, who objected from which lens, how it resolved, and its epistemic tag. Overruled dissent is
    recorded, not deleted — it is the cheapest future-debugging asset there is.

G5. **Open items split into ASSUMED (proceeding on defaults) and NEEDS-INPUT (awaiting the user).**