# Python Engineering Discipline — v1.0.0

The first redistributable release. One archive, `agent-discipline-v1.0.0.zip`, unzipped at
the root of a repository, produces `.agent/` and two files beside it. From there, one
command announces the discipline to that repository's agent configuration.

```bash
python .agent/tools/integrate.py --dry-run    # preview; writes nothing
python .agent/tools/integrate.py              # apply
python .agent/tools/integrate.py --check      # CI: present and current?
python .agent/tools/integrate.py --remove     # uninstall
```

`INSTALL-DISCIPLINE.md` at the archive root is the short version; `.agent/INTEGRATION.md`
is the detail.

## What it is

A single Python engineering discipline written to be loaded, navigated and enforced by
agents rather than read cover to cover by people. It replaces eleven accumulated guideline
documents (~113,000 tokens) that contradicted each other in ~35 places and referenced ~130
files that did not exist.

Its thesis, and the reason for every rule in it:

> **A failure must be machine-diagnosable and machine-repairable.** An agent meeting a
> defect determines what broke, where, in which layer, against which contract, with which
> value, from the program's own output — and derives the fix without re-reading the
> codebase.

Deep error traceability is the diagnostic channel; least coupling, with every foreign
dependency behind one port at the edge, is what makes a diagnosis *localizing*. The
authoring axiom is that anything mechanically verifiable shall be mechanically verified,
and a rule that names no mechanism is marked as such rather than quietly counted.

## What is in it

| | |
|---|---|
| Rule modules | 28, across `law/` `fact/` `frame/` `ops/` `meta/` |
| Rules | 182 — 167 binding, 14 advisory, 1 blocked on an open decision |
| Binding rules with a mechanism that runs | 61 of 167 |
| Named mechanisms | 87, of which 32 are built |
| Navigation graph | 571 nodes, 1,151 edges, generated and byte-stable |
| Entry point | `.agent/discipline/KERNEL.md`, ~1,800 tokens |

- `discipline/` — the corpus. `KERNEL.md` first: thesis, sixteen always-apply invariants, a
  router table, precedence. Everything else is loaded only when the router says so, and
  each module's front matter carries a measured token count so the cost is known before the
  read.
- `enforce/` — the mechanisms. AST checks under `checks/`, fitness tests under `fitness/`,
  and the configuration templates a consuming project copies (`templates/pyproject.toml`,
  `importlinter.toml`, `Doxyfile`).
- `tools/` — `nav.py` (ask the graph instead of reading), `learn.py` (record and retrieve
  what sessions discover here), `validate.py`, `integrate.py`, `vendor.py`, and the
  generators for the index and the graph.
- `learning/` — project-owned and **empty**. Seeded with `schema.sql` and `config.toml`
  only; the ledger is yours from the first entry.
- `overrides/` — project-owned, for local waivers.
- `MANIFEST.json` — a content hash of every upstream file, plus the release name. `python
  .agent/tools/vendor.py check .` reports any vendored file edited in place.

Integration writes one delimited block into `CLAUDE.md` and `AGENTS.md`, merges a narrow
permission set into `.claude/settings.json`, and adds four derived paths to `.gitignore`.
Every byte already in a markdown file it appends to is preserved — trailing blank lines and
line endings included — and the block is written in whichever line ending that file already
uses. Running it twice changes nothing the second time.

`--remove` takes back only what the install record says was added. Applying writes
`.agent/integration-record.json`, naming the permission and ignore entries that were
genuinely absent beforehand and the blank line inserted before each block, and removal
consults that rather than filtering by value — an entry the project already had is the
same string as one the integrator would have added, so value alone cannot tell them apart.
A markdown file the integrator appended its block to comes back byte for byte. Where there
is no record, removal takes out the managed block but no permission or ignore entry at all,
and names what it left behind.

## Known limits

Stated here rather than discovered later. The corpus exists to remove the failure mode
where a document hides what it does not do, and a release note is not exempt.

**Most binding rules are not mechanically decided.** 61 of 167 (36.5%; `ENFORCEMENT.md`
rounds it to 37%) have every mechanism they name built and runnable. The other 106 read as
obligations a gate will catch, and no gate will — 55 of the 87 named mechanisms are
declared but not implemented. `discipline/rules.json` carries the true status per rule
(`enforcement: unbuilt` / `unmechanized`), `enforce/ENFORCEMENT.md` lists every one by
name, and `tools/validate.py` reports each as a `V080` warning on every run. **Treat an
unbuilt rule as advice, not as a gate**, until you build the mechanism. That is the
difference between this corpus and the documents it replaces: the gap is counted, not
assumed closed.

**`ruff check` on this repository's own tooling exits 1 with 272 findings.** Under
`select = ["ALL"]`, mostly `D401` imperative mood, `TC003` type-checking imports, unused
imports and `noqa`-form preferences. Style debt in the tooling, not contract violations —
but it means the corpus's own first gate is red, and shipping a linting discipline whose
author's tree does not lint clean is a fair thing to hold against it. The shipped
*template* configuration is not the source of these findings; this repository's
documentation-corpus layout is.

**The `ARCH` and `TEST` rule families have never been exercised against a real hexagonal
project.** They are the largest families and the ones carrying the thesis — ports and
adapters, the real/fake/faulty triad, the shared contract suite, the fault and property
layers. They were derived from the source documents and reviewed for internal consistency,
not validated by writing a service against them. Expect the first real adoption to find
rules that are ambiguous, over-specified, or wrong at the edges. Record those with
`learn.py record --scope discipline`; that is what the scope is for.

**Doxygen behaviour is pinned to 1.10.0.** `discipline/fact/doxygen.md` records
measurements taken against exactly that version on 2026-08-18, and two settings in
`enforce/Doxyfile` (`WARN_IF_UNDOCUMENTED` and `WARN_NO_PARAMDOC`, both off) are
consequences of defects verified there. A different Doxygen changes what those defects are.
`enforce/fitness/test_meta.py::test_doxygen_version_matches_recorded` catches the mismatch
— but only when Doxygen is installed; otherwise it skips and verifies nothing.

**The documentation gate proves presence, not truth.** Every covered file passes presence,
style and behaviour-preservation, all three of which run in CI. The Doxygen build passes
too, but it is run by hand: `docgate.py` deliberately excludes it, and the CI workflow
installs Doxygen only to check its version. So "passes Doxygen" is a measurement taken at
release time, not a property CI defends. A reviewer pass over the same files then found
90 claims that were confidently false about the code they described. `DOC-013` names
truthfulness and leaves it to review, which is honest and not sufficient.

**Provenance is at document-section granularity.** All 324 sections of the eleven source
documents are accounted for in `discipline/meta/PROVENANCE.md`. That proves no document was
dropped; it does not prove every individual claim survived the merge intact.

**The learning loop has no outcomes yet.** The mechanism works — record, retrieve, decay,
calibrate — but in the repository that built this release it holds several dozen entries and zero
reported outcomes, so retrieval precision is `n/a` and nothing has been promoted to a
mechanism. `learn.py calibrate` has a bootstrap protocol for an empty database and little
to say about a populated one that has never been queried. Your ledger starts empty, so you
begin where that measurement begins.

**Packaging limits, specific to this archive.**

- The archive ships `discipline/`, `enforce/`, `tools/` and `INTEGRATION.md`. It does
  **not** ship the Claude Code skill mirror that exists upstream at
  `.claude/skills/python-discipline/`. That mirror is now generated by
  `tools/build_skill_mirror.py` and is byte-identical to `discipline/`, with its drift
  checked in the gate -- but it is a second copy of the same corpus in a Claude-Code-specific
  layout, and an adopter who wants it can generate it themselves.
- `.agent/tools/` carries the whole authoring toolchain, test files included — the
  generators, the corpus validator and the source extractor. Most adopters need only
  `nav.py`, `learn.py`, `integrate.py` and `vendor.py`. Nothing breaks if the rest sits
  there unused, but it is more than you need.
- **`nav.py` requires PyYAML** (transitively, through the graph builder) even though it
  reads a generated JSON graph; `validate.py` additionally requires `jsonschema`, and
  `build_index.py` uses `tiktoken` when present. `learn.py` and `integrate.py` are
  standard-library only. No requirements or lock file ships with the archive, and there is
  no rule pinning these for a consumer.
- Python **3.11 or newer** (`discipline/fact/py-typing.md`); the tooling itself is verified
  on 3.13 on Windows only. A three-OS workflow (`.github/workflows/gate.yml`) covers Linux
  and macOS as well, but the repository has no git remote, so it has never executed.
- The archive is byte-reproducible: every member is stamped with a fixed timestamp, so
  rebuilding from the same corpus yields the same file. Rebuild with
  `python tools/release.py`.

## Verifying what you got

```bash
python .agent/tools/vendor.py check .     # any vendored file edited in place?
python .agent/tools/integrate.py --check  # block present and current?
python .agent/tools/nav.py context --file src/pkg/adapters/fs.py --error "..."
```

`MANIFEST.json` names both the release (`v1.0.0`) and a content hash over every upstream
file. The hash is what `--check` compares — a release name can be claimed, a hash can only
be computed.
