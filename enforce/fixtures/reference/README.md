# The reference package

A stale-file pruner, about 700 lines, written to the discipline. It exists for
three jobs, in order of how much each is worth:

1. **The positive case for the fitness tests.** `fitness:test_port_triad`,
   `test_contract_suite_per_adapter`, `test_layers_populated` and the rest need a
   conformant tree to run against. This is it. Their proof-of-failure cases come
   from `broken_copy`, which takes this tree and breaks exactly one thing.
2. **A target for the tools that had none.** `mypy --strict`, `pyright` and
   `lint-imports` decide nineteen `external` rules and, before this package
   existed, ran nowhere in this repository. The import contracts in particular
   named a placeholder package `mypkg` that does not exist.
3. **A worked example.** Every rule cited below is cited in the source, at the
   line that obeys it.

It is **not** installed, **not** shipped as a runnable tool, and **not** imported
by anything in `tools/`. It is read, scanned and executed by tests.

## What it is

```
src/refpkg/
  domain/     model.py  plan.py  errors.py     pure; imports nothing I/O-capable
  ports/      clock.py  files.py  errors.py    Protocols, and the failures they publish
  app/        prune.py  errors.py              orchestration; every effect a parameter
  adapters/   clock/{real,fake,faulty}.py      one foreign dependency each
              files/{real,fake,faulty}.py
              faults.py                        fault injection as data
  shell/      composition.py  envelope.py  cli.py
tests/        unit/ contract/ integration/ fault/ property/
```

Given a directory, a maximum age and a number of newest files to spare, it decides
which files are stale and — only if asked — deletes them.

That domain was chosen because it is small and still forces the hard parts: a
clock and a filesystem are two genuinely different ports, and deletion is
irreversible, so plan-then-apply is not a ceremony here but the only safe design.

## What each part demonstrates

| Rule | Where |
|---|---|
| `ARCH-001` dependencies point inward | `importlinter.toml`, contract 1 — checked, not asserted |
| `ARCH-002` the domain imports nothing I/O-capable | contracts 2 and 3; `domain/` imports `dataclasses` and its own siblings |
| `ARCH-003` adapters are independent | contract 4 |
| `ARCH-004` one importer per foreign dependency | contracts 5 and 6: `time` in `clock/real.py`, `pathlib` in `files/real.py` |
| `ARCH-005` effects are named in the signature | `app/prune.py` — both ports are parameters |
| `ARCH-007` ports are Protocols with a stated contract | `ports/clock.py`, `ports/files.py` docstrings |
| `ARCH-008` the real/fake/faulty triad | `adapters/clock/`, `adapters/files/` — three each, unconditionally |
| `ARCH-009` one contract suite per adapter | `tests/contract/` — parameterised over all three, faulty in healthy mode |
| `ARCH-010` a port earns its place | the **Justification** paragraph opening each port |
| `ARCH-011` one composition root | `shell/composition.py`; contract 7 proves the app cannot reach an adapter |
| `ERR-001` two channels only | refusals are returned; the exceptional is raised |
| `ERR-002` unions narrowed to `Never` | `domain/plan.py::narrow` |
| `ERR-004` a layer produces its own family | three families; `shell/envelope.py::layer_of` derives the layer *from* them |
| `ERR-011` parse at the boundary | `Instant.parse`, `Policy.parse` |
| `DIAG-001` every escaping error becomes an envelope | `shell/envelope.py`, validated against `enforce/schema/diagnostic.schema.json` |
| `DIAG-005` cross-layer re-raises chain | `app/prune.py` raises `PruneInterrupted` **from** the port error |
| `EFCT-005` destructive work plans first | `--apply` is opt-in; the default changes nothing |
| `EFCT-006` a dry run is the pipeline truncated | `survey` then stop, or `survey` then `apply` — one implementation |
| `EFCT-009` what is not guaranteed is stated | `ports/files.py` says `delete` is not atomic across calls; `PruneInterrupted` reports how far it got |
| `TEST-002` every layer populated | `tests/{unit,contract,integration,fault,property}` |
| `TEST-004` every module declares its oracle | the **Oracle** line opening each test module |
| `TEST-009` fault injection is data | `adapters/faults.py::FaultSchedule` |
| `TYPE-005` constrained types parse | `Instant`, `Policy` |
| `TYPE-006` closed sets are enumerations | `ports/errors.py::StoreOperation` |
| `TYPE-007` domain values are frozen and slotted | every dataclass in `domain/` |

## Three things it found while being written

Worth recording, because they are the argument for building it at all.

**The import contracts had never been readable.** `enforce/importlinter.toml` used
a `[importlinter]` section where the tool requires `[tool.importlinter]`. It
parsed as nothing, so `lint-imports` reported "Could not read any configuration"
and the eight rules it decides had been marked `external` — *a configured tool
settles it* — while nothing was ever settled. Running it once, against real code,
was all it took.

**A port's error type belongs to the port.** The error families started under
`adapters/`, and `ARCH-001` immediately caught `app/prune.py` importing them: the
app must catch an adapter failure to report an interrupted apply. The import was
the symptom; the cause was that a failure mode had been filed as an
implementation detail when `ARCH-007` says a port states its error modes. They
now live in `ports/errors.py`, and the app catches a contract's failure without
knowing that adapters exist.

**`ARCH-004` cannot bind the composition root.** The contract forbidding `time`
outside the clock adapter failed on `shell/composition.py`, which reaches `time`
transitively because wiring an adapter means importing it. A rule forbidding that
would make `ARCH-011` impossible to satisfy at the same time. The contract now
exempts the composition root, and says why.

## Running it

```bash
python -m pytest enforce/fixtures/reference/tests -q
python -m mypy --strict enforce/fixtures/reference/src/refpkg
lint-imports --config enforce/fixtures/reference/importlinter.toml   # needs src/ on PYTHONPATH
python -m ruff check enforce/fixtures/reference
```

## What it is not

- **Not evidence that the rules are right.** It was written to satisfy them, so
  it cannot be surprised by them. That is what validating against an unrelated
  codebase is for.
- **Not exhaustive.** It has no concurrency, no persistence beyond a directory,
  no schema migration and no network, so `EFCT-013`–`015`, `API-012` and
  `DIAG-013` still have no positive case here.
- **Not a template to copy.** Copy `enforce/templates/pyproject.toml` and
  `enforce/importlinter.toml`. This package is for reading.
