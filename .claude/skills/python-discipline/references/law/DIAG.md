---
id: law/DIAG
kind: law
title: Diagnostics and Traceability
tokens: 2478
load_when:
  - "exception"
  - "traceback"
  - "logging"
  - "error message"
  - "error code"
  - "correlation id"
  - "add_note"
  - "raise from"
  - "what went wrong"
applies_to: ["**/*.py"]
requires: ["law/ARCH"]
decay: none
python: ">=3.11"
---

# Diagnostics and Traceability

The module the Prime Directive most directly demands. Everything here exists so that an
agent meeting a failure can answer *what broke, where, against which contract, with which
value* from the program's own output, and derive a fix without opening the source.

An error that is merely *raised* is hygiene. An error that is **localizing** is a
diagnosis, and the difference is entirely in what it carries.

---

## The diagnostic envelope

Every error that escapes to a process boundary serializes to one record, validated against
`enforce/schema/diagnostic.schema.json`.

```text
code            stable, namespaced, greppable    "pkg.domain.invariant.outline_cycle"
layer           domain | app | adapter | shell   where it originated
port            which contract was crossed       adapter faults only
operation       which call on that contract
expected        the predicate that was violated
actual          what was seen instead
value           the offending input, redacted
rule_ids        discipline rules implicated      ["TYPE-004", "ARCH-002"]
cause_chain     __cause__ walk, innermost first
notes           __notes__, context accreted on the way out
correlation_id  ties the record to its log lines
remediation     one line the reader can act on
```

### DIAG-001 · Every escaping error produces a valid envelope  [BINDING] [fitness:test_envelope_conforms]
An error reaching a process boundary MUST serialize to a record conforming to the
published schema, on every exit path.
- **Why** A schema-valid envelope is what makes automated repair possible at all; prose on
  stderr is not parseable and not actionable.
- **Check** `pytest enforce/fitness/test_diagnostics.py::test_envelope_conforms`

### DIAG-002 · Every custom exception carries a stable code  [BINDING] [check:exception_has_code]
Exception and result-error types MUST define a namespaced `code` class attribute. The code
is never embedded only in the message text.
- **Why** A greppable code survives message rewording and translation; a sentence does not,
  and every consumer matching on prose breaks silently when the prose improves.
- **Check** `python -m checks.exception_has_code`
- **See** [law/API]

### DIAG-003 · Error detail is carried in attributes, not interpolated away  [BINDING] [check:exception_has_code]
The offending value, the expected predicate and what was actually seen MUST be structured
attributes on the error. The message renders them; it is not where they live.
- **Why** An agent can compare `expected` to `actual`; it cannot reliably parse them back
  out of a formatted sentence.
- **Check** `python -m checks.exception_has_code`

### DIAG-004 · A code is a public contract  [BINDING] [fitness:test_codes_are_stable]
Renaming or removing an error code, or adding a variant to a result union, is a breaking
change and MUST be versioned as one.
- **Why** Automated diagnosis is only worth building against a surface that holds still
  across releases.
- **Check** `pytest enforce/fitness/test_diagnostics.py::test_codes_are_stable`
- **See** [law/API]

---

## Preserving the chain

### DIAG-005 · Every cross-layer re-raise uses explicit chaining  [BINDING] [check:raise_from]
When an exception is translated at a layer boundary, the new exception MUST be raised
`from` the original.
- **Why** The chain is the localization: without it, the outermost frame is all that
  survives and the true origin is gone.
- **Check** `python -m checks.raise_from`

### DIAG-006 · Context is accreted with notes, not by re-wrapping  [BINDING] [check:raise_from]
To add context while propagating, attach a note to the live exception. Wrapping an error
solely to append information is prohibited.
- **Why** Re-wrapping buries the type a caller matches on one level deeper each time;
  notes add context without changing what the error *is*.
- **Check** `python -m checks.raise_from`

A bare `raise` inside a handler preserves the original traceback and is the correct way to
let an error pass through untouched. One source document claimed it loses the call site;
that claim is wrong and is not carried forward — see [meta/CONFLICTS].

### DIAG-007 · Suppressing the cause requires a stated reason  [BINDING] [check:raise_from]
Raising `from None` MUST carry an adjacent comment giving the reason the underlying cause
is not useful to a reader.
- **Why** Cause suppression is occasionally right and usually an accident; requiring the
  sentence separates the two.
- **Check** `python -m checks.raise_from`

### DIAG-008 · Exceptions are never silently swallowed  [BINDING] [auto:ruff:BLE001] [check:raise_from]
Bare `except`, catching broad exception base classes, and catching-then-passing are
prohibited. Deliberate suppression uses a narrow, explicit suppression context with a
comment.
- **Why** A swallowed exception is the one failure mode no diagnostic machinery can
  recover from; nothing is emitted to analyse.
- **Check** `ruff check` (rules `E722`, `BLE001`, `S110`) · `python -m checks.raise_from`

### DIAG-009 · Assertions are not validation  [BINDING] [check:assert_usage]
`assert` MUST be used only for internal invariants that cannot be false unless the program
is wrong. Any check that must run in production — boundary input, authorization, resource
state — MUST NOT be an assertion.
- **Why** Assertions vanish under optimized bytecode, so a validation written as one is a
  check that silently ceases to exist in the environment that needed it.
- **Check** `python -m checks.assert_usage` · `ruff check` (rule `S101` outside tests)
- **See** [law/ERR]

---

## Logging as transport

Logging carries the diagnosis; it does not constitute it. A structured error result is the
contract, and a log line is a copy for the operator.

### DIAG-010 · Each exception is logged once, at its handling boundary  [BINDING] [check:log_once]
`logger.exception` MUST be called only from inside a handler that is not re-raising, and
an error MUST NOT be logged twice on one path.
- **Why** Duplicate stack traces for one fault make an agent count two failures where
  there was one, and the second copy is always the less informative.
- **Check** `python -m checks.log_once`

### DIAG-011 · Library code configures no logging  [BINDING] [check:library_logging]
Reusable modules MUST obtain a module-level logger by name and attach nothing but a null
handler at the package root. Configuring handlers, formatters or levels is the consuming
application's prerogative.
- **Why** A component that drags its logging policy into every host is not reusable, and
  reusability is what keeps coupling at the edge.
- **Check** `python -m checks.library_logging`

### DIAG-012 · Log arguments are deferred, never pre-formatted  [BINDING] [auto:ruff:G004]
Log calls MUST pass format arguments to the logger rather than building the string at the
call site.
- **Why** An eagerly built message is paid for at every level, including the levels that
  discard it, which is how debug logging gets deleted instead of disabled.
- **Check** `ruff check` (rules `G004`, `G010`)

### DIAG-013 · A correlation identifier ties a failure to its trace  [BINDING] [fitness:test_correlation_propagates]
Every entry point MUST establish a correlation identifier in context-local state, and every
log record and envelope MUST carry it.
- **Why** It is what turns scattered lines into one reconstructable story, which is the
  difference between reading a trace and searching a file.
- **Check** `pytest enforce/fitness/test_diagnostics.py::test_correlation_propagates`

### DIAG-014 · Secrets and personal data never reach a log or an envelope  [BINDING] [check:redaction]
Credentials, tokens and personal data MUST be redacted before they are logged or placed in
the `value` field.
- **Why** The envelope is designed to be read widely and machine-processed, which is
  exactly what makes an unredacted value in it expensive.
- **Check** `python -m checks.redaction`

### DIAG-015 · Structured fields, not sentences  [BINDING] [auto:ruff:G004] [check:log_once]
Log records MUST attach their variables as structured fields rather than interpolating
them into prose.
- **Why** Unstructured logs do not survive being queried, and a diagnosis nobody can query
  is one nobody will find.
- **Check** `ruff check` · `python -m checks.log_once`

### DIAG-016 · State transitions are observable  [ADVISORY]
Components with a non-trivial state machine SHOULD log each transition, with the previous
state, the next state and the trigger.
- **No mechanism** Which machines are "non-trivial" cannot be decided statically; the
  transition legality rules are enforced separately in [law/EFCT].
- **Why** A transition log turns "it ended in the wrong state" into a specific illegal
  step, which is the difference between a bug report and a diagnosis.
