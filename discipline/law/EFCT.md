---
id: law/EFCT
kind: law
title: Effects, State and Time
tokens: 2362
load_when:
  - "write a file"
  - "mutation"
  - "state machine"
  - "transaction"
  - "rollback"
  - "dry run"
  - "concurrency"
  - "lock"
  - "clock"
  - "random"
  - "delete"
applies_to: ["**/*.py"]
grounds_on: ["fact/py-testing"]
requires: ["law/ARCH"]
decay: none
python: ">=3.11"
---

# Effects, State and Time

Everything that changes the world outside the process. The rules here exist because an
effect that is computed and performed in one pass leaves no artifact to diagnose from: on
interruption there is no record of what was intended, what was done, and what was not.

The governing shape is **validate, then plan, then apply**. A destructive operation is
never a single function that decides and acts.

---

## Explicit effects

### EFCT-001 · Foreign effects stay behind ports  [BINDING] [auto:import-linter]
Domain code MUST perform no effects. Application orchestration MAY invoke effects through
injected ports, but MUST NOT import a foreign API or perform its I/O directly. Adapters
perform foreign technology effects; the repository-local shell owns process setup, final
rendering and escape handling.
- **Why** The domain remains a pure policy oracle while application code can sequence real
  work without knowing the technology or representation that performs it.
- **Check** `lint-imports --config enforce/importlinter.toml` contract `ARCH-002 domain is pure` · `python tools/import_gate.py`
- **See** [ARCH-005] · [ARCH-019] · [ARCH-020]

### EFCT-002 · Time, randomness and environment enter through ports  [BINDING] [check:explicit_effects]
The wall clock, random sources, environment variables and process identity MUST be reached
only through an injected port.
- **Why** Each is a hidden input that makes a result irreproducible, and an irreproducible
  failure cannot be replayed for diagnosis.
- **Check** `python -m checks.explicit_effects`

### EFCT-003 · Determinism is the default  [BINDING] [fitness:test_determinism]
Given the same inputs and the same fault schedule, a run MUST produce the same outputs and
the same sequence of effects. Deliberate nondeterminism is injected, documented and
seedable.
- **Why** Reproduction is the first step of every diagnosis; a failure that cannot be
  reproduced can only be guessed at.
- **Check** `pytest enforce/fitness/test_determinism.py`
- **See** [law/TEST]

---

## Changing state

### EFCT-004 · Mutating operations are commands, not raw writes  [BINDING] [check:plan_apply]
A change to persistent state MUST be expressed as a named command carrying its intent, not
as a direct write performed wherever it was computed.
- **Why** A named command is a thing that can be validated, logged, replayed and refused;
  a scattered write is none of those.
- **Check** `python -m checks.plan_apply`

### EFCT-005 · Destructive operations plan before they apply  [BINDING] [check:plan_apply]
An operation that deletes or overwrites MUST compute a complete plan of its effects, and
apply it only as a separate step. Computing and performing in one pass is prohibited.
- **Why** A recorded incident in the source corpus is exactly this shape: a cleanup
  routine that computed and performed deletion in one pass destroyed 8,023 files under
  three fault conditions while reporting success. The plan is what makes the difference
  between a preview and an apology.
- **Check** `python -m checks.plan_apply`

### EFCT-006 · A dry run is the pipeline truncated, never a second path  [BINDING] [fitness:test_dry_run_matches_apply]
Preview mode MUST produce the plan and stop. It MUST NOT be implemented as separate code
that predicts what the real path would do.
- **Why** Two code paths diverge, and the preview that diverges is worse than no preview
  because it is trusted.
- **Check** `pytest enforce/fitness/test_effects.py::test_dry_run_matches_apply`

### EFCT-007 · A multi-effect apply is journalled  [BINDING] [fitness:test_interruption_recovers]
Where the substrate offers no all-or-nothing guarantee across effects, the apply step MUST
write a journal that lets an interrupted run be detected and completed or rolled back.
- **Why** Filesystems give no cross-file transaction; without a journal an interruption
  leaves a state nothing can classify, which is undiagnosable by construction.
- **Check** `pytest enforce/fitness/test_effects.py::test_interruption_recovers`

### EFCT-008 · Atomicity claims are qualified  [BINDING] [check:atomicity_qualified]
A contract MUST state which guarantee it offers — single-file-rename atomic,
journal-recoverable, or transactionally atomic — and against what. The bare word is a
documentation defect.
- **Why** Two source documents used it in incompatible senses; a reader who assumes the
  strong sense builds on a guarantee that was never offered.
- **Check** `python -m checks.atomicity_qualified`
- **See** [meta/GLOSSARY]

### EFCT-009 · What is not guaranteed is stated  [BINDING] [fitness:test_what_is_not_guaranteed_is_stated]
A contract offering partial guarantees MUST name what it does not guarantee — cross-process
isolation during a commit window, the indivisibility of the journal write itself, ordering
under concurrent readers.
- **Why** An unstated non-guarantee is discovered as a bug, and attributed to the wrong
  component every time.
- **Check** `pytest enforce/fitness/test_effects.py::test_what_is_not_guaranteed_is_stated`

---

## Lifecycle

### EFCT-010 · State transitions are explicit and closed  [BINDING] [check:plan_apply]
A lifecycle MUST be a declared set of states with a declared transition table. Any state
change goes through it.
- **Why** A closed table makes an illegal transition a checkable event with two named
  states, rather than an object quietly in the wrong condition.
- **Check** `python -m checks.plan_apply`

### EFCT-011 · Illegal transitions are refused before any effect  [BINDING] [check:plan_apply]
A transition not in the table MUST be rejected during validation, with the source and
target states in the error, and MUST NOT be partially performed.
- **Why** Refusing before the first effect is what keeps the failure cheap and the state
  interpretable.
- **Check** `python -m checks.plan_apply`
- **See** [law/ERR]

### EFCT-012 · Persistent state has exactly one owning path  [BINDING] [auto:import-linter]
Each persistent artifact MUST be written through one owning module. Clients, hooks and
agents go through the command surface, never directly to storage.
- **Why** Two writers make every corruption a question of which one did it; one writer
  makes it an answer.
- **Check** `lint-imports --config enforce/importlinter.toml` contract `EFCT-012 storage has one owner` · `python tools/import_gate.py`
- **See** [law/API]

---

## Concurrency

### EFCT-013 · Concurrency is introduced only with stated semantics  [BINDING] [fitness:test_concurrency_documented]
Any concurrent component MUST document its ownership, ordering, cancellation, shutdown and
stale-state behaviour before it is written.
- **Why** Undocumented concurrency produces failures whose reproduction depends on
  timing — the class of defect a diagnostic record is least able to capture after the fact.
- **Check** `pytest enforce/fitness/test_concurrency.py::test_concurrency_documented`

### EFCT-014 · Shared mutable state is guarded by a stated lock order  [BINDING] [fitness:test_concurrency_documented]
Where locks are necessary, the acquisition order MUST be part of the design and written
down.
- **Why** Locks without a documented order are a recurring source of deadlocks that take
  weeks to find, and a deadlock emits nothing to diagnose.
- **Check** `pytest enforce/fitness/test_concurrency.py::test_concurrency_documented`

### EFCT-015 · Writer exclusion is enforced; contention is a result  [BINDING] [fitness:test_single_writer]
Where a single writer is required, exclusion MUST be enforced by a lock with defined stale
recovery, and losing the race MUST surface as a typed conflict result, not a crash.
- **Why** A contended write that raises reads as a defect; one that returns a conflict
  reads as the expected outcome it is.
- **Check** `pytest enforce/fitness/test_concurrency.py::test_single_writer`
- **See** [law/ERR]

### EFCT-016 · Prefer the sequential design  [ADVISORY]
Concurrency SHOULD be introduced to meet a stated requirement, not because a task looks
parallelizable.
- **No mechanism** Whether a requirement genuinely demands concurrency cannot be read off
  the code; [EFCT-013] mechanizes the obligation to document it once it is introduced.
- **Why** Every concurrent path multiplies the interleavings a fault schedule must cover
  to keep the failure space diagnosable.
