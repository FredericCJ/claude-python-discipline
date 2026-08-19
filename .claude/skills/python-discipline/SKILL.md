---
name: python-discipline
description: Load the Python engineering discipline — hexagonal architecture with a functional core, strict typing, deep error traceability, and systematic testing, all machine-enforced. Use when writing or reviewing Python, deciding where code goes, designing error handling or logging, writing tests, adding a dependency, or asking "what are the rules here". Routes to one of 23 modules rather than loading everything.
---

# Python Engineering Discipline

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

Rules ship with the mechanism that decides them. A rule nothing checks is not binding in
practice, whatever its tag claims.

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

Read only what the task needs. Files are under `references/`.

| Task involves | Read |
|---|---|
| module layout, ports, adapters, import errors, coupling | `references/law/ARCH.md` |
| type hints, `Any`, `Protocol`, generics, a checker complaint | `references/law/TYPE.md` + `references/fact/py-typing.md` |
| raising, catching, result unions, validation, error taxonomy | `references/law/ERR.md` + `references/fact/py-errors.md` |
| tracebacks, error codes, logging, correlation, diagnosis | `references/law/DIAG.md` + `references/fact/py-logging.md` |
| writing files, deleting, state machines, locks, clocks, determinism | `references/law/EFCT.md` |
| writing tests, fixtures, properties, fault injection, mutation | `references/law/TEST.md` + `references/fact/py-testing.md` |
| public surface, CLI, structured output, versioning, migrations | `references/law/API.md` |
| adding a dependency, lockfiles, generated files | `references/law/DEP.md` |
| what to do first, definition of done, decision records | `references/law/FLOW.md` |
| choosing a paradigm, refactoring, legacy code, tradeoffs | `references/frame/architecture.md` |
| writing a spec, requirements, traceability, reusability | `references/frame/spec.md` |
| dispatching a subagent, choosing tier and effort | `references/ops/ALLOC.md` |
| coordinating several agents, team mechanics | `references/ops/teams.md` |
| a term used two ways — `coverage`, `atomic`, double names | `references/meta/GLOSSARY.md` |
| "why was this decided?", two sources disagree | `references/meta/CONFLICTS.md` |
| authoring or editing a rule | `references/meta/SCHEMA.md` |

**Negative routing.** A typo fix, a comment, a rename that changes no contract, a
docstring: read nothing further.

Grep `references/INDEX.md` for a rule id, or `jq` over `references/rules.json`, then open
only the owning module. Each module's front-matter carries a measured `tokens:` count.

## Precedence

The consuming project's own `CLAUDE.md` beats this. Then `law/` (binding), then `fact/`
(dated tooling truth — constrains *how* a rule is satisfied, never *what* it requires),
then `frame/` (grounding, never prescriptive). More specific beats more general.

## Applying it to a project

`enforce/templates/pyproject.toml` and `enforce/importlinter.toml` are the canonical tool
configuration; `enforce/checks/` holds the AST checks for rules no linter covers. Copy them
in and replace the placeholder package name. `enforce/ENFORCEMENT.md` maps every rule to
the mechanism that decides it, and lists the mechanisms not yet built.
