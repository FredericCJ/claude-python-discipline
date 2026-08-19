---
id: fact/py-logging
kind: fact
title: Python Logging Mechanics
tokens: 1509
load_when:
  - "log level"
  - "getLogger"
  - "basicConfig"
  - "NullHandler"
  - "handler"
  - "formatter"
  - "propagate"
  - "structlog"
  - "contextvars"
verified: 2026-08-18
decay: years
python: ">=3.11"
---

# Python Logging Mechanics

What the standard logging machinery actually does. The obligations are in [law/DIAG];
this is what makes them satisfiable.

---

## Severity

`ESTABLISHED` — there are **five emittable severities**: debug, info, warning, error,
critical, at numeric values 10 through 50 in steps of ten.

`ESTABLISHED` — a sixth named constant exists at zero, but it is a **sentinel meaning
"not set"**, not a severity. A logger left at it inherits its effective level by walking up
the hierarchy. Any specification enumerating six levels has conflated the constants with the
severities — a real defect one source document had to correct in place.

`ESTABLISHED` — the root logger defaults to warning, so info and debug records are
discarded unless the application configures otherwise. A library that assumes its info
records are visible is assuming a configuration it does not control.

## The object model

`ESTABLISHED` — four collaborating objects: the **logger** a record is created on, the
**handler** that emits it, the **formatter** that renders it, and **filters** that can drop
or enrich it.

`ESTABLISHED` — level gating happens **twice**: once on the logger, once per handler. A
record can pass the logger and be dropped by a handler, which is how one destination gets
debug and another gets warnings.

`ESTABLISHED` — retrieving a logger by the same name returns the same object. Naming a
logger after its module produces a hierarchy matching the package structure for free.

`ESTABLISHED` — records propagate up the hierarchy to ancestor handlers by default. The
ancestor's *level* is not re-checked during propagation — only its handlers' levels are.
This surprises people who set a parent level expecting it to filter children.

## Library discipline

`ESTABLISHED` — a library should add **no handler except a null handler**, attached to its
top-level package logger. The official guidance is explicit that handler configuration is
the application developer's prerogative.

`ESTABLISHED` — the convenience configuration function attaches a handler to the **root**
logger. Calling it from library code silently configures the host application, which is why
it is prohibited there.

`ESTABLISHED` — with no handler configured anywhere, a last-resort handler emits warnings
and above to standard error, so a record is not lost entirely.

`OPEN` — "no logging side effects at import time" is widely held and not stated in the
official documentation. It is adopted here as project policy, not cited as a language fact.

**This discipline is enforced by convention and review, not by the runtime.** A component
*can* configure the root logger and nothing stops it. [law/DIAG] mechanizes what can be
mechanized — the import-level shape — and the rest is a check, not a guarantee.

## Cost

`ESTABLISHED` — passing format arguments to the logger defers interpolation until the
record is actually emitted. An eagerly formatted string is built whether or not the level
is enabled.

`ESTABLISHED` — for genuinely expensive arguments, an explicit level check before the call
avoids computing them at all.

`VERSION-DEPENDENT` — linters commonly flag deferred-argument style and offer to rewrite it
to eager interpolation. That rewrite is wrong for logging, and the rule has to be configured
deliberately rather than left to collide. This is the concrete collision recorded in
[meta/CONFLICTS] and settled in `enforce/templates/pyproject.toml`.

## Context

`ESTABLISHED` — extra fields can be attached per call, or injected for all records by a
filter. Field names collide with the record's own attributes, and a collision raises.

`ESTABLISHED` — context-local variables propagate correctly across async tasks, which makes
them the right carrier for a correlation identifier. A thread-local does not.

`ESTABLISHED` — structured logging libraries build on this machinery rather than replacing
it, and can render through the standard handlers.

`OPEN` — full distributed tracing is out of scope for single-process work. Adopting it for
a single-process application buys complexity and no diagnosis. One source document deferred
this topic to another that declined it; the deferral is closed here rather than left
circular.

## Exceptions

`ESTABLISHED` — the exception-logging call attaches the active exception's traceback, and
is meaningful **only from inside a handler**. It also accepts an explicit exception
instance.

`ESTABLISHED` — logging an exception and then re-raising it produces the same stack trace
twice, once from the intermediate handler and once from the outer one. The duplicate is
strictly less informative than the original, and it makes one fault look like two.

## Security

`OPEN / widely held` — credentials, tokens and personal data must be redacted before
logging. This is universally accepted practice and is **not** stated in the official
logging documentation, so it is adopted here as policy rather than attributed to a source
that does not say it.

---

## Sources

Verified against the official logging documentation, its how-to guides and the library
cookbook on 2026-08-18. Claims tagged `OPEN` are explicitly *not* attributable to those
sources and are adopted as project policy. Re-verify when `verified:` exceeds the decay
window.
