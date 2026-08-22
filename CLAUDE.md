# Python Engineering Discipline

**Read `discipline/KERNEL.md` first. It is ~1,500 tokens and it routes everything else.**

Do not read the modules under `discipline/law/`, `fact/`, `frame/` or `ops/` speculatively.
The kernel's router says which one a task needs; each module's front-matter carries a
measured `tokens:` count so you can budget before opening it.

The governing thesis, in one line: **a failure must be machine-diagnosable and
machine-repairable** — an agent meeting a defect should be able to name what broke, where,
against which contract, from the program's own output. Deep error traceability and least
coupling exist to serve that, and the authoring axiom is that anything mechanically
verifiable shall be mechanically verified.

## Finding things

Prefer the navigator to reading speculatively:

```bash
python tools/nav.py context --file P --error E --task T   # what to read, and its cost
python tools/nav.py applies src/pkg/adapters/fs.py        # which rules govern this file
python tools/nav.py why ARCH-008                          # which decision shaped it
python tools/learn.py retrieve --file P --error E         # what earlier sessions found
```

Fallbacks and ledgers:

- `discipline/INDEX.md` — one line per rule: id, force, mechanism, title. Grep it, then
  open only the owning module.
- `discipline/rules.json` — the same, for `jq`. `discipline/graph.json` — the rule graph.
- `enforce/ENFORCEMENT.md` — every rule against the mechanism that decides it, and the
  mechanisms not yet built.
- `learning/INDEX.md` — what this repository has learned; `learning/calibration.md` — how
  well that is working.

Every element of the code carries a documentation comment, in Doxygen form —
docstrings where Python has a slot, `##` blocks for module constants, class attributes,
dataclass fields and enum members. They are required whether or not documentation is ever
generated. See `discipline/law/DOC.md`; the engine's own quirks are in
`discipline/fact/doxygen.md`.

Rule ids (`ARCH-002`, `DIAG-005`) are stable and citable. Use them in review comments and
commit messages.

## Working on this repository

The corpus validates itself. After any edit under `discipline/`:

```bash
python tools/build_index.py         # refresh tokens:, INDEX.md, rules.json, ENFORCEMENT.md
python tools/build_graph.py         # then the graph, which reads those token counts
python tools/build_skill_mirror.py  # then both agent-native skill entry points
python tools/validate.py            # must exit 0
python -m pytest -q
```

Order matters: `build_index` rewrites the `tokens:` field that `build_graph` reads, and the
skill builder copies the one authored skill under `skills/` into both `.claude/skills/`
and `.agents/skills/`. Omitting it leaves a stale host entry point that passes every command
above and fails the gate's fifth step — this sequence was missing it until a pass over the
claims in this file ran them.

The whole gate is eleven steps, defined once in `tools/gate.py::GATE`, and `python
tools/gate.py` runs all of them and names the ones that failed. `tools/release.py` runs the
same tuple and refuses to build an archive from a tree that fails it.

Before reporting done, record what the session learned — `python tools/learn.py record
--kind ... --claim ... --action ... --trigger ...`, or nothing if there was nothing. The
rules for that are in `discipline/law/LEARN.md`.

`tools/validate.py` enforces `discipline/meta/SCHEMA.md` — the file format, the rule
grammar, budget ceilings, reference integrity and the glossary. Read SCHEMA.md before
authoring a rule. Every check in it has a proof-of-failure test in `tools/test_validate.py`;
if you add a check, add its companion.

`discipline/INDEX.md`, `discipline/rules.json` and `enforce/ENFORCEMENT.md` are generated.
Edit the source module and rebuild.

The Python environment is the conda env named `claude`. Note that a bare `python` resolves
to the miniforge base environment, which has no pytest and no jsonschema — a gate run
against it looks like it passed and decided nothing.

## Maintenance agents

Nine subject-matter agents in `.claude/agents/` maintain the machinery around the
discipline: `graph-keeper` (derived layer), `gate-warden` (the eleven-step gate),
`conda-steward` (environment and lock), `mechanism-builder` (unbuilt checks and the V080
ratchet), `release-engineer` and `adoption-tester` (build and round-trip the archive),
`doc-verifier` (are the claims true), `learning-steward` (the learning loop) and
`fact-refresher` (dated `fact/` and `ops/` claims).

`MAINTENANCE.md` carries the dispatch table, the seams between them, the release train and
the restrictions that hold for all of them. They maintain this repository; they are not part
of the discipline and are not vendored.

## `sources/`

The eleven original documents, superseded. They contain ~35 known contradictions and ~130
references to files that do not exist. **Do not read them as guidance.** Where their
material went is recorded in `discipline/meta/PROVENANCE.md`; why each conflict resolved
the way it did is in `discipline/meta/CONFLICTS.md`.
