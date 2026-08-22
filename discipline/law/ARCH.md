---
id: law/ARCH
kind: law
title: Architecture and Coupling
tokens: 2921
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

Hexagonal, with a functional core and an imperative shell. Not a preference: it is what
makes a fault's origin follow from its layer, so an error can be localized without
reading the code that produced it.

Four layers, dependencies pointing inward only:

```text
shell        process entry, exit codes, effect execution
  |
adapters     the ONLY place a foreign dependency may be imported
  |
app          orchestration over the domain; no direct I/O
  |
domain       pure logic; total or Result-returning
```

---

## Layer boundaries

### ARCH-001 · Dependencies point inward only  [BINDING] [auto:import-linter]
Each layer MUST import only from layers beneath it: `shell` to `adapters` to `app` to
`domain`. `domain` imports nothing from the others. A project MAY map its own directory
names onto these four in `[tool.agent-discipline]`; it MUST NOT add a fifth.
- **Why** An inward-only graph is what lets a stack trace's deepest frame name the layer
  that owns the fault. The names are canonical because the *order* is what carries the
  meaning; a layer outside that order has no defined direction to point in.
- **Check** `lint-imports --config enforce/importlinter.toml` contract `ARCH-001 layers point inward` · `python tools/import_gate.py`
- **See** [DOC-014]

The four names are how every layer-scoped mechanism finds its subject. A project laying its
code out as `services/` and `composition/` without declaring the mapping has those files
resolve to no layer at all, and every such check skips them **while reporting clean** —
which is why the declaration is a rule and not a convenience.

### ARCH-002 · The domain imports nothing that can perform I/O  [BINDING] [auto:import-linter] [check:domain_purity]
Modules under `domain/` MUST NOT import any I/O-capable module — filesystem, network,
subprocess, environment, wall clock or process-global randomness — directly or
transitively.
- **Why** A pure domain means a domain-layer failure is a logic defect, never an
  environment one; that inference is what makes the layer field worth recording.
- **Check** `lint-imports --config enforce/importlinter.toml` contract `ARCH-002 domain is pure` · `python tools/import_gate.py` · `python -m checks.domain_purity`
- **See** [ARCH-006] · [law/DIAG]

### ARCH-003 · No adapter imports another adapter  [BINDING] [auto:import-linter]
Adapter modules MUST be independent of one another. Composition happens in `shell`, never
between adapters.
- **Why** Independent adapters mean a misbehaving one cannot contaminate a healthy one,
  which is the property the fault tests exist to demonstrate.
- **Check** `lint-imports --config enforce/importlinter.toml` contract `ARCH-003 adapters are independent` · `python tools/import_gate.py`

### ARCH-004 · Each foreign dependency is imported in exactly one module  [BINDING] [auto:import-linter]
A third-party or system-level dependency MUST appear in the import graph of exactly one
adapter module.
- **Why** This is what "push coupling to the very edge" means operationally: a library
  reachable from two places has two possible blast radii and no single owner.
- **Check** `lint-imports --config enforce/importlinter.toml` contract `ARCH-004 foreign dependencies are cornered` · `python tools/import_gate.py`
- **See** [ARCH-010]

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

---

## Ports and swappability

### ARCH-007 · Every port is a Protocol with a published contract  [BINDING] [fitness:test_every_port_is_a_protocol]
A boundary the core crosses MUST be expressed as a `Protocol` under `ports/`, with its
inputs, outputs, error modes, ordering constraints and idempotency stated.
- **Why** The contract is the oracle every adapter is tested against; without it there is
  nothing for a fake to be faithful to.
- **Check** `pytest enforce/fitness/test_ports.py::test_every_port_is_a_protocol`
- **See** [ARCH-008] · [law/TEST]

### ARCH-008 · Every port has a real, a fake and a faulty adapter  [BINDING] [fitness:test_port_triad]
Unconditionally, with no "if it has meaningful failure modes" qualifier.
- **Why** The port judged to have no failure mode is the one whose failure is discovered
  in production. Swappability is proved by three implementations, not asserted by one.
- **Check** `pytest enforce/fitness/test_ports.py::test_port_triad`

### ARCH-009 · One contract suite runs against every adapter  [BINDING] [fitness:test_contract_suite_per_adapter]
The port's suite MUST run against the real adapter, the fake, and the faulty adapter in
healthy mode, unchanged.
- **Why** A fake that can drift from its real counterpart without a test failing is
  worthless, and every unit test standing on it is worth as little.
- **Check** `pytest enforce/fitness/test_ports.py::test_contract_suite_per_adapter`

### ARCH-010 · A port earns its place from a stated justification  [BINDING] [fitness:test_port_justification]
Every port MUST name, in its module docstring, which of these it claims: replacing the
implementation without touching the core; testing the core against a fake; a named
behavioural contract; controlling a specific effect; fault injection; observing an
interaction; isolating the core from an unstable external technology; supporting more than
one real adapter.
- **Why** Without a closed list, "port" degrades into wrapping standard-library calls,
  and the boundary stops meaning anything.
- **Check** `pytest enforce/fitness/test_ports.py::test_port_justification`

Serialization, path computation and hashing are *not* ports on purity grounds alone — they
are pure functions and belong in the domain. They become ports only when one of the eight
justifications applies, most often containment of an unstable external format.

### ARCH-011 · Adapters are selected at one composition root  [BINDING] [check:single_wiring_point]
Concrete adapters MUST be chosen in a single wiring module in `shell`. No other module may
name a concrete adapter class.
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

### ARCH-014 · Translation between representations is explicit  [BINDING] [check:domain_purity]
Wire and storage representations MUST be converted to domain types by a named function at
the boundary, never by attribute-name coincidence or automatic mapping.
- **Why** An explicit mapping fails in one identifiable place with both values in hand;
  an implicit one fails somewhere downstream with neither.
- **Check** `python -m checks.domain_purity`

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
- **No mechanism** Whether a boundary is *meaningful* is a design judgment; the closed
  justification list in [ARCH-010] mechanizes the part of it that can be.
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
