# Python Engineering Discipline — v3.0.0

**v2.0.0's headline claim was false, and this release is mostly the consequence of finding
out.**

That release said: *"Every named mechanism is now built: 87 of 87, and `V080` is 0. All 168
binding rules are decided by something that runs."* It was overstated by twenty, for a
reason that fits in a sentence — `V080` resolved a `check:foo` tag by asking whether
`enforce/checks/foo.py` **exists**, never whether that check claims the rule. So any rule
could tag any check in the repository and be counted decided.

```bash
python .agent/tools/integrate.py --dry-run    # preview; writes nothing
python .agent/tools/integrate.py              # apply
python .agent/tools/integrate.py --hooks      # run the gate before every push
python .agent/tools/integrate.py --check      # CI: present and current?
python .agent/tools/integrate.py --remove     # uninstall
```

## Why this is a major version

Four things break an adopter upgrading from v2.0.0:

- **`ALLOC-010` is now `[BINDING]`.** A repository with dispatch records and no
  `overrides/allocation.toml` fails a rule that previously did not bind.
- **The `allocation.toml` template is refused unedited.** v2.0.0 shipped
  `"your-strongest-model"`, which *resolves* — so copying the template and changing nothing
  satisfied the rule. It now ships `UNSET`, which the check rejects.
- **Two new gate steps**, and one needs a system binary: Doxygen 1.10.0. A tree without it
  fails the documentation-build step.
- `mechanism_is_implemented` and `enforcement_of` take a rule id. Only relevant if you
  import them.

Everything else is a relaxation: four rules moved `[BINDING]` → `[ADVISORY]`, and eight
checks were narrowed to what they actually report, so an adopter sees **fewer** findings,
not more. No rule id was renumbered or removed.

## The correction

Eight checks named seventeen rules they can never report. **Five of them said so in their
own docstrings:**

> `dispatch_recorded`: *"It cannot decide ALLOC-006 through ALLOC-009, which are about what
> the coordinator did before writing the record."*
>
> `error_channels`: *"It cannot decide whether a given failure is conceptually expected or
> exceptional — that is a judgement, and ERR-014 keeps a reviewer for it."*

The prose was honest the whole time. The `rules` tuple was not, and the tuple is what
nothing read. Resolving tags properly found four more: `ARCH-014`, `TYPE-004`, `TYPE-008`
and `TYPE-014` all tag `check:domain_purity`, which claims none of them.

A `check:` tag now resolves against the check's own `rules` tuple, parsed rather than
imported. `validate.py` and `build_index.py` both pass the rule id — they briefly disagreed
while only one was fixed, which is exactly the drift that function's docstring warns about.

**`V080` is 14, and it is a floor rather than a count.** See `OPEN-015`: 64 rules rest on a
`fitness:` tag, which is *still* resolved by existence alone because a fitness function
declares no rule list, and none of those 64 is discriminated.

## Two new numbers

**`D` — discrimination coverage: 20 of 164.** `V080` asks whether a mechanism exists; `D`
asks whether anyone has watched it **reject something**. Each entry in
`enforce/discrimination.py` declares one concrete mutation that must make one rule fire,
and states the finding or clause it comes from. Gate step 9, ratcheted.

It earns its place: six of the entries written so far were *wrong on first run* and the
runner said so — a record using `A3 B1` where the check parses `A=3 B=1`, a mutation
hitting a sibling rule's path, an insert that broke parsing.

**`R` — recovery cost, reported and never gated.** Twelve frozen defects drawn from real
code, each measured as: given only what a failing program printed, is a governing rule
reached, and at what reading cost. A benchmark wired into a gate becomes a target, so this
one is not (`OPEN-017`).

It found the corpus indexed 17 error triggers, **every one a ruff code or a contract name** —
the vocabulary its own gate emits. A Python traceback, a mypy line and a pytest failure
resolved to an entirely empty reading plan.

| | before | after |
|---|---|---|
| governing rule reached from program output | 4 of 8 | **8 of 8** |
| cost to reach it | 4,994 tokens | **57 tokens** |

## The Prime Directive's last hop

`DIAG-001`'s envelope has carried a `rule_ids` field since it was published and **nothing
populated it**, so the field that turns a diagnosis into a lookup carried nothing.

The reference's error families now name the rules they defend, `envelope.from_error`
propagates them, and `nav diagnose` takes an envelope — or raw error text, for a codebase
that has adopted none of this — and returns the governing rules' own words: statement,
rationale, the command that decides them, and the line to open.

```
$ nav.py diagnose --envelope failure.json
EFCT-007 [BINDING]  A multi-effect apply is journalled
    Where the substrate offers no all-or-nothing guarantee ...
    check  pytest enforce/fitness/test_effects.py::test_interruption_recovers
    open   discipline/law/EFCT.md:88  (law/EFCT)
COST  104 tok -- 2 rule(s), read in full
```

## Also in this release

- **Doxygen decides its rules.** Installed, pinned and version-verified since v2.0.0 — and
  the only invocation anywhere was `--version`. Now gate step 10, at 0.2 s, catching an
  `@param` that names an argument the signature does not have. It decides `DOC-005`,
  `DOC-010` and `DOC-011`; `DOC-007`'s `auto:doxygen` tag is removed, because
  `WARN_NO_PARAMDOC` is off and the tag was claiming a contribution the configuration
  cannot make.
- **The dependency register is derived.** `ARCH-004` shipped with `forbidden_modules = []`,
  which forbids nothing and passes on every tree — with a comment making the vacuity look
  deliberate. `tools/register_deps.py` derives it and `--check` fails closed.
- **The router answers ordinary questions.** It matched multi-word `load_when` phrases
  verbatim, so "adding a new dependency" reached nothing. Ten of twenty-one oracle cases
  failed on first run. Nineteen cases in `enforce/fixtures/routing.toml` now hold it to
  both recall and precision — including two queries that must reach *nothing*.
- **`OPEN-006` closed**, and `ALLOC-008` retired as a word-for-word duplicate of
  `TEAMS-002` — the first use of the supersession protocol.
- **The installer has a contract**, and a synthetic round trip: install → integrate → gate
  → check → remove, asserting every byte outside the managed markers survives, in both line
  endings.
- **`integrate.py --hooks`** points `core.hooksPath` at the vendored hooks, so the gate runs
  before a push. A pointer, not a copy: a copy forks the moment the discipline updates.

## Known gaps

Ten accepted defects are now numbered decisions in `discipline/meta/OPEN.md`, each with a
concrete closing condition, because an accepted defect with no exit is an excuse. The three
that matter most:

- **`OPEN-011` — no repository actually depends on this.** The round trip is synthetic. The
  last untested claim, and the one most likely to be expensive.
- **`OPEN-009` — no CI has ever run.** Every verdict came from one machine: win32, cp932.
- **`OPEN-015` — 64 rules rest on a tag nothing can verify.** Why `V080 = 14` is a floor.

Three warnings fire on every run and are meant to: `V051` (the kernel is at 91% of its
always-loaded ceiling), `V080` (14 binding rules decided by nothing), `V097` (6 reported
outcomes against 102 learnings). All true, all visible.

## By the numbers

| | v2.0.0 | v3.0.0 |
|---|---|---|
| Binding rules decided by something that runs | *claimed* 169 of 169 | **150 of 164** |
| `V080` | *claimed* 0 | **14** |
| `D` — rules watched rejecting something | — | **20** |
| Gate steps | 9 | **11** |
| Advisory rules | 14 | **19** |
| Tests | 610 | **696** |
| Accepted defects with a recorded exit | 0 | **10** |

The two numbers that fell are the two that were wrong. Nothing in the corpus regressed;
the measurement did, and now measures.
