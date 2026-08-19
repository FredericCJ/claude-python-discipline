---
id: meta/OPEN
kind: meta
title: Open Decisions
tokens: 2138
load_when: ["open question", "undecided", "which tool", "pin a version"]
decay: none
---

# Open Decisions

The axiom is that anything mechanically verifiable shall be verified, so an undecided
question is a defect with a cost, not a neutral state. This file exists to keep that cost
visible.

Two sections: decisions **taken**, with the reasoning, so they are not silently
re-litigated; and decisions **still open**, each naming what it blocks. Any rule tagged
`[OPEN]` must appear below, and `tools/validate.py` enforces that.

The source corpus deferred roughly fourteen decisions, several of them in circles — one
document deferred distributed tracing to a second, which declined it. Most are settled
here.

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

### OPEN-006 · The capability-tier to model mapping

`ops/ALLOC` classifies work onto capability tiers, but the table binding a tier to an
actual model is empty — it was empty in the source doctrine too, which called that "itself
a defect while it persists".

*Blocks:* [ALLOC-010], the rule that depends on it, is tagged `[OPEN]` rather than
`[BINDING]`. Until
the table is filled, a tier names a role rather than a verifiable choice, and a dispatch
under that rule cannot be audited after the fact.

*Deliberately not resolved here:* the mapping is an operating-organization decision that
changes with procurement and model availability, and hard-coding it would violate the same
doctrine's rule against naming models in project documents.

---

## How to close an item

Move it to **Taken** with the reasoning that decided it, retag the dependent rules from
`[OPEN]` to `[BINDING]`, give each a mechanism, and rebuild the index. An item closed
without its rules being retagged has not been closed.
