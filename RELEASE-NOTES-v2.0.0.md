# Python Engineering Discipline — v2.0.0

One theme: **the corpus stopped asserting rules and started deciding them.**

At v1.0.0, 106 of 167 binding rules were decided by nothing. They read as obligations a
gate would catch, and no gate would — which is exactly the failure the sources this corpus
replaced had, and the difference was only that the gap was counted. It is now zero. Every
binding rule is decided by something that runs, and the mechanisms have been held against
code written by someone who had never read them.

```bash
python .agent/tools/integrate.py --dry-run    # preview; writes nothing
python .agent/tools/integrate.py              # apply
python .agent/tools/integrate.py --check      # CI: present and current?
python .agent/tools/integrate.py --remove     # uninstall
```

## Why this is a major version

**Upgrading will make your gate fail.** That is the whole point, and it is still a breaking
change. Fifty-five mechanisms that did not exist now run: 24 AST checks and 31 fitness
tests. Code that passed a vendored v1.x gate will not necessarily pass this one. Nothing
about your code changed; what changed is that the rules it was always held to are now
checked.

No rule id was renumbered or removed. Every `ARCH-002`-style citation in your review
comments and commit messages still resolves to the same rule.

Three other breaks, smaller and worth naming:

- `enforce/checks/project.py` introduces a `[tool.agent-discipline]` declaration. Projects
  that declare nothing keep the canonical four layer names and get no documentation-form
  rules — see below, because that is a **relaxation** and you may not want it.
- `CANONICAL_LAYERS` gained `ports`. A file under `ports/` previously resolved to
  `unknown`; it now resolves to `ports`.
- `check_env.read_pins` returns a four-tuple. Only relevant if you import it.

## The headline

**`V080`: 106 → 0. Every named mechanism is built: 87 of 87.**

What `mechanized` claims is narrow and stated plainly in the generated `INDEX.md`: a
mechanism *exists*, not that the rule is fully decided by it. `ARCH-012` is the worked
example. Overstating this would be the exact failure the corpus exists to refuse.

Fifteen rules remain unmechanized and this is the permanent floor by construction — the 14
advisory rules, unenforceable by definition, and `ALLOC-010`, which is `[OPEN]` and blocked
on `OPEN-006`.

## The rules met code they were not written for

A fixture written to satisfy a rule proves nothing about that rule. Every mechanism was run
against ~6,700 lines of hexagonal Python across four packages, written by someone who had
never read this corpus. **No rule needed changing. Five mechanisms did.**

- `layer_of` matched directory segments only, so a shell written as `cli.py` and
  `composition.py` at the package root resolved to `unknown` and every layer-scoped check
  skipped it. Eight files, silently. A check that finds nothing reads exactly like a check
  that finds nothing wrong.
- `ARCH-002` fired on `PurePosixPath`, which exists in the standard library *because* it
  cannot touch a disk, and on `datetime.date` imported as a type. The rule forbids
  importing what **can** perform I/O; these provably cannot. It was telling a careful
  author — one whose module docstring already argued the point — to stop using the tool
  built for the situation.
- `ARCH-012` fired on `zone == "test"` in a domain that classifies source files into zones.
  A string literal is not a test signal; a test signal is something the environment tells
  the program.
- `ARCH-013` **under-reported**, which is the dangerous direction. `BaseModel` was in its
  foreign-type list from the start and it reported nothing against four domains modelled
  entirely in pydantic — because it examined only function signatures, and inheritance is
  how a domain actually acquires a framework. It was caught only because import-linter
  found the same coupling from the graph side.

Every fix is pinned by a **pair**: the case that must stay silent and the case that must
still fire. Three of the five are narrowings, and a narrowing with only the first half is
how a check gets quietly disarmed.

## Documentation form is now opt-in

`DOC-002` and `DOC-007` — the `##` block and `@param` forms — are conditional on a declared
`doc_engine`. `DOC-001` and `DOC-003` stay universal: every element must still be
documented.

The evidence was blunt. Of 1,082 findings against that well-documented external codebase,
**1,064 were the form and not the absence** — 702 `DOC-007` because it documents in Sphinx
`:param:` style. A rule reporting a thousand findings against good documentation is not
enforcing documentation; it is enforcing Doxygen, and it should say which it is doing.

```toml
[tool.agent-discipline]
doc_engine = "doxygen"          # doxygen | sphinx | none.  Absent => none.

[tool.agent-discipline.layers]  # your segment names -> the canonical four
services = "app"
composition = "shell"
```

**No silent reduction.** A run with a rule switched off by declaration says so on stdout.
The surface is two keys wide and no rule can be switched off wholesale — a declaration that
became a general opt-out would be worse than no declaration.

`OPEN-008` records this as a refinement of `OPEN-007` rather than a reversal, and says
which half of it still stands. New rule `DOC-014` states the obligation that survives: a
project declares its engine and is held to that form throughout.

## The gate is nine steps

Two new steps, over a reference package that did not exist before:

- **import contracts** — `ARCH-001`–`004`, `ARCH-011`, `EFCT-012`, `API-004`, as
  import-linter contracts that actually run. `enforce/importlinter.toml` used an
  `[importlinter]` table where the tool requires `[tool.importlinter]`. It was never
  parsed. Eight rules marked `external` on the strength of it were decided by nothing.
- **types** — `mypy --strict` and pyright strict. Running both is `OPEN-005`'s decision and
  it earned itself immediately: pyright found two defects in the reference that mypy
  reported clean.

**Every tool wired in this release exits 0 when it checks nothing.**
`python -m importlinter.cli` imports a module with no `__main__` guard and returns success
having checked no contract. `mypy` on an unresolvable path reports "no issues found in 0
source files". `docgate --all` passes on a covered file with no baseline entry. So both new
steps are wrapped in a script that asserts **how much it examined**, and fails when the
count falls below what the tree holds.

`tools/gate.py` itself had the same defect: it was documented as runnable and had no entry
point, so `python tools/gate.py` printed nothing and exited 0. It now runs all nine steps
and names the ones that failed.

## Environment

`environment.yml` is a real lock: 11 pinned pip packages, one pinned conda package, and one
command that decides whether the running interpreter matches. `DEP-005` and `DEP-006` were
both `[BINDING]` and both decided by nothing, in a repository whose generated output
silently differed depending on what happened to be installed.

Doxygen 1.10.0 is installed, declared, and **verified by execution** — two `enforce/Doxyfile`
settings are consequences of defects verified at exactly that version. Installing it was not
enough: a conda environment puts native binaries on `PATH` only on *activation*, so the test
kept skipping against a machine where Doxygen was correctly present. Both the test and
`check_env.py` now look beside the interpreter first.

`mutmut` is **not** pinned and `TEST-013` stays undecided, for a harder reason than "not yet
wired": mutmut 3.3.1 does an unconditional module-scope `import resource`, which is Unix-only,
so it cannot run on Windows at all. `ENFORCEMENT.md` records that rather than implying a tool
runs.

## By the numbers, against v1.0.0

| | v1.0.0 | v2.0.0 |
|---|---|---|
| Binding rules decided by something that runs | 61 of 167 | **168 of 168** |
| Named mechanisms built | 32 of 87 | **87 of 87** |
| Gate steps | 7 | **9** |
| Test functions defined | 270 | **480** |
| Files under the documentation gate | 32 | **121** |

Each figure is read from the tagged tree, not recalled. Two measures are deliberately
absent from that table because they cannot be stated honestly as a comparison:

- **Test count.** 480 is the number of `def test_` functions, which is what v1.0.0 can be
  measured for. The suite *collects* 610, the difference being parametrized expansion —
  quoting one against the other would inflate the change.
- **Ruff findings.** `ruff.toml` is not the same file it was at v1.0.0, so the two counts
  answer different questions. What can be said within this release's own configuration: the
  lint gate started at 766 findings the first time ruff actually ran — it had been locating
  `ruff.exe` beside the interpreter, missing `Scripts/`, and skipping itself behind a green
  run — and the ratchet now stands at **113**, having only ever fallen.

## Known gaps, stated rather than discovered

- **No CI has ever run.** The three-OS workflow exists and is kept in step with the gate by
  a test, which is the most that can be done without executing it. Portability stays
  withdrawn to win32 / Python 3.13.14.
- **No second machine.** Two builds here are byte-identical; cross-machine reproducibility
  is untested.
- **The 14 advisory rules** are permanently unenforceable by construction.
- **Roughly 90 false documentation claims** were found by a review pass long ago and never
  itemized. That list has still not been reconstructed. What *was* re-checked this cycle is
  narrower: the numeric claims in `README.md`, several of which were stale by a full phase,
  and `CLAUDE.md`'s rebuild sequence, which omitted a step and would have failed the gate.
- **One real adoption.** The external validation exercised the *rules*; it did not exercise
  `vendor.py install` → `integrate.py` → daily use in a repository that actually depends on
  this. That remains the last untested claim.
- **`ops/teams.md` is dated 2026-06-17 and was only partly re-verified.** Its front-matter
  date deliberately did not move; the module records exactly which claims were re-checked by
  execution and which three still need a live dispatch.
