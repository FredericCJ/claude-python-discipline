---
name: python-discipline
description: Apply the repository's Python engineering discipline: hexagonal architecture with a functional core, strict typing, deep error traceability, systematic testing, and machine-enforced rules. Use when writing or reviewing Python, deciding where code goes, designing errors or logging, writing tests, adding dependencies, or asking what rules apply. Do not use for changes unrelated to Python engineering.
---

# Python Engineering Discipline

## Locate the one corpus

At first use, find the repository root rather than assuming the current directory is it.
Use `<repo>/.agent` as the bundle root when `.agent/discipline/KERNEL.md` exists; this is
the installed layout. Otherwise use `<repo>` when `discipline/KERNEL.md` exists; this is
the discipline's source checkout. If neither exists, report that the discipline is not
installed and do not invent its rules.

All paths below are relative to `<bundle-root>`. Claude Code and Codex receive the same
skill and route into the same corpus; the host-specific skill directories are discovery
entry points, never independent copies of the rules.

Read `discipline/KERNEL.md` first. Do not read modules under `discipline/law/`, `fact/`,
`frame/`, or `ops/` speculatively. The kernel routes the task and every module declares
its measured token cost.

## Prime Directive

> **A failure must be machine-diagnosable and machine-repairable.** An agent meeting a
> defect determines *what broke, where, in which layer, against which contract, with which
> value* from the program's own output, and derives the fix without re-reading the codebase.

Deep error and exception traceability is the primary diagnostic channel. Least coupling,
with foreign coupling pushed to the edge, makes that record localizing. When a rule is
unclear, choose the reading that leaves a failure easier to diagnose unaided.

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

Read only what the task needs.

| Task involves | Read below `<bundle-root>` |
|---|---|
| module layout, ports, adapters, import errors, coupling | `discipline/law/ARCH.md` |
| type hints, `Any`, `Protocol`, generics, a checker complaint | `discipline/law/TYPE.md` + `discipline/fact/py-typing.md` |
| raising, catching, result unions, validation, error taxonomy | `discipline/law/ERR.md` + `discipline/fact/py-errors.md` |
| tracebacks, error codes, logging, correlation, diagnosis | `discipline/law/DIAG.md` + `discipline/fact/py-logging.md` |
| writing files, deleting, state machines, locks, clocks, determinism | `discipline/law/EFCT.md` |
| writing tests, fixtures, properties, fault injection, mutation | `discipline/law/TEST.md` + `discipline/fact/py-testing.md` |
| public surface, CLI, structured output, versioning, migrations | `discipline/law/API.md` |
| adding a dependency, lockfiles, generated files | `discipline/law/DEP.md` |
| what to do first, definition of done, decision records | `discipline/law/FLOW.md` |
| choosing a paradigm, refactoring, legacy code, tradeoffs | `discipline/frame/architecture.md` |
| writing a spec, requirements, traceability, reusability | `discipline/frame/spec.md` |
| dispatching a subagent, choosing tier and effort | `discipline/ops/ALLOC.md` |
| coordinating several agents, team mechanics | `discipline/ops/teams.md` |
| a term used two ways | `discipline/meta/GLOSSARY.md` |
| why something was decided, or two sources disagree | `discipline/meta/CONFLICTS.md` |
| authoring or editing a rule | `discipline/meta/SCHEMA.md` |

For a typo, comment, or rename that changes no contract, read nothing further. Grep
`discipline/INDEX.md` for a rule id or query `discipline/rules.json`, then open only the
owning module.

Prefer the navigator to speculative reading:

```bash
python <bundle-root>/tools/nav.py context --file P --error E --task T
python <bundle-root>/tools/nav.py applies P
python <bundle-root>/tools/nav.py why ARCH-008
python <bundle-root>/tools/learn.py retrieve --file P --error E
```

Replace `<bundle-root>` with the path located above; it is a notation, not a shell variable.

## Precedence

Instructions the host loaded for the consuming repository beat this skill. Within the
discipline, `law/` beats dated tooling truth in `fact/`, which beats non-prescriptive
grounding in `frame/`. More specific guidance beats more general guidance.

## Applying it to a project

`enforce/templates/pyproject.toml` and `enforce/importlinter.toml` below the bundle root are
the canonical tool configuration. `enforce/checks/` holds AST checks for rules no linter
covers, and `enforce/ENFORCEMENT.md` maps every rule to its deciding mechanism.
