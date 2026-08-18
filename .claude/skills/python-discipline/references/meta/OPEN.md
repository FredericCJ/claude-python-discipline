---
id: meta/OPEN
kind: meta
title: Open Decisions
tokens: 971
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

### Python floor 3.11, target 3.13

The sources assumed three different floors (3.11, 3.12–3.14, and unpinned). 3.11 is the
version at which `ExceptionGroup`, `except*`, `Exception.add_note`, `Self` and
`assert_never` all become available natively, so the whole diagnostic contract can be
expressed with no backport dependency. 3.13 is the tested target and the version in the
project environment.

*Consequence:* PEP 695 native generic syntax needs 3.12+ and is therefore advisory, not
binding, until the floor moves.

### pydantic v2 for boundary parsing

One source left the choice open between pydantic v1, v2 and hand-written parsing; another
already mandated v2. v2 is chosen: it is the maintained line, its `ValidationError`
carries structured, per-field detail that maps directly onto the diagnostic envelope, and
its validation survives `python -O` where an `assert` would not.

*Consequence:* v1 idioms are a migration defect, not a style preference.

### mutmut as the mutation engine

The sources mandated mutation testing and then declined to name an engine, which left the
requirement unenforceable. mutmut is chosen for having a workable incremental mode over a
pytest suite. The requirement is on the capability, not the tool, so the pin lives in a
`fact` file and can be swapped without touching any rule.

### pytest-socket for network isolation

Left open in the sources as "a dedicated plugin vs a hand-rolled `monkeypatch` autouse
fixture". The plugin is chosen: it fails closed by default, which a fixture someone
forgets to request does not.

### Two type checkers, both pinned

mypy and pyright infer differently, and a claim that survives both is stronger than one
that survives either. The second checker is treated as a differential oracle rather than
redundancy.

---

## Still open

### The capability-tier to model mapping

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
