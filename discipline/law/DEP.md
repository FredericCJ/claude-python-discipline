---
id: law/DEP
kind: law
title: Dependencies and Generated Artefacts
tokens: 2111
load_when:
  - "add a dependency"
  - "third party library"
  - "lockfile"
  - "environment"
  - "code generation"
  - "generated file"
  - "vendoring"
applies_to: ["**/*.py", "pyproject.toml"]
grounds_on: ["fact/py-testing"]
requires: ["law/ARCH"]
decay: none
python: ">=3.11"
---

# Dependencies and Generated Artefacts

Two ways foreign material enters a codebase: it is installed, or it is produced. Both are
governed here, and for the same reason — each one, unmanaged, makes a failure attributable
to something outside the code an agent is reading.

---

## Taking a dependency

### DEP-001 · The domain depends on the standard library only  [BINDING] [auto:import-linter]
Domain modules MUST NOT import a third-party package. Third-party code is reachable only
from adapters.
- **Why** A domain failure that can originate in a vendor's code is a domain failure that
  localizes nothing, and the layer field stops meaning what it claims.
- **Check** `lint-imports` contract `domain-is-pure`
- **See** [law/ARCH]

### DEP-002 · A dependency is judged by its architectural position  [BINDING] [fitness:test_dependency_position]
A dependency confined behind one adapter is cheap; one whose types appear across the
codebase is expensive regardless of its quality. Every dependency MUST be recorded with the
adapter that owns it.
- **Why** Replaceability is a function of position, not of the library's merits, and the
  position is the only part that can be checked.
- **Check** `pytest enforce/fitness/test_deps.py::test_dependency_position`

### DEP-003 · An adapter owns its dependency's failure modes  [ADVISORY]
The adapter owning a dependency MUST state which faults it can produce and translate them
into the infrastructure error family.
- **Why** An untranslated vendor exception crossing a layer boundary carries the vendor's
  vocabulary into a diagnosis written in ours.
- **No mechanism** `test_fault_catalogue` claimed this rule and asserts a faulty
  adapter file exists for every port. The rule's two obligations -- that the adapter
  STATES which faults it can produce, and that it TRANSLATES them into the
  infrastructure error family -- are both unchecked. The second is mechanizable: an
  adapter letting a vendor exception cross its own boundary is visible to an AST check,
  and [ERR-004] is the neighbouring rule that would host it.
- **See** [law/ERR]

### DEP-004 · Do not reimplement a solved, specified problem  [ADVISORY]
Parsers, cryptography, date arithmetic and schema validation SHOULD use an established
implementation rather than a local one.
- **No mechanism** Recognizing that a hand-rolled routine reimplements a standard is a
  judgment about intent that no check can make from the code.
- **Why** A local reimplementation carries defects nobody else has already found, and no
  shared vocabulary for describing them when they surface.

---

## Reproducibility

### DEP-005 · The environment is locked by content hash  [BINDING] [fitness:test_environment_locked]
Every dependency MUST be pinned by content hash in a lockfile committed to the repository.
- **Why** A build that resolves differently on two machines produces failures that cannot
  be reproduced, and reproduction is the first step of diagnosis.
- **Check** `pytest enforce/fitness/test_deps.py::test_environment_locked`

### DEP-006 · A command verifies the environment matches the lock  [BINDING] [fitness:test_environment_locked]
The project MUST provide a check that reports drift between the installed environment and
the lockfile, and it MUST run before the test suite in continuous integration.
- **Why** Drift discovered by a mysterious test failure costs far more than drift reported
  as drift.
- **Check** `pytest enforce/fitness/test_deps.py::test_environment_locked`

---

## A vendored discipline

### DEP-012 · A vendored discipline is announced, not merely present  [BINDING] [auto:integrate]
A repository that vendors this discipline MUST carry a pointer to it in the top-level agent
configuration its sessions actually read.
- **Why** Copying the files does not make them load. A discipline nobody is told about is
  one every session ignores, which costs the vendoring and returns nothing.
- **Check** `python .agent/tools/integrate.py --check`

### DEP-013 · The announcement is generated, never hand-edited  [BINDING] [auto:integrate] [fitness:test_an_existing_block_is_replaced_not_duplicated]
The pointer MUST live inside the managed markers, and everything outside them MUST be left
untouched by the tool. Hand-editing inside the block is prohibited; it is overwritten on
the next update.
- **Why** A clear boundary is what lets an update replace the pointer without touching the
  project's own configuration, and lets the project write freely without fear of losing it.
- **Check** `python .agent/tools/integrate.py --check` · `pytest tools/test_integrate.py`
- **See** [DEP-007]

### DEP-014 · Configuration is changed by plan, then apply  [BINDING] [fitness:test_a_dry_run_writes_nothing]
A tool that edits files the project owns MUST be able to show its complete plan without
writing, and the preview MUST be the same code path truncated rather than a second
implementation that predicts it.
- **Why** This is [EFCT-005] applied to the discipline's own installer: a preview produced
  by different code is a preview that can be wrong in exactly the case that matters.
- **Check** `pytest tools/test_integrate.py::test_a_dry_run_writes_nothing`
- **See** [law/EFCT]

---

## Generated artefacts

A file is generated if it is *produced from a model by a generator*, wherever it lives.
Directory location does not decide it; provenance does.

### DEP-007 · Generated files carry a provenance header  [BINDING] [check:generated_provenance]
Every generated file MUST begin with a header naming the generator, its version, a digest
of the model it was produced from, and a do-not-edit marker.
- **Why** Without provenance an agent cannot tell an artefact it may regenerate from a
  source it must not overwrite, and will eventually destroy one of them.
- **Check** `python -m checks.generated_provenance`

### DEP-008 · Generated output contains no timestamp  [BINDING] [check:generated_provenance]
Provenance headers MUST NOT include a wall-clock time.
- **Why** A timestamp makes every regeneration a diff, which trains reviewers to ignore
  generated diffs, which is how a real change gets waved through.
- **Check** `python -m checks.generated_provenance`

### DEP-009 · Regeneration is idempotent and byte-stable  [BINDING] [fitness:test_regeneration_stable]
Regenerating from an unchanged model MUST produce byte-identical output, on every machine.
- **Why** Byte-stability is what makes a regenerate-and-compare gate able to distinguish a
  real divergence from noise.
- **Check** `pytest enforce/fitness/test_generated.py::test_regeneration_stable`

### DEP-010 · Drift between model and output fails the build  [BINDING] [fitness:test_regeneration_stable]
Continuous integration MUST regenerate every generated artefact and fail if the result
differs from what is committed.
- **Why** Committed output that silently diverges from its model is a lie that every
  subsequent reader inherits.
- **Check** `pytest enforce/fitness/test_generated.py::test_regeneration_stable`

### DEP-011 · Generated output is committed  [BINDING] [fitness:test_regeneration_stable]
Generated artefacts MUST be committed to the repository rather than produced only at build
time.
- **Why** A change that is invisible in review is a change nobody reviewed; committing the
  output is what makes the generator's behaviour auditable.
- **Check** `pytest enforce/fitness/test_generated.py::test_regeneration_stable`
