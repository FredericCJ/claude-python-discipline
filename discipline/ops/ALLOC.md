---
id: ops/ALLOC
kind: ops
title: Workload Allocation
tokens: 2145
load_when:
  - "dispatch a subagent"
  - "which model"
  - "how much effort"
  - "delegate"
  - "escalate"
  - "sub-agent"
verified: 2026-08-18
decay: months
---

# Workload Allocation

Binding for any party that dispatches work to another agent — human or agent. That party is
the **coordinator**.

This track governs *who does the work*. It never governs *what the system accepts*: a
dispatch at any tier is validated identically by the core, per [law/API].

> Run each workload on the **cheapest capability tier, at the cheapest effort tier, that is
> genuinely able to carry it** — where "able" is judged against the workload *as handed
> over*, not as it exists in the coordinator's head.

Both failure directions cost. Over-provisioning wastes capability on mechanical work.
Under-provisioning produces work that is confident and wrong, which is worse: detecting it
costs more than the allocation saved, and a plausible wrong answer survives review.

---

## Tiers

Tiers are defined by capability characteristics, never by vendor or product name, so this
survives model and procurement changes.

| Tier | Capability |
|---|---|
| T0 | mechanical transformation against an explicit, complete specification |
| T1 | bounded reasoning within a stated contract |
| T2 | open-ended reasoning, arbitration, novel design |

| Effort | Reasoning budget |
|---|---|
| E0 | direct response |
| E1 | considered |
| E2 | deep deliberation |

Capability answers *which agent*; effort answers *how much budget it gets*. They are
independent axes and are chosen separately. T2 at E0 is almost always a mistake: work that
needs open reasoning needs deliberation.

### ALLOC-001 · Refer to the tier, never to a model  [BINDING] [check:no_model_names]
Project documents and dispatch records MUST name the tier. Naming a specific model breaks
when models change.
- **Why** A tier is a role; the model filling it is an implementation detail, and the same
  push-coupling-to-the-edge reasoning applies to procurement as to libraries.
- **Check** `python -m checks.no_model_names`

---

## Classification

Score seven signals, 0 to 3 each, for a total of 0 to 21.

| | Signal | 0 | 3 |
|---|---|---|---|
| A | Determinism of output | one correct answer | many defensible answers |
| B | Specification completeness | fully specified | must be inferred |
| C | Blast radius | one file, trivially reversible | destructive, irreversible, or a published contract |
| D | Failure visibility | immediate hard failure | silent; may ship undetected |
| E | Context breadth | one file | whole system, or unbounded |
| F | Domain novelty | routine | unfamiliar |
| G | Specialist competence required | none | deep domain expertise |

| Total | Allocation |
|---|---|
| 0–3 | T0 / E0 |
| 4–7 | T0 / E1, or T1 / E0 if B is 2 or more |
| 8–12 | T1 / E1 |
| 13–15 | T1 / E2 |
| 16–21 | T2 / E2 |

The band boundaries are absolute risk thresholds, not proportional slices.

### ALLOC-002 · Score before dispatching, and record the score  [BINDING] [check:dispatch_recorded]
A dispatch MUST carry its seven signal scores, the resulting allocation, any override
applied, and a one-line rationale where the allocation departs from the score.
- **Why** An unrecorded allocation cannot be audited after a failure, which is the only
  moment the classification's quality can actually be assessed.
- **Check** `python -m checks.dispatch_recorded`

### ALLOC-003 · Named categories force escalation regardless of score  [BINDING] [check:dispatch_recorded]
These MUST be dispatched at T2/E1 or above: changing a published contract; the adversarial
verification before a change lands; designing an irreversible or destructive operation;
anything touching security or the supply chain; arbitration between conflicting positions;
root-cause analysis after a defect escaped.
- **Why** Each is a case where the cost of a confident wrong answer is not bounded by the
  size of the change.
- **Check** `python -m checks.dispatch_recorded`

### ALLOC-004 · A single signal at 3 raises the floor  [BINDING] [check:dispatch_recorded]
Any signal scored 3 forces at least T1/E1. A signal D of 3 — a mistake would ship
silently — forces E2 regardless of tier.
- **Why** A workload cannot be dispatched cheaply because its *sum* is low if one dimension
  is individually at the top of its scale.
- **Check** `python -m checks.dispatch_recorded`

### ALLOC-005 · Escalation rules beat the mechanical permit  [BINDING] [check:dispatch_recorded]
A mechanical substitution with an explicit stop condition may run at T0/E0 — but where an
escalation rule also applies, the escalation wins.
- **Why** This is not hypothetical. The recorded incident that destroyed 8,023 files began
  as exactly this shape: a mechanical directory-cleanup instruction, dispatched without
  regard for its blast radius.
- **Check** `python -m checks.dispatch_recorded`
- **See** [law/EFCT]

---

## Coordinator obligations

### ALLOC-006 · Sharpen the contract before raising the tier  [BINDING] [check:dispatch_recorded]
Where signal B is high, the coordinator MUST first attempt to complete the specification,
and re-score, before escalating.
- **Why** This is the doctrine's central lever: sharpening the contract lowers the tier, it
  is nearly always cheaper than escalating, and it produces a reusable artifact.
- **Check** `python -m checks.dispatch_recorded`

### ALLOC-007 · Split before upgrading  [BINDING] [check:dispatch_recorded]
Prefer decomposing a workload into a large mechanical part and a small reasoning part over
running the whole at a high tier.
- **Why** Two cheap agents with a clear contract between them usually beat one expensive
  agent, and the contract survives the task.
- **Check** `python -m checks.dispatch_recorded`

### ALLOC-008 · A restriction is not lifted by an instruction  [RETIRED]
Retired as a duplicate. The obligation is [TEAMS-002], word for word in substance: a
dispatch cannot grant a capability the receiving agent does not hold, and that agent must
not achieve the effect by other means.
- **Why** Two ids for one obligation is worse than either alone. A reader who greps
  `ALLOC-008` and a reader who greps `TEAMS-002` find different halves of the same rule and
  each believes they have the whole of it, and a finding cites whichever the check's author
  reached for first.
- **Superseded by** TEAMS-002
- **See** [ops/teams]

### ALLOC-009 · Misclassification belongs to the coordinator  [BINDING] [check:dispatch_recorded]
When returned work is inadequate, the coordinator MUST re-score and record which of four
defect kinds it was: misclassification, specification defect, execution defect, or
capability mismatch.
- **Why** The distribution over those four tells the organization whether it is
  under-tiering, under-specifying, or genuinely at a tier's limit — three problems with
  three different remedies.
- **Check** `python -m checks.dispatch_recorded`

### ALLOC-010 · The gate's tier follows the risk under test  [BINDING] [check:allocation_declared]
A verification workload is scored on the risk of the code it examines, not on how routine
the act of verifying sounds. The tier it lands on MUST resolve through a declared
tier-to-model mapping, so the dispatch can be audited after the fact.
- **Why** Writing a fault-injection suite for a destructive operation is open-reasoning
  work even though "writing tests" sounds mechanical. And a tier that resolves to nothing
  names a role rather than a choice, which is unauditable however carefully it was scored.
- **Check** `python -m checks.allocation_declared`
- **See** [meta/OPEN]

The mapping is declared in `overrides/allocation.toml`, which is project-owned and never
vendored — so this rule binds without the corpus naming a model, which [ALLOC-001] forbids.
[meta/OPEN] `OPEN-006` records why that was the only way through.
