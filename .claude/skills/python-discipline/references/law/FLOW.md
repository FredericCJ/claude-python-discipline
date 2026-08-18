---
id: law/FLOW
kind: law
title: How a Change Is Made
tokens: 1985
load_when:
  - "definition of done"
  - "before i commit"
  - "what should i do first"
  - "ADR"
  - "decision record"
  - "review"
  - "is this finished"
applies_to: ["**/*"]
requires: ["law/TEST"]
decay: none
python: ">=3.11"
---

# How a Change Is Made

The order of work, and what "finished" means. Every other module says what the code must
be; this one says what the *change* must be.

The order matters for one reason: each step produces the artifact the next step is checked
against. Skipping a step does not save it — it moves it to the point where it costs most.

---

## Order

### FLOW-001 · The contract is written before the implementation  [BINDING] [fitness:test_contract_documented]
Before a component is written, its inputs, outputs, invariants, error modes and ordering
constraints MUST be stated. The specification owns what and how well; the implementer owns
how.
- **Why** A contract written afterwards describes what was built, so it can never disagree
  with it, and can therefore never catch anything.
- **Check** `pytest enforce/fitness/test_api.py::test_contract_documented`
- **See** [law/API] · [frame/spec]

### FLOW-002 · Test obligations are named before tests are written  [BINDING] [check:oracle_declared]
An obligation MUST name the observable contract under test, the input partitions and
boundary values, the expected observable, and the error paths. It does not contain
assertions.
- **Why** Obligations written after the tests are a summary of the tests, and the gap they
  were meant to expose closes silently.
- **Check** `python -m checks.oracle_declared`
- **See** [law/TEST]

### FLOW-003 · A structural decision is recorded before it is relied upon  [BINDING] [fitness:test_decisions_recorded]
Introducing a port, a new layer, a concurrency model or a persisted format MUST be recorded
as a numbered decision stating context, decision, justification, alternatives considered,
consequences and enforcement.
- **Why** The alternatives and the reason are exactly what a later agent needs and cannot
  reconstruct from the code, which shows only the option that won.
- **Check** `pytest enforce/fitness/test_decisions.py::test_decisions_recorded`
- **See** [law/ARCH]

### FLOW-004 · Decision records are appended, never rewritten  [BINDING] [fitness:test_decisions_recorded]
Records MUST be numbered sequentially and never renumbered or deleted. A superseded
decision is marked superseded and kept.
- **Why** A deleted decision takes its reasoning with it, and the next agent re-derives
  and re-litigates it.
- **Check** `pytest enforce/fitness/test_decisions.py::test_decisions_recorded`

### FLOW-005 · Overruled objections are recorded, not discarded  [BINDING] [fitness:test_decisions_recorded]
Where a decision was contested, the objection and its resolution MUST be recorded.
- **Why** When the decision later proves wrong, the recorded objection is usually the
  fastest available description of why — the cheapest future-debugging asset there is.
- **Check** `pytest enforce/fitness/test_decisions.py::test_decisions_recorded`

---

## Every rule earns its keep

### FLOW-006 · A rule without a mechanism is not binding  [BINDING] [fitness:test_binding_rules_have_mechanisms]
A rule tagged binding MUST name a runnable mechanism. One that cannot is advisory, with a
written statement of why no mechanism exists.
- **Why** This is the axiom the whole discipline rests on. A binding rule nothing checks
  degrades to the same failure mode as a verification that passes vacuously.
- **Check** `pytest enforce/fitness/test_meta.py::test_binding_rules_have_mechanisms`
- **See** [meta/SCHEMA]

### FLOW-007 · No check may pass vacuously  [BINDING] [fitness:test_checks_can_fail]
Every check MUST have a companion test proving it fails when its condition is violated. A
check whose success signal is empty output MUST first be shown able to produce a failing
one, in the environment it runs in.
- **Why** A check never observed to fail has not been shown to check anything, and its
  silence is indistinguishable from correctness.
- **Check** `pytest enforce/fitness/test_meta.py::test_checks_can_fail`
- **See** [law/TEST]

### FLOW-008 · Deviations from an advisory rule are recorded in the change  [BINDING] [check:deviation_recorded]
Departing from an advisory rule MUST be justified in the commit message or the decision
record, citing the rule identifier.
- **Why** An unrecorded departure is indistinguishable from an oversight, and the next
  reader restores the rule and breaks whatever the departure was for.
- **Check** `python -m checks.deviation_recorded`

---

## Definition of done

A change is finished when every line below is true. Not "mostly", and not "the failures are
unrelated".

### FLOW-009 · The gates pass before a change is offered  [BINDING] [fitness:test_gate_suite_defined]
Formatting, linting, both type checkers, import contracts, the custom checks, and the unit,
contract, integration and fault suites MUST all pass. Property suites run on the seeds
recorded for the touched modules, and the mutation gate runs on touched core modules.
- **Why** A gate run after the change is offered is a gate that reviews someone else's
  time instead of the author's.
- **Check** `pytest enforce/fitness/test_meta.py::test_gate_suite_defined`

### FLOW-010 · New behaviour arrives with its obligations discharged  [BINDING] [fitness:test_layers_populated]
A new component arrives with its contract, its unit tests, and — if it is a port — its
three adapters, its contract suite and its fault suite. A new invariant arrives with its
property test.
- **Why** The suite is complete at every commit or at none; "tests to follow" is where
  they stop following.
- **Check** `pytest enforce/fitness/test_layers.py::test_layers_populated`
- **See** [law/ARCH]

### FLOW-011 · The diagnosis is checked, not assumed  [BINDING] [fitness:test_envelope_conforms]
For a change touching an error path, the resulting envelope MUST be inspected: its code,
layer, expected and actual values, and remediation must be enough to locate and fix the
fault without reading the source.
- **Why** This is the Prime Directive's acceptance test, and the only step at which the
  discipline's actual purpose is verified rather than approximated.
- **Check** `pytest enforce/fitness/test_diagnostics.py::test_envelope_conforms`
- **See** [law/DIAG]

### FLOW-012 · Report what happened, including what did not  [BINDING] [check:deviation_recorded]
A change description MUST state what was verified, what was skipped and why, and any rule
deviation with its identifier. A failing test is reported as failing.
- **Why** An agent inherits the previous agent's report as fact; a report that rounds a
  partial result up to a complete one poisons every decision built on it.
- **Check** `python -m checks.deviation_recorded`

### FLOW-013 · Scale ceremony to reuse ambition, not to line count  [ADVISORY]
For a genuinely single-use script, the cascade SHOULD be compressed — and the compression
stated.
- **No mechanism** Reuse ambition is an intention about the future that no check can read
  from the present code.
- **Why** Full ceremony applied indiscriminately trains people to route around it, which
  costs more than the ceremony saved.
