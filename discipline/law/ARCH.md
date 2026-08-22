---
id: law/ARCH
kind: law
title: Architecture and Coupling
tokens: 3361
load_when:
  - "new module"
  - "package layout"
  - "port"
  - "adapter"
  - "hexagonal"
  - "dependency injection"
  - "where does this code go"
  - "import error"
  - "circular import"
applies_to: ["**/*.py"]
grounds_on: ["fact/py-typing", "fact/py-testing"]
decay: none
python: ">=3.11"
---

# Architecture and Coupling

Hexagonal, with pure policy and foreign effects behind typed contracts. The governed
repository declares five roles, four of which contain executable policy or mechanisms:

```text
shell          repository-local wiring, process lifecycle, final escape handling
  | \
  |  adapters  foreign technology effects and representation translation
  |     |
  +-- app      policy sequencing and recovery through injected ports
        |
      domain   pure values, invariants, decisions and typed outcomes

ports          typed contracts used by app and implemented by adapters
```

Ports are declarations, not a fifth executable rung. Application code invokes injected
ports without naming adapters or foreign APIs; the shell selects adapters locally.

---

## Layer boundaries

### ARCH-001 · Source dependencies point toward policy  [BINDING] [check:dependency_boundaries] [auto:import-linter]
The domain MUST depend only on domain policy. Ports MAY depend on domain vocabulary.
Application code MAY depend on domain and ports. Adapters MAY depend on domain and ports.
The repository-local shell MAY depend on every role. A dependency in the reverse
direction MUST fail. The more specific adapter-selection and adapter-independence cases
are [ARCH-019] and [ARCH-003].
- **Why** Direction toward policy keeps a technology or process decision from becoming a
  prerequisite of the rule it serves, while ports let application orchestration invoke
  effects without importing their implementations.
- **Check** `python -m checks.dependency_boundaries` · `lint-imports --config enforce/importlinter.toml` · `python tools/import_gate.py`
- **See** [DOC-014]

[ARCH-018] separately makes role-path completeness decidable; dependency direction cannot
be credited for files the declaration omitted.

### ARCH-002 · The domain imports nothing that can perform I/O  [BINDING] [auto:import-linter] [check:domain_purity]
Modules under `domain/` MUST NOT import any I/O-capable module — filesystem, network,
subprocess, environment, wall clock or process-global randomness — directly or
transitively.
- **Why** A pure domain means a domain-layer failure is a logic defect, never an
  environment one; that inference is what makes the layer field worth recording.
- **Check** `lint-imports --config enforce/importlinter.toml` contract `ARCH-002 domain is pure` · `python tools/import_gate.py` · `python -m checks.domain_purity`
- **See** [ARCH-006] · [law/DIAG]

### ARCH-003 · Adapter boundaries remain independent  [BINDING] [check:dependency_boundaries] [auto:import-linter]
One adapter boundary MUST NOT import another adapter boundary. Several cooperating modules
inside one declared adapter boundary are allowed. Composition happens in the
repository-local shell, never between independent adapters.
- **Why** Independent adapters mean a misbehaving one cannot contaminate a healthy one,
  which is the property the fault tests exist to demonstrate.
- **Check** `python -m checks.dependency_boundaries` · `lint-imports --config enforce/importlinter.toml` contract `ARCH-003 adapters are independent` · `python tools/import_gate.py`

### ARCH-004 · Each foreign dependency has one importer module  [RETIRED]
Retired because a single module is a physical form, not the intended ownership property,
and because a transitive ban on the local shell contradicted its wiring responsibility.
One adapter *boundary* now owns all direct imports while shell-to-adapter reach is valid.
- **Why** Retaining the id makes old findings resolvable without preserving the defective
  one-file prescription or silently changing what historical citations meant.
- **Superseded by** ARCH-020
- **See** [ARCH-011] · [EVID-005]

### ARCH-005 · Effects are named in the signature  [BINDING] [check:explicit_effects]
A function that performs an effect MUST receive the port that performs it as a parameter.
Reaching for a clock, a random source, an environment variable or a filesystem inside a
function body is prohibited.
- **Why** An effect passed in can be substituted, and therefore faulted on demand; an
  effect reached for cannot, and its failure mode is untestable.
- **Check** `python -m checks.explicit_effects`

### ARCH-006 · Domain functions are total or return a typed result  [BINDING] [auto:mypy]
A domain function MUST either be total for its argument types, or return a discriminated
result union whose error arm the caller is forced to handle.
- **Why** Exhaustiveness is checkable; a docstring promise is not.
- **Check** `mypy --strict` with exhaustiveness on the result union
- **See** [law/ERR]

### ARCH-011 · Adapters are selected at one local wiring root  [BINDING] [check:single_wiring_point]
Concrete adapters MUST be chosen in a single repository-local wiring module in `shell`.
No other module may select a concrete adapter class. This root does not assemble sibling
repositories or define a larger application's topology.
- **Why** Replaceability that requires edits in several places is not replaceability; the
  single root is what makes substitution in a test identical to substitution in production.
- **Check** `python -m checks.single_wiring_point`

---

## Keeping the core clean

### ARCH-012 · No test-mode branch in production code  [BINDING] [check:no_test_branches]
Production modules MUST NOT contain conditionals keyed on a test environment variable, a
test flag, or the identity of the caller.
- **Why** Testability comes from the seam, not from the code knowing it is being tested —
  and a branch that only runs under test is a branch nothing verifies in production.
- **Check** `python -m checks.no_test_branches`

### ARCH-013 · Framework and transport types stay out of the domain  [BINDING] [check:domain_purity]
Domain signatures MUST NOT mention an argument parser namespace, an ORM model, a request
object, a serialization node, or any other type owned by a framework.
- **Why** A domain modelled in a framework's types is coupled to it at every call site,
  and the framework's failures become indistinguishable from the domain's.
- **Check** `python -m checks.domain_purity`

### ARCH-014 · Translation between representations is explicit  [BINDING] [review]
Wire and storage representations MUST be converted to domain types by a named function at
the boundary, never by attribute-name coincidence or automatic mapping.
- **Why** An explicit mapping fails in one identifiable place with both values in hand;
  an implicit one fails somewhere downstream with neither.
- **Check** `adversarial-review.json` question `contracts`, against the declared
  representation and translation evidence

### ARCH-015 · Metaprogramming leaves the four questions answerable  [BINDING] [check:no_magic_in_domain]
Inside the domain, it MUST remain possible to answer by reading the code — not by running
it — what runs, when, what state it changes, and what happens when it fails.
- **Why** A mechanism that requires a debugger to trace defeats every diagnostic
  guarantee downstream of it.
- **Check** `python -m checks.no_magic_in_domain`

### ARCH-016 · Module complexity stays within budget  [BINDING] [auto:ruff:C901]
No function may exceed the configured cyclomatic complexity budget.
- **Why** A budget nobody measures is a wish; the source corpus watched a suite degrade
  for exactly that reason.
- **Check** `ruff check` (rule `C901`)

### ARCH-017 · Prefer the direct call to the abstraction  [ADVISORY]
An abstraction SHOULD be introduced when it creates a boundary for specification,
substitution, observation or containment — not for symmetry.
- **No mechanism** Whether a boundary is *meaningful* is a design judgment; [ARCH-021]
  checks only that a volatile decision and concrete change scenario were actually recorded.
- **Why** Layers added without a stated purpose are indistinguishable from layers added
  by habit, and each one lengthens every trace.

### ARCH-018 · Every production source has one declared role  [BINDING] [check:source_roles]
Every Python file beneath a declared production source root MUST match exactly one
repository-relative `domain`, `application`, `ports`, `adapters`, or `shell` role path.
An absent source root and an unmapped source file are failures, never empty successful
walks. Ports are contract declarations and are not a fifth executable layer.
- **Why** A layer-scoped mechanism cannot decide anything about a file it silently calls
  `unknown`. An explicit path partition turns that silence into a local, actionable defect
  without claiming that the declared role is semantically correct.
- **Check** `python -m checks.source_roles`
- **See** [ARCH-001] · [EVID-003]

### ARCH-019 · Application code names no concrete adapter  [BINDING] [check:dependency_boundaries]
Application orchestration MUST invoke effects only through injected port contracts and
MUST NOT directly import an adapter implementation. Adapter selection belongs to the
repository-local shell.
- **Why** This is the precise dependency-inversion seam. It permits the application to
  cause effects while keeping policy independent of the technology that realizes them.
- **Check** `python -m checks.dependency_boundaries`
- **See** [ARCH-005] · [ARCH-011] · [EFCT-001]

### ARCH-020 · One adapter boundary owns each technology  [BINDING] [check:dependency_boundaries]
Every declared third-party or system technology import MUST have exactly one owning
adapter boundary. Production code outside that boundary MUST NOT import the technology
directly. Several modules inside the owner MAY import it, and the local shell MAY reach it
transitively by importing the selected adapter.
- **Why** Boundary ownership gives a foreign technology one containment and translation
  site without forcing an adapter into one file or making valid local wiring impossible.
- **Check** `python -m checks.dependency_boundaries`
- **See** [ARCH-003] · [ARCH-011] · [DEP-002]

### ARCH-021 · Boundaries hide named volatile decisions  [BINDING] [check:architecture_model]
The repository MUST carry one canonical `architecture.json` whose unit kind agrees with
its project declaration. Every internal boundary MUST be justified by a named volatile
decision, its owning role, and at least one concrete change scenario the boundary is
intended to absorb.
- **Why** A directory diagram records a physical form. Information hiding records why the
  boundary exists and supplies a falsifiable change against which its cohesion can be
  reviewed.
- **Check** `python -m checks.architecture_model`
- **See** [ARCH-017] · [EVID-004]

### ARCH-022 · Four local architecture views stay complete  [BINDING] [check:architecture_model]
The canonical architecture record MUST contain this repository's boundary operations and
interaction terms, resource ownership or an explicit absence, and failure detection,
containment, recovery ownership, escalation, and terminal state. The source dependency
view is the joined project role and ownership declaration. Every record MUST use stable
local identifiers, exact fields, and resolvable local roles.
- **Why** Imports, runtime interaction, resource lifetime, and failure propagation are
  different graphs. Flattening them into one component diagram hides ownerless cleanup
  and implicit recovery policy.
- **Check** `python -m checks.architecture_model`
- **See** [ARCH-018] · [law/ERR]

### ARCH-023 · Component contracts name roles, never peers  [BINDING] [check:architecture_model]
For `unit = "component"`, published and consumed contracts MUST identify external actors
only by lower-snake contract roles. The local model MUST NOT carry a parent or sibling
repository identity, filesystem location, deployment endpoint, address, or topology.
External snapshots MAY record version, digest, and source role, never a source checkout.
- **Why** A standalone component owns what it promises and consumes, not which concrete
  counterpart or deployment happens to satisfy that role in a larger application.
- **Check** `python -m checks.architecture_model`
- **See** [meta/SCOPE] · [EVID-006]
