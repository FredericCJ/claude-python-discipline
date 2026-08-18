---
id: law/LEARN
kind: law
title: What a Session Learns
tokens: 1888
load_when:
  - "learning"
  - "record what i learned"
  - "session memory"
  - "why did this fail before"
  - "calibration"
  - "promote a learning"
  - "what do we know here"
applies_to: ["**/*"]
grounds_on: ["fact/py-testing"]
requires: ["law/FLOW"]
decay: none
python: ">=3.11"
---

# What a Session Learns

An agent working in a repository that vendored this discipline discovers things the
discipline cannot know: which error means what here, which path is generated, which rule is
ambiguous against this codebase. None of it survives the session unless it is written down,
so every successor pays the same discovery cost again.

The learning database is where it is written down. It is not a notes pile: it is a **staging
area for mechanisms**. A learning that can become a check becomes one, and then retires.

Two stores, two jobs. `learning/ledger.jsonl` is append-only and committed — the record.
`learning/learning.db` is a query index rebuilt from it and never committed. The ledger is
what a reviewer reads and what git merges.

---

## Recording

### LEARN-001 · A session records what it learned before reporting done  [BINDING] [check:session_recorded]
Before a change is offered, a session MUST record its learnings, or record that it had
none. Silence and "nothing learned" are different states.
- **Why** The cost of rediscovery is paid by every later agent, and it is invisible — no
  one ever sees the sessions that re-derived a fact already known.
- **Check** `python -m checks.session_recorded`
- **See** [law/FLOW]

### LEARN-002 · A learning states a claim, an action and a trigger  [BINDING] [auto:learn]
Every entry MUST carry one sentence of what is true, one imperative of what to do
differently, and at least one trigger — a path glob, an error signature, a rule id, a
command or a term.
- **Why** A claim with no action is trivia; a claim with no trigger can never be retrieved
  and is therefore write-only.
- **Check** `python tools/learn.py record` refuses all three omissions

### LEARN-003 · Credentials never enter the ledger  [BINDING] [auto:learn] [fitness:test_a_credential_is_refused]
Recording MUST refuse material that is credential-shaped, and an entry MUST describe the
shape of a problem rather than the value that exposed it.
- **Why** The ledger is designed to be read widely and machine-processed, which is exactly
  what makes a secret in it expensive.
- **Check** `pytest tools/test_learn.py::test_a_credential_is_refused`
- **See** [law/DIAG]

### LEARN-004 · A learning is scoped by who it is about  [BINDING] [check:learning_scope]
An entry that says this repository behaves a certain way is `project`. An entry that says
the discipline itself is wrong, ambiguous or missing a rule is `discipline`, and is what
`harvest` exports upstream.
- **Why** A discipline defect recorded as a project quirk is a defect that never gets
  fixed, only worked around in every repository separately.
- **Check** `python -m checks.learning_scope`

---

## Keeping it honest

### LEARN-005 · A contradicted learning is refuted, never deleted  [BINDING] [check:ledger_append_only]
Ledger entries MUST NOT be edited or removed. A wrong entry is corrected by appending a
refutation; a replaced one by appending a supersession.
- **Why** The record of what was believed and why it stopped being believed is the only
  thing that stops the same wrong conclusion being reached twice.
- **Check** `python -m checks.ledger_append_only`

### LEARN-006 · The ledger and its index do not drift  [BINDING] [fitness:test_the_database_is_reconstructible_from_the_ledger]
The database MUST be reconstructible from the ledger exactly. A database holding events
the ledger does not is answering retrievals from material nobody reviewed.
- **Why** The moment the derived store can disagree with the record, the record stops
  being the record.
- **Check** `pytest tools/test_learn.py::test_the_database_is_reconstructible_from_the_ledger`
- **See** [law/DEP]

### LEARN-007 · Retrieval is deterministic  [BINDING] [fitness:test_retrieval_is_reproducible]
The same situation MUST yield the same learnings in the same order. Trigger matching is
exact; relevance ranking is a pure function of the stored state and the date.
- **Why** An unreproducible retrieval cannot be reviewed, and cannot be calibrated — you
  would never know whether a change to the parameters helped.
- **Check** `pytest tools/test_learn.py::test_retrieval_is_reproducible`
- **See** [law/EFCT]

### LEARN-008 · Confidence decays, and staleness is shown  [BINDING] [fitness:test_confidence_decays_with_time]
An entry not seen or re-verified within its half-life MUST be offered more quietly, and
MUST be marked stale when it is offered at all.
- **Why** An old claim presented with the authority of a fresh one is worse than no claim:
  it is a confident wrong answer, which is the expensive failure direction.
- **Check** `pytest tools/test_learn.py::test_confidence_decays_with_time`

---

## Retiring into mechanisms

### LEARN-009 · A learning that can be checked becomes a check  [BINDING] [check:promotion_due]
Once an entry has met the evidence threshold and can be expressed as a lint rule, a
contract, a configuration change or a test, the mechanism MUST be built and the entry
promoted — after which it stops being offered.
- **Why** This is the authoring axiom applied to experience. Without it the database
  becomes a permanent pile of things everyone is expected to remember, which is the
  failure mode it exists to prevent.
- **Check** `python -m checks.promotion_due`
- **See** [meta/SCHEMA]

### LEARN-010 · The active set is triaged before it outgrows its ceiling  [BINDING] [check:learning_size]
When the active set passes the configured ceiling, the next calibration pass MUST triage
rather than accumulate.
- **Why** A database nobody prunes becomes a database nobody reads, and an unread database
  costs its write time and returns nothing.
- **Check** `python -m checks.learning_size`

### LEARN-011 · A parameter change is recorded with its reason  [BINDING] [auto:learn]
Changing a retrieval, promotion or decay parameter MUST append a calibration event stating
what moved and why.
- **Why** A parameter changed without a record is indistinguishable from drift, and the
  next pass cannot tell a deliberate tightening from an accident.
- **Check** `python tools/learn.py calibrate --set` refuses without `--why`

### LEARN-012 · Prefer the smallest true entry  [ADVISORY]
An entry SHOULD record the narrowest claim that would have saved the time, rather than the
general lesson it seems to suggest.
- **No mechanism** Whether a claim is the right size is a judgment about what a future
  reader will need; the trigger requirement in [LEARN-002] mechanizes only that it can be
  found at all.
- **Why** Broad entries match everything, cost attention on every task, and are the first
  to be ignored.
