---
id: law/TYPE
kind: law
title: Typing and Contracts
tokens: 2211
load_when:
  - "type hint"
  - "mypy"
  - "pyright"
  - "Protocol"
  - "generic"
  - "dataclass"
  - "NewType"
  - "Enum"
  - "Any"
  - "cast"
  - "type error"
applies_to: ["**/*.py"]
grounds_on: ["fact/py-testing", "fact/py-typing"]
requires: ["law/ARCH"]
decay: none
python: ">=3.11"
---

# Typing and Contracts

Strong typing is not a style choice here; it is the mechanism by which a contract is
enforced rather than described. Every rule below buys a specific guarantee that the
diagnostic envelope or the test oracles then depend on.

The type system's limits are as load-bearing as its powers: it cannot express value
ranges, cross-field invariants, ordering constraints, units, or stateful protocols. Those
become boundary parsing and runtime contracts, and the rules say which is which.

---

## Checking

### TYPE-001 · Two checkers, both strict, both pinned  [BINDING] [auto:mypy] [auto:pyright]
The package MUST pass both configured checkers in their strict configurations, with the
enabled rule set committed to version control.
- **Why** The two infer differently, so agreement between them is a differential oracle;
  "strict" alone names no portable rule set and guarantees nothing.
- **Check** `mypy --strict src/` · `pyright src/` · `python tools/type_gate.py`
- **See** [law/TEST]

### TYPE-002 · The domain carries no `Any`  [BINDING] [auto:mypy] [check:domain_purity]
Domain modules MUST NOT use `Any`, explicit or implicit — including via untyped
third-party stubs and unannotated function bodies.
- **Why** `Any` silently disables every downstream guarantee on the values that flow
  through it, so the layer whose errors must be trustworthy is the layer it cannot enter.
- **Check** `mypy --strict --disallow-any-explicit src/domain` · `python -m checks.domain_purity`

### TYPE-003 · Escape hatches are narrow, justified and counted  [BINDING] [auto:mypy] [auto:ruff:PGH003]
Every `cast`, `type: ignore` and explicit `Any` MUST name the specific rule it suppresses
and carry a comment giving the reason. Redundant casts and unused ignores fail the build.
- **Why** A `cast` is an unchecked assertion the checker trusts blindly; a wrong one
  propagates a lie until something unrelated crashes, which is the hardest failure to trace.
- **Check** `mypy --warn-redundant-casts --warn-unused-ignores` · `ruff check` (rule `PGH003`)

---

## Making invalid states unrepresentable

### TYPE-004 · Distinct concepts are distinct types  [BINDING] [review]
Identifiers and domain scalars MUST NOT be interchangeable primitives. Each concept gets
its own type.
- **Why** Passing an argument in the wrong position is the defect class this eliminates
  outright rather than testing for.
- **Check** `adversarial-review.json` questions `architecture` and `contracts`, against
  the repository's domain vocabulary and strict-checker evidence

### TYPE-005 · A constrained type is a wrapper with a parsing constructor  [BINDING] [check:boundary_parsing]
A type carrying a well-formedness rule MUST be a frozen wrapper whose constructor
validates and returns a result. `NewType` is prohibited for constrained values.
- **Why** `NewType` has no constructor and validates nothing, so it renames a primitive
  without excluding a single invalid value.
- **Check** `python -m checks.boundary_parsing`
- **See** [law/ERR]

### TYPE-006 · Closed sets are enumerations  [BINDING] [check:domain_purity]
A value drawn from a fixed set MUST be an enumeration, not a string literal union.
- **Why** An enumeration has one definition site that exhaustiveness checking follows;
  a literal union repeated at each use has as many definitions as usages.
- **Check** `python -m checks.domain_purity`

### TYPE-007 · Domain values are frozen and slotted  [BINDING] [check:domain_purity]
Domain value types MUST be immutable dataclasses with slots.
- **Why** A value that cannot be mutated after construction cannot drift between
  validation and use, which is what lets an error name the value it was given.
- **Check** `python -m checks.domain_purity`

### TYPE-008 · Signatures take read-only collection types  [BINDING] [check:domain_purity]
Function signatures MUST declare immutable or read-only collection types for parameters
the callee does not own.
- **Why** A mutable collection in a signature is an undeclared output channel, and the
  caller learns about it only when its own data changes underneath it.
- **Check** `python -m checks.domain_purity`

---

## Boundaries and contracts

### TYPE-009 · Ports are structural protocols  [RETIRED]
Retired because structural and nominal typing can both preserve inward dependencies when
the boundary contract is owned by the ports role. The repository now declares its form
and the conformance mechanism checks that source matches it.
- **Why** The v3 rationale incorrectly treated an adapter importing an inward port
  contract as dependency reversal. The relevant property is direction and typed
  conformance, not structural typing alone.
- **Superseded by** ARCH-024
- **See** [law/ARCH]

### TYPE-010 · Runtime protocol checks are not contract checks  [BINDING] [check:boundary_parsing]
A runtime-checkable protocol MUST NOT be used as evidence that an object satisfies a
contract; it confirms member existence only, never signature or behaviour.
- **Why** An object that passes the runtime check and violates the contract produces a
  failure attributed to the wrong component.
- **Check** `python -m checks.boundary_parsing`

### TYPE-011 · What the checker cannot enforce is enforced at runtime  [ADVISORY]
Value ranges, cross-field invariants, ordering and temporal constraints, units, and
stateful protocols MUST be enforced by boundary parsing or an explicit runtime contract,
and stated in the docstring. They MUST NOT be assumed carried by an annotation.
- **Why** Any claim that strict typing guarantees correctness is false, and a contract
  that relies on it fails without ever having been checked.
- **No mechanism** Which constraints a checker *could* have carried is a judgement
  about the type system's reach on that expression, not a property of the syntax.
  `check:boundary_parsing` named this rule and never reported it.
- **See** [TYPE-005] · [law/ERR]

### TYPE-012 · Signature or docstring, by who can enforce it  [ADVISORY]
If a checker can enforce a constraint, it MUST be in the signature. If only a human or a
runtime check can, it MUST be in the docstring and backed by a runtime check where it
matters.
- **Why** A constraint in prose that a checker could have carried is a guarantee
  downgraded to a hope for no reason.
- **No mechanism** The rule turns on who *can* enforce a constraint, which is the
  same judgement as [TYPE-011] read from the other side. `check:boundary_parsing`
  named it and never reported it.

### TYPE-013 · Conversions are explicit  [BINDING] [auto:mypy]
Numeric and string conversions MUST be written explicitly; implicit coercion and
cross-type equality comparisons fail the build.
- **Why** A silent coercion is a value changing identity with no site to attribute it to.
- **Check** `mypy --strict-equality`

### TYPE-014 · Immutability is declared, and not mistaken for a guarantee  [BINDING] [review]
Frozen dataclasses, read-only mappings and final declarations MUST be used to signal
intent; code MUST NOT rely on them being unbypassable.
- **Why** The freeze is shallow and can be circumvented; treating it as a hard guarantee
  produces an invariant nothing actually maintains.
- **Check** `adversarial-review.json` question `architecture`, against declared
  invariants, mutation ownership, and strict-checker evidence

### TYPE-015 · Type sophistication stays proportionate  [ADVISORY]
Type-level machinery SHOULD be introduced when it removes a class of defect, not to
demonstrate that it can be.
- **No mechanism** "Proportionate" is a judgment about the defect being prevented, which
  no check can weigh against the reading cost it imposes.
- **Why** A signature only a specialist can read moves the comprehension cost onto every
  future reader, including the agent trying to repair it.
