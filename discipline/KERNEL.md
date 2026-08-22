---
id: meta/KERNEL
kind: meta
title: Discipline Kernel
tokens: 1982
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

## Scope

One installation governs exactly one repository: either a complete application or one
independently developed component. A component owns its contracts and local behavior, not
its counterparts, parent repository or whole-application integration. See [meta/SCOPE].

## Always true

1. Source dependencies point toward policy; every production file has one role. `ARCH-001/018`
2. One adapter boundary owns each technology; the local shell wires it. `ARCH-011/020`
3. Application policy invokes injected ports, never concrete adapters. `ARCH-005/019`, `EFCT-001`
4. Boundary substitutes share one term-traced contract and scheduled-fault evidence. `ARCH-024/025`, `TEST-020`
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
16. Every element carries a documentation comment, generated or not. `DOC-001/003`

## Router

Load only what the task needs. Match on what you actually have in hand — an error message,
an API name, a task verb.

| Task involves | Load |
|---|---|
| module layout, ports, adapters, import errors, coupling | `law/ARCH` + `law/ARCH-PORTS` |
| type hints, `Any`, `Protocol`, generics, a checker complaint | `law/TYPE` + `fact/py-typing` |
| raising, catching, result unions, validation, error taxonomy | `law/ERR` + `fact/py-errors` |
| tracebacks, error codes, logging, correlation, diagnosis | `law/DIAG` + `fact/py-logging` |
| writing files, deleting, state machines, locks, clocks, determinism | `law/EFCT` |
| capabilities, lifecycle, resources, budgets, shutdown, recovery | `law/OPS` |
| security, trust boundaries, sensitive data, adversarial review | `law/SEC` |
| writing tests, fixtures, properties, fault injection, mutation | `law/TEST` + `fact/py-testing` |
| public surface, CLI, structured output, versioning, migrations | `law/API` |
| adding a dependency, lockfiles, generated files | `law/DEP` |
| docstrings, documentation comments, Doxygen | `law/DOC` + `fact/doxygen` |
| what to do first, definition of done, decision records | `law/FLOW` |
| choosing a paradigm, refactoring, legacy code, tradeoffs | `frame/architecture` |
| writing a spec, requirements, traceability, reusability | `frame/spec` |
| dispatching a subagent, choosing tier and effort | `ops/ALLOC` |
| a term used two ways — `coverage`, `atomic`, double names | `meta/GLOSSARY` |
| "why was this decided?", two sources disagree | `meta/CONFLICTS` |
| application vs component, parent repository, scope boundary | `meta/SCOPE` |
| authoring or editing a rule | `meta/SCHEMA` |

**Negative routing.** A typo fix, a comment, a rename that changes no contract, a
docstring: load nothing further. Loading a module you do not need costs the task budget it
was written to protect.

## Navigating

Prefer the navigator to reading speculatively.

```
nav.py diagnose --envelope E | --error TEXT  what broke, which rule, what to do
nav.py context --file P --error E --task T   what to read, and the token cost
nav.py applies PATH                          which rules govern this file
nav.py rule ID / why ID / neighbors ID       one rule, its shape, its neighbours
nav.py path A B / budget IDS                 how two relate; what a set costs
```

**`diagnose` when something failed; `context` before you write.** The first returns the
governing rules' own words — statement, rationale, the deciding command — for tens of
tokens; the second returns a reading plan for thousands. Measured over twelve real
defects: 57 against 4,994.

If the tool cannot run: grep `INDEX.md` for a rule id, or `jq` over `rules.json`. Every
module's front-matter carries a measured `tokens:` count — budget before you read.

## What this repository has learned

`learn.py retrieve --file P --error E` returns what earlier sessions found here. Entries
carry a confidence and go stale — weigh them, do not obey them.

Before reporting done: `learn.py record --kind ... --claim ... --action ... --trigger ...`.
A finding that the discipline itself is wrong is `--scope discipline`, harvested upstream
rather than worked around. Full rules: `law/LEARN`.

## Genres, in precedence order

1. The consuming project's own `CLAUDE.md`.
2. `law/` — binding rules and the mechanisms that decide them.
3. `fact/` — sourced, dated tooling truth. Facts constrain *how* a rule is satisfied;
   they never override *what* it requires.
4. `frame/` — vocabulary and reasoning scaffolds. Never prescriptive.

Beside these: `ops/` agent dispatch · `meta/` this file, the format spec, the ledgers.
More specific beats more general. Contradictions are resolved once in `meta/CONFLICTS`.

## Done means

Gates pass — format, lint, both checkers, import contracts, custom checks, and the unit,
contract, integration and fault suites. New behaviour arrives with its contract, its tests
and, for a port, its registered implementations, shared suite and fault evidence. For any
change touching an error path,
**the envelope was inspected**: code, layer, expected, actual, remediation — enough to
locate and fix the fault without reading the source. Report what was verified, what was
skipped and why, and any deviation by rule id. A failing test is reported as failing.

Full definition: `law/FLOW`.
