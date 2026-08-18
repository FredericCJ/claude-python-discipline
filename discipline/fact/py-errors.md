---
id: fact/py-errors
kind: fact
title: Python Error and Exception Mechanics
tokens: 1441
load_when:
  - "raise from"
  - "__cause__"
  - "__context__"
  - "add_note"
  - "ExceptionGroup"
  - "except star"
  - "suppress"
  - "traceback"
verified: 2026-08-18
decay: years
python: ">=3.11"
---

# Python Error and Exception Mechanics

What the language actually does with exceptions. The obligations built on these facts are
in [law/ERR] and [law/DIAG].

---

## The asymmetry everything follows from

`ESTABLISHED` — there are no checked exceptions. A raised exception is invisible to the
type system, so it is **not** part of a function's statically enforced signature. A checker
cannot force a caller to handle it.

`ESTABLISHED` — an in-band result **can** be modelled as a discriminated union and
statically enforced for exhaustive handling: narrow every member away and the residual type
is `Never`, at which point an exhaustiveness assertion typechecks only if nothing remains.

These two facts are the entire basis of the two-channel design. Which outcomes belong to
the contract is a decision; which channel can enforce that decision is not.

## Chaining

`ESTABLISHED` — `raise X from Y` sets `__cause__` and marks the context as suppressed. The
displayed traceback reads "The above exception was the direct cause of the following
exception".

`ESTABLISHED` — raising inside an active handler sets `__context__` **automatically**, even
with no `from` clause. The traceback reads "During handling of the above exception, another
exception occurred". So the chain is not lost by omission; it is lost by suppression.

`ESTABLISHED` — a bare `raise` inside a handler re-raises the current exception and
**preserves the original traceback**. It adds nothing and loses nothing.

This last point corrects a claim carried by one source document, which stated that a bare
re-raise loses the call site. It does not. The recorded resolution is in [meta/CONFLICTS].

`ESTABLISHED` — `raise X from None` suppresses the context display entirely. The underlying
error is then absent from the output, which is why [law/DIAG] requires a stated reason.

## Notes

`ESTABLISHED` — an exception carries a list of notes, appended with a method call and
displayed after the message in the traceback. Notes can be added to a *live* exception as
it propagates.

This is the mechanism behind context accretion without re-wrapping. Re-wrapping to add
context changes the type a caller matches on; a note does not.

## Groups

`ESTABLISHED` — exception groups carry multiple independent exceptions, and the `except*`
form handles them selectively: matching subgroups are handled, non-matching ones propagate.
Groups can be split, subgrouped and derived.

`ESTABLISHED` — this is the only construct in the language that reports concurrent
failures without discarding all but one. Collapsing five failures to the first is a real
loss of diagnostic information, not a simplification.

## Catching

`ESTABLISHED` — a bare `except` catches everything including control-flow exceptions such
as interrupt and generator exit, which is almost never intended.

`ESTABLISHED` — the base of the exception hierarchy that ordinary code should catch is
`Exception`, not `BaseException`. Catching the latter intercepts interpreter shutdown and
keyboard interrupt.

`ESTABLISHED` — an `else` clause runs only when no exception was raised, and `finally` runs
regardless. Together they let the guarded block contain only what can actually fail.

`ESTABLISHED` — the narrow suppression context manager is the explicit way to ignore a
specific exception. It is scoped and readable, which a catch-and-pass is not.

## Assertions

`ESTABLISHED` — `assert` compiles to a conditional on the debug flag, and the entire
statement is removed under optimized bytecode. Validation written as an assertion ceases to
exist in an optimized deployment, silently.

`ESTABLISHED` — this makes assertions correct for internal invariants that cannot be false
unless the program is wrong, and incorrect for boundary input, authorization and resource
state.

## Message anatomy

`OPEN` — the following structure is a convention, not a language rule, but it is what the
diagnostic envelope in [law/DIAG] is built to carry:

1. what operation was being attempted
2. what was expected versus what was seen
3. the offending identifier or value
4. a remediation hint
5. a stable, namespaced code — as an attribute, not embedded in the prose

`ESTABLISHED` — carrying these as structured attributes rather than only in a formatted
string is what allows a consumer to branch on them. Parsing them back out of a rendered
sentence is possible and always fragile.

## Errors as public surface

`ESTABLISHED / OPEN` — that an exception hierarchy is API surface is established practice;
the precise policy for what counts as a breaking change is a project decision. This
discipline's policy is in [law/API]: renaming a code, removing one, or adding a variant to
a published union is breaking.

---

## Sources

Verified against the official language reference, library documentation and the relevant
enhancement proposals on 2026-08-18. Behavioural claims about chaining, notes and groups
were confirmed by execution on the installed interpreter. Re-verify when `verified:`
exceeds the decay window.
