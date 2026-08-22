---
id: law/OPS
kind: law
title: Local Operations and Capability Activation
tokens: 507
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
