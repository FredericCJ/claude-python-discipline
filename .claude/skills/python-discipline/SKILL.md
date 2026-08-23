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

## Governed unit

One installation governs exactly one repository containing either a complete application
or one independently developed component. For a component, its contracts and locally
owned behavior are in scope; counterpart repositories, parent wiring and whole-application
verification are not. Read `discipline/meta/SCOPE.md` when that boundary is relevant.

## Development environment

Use the development leg shipped beside this skill instead of assembling verifier tools on
the host. In a source checkout, Windows runs `<bundle-root>/dev/windows.cmd` and Linux runs
`sh <bundle-root>/dev/docker.sh`. In an installed repository those resolve to
`.agent/dev/windows.cmd` and `.agent/dev/docker.sh`.

The Windows leg requires only Conda on `PATH`; the Linux leg requires only Docker. With no
extra arguments each verifies the shared declaration and runs the appropriate source or
project gate. Append an explicit command for focused work. Do not silently install an
undeclared project dependency into the shared environment or image: project-specific
dependencies remain owned by the governed repository.

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
2. One adapter boundary owns each foreign technology; the local shell wires it. `ARCH-020`
3. Application policy invokes effects through injected ports, never concrete adapters. `ARCH-019`, `EFCT-001`
4. Boundary form is explicit; real, controllable, and scheduled-fault evidence shares one term-traced suite. `ARCH-024/025`, `TEST-020`
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
16. Every governed entity and local binding carries its semantic contract in the
    comment form assigned to that owner. `DOC-001/002/016`
17. Governed execution is narrated by logical operation, including branches, exits,
    translations, state transitions, and effect sequences. `DOC-017/018/019`
18. Doxygen is the sole structured engine; the project model owns scope, vocabulary,
    naming grammar, generated-name mappings, and inferable semantic properties.
    `DOC-015/022/023/024/025/029`

## Router

Read only what the task needs.

| Task involves | Read below `<bundle-root>` |
|---|---|
| module layout, ports, adapters, import errors, coupling | `discipline/law/ARCH.md` + `discipline/law/ARCH-PORTS.md` |
| type hints, `Any`, `Protocol`, generics, a checker complaint | `discipline/law/TYPE.md` + `discipline/fact/py-typing.md` |
| raising, catching, result unions, validation, error taxonomy | `discipline/law/ERR.md` + `discipline/fact/py-errors.md` |
| tracebacks, error codes, logging, correlation, diagnosis | `discipline/law/DIAG.md` + `discipline/fact/py-logging.md` |
| writing files, deleting, state machines, locks, clocks, determinism | `discipline/law/EFCT.md` |
| capabilities, lifecycle, resources, budgets, shutdown, recovery | `discipline/law/OPS.md` |
| security, trust boundaries, sensitive data, adversarial review | `discipline/law/SEC.md` |
| writing tests, fixtures, properties, fault injection, mutation | `discipline/law/TEST.md` + `discipline/fact/py-testing.md` |
| public surface, CLI, structured output, versioning, migrations | `discipline/law/API.md` |
| adding a dependency, lockfiles, generated files | `discipline/law/DEP.md` |
| comments, docstrings, local bindings, naming, Doxygen, documentation model | `discipline/law/DOC.md` + `discipline/law/DOC-COMMENTS.md` + `discipline/law/DOC-NAMING.md` + `discipline/frame/documentation.md` |
| what to do first, definition of done, decision records | `discipline/law/FLOW.md` |
| choosing a paradigm, refactoring, legacy code, tradeoffs | `discipline/frame/architecture.md` |
| writing a spec, requirements, traceability, reusability | `discipline/frame/spec.md` |
| dispatching a subagent, choosing tier and effort | `discipline/ops/ALLOC.md` |
| coordinating several agents, team mechanics | `discipline/ops/teams.md` |
| a term used two ways | `discipline/meta/GLOSSARY.md` |
| why something was decided, or two sources disagree | `discipline/meta/CONFLICTS.md` |
| application vs component, parent repository, scope boundary | `discipline/meta/SCOPE.md` |
| authoring or editing a rule | `discipline/meta/SCHEMA.md` |

For a typo, comment, or rename that changes no contract, read nothing further. Grep
`discipline/INDEX.md` for a rule id or query `discipline/rules.json`, then open only the
owning module.

Prefer the navigator to speculative reading:

```bash
python <bundle-root>/tools/nav.py context --file P --error E --task T
python <bundle-root>/tools/nav.py applies P
python <bundle-root>/tools/nav.py why ARCH-025
python <bundle-root>/tools/learn.py retrieve --file P --error E
```

Replace `<bundle-root>` with the path located above; it is a notation, not a shell variable.

## Precedence

Instructions the host loaded for the consuming repository beat this skill. Within the
discipline, `law/` beats dated tooling truth in `fact/`, which beats non-prescriptive
grounding in `frame/`. More specific guidance beats more general guidance.

## Applying it to a project

`enforce/templates/pyproject.toml`, `enforce/templates/documentation-model.json`,
`enforce/Doxyfile`, and `enforce/importlinter.toml` below the bundle root are the canonical
tool configuration. `enforce/checks/` holds AST checks for rules no linter covers, and
`enforce/ENFORCEMENT.md` maps every rule to its deciding mechanism.

For a v4 repository, preview the v5 structural migration before authoring comments:

```bash
python <bundle-root>/tools/migrate_v5.py --root .
python <bundle-root>/tools/migrate_v5.py --root . --apply
python -m checks src tests --root . --project pyproject.toml
```

The migrator selects Doxygen and creates only missing, mechanically derivable project
artifacts. It preserves existing artifacts and never invents semantic prose, vocabulary,
generated-code ownership, or naming rules; resolve every reported inventory item from the
actual implementation before accepting the migration.
