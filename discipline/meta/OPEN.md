---
id: meta/OPEN
kind: meta
title: Open Decisions
tokens: 3971
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

### OPEN-003 · mutmut as the mutation engine

The sources mandated mutation testing and then declined to name an engine, which left the
requirement unenforceable. mutmut is chosen for having a workable incremental mode over a
pytest suite. The requirement is on the capability, not the tool, so the pin lives in a
`fact` file and can be swapped without touching any rule.

### OPEN-004 · pytest-socket for network isolation

Left open in the sources as "a dedicated plugin vs a hand-rolled `monkeypatch` autouse
fixture". The plugin is chosen: it fails closed by default, which a fixture someone
forgets to request does not.

### OPEN-005 · Two type checkers, both pinned

mypy and pyright infer differently, and a claim that survives both is stronger than one
that survives either. The second checker is treated as a differential oracle rather than
redundancy.

### OPEN-006 · The capability-tier to model mapping

The mapping is **declared by the operating organization, and its use is checked by the
corpus.** `overrides/allocation.toml` carries the table; `check:allocation_declared`
requires that a mapping exist and that every dispatch record cite a tier it resolves.
[ALLOC-010] is retagged `[BINDING]`.

*The objection this had to answer, and does:* the table binds a tier to a model, and
[ALLOC-001] forbids naming a model in a project document — a model name is the
fastest-decaying fact in the system, and a corpus carrying one is wrong within months in a
file nobody thinks to re-check. Hard-coding it was never available.

*What changed:* `overrides/` is project-owned. The installer creates it once and never
writes it again, and `vendor.py` copies `discipline/`, `enforce/` and `tools/` — not it.
So an adopter's model names stay in the adopter's tree and the corpus still names none.
This is the same shape `[tool.agent-discipline]` used to make `DOC-002` conditional
without weakening it: **declare it, then be checked on it.**

*What is still not checked, stated so nobody reads more into this than it says:* whether
the mapping is any GOOD — whether `T2` really is the strongest model available — is
unknowable from here and belongs to whoever owns the file, which is why the template
carries an `owner` field. What is now knowable, and was not, is whether a dispatch cites a
tier that means anything. That was the half `OPEN-006` called unauditable.

*Consequence:* a repository that dispatches nothing needs no mapping and the check stays
silent on it. A repository that dispatches at a tier resolving to nothing now fails.

### OPEN-007 · Documentation comments on every element, for Doxygen

**This reverses a decision this repository previously made and justified.**
`enforce/templates/pyproject.toml` used to ignore the missing-module-docstring rules, with the
reason: *"a blanket requirement produces ceremonial docstrings that say nothing, which is
worse than none."* That objection is real, and it is not answered by pretending it is not.

The requirement is now universal: every element of the code carries a documentation
comment, written for a full-featured Doxygen, present whether or not documentation is ever
generated. The ceremony objection is answered by rules rather than by an exemption —
[DOC-009] rejects documentation that merely restates the identifier, and [DOC-013] asks for
one accurate sentence rather than a padded block. A rule against filler is a better answer
than a licence to omit.

*Consequences, all decided here:*

- **Docstrings where Python has a slot; `##` blocks where it does not.** Python offers no
  docstring slot for a module constant, class attribute, dataclass field or enum member, and
  Doxygen reads `##` blocks for exactly those. A `##` block on a function would be invisible
  to `help()` and to every other Python tool, so it is prohibited there.
- **`PYTHON_DOCSTRING = NO`.** Otherwise a docstring full of `@param` renders as literal
  text and nothing warns. Set once in the Doxyfile rather than trusted to a `"""!` marker an
  author will eventually forget.
- **No pydocstyle convention, and three ruff rules disabled.** A convention makes the linter
  demand Google- or NumPy-style section headings that Doxygen cannot read without an input
  filter. `docstring-missing-returns`, `-yields` and `-exception` are disabled for the same
  reason; the engine's own `WARN_NO_PARAMDOC` is a stricter test, since it also catches a
  documented parameter that does not exist.
- **The rendered documentation tree is not committed** — the one deliberate exception to
  [DEP-011], recorded as a tension because it genuinely is one. The reviewable artefact here
  is the comment in the source, and a large rendered tree in every diff is how reviewers
  learn to wave generated output through.

*Cost, stated plainly:* this repository's own code does not yet comply — 441 findings at
the time of the decision. The mechanisms are in place so the gap cannot grow, and the
migration is real work that has not been done.

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

`tools/test_vendor.py` takes a greenfield temporary repository through install → integrate
→ gate → check → remove, asserting every byte outside the managed markers survives in both
line endings. That is a **synthetic** adopter: the machinery, once, on an empty tree. It
does not exercise checks meeting code nobody wrote to satisfy them, or an update landing on
a tree with local history. Every defect found in these mechanisms was found by contact with
unfamiliar code.

*Closes when:* one repository depends on this in daily use and reports back. The last
untested claim, and the one most likely to be expensive.

### OPEN-012 · Mutation testing cannot run on the maintaining platform

`TEST-013` is `external` on `auto:mutmut`. mutmut 3.3.1 does an unconditional module-scope
`import resource`, which is Unix-only, so it fails before parsing an argument. Not pinned:
a lock demanding an unusable package is worse than an absent one.

*Closes when:* a Unix runner exists, or a win32-capable engine is chosen and `OPEN-003`
revisited. Until then `TEST-013` is delegated and undecided, and `ENFORCEMENT.md` says so.

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

The defect that made `V080` read 0 for two releases, on the side that cannot yet be
checked. A `check:` tag now resolves against the check's own `rules` tuple — a module that
exists but does not claim the rule decides nothing about it — and that correction found
seventeen rules claimed by checks that could never report them. A fitness function declares
no rule list, so its tag is still resolved by asking whether a function of that name
exists.

**64 rules rest on a `fitness:` tag and none is discriminated.** `V080 = 14` is a floor,
not a count.

*Closes when:* the discrimination matrix covers fitness-decided rules, which the
`DISCIPLINE_REFERENCE` seam now makes possible.

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
