---
id: law/TEST
kind: law
title: Systematic Testing and Oracles
tokens: 2777
load_when:
  - "write a test"
  - "pytest"
  - "fixture"
  - "hypothesis"
  - "property test"
  - "mutation"
  - "MC/DC"
  - "fault injection"
  - "contract suite"
  - "golden file"
  - "flaky"
applies_to: ["tests/**/*.py", "**/*.py"]
grounds_on: ["fact/py-testing", "fact/py-typing"]
requires: ["law/ARCH", "law/ERR"]
decay: none
python: ">=3.11"
---

# Systematic Testing and Oracles

Testing is an architectural activity: a component that cannot be tested independently is a
design defect, not a testing problem.

Two questions govern every test. **What layer is this?** — which fixes what it may touch.
**What is its oracle?** — which fixes what makes it right. A suite without stated oracles
converges on asserting whatever the code already does.

---

## Layers

| Layer | May touch | Oracle |
|---|---|---|
| unit | nothing external; pure domain | invariants and stated obligations |
| contract | one port, all its adapters | the port's published contract |
| integration | one real technology | the real thing's observed behaviour |
| fault | faulty adapters, fault schedules | containment and propagation rules |
| property | pure domain, generated inputs | algebraic properties |
| mutation | the suite itself | does the suite detect a seeded defect |

### TEST-001 · Unit tests touch no external resource  [BINDING] [fitness:test_unit_layer_is_pure]
Tests in the unit layer MUST NOT import filesystem, network, subprocess, clock or
environment modules, nor any adapter.
- **Why** A unit failure that can be caused by the environment is a unit failure that
  localizes nothing.
- **Check** `pytest enforce/fitness/test_layers.py::test_unit_layer_is_pure`
- **See** [law/ARCH]

### TEST-002 · Each test layer exists and is populated  [BINDING] [fitness:test_layers_populated]
Every port MUST have a contract suite and a fault suite; every domain module MUST have
unit tests and, where it states an invariant, a property suite.
- **Why** An untested seam is not visibly untested — it looks exactly like a tested one
  until it fails.
- **Check** `pytest enforce/fitness/test_layers.py::test_layers_populated`

### TEST-003 · Per-test time is budgeted and enforced  [BINDING] [auto:pytest-timeout]
Unit tests MUST complete within the configured per-test budget.
- **Why** The budget is a proxy for the architecture: a unit test that got slow did so by
  acquiring a dependency it was not supposed to have.
- **Check** `pytest --timeout` as configured in `enforce/templates/pyproject.toml`

The suite's wall-clock total is reported, never gated. It is flaky by construction and
gameable by splitting, and one source document set it as a budget in one section and argued
against it in another.

---

## Oracles, strongest first

### TEST-004 · Every test module declares its oracle  [BINDING] [check:oracle_declared]
A test module MUST name, in its docstring, which oracle its assertions rest on: contract,
property, differential, golden, or example.
- **Why** An undeclared oracle is almost always "whatever the implementation did when I
  wrote this", which locks in the defect instead of detecting it.
- **Check** `python -m checks.oracle_declared`

### TEST-005 · One contract suite runs against every adapter  [BINDING] [fitness:test_contract_suite_per_adapter]
The port's contract is the oracle for all of its adapters, and the same suite runs against
real, fake, and faulty-in-healthy-mode without modification.
- **Why** This is the strongest oracle available: it tests against the published promise
  rather than against an implementation.
- **Check** `pytest enforce/fitness/test_ports.py::test_contract_suite_per_adapter`
- **See** [law/ARCH]

### TEST-006 · A fake that can drift from the real adapter is worthless  [BINDING] [fitness:test_contract_suite_per_adapter]
Any behaviour a fake exhibits that the real adapter does not MUST be caught by the shared
contract suite.
- **Why** Every unit test standing on a drifting fake is worth exactly as little as the
  fake, and none of them will say so.
- **Check** `pytest enforce/fitness/test_ports.py::test_contract_suite_per_adapter`

### TEST-007 · Stated invariants have property suites  [BINDING] [fitness:test_layers_populated]
Round-trip, idempotence, involution, ordering and closure properties MUST be expressed as
generated-input property tests, not as hand-picked examples.
- **Why** A property is a claim about all inputs; three examples test three inputs and
  imply the rest.
- **Check** `pytest enforce/fitness/test_layers.py::test_layers_populated`

### TEST-008 · Golden files are reviewed, never merely regenerated  [BINDING] [fitness:test_goldens_reviewed]
A change to a golden artifact MUST be accompanied by the source change that justifies it.
Regenerating goldens to make a suite pass is prohibited.
- **Why** "Just regenerate" converts an oracle into a recording of the current behaviour,
  which is the same as deleting it.
- **Check** `pytest enforce/fitness/test_goldens.py::test_goldens_reviewed`

---

## Faults

### TEST-009 · Fault injection is data, not bespoke classes  [BINDING] [fitness:test_fault_schedules_are_data]
A fault MUST be expressed as a schedule — port, operation, occurrence, fault kind — that
can be serialized, replayed and shrunk. Hand-written single-purpose failing classes are
prohibited.
- **Why** A schedule that survives as data is a failing case an agent can replay verbatim;
  a bespoke class is a one-off that has to be re-derived.
- **Check** `pytest enforce/fitness/test_faults.py::test_fault_schedules_are_data`
- **See** [examples/port-triad]

### TEST-010 · The fault catalogue is covered per port  [BINDING] [fitness:test_fault_catalogue]
Each port MUST be exercised against the fault categories that apply to it: explicit
failure, omission, timing, value corruption, state inconsistency, stale state,
duplication, reordering, partial effect, and protocol violation.
- **Why** Faults found in production are drawn from this list; a category never injected is
  a category first observed live.
- **Check** `pytest enforce/fitness/test_faults.py::test_fault_catalogue`

### TEST-011 · Propagation and containment are tested, not assumed  [BINDING] [fitness:test_fault_containment]
For a chain of components, tests MUST assert what a downstream component does when an
upstream one misbehaves, and that a healthy neighbour is unaffected.
- **Why** The interesting behaviour is never the direct failure; it is what the next
  component does with it.
- **Check** `pytest enforce/fitness/test_faults.py::test_fault_containment`
- **See** [law/ERR]

### TEST-012 · Interruption is tested at every effect boundary  [BINDING] [fitness:test_interruption_recovers]
A multi-effect apply MUST be tested for interruption before, between and after each
effect, asserting that recovery reaches a defined state.
- **Why** The failure that destroyed 8,023 files in the source corpus happened in exactly
  this window, and reported success while doing it.
- **Check** `pytest enforce/fitness/test_effects.py::test_interruption_recovers`
- **See** [law/EFCT]

---

## Confirming the suite discriminates

### TEST-013 · Mutation score is gated on the core  [BINDING] [auto:mutmut]
Seeded defects in domain modules MUST be detected at or above the configured score.
Surviving mutants are dispositioned in a ledger, never ignored.
- **Why** This is the only check that tests the tests; line execution cannot distinguish
  "this ran" from "this was verified".
- **Check** the configured mutation run and its score gate
- **See** [TEST-004]

### TEST-014 · Compound decisions are decomposed and tabulated  [BINDING] [check:compound_gate]
A gate decision combining conditions MUST either be decomposed into named predicates, or
be accompanied by a parametrized truth-table test covering each condition's independent
effect on the outcome.
- **Why** No mainstream tool measures `modified condition/decision coverage` for this
  language, so the requirement is met by construction instead of by measurement.
- **Check** `python -m checks.compound_gate`

### TEST-015 · Every check has a proof-of-failure companion  [BINDING] [fitness:test_checks_can_fail]
Every gate, fitness test and custom check MUST have a companion test demonstrating it
fails when the condition it guards is violated.
- **Why** A check whose passing signal is empty output has not been shown to check
  anything, and silent vacuity is indistinguishable from success.
- **Check** `pytest enforce/fitness/test_meta.py::test_checks_can_fail`

### TEST-016 · A test that weakens must say so  [BINDING] [check:test_weakening]
A change that loosens an assertion, widens a caught type, or narrows a generator MUST
state in the change whether the previous discrimination is preserved.
- **Why** Suites do not collapse in one commit; they are weakened one reasonable-looking
  edit at a time, and nothing objects unless something is watching.
- **Check** `python -m checks.test_weakening`

---

## Hygiene

### TEST-017 · Tests are order-independent and network-isolated  [BINDING] [auto:pytest-randomly] [auto:pytest-socket]
The suite MUST pass under randomized ordering, and network access MUST be blocked by
default.
- **Why** Order dependence and ambient network access are both hidden inputs, and both
  produce failures that reproduce only sometimes.
- **Check** `pytest` with the configured plugins

### TEST-018 · A flaky failure is a defect in the harness  [BINDING] [fitness:test_seeds_recorded]
An unreproducible failure MUST be investigated at the priority of a domain defect. Reruns
MUST NOT be used to dismiss one. Failing generated cases are recorded as fixtures.
- **Why** Rerunning until green discards the one observation that had diagnostic value.
- **Check** `pytest enforce/fitness/test_determinism.py::test_seeds_recorded`

### TEST-019 · Test names state the behaviour  [ADVISORY]
A test name SHOULD say what must hold, not restate the implementation or number a case.
- **No mechanism** Whether a name describes behaviour or mechanism is a reading judgment;
  a pattern check would accept any sufficiently long name.
- **Why** The name is what an agent reads first in a failure report, and often all it gets.
