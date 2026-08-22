---
id: meta/GLOSSARY
kind: meta
title: Glossary
tokens: 1308
load_when: ["terminology", "what does this mean", "define", "ambiguous term"]
decay: none
---

# Glossary

One meaning per term, across the whole corpus.

Terms marked `[BARE-BANNED]` may not be used unqualified anywhere outside this file.
Each was used in incompatible senses by the source documents, and `tools/validate.py`
rejects the bare form. The qualified alternatives are listed under each entry.

---

## Banned in bare form

### coverage [BARE-BANNED]

The sources used this word in at least three incompatible senses. Say which:

- **line coverage** — lines executed at least once. Weak; cannot distinguish "this ran"
  from "this was verified".
- **branch coverage** — both outcomes of each decision taken.
- **obligation coverage** — every stated test obligation has at least one asserting test.
  This is the sense the discipline gates on.
- **artifact coverage** — every port has a contract suite, every rendering rule has a
  golden file. Enforced by fitness tests rather than by a percentage.

- **coverage.py** — the measurement tool. A proper noun, not a sense of the word.

A bare percentage target is a Goodhart trap and is never a gate on its own.

### atomic [BARE-BANNED]

One source assumed operations were atomic; another declared the bare word a documentation
defect. Say what is guaranteed and against what:

- **single-file-rename atomic** — a same-volume rename replaces one file's contents
  indivisibly with respect to other processes.
- **journal-recoverable** — a multi-effect change is not indivisible, but an interrupted
  run is detectable and completable from its journal.
- **transactionally atomic** — all-or-nothing across effects, with rollback. Rare outside
  a database, and never assumed of a filesystem.

- **atomic reusability** — an unrelated sense, from the specification vocabulary: a unit
  works standalone given its declared dependencies. Nothing to do with indivisibility.

A contract that says only "atomic" is a defect.

---

## Adapter and double vocabulary

The corpus carried two clashing taxonomies. **`real` / `fake` / `faulty` is the adapter
vocabulary**; Meszaros' terms are mapped onto it and not used on their own.

| Term | Meaning here | Meszaros equivalent |
|---|---|---|
| **real adapter** | talks to the actual external technology | — |
| **fake adapter** | a working in-memory implementation of the same contract | fake |
| **faulty adapter** | a real-shaped adapter driven by a fault schedule; in *healthy mode* it must pass the port's contract suite unchanged | — (no equivalent) |
| **spy** | records calls; permitted only inside fault tests, never a contract-tested adapter | spy |
| **stub / dummy / mock** | not used; a fake implementing the contract is used instead | stub, dummy, mock |

### port

A typed boundary the core may cross. Its repository declares structural or nominal form,
registers a real implementation plus controllable and scheduled-fault test capabilities,
and runs one term-traced contract suite across every registered implementation.

### seam

A place where behaviour can be substituted without editing the code around it. Ports are
the deliberate seams; a seam that exists by accident is a coupling defect.

---

## Layer vocabulary

| Term | Meaning |
|---|---|
| **domain** | pure, total or `Result`-returning logic. No I/O, no clock, no randomness, no adapter imports. |
| **app** | orchestration over the domain; still no direct I/O. |
| **adapter** | the only place a foreign dependency may be imported. |
| **shell** | process entry, argument parsing, exit codes, effect execution. |

**functional core / imperative shell** — the arrangement in which domain and app are pure
and every effect is pushed outward into shell and adapters.

---

## Diagnostic vocabulary

### diagnostic envelope

The serialized, schema-validated record every escaping error produces. It is the artifact
an agent reads to localize a fault without opening the source.

### error code

A stable, namespaced, greppable identifier carried as an attribute on an exception or
result variant — never embedded only in prose. Part of the public contract.

### fault schedule

Fault injection expressed as data (port, operation, occurrence, fault kind) rather than as
a bespoke class, so a failing case can be serialized, replayed, and shrunk.

---

## Normative vocabulary

**binding**, **advisory**, **open** — see `meta/SCHEMA.md` section 3.2. Note that
`[BINDING]` grades *normative force*, whereas `ESTABLISHED` / `VERSION-DEPENDENT` /
`OPEN` grade *source authority* and appear only in `fact` and `ops` files. The two axes
are independent, and the epistemic scheme used for specifications
(`STATED` / `INFERRED` / `ASSUMED` / …) is a rule about authoring specs, not a tag for
this repository.
