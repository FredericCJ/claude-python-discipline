---
id: law/OPS
kind: law
title: Local Operations and Capability Activation
tokens: 1575
load_when:
  - "capability manifest"
  - "operational behavior"
  - "subprocess lifecycle"
  - "network io"
  - "persistent state"
  - "generated artifact"
  - "resource budget"
applies_to: ["pyproject.toml", "**/*.py", "operational-model.json"]
grounds_on: ["law/ARCH", "law/EFCT", "law/TEST"]
decay: none
python: ">=3.11"
---

# Local Operations and Capability Activation

Capabilities describe observable facts about this repository. They only add local
obligations; they cannot waive the consequential-software kernel or assign work to a
parent, sibling, counterpart, or system integrator.

## Activation

### OPS-001 · Capability facts are closed, explicit, and additive  [BINDING] [check:capabilities]
`[tool.agent-discipline.capabilities]` MUST contain the complete v4 capability vocabulary
as booleans. `true` activates obligations and MAY conservatively exceed inference;
absence never means false. A repository claiming subprocess lifecycle ownership MUST also
declare that it launches subprocesses.
- **Why** An optional or open-ended table turns every future obligation into a silent
  waiver for existing repositories. Additive facts keep one strict kernel.
- **Check** `python -m checks.capabilities`
- **See** [meta/SCOPE] · [EVID-003]

### OPS-002 · Observed capability cannot be declared false  [BINDING] [check:capabilities]
A capability inferred from declared production roots, build metadata, or the canonical
local contract model MUST be `true`. Inference MAY activate an obligation; lack of a
syntactic witness MUST NOT deactivate one.
- **Why** Imports and effect calls can refute under-declaration cheaply, while no finite
  syntax scan can prove that a semantic capability is absent.
- **Check** `python -m checks.capabilities`
- **See** [ARCH-018] · [EVID-003]

## Operational model

### OPS-003 · Operational ownership joins the local architecture  [BINDING] [check:operational_model]
The project MUST name one repository-local `operational-model.json`. Every resource and
recovery cited by an enabled capability MUST resolve to the canonical local architecture
model; an empty ownership set MUST carry an explicit local-absence rationale. Evidence
paths MUST remain inside this repository.
- **Why** A lifecycle claim without an owned resource or recovery identity leaves cleanup
  assignable to nobody—or quietly assigns it to an out-of-scope integrator.
- **Check** `python -m checks.operational_model`
- **See** [ARCH-023] · [meta/SCOPE]

### OPS-004 · Every local lifecycle phase is decided  [BINDING] [check:operational_model]
The operational model MUST define startup, steady state, interruption, drain, shutdown,
and forced cleanup in that order. Startup, steady state, and shutdown MUST name executable
evidence. Each other phase MUST name executable evidence when an enabled capability
activates it; otherwise it MUST state why the phase is locally inapplicable. Every phase
MUST name its local owner and a declared terminal state.
- **Why** Happy-path typing says nothing about interruption, half-completed work, or who
  performs the last cleanup operation.
- **Check** `python -m checks.operational_model`
- **See** [OPS-001] · [EFCT-009]

### OPS-005 · Safe and degraded outcomes are observable  [BINDING] [check:operational_model]
The operational model MUST define at least one safe and one degraded local state. State
entry MUST have a stable event code. Terminal outcomes MUST join a declared state, carry
a correlation field and executable evidence, and include at least one non-exception
outcome.
- **Why** Refusal, dropped work, exhaustion, and controlled degradation are operational
  facts even when no exception escapes; exception-only telemetry makes them disappear.
- **Check** `python -m checks.operational_model`
- **See** [DIAG-010] · [DIAG-016]

### OPS-006 · Activated work has a finite measured budget  [BINDING] [check:operational_model]
The operational model MUST decide time, memory, queue, retry, input-size, and cleanup
budgets. A budget activated by a true capability MUST carry a positive finite bound, a
compatible unit, and repository-local measurement evidence. An inactive budget MUST
instead state why it is locally inapplicable.
- **Why** Type-correct unbounded work remains an availability defect; a number without a
  measurement is an aspiration rather than a controlled limit.
- **Check** `python -m checks.operational_model`
- **See** [TYPE-001] · [TEST-003]

### OPS-007 · Delivery identity and platform intent are explicit  [BINDING] [check:operational_model]
The operational model MUST name the local build-identity source, executable evidence that
runtime diagnostics expose both version and build id, and distinct runtime and
development-tool support outcomes for Windows and Linux. Every support claim MUST cite
local evidence; every unsupported or inapplicable outcome MUST state its limitation.
- **Why** An unattributed failure cannot be tied to the artifact that ran, and an absent
  platform result must not be mistaken for support.
- **Check** `python -m checks.operational_model`
- **See** [DIAG-001] · [EVID-005]

### OPS-008 · Capability activation expands to a closed evidence set  [BINDING] [check:operational_model]
Every true capability MUST have exactly one operational record containing every generated
obligation for that capability and no unknown obligation. Each obligation MUST point to
confined executable evidence. False capabilities MUST have no operational record.
- **Why** A prose checklist can omit the one hostile condition that matters while still
  looking complete; exact generated joins make omission and stale evidence observable.
- **Check** `python -m checks.operational_model`
- **See** [OPS-001] · [TEST-020] · [EVID-003]
