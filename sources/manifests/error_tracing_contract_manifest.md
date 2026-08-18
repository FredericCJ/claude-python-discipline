# Error-Tracing & Exception-Handling Contract — Ground-Truth Manifest

**Purpose.** A citable ground-truth reference for designing robust error-tracing and exception-handling in **small-scale, strictly-typed Python** organized as a **functional core / imperative shell**. It grounds four decisions for the team's new feature: how errors propagate, how exceptions are handled, how messages are written for easy source-tracing, and where upfront assertions belong. This file is **GROUNDING, not a rulebook**: cite a principle when it materially shapes a decision; reason past it when the situation does not match. Every factual claim is tagged **ESTABLISHED** (normative/stable in the language or a PEP), **VERSION-DEPENDENT** (tied to a Python version or library major), **OPEN** (a design synthesis or convention with no single prescribing primary source — the team must pin it), or **CC-FACT** (Claude-Code mechanics; none arise here). Primary sources are inline-cited and listed under **## Sources**.

Sibling manifests are referenced, not repeated. Architecture paradigms, the functional-core/imperative-shell rationale, and reusability theory live in `architecture_manifest_default.md` and `software_spec_discipline_manifest.md`. Type-system facts (unions, `Never`, narrowing) live in `python_typing_contract_manifest.md`. Test-tooling facts live in `python_testing_tooling_manifest.md`. **Logging and observability mechanics live in `logging_observability_manifest.md`; this manifest states only the error-side obligations and CROSS-REFERENCES that file for handler/formatter/transport policy — it does not duplicate it.**

---

## 1. Purpose and scope

This manifest covers errors as a **public, version-stable contract** for a strictly-typed small app. Two facts frame everything below. **ESTABLISHED:** Python has **no checked exceptions** — a raised exception is invisible to the static type system, so it is *not* part of a function's statically-enforced signature (https://docs.python.org/3/library/typing.html). **ESTABLISHED:** an in-band result *can* be modeled in the type system as a discriminated union and statically enforced for exhaustive handling (https://typing.python.org/en/latest/spec/special-types.html). The whole design follows from this asymmetry: outcomes that belong to the contract should be **typed and in-band**; outcomes that are genuinely exceptional should be **raised**. Scope is single-process, small-scale apps; distributed tracing and metrics are out of scope and deferred to `logging_observability_manifest.md`.

## 2. Guiding principles (PEP 20)

**ESTABLISHED.** The Zen of Python anchors the error stance verbatim: **"Errors should never pass silently. Unless explicitly silenced."**, **"Explicit is better than implicit."**, and **"In the face of ambiguity, refuse the temptation to guess."** (https://peps.python.org/pep-0020/). Operationalized: never catch-and-ignore; if you suppress, suppress explicitly and narrowly (§10). Beyond PEP 20, the operating slogan for this manifest is **fail loud, fail typed** — a failure that is part of the contract is a typed value the checker forces you to handle; a failure that is a bug or a genuinely exceptional condition raises loudly with a traceable record.

## 3. Two propagation channels

**ESTABLISHED.** Exactly two channels exist, with different static guarantees (https://docs.python.org/3/library/typing.html; https://typing.python.org/en/latest/spec/special-types.html):

- **In-band typed value** — a discriminated union return such as `EmitOk | EmitError`. A static checker verifies the caller handles every arm: after narrowing all members away, the residual type is `Never`, and a final `assert_never(x)` typechecks only when no member remains. "Who handles which failure" becomes a **checked** part of the public contract, not tribal knowledge.
- **Out-of-band raised exception** — invisible to the type system (no checked exceptions). It does **not** appear in the signature; the checker cannot force a caller to handle it.

**Design rule (OPEN — convention, see §6):** expected/recoverable *domain* outcomes that belong to the contract → typed union; genuinely exceptional, unrecoverable-at-this-layer, or programmer-error conditions → raise.

## 4. Typed result objects: `EmitOk | EmitError`

**ESTABLISHED.** Python ships **no built-in `Result`/`Either`**; the idiomatic encoding is a union of **frozen result variants** (a tagged/discriminated union), e.g. two frozen dataclasses `EmitOk` and `EmitError` distinguished by a literal tag or by type (https://docs.python.org/3/library/typing.html). Properties that make this the preferred channel for contract-level failures:

- **Statically checkable exhaustiveness.** Branch on each member (if/elif or `match`); after narrowing all members the residual type is `Never`; the final `assert_never(arg)` typechecks only when nothing is left.
- **Add-a-variant breaks the build.** Adding a new error variant to the union makes `arg` non-`Never` at every non-exhaustive consumer, so the checker flags **every** call site that fails to handle it — exactly the property wanted for "errors as part of the public contract."
- **`Never` / `assert_never` baseline:** added in **Python 3.11**; `NoReturn` (equivalent semantics) since 3.6.2 (§18). `Never` is the bottom type — the empty set of values (https://typing.python.org/en/latest/spec/special-types.html).

**Prefer in-band typed returns when** the failure is an expected, recoverable, domain outcome the caller must reason about (validation rejections, "not found" where absence is normal, business-rule denials). The dependency-vs-control choice — hand-rolled union vs a third-party `Result` library — is **OPEN** (§21, no stdlib type exists).

(Union mechanics, narrowing, `Literal` tags, and frozen-dataclass patterns: `python_typing_contract_manifest.md`.)

## 5. `assert_never` / `Never` exhaustiveness

**ESTABLISHED.** `assert_never(arg)` is the canonical exhaustiveness mechanism (https://docs.python.org/3/library/typing.html#typing.assert_never). A **missed case** leaves `arg` with a non-`Never` static type, so the checker emits an error; **at runtime** a reached `assert_never` raises `AssertionError`. Canonical pattern: branch on each union member, and in the final `case _:` / `else` call `assert_never(arg)`. This is a *special, intended* assertion (exhaustiveness) backed by static checking — distinct from the runtime-invariant assertions of §14, and it is the one assertion whose primary value is at type-check time, not run time.

## 6. The functional-core / imperative-shell boundary — where conversion happens

**OPEN — convention, tag the seam explicitly in your design.** The placement of the result/exception boundary is a **design-pattern synthesis, not a Python-spec mandate** (synthesis over https://docs.python.org/3/library/typing.html and PEP 20; no single primary source prescribes the seam). The grounded inference, layered on the language facts:

- The **pure functional core** returns **typed results** for expected/domain failures and stays exception-light; raised exceptions in the core are reserved for can't-happen invariant violations (§14).
- The **imperative shell** is where exceptions are **caught** and **converted**: translate low-level/library exceptions into typed results going *inward*, and translate typed errors into raised exceptions / log+exit going *outward* (§16 for the logging side).
- **Teams differ on exactly where the line sits.** This manifest mandates that the design **tag the exact seam** (which module/function is the shell boundary, what gets converted, in which direction) as an explicit OPEN/convention decision in the spec, per the epistemic-tagging discipline of `software_spec_discipline_manifest.md`. Do not leave it implicit.

(Functional-core/imperative-shell rationale and testability payoff: `architecture_manifest_default.md`, `software_spec_discipline_manifest.md` §F1.)

## 7. Raised exceptions: when they are the right channel

**ESTABLISHED (by the no-checked-exceptions fact, §3).** Raise — rather than return a typed result — when the condition is one of: **truly exceptional** (violates an assumption the contract is entitled to make), **unrecoverable at this layer** (this code cannot meaningfully decide what to do), or **programmer error** (a bug: a can't-happen state reached). Because raised exceptions are not in the static signature, reserving them for these cases keeps the *checkable* contract (the typed-union returns) honest and complete. A failure a caller is expected to branch on routinely should be a typed return (§4), not an exception the caller might forget to catch.

## 8. Exception chaining: `raise X from Y`, `__cause__` vs `__context__`

**ESTABLISHED** (https://docs.python.org/3/reference/simple_stmts.html; https://docs.python.org/3/library/exceptions.html):

- **`raise X from Y`** sets `X.__cause__ = Y` (the **explicit** cause; `__cause__` is writable). Setting `__cause__` also sets `__suppress_context__ = True`.
- **Implicit context:** when a new exception is raised *while another is being handled*, the prior one is auto-attached as `X.__context__`.
- **Display rules:** `__cause__` is **always** shown — *"The above exception was the direct cause of the following exception."* `__context__` is shown **only if** `__cause__` is `None` **and** `__suppress_context__` is false — *"During handling of the above exception, another exception occurred."*
- **Use** `raise Domain from low` when wrapping a low-level error in a domain exception at an abstraction boundary, so the original is preserved for tracing (§10, §11).

## 9. `from None` — use sparingly

**ESTABLISHED.** `raise NewError(...) from None` *"effectively replaces the old exception with the new one for display purposes (e.g. converting `KeyError` to `AttributeError`), while leaving the old exception available in `__context__` for introspection when debugging."* (https://docs.python.org/3/library/exceptions.html#BaseException.__suppress_context__). The original is **not lost** — it stays in `__context__` — but it is hidden from the rendered traceback. **Use sparingly:** suppressing context can hide the real source from a traceback, which works directly against source-tracing. Justify each use (typically: the wrapped exception is an irrelevant implementation detail of the lookup, and surfacing it would mislead).

## 10. Re-raise vs wrap vs explicit-suppress

**ESTABLISHED** (https://peps.python.org/pep-0020/; https://docs.python.org/3/library/exceptions.html; https://docs.python.org/3/library/contextlib.html):

- **Re-raise** with a bare `raise` (no expression) inside the handler to **preserve the original traceback** — the cheapest way to add nothing but let it propagate. (To add context without changing type, prefer `add_note`, §13.)
- **Wrap** with `raise Domain(...) from low` when crossing an **abstraction boundary**, keeping the cause chained (§8). This is the shell's primary tool for not leaking low-level exceptions across an API boundary (§19 anti-pattern).
- **Explicitly suppress** — and *only* explicitly, per PEP 20 *"Unless explicitly silenced"* — with `contextlib.suppress(SpecificError)`, narrowly scoped to the specific exception, with a comment or log explaining why. Never catch-and-ignore (§19).

## 11. Custom exception hierarchy

**ESTABLISHED** (https://docs.python.org/3/library/exceptions.html; https://docs.python.org/3/tutorial/errors.html):

- **Root at `Exception`, never `BaseException`.** *"Programmers are encouraged to derive new exceptions from the `Exception` class or one of its subclasses, and not from `BaseException`."* `BaseException` also covers `SystemExit`/`KeyboardInterrupt`/`GeneratorExit`, which must not be swallowed (§12).
- **Single inheritance.** *"It's recommended to only subclass one exception type at a time"* — multiple inheritance of exception types causes args-handling and C-level memory-layout conflicts.
- **`Error` naming.** *"Most exceptions are defined with names that end in `Error`."*
- **One package base.** Define a single `PackageError(Exception)` base so callers can catch the whole library's failures with one handler, plus **narrow subclasses** for specific conditions. This makes the error surface a documented, reusable part of the public contract (§17).
- **Define vs reuse.** Define a custom exception when callers need to **distinguish it programmatically** or when it **crosses an API boundary**; otherwise **reuse a built-in** (`ValueError`, `TypeError`, `KeyError`, …). Do not invent a class where a builtin already carries the right meaning.

## 12. Catch narrowly; `else` / `finally`; never bare `except`

**ESTABLISHED** (https://docs.python.org/3/tutorial/errors.html):

- **Catch narrowly.** Name the specific exception type(s). **Bare `except:` and `except BaseException:` also catch `KeyboardInterrupt`/`SystemExit`/`GeneratorExit`**, which user code should not intercept — pair this with §11's `Exception`-not-`BaseException` rule.
- **`else`** runs only if the `try` body raised nothing and *"is better than adding additional code to the `try` clause because it avoids accidentally catching an exception that wasn't raised by the code being protected."* Keep the protected region minimal — this directly aids tracing the true source.
- **`finally`** *"will execute as the last task … whether or not the `try` statement produces an exception"* — for releasing external resources.

## 13. EAFP over LBYL (with the TOCTOU caveat)

**ESTABLISHED** (https://docs.python.org/3/glossary.html):

- **EAFP** ("Easier to ask for forgiveness than permission") is the idiomatic Python style: *"assumes the existence of valid keys or attributes and catches exceptions if the assumption proves false. This clean and fast style is characterized by the presence of many `try` and `except` statements."*
- **LBYL** ("Look before you leap") tests preconditions before acting and is the contrast. **TOCTOU caveat:** *"In a multi-threaded environment, the LBYL approach can risk introducing a race condition between the looking and the leaping … `if key in mapping: return mapping[key]` can fail if another thread removes `key` … This issue can be solved with locks or by using the EAFP approach."* Prefer EAFP; where LBYL is unavoidable across a shared resource, recognize the time-of-check/time-of-use window.

## 14. Assertions — what they are FOR and NOT for

**ESTABLISHED** (https://docs.python.org/3/reference/simple_stmts.html):

- **Mechanism.** `assert expr, msg` compiles to `if __debug__: if not expr: raise AssertionError(msg)`. `__debug__` is *"True under normal circumstances, False when optimization is requested (`-O`)"*, and *"the current code generator emits no code for an `assert` statement when optimization is requested at compile time."*
- **FOR:** internal **can't-happen invariants** and **pre/post-conditions** — programmer-believed facts whose violation means a **bug**, not bad input (e.g. "this list is non-empty here", a postcondition on a pure function). `assert_never` (§5) is the special, intended, statically-backed assertion.
- **NOT for:** validating **untrusted/boundary input**, auth, or resource state — **any check that must run in production must not be an `assert`**, because under `-O` it vanishes silently, which is both a correctness and a **security** hole.
- **Production policy is OPEN** (§21): if `-O` is ever shipped, every must-survive check has to be audited to confirm it is not an `assert`.

## 15. Boundary validation & "parse, don't validate"

**OPEN — best-practice synthesis; library identity/version is unpinned.** *"Parse, don't validate"* (Alexis King, 2019) and *"make illegal states unrepresentable"*: push checking to the boundary and **encode the proof in a type** so the core can assume the invariant holds (https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/). **Pydantic** positions itself as exactly this border control: *"Pydantic guarantees the types and constraints of the output, not the input data … after parsing and validation, Pydantic guarantees that the fields of the resultant model instance will conform to the field types."* (https://docs.pydantic.dev/latest/concepts/models/). This is the **production-grade replacement** for the (wrong) use of `assert` on boundary input (§14): validation raises a real, catchable `ValidationError` with structured, actionable detail that **survives `-O`**.

**The relationship to chain together:** parse at the imperative-shell boundary → typed objects flow into the functional core → asserts guard internal invariants the parser already guarantees. **Pydantic v1 vs v2 differ** in behavior and error shape (VERSION-DEPENDENT); the choice of pydantic vs plain dataclasses + manual parsing is unpinned (§21).

## 16. Descriptive messages — anatomy & structured attributes

**OPEN — best-practice synthesis; tag the 5-part anatomy as a team convention.** A high-quality error/exception, written to let a reader trace the failure to its source, carries five parts:

1. **Operation context** — what was being attempted.
2. **Expected vs actual** — what was required against what was found.
3. **Offending identifier/value** — the specific input/id at fault.
4. **Remediation hint** — what the caller can do about it.
5. **Stable error code** — a namespaced, machine-greppable code (ideally as an attribute, not embedded in prose).

The specific 5-part anatomy is a synthesis, **not** a single primary spec, but it is grounded in two facts (https://docs.python.org/3/reference/simple_stmts.html; https://docs.python.org/3/tutorial/errors.html): the assert-statement note says including the failing expression text is unnecessary because *"it will be displayed as part of the stack trace"* — i.e. **a message should add information the traceback lacks** (values, intent, remediation), not echo it; and custom exception classes *"often only offering a number of attributes that allow information about the error to be extracted by handlers"* — i.e. carry **structured fields** (offending id, code) **as attributes, not just a string**, so handlers and loggers can consume them. **Prefer structured attributes over bare strings.** Stable error codes as attributes make errors machine-greppable across versions (a convention, not mandated — §17, §21).

## 17. Errors as a documented, version-stable public contract (reusability)

**ESTABLISHED / OPEN.** The exception hierarchy (§11) and the typed-result unions (§4) **are** public API surface. **ESTABLISHED:** a single `PackageError` base plus narrow subclasses lets a caller catch the whole library with one handler while distinguishing specific conditions — a documented, reusable contract (https://docs.python.org/3/library/exceptions.html; https://docs.python.org/3/tutorial/errors.html). **OPEN (convention):** the **stability of error codes and exception types across versions** — namespaced codes as exception attributes, deprecation guarantees on the error surface — is a versioned-contract decision the team must pin (§21). Treat adding a union variant or renaming an exception as a **breaking change** to consumers, subject to the reusability discipline in `software_spec_discipline_manifest.md` (§C, §G).

## 18. ExceptionGroup / `except*` (PEP 654, 3.11+)

**VERSION-DEPENDENT (3.11+)** (https://peps.python.org/pep-0654/; https://docs.python.org/3/library/exceptions.html):

- **`ExceptionGroup(msg, excs)`** wraps `Exception` subclasses; **`BaseExceptionGroup`** wraps any `BaseException` (and **downgrades** to `ExceptionGroup` if all members are `Exception`s).
- **`except*`** can run **multiple** clauses, each matching a subset of the group.
- **`split(condition)` / `subgroup(condition)`** partition by type or — **3.13+** — by an arbitrary callable; **`derive(excs)`** lets subclasses preserve their type through a split.
- **Backward compatible:** plain `except Exception:` still catches a group.
- **Use selectively.** PEP 654: *"exception groups and `except*` will be used selectively, only when they are needed"* (e.g. concurrent tasks, multiple independent validation failures), and adoption *"will normally be done by introducing a new API rather than modifying an existing one."* In a small single-process app, single-exception flow is usually sufficient (§21 — justify any group call sites concretely).
- **Backport:** `exceptiongroup` for < 3.11.

## 19. Notes & tracebacks (PEP 678, 3.11+)

**VERSION-DEPENDENT (3.11+)** (https://peps.python.org/pep-0678/; https://docs.python.org/3/library/exceptions.html#BaseException.add_note):

- **`add_note(note: str)`** appends to the auto-created **`__notes__`** list; notes print in the standard traceback **after** the exception string, in insertion order (`TypeError` if `note` is not a `str`).
- **Preferred over re-wrapping when you only need to add context.** PEP 678 rationale: exception chaining *"reports several lines of additional detail, which are distracting … and can be very confusing for beginners"*; notes add context **without changing the exception type or cause**.
- **For tracing:** catch as it bubbles, `e.add_note(f"while processing user={uid}")`, `raise` — the call-site context lands in the traceback **without** losing the original type or chained cause.
- **Pairs with** ExceptionGroups (each member carries its own context) and retry loops (record attempt count/timestamp).
- **How a traceable record assembles:** the **message** (§16: values + intent + remediation + code) + **notes** (§19: propagation context) + **chained cause** (§8: the underlying error) combine into one source-traceable traceback. Backport: `typing_extensions` / the `exceptiongroup` package provide `add_note` shims for < 3.11.

## 20. Observability & logging — error-side obligations only

**ESTABLISHED** (https://docs.python.org/3/howto/logging.html) — stated here as the *error contract's* logging obligations; **all handler/formatter/transport policy lives in `logging_observability_manifest.md` and is not duplicated here**:

- **Module logger:** `logger = logging.getLogger(__name__)`.
- **`logger.exception()`** *"dumps a stack trace along with it. Call this method only from an exception handler"* (logs at ERROR + traceback); equivalently `logger.error(msg, exc_info=True)`.
- **Libraries add only `NullHandler`:** *"do not add any handlers other than `NullHandler` to your library's loggers … configuration of handlers is the prerogative of the application developer."*
- **The error/observability tie-in:** structured exception attributes (offending id, stable code — §16) + `add_note` context (§19) + chained cause (§8) give the log a **complete, source-traceable record**. The **shell** (not the core) owns logging policy (§6).

## 21. Version matrix and minimum target

**VERSION-DEPENDENT.** The feature baseline that this manifest's design leans on:

| Feature | Since | Backport for < 3.11 |
|---|---|---|
| `Never` (bottom type), `assert_never` | **3.11** | `typing_extensions` |
| `NoReturn` (≈ `Never` semantics) | 3.6.2 | stdlib |
| `ExceptionGroup` / `BaseExceptionGroup`, `except*` | **3.11** (callable `split`/`subgroup` condition **3.13**) | `exceptiongroup` |
| `BaseException.add_note` / `__notes__` (PEP 678) | **3.11** | `exceptiongroup` / `typing_extensions` shim |
| `contextlib.suppress`, `raise … from …`, `__cause__`/`__context__`/`__suppress_context__`, `assert`/`__debug__`/`-O`, EAFP/LBYL, logging `NullHandler`/`exception` | long-stable | n/a |

**Recommendation (OPEN — team must pin):** assume a **3.11+ minimum** so `ExceptionGroup`, `except*`, `add_note`, `assert_never`, and `Never` are native; otherwise adopt the `exceptiongroup` + `typing_extensions` backports and gate on them.

**Open questions to resolve before building** (carry into the spec per `software_spec_discipline_manifest.md` §G5):
- **Seam placement (OPEN, §6):** where exactly is the result/exception boundary, and do all domain "expected failures" become typed unions while only truly-exceptional conditions raise?
- **Stable error-code scheme (OPEN, §16–17):** project-wide namespaced codes as exception attributes, part of the versioned public contract with deprecation guarantees?
- **Minimum Python (VERSION-DEPENDENT, §21):** assume 3.11+ or cover backports for < 3.11?
- **Boundary tool (VERSION-DEPENDENT, §15):** pydantic v1 vs v2 vs plain dataclasses + manual parsing — error shapes differ by major.
- **Result type (OPEN, §4):** hand-rolled discriminated union vs a third-party library (e.g. `returns`) — dependency-vs-control trade-off; no stdlib `Result` exists.
- **Logging policy (OPEN, §20):** structured logging (JSON, error codes, correlation IDs) vs plain `logger.exception` — defer detail to `logging_observability_manifest.md`.
- **ExceptionGroup aggressiveness (§18):** are there concrete concurrent/multi-failure call sites that justify groups, or is single-exception flow sufficient?
- **Assertions in production (OPEN, §14):** ship with or without `-O`? If `-O` is ever used, audit every must-survive check to confirm it is not an `assert`.

## 22. Anti-patterns checklist

Each is a violation of a section above; reject on sight.

- **Bare `except:` / `except BaseException:`** — swallows `KeyboardInterrupt`/`SystemExit`/`GeneratorExit` (§11, §12).
- **`assert` on untrusted/boundary input** — stripped under `-O`; a correctness and security hole (§14, §15).
- **Swallow-and-continue** (catch and ignore) — violates PEP 20 *"never pass silently"* (§2, §10).
- **String-only errors** — no structured attributes; not machine-consumable, not greppable across versions (§16).
- **Raising the base package exception directly** — defeats narrow handling; raise a specific subclass (§11).
- **Leaking low-level/library exceptions across an API boundary** — wrap with `raise Domain from low` instead (§8, §10).
- **`from None` by default** — hides the real source from the traceback; use sparingly with justification (§9).
- **Exceptions for routine, expected, contract-level outcomes** — those belong in a typed union the checker forces callers to handle (§3, §7).
- **Non-exhaustive union handling** — missing `assert_never` lets an unhandled variant slip past the checker (§5).
- **Retrofitting `ExceptionGroup`/`except*` onto an existing single-exception API** — introduce a new API instead (§18).

## 23. Decision flowchart

```
Is the failure an expected, recoverable, contract-level DOMAIN outcome
the caller must branch on?
   YES → return a typed discriminated union (EmitOk | EmitError);
         enforce exhaustiveness with assert_never / Never.            [§3,§4,§5]
   NO  ↓
Is it truly exceptional / unrecoverable-at-this-layer / programmer error?
   YES → raise a specific subclass of your PackageError(Exception).   [§7,§11]
   ↓
Are you crossing an abstraction / API boundary while raising?
   YES → raise DomainError(...) from low_level   (keep the cause)     [§8,§10]
         (add e.add_note(context) instead of re-wrapping if only
          context is needed)                                          [§19]
   ↓
Did multiple independent failures occur together
(concurrent tasks / batch validation)?
   YES → raise ExceptionGroup(msg, excs); handle with except*        [§18]
         (3.11+ / exceptiongroup backport; use selectively)
   ↓
Untrusted input at the shell boundary?
   → parse, don't validate: produce typed objects (pydantic-style),
     raising a real catchable ValidationError — never assert.         [§14,§15]
   ↓
Always: write a descriptive message (context + expected/actual +
offending value + remediation + stable code), log with
logger.exception() inside the handler, never pass silently.           [§2,§16,§20]
```

---

## Sources

- Python `typing` — `assert_never`, `Never`, `NoReturn` — https://docs.python.org/3/library/typing.html and https://docs.python.org/3/library/typing.html#typing.assert_never . Accessed 17 Jun 2026.
- Python typing spec — special types (`Never` = bottom type, empty set of values, added 3.11) — https://typing.python.org/en/latest/spec/special-types.html . Accessed 17 Jun 2026.
- Python language reference — `raise` statement and chaining; `assert` statement, `__debug__`, `-O` emits no code; assert-message note — https://docs.python.org/3/reference/simple_stmts.html . Accessed 17 Jun 2026.
- Python built-in exceptions — `__cause__`/`__context__`/`__suppress_context__`, `from None`, `Exception` vs `BaseException`, single-subclass guidance, `ExceptionGroup`/`BaseExceptionGroup`/`subgroup`/`split`/`derive`, `BaseException.add_note`/`__notes__` — https://docs.python.org/3/library/exceptions.html (and #BaseException.__suppress_context__, #BaseException.add_note). Accessed 17 Jun 2026.
- Python tutorial — errors and exceptions: `else`/`finally`, user-defined exceptions, `Error` naming, exception attributes for handlers — https://docs.python.org/3/tutorial/errors.html . Accessed 17 Jun 2026.
- Python glossary — EAFP, LBYL, TOCTOU race-condition caveat — https://docs.python.org/3/glossary.html . Accessed 17 Jun 2026.
- PEP 20 — The Zen of Python ("Errors should never pass silently. Unless explicitly silenced."; "Explicit is better than implicit.") — https://peps.python.org/pep-0020/ . Accessed 17 Jun 2026.
- PEP 654 — Exception Groups and `except*` ("used selectively"; "new API rather than modifying an existing one") — https://peps.python.org/pep-0654/ . Accessed 17 Jun 2026.
- PEP 678 — Enriching Exceptions with Notes (`add_note`/`__notes__`; chaining-is-distracting rationale) — https://peps.python.org/pep-0678/ . Accessed 17 Jun 2026.
- Python logging HOWTO — `Logger.exception`/`exc_info`, `getLogger(__name__)`, `NullHandler` in libraries — https://docs.python.org/3/howto/logging.html . Accessed 17 Jun 2026.
- `contextlib.suppress` — explicit, narrow silencing — https://docs.python.org/3/library/contextlib.html . Accessed 17 Jun 2026.
- Pydantic — models concept ("guarantees the types and constraints of the output, not the input data") — https://docs.pydantic.dev/latest/concepts/models/ . Accessed 17 Jun 2026.
- Alexis King — "Parse, don't validate" / make illegal states unrepresentable — https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/ . Accessed 17 Jun 2026.

### Sibling manifests (cross-referenced, not duplicated)
- `architecture_manifest_default.md` — paradigms, functional-core/imperative-shell rationale, debuggability.
- `software_spec_discipline_manifest.md` — epistemic tagging, reusability ledger, contracts-as-public-API discipline.
- `python_typing_contract_manifest.md` — union/narrowing/`Never`/frozen-dataclass type-system facts.
- `python_testing_tooling_manifest.md` — test obligations for error paths.
- `logging_observability_manifest.md` — logging handlers, formatters, structured/JSON logging, correlation IDs, transports (the observability mechanics this manifest defers to).
