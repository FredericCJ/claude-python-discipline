# The Cheapest-Able Doctrine

**Status:** Binding for all agentic work in this project · Revision 5.
**Applies to:** Every agent that dispatches sub-agents, and every human who
dispatches agents. Such a party is a **coordinator**.

---

## 1. The rule

> Run each workload on the **cheapest capability tier, at the cheapest effort
> tier, that is genuinely able to carry it** — where "able" is judged against
> the workload *as handed over*, not as it exists in the coordinator's head.

Two failure directions, both expensive:

- **Over-provisioning** wastes capability on mechanical work, and slows delivery
  for no gain in correctness.
- **Under-provisioning** produces work that is confident and wrong. This is the
  worse direction, because detecting it costs more than the allocation saved,
  and because a plausible-looking wrong answer can survive review.

The doctrine exists to make the choice explicit, mechanical and auditable
instead of intuitive.

---

## 2. Why this is a doctrine and not a preference

This project expects substantial automated contribution. Unmanaged allocation
produces two observable pathologies:

1. Everything is escalated to the highest tier "to be safe", and the project
   pays a large constant factor on trivial edits.
2. Everything is dispatched at the lowest tier "to be fast", and the project
   pays for silent defects at review time — or, worse, after landing.

Neither is a judgement call to be re-litigated per task. The classification
procedure in §5 is designed to be applied the same way by any coordinator, and
to be reviewable after the fact.

---

## 3. Capability tiers

Tiers are defined by **capability characteristics, not vendor or product
names**, so this doctrine survives model changes, procurement changes and
version changes. Each operating organization maintains the mapping table in
§3.2 and updates it as its available models change.

### 3.1 Tier definitions

| Tier | Name | Characteristic capability | Appropriate workloads |
|---|---|---|---|
| **T0** | Mechanical | Executes a fully specified transformation reliably. Follows an explicit procedure. Does not need to infer intent or resolve ambiguity. | String substitutions, applying an explicit migration map, mechanical renames, transcription, format-fixed table rows, reformatting |
| **T1** | Bounded | Implements against a stated contract. Reasons locally across a handful of files. Recognizes when a spec does not cover a case and asks rather than guesses. | A module to a fixed API, a new script to a written spec, content migration under stated invariants, running and reporting a defined verification |
| **T2** | Open | Designs under ambiguity. Reasons across a whole system. Constructs adversarial cases nobody enumerated. Arbitrates between conflicting positions. | Architecture, contract design, adversarial verification, failure-mode enumeration, root-cause analysis, dispute arbitration |

### 3.2 Mapping table — maintained by the operating organization

**Owner:** the project's engineering lead (the same role assigned in
`PROPOSAL.md` §15.1). This table is empty in a document this doctrine
otherwise treats as binding, which is itself a defect while it persists:
filling it is a named **P0 deliverable** (`PROPOSAL.md` §15.1's P0 exit
criterion includes "every open question in §16 tagged 'P0' resolved," and
this table is one of them) — no dispatch under this doctrine is fully
auditable until it is filled, because "T1" names a role, not a verifiable
choice, while the row reads "*(fill in)*".

| Tier | Model | Notes | Reviewed |
|---|---|---|---|
| T0 | *(fill in)* | Cheapest model that reliably follows explicit procedures | *(date)* |
| T1 | *(fill in)* | Default working tier | *(date)* |
| T2 | *(fill in)* | Strongest available reasoning | *(date)* |

**This table MUST be reviewed whenever available models change.** A tier is a
role; the model filling it is an implementation detail. Referring to a model by
name anywhere else in the project is a doctrine violation — refer to the tier.

---

## 4. Effort tiers

Capability tier answers *which model*. Effort tier answers *how much reasoning
budget it is given*. They are independent axes and must be chosen separately.

| Effort | Name | Meaning | Use when |
|---|---|---|---|
| **E0** | Direct | Minimal deliberation; act on the instruction as written | The procedure is explicit and the answer is not discovered but applied |
| **E1** | Considered | Normal deliberation; plan, then act; check the result | Implementation against a contract, with local decisions to make |
| **E2** | Deep | Extended deliberation; enumerate alternatives, seek counter-examples, self-critique | Design, adversarial analysis, anything where the first plausible answer is often wrong |

Useful combinations, and what they mean:

- **T0/E0** — the cheapest possible dispatch. Correct only when the workload is
  a specified transformation with an explicit stop-condition.
- **T1/E1** — the default. Most implementation work lives here.
- **T1/E2** — a bounded problem with a nasty solution space. Cheaper than T2/E1
  and often better for well-scoped but tricky implementation.
- **T2/E2** — design, arbitration, adversarial verification. Deliberately
  expensive; use where being wrong is silent and costly.
- **T2/E0** — almost always a mistake. If the problem needs T2 capability, it
  needs deliberation. Flag this combination in review.

---

## 5. Automatic classification

Score the workload on seven signals. Each scores **0–3**. Sum to a total of
0–21.

### 5.1 The signals

| # | Signal | 0 | 1 | 2 | 3 |
|---|---|---|---|---|---|
| **A** | **Determinism of output** — how much is the answer fixed by the input? | Fully determined; one correct output | Minor formatting latitude | Several valid solutions; choice matters | Open-ended; the shape of the answer is part of the work |
| **B** | **Specification completeness** — how much must be discovered? | Exact contract supplied, including edge cases | Contract supplied, edges implicit | Goal stated, method to be chosen | Problem itself must be characterized |
| **C** | **Blast radius** — what happens if it is wrong? | One file, trivially reversible | Several files, reversible | Cross-cutting or hard to reverse | Destructive, irreversible, or changes a published contract |
| **D** | **Failure visibility** — how loudly does a mistake announce itself? | Immediate hard failure (compile/type error) | Test failure | Requires review to notice | Silent; may ship undetected |
| **E** | **Context breadth** — how much must be held at once? | 1 file | 2–5 files | 6–20 files | Whole system, or unbounded |
| **F** | **Domain novelty** — has this been done before here? | Routine, precedented pattern | Variation on a precedent | New combination of known parts | Genuinely novel design |
| **G** | **Specialist competence required** — bilingual, typographic, or archival-format correctness | None of these are load-bearing to the task | One is touched incidentally, and a mistake would be locally visible | One governs correctness (e.g. a bilingual field, a bibliography numbering rule) and a mistake could pass casual review | Multiple interact (e.g. a bilingual, typographically-locale-sensitive, archivally-validated field) or a mistake would be invisible without domain expertise |

Signal G exists because a project whose distinguishing requirement is
bilingual correctness has a rubric that is otherwise blind to bilingual
risk: a change can score low on A–F (one file, reversible, precedented
pattern) while still being exactly the kind of change a non-specialist
reviewer would pass without noticing that the Japanese rendering, the
archival metadata, or a typographic rule broke.

### 5.2 The mapping

| Score | Allocation |
|---|---|
| **0–3** | T0 / E0 |
| **4–7** | T0 / E1 — or T1 / E0 if signal B ≥ 2 |
| **8–12** | T1 / E1 |
| **13–15** | T1 / E2 |
| **16–21** | T2 / E2 |

**On the boundaries, after adding signal G.** Adding G raised the maximum
possible total from 18 (six signals) to 21 (seven). Only the top band's
ceiling (18 → 21) was mechanically widened when G was added; the lower
boundaries (4, 8, 13) were reviewed at that time and kept as-is, deliberately
— they are stated as absolute risk thresholds tied to a concrete meaning at
each cut point (e.g., "4" is where a workload stops being purely mechanical
in aggregate; "13" is where it starts needing genuine deliberation), not as
proportional slices of the theoretical maximum, so they do not automatically
need to move just because the maximum did. This was a judgement call, not a
derivation, and it is recorded here rather than left implicit. One
consequence that follows directly and MUST be respected by anyone comparing
historical dispatch records: **a revision-1 score (six signals, max 18) is
not comparable to a revision-2-or-later score (seven signals, max 21)** —
the same workload can score differently across the two schemes purely
because G exists in one and not the other, independent of any change in the
workload itself. Do not average or trend scores across that boundary without
re-scoring the older ones on all seven signals first.

### 5.3 Mandatory overrides

These force a **minimum** of **T2 / E1** regardless of score:

1. Designing or changing a **published contract**: a port interface, a result
   schema, a persisted model schema, or an exit-code convention.
2. **Adversarial verification of a landing** — the pre-landing gate. Its tier
   follows the risk of the change under test, never the budget of the change
   that produced it.
3. Designing any **irreversible or destructive** operation.
4. **Security or supply-chain** work: artifact pinning, hash verification,
   credential handling.
5. **Arbitration** between conflicting specialist positions.
6. **Root-cause analysis** of a defect that escaped a gate.

These force a **minimum** allocation regardless of the total score:

7. **Any single signal scored 3** forces a minimum of **T1 / E1** — a
   workload cannot be dispatched at T0 merely because its *sum* is low if
   one dimension is individually at the top of its scale (an irreversible
   change touched in passing, or a signal-G-3 bilingual/typographic/archival
   risk, is not made safe by every other signal being 0).
8. **`D = 3` (a mistake would ship silently)** forces a minimum of **E2**
   regardless of tier — silent failure is exactly the condition under which
   effort, not capability, is what catches the mistake before it ships.

9. **Precedence: the escalation rules above (1–8) win over the T0/E0 permit
   below.** They are checked first, and if any applies, the permit below
   does not. A workload can satisfy both the permit's letter (an explicit,
   fully specified mechanical substitution) and one of rules 1–8 (most often
   rule 7, via a signal scored 3, or override 3's "irreversible or
   destructive") at the same time — a mechanical substitution is not made
   safe by being mechanical if what it substitutes sits on a destructive or
   irreversible path. **This is not a hypothetical conflict.** The project's
   own recorded data-loss incident (`PROPOSAL.md` §3.4) began as exactly
   this shape: a mechanical directory-cleanup instruction, dispatched
   without regard for its blast radius, that a T0/E0-shaped reading of the
   permit below would have re-authorized. Any coordinator reasoning that
   reaches for the permit below MUST first check it against rules 1–8; if
   both appear to apply, rules 1–8 govern.

These permit **T0 / E0** regardless of score, and only when none of rules
1–8 above applies (rule 9):

1. A mechanical substitution with an explicit stop-condition — the instruction
   states exactly what to find, exactly what to replace it with, and exactly
   what to do if the target is not found.

### 5.4 Worked examples

Drawn from real dispatches, with observed outcomes.

**Example 1 — replace an import path in two named files.**
A0 B0 C0 D0 E1 F0 G0 = **1** → T0/E0.
G honestly reviewed, not retrofitted: an import-path edit has no bilingual,
typographic, or archival-format dimension, so G0 is the correct score, not a
mechanical default.
*Outcome: 6 tool calls, 29 seconds, correct.* Contrast with the same work at
T1/E1 elsewhere in the same session: 46–106 tool calls. Correct classification.

**Example 2 — migrate a document tree against a supplied file-by-file map.**
A1 B0 C2 D2 E3 F1 G3 = **12** → T1/E1.
G was retrofitted to 0 in an earlier pass rather than honestly re-scored;
corrected here to 3 — the migration touches bilingual metadata, dates in both
locales, and archival fields simultaneously, which is G's own definition of a
3 ("multiple interact... or a mistake would be invisible without domain
expertise"). The corrected total (12, not 9) still lands in the 8–12 band, so
the allocation is unchanged at T1/E1 — and is now independently mandated by
§5.3 rule 7 as well (a single signal at 3 forces at least T1/E1), so the two
routes agree rather than conflict.
*Outcome: correct, with zero deviations from the map.* The map was what pulled
signal B to 0; without it, B would be 2–3 and the score would reach T1/E2.
**This is the doctrine's central lever: sharpening the contract lowers the
tier.**

**Example 3 — adversarially verify a landing containing a destructive delete.**
Override 2 applies → **T2/E2**.
*Outcome: found three independent data-loss paths, one a strict regression,
that two lower-tier passes had missed.* One required constructing a timing race
by hand. This is what the top tier buys, and why override 2 exists.

**Example 4 — triage 51 test failures as pre-existing or newly introduced.**
A2 B2 C2 D3 E3 F1 G0 = **13** → T1/E2 (all seven signals shown; the total is
exactly 13, not the previously asserted, unreproducible "13+"). A=2: whether
a failure is "pre-existing" is not mechanically determined — it requires
judgment about flakiness and accepted-known-failure status. B=2: the goal
was stated ("triage as pre-existing or new") but no baseline/method was
supplied, unlike example 2's explicit map. C=2: a wrong triage can wrongly
block or unblock a release gate — cross-cutting, not one-file. D=3: a wrong
triage is silent. E=3: correctly triaging requires the whole test-history
context, not a bounded file set. F=1: a routine pattern, but not fully
rote. G=0: no bilingual/typographic/archival dimension.
Dispatched implicitly at T1/E1 as part of a larger task.
*Outcome: 50 of 51 correct; the one error misclassified a permanent regression
as transient.* Correct score was 13 → T1/E2 minimum — and, independently,
§5.3's rule 8 (`D = 3` forces a minimum of E2) already mandated E2 regardless
of the total.
**This was a coordinator misclassification, and the doctrine assigns it to
the coordinator, not the agent.**

---

## 6. Coordinator obligations

1. **Classify before dispatching.** Score the seven signals. Record the score.
2. **Sharpen the contract before raising the tier.** A workload that scores
   high on signal B can often be brought down a tier by supplying the missing
   specification. This is nearly always cheaper than escalating, and it produces
   a reusable artifact.
3. **Split before you upgrade.** Prefer decomposing into a large mechanical part
   and a small reasoning part over running the whole thing at a high tier.
   Two cheap agents plus a clear contract usually beat one expensive agent.
4. **Fix shared contracts yourself, first.** Where several workloads depend on
   one interface, define it before dispatch so the lanes run in parallel rather
   than in series.
5. **Dispatch independent workloads together**, not serially.
6. **Never discount the gate.** See override 2.
7. **Record the classification** — see §8.
8. **Own misclassification.** If work comes back wrong because the tier was too
   low, that is the coordinator's defect. Re-dispatch at the correct tier and
   record the correction. Do not attribute it to the sub-agent.

---

## 6b. Capability is a separate axis from tier

Tier answers *how much reasoning* a workload needs. It does **not** answer
*what the agent is permitted to do*. These are independent axes, and a
coordinator must check both before dispatch.

An agent may hold a restricted tool set by design. A read-only reviewing agent,
for instance, deliberately holds no write capability, so that its verdicts stay
independent of the work it judges. Such an agent can be correctly tiered for a
workload and still be structurally unable to perform it.

**Binding rules:**

1. **Check capability before dispatching**, not after. "Does this lane hold the
   tools this workload requires" is a different question from "is this lane
   strong enough", and the second does not imply the first.
2. **A restricted agent refusing work it lacks the tools for is correct
   behaviour**, not obstruction. Re-route it; do not argue with it.
3. **A restriction is not lifted by an instruction.** A dispatch message cannot
   grant capability a lane does not have, and a lane must not achieve the effect
   by other means — for example, writing files through a shell when it holds no
   editing tool. A lane that circumvents its own restriction commits a graver
   fault than the coordinator who misrouted the work.
4. **Misrouting is the coordinator's defect**, exactly as misclassification is
   (§6 obligation 8). Record it in the §8 audit as a fourth defect kind:
   **capability mismatch**.

**Worked example (observed).** A coordinator dispatched document-editing work to
a read-only verification lane. The tier was defensible; the capability was not.
The lane refused, correctly noting that a mid-task instruction grants no
capability and that it would not obtain the effect by other means. The work was
re-routed to a lane holding editing tools and completed normally.

Cost of the refusal: one wasted dispatch. Cost had the lane instead complied by
circumventing its restriction: the independence of every verdict it had ever
issued would be open to question. The asymmetry is why rule 3 is absolute.

---

## 7. Anti-patterns

| Anti-pattern | Why it is wrong | Correct response |
|---|---|---|
| "Use the strongest tier, it is safer" | Pays a constant factor on every trivial edit; hides the fact that the contract was never written down | Score it; sharpen the contract |
| "Use the cheapest tier, we can review it" | Review costs more than the saving when failure is silent (signal D) | Score signal D honestly |
| Escalating after a failure without re-scoring | Repeats the misclassification next time | Record the corrected score |
| Discounting the verification tier because the change was cheap | The gate's tier follows the risk under test | Override 2 |
| T2/E0 | Capability without deliberation is the worst of both | Re-score effort |
| Naming a model instead of a tier in project documents | Breaks when models change | Refer to the tier; update §3.2 |
| Dispatching a workload the coordinator cannot specify | Guarantees guessing | Finish coordinating first |

---

## 8. Recording and audit

Every dispatch records, in the task or its output:

```text
workload:   <one line>
signals:    A? B? C? D? E? F? G?  = <total>
allocation: T? / E?
override:   <none | which override applied>
rationale:  <one line, only if the allocation departs from the score>
```

**Audit rule.** Any bounce — work returned as incorrect — triggers a
classification review. Determine whether the failure was:

- a **misclassification** (the score was wrong, or a signal was scored
  optimistically), or
- a **specification defect** (the score was right but the contract was
  incomplete), or
- an **execution defect** (correct tier, correct contract, wrong output).

Record which. Over time this distribution tells the organization whether it is
under-tiering, under-specifying, or genuinely at the limit of a tier — three
problems with three different remedies.

---

## 9. Relationship to the other doctrines

- `SOFTWARE-ENGINEERING.md` §"Agentic use does not relax validation": an agent
  is an ordinary client. Cheapest-able governs **who does the work**; it never
  governs **what the system accepts**. A T0 dispatch and a T2 dispatch are
  validated identically by the core.
- `TESTING.md`: the tier of a testing workload follows the risk of the code
  under test. Writing a fault-injection suite for a destructive operation is
  T2 work even though "writing tests" sounds routine.

---

## 10. Summary card

```text
score seven signals 0-3:  A determinism   B specification   C blast radius
                          D failure visibility   E context breadth   F novelty
                          G specialist competence required (bilingual /
                          typographic / archival-format)

 0-3  -> T0/E0        13-15 -> T1/E2
 4-7  -> T0/E1 (or T1/E0 if B >= 2)     16-21 -> T2/E2
 8-12 -> T1/E1

override to >= T2/E1:  published contract · pre-landing gate · destructive design
                       · supply chain · arbitration · post-escape root cause

any signal scored 3:   forces a minimum of T1/E1
D=3 (silent failure):  forces E2

before escalating:     sharpen the contract, or split the workload
after a bounce:        re-score, and record which of the three defect kinds it was
always:                the gate's tier follows the risk under test
```

---

## Appendix — Revision log

| Rev | Change |
|---|---|
| 1 | Initial doctrine: the rule, capability/effort tiers, automatic classification, coordinator obligations, anti-patterns, recording and audit |
| 2 | §10's summary card fixed to include the "or T1/E0 if signal B >= 2" branch already present in §5.2 (I1); added a seventh signal, G — specialist competence required (bilingual / typographic / archival-format), §5.1 (I2); added §5.3 rules 7–8 — any signal scored 3 forces a minimum of T1/E1, and D=3 forces a minimum of E2 (I3); assigned an owner-role and a P0-deliverable status to §3.2's empty tier-to-model mapping table, cross-referenced from `PROPOSAL.md` §15.1 (I4). No other section of this doctrine was touched. |
| 3 | *(No entry.)* This document was not touched in revision 3 of the document set; the row is kept so the gap between 2 and 4 is explicit rather than silent. |
| 4 | Finished propagating signal G (added in revision 2, §5.1) into the rest of the workflow it never reached: §6 obligation 1 now says "seven signals," not "six"; §8's recording template now shows a `G?` slot. Added §5.3 rule 9: the escalation rules (1–8) explicitly win over the T0/E0 mechanical-substitution permit when both could apply to the same workload — the observed data-loss incident (`PROPOSAL.md` §3.4) is cited as the non-hypothetical case this closes (a mechanical directory cleanup on a destructive path). §5.4's worked examples re-scored honestly on G rather than left at a retrofitted G0: example 2 corrected from G0 to G3 (bilingual metadata + dual-locale dates + archival fields, meeting G's own definition of 3; total 9 → 12, allocation unchanged at T1/E1, now also independently mandated by rule 7); example 4 rewritten to show all seven signals summing to a reproducible 13 (was: two signals shown, asserting an unreproducible "13+"); example 1 confirmed (not changed) with an explicit note that G0 was reviewed, not defaulted. §5.2: added an explicit note that the band boundaries (4/8/13) were reviewed and deliberately kept as absolute thresholds when G raised the maximum from 18 to 21 (only the top band's ceiling moved), and that revision-1 (six-signal) scores are not comparable to revision-2-or-later (seven-signal) scores without re-scoring. |
| 5 | Final coherence sweep. The status line stated no revision number at all despite this log's existing rows — added "Revision 5" and filled the previously silent gap at revision 3 (row above) so the log is contiguous. Cross-references and terminology checked against the rest of the set; no other content changes. |
