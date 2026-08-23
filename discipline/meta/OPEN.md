---
id: meta/OPEN
kind: meta
title: Open Decisions
tokens: 3950
load_when: ["open question", "undecided", "which tool", "pin a version"]
decay: none
---

# Open Decisions

The axiom is that anything mechanically verifiable shall be verified, so an undecided
question is a defect with a cost, not a neutral state. This file exists to keep that cost
visible.

Two sections: decisions **taken**, with the reasoning, so they are not silently
re-litigated; and **accepted defects**, which block no rule and each name what would close
them. Any rule tagged `[OPEN]` must appear below, and `tools/validate.py` enforces that.

---

## Taken

### OPEN-001 · Python floor 3.11, target 3.13

The sources assumed three different floors (3.11, 3.12–3.14, and unpinned). 3.11 is the
version at which `ExceptionGroup`, `except*`, `Exception.add_note`, `Self` and
`assert_never` all become available natively, so the whole diagnostic contract can be
expressed with no backport dependency. 3.13 is the tested target and the version in the
project environment.

*Consequence:* PEP 695 native generic syntax needs 3.12+ and is therefore advisory, not
binding, until the floor moves.

### OPEN-002 · pydantic v2 for boundary parsing

One source left the choice open between pydantic v1, v2 and hand-written parsing; another
already mandated v2. v2 is chosen: it is the maintained line, its `ValidationError`
carries structured, per-field detail that maps directly onto the diagnostic envelope, and
its validation survives `python -O` where an `assert` would not.

*Consequence:* v1 idioms are a migration defect, not a style preference.

### OPEN-003 · Cosmic Ray as the portable mutation engine

The sources mandated mutation testing and then declined to name an engine, which left the
requirement unenforceable. mutmut was initially chosen for its incremental pytest mode, but
its fork requirement made the resulting binding rule unsupported on native Windows. v4
replaces it with Cosmic Ray 8.7.0 and a repository-owned adapter that runs on Windows and
Linux, creates a throwaway source copy, requires a normal passing baseline, refuses zero
mutants, independently rejects abnormal or incompetent workers, and admits no survivors.
The requirement remains on the capability; the dated tool pin stays in `fact/py-testing`.

### OPEN-004 · pytest-socket for network isolation

Left open in the sources as "a dedicated plugin vs a hand-rolled `monkeypatch` autouse
fixture". The plugin is chosen: it fails closed by default, which a fixture someone
forgets to request does not.

### OPEN-005 · Two type checkers, both pinned

mypy and pyright infer differently, and a claim that survives both is stronger than one
that survives either. The second checker is treated as a differential oracle rather than
redundancy.

### OPEN-006 · The capability-tier to model mapping

**Closed in v3.0.0.** `overrides/allocation.toml` carries the table and
`check:allocation_declared` requires every dispatch record to cite a tier that resolves;
[ALLOC-010] is `[BINDING]`. The objection it had to answer was [ALLOC-001] — a corpus may
not name a model, because a model name is the fastest-decaying fact in the system. It does
not: `overrides/` is project-owned and `vendor.py` never copies it, so an adopter's model
names stay in the adopter's tree. Whether the mapping is any *good* remains unknowable from
here, which is why the template carries an `owner` field; whether a dispatch cites a tier
that means anything is now checked, and that was the half this record called unauditable.

### OPEN-007 · Documentation comments on every element, for Doxygen

This reverses an earlier exemption for supposedly ceremonial comments. Every element now
carries a useful documentation comment; [DOC-009] rejects identifier restatement and
[DOC-013] asks for accuracy instead of padding.

*Consequences:* use docstrings where Python has a slot and `##` blocks where it does not.
Engine details live in [fact/doxygen]. The rendered tree is not committed: the source
comment is the reviewable artifact, and generated bulk obscures review.

The repository initially carried 441 findings. The mechanisms keep that gap from growing.

### OPEN-008 · The Doxygen form is declared, not assumed

**This refines OPEN-007; it does not reverse it.** That decision made a documentation
comment on every element universal, and answered the ceremony objection with rules against
filler rather than an exemption. All of that stands.

What it did not separate is *that* an element is documented from *how the comment is
punctuated*. `DOC-002`'s `##` block and `DOC-007`'s `@param` are Doxygen's own syntax, and
they were required of every adopter.

The cost was measured rather than argued. Run over four independently written hexagonal
Python packages — about 6,700 lines, documented throughout in Sphinx style — the check
reported **1,082 findings, of which 1,064 were the form**: 702 `@param` tags absent where
`:param:` was present, 362 `##` blocks absent where the values were described in prose. The
18 real findings were invisible underneath. A check at that ratio is not read; it is
switched off, and `DOC-001` goes with it.

*Resolved:* `DOC-001` and `DOC-003` — every element carries a documentation comment — stay
universal. `DOC-002` and `DOC-007` apply under a declared engine that reads those forms.
`DOC-014` makes the declaration itself binding, because the failure being avoided is not
strictness but *silence*: an undeclared project must not look the same as a conformant one.

*Consequence:* this repository declares `doc_engine = "doxygen"` in its own
`pyproject.toml`. It was the first thing the change broke — without it, this corpus's
documentation gate quietly stopped deciding two of its four rules.

*Same shape, same fix:* `ARCH-001`'s four layer names had the identical defect. A project
naming its layers otherwise had every layer-scoped check skip its files while reporting
clean. The layer mapping lives in the same declaration.

### OPEN-020 · Contract evidence is semantic, representation is explicit

**Taken for v4.** The v3 real/fake/faulty file triad and universal structural `Protocol`
shape are retired. Each internal contract now selects structural or nominal typing,
registers real, controllable and scheduled-fault capabilities, and traces its operation
terms to one shared suite. One implementation may provide both test capabilities.

*Consequence:* filenames and class count decide nothing; [ARCH-024], [ARCH-025], and
[TEST-020] decide the locally observable properties.

---

## Still open

Known, costed, not fixable here as things stand. Each names what would close it: an
accepted defect with no exit is an excuse. Recorded here rather than in a README because
prose nothing checks has now been found stale twice.

### OPEN-009 · No continuous integration has ever run

The eleven-step, three-OS workflow has never executed. Every verdict this repository has
reached came from one machine: win32, cp932. `test_the_workflow_mirrors_the_gate` keeps the
file correct, which is not the same as run — and two real defects were found by reasoning
about other platforms rather than testing them, so the class is real.

*Closes when:* a remote exists and one matrix run is green. Portability stays withdrawn to
win32 / Python 3.13.14.

### OPEN-010 · No second machine has built the archive

Two consecutive runs produce byte-identical archives. That is determinism in one
environment, not reproducibility across environments. The lock pins by exact version, not
by wheel hash.

*Closes when:* a second machine builds the same commit to the same SHA-256.

### OPEN-011 · No repository actually depends on this

**Narrowed in v3.2, not closed.** Until this release a repository that already existed could
not adopt at all: `python -m checks` printed every finding and exited 1, with no baseline and
no ratchet. `tools/conformance.py` is the ratchet, validated by taking a copy of a real
124-module codebase through the whole trip.

*Measured rather than supposed:* **117 findings, none protected**, so the tree adopts. The
baseline was minted, the tree went green, and then — the assertion that matters — a new
violation of an already-baselined rule failed by name, and an `assert` used as validation
failed as [ERR-012] and [DIAG-009] **with the baseline in place**. A baseline that goes green
is easy; one that still catches the next regression is the feature.

*What it also found:* two of `PROTECTED`'s four entries could never fire, being decided by a
fitness test and a ruff code rather than by any check this tool runs — the vacuity this
repository exists to remove, reproduced inside the guard against it.

*Still not closed:* a copy driven through a script by its author is not a repository
depending on this in daily use. Nothing here has met an update landing on a tree with local
history, or a disagreement about a baselined finding.

*Closes when:* one repository depends on this in daily use and reports back.

### OPEN-012 · Mutation testing cannot run on the maintaining platform — closed

The original `auto:mutmut` mechanism could not run natively on Windows; current upstream
still requires fork support and directs Windows users to WSL. This was a mechanism defect,
not permission to narrow `TEST-013`. Closed in v4 by `OPEN-003`: `auto:cosmic-ray` is pinned,
run by the project gate on a throwaway copy, and held against real kill/survive control
experiments on the maintaining Windows platform. Independent Linux evidence remains a
release criterion rather than an excuse to call either platform unsupported.

### OPEN-013 · Three tools decide against one 26-file layout

mypy, pyright and import-linter run every gate — over `enforce/fixtures/reference/`: 26
files, one package, shell as a directory. Shape matters. `layer_of` matched directory
segments only, and a real codebase whose shell was `cli.py` and `composition.py` at the
package root had its whole shell skipped in silence — invisible against a fixture without
that shape.

*Closes when:* a second conformant fixture exists in a deliberately different shape, and
the three tools decide against both.

### OPEN-014 · The reference is written to satisfy the rules it validates

It is the positive case for 31 fitness suites, the subject of every mutation, and the
target of four tools. Written to conform, so validating against it proves it conforms. The
one independent check — a read-only pass over ~6,700 lines whose author had never read this
corpus — changed no rule and corrected five mechanisms: four over-reporting, one silently
under-reporting. Not repeatable; the code is not ours to vendor.

*Closes when:* a fixture exists that is deliberately *wrong* in the ways real code is
wrong, with an expected-findings manifest, so over-reporting is measured rather than
noticed by luck.

### OPEN-015 · A `fitness:` tag is resolved by existence alone

**Closed in v3.1.** A fitness function declares what it decides via `@decides`
(`enforce/decides.py`), and the tag resolves against that declaration exactly as a `check:`
tag resolves against the check's `rules` tuple. **An undeclared function decides nothing** —
treating a missing declaration as consent is how sixty-four rules came to rest on a tag that
only asked whether some file contained the text `def <name>(`.

Reading all forty tagged functions against what they claimed found sixteen claims that did
not hold — 20%, against the check side's 23%. `V080` stayed at 14. Superseded by `OPEN-019`.

### OPEN-019 · The decided set and the discriminated set are not the same set

`V080` asks whether a mechanism exists and claims the rule. `V098` asks whether anyone has
watched it work, and **93 of 142 decided binding rules have not been.**

The scar is [ARCH-013]: it named `BaseModel` among the framework types a domain may not
borrow, claimed the rule properly, was counted mechanized, and reported **nothing** against
four domains modelled entirely in pydantic — it read annotations and never bases. Nothing
here could have found that, because nothing had put something it should reject in front
of it.

`D` is 49, up from 20. A warning rather than an error, beside `V051`, `V080` and `V097`: a
gate failing for a reason nobody can clear that afternoon is one people run with
`--no-verify`. `tools/discrimination_baseline.json` carries a floor `D` may not fall below
and a ceiling the gap may not rise above.

*Closes when:* the gap reads as a list rather than a backlog, and a rule is decided if and
only if it has been watched rejecting something.

### OPEN-016 · Nineteen advisory rules are unenforceable by construction

`[ADVISORY]` is a debt, not a category: no mechanism found, justification written. Five
were added deliberately when `[BINDING]` proved to be promising a gate that would never
fire. Some are judgements no machine can reach; others may yield to an instrument nobody
has thought of yet.

*Closes when:* a mechanism is found for one, moving it to `[BINDING]`; or it is retired
under the supersession protocol, as `ALLOC-008` was. Not by the count falling for its own
sake.

### OPEN-017 · The recovery-cost benchmark is not gated

`R` is measured by `tools/bench.py` and gated by nothing, so a regression in diagnosis cost
is invisible unless somebody runs it. **Deliberate, and recorded so it is not "fixed" by
someone tidying**: a benchmark wired into a gate becomes a target and stops measuring. The
frozen defect set is protected by `test_the_defect_set_is_frozen`, because the cheapest way
to improve `R` is to add defects the navigator already handles.

*Closes when:* nothing. Revisit only if `R` is found to have regressed unnoticed, which is
the risk being accepted.

### OPEN-018 · Roughly ninety false documentation claims were never itemized

A review pass found about ninety claims confidently false about the code they described.
The number was recorded; the list was not, and has never been reconstructed. What has been
re-checked since is narrower and should not be mistaken for it: the numeric claims and
named commands in the shipping documents, found stale twice — both times by the work that
made them stale.

*Closes when:* the ninety are reconstructed as a list, each confirmed or refuted. `DOC-013`
names the obligation and leaves it to review, which is honest and not sufficient.

---

## How to close an item

Move it to **Taken** with the reasoning that decided it, retag the dependent rules from
`[OPEN]` to `[BINDING]`, give each a mechanism, and rebuild the index. An item closed
without its rules being retagged has not been closed.
