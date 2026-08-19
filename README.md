# Python Engineering Discipline

One discipline for robust Python, built for agents to load, navigate and enforce.

Agents start at **`discipline/KERNEL.md`** (~1,800 tokens). It carries the thesis, the
fifteen always-apply invariants, a router table, and the two commands that replace reading
speculatively. Everything else is loaded on demand.

## Why it is shaped this way

It replaces eleven guideline documents (~113,000 tokens) accumulated from several disjoint
projects. As a set they could not be used: four genres were mixed with no marking, ~35
contradictions ran between them, ~130 references pointed at files that did not exist, and
most of what they mandated was checked by nothing.

Three ideas do the work:

**Genres are separated.** `law/` holds binding rules and the mechanisms that decide them.
`fact/` holds dated, sourced truth about Python and its tools. `frame/` holds vocabulary and
reasoning scaffolds and prescribes nothing. `ops/` covers agent dispatch. Each decays at a
different rate, and mixing them is what made the sources unusable. It also dissolves their
sharpest conflict for free: **law never pins a version; every pin lives in `fact/` with a
`verified:` date**, so a rule outlives its tools.

**Rules are addressable.** Every rule has a stable id (`ARCH-002`, `DIAG-005`), a force tag,
and a tag naming the tool that enforces it — all on one line, so `grep '^### '` yields the
entire rule surface with no body text. Ids are citable in reviews, commits and error
payloads. The sources referenced each other positionally, and those references broke.

**Rules ship with mechanisms.** The governing axiom is that anything mechanically
verifiable shall be mechanically verified. `[ADVISORY]` means no mechanism was found and
carries a written justification; `enforce/ENFORCEMENT.md` reports the unenforceable surface
and the mechanisms still to build, so the gap is tracked rather than assumed closed.

## Navigating it, and remembering what it taught

Two systems, one graph. The **navigation graph** is a directed typed multigraph over
modules, rules, mechanisms, layers, decisions and triggers — 573 nodes and 1,162 edges,
generated from the corpus and byte-stable. Agents never load it; they ask `tools/nav.py`,
which returns a few hundred tokens: what to read, why, and what it costs.

The **learning database** is the second layer, overlaid at query time. Agents record what a
session discovered — a project constraint, an error-to-fix mapping, a rule that was
ambiguous here — and later sessions get it back when the triggers match. It is a staging
area for mechanisms, not a notes pile: an entry that can become a check becomes one and
retires. `learning/ledger.jsonl` is the committed record; the SQLite index is derived and
gitignored, and drift between them is a validation error.

```bash
python tools/nav.py context --file src/pkg/adapters/fs.py --error "..."
python tools/nav.py applies src/pkg/domain/outline.py     # 15 rules govern this file
python tools/nav.py why ARCH-008                          # CONF-007 gave it this shape
python tools/learn.py retrieve --file P --error E
python tools/learn.py record --kind diagnostic --claim "..." --action "..." --trigger ...
python tools/learn.py calibrate                           # is any of this working?
doxygen enforce/Doxyfile                                  # the documentation gate
```

**Reachability is the navigability metric**: every one of the 183 rules is reachable from
some module within three hops, checked as `V092` on every validation run.

## Vendoring and integration

```bash
python tools/vendor.py install ../some-repo   # -> ../some-repo/.agent/
cd ../some-repo
python .agent/tools/integrate.py --dry-run    # read the plan
python .agent/tools/integrate.py              # announce it in CLAUDE.md / AGENTS.md
```

Two steps, because they have different blast radii. **Vendoring** writes only inside
`.agent/`. **Integration** writes files the project owns — `CLAUDE.md`, `AGENTS.md`,
`.claude/settings.json`, `.gitignore` — so it is plan-then-apply, and `--dry-run`
truncates the same code path rather than predicting it from a second one.

Integration manages one delimited block. A repository with no configuration gets a minimal
file carrying the block and nothing else; a repository that already has one gets the block
appended with **every byte outside the markers preserved**. Running it twice changes
nothing the second time, `--check` reports a missing or stale block for a consuming
repository's own gate, and `--remove` takes the block, the permission entries and the
ignore lines back out. `.agent/INTEGRATION.md` is what an agent reads when told to wire it
in.

```bash
python tools/vendor.py check   ../some-repo   # local edits to read-only files
python tools/harvest.py        ../some-repo   # discipline-level findings, upstream
python tools/release.py                       # -> dist/agent-discipline-v3.2.0.zip
```

`release.py` builds the redistributable archive by running `vendor.py install` against a
scratch repository, so what ships is what the installer writes and not a hand-assembled
copy. It prunes caches and databases, refuses to build if the learning ledger would ship
non-empty, scans every member for absolute paths and credential shapes, and emits a
byte-reproducible zip whose members are `.agent/` plus `INSTALL-DISCIPLINE.md` and the
release notes. Unzipped at a repository root it lands exactly where `integrate.py` expects.

`.agent/discipline/`, `.agent/enforce/` and `.agent/tools/` are upstream-owned and replaced
wholesale on update. `.agent/learning/` and `.agent/overrides/` are project-owned and never
touched. A content-hash manifest makes a local edit to a read-only file visible rather than
silently carried, and `harvest` exports `scope: discipline` findings as a report plus
proposed rule text for review.

## Layout

```
discipline/
  KERNEL.md          always loaded: thesis, invariants, router, precedence
  INDEX.md           generated: one line per rule
  rules.json         generated: the same, for jq
  KERNEL.md          also the navigator card and the learning loop
  graph.json         generated: the navigation multigraph
  law/               ARCH TYPE ERR DIAG EFCT TEST API DEP FLOW LEARN
  fact/              py-typing py-testing py-errors py-logging   (dated)
  frame/             architecture spec
  ops/               ALLOC teams
  meta/              SCHEMA GLOSSARY CONFLICTS OPEN PROVENANCE edges.yaml
enforce/
  templates/         copied into a consuming project, never live here
    pyproject.toml   ruff / mypy / pyright / pytest / coverage / mutmut
  importlinter.toml  layer, purity, independence contracts (needs --config)
  checks/            AST checks for what no linter covers, with failure proofs
  ENFORCEMENT.md     generated: every rule against its mechanism
learning/            schema.sql  config.toml  ledger.jsonl  INDEX.md  calibration.md
tools/               validate.py build_index.py build_graph.py nav.py learn.py
                     vendor.py integrate.py harvest.py build_provenance.py release.py
packaging/           INSTALL-DISCIPLINE.md, the archive-root pointer for adopters
INTEGRATION.md       what an agent reads when told to wire the discipline in
sources/             the eleven originals, frozen and superseded
.claude/skills/python-discipline/   the same discipline as a Claude Code skill
```

## Using it in a project

Copy `enforce/templates/pyproject.toml` and `enforce/importlinter.toml` into the target project and
replace the placeholder package name; copy `enforce/checks/` alongside. The configuration
comments name the rule ids each stanza enforces, so a lint failure traces back to a rule
and a rule traces forward to the check that decides it.

## Working on the discipline itself

Requires the conda environment named `claude`.

```bash
python tools/build_index.py       # refresh tokens:, INDEX.md, rules.json, ENFORCEMENT.md
python tools/build_graph.py       # then the graph, which reads those token counts
python tools/build_provenance.py  # regenerate the source-section ledger
python tools/validate.py          # must exit 0
python -m pytest -q
```

Order matters: `build_index` rewrites the `tokens:` field `build_graph` reads.

`discipline/meta/SCHEMA.md` is the file format and the rule grammar; `tools/validate.py`
implements it, and where the two disagree the validator is the defect. Each of its checks
has a proof-of-failure test in `tools/test_validate.py` — the corpus's own anti-vacuity rule
turned on its tooling. Generated files carry a banner; edit the source module and rebuild.

## Known gaps

Stated here rather than discovered later, because the axiom cuts both ways.

- **`V080` is 14, and it was 0 for the wrong reason.** For two releases this section said
  every binding rule was decided by something that runs. It was not. `V080` resolved a
  `check:foo` tag by asking whether `enforce/checks/foo.py` *exists*, never whether that
  check claims the rule — so a rule could tag any check in the repository and count as
  decided. Eight checks named seventeen rules they can never report, **five of them saying
  so in their own docstrings**. The tag now resolves against the check's own `rules` tuple.
  Of the twenty that surfaced: one was a duplicate and was retired, one was built, four
  were retagged `[ADVISORY]` because no machine can decide them, and **14 remain binding
  and unbuilt** — which is what this number is for. `enforce/ENFORCEMENT.md` carries the
  census; 164 binding rules, 19 advisory, 115 mechanized.
- **A mechanism existing is not a mechanism discriminating.** `D` counts rules observed
  rejecting a concrete thing: **20 of 164**. The other 144 have a mechanism nobody has
  watched work. `ARCH-013` is why this is measured — `mechanized` its whole life, and it
  reported nothing against four real domains modelled entirely in pydantic.
- **Provenance is at document granularity.** All 324 source sections are accounted for, but
  that proves no document was dropped, not that every individual claim survived.
- **This repository's own Python carries 113 residual lint findings**, ratcheted. Under
  `select = ["ALL"]` and ruff 0.16.3 the count was 275 at the start of v1.1.0; the eight
  `C901` findings — self-violations of `ARCH-016`, which this corpus enforces through that
  exact ruff code — were fixed by decomposition, every safe autofix was applied, and
  type-only imports were moved. `D401` was resolved the other way: it demands an imperative
  where `DOC-009` asks for the noun phrase that states an accessor's contract, so it is
  ignored in the template with that conflict written down. What remains is style debt,
  held by `tools/lint_baseline.json` — the exact `(file, code)` pairs, so raising one
  integer cannot switch the gate off, and **no ruff code that decides a binding rule may
  enter it**, checked before the baseline is consulted at all.
- **The documentation gate does not prove documentation is *true*.** All 135 covered files
  pass presence, style and behaviour-preservation, but a reviewer pass over an earlier
  version of the same files found roughly 90 claims that were confidently false about the
  code they described. Those were never itemized, and that list has still not been
  reconstructed. Presence and truth are separate properties; only the first is mechanized.
  `DOC-013` names the second and leaves it to review, which is honest but not sufficient.
  What has been re-checked since is narrower and worth stating exactly: the numeric claims
  in this file, which have now been found stale twice — both times by the work that made
  them stale, and both times only because somebody went looking.
- **The learning database holds 102 learnings and 3 reported outcomes**, so retrieval
  precision is a real number — 67% — on a sample far too small to act on, and two
  learning has been promoted. The loop closed for the first time when a validation batch
  retrieved before running and reported after; nothing yet *prompts* that, so it remains a
  habit rather than a mechanism, and a habit is what `V096` exists because nobody keeps.

## Auditing the merge

- `discipline/meta/CONFLICTS.md` — every contradiction between the sources, its resolution
  and the reason. Includes the cases where a source was simply wrong and was corrected
  rather than averaged.
- `discipline/meta/PROVENANCE.md` — all 324 source sections and where each went.
- `discipline/meta/OPEN.md` — decisions taken during the merge, with reasoning, and the one
  left open with what it blocks.
- `sources/SUPERSEDED.md` — the originals, and why they must not be read as guidance.
