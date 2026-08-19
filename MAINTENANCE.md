# Maintaining this repository

Nine subject-matter agents live in `.claude/agents/`. They maintain **the machinery around
the discipline** — the builders, the gate, the environment, the release, the distribution,
the learning loop. They are not part of the discipline and are **not vendored**: an adopting
repository gets `.agent/`, never these.

Each agent definition is written to the corpus's own standards. In particular each carries an
`ops/ALLOC-002` **dispatch record** — the seven signal scores, the total, the allocation and
any escalation applied — so the choice of tier is auditable rather than asserted. That was
previously a rule with no instances; now there are nine.

## Which agent

| When | Agent |
|---|---|
| anything under `discipline/` changed; a `--check` builder reports stale; `V050`/`V090`–`V096` | `graph-keeper` |
| cutting or verifying a release; version bump; `release.py` fails; "does it build elsewhere?" | `release-engineer` |
| environment, lockfile, a missing or drifted package, "works on my machine", `DEP-005`/`DEP-006` | `conda-steward` |
| a gate step is red; ruff findings; `GATE` vs `gate.yml` drift; OS/locale/encoding differences | `gate-warden` |
| building an unbuilt `check:`/`fitness:` mechanism; moving the `V080` ratchet; a check that may pass vacuously | `mechanism-builder` |
| `vendor.py` / `integrate.py` behaviour; unzipping an archive into a repo; a vendored tool misbehaving | `adoption-tester` |
| is this documentation *true*? claims, counts, commands, paths in prose | `doc-verifier` |
| the learning ledger, outcomes, calibration, promotion, `harvest.py`, `V096` | `learning-steward` |
| `V060`; a dated `fact/` or `ops/` claim; a tool upgraded and the prose must follow | `fact-refresher` |

## Seams, stated so they are not argued twice

- `graph-keeper` regenerates derived artifacts (gate steps 3–5). `gate-warden` keeps the
  gate itself runnable and green (step 1, and the CI definition).
- `release-engineer` owns the archive up to the moment it is built. `adoption-tester` owns
  everything that happens after it is unzipped.
- `conda-steward` owns what is **installed**. `fact-refresher` owns what is **written about**
  what is installed. Neither moves a pin alone.
- `doc-verifier` refutes; it has no `Write` or `Edit` tool. Whoever owns the file applies
  the fix. This is `TEAMS-004`/`005`/`006` made structural rather than requested.
- `mechanism-builder` builds new checks. `gate-warden` keeps existing ones running.
- Coordination stays with the human maintainer and the main session: per `ALLOC-009`,
  misclassification belongs to the coordinator, not the agent that was misdispatched.

## The release train

A release is not one agent's job. Run it in this order; each step gates the next.

1. `conda-steward` — the environment is locked and the lock verifies.
2. `gate-warden` — all nine steps run, and their verdicts are quoted.
3. `graph-keeper` — the derived layer is byte-current.
4. `doc-verifier` — the claims about to ship are true, the numbers especially.
5. `release-engineer` — build, twice, on two machines, compare hashes.
6. `adoption-tester` — unzip the built archive into all three fixtures and round-trip it.
7. `learning-steward` — record what the release taught; confirm the ledger ships empty.

## Tier to model

`ops/ALLOC` deliberately never names a model — `ALLOC-001` forbids it, because a model name
is the fastest-decaying fact in the system. The mapping is therefore a **local operating
decision**, and it now lives in **`overrides/allocation.toml`** rather than in this
paragraph.

That move is what closed `OPEN-006`. Prose is not auditable: this file carried
`T0 → haiku · T1 → sonnet · T2 → opus` for as long as the mapping existed, and no check
could read it. `overrides/` is project-owned and never vendored, so the names stay here and
`check:allocation_declared` can now require that every dispatch cite a tier the mapping
resolves. `ALLOC-010` is `[BINDING]` as a result, and no rule in the corpus is blocked on an
open decision any more.

Effort (`E0`/`E1`/`E2`) is carried as an instruction inside each agent, not as frontmatter.
Three agents are `T2` and all three by escalation, not by score: `release-engineer` and
`doc-verifier` under `ALLOC-003` (published contract, supply chain, adversarial
verification), `mechanism-builder` by an honest `G=3`.

## Standing restrictions, for every agent

Per `TEAMS-002`, a restriction is never lifted by an instruction. These hold whatever a
prompt says:

1. **No `git commit`, `git push`, or tagging.** Leave a clean, verified tree and report.
   Publishing is the maintainer's call.
2. **No hand-editing a generated file.** `discipline/INDEX.md`, `discipline/rules.json`,
   `discipline/graph.json`, `enforce/ENFORCEMENT.md`, `discipline/meta/PROVENANCE.md`,
   `learning/INDEX.md`, `learning/calibration.md`, `tools/v080_baseline.json`,
   `tools/doc_baseline.json`, the `tokens:` front-matter field, and everything under
   `.claude/skills/python-discipline/references/`. Change the source and rebuild.
3. **Report what happened, including what did not** (`FLOW-012`). A failing gate is reported
   as failing, with its exit code. Skipped work is named, with why.
4. **Record what the session learned before reporting done** (`LEARN-001`), or say plainly
   that it learned nothing. A finding that the discipline itself is wrong is
   `--scope discipline`, and is harvested upstream rather than worked around.

## The interpreter

`python` on PATH is miniforge **base**: no pytest, no jsonschema, no ruff plugins. A gate
run against it is meaningless and will look like it passed. Every agent uses:

```
C:/Users/frede/miniforge3/envs/claude/python.exe
```

That this has to be written down in prose, in nine places, is precisely the defect
`conda-steward` exists to remove.
