# Logging & Observability — Ground-Truth Manifest

**Purpose.** A citable ground-truth reference for designing robust LOGGING and OBSERVABILITY into
small-scale, strictly-typed, **reuse-first** Python applications. It serves a feature with three
goals: **goal1** — a debugging aid for the developer/contributor *and* for downstream reusers;
**goal2** — monitoring the software in action operationally; **goal3** — per-component reusability,
so each component drops cleanly into a consuming application without dragging logging policy with it.
This file is **GROUNDING, not a rulebook**: cite a rule when it materially shapes a decision; reason
beyond it when the situation does not match. Every factual claim is tagged **ESTABLISHED** (normative
and stable in the cited primary source), **VERSION-DEPENDENT** (tied to a Python/library version or to
a derived phrasing not verbatim in the source), or **OPEN** (no authoritative python.org source; a
best-practice or project-policy call); Claude-Code mechanics are tagged **CC-FACT** where they arise.
Sibling manifests are cross-referenced by filename and **not duplicated**: spec discipline lives in
`software_spec_discipline_manifest.md`; architecture principles in `architecture_manifest_default.md`;
typing facts in `python_typing_contract_manifest.md`; test tooling in
`python_testing_tooling_manifest.md`; the exception-propagation contract this manifest composes with
lives in `error_tracing_contract_manifest.md`.

---

## 1. Scope and the three goals

Target: a small, strictly-typed, reuse-first Python codebase made of components meant to be lifted
into other applications. Logging is the observability seam; the design problem is to make the seam
*useful* (goals 1 and 2) without making it *opinionated* (goal 3). The whole architecture below is the
mechanical resolution of that tension: components emit richly and configure nothing; applications
configure once and own all routing.

The three goals map onto the severity model and architecture as follows, developed in §6:
- **goal1 (debug aid)** → DEBUG/INFO at component seams with descriptive context, source obvious from
  the logger name.
- **goal2 (operational monitoring)** → INFO/WARNING/ERROR/CRITICAL as the operational signal, plus
  structured/JSON output and correlation/trace IDs.
- **goal3 (per-component reuse)** → `NullHandler` + zero global configuration + propagation. **This is
  the load-bearing constraint** and the one most easily violated; it is **BEST-EFFORT, not absolute**
  (§4, §6).

---

## 2. The severity model: FIVE emittable levels

**ESTABLISHED.** The stdlib `logging` module defines exactly five severities you actually emit at,
with these numeric values and official "when to use" semantics
(https://docs.python.org/3/library/logging.html; https://docs.python.org/3/howto/logging.html):

| Level | Numeric | Official semantics (verbatim) |
|---|---|---|
| **CRITICAL** | **50** | "A serious error, indicating that the program itself may be unable to continue running." |
| **ERROR** | **40** | "Due to a more serious problem, the software has not been able to perform some function." |
| **WARNING** | **30** | "An indication that something unexpected happened, or that a problem might occur in the near future (e.g. disk space low). The software is still working as expected." |
| **INFO** | **20** | "Confirmation that things are working as expected." |
| **DEBUG** | **10** | "Detailed information, typically only of interest to a developer trying to diagnose a problem." |

These are the levels you call via the convenience methods `logger.critical/error/warning/info/debug`.
The same when-to-use table appears in **both** the library reference and the HOWTO (ESTABLISHED).

**ESTABLISHED — default threshold.** The default level of the root logger is **WARNING**; "only events
of this severity and higher will be tracked, unless the logging package is configured to do otherwise"
(https://docs.python.org/3/howto/logging.html). Consequence for every decision table below: **INFO and
DEBUG are silent by default** and require the consuming application to lower the threshold
(`basicConfig`/`dictConfig`). A component that "logs INFO" emits nothing until an application asks for
INFO.

### 2a. NOTSET (0) is a SENTINEL, not a sixth severity — explicit correction

**ESTABLISHED — the trap.** The module also defines `NOTSET = 0`. That makes **six named level
constants** but only **five emittable severities**. A specification that says "five levels" and then
enumerates six (including NOTSET) is **conflating the level CONSTANTS with the emittable SEVERITIES**.
The correct treatment, and the one this manifest adopts: enumerate the **five** severities you actually
call, and document NOTSET **separately** as a sentinel
(https://docs.python.org/3/library/logging.html). **You never write `logger.log(logging.NOTSET, ...)`
as a real severity** — NOTSET is not an emission level.

**ESTABLISHED — what NOTSET actually means.** It is the "no level explicitly set / defer to parent"
sentinel that drives the effective-level lookup. Verbatim docs: "When set on a logger, indicates that
ancestor loggers are to be consulted to determine the effective level. If that still resolves to
NOTSET, then all events are logged." And: "When a logger is created, the level is set to NOTSET (which
causes all messages to be processed when the logger is the root logger, or delegation to the parent
when the logger is a non-root logger)." So on a **non-root** logger NOTSET means *walk up*; on the
**root** logger NOTSET means *process everything*
(https://docs.python.org/3/library/logging.html). NOTSET configures the effective-level machinery; it
is meaningless as an emission severity.

### 2b. Decision table — which level, and print vs `warnings.warn` vs `logging`

**ESTABLISHED.** The dispatch below comes straight from the HOWTO's "what to use when" guidance
(https://docs.python.org/3/howto/logging.html):

| Situation | Use | Rationale |
|---|---|---|
| Console output for ordinary CLI usage | `print()` | Plain user-facing output, not an observability event. |
| Report events during normal operation; status monitoring / fault investigation | `logger.info()` or `logger.debug()` | INFO = "working as expected"; DEBUG = developer diagnostics. |
| Internal decision / input / branch point of interest to a contributor | `logger.debug()` | Developer-facing diagnostics; silent in production by default. |
| A component begins/ends a meaningful unit of work; public-API boundary crossed | `logger.info()` | The operational "things are working" signal (goal1/goal2 seam). |
| Issue a runtime warning the **client code should change** (avoidable misuse) | `warnings.warn()` | Library-code idiom for "fix your usage." |
| Something unexpected happened but the software still works, and the **client app can do nothing** about it, yet it should be noted | `logger.warning()` | WARNING semantics; not the caller's bug to fix. |
| A function could not be performed / a serious problem occurred | `raise` an exception, or `logger.error()` / `logger.exception()` / `logger.critical()` | Error reporting; see §10 for log-once discipline. |

The `print` vs `warnings.warn` vs `logging.warning` split is the most-missed part: `warnings.warn` is
for *avoidable* problems the **caller** should fix; `logger.warning` is for *unavoidable* notable
events the caller cannot act on. (ESTABLISHED.)

---

## 3. Architecture: Logger, Handler, Formatter, Filter

**ESTABLISHED — four object types** (https://docs.python.org/3/library/logging.html):
- **Logger** — "Loggers expose the interface that application code directly uses." This is what
  components hold and call.
- **Handler** — "Handlers send the log records (created by loggers) to the appropriate destination"
  (console, file, JSON sink, network).
- **Filter** — "Filters provide a finer grained facility for determining which log records to output."
  Filters may also *modify* records (used for contextual fields; §7, §8).
- **Formatter** — "Formatters specify the layout of log records in the final output."

**ESTABLISHED — two-stage level thresholds.** A `LogRecord` is gated **twice**
(https://docs.python.org/3/library/logging.html):
1. It is **created only if** its level ≥ the logger's **effective level** (walked up the hierarchy; root
   NOTSET ⇒ all events), and it passes any **logger** filters.
2. It is then offered to each handler reachable via propagation, and **each handler independently
   drops it** if it is below **that handler's own level**, and applies that handler's own filters and
   formatter.

**Manifest implication (ESTABLISHED).** Set the logger (or root) level to the **lowest** severity you
ever want to capture, and use **per-handler levels to fan out** — e.g. a console handler at INFO and a
file/JSON handler at DEBUG against the same root logger at DEBUG. The two-stage model is why one
configuration can route the same stream to multiple destinations at different verbosities.

### 3a. Logger hierarchy, `getLogger(__name__)`, effective level, propagation

**ESTABLISHED — singletons via `getLogger`.** "Loggers should NEVER be instantiated directly, but
always through the module-level function `logging.getLogger(name)`. Multiple calls to `getLogger()`
with the same name will always return a reference to the same `Logger` object." Convention is
`logging.getLogger(__name__)` so logger names track the package/module hierarchy
(https://docs.python.org/3/library/logging.html; https://docs.python.org/3/howto/logging.html).

**ESTABLISHED — dotted hierarchy and effective-level walk-up.** Names like `foo`, `foo.bar`,
`foo.bar.baz` form a parent/child hierarchy and "all loggers are descendants of the root logger." "If
a level is not explicitly set on a logger, the level of its parent is used instead as its effective
level… all ancestors are searched until an explicitly set level is found"
(https://docs.python.org/3/library/logging.html; https://docs.python.org/3/howto/logging.html). This
is the NOTSET sentinel (§2a) in action.

**ESTABLISHED — propagation.** `propagate` defaults to **True** (set in the constructor). "If this
attribute evaluates to true, events logged to this logger will be passed to the handlers of higher
level (ancestor) loggers… Messages are passed **directly** to the ancestor loggers' handlers — **neither
the level nor filters of the ancestor loggers in question are considered**"
(https://docs.python.org/3/library/logging.html). Two consequences:
- An ancestor's *handlers* receive the record, but the ancestor's *level/filters* are **not**
  re-checked — only the originating logger's effective level (stage 1) and each handler's own level
  (stage 2) gate the record.
- Official best practice: "A common scenario is to attach handlers only to the root logger, and to let
  propagation take care of the rest." This is why a top-level application configures one set of
  handlers and child/module loggers need none — the mechanical foundation of goal3.

---

## 4. Reusable-component / library discipline (goal3 — the load-bearing part)

This is the heart of the feature. A reusable component must be **silent and unopinionated by default**
and hand *all* configuration to the consuming application. The rules below are quoted from the official
"Configuring Logging for a Library" guidance
(https://docs.python.org/3/howto/logging.html), tagged by how firmly the source states them.

- **ESTABLISHED — use `getLogger(__name__)`; do NOT log to root.** "It is strongly advised that you do
  not log to the root logger in your library. Instead, use a logger with a unique and easily
  identifiable name, such as the `__name__` for your library top-level package or module. Logging to
  the root logger will make it difficult or impossible for the application developer to configure the
  logging verbosity or handlers of your library as they wish."
- **ESTABLISHED — do NOT add handlers other than `NullHandler`, and do NOT call `basicConfig`.** "It is
  strongly advised that you do not add any handlers other than `NullHandler` to your library loggers.
  This is because the configuration of handlers is the prerogative of the application developer who
  uses your library." `basicConfig` adds a handler to the **root** logger, so it is forbidden in library
  code by the same rule.
- **ESTABLISHED — attach one `logging.NullHandler()` to the library's TOP-LEVEL logger.** NullHandler
  "instances do nothing with error messages" and exist so libraries "avoid the *No handlers could be
  found for logger XXX* message." Canonical one-liner, on the **top-level package logger** only:
  `logging.getLogger('orgname.foo').addHandler(logging.NullHandler())`
  (https://docs.python.org/3/howto/logging.html;
  https://docs.python.org/3/library/logging.handlers.html). **This is the single permitted handler in
  library code.** Note: on modern Python the unconfigured fallback is `logging.lastResort` — a
  `StreamHandler` at WARNING writing to stderr — so **without** a NullHandler a library's WARNING+
  records still surface on stderr; the NullHandler suppresses that.
- **VERSION-DEPENDENT / OPEN-wording — "no logging side-effects on import."** The docs contain no single
  sentence literally saying "no side effects on import," so treat the strict phrasing as
  **derived-best-practice**, not a verbatim quote. What **is** officially established and adds up to the
  same rule: do not call `basicConfig`, do not configure root, do not add non-Null handlers. The **only**
  logging actions a module may safely take at import are `logger = logging.getLogger(__name__)` and (at
  the package top level) `addHandler(NullHandler())`. **Tag the literal "no side-effects on import"
  bullet as best-practice/OPEN-wording in any derived spec while citing the handler/root rules as
  ESTABLISHED.**

**Why goal3 is BEST-EFFORT, not absolute.** The discipline is enforced by convention and review, not by
the type system or the runtime: a component *can* call `basicConfig`, and nothing stops it. The rules
make reuse clean when followed; they do not make misconfiguration impossible. State goal3 as a
best-effort guarantee.

---

## 5. Application-side configuration (the consumer)

The complement of §4: the **application** owns logging policy and configures it **once, at startup**.

- **ESTABLISHED — configure handlers/levels/formats once, centrally.** Because components add no
  handlers and propagation (default True) carries their records upward, the recommended scenario is to
  "attach handlers only to the root logger, and to let propagation take care of the rest"
  (https://docs.python.org/3/library/logging.html). Configure the root logger to the **lowest** level
  you want to capture, then fan out via per-handler levels (§3).
- **ESTABLISHED — `basicConfig` vs `dictConfig`.** `basicConfig` is the quick path: it adds a handler
  to the root logger (hence forbidden in libraries, §4). For anything with multiple handlers,
  console-vs-file/JSON split, filters, or per-logger levels, prefer a declarative `dictConfig`. The
  cookbook's centralize-configuration guidance is explicit that "the application code does not care
  about multiple handlers" — configure them once to avoid duplicate output
  (https://docs.python.org/3/howto/logging-cookbook.html).
- **Typical fan-out (ESTABLISHED pattern).** Root at DEBUG; a console `StreamHandler` at INFO for
  humans; a file or JSON handler at DEBUG for machines/retention. This realizes goal1 (DEBUG for
  contributors) and goal2 (structured INFO+ for monitoring) from a single configuration.
- **VERSION-DEPENDENT items to freeze against the supported Python range** (see §12 / open questions):
  `basicConfig(encoding=...)` (3.9+), `exc_info` accepting an exception instance (3.5+), `stacklevel=`
  support, and `lastResort` fallback behavior. Pin these to the project's actual minimum version.

---

## 6. Goals mapping (severity + architecture → the three goals)

**goal1 — debugging aid for contributors and reusers (ESTABLISHED).** Use DEBUG/INFO at **component
seams** with descriptive context, and rely on `getLogger(__name__)` so "it is intuitively obvious
where events are logged just from the logger name"
(https://docs.python.org/3/howto/logging.html). Map: **INFO** when a component starts/finishes a
meaningful unit of work and at public-API boundaries; **DEBUG** for internal decisions, inputs, and
branch points. Using `logging` rather than `print` lets the reuser dial verbosity without touching the
component's code — the source is obvious from the logger name, and the level is the application's to
set.

**goal2 — monitor the software in action (ESTABLISHED).** Use **INFO/WARNING/ERROR/CRITICAL** as the
operational signal — WARNING/ERROR/CRITICAL are the alerting tiers per their official semantics (§2).
Prefer **structured/JSON** output and attach **correlation/trace IDs** so one logical request can be
stitched across components/services. Structured/contextual logging is supported via (a) `extra=` /
`LoggerAdapter`, (b) Filters that inject fields, (c) `contextvars`-backed filters for async/threaded
request scope, or (d) `structlog`/JSON formatters
(https://docs.python.org/3/howto/logging-cookbook.html;
https://www.structlog.org/en/stable/contextvars.html). Detailed in §7–§8.

**goal3 — per-component reuse (ESTABLISHED mechanism; BEST-EFFORT guarantee).** The NullHandler
discipline + zero global configuration in component code is exactly what makes components reusable.
Because each component uses `getLogger(__name__)`, adds no handlers (except a top-level NullHandler),
and never configures root/`basicConfig`, the consuming application owns all routing, levels, and
formats; propagation (default True) carries component records to the app's root handlers automatically
(https://docs.python.org/3/howto/logging.html; https://docs.python.org/3/library/logging.html). This is
the **direct mechanical link** between the official library guidance and goal3. As in §4, it is
**explicitly best-effort, not absolute** — enforced by discipline, not by the runtime.

---

## 7. Structured & contextual logging

**ESTABLISHED — `extra=` and `LoggerAdapter`.** Passing `extra={...}` to a log call injects keys onto
the `LogRecord` that a formatter can then render. `LoggerAdapter` is "an easy way in which you can pass
contextual information"; its `process()` "inserts an `extra` key in the keyword argument whose value is
the dict-like object passed to the constructor"
(https://docs.python.org/3/howto/logging-cookbook.html).
**Reserved-key caveat (ESTABLISHED stdlib behavior):** keys in `extra` must **not** collide with
reserved `LogRecord` attributes (e.g. `message`, `asctime`, `args`) or `logging` raises. Choose
namespaced field names to avoid collisions.

**ESTABLISHED — Filters as field injectors.** "You can also add contextual information to log output
using a user-defined `Filter`. Filter instances are allowed to **modify** the LogRecords passed to
them, including adding additional attributes"
(https://docs.python.org/3/howto/logging-cookbook.html). A filter is the right place to stamp
process-wide or request-scoped fields onto every record without touching call sites.

**ESTABLISHED — `structlog` (optional, for goal2 JSON pipelines).** `structlog` is built from chains of
**processors** that take and return dicts, **bound loggers** that accumulate context, and renderers for
"JSON, logfmt, as well as pretty console output out-of-the-box." It integrates with the stdlib via
`structlog.stdlib` (`LoggerFactory`, `BoundLogger`, `ProcessorFormatter`) so structlog-rendered events
can flow through stdlib handlers
(https://www.structlog.org/en/stable/; https://www.structlog.org/en/stable/standard-library.html).
**VERSION-DEPENDENT — configure once, then freeze.** structlog docs recommend
`cache_logger_on_first_use=True` to "effectively freeze configuration after creating the first bound
logger," implying one-time configuration at startup
(https://www.structlog.org/en/stable/standard-library.html).
**OPEN — library-vs-app split for structlog.** structlog publishes **no** explicit library-vs-app
guidance; by analogy with the stdlib rule, a reusable component should **not** call
`structlog.configure()` — that belongs to the application. Tag "libraries shouldn't configure structlog"
as **best-practice/project-policy**, not vendor doctrine.

---

## 8. Correlation / trace IDs

**ESTABLISHED — stdlib-native via `contextvars` + Filter.** For multithreaded/async code the cookbook
gives a `contextvars.ContextVar` pattern: request-scoped vars are set at the request boundary, and a
**Filter** reads them and stamps fields (e.g. `record.method`, `record.ip`, `record.user`) onto every
record. This is the stdlib-native correlation-ID mechanism — context-local, async-safe, and requires no
change at the individual call sites
(https://docs.python.org/3/howto/logging-cookbook.html).

**ESTABLISHED — `structlog.contextvars`.** structlog provides "a global structlog context that is local
to the current execution context": call `clear_contextvars()` at request start,
`bind_contextvars(request_id=...)` to stamp correlation IDs, and place the `merge_contextvars`
processor **first** so "any context-local binds get included in all of your log messages"
(https://www.structlog.org/en/stable/contextvars.html).

**Correlation transport is a scoping decision (OPEN / project policy).** Choose the lightest transport
that fits: a stdlib `contextvars` filter or `structlog.contextvars` for a single process; full
**OpenTelemetry** `trace_id`/`span_id` propagation **only if the application is actually distributed /
multi-service**. Do not adopt OTel for a single-process app. See open question on correlation-ID
transport.

---

## 9. Performance: lazy `%`-style args and `isEnabledFor`

**ESTABLISHED — lazy `%`-style formatting.** Use the `%`-style argument form, e.g.
`logging.warning('%s before you %s', 'Look', 'leap!')` — the args are merged into the message **only if
the record is actually emitted** (https://docs.python.org/3/howto/logging.html). An **f-string is
evaluated eagerly regardless of level**, defeating this optimization, so **f-strings are discouraged in
hot/DEBUG paths**.

**ESTABLISHED — guard expensive arguments with `isEnabledFor`.** When building an argument is itself
costly, gate the whole call:
`if logger.isEnabledFor(logging.DEBUG): logger.debug("Message with %s, %s", expensive1(), expensive2())`
(https://docs.python.org/3/howto/logging.html). This avoids evaluating the expensive arguments when
DEBUG is disabled — which, given the default WARNING threshold (§2), is the common case in production.

**Strict-typing friction (VERSION-DEPENDENT — agree a lint exception).** Strictly-typed projects and
linters (mypy/pyright/ruff) sometimes flag `%`-style args or push "fix" suggestions toward f-strings.
The `%`-args form is the **intentional, official lazy-logging idiom**; document it as such and agree a
**lint exception** so the recommended pattern is not auto-"fixed" into eager f-strings (see §12 and the
open question on lint configuration).

---

## 10. Exceptions: log ONCE at the handling boundary

**ESTABLISHED — `logger.exception()` and `exc_info`.** `logger.exception()` "logs a message with level
ERROR… Exception info is added to the logging message. This method should **only** be called from an
exception handler." `exc_info`: "If exc_info does not evaluate as false, it causes exception information
to be added to the logging message… otherwise, `sys.exc_info()` is called"
(https://docs.python.org/3/library/logging.html). So: use `logger.exception('...')` inside an `except`
block to log at ERROR **with traceback**; use `logger.warning('...', exc_info=True)` (or any level) to
attach a traceback at a **non-ERROR** level. **VERSION-DEPENDENT:** since Python 3.5 `exc_info` can
accept an exception **instance** directly.

**OPEN / best-practice — log once at the handling boundary, not at every re-raise.** The cookbook's
centralize-configuration guidance ("the application code does not care about multiple handlers";
configure once to avoid duplicate output) **supports** the principle, but the docs do not state "log
once at the handling boundary" verbatim
(https://docs.python.org/3/howto/logging-cookbook.html). The design rule: let exceptions **propagate
carrying context** (`raise` / `raise … from …`), and log them **exactly once** with
`logger.exception()` at the layer that actually **handles/swallows** them (or at the top-level
boundary). Re-raising **and** re-logging at every layer produces duplicate stack traces and noise.
**CROSS-REFERENCE `error_tracing_contract_manifest.md`:** that manifest owns the propagation/chaining
contract (`raise … from …`, preserving the original cause); this rule is its natural logging
complement — the error-tracing layer preserves the cause, this layer logs it **once** where it is
handled. Where exactly the "handling boundary" sits in this codebase's layering (per public-API call?
per CLI/HTTP entrypoint?) must be pinned to that sibling manifest (open question).

---

## 11. Security: never log secrets or PII

**OPEN / best-practice (NOT in python.org logging docs).** Never log credentials, tokens, PII, or full
request bodies; redact before logging. This is a universally accepted security practice but it is **not
stated** in the cited python.org logging pages, so do **not** attribute it to those docs. Implement via
**redaction in a Filter or structlog processor**, or by simply never placing secrets in the message or
`extra`. For an authoritative citation, reference **OWASP** logging guidance, not python.org. The
concrete redaction mechanism (filter vs processor) and the allow/deny-list of fields are an **internal
policy** decision (open question).

---

## 12. Strict-typing notes

- **`%`-style lazy args vs linters (VERSION-DEPENDENT).** As in §9, the official lazy-logging idiom uses
  `%`-style args, which mypy/pyright/ruff may flag or try to rewrite to f-strings. Agree an explicit
  **lint exception / configuration** so the recommended pattern survives auto-formatting. This is a
  required project decision, not optional polish.
- **Typing around loggers and adapters.** `logging.getLogger(__name__)` returns a `logging.Logger`;
  `LoggerAdapter` is generic over the underlying logger. Keep the `extra=`/adapter context dicts typed
  where the strict-typing posture in `python_typing_contract_manifest.md` requires it; the reserved-key
  caveat (§7) is a runtime constraint the type checker will **not** catch.
- **Version-gated APIs to freeze (VERSION-DEPENDENT).** `basicConfig(encoding=...)` (3.9+),
  `exc_info`-accepts-instance (3.5+), and `stacklevel=` support must be pinned to the project's minimum
  supported Python (open question on target versions).

---

## 13. Checklists

### Library / reusable-component author checklist
- [ ] `logger = logging.getLogger(__name__)` at module top — never instantiate `Logger` directly. (ESTABLISHED)
- [ ] **Never** log to the root logger. (ESTABLISHED)
- [ ] **Never** call `basicConfig` or otherwise configure root. (ESTABLISHED)
- [ ] Add **no handlers** except a single `logging.NullHandler()` on the **top-level package** logger. (ESTABLISHED)
- [ ] No logging side-effects at import beyond `getLogger(__name__)` and the top-level `NullHandler`. (best-practice / OPEN-wording)
- [ ] Emit DEBUG/INFO at seams with descriptive context (goal1); leave WARNING/ERROR/CRITICAL for genuine operational events (goal2). (ESTABLISHED)
- [ ] Use lazy `%`-style args; guard expensive args with `isEnabledFor`; do not use f-strings in hot paths. (ESTABLISHED)
- [ ] Log exceptions **once**, at the handling boundary, with `logger.exception()`; let them propagate carrying context elsewhere (cross-ref `error_tracing_contract_manifest.md`). (OPEN/best-practice)
- [ ] Never put secrets/PII into messages or `extra`. (OPEN/best-practice; OWASP)
- [ ] Do **not** call `structlog.configure()` in component code. (OPEN/project-policy)

### Application / consumer author checklist
- [ ] Configure logging **once at startup** (prefer `dictConfig` for any multi-handler setup; `basicConfig` for the trivial case). (ESTABLISHED)
- [ ] Attach handlers to the **root** logger and let propagation route component records. (ESTABLISHED)
- [ ] Set the root/logger level to the **lowest** severity you want to capture; fan out via **per-handler levels** (e.g. console INFO, file/JSON DEBUG). (ESTABLISHED)
- [ ] Choose console vs file/JSON handlers; add a JSON formatter (stdlib or `structlog.ProcessorFormatter`) for goal2 machine consumption. (ESTABLISHED)
- [ ] Inject correlation/trace IDs via a `contextvars` Filter or `structlog.contextvars` (`clear`/`bind`/`merge_contextvars`); adopt OpenTelemetry only if distributed. (ESTABLISHED mechanism; transport is OPEN/project-policy)
- [ ] Add a redaction Filter/processor for secrets/PII. (OPEN/best-practice; OWASP)
- [ ] Freeze version-gated APIs (`encoding=`, `exc_info` instance, `stacklevel=`) against the supported Python range. (VERSION-DEPENDENT)
- [ ] Agree a lint exception so `%`-style lazy-logging args are not auto-rewritten to f-strings. (VERSION-DEPENDENT)

---

## Open questions

1. **structlog/JSON mandate for goal2?** Mandate structlog/JSON, or keep stdlib-only as the baseline
   with structlog optional? structlog gives no library-vs-app guidance, so "components never call
   `structlog.configure()`" is **project policy**, not vendor doctrine.
2. **Where is the "handling boundary"?** The log-once rule (§10) needs the boundary pinned to this
   codebase's layering (per public-API call? per CLI/HTTP entrypoint?) against
   `error_tracing_contract_manifest.md`.
3. **Correlation-ID transport in scope?** stdlib `contextvars` filter, `structlog.contextvars`, or full
   OpenTelemetry trace/span propagation — adopt OTel only if the app is actually distributed/multi-service.
4. **Secret-redaction mechanism + field lists.** Filter vs processor; which keys allow/deny. "Never log
   secrets" is not in python.org docs — needs an internal policy plus an OWASP cite (§11).
5. **Exact target Python version(s).** Affects `lastResort` fallback, `exc_info`-accepts-instance (3.5+),
   `basicConfig(encoding=)` (3.9+), and `stacklevel=`. Freeze version-dependent items against the
   supported range.
6. **Strict-typing tooling stance on `%`-style lazy args.** mypy/pyright/ruff may flag them vs the
   official lazy-logging idiom — agree a lint configuration so the recommended pattern is not
   auto-"fixed" into f-strings.

---

## Sources

- Python `logging` — Logging facility (library reference): level constants and numeric values, NOTSET
  sentinel semantics, when-to-use table, four object types, two-stage thresholds, `getLogger` singleton
  rule, dotted hierarchy, propagation defaults, `exception()`/`exc_info` —
  https://docs.python.org/3/library/logging.html . Accessed 17 Jun 2026.
- Python `logging` HOWTO: when-to-use table, default WARNING level, print vs `warnings.warn` vs logging,
  effective-level walk-up, "Configuring Logging for a Library" (no root logging, no non-Null handlers,
  no `basicConfig`, `NullHandler`), logger-name intuition, lazy `%`-args and `isEnabledFor` —
  https://docs.python.org/3/howto/logging.html . Accessed 17 Jun 2026.
- Python `logging` Cookbook: `LoggerAdapter`/`extra=`, Filters that modify records, `contextvars`
  correlation pattern, centralized configuration / avoid-duplicate-output guidance —
  https://docs.python.org/3/howto/logging-cookbook.html . Accessed 17 Jun 2026.
- Python `logging.handlers`: `NullHandler` ("instances do nothing with error messages") —
  https://docs.python.org/3/library/logging.handlers.html . Accessed 17 Jun 2026.
- structlog — overview (processors, bound loggers, JSON/logfmt/console renderers) —
  https://www.structlog.org/en/stable/ . Accessed 17 Jun 2026.
- structlog — Context Variables (`clear_contextvars`/`bind_contextvars`/`merge_contextvars`) —
  https://www.structlog.org/en/stable/contextvars.html . Accessed 17 Jun 2026.
- structlog — Standard Library integration (`LoggerFactory`, `BoundLogger`, `ProcessorFormatter`,
  `cache_logger_on_first_use`) — https://www.structlog.org/en/stable/standard-library.html . Accessed
  17 Jun 2026.
- OWASP Logging guidance — referenced as the authoritative source for "never log secrets/PII" (not
  stated in the python.org logging docs); cite the specific OWASP page when fixing the redaction policy.
  Accessed 17 Jun 2026.
