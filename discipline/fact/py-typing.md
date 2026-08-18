---
id: fact/py-typing
kind: fact
title: Python Typing and Checkers
tokens: 1546
load_when:
  - "mypy flags"
  - "pyright config"
  - "strict mode"
  - "Protocol"
  - "TypedDict"
  - "PEP 695"
  - "cast"
  - "runtime_checkable"
verified: 2026-08-18
decay: quarters
python: ">=3.11"
---

# Python Typing and Checkers

Verified truth about what the type system and the checkers actually do. Facts, not rules —
the obligations are in [law/TYPE]. Every claim is tagged with how far it can be trusted.

Versions below are the ones installed in this project's environment and confirmed by
invoking the tools. Re-verify against the changelogs before relying on a pin.

---

## Installed versions

| Tool | Version | Tag |
|---|---|---|
| CPython | 3.13.15 | `VERSION-DEPENDENT` |
| mypy | 2.3.1 | `VERSION-DEPENDENT` |
| pyright | 1.1.411 | `VERSION-DEPENDENT` |
| ruff | 0.16.3 | `VERSION-DEPENDENT` |
| pydantic | 2.13.4 | `VERSION-DEPENDENT` |

`VERSION-DEPENDENT` — mypy crossed a major boundary at 2.0, which changed several defaults
including byte-type strictness and local partial types. A configuration written against the
1.x line is not safe to assume equivalent.

## Strictness is not portable

`ESTABLISHED` — "strict" names a different rule set in each checker, and a different one in
each version of each checker. The two also use different inference algorithms, so they
disagree on real code.

`ESTABLISHED` — mypy's strict bundle enables roughly fifteen flags. It notably does **not**
ban explicit `Any`; that requires an additional flag. Nor does it warn on unreachable code
or on decorated-`Any` by default.

`ESTABLISHED` — pyright has four modes (off, basic, standard, strict). The CLI default and
the editor-extension default differ, so a file can be clean in one and not the other.

**Consequence for [law/TYPE]:** naming a checker is not enough. The version and the
enabled rule set are pinned in `enforce/pyproject.toml` and committed, and both checkers
run because their disagreement is information.

## What the type system cannot express

`ESTABLISHED` — none of these is carried by an annotation:

- value ranges and magnitudes
- cross-field invariants
- ordering and temporal constraints
- units of measure
- stateful protocols, where the legal calls depend on prior calls

Each must become boundary parsing, a runtime contract, or a documented and separately
checked obligation. See [law/TYPE] and [law/ERR].

## Things that look like guarantees and are not

`ESTABLISHED` — `cast` has **no runtime effect**. The implementation returns its argument
unchanged. It is a promise the checker trusts without evidence; a wrong one propagates
silently until something unrelated fails.

`ESTABLISHED` — a runtime-checkable protocol checks **member existence only**. It does not
check signatures, and never checks behaviour.

`ESTABLISHED` — frozen dataclasses are **shallowly** immutable, and the freeze can be
bypassed. The official documentation states outright that truly immutable objects are not
possible in this language.

`ESTABLISHED` — `Final` and annotation metadata are checker-only. They constrain nothing at
runtime.

`ESTABLISHED` — assertions are removed under optimized bytecode. Any check that must run in
production cannot be an assertion. This is a correctness and a security property, and it is
the basis of the boundary rules in [law/ERR].

## Vocabulary that does carry weight

`ESTABLISHED` — structural protocols give conformance by shape, which is what allows an
adapter to satisfy a port without importing the core. This is load-bearing for the
dependency direction in [law/ARCH].

`ESTABLISHED` — a discriminated union narrowed to `Never`, closed with an exhaustiveness
assertion, makes adding a variant a build failure at every consumer. This is the strongest
static guarantee available here and is why [law/ERR] puts contract outcomes on the returned
channel.

`ESTABLISHED` — enumerations have one definition site that exhaustiveness follows. Literal
unions repeated at each use do not.

`ESTABLISHED` — a distinct-type alias with no constructor validates nothing. A frozen
wrapper with a parsing constructor does, which is the distinction behind the wrapper rule.

## Version gates

| Feature | Available from | Tag |
|---|---|---|
| exception groups and `except*` | 3.11 | `ESTABLISHED` |
| `add_note` on exceptions | 3.11 | `ESTABLISHED` |
| `Self` | 3.11 | `ESTABLISHED` |
| `assert_never`, `Never` | 3.11 | `ESTABLISHED` |
| native generic syntax (PEP 695) | 3.12 | `ESTABLISHED` |
| deferred annotations by default | 3.14 | `VERSION-DEPENDENT` |

`ESTABLISHED` — the floor of 3.11 chosen in [meta/OPEN] is exactly the point at which the
whole diagnostic vocabulary is available without a backport.

## Runtime enforcement

`ESTABLISHED` — pydantic v2 performs validation in a compiled core and reports structured,
per-field errors, which map directly onto the diagnostic envelope's expected/actual/value
fields. Its validation is ordinary code and therefore survives optimized bytecode.

`VERSION-DEPENDENT` — v1 and v2 differ in API and in error shape. Mixing them in one
codebase produces two incompatible error surfaces.

`OPEN` — design-by-contract libraries offering precondition and postcondition decorators
exist and are usable, but no single one is established enough here to pin. Where a runtime
contract is needed, an explicit check in a validating constructor is the default.

---

## Sources

Claims above were verified against the official language and checker documentation and by
invoking the installed tools directly on 2026-08-18. Version numbers come from the tools
themselves, not from a changelog. Re-verify when `verified:` exceeds the decay window.
