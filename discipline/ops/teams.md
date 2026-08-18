---
id: ops/teams
kind: ops
title: Agent Team Mechanics
tokens: 1384
load_when:
  - "agent team"
  - "teammate"
  - "subagent definition"
  - "spawn an agent"
  - "task list"
  - "slash command"
  - "skill frontmatter"
  - "quality gate hook"
verified: 2026-06-17
decay: months
---

# Agent Team Mechanics

What the tooling actually does when several agents work together. This is the fastest
decaying material in the corpus — it is graded against a specific product version, not
against the language — so treat every claim here as needing re-verification before it is
relied on.

`VERSION-DEPENDENT` — **mechanics as of mid-2026.** Confirm against the installed version
before deploying anything built on them. The source material already recorded one
coordination tool pair that had been removed since it was documented.

This module governs the *envelope* around delegated work. What the delegated work must
produce is [law/FLOW]; who it should be delegated to is [ops/ALLOC].

---

## When a team is warranted

`ESTABLISHED` — default to ordinary subagents. A team earns its cost only when the work
needs live, parallel, peer-to-peer cross-talk between long-running roles.

A linear "do A, then summarize B" pipeline does not earn a team. Mutual falsification
across parallel roles does — which is the same falsification-before-acceptance pressure
[frame/spec] describes between altitudes.

## Topology

`ESTABLISHED` — four parts: a **lead** (the main session, fixed for its lifetime), 
**teammates** (separate sessions with their own context, inheriting no conversation
history), a shared **task list**, and a **mailbox**.

`ESTABLISHED` — one team per session; no nested teams; the lead cannot be transferred.

`ESTABLISHED` — teammates address each other by name. There is no broadcast primitive;
a broadcast is manual fan-out.

Because teammates inherit no history, **everything a teammate needs must be in its
dispatch**. This is the same constraint [ops/ALLOC] scores as signal B, and the same lever:
sharpening the handover is cheaper than raising the tier.

## Reusing role definitions

`ESTABLISHED` — a subagent definition reused as a teammate has its **body appended**, not
substituted. Its tool allowlist and model are honoured; some fields are silently dropped on
that path.

Consequence: write a role body as *additive* instructions layered onto a general teammate,
not as a self-contained replacement. A role written as a complete system prompt will find
itself layered under one it did not expect.

### TEAMS-001 · A dispatch states the contract, not the intention  [BINDING] [check:dispatch_recorded]
Work handed to a teammate MUST carry its inputs, its expected observable output, its
acceptance criterion and its stop condition.
- **Why** "Able" is judged against the workload as handed over, not as it exists in the
  coordinator's head; an under-specified dispatch produces confident, wrong work.
- **Check** `python -m checks.dispatch_recorded`
- **See** [ops/ALLOC]

### TEAMS-002 · A restriction is never lifted by an instruction  [BINDING] [check:dispatch_recorded]
An agent MUST NOT achieve an effect its granted tools exclude by routing around them, and
a dispatch MUST NOT purport to grant a capability the receiving agent does not hold.
- **Why** The cost of refusing is one wasted dispatch; the cost of circumventing is that
  every verdict that agent ever issued becomes questionable.
- **Check** `python -m checks.dispatch_recorded`
- **See** [ops/ALLOC]

### TEAMS-003 · Verification runs as a gate, not as a request  [BINDING] [fitness:test_gate_suite_defined]
Where the tooling offers a completion hook, the verification obligation MUST be enforced
there — a task cannot be marked done while its gate fails.
- **Why** This is what turns a soft norm into a hard one, and it is the only place the
  discipline's own axiom can be applied to agent coordination itself.
- **Check** `pytest enforce/fitness/test_meta.py::test_gate_suite_defined`
- **See** [law/FLOW]

## Cost

`ESTABLISHED` — teammates carry their own context, so a team multiplies token cost roughly
by its size, and planning-heavy modes multiply it further.

`ESTABLISHED` — the levers are team size and how much each role is asked to hold, not the
protocol. A team of three with sharp contracts costs less and returns more than a team of
six sharing a vague one.

## Known limits

`VERSION-DEPENDENT` — task status can lag; shutdown can be slow; an in-process teammate may
not be resumable. None of these is a reason to avoid teams, but each is a reason not to
build a gate that assumes the opposite.

`OPEN` — display and control details, and the exact set of coordination tools, have already
changed once since the source material was written. Verify before depending on them.

---

## Sources

Derived from a ground-truth manifest verified against the product documentation on
2026-06-17, with an adversarial confirmation pass over each claim. That date is carried
forward here unchanged rather than restated as fresh: nothing in this module was
re-verified during the migration, and its decay window is months.
