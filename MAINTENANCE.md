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
2. `gate-warden` — all eleven steps run, and their verdicts are quoted.
3. `graph-keeper` — the derived layer is byte-current.
4. `doc-verifier` — the claims about to ship are true, the numbers especially.
5. `release-engineer` — build, twice, on two machines, compare hashes.
6. `adoption-tester` — unzip the built archive into all three fixtures and round-trip it.
7. `learning-steward` — record what the release taught; confirm the ledger ships empty.

## Maintaining the v5 documentation mechanisms

The v5 source model has two deliberately separate owners. Doxygen parses structured entity
contracts and produces the browsable projection; the AST checks allocate narration to
local bindings and execution steps that Doxygen cannot represent. Do not make either layer
stand in for the other, and do not describe syntactic coverage as proof that prose is true.

After changing Python or its documentation, run `python tools/docgate.py --all`. The gate
executes entity coverage, narration, naming-model, and semantic-property checks over every
governed file. `tools/doc_baseline.json` is a content-bound behavior oracle, not a waiver
list: re-record an entry only for an intentional executable change, with a Git-resolvable
source ref and an explicit reason. Documentation-only edits must preserve the stored AST
fingerprint.

Changes to `enforce/Doxyfile`, the Doxygen or Graphviz pins, extraction allocation, warning
policy, or relationship requirements also require `python -m pytest
tools/test_doxygen_gate.py`. That suite executes Doxygen 1.17.0, inspects generated HTML and
XML, proves call/caller/dependency relationships, rejects remote assets, and reruns the
known parser defects. Run it through both development legs before changing the dated facts
in `discipline/fact/doxygen.md`.

The project-owned `documentation-model.json` is strict data. Generic tooling may validate
declared scopes, abbreviation mappings, naming dimensions, generated-name boundaries and
semantic-property patterns; it must not invent a project's vocabulary. Whenever a target
file changes after semantic review, refresh `adversarial-review.json` against the new
content digest rather than carrying forward a stale human conclusion.

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
   `.claude/skills/python-discipline/` or `.agents/skills/python-discipline/`. Change
   `skills/python-discipline/` and rebuild.
3. **Report what happened, including what did not** (`FLOW-012`). A failing gate is reported
   as failing, with its exit code. Skipped work is named, with why.
4. **Record what the session learned before reporting done** (`LEARN-001`), or say plainly
   that it learned nothing. A finding that the discipline itself is wrong is
   `--scope discipline`, and is harvested upstream rather than worked around.

## The interpreter

Do not infer the verifier environment from whichever `python` happens to be on `PATH`.
Windows maintenance starts through:

```
dev\windows.cmd <optional command>
```

It requires only Conda, creates or repairs the named environment from `environment.yml`,
and verifies the result independently. Linux and WSL maintenance starts through:

```
sh dev/docker.sh <optional command>
```

It requires only Docker, uses the same declaration in a digest-pinned image, and mounts
this checkout as the invoking uid/gid. With no optional command, either leg runs the full
source gate.
