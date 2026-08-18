---
id: meta/KERNEL
kind: meta
title: Discipline Kernel
tokens: 1532
load_when: ["python", "discipline", "how should i", "what are the rules"]
decay: none
---

# Discipline Kernel

Always loaded. ~1,800 tokens. Everything else is a jump away.

## Prime Directive

> **A failure must be machine-diagnosable and machine-repairable.** An agent meeting a
> defect determines *what broke, where, in which layer, against which contract, with which
> value* from the program's own output, and derives the fix without re-reading the codebase.

Two commitments serve it, and are not matters of taste:

- **Deep error and exception traceability** is the primary diagnostic channel. Error chains
  are the machine-readable record, not hygiene.
- **Least coupling, all foreign coupling pushed to the very edge**, is what makes that
  record *localizing*: with a pure core and every dependency behind one swappable port, a
  fault's origin follows from its layer. Coupling turns a precise error into a search.

When a rule's application is unclear, pick the reading that leaves a failure easier to
diagnose unaided.

## Authoring axiom

> **If something can be mechanically verified, it SHALL be.**

Rules ship with the mechanism that decides them. `[ADVISORY]` means no mechanism was found,
carries a written justification, and counts as a defect. **A rule nothing checks is not
binding in practice, whatever its tag claims.**

## Always true

1. Dependencies point inward; the domain imports nothing that can perform I/O. `ARCH-001/002`
2. A foreign dependency is imported in exactly one adapter. `ARCH-004`
3. Effects are parameters, never reached for. `ARCH-005`, `EFCT-002`
4. Every port has real + fake + faulty adapters and one shared contract suite. `ARCH-007/008/009`
5. Two error channels only: typed results for contract outcomes, raised for the exceptional. `ERR-001`
6. Result unions are exhaustively narrowed to `Never`. `ERR-002`
7. A layer produces only its own error family. `ERR-004`
8. Every custom error carries a stable code and structured attributes. `DIAG-002/003`
9. Every cross-layer re-raise chains explicitly; nothing is swallowed. `DIAG-005/008`
10. Each exception is logged once, at its handling boundary. `DIAG-010`
11. No `Any` in the domain; two strict checkers, both pinned. `TYPE-001/002`
12. Parse at the boundary; assertions are never validation. `ERR-011/012`
13. Destructive work plans before it applies. `EFCT-005`
14. Every test module declares its oracle. `TEST-004`
15. Every check has a proof-of-failure companion. `TEST-015`, `FLOW-007`

## Router

Load only what the task needs. Match on what you actually have in hand — an error message,
an API name, a task verb.

| Task involves | Load |
|---|---|
| module layout, ports, adapters, import errors, coupling | `law/ARCH` |
| type hints, `Any`, `Protocol`, generics, a checker complaint | `law/TYPE` + `fact/py-typing` |
| raising, catching, result unions, validation, error taxonomy | `law/ERR` + `fact/py-errors` |
| tracebacks, error codes, logging, correlation, diagnosis | `law/DIAG` + `fact/py-logging` |
| writing files, deleting, state machines, locks, clocks, determinism | `law/EFCT` |
| writing tests, fixtures, properties, fault injection, mutation | `law/TEST` + `fact/py-testing` |
| public surface, CLI, structured output, versioning, migrations | `law/API` |
| adding a dependency, lockfiles, generated files | `law/DEP` |
| what to do first, definition of done, decision records | `law/FLOW` |
| choosing a paradigm, refactoring, legacy code, tradeoffs | `frame/architecture` |
| writing a spec, requirements, traceability, reusability | `frame/spec` |
| dispatching a subagent, choosing tier and effort | `ops/ALLOC` |
| a term used two ways — `coverage`, `atomic`, double names | `meta/GLOSSARY` |
| "why was this decided?", two sources disagree | `meta/CONFLICTS` |
| authoring or editing a rule | `meta/SCHEMA` |

**Negative routing.** A typo fix, a comment, a rename that changes no contract, a
docstring: load nothing further. Loading a module you do not need costs the task budget it
was written to protect.

Grep `INDEX.md` for a rule id, or `jq` over `rules.json`; then open only the owning module.
Each module's front-matter carries a measured `tokens:` count — budget before you read.

## Precedence

1. The consuming project's own `CLAUDE.md`.
2. `law/` — the binding rules.
3. `fact/` — dated ecosystem truth. Facts constrain *how* a rule is satisfied; they never
   override *what* it requires.
4. `frame/` — grounding. Never prescriptive; informs judgment where no rule applies.

More specific beats more general. `law/` states capability requirements and never pins a
version; every pin lives in `fact/` with a `verified:` date, so rules outlive their tools.
Contradictions between the source documents are resolved once in `meta/CONFLICTS`, not
re-argued per task.

## Genres

`law/` rules and mechanisms (binding) · `fact/` sourced, dated tooling truth ·
`frame/` vocabulary and reasoning scaffolds · `ops/` agent dispatch ·
`meta/` this file, the format spec, the ledgers.

## Done means

Gates pass — format, lint, both checkers, import contracts, custom checks, and the unit,
contract, integration and fault suites. New behaviour arrives with its contract, its tests
and, for a port, its three adapters and both suites. For any change touching an error path,
**the envelope was inspected**: code, layer, expected, actual, remediation — enough to
locate and fix the fault without reading the source. Report what was verified, what was
skipped and why, and any deviation by rule id. A failing test is reported as failing.

Full definition: `law/FLOW`.
