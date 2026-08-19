---
id: ops/teams
kind: ops
title: Agent Team Mechanics
tokens: 2592
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

### Partial re-verification, 2026-08-19

The front-matter `verified:` date has deliberately **not** moved. Only part of this
module was re-checked, and dating the whole of it from a partial check is the failure
that makes a date worse than no date.

**Re-verified by execution.** A subagent definition is honoured with exactly four
front-matter keys — `name`, `description`, `tools`, `model`. Evidence: the nine
definitions under `.claude/agents/` carry those four and no others, and all nine load
and appear as dispatchable types with their descriptions intact. One adjacent
observation, made while writing them: the `description` value is parsed as YAML, so an
unquoted colon-space inside it breaks the definition silently — `verified: ` in a
sentence was enough to do it.

**NOT re-verified, and still dated 2026-06-17.** The claims below need a live dispatch
to test, which was out of scope for the session that wrote this note:

- that a role definition reused as a teammate has its body *appended* rather than
  substituted;
- that some fields are silently dropped on that path;
- `TEAMS-003`'s premise that the tooling offers a completion hook at all.

Treat those three as the oldest material in the corpus and check them before relying on
them.

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

### TEAMS-003 · Verification runs as a gate, not as a request  [BINDING] [fitness:test_completion_hook_enforces_the_gate]
Where the tooling offers a completion hook, the verification obligation MUST be enforced
there — a task cannot be marked done while its gate fails.
- **Why** This is what turns a soft norm into a hard one, and it is the only place the
  discipline's own axiom can be applied to agent coordination itself.
- **Check** `pytest enforce/fitness/test_meta.py::test_completion_hook_enforces_the_gate`
- **See** [law/FLOW]

## Documentation work: write, then refute

`ESTABLISHED` — measured on this repository. A documentation migration ran 13 batches of
agents over 585 elements in 28 files. Every batch passed four mechanical gates — behaviour
preservation by AST fingerprint, `doc_coverage`, `doc_style`, ruff — and a clean Doxygen
build. A second, independent agent was then run over each batch with the sole task of
checking each claim against the code it described. It found **90 claims that were
confidently false** and **59 filler docstrings restating the identifier**: roughly a 15
percent semantic error rate surviving a green gate.

`ESTABLISHED` — the 90 were sampled and classified as almost entirely *semantic*, not
referential: they cite symbols that genuinely exist and attribute behaviour the code does
not have. "Normalizes a scalar" where only strings normalize; "parameters of all four
kinds" where there are three; "the strongest evidence found" where the code reports the
first one written; "everything added here is marked declared" where the node type has no
origin field at all. A reference-existence linter would have caught approximately none of
them. This is what [DOC-013] names when it says the remainder is a reading judgment.

### TEAMS-004 · Documentation is written in one stage, verified in another  [ADVISORY]
Documentation dispatched to agents SHOULD run as two stages, the verifier a fresh agent
holding no memory of having written the text and re-deriving each claim from the code.
- **Why** A writer re-reading its own documentation re-derives its own assumptions and so
  confirms them; independence is the only thing that makes the second reading evidence.
- **No mechanism** Whether a second, independent pass happened is a fact about dispatch
  history, not about the tree, and nothing in the repository can read it.
- **See** [TEAMS-001] · [law/DOC]

### TEAMS-005 · A verifier refutes claims; it does not improve prose  [ADVISORY]
The verifier's task SHOULD be stated as refutation — for each claim, find the code that
contradicts it — and SHOULD NOT include rewriting, tightening or restyling.
- **Why** An agent asked to improve documentation optimizes wording it can see; an agent
  asked to refute must open the code, which is the only place the error is visible.
- **No mechanism** The instruction is in a dispatch, and its effect is a judgment about
  whether a claim was tested rather than admired; neither is inspectable after the fact.
- **See** [DOC-009] · [TEAMS-001]

### TEAMS-006 · Presence and truth need separate mechanisms  [ADVISORY]
Documentation completeness and documentation truth SHOULD be treated as two properties;
the mechanical gate decides only the first, and a green gate SHOULD NOT be read as the
second.
- **Why** Treating the gate as a truth oracle is what let 90 false claims ship green —
  and a false docstring is worse than an absent one, because an agent trusts it.
- **No mechanism** Deciding whether a sentence is true of the code it sits above is the
  general program-understanding problem; [DOC-001]–[DOC-011] mechanize presence and form,
  which is the whole of what a checker can reach.
- **See** [DOC-013] · [law/DOC]

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
