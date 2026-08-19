---
id: law/ERR
kind: law
title: Error Semantics
tokens: 2609
load_when:
  - "raise"
  - "except"
  - "Result"
  - "error type"
  - "exception hierarchy"
  - "validation"
  - "parse"
  - "assert_never"
  - "ExceptionGroup"
applies_to: ["**/*.py"]
grounds_on: ["fact/py-errors", "fact/py-testing", "fact/py-typing"]
requires: ["law/ARCH"]
decay: none
python: ">=3.11"
---

# Error Semantics

Which channel a failure travels on, and what the type system is made to guarantee about
it. [law/DIAG] governs what an error *carries*; this module governs what it *is* and who
is forced to handle it.

The whole design follows from one asymmetry: **a raised exception is invisible to the type
checker, an in-band result is not.** So outcomes that belong to the contract are typed and
returned, and outcomes that are genuinely exceptional are raised.

---

## The two channels

### ERR-001 · Exactly two propagation channels exist  [BINDING] [check:error_channels]
Expected, recoverable outcomes that belong to a function's contract MUST be returned as a
discriminated result union. Genuinely exceptional, unrecoverable-at-this-layer or
programmer-error conditions MUST be raised. No third channel — no error return codes, no
sentinel values, no out-parameters.
- **Why** The typed channel is the one a checker can force a caller to handle; putting a
  contract outcome on the raised channel silently makes handling optional.
- **Check** `python -m checks.error_channels`

### ERR-002 · Result unions are exhaustively handled  [BINDING] [auto:mypy] [auto:pyright]
Every result union MUST be narrowed to `Never` at each consumer, with a final
`assert_never` that fails to typecheck if any member remains unhandled.
- **Why** This is what makes adding an error variant break the build rather than leak
  through an untested branch — the single most valuable static guarantee in the discipline.
- **Check** `mypy --strict` · `pyright --strict`
- **See** [ERR-005] · [law/TYPE]

### ERR-003 · Conversion between channels happens at one named seam  [BINDING] [check:error_channels]
The module and direction at which raised infrastructure failures become typed domain
results MUST be named explicitly in the shell layer, and conversion MUST NOT occur
anywhere else.
- **Why** A seam left implicit is a seam no one can test, and the source corpus left this
  decision deferred between two documents until neither made it.
- **Check** `python -m checks.error_channels`
- **See** [law/ARCH]

---

## Taxonomy

Two disjoint hierarchies, each owned by a layer. The flat single-hierarchy form used by one
source document is superseded — see [meta/CONFLICTS].

```text
DomainError            produced only by domain and app
  NotFound             kind, id
  InvalidCommand       field, reason, suggestion
  InvariantViolation   invariant, detail
  Conflict             what, existing
  IllegalTransition    from_state, to_state
  UnsupportedSchema    found, supported
  CorruptModel         where, detail

InfrastructureError    produced only by adapters
  PortFailure          port, cause
  Timeout              port, budget
  ContractViolation    port, expectation, observed
  ExternalToolFailure  tool, exit_code, diagnostics
```

### ERR-004 · A layer produces only its own error family  [BINDING] [check:error_channels]
Domain and app code MUST NOT construct or return an infrastructure error. Adapters MUST
NOT construct a domain error.
- **Why** Layer ownership is what makes the envelope's `layer` field derivable from the
  error's type alone, rather than guessed from a traceback.
- **Check** `python -m checks.error_channels`
- **See** [law/DIAG]

### ERR-005 · A new variant is declared at its definition site  [BINDING] [auto:mypy]
Adding an error variant MUST mean adding it to the union's declaration, so every
exhaustiveness check fails until each consumer is updated.
- **Why** A variant introduced by returning an undeclared type is invisible to every
  caller and to the checker.
- **Check** `mypy --strict`

### ERR-006 · Exceptions form one narrow hierarchy under a package base  [BINDING] [check:exception_shape]
Custom exceptions MUST derive from a single package-level base which itself derives from
`Exception`, never from `BaseException`. Names end in `Error`. Multiple inheritance among
exception types is prohibited.
- **Why** One base gives a consumer a single, reliable catch for "this library failed";
  a flat set of unrelated types gives them no safe boundary at all.
- **Check** `python -m checks.exception_shape`

### ERR-007 · Define an exception only when a caller must distinguish it  [ADVISORY]
Define a custom exception when callers need to branch on it programmatically, or when it
crosses a published boundary. Otherwise reuse a built-in.
- **No mechanism** Whether a caller *needs* to distinguish an outcome is a contract
  judgment; [ERR-006] mechanizes the shape, not the decision to create one.
- **Why** A hierarchy with a type per call site is as unusable as one with no types.

---

## Catching

### ERR-008 · Catch narrowly  [BINDING] [auto:ruff:BLE001]
`except` clauses MUST name the specific exception types they handle. Broad base classes
are caught only at a top-level boundary that converts to an envelope and exits.
- **Why** A broad catch converts an unrelated defect into the handled path, and the real
  fault is never reported.
- **Check** `ruff check` (rules `E722`, `BLE001`)
- **See** [law/DIAG]

### ERR-009 · The `try` body holds only what can fail  [BINDING] [auto:ruff:TRY300]
Code that cannot raise the caught exception MUST move to an `else` clause; cleanup that
must always run MUST use `finally`.
- **Why** A wide `try` body silently extends a handler's reach over statements it was
  never written for.
- **Check** `ruff check` (rules `TRY300`, `TRY301`)

### ERR-010 · Grouped failures propagate as a group  [BINDING] [check:exception_shape]
Concurrent or batched operations that can fail independently MUST raise an exception group
and be handled with `except*`, rather than collapsing to the first failure.
- **Why** Reporting one of five failures gives an agent one fifth of the diagnosis and no
  indication that the rest exist.
- **Check** `python -m checks.exception_shape`

---

## Boundaries

### ERR-011 · Parse at the boundary; do not validate in the interior  [ADVISORY]
External data MUST be converted to a domain type by a validating constructor at the
boundary, which returns a result. Interior code receives types that cannot be invalid.
- **Why** Validation repeated in the interior is validation that can be forgotten in one
  place; parsing once makes the invalid state unrepresentable thereafter.
- **No mechanism** The rule's deeper claim -- that validation happens at the
  boundary rather than scattered through the interior -- needs to know which values
  crossed a boundary, and an AST check cannot see that. `check:boundary_parsing`
  named this rule for a year and never once reported it; its own docstring said so.
  What IS mechanized is the adjacent, narrower [ERR-013] and [TYPE-005].
- **See** [law/TYPE]

### ERR-012 · Boundary validation survives optimized bytecode  [BINDING] [check:assert_usage]
Boundary checks MUST be ordinary statements or a validating library, never assertions.
- **Why** Assertions are stripped under optimization, so a boundary guarded by one is
  unguarded in exactly the deployment that removed it.
- **Check** `python -m checks.assert_usage`
- **See** [law/DIAG]

### ERR-013 · Try the operation rather than pre-checking the world  [BINDING] [check:boundary_parsing]
Where a pre-check and the operation it guards can disagree — filesystem existence,
permissions, resource availability — the operation MUST be attempted and its failure
handled, rather than guarded by a prior check.
- **Why** Between the check and the use, the world changes; the guarded form has a race
  the direct form does not.
- **Check** `python -m checks.boundary_parsing`

---

## Failure kinds

### ERR-014 · Expected failure and contract violation are distinguished  [ADVISORY]
A refusal the contract anticipates MUST be a typed result. A response that breaks the
contract — a store that accepts a value and returns a different one — MUST raise.
- **Why** They demand opposite reactions: one is handled, the other means a component is
  lying and nothing downstream of it can be trusted.
- **No mechanism** Whether a given failure is *conceptually* expected or a contract
  violation is a judgement about intent. `check:error_channels` named this rule and
  never reported it, and its docstring said the rule keeps a reviewer for exactly
  this reason. Retagged rather than left claiming a gate that would never fire.

### ERR-015 · No unhandled exception reaches the process boundary  [BINDING] [fitness:test_no_unhandled_escape]
Every entry point MUST convert an escaping exception into a diagnostic envelope and a
defined exit status.
- **Why** An interpreter traceback on stderr is the one failure output that carries no
  code, no layer and no remediation.
- **Check** `pytest enforce/fitness/test_diagnostics.py::test_no_unhandled_escape`
- **See** [law/DIAG] · [law/API]

### ERR-016 · A fault is contained at the boundary that detected it  [BINDING] [fitness:test_fault_containment]
A failing component MUST be detected, converted and either rejected or degraded, leaving
neighbouring components in a healthy state.
- **Why** Containment is what makes the layer attribution meaningful; without it a fault's
  first observable symptom is somewhere else entirely.
- **Check** `pytest enforce/fitness/test_faults.py::test_fault_containment`
- **See** [law/TEST]
