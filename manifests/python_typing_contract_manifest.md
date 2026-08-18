# Python Typing & Contract-Enforcement — Ground-Truth Manifest

**Version anchor:** This manifest is anchored to mid-2026 stable releases. **CPython 3.14** (released 7 October 2025) is the latest stable feature release; **CPython 3.13** remains widely deployed and is supported until 31 October 2029 per `devguide.python.org/versions/` (3.13 was the first release to extend the full bugfix phase from 1.5 to 2 years within the 5-year total). Static checkers: **mypy 1.19.0** was released 28 November 2025, and **mypy 2.0.0 / 2.1.0** shipped to PyPI on 6 May 2026 and 11 May 2026 respectively — so the 2.x line is now released, not merely in progress. **pyright 1.1.410** was released 1 June 2026 (PyPI), and pyright's default Python target was changed from 3.13 to 3.14 in the 1.1.40x series. **pydantic v2** (current 2.x) is the dominant runtime-validation library. Tag legend: **ESTABLISHED** = well-documented, stable across releases; **VERSION-DEPENDENT** = behavior bound to a specific Python/checker version; **OPEN** = no authoritative source found.

---

## TL;DR

- **"Strict static typing" is not a single, portable meaning.** `mypy --strict` and pyright `strict` enable *different, version-specific* rule sets and use *different inference algorithms*, so a contract spec must name the checker, pin its version, and commit the exact enabled-rule set to version control — never just say "strict."
- **The type system cannot express value ranges, cross-field invariants, ordering/temporal constraints, units, or stateful protocols.** These MUST become boundary validation (pydantic) and/or runtime contracts (icontract/deal/`__post_init__`) and be documented in docstrings — never assumed to be carried by annotations. `typing.cast` has zero runtime effect, `Final`/`Protocol`/`Annotated` constraints are checker-only or metadata-only, and `assert` is stripped under `python -O`.
- **Parse once at the boundary, then trust types internally.** Validate untrusted data at the system edge (pydantic v2, Rust-cored, 5–50× faster than v1), produce trusted typed objects, and reserve `assert` for internal "can't happen" guards — raising explicit exceptions for anything that must run in production.

---

## Key Findings

1. **mypy `--strict` (mypy 1.19 / unchanged through 2.x) enables a documented but mutable set of 15 flags**, and explicitly does NOT forbid all `Any`. mypy also *skips unannotated function bodies entirely* by default — its single biggest divergence from pyright.
2. **pyright has four modes** (`off`/`basic`/`standard`/`strict`; CLI default `standard`, Pylance default `off`). Its `strict`-only `reportUnknown*` family flags implicit `Any` from untyped code and has no direct mypy equivalent.
3. **A codebase clean under `mypy --strict` is frequently NOT clean under `pyright --strict`** — they diverge by design; there is no authoritative cross-conformance mapping.
4. **`typing.cast` returns its second argument unchanged with no check or coercion** — an unchecked promise the checker trusts blindly.
5. **pydantic v2 is a ground-up rewrite** with a Rust core and renamed APIs (`@validator`→`@field_validator`, `Config`→`model_config`, `.dict()`→`.model_dump()`).
6. **`assert` is removed from bytecode under `-O`/`PYTHONOPTIMIZE`** and must never be used for validation, auth, or input checks.
7. **`frozen=True` dataclasses give shallow, bypassable immutability**; the type system cannot express deep immutability or purity at all.

---

## Details

### 1. Static type checkers and "strict" modes

**mypy `--strict` — what it enables (VERSION-DEPENDENT; mypy 1.19, Nov 2025).** mypy's own docs warn: "the exact list of flags enabled by running `--strict` may change over time." As of mypy 1.19 (`mypy --help`), `--strict` turns on this exact set: `--warn-unused-configs`, `--disallow-any-generics`, `--disallow-subclassing-any`, `--disallow-untyped-calls`, `--disallow-untyped-defs`, `--disallow-incomplete-defs`, `--check-untyped-defs`, `--disallow-untyped-decorators`, `--warn-redundant-casts`, `--warn-unused-ignores`, `--warn-return-any`, `--no-implicit-reexport`, `--strict-equality`, `--strict-bytes`, and `--extra-checks`. `--strict-bytes` disables treating `bytearray`/`memoryview` as subtypes of `bytes` (per PEP 688); it is now **default in mypy 2.0** — confirmed by the mypy 2.0 changelog: "Per PEP 688, mypy no longer treats bytearray and memoryview values as assignable to the bytes type" (default in 2.0, PR 18371). Likewise `--local-partial-types` becomes default in 2.0. Crucially, `--strict` does NOT enable `--disallow-any-explicit`, `--warn-unreachable`, or `--disallow-any-decorated` — teams that believe "strict" forbids all `Any` are mistaken (ESTABLISHED caveat). The mypy docs state that with `--strict` "you will basically never get a type related error at runtime without a corresponding mypy error, unless you explicitly circumvent mypy somehow."

**mypy default behavior (ESTABLISHED).** Without `--strict` or `--check-untyped-defs`, mypy SKIPS the bodies of unannotated functions entirely — a function with no annotations gets no type checking. This is the single biggest divergence from pyright and the most common surprise for teams.

**pyright modes (VERSION-DEPENDENT; pyright 1.1.410, June 2026).** pyright's `typeCheckingMode` has four values: `"off"`, `"basic"`, `"standard"`, `"strict"`. The CLI default is `"standard"`; the Pylance VS Code extension default is `"off"`. (`"standard"` was added later — pyright originally shipped only `basic` and `strict`; `standard` was introduced to match the Python typing-spec conformance baseline.) `off` still reports syntax errors, unresolved imports, and undefined variables. The authoritative source for which rules each mode enables is the per-mode default-severity table in `microsoft/pyright/blob/main/docs/configuration.md`, which must be read from the version-matched build.

**What pyright `strict` adds over `standard`/`basic` (VERSION-DEPENDENT).** strict mode flips on a large family of rules that are `"none"` in lower modes, notably: `reportMissingParameterType`, `reportMissingTypeArgument`, `reportUnknownParameterType`, `reportUnknownArgumentType`, `reportUnknownLambdaType`, `reportUnknownVariableType`, `reportUnknownMemberType`, `reportUnusedImport`, `reportUnusedClass`, `reportUnusedFunction`, `reportUnusedVariable`, `reportUntypedFunctionDecorator`, `reportUntypedClassDecorator`, `reportUntypedBaseClass`, `reportUntypedNamedTuple`, plus boolean inference rules `strictListInference`, `strictDictionaryInference`, `strictSetInference`, and `reportMissingTypeStubs`. The `reportUnknown*` family — which flags implicit `Any` propagating from untyped third-party code — is the defining feature of pyright strict and has no direct mypy equivalent.

**Where they diverge in inference (ESTABLISHED).** (1) mypy skips unannotated function bodies by default; pyright analyzes them and infers types. (2) pyright's `reportUnknown*` rules surface implicit-`Any` from untyped imports that mypy tolerates silently. (3) pyright performs more aggressive control-flow-based narrowing and reachability analysis. (4) The two use different inference algorithms, so a codebase clean under `mypy --strict` will frequently NOT be clean under `pyright --strict`, and vice versa. On speed, per pydevtools.com: "On-demand type computation historically outran mypy by 3-5x; mypy's 1.18+ mypyc-compiled builds have closed that gap, and ty is now significantly faster than both."

**Implication for a team mandating "strict static typing" as a global rule (decision).** "Strict" is not a portable, single-meaning setting. A contract spec must name the checker AND its version AND pin the flag set, because (a) `mypy --strict`'s flag list changes between releases (and defaults shifted in mypy 2.0), (b) pyright's rule-per-mode table changes between releases, and (c) the two tools disagree on inference. The correct mandate is: "code must pass `mypy --strict` (pinned version X) and `pyright --strict` (pinned version Y), with the exact enabled-rule set committed to version control via `pyproject.toml`/`mypy.ini`/`pyrightconfig.json`." Treat any deviation as a spec violation.

### 2. The typing vocabulary for contracts

Each construct below is verified against `docs.python.org`, `typing.python.org`, and the cited PEP.

- **`typing.Protocol` — structural typing (PEP 544; Python 3.8). ESTABLISHED.** Defines an interface by shape (methods/attributes), not inheritance: any class with the right shape conforms, with no explicit subclassing. Contract use: express "anything that can `read()`/`close()`" capability contracts, especially for third-party types you do not control. Checked statically only; `@runtime_checkable` enables `isinstance()` but verifies only member *existence*, not signatures or types, and "can be surprisingly slow" (mypy docs).
- **`abc.ABC` — nominal typing (`abc` module). ESTABLISHED.** Conformance requires explicit inheritance/registration. Use when implementations share code or when you control the hierarchy and want enforced subclassing. Contrast: Protocol = structural/duck, ABC = nominal/declared.
- **`@dataclass` (`dataclasses` module; PEP 557; Python 3.7). ESTABLISHED.** Generates `__init__`/`__repr__`/`__eq__` from annotated fields. Stdlib dataclasses do NOT validate types at runtime — annotations are inert. Distinction: `attrs` (`@define`) offers richer validation/converters and slots by default; `pydantic` (`BaseModel`, or `pydantic.dataclasses.dataclass`) performs full runtime validation/coercion. Use stdlib dataclass for plain typed records; use attrs/pydantic when you need runtime enforcement.
- **`TypedDict` (`typing`; PEP 589; Python 3.8). ESTABLISHED.** Types a dict with a fixed set of string keys and per-key value types. At runtime it is a plain `dict` — no enforcement. Extensions: `Required`/`NotRequired` (PEP 655, 3.11), `ReadOnly` (PEP 705, 3.13), closed/extra-items (PEP 728, targeted at 3.15). The keyword-argument creation form was deprecated in 3.11 and removed in 3.13.
- **`NamedTuple` (`typing`; based on `collections.namedtuple`). ESTABLISHED.** Immutable typed tuple with named fields. Generic NamedTuples supported from 3.11.
- **`Enum` (`enum` module; Python 3.4) and `Literal` (`typing`; PEP 586; Python 3.8). ESTABLISHED.** `Enum` gives a closed set of named constants checkable at runtime and statically. `Literal["a","b"]` constrains a value to specific literal constants at the type level only. Per the mypy enum spec, enum members must be left unannotated. Contract use: model closed value domains (states, modes, discriminators).
- **`NewType` (`typing`; PEP 484; Python 3.5.2; became a class in 3.10). ESTABLISHED.** `UserId = NewType('UserId', int)` creates a distinct subtype of `int` for the checker with minimal runtime cost (a thin callable that returns its argument). Contract use: prevent mixing semantically different values that share a representation (e.g., `UserId` vs `OrderId`).
- **`Generic`/`TypeVar` (PEP 484; 3.5), `ParamSpec` (PEP 612; 3.10), `TypeVarTuple` (PEP 646; 3.11). ESTABLISHED.** `TypeVar` parameterizes by a single type; `ParamSpec` captures a callable's full parameter signature (for decorators); `TypeVarTuple` enables variadic generics (`tuple[int, *Ts]`). PEP 695 (Python 3.12) added the `class Foo[T]:` / `def f[T]()` native syntax and the `type` statement; variance is inferred under PEP 695 rather than declared.
- **`Self` (`typing`; PEP 673; Python 3.11). ESTABLISHED.** Annotates methods returning an instance of their own (possibly subclass) type — fluent/builder APIs, `__enter__`, copy/clone. Equivalent to but more concise than a bound `TypeVar`. Rejected in staticmethods and metaclasses per the PEP.
- **`Final` and `@final` (`typing`; PEP 591; Python 3.8). ESTABLISHED.** `Final` marks a name that must not be reassigned/redefined/overridden; `@final` marks a class/method as non-subclassable/non-overridable. "There is no runtime checking of these properties" (typing docs) — enforced by checkers only.
- **`Annotated` (`typing`; PEP 593; Python 3.9). ESTABLISHED.** `Annotated[T, x]` attaches arbitrary metadata `x` to type `T`. Tools without special logic for `x` "should ignore it and simply treat the type as T." Basis for pydantic field constraints and the `annotated-types` library.
- **`Never` and `NoReturn` (`typing`). VERSION-DEPENDENT.** `NoReturn` (PEP 484; added 3.6.2) annotates functions that never return normally. `Never` (added in Python 3.11 with NO dedicated PEP) is the explicit spelling of the bottom type (uninhabited). Checkers treat the two equivalently. NOTE: the task's reference to "PEP 661" is incorrect — PEP 661 is "Sentinel Values" (accepted for 3.15) and is unrelated to `Never`; `Never` has no PEP.

### 3. Explicit conversion and cast discipline

- **`typing.cast(typ, val)` (PEP 484; `typing`). ESTABLISHED.** Has NO runtime effect: per the typing spec, "At runtime a cast always returns the expression unchanged – it does not check the type, and it does not convert or coerce the value," and the CPython implementation is literally `def cast(typ, val): return val`. It is a promise the checker trusts blindly — an unchecked assertion, not a conversion. A wrong cast silently propagates a lie until something downstream crashes.
- **`assert_type(val, typ)` (`typing`; Python 3.11; NO dedicated PEP). VERSION-DEPENDENT.** Asks the checker to confirm the inferred type of `val` equals `typ`; "At runtime this does nothing: it returns the first argument unchanged." It checks *type equivalence* (not assignability), so asserting a parent type/Protocol against an inferred concrete subtype fails. Use it in test files to lock down inferred types. (The task's "PEP 675" attribution is wrong — PEP 675 is `LiteralString`; `assert_type` has no dedicated PEP, confirmed via PEP 729.)
- **`reveal_type(obj)` (`typing`; runtime function added Python 3.11). VERSION-DEPENDENT.** Causes the checker to emit the inferred static type as a diagnostic (e.g., `Revealed type is "builtins.int"`). Historically a checker-only magic name; now also importable at runtime.
- **Sources of implicit `Any` and how strict surfaces them (ESTABLISHED).** Implicit `Any` enters via: untyped third-party imports/missing stubs, unannotated function parameters/returns, untyped containers, and `# type: ignore`. `mypy --strict` catches missing annotations via `--disallow-untyped-defs`/`--disallow-incomplete-defs` and unwarranted returns via `--warn-return-any`, and can audit residual `Any` via the `--any-exprs-report`. pyright strict's `reportUnknown*` family is the most direct surface for implicit `Any` from untyped code.
- **"No implicit coercion / explicit conversion" concretely (ESTABLISHED).** It means: do not rely on truthiness as a stand-in for an explicit boolean test or count; do not depend on implicit numeric promotion at type boundaries; call `int(x)`, `str(x)`, `float(x)` explicitly when changing representation. `mypy --strict-equality` (in `--strict`) prohibits comparisons between non-overlapping types (e.g., `42 == 'no'`, `b'x' != s`), catching a major class of silent-coercion bugs.
- **When a cast is genuinely unavoidable, and how to confine it (decision).** A cast is legitimate only when the human knows something the checker provably cannot — e.g., narrowing an `object`/`Any` from a deserializer where a runtime `isinstance` check just preceded it, or working around a missing/incorrect third-party stub. Confine it: (1) put the `cast` on the smallest possible expression immediately after a runtime check that actually validates the assumption; (2) add a comment stating WHY it is safe; (3) never use `cast` to silence a real type error you could fix structurally. With `--warn-redundant-casts` (in `--strict`), mypy flags casts that are unnecessary, keeping the cast surface minimal.

### 4. What the type system CANNOT express

The Python type system is (broadly) about the *shape* and *identity* of values, not their runtime *values* or *history*. The following are out of scope for static checkers and MUST become runtime contracts or boundary validation — never silently dropped (principle).

- **Value-range constraints (ESTABLISHED).** "a positive int", "0 ≤ x ≤ 100", "non-empty string". The type system has no dependent types; `int` cannot be narrowed to "positive int" statically.
- **Cross-field invariants (ESTABLISHED).** "`start_date` ≤ `end_date`", "if `kind=='A'` then `payload` is required". No checker enforces relationships between fields.
- **Ordering/temporal constraints (ESTABLISHED).** "`open()` must precede `read()`", "monotonically increasing timestamps". Sequencing is a stateful runtime property.
- **Units of measure (ESTABLISHED).** "meters vs feet", "seconds vs milliseconds". Best partial mitigation is `NewType` per unit, but arithmetic between them is not dimensionally checked.
- **Stateful protocols / typestate (ESTABLISHED).** "a socket is connected before send", "a transaction is open". The type of an object does not change as its internal state mutates (no typestate in Python's type system).

**Partial mitigations and their limits (ESTABLISHED).** (1) `Literal` and `Enum` close a value domain but cannot express ranges or relations. (2) `Annotated[int, ...]` carries constraint metadata — via the `annotated-types` library (current v0.7.0): `Gt`, `Ge`, `Lt`, `Le`, `Interval`, `MultipleOf`, `MinLen`, `MaxLen`, `Len`. These are PURE METADATA that static type checkers IGNORE per PEP 593 ("Annotated[T, x] should be treated as T by any tool or library without special logic for x"); the `annotated-types` README is explicit that "annotated-types avoids runtime checks for performance" and that "Downstream implementors may choose to raise an error, emit a warning, silently ignore a metadata item, etc." — i.e., constraints like `Gt(18)` are enforced only if a runtime consumer (e.g., pydantic) reads them. (3) `NewType` distinguishes representations but adds no validation. (4) Refinement-style/verification tools (e.g., CrossHair, which integrates with icontract) explore constraints but are analyzers/test-generators, not part of the type checker, and do not scale to arbitrary code. Conclusion: encode these invariants at the boundary (parsing/validation) and as runtime contracts in the core; document them in the contract docstring.

### 5. Runtime contract-enforcement landscape

- **pydantic (boundary validation/parsing). VERSION-DEPENDENT (v1 vs v2).** pydantic validates and coerces external data into typed models at runtime. **v2 is a ground-up rewrite**: the validation core (`pydantic-core`) was rewritten in **Rust**. Per Pydantic's official announcement (pydantic.dev, "Pydantic v2 Pre Release"): "Performance - Pydantic V2 is 5-50x faster than Pydantic V1"; this was independently reproduced by The Data Quarry: "Pydantic v2 performs ~1.3 million validations in roughly 6 seconds, while the exact same workflow in v1 took almost 30 seconds: that's a 5x improvement, for free!" API/behavior changes from v1→v2: `class Config` → `model_config` (a `ConfigDict`); `@validator` → `@field_validator`; `@root_validator` → `@model_validator`; `.dict()` → `.model_dump()`, `.json()` → `.model_dump_json()`; `parse_obj` → `model_validate`; `allow_mutation` config → `frozen`. v2 also added `TypeAdapter` for validating non-model types and four validator modes (before/after/plain/wrap, via `@field_validator(mode=...)` or `Annotated`-pattern `BeforeValidator`/`AfterValidator`). v2 is stricter by default (less silent coercion). **When it runs:** at model instantiation/validation (boundary). **Cost:** non-trivial per-object validation, but the Rust core makes it negligible for typical API workloads. **Where it belongs:** the system boundary (request/response parsing, config, deserialization), NOT hot inner loops.
- **dataclasses with `__post_init__` (`dataclasses`; stdlib). ESTABLISHED.** `__post_init__` runs after the generated `__init__` and is the canonical place for creation-time validation and derived fields. **When it runs:** at construction. **Cost:** whatever you write. **Where it belongs:** lightweight invariant checks on plain dataclasses when you do not want a pydantic dependency. Caveat: on a `frozen=True` dataclass, assigning derived attributes in `__post_init__` raises `FrozenInstanceError`; you must use `object.__setattr__(self, name, value)`.
- **Design-by-contract libraries. VERSION-DEPENDENT (maintenance status).** **icontract** (`@icontract.require` / `@icontract.ensure` / `@icontract.invariant`) provides preconditions, postconditions, and class invariants with informative violation messages and contract inheritance (precondition weakening / postcondition strengthening); current series 2.x (Snyk rates its maintenance "Healthy"); integrates with CrossHair and Hypothesis (icontract-hypothesis). **deal** (`@deal.pre`, `@deal.post`, `@deal.ensure`, `@deal.pure`, `@deal.raises`) offers DbC plus static analysis, a linter, property-based test generation, and the ability to disable contracts in production. Both are actively used. **When they run:** on each decorated call (runtime). **Cost:** per-call overhead proportional to the predicate. **Where they belong:** core-logic functions where invariants are non-trivial and worth documenting executably.
- **Plain `assert` statements. ESTABLISHED — with a critical caveat.** `assert cond, msg` is the cheapest runtime check, but Python's `-O` (and `-OO`) flag, or `PYTHONOPTIMIZE`, sets `__debug__=False` and STRIPS all `assert` statements from the compiled bytecode. Therefore `assert` MUST NEVER be used for data validation, input sanitization, authorization, or any check that must run in production. Use `assert` only for internal invariants/sanity checks that are acceptable to disable; raise explicit exceptions (`ValueError`, `TypeError`, custom) for anything that must always run. **Where it belongs:** developer-facing "this should never happen" guards, never boundary validation.

**Decision — boundary vs core placement.** Parse/validate untrusted data ONCE at the boundary (pydantic or explicit validation), producing trusted typed objects; then rely on types + targeted contracts/asserts internally. This is the "parse, don't validate" discipline: never re-validate trusted core data in hot paths, and never lose a boundary invariant by assuming the type system carries it.

### 6. Immutability and purity signalling

- **`frozen=True` dataclasses (ESTABLISHED).** Setting `@dataclass(frozen=True)` generates `__setattr__`/`__delattr__` that raise `FrozenInstanceError` on assignment. The CPython docs are explicit: "It is not possible to create truly immutable Python objects." The immutability is **shallow** — a frozen dataclass holding a `list` still allows mutation of that list's contents; and `object.__setattr__` can bypass the freeze entirely. Frozen + `eq=True` makes instances hashable (usable as dict keys/set members). There is a small `__init__` performance penalty (must use `object.__setattr__`).
- **`Final` (PEP 591; ESTABLISHED).** Signals "do not reassign/override" to the checker only — "There is no runtime checking of these properties." It prevents rebinding the name, not mutation of the referenced object.
- **Read-only containers (ESTABLISHED).** `Mapping`/`Sequence` (abstract, read-only interfaces) vs `MutableMapping`/`MutableSequence`; `tuple` and `frozenset` are genuinely immutable at the container level (but their elements may be mutable). Annotating a parameter as `Mapping[str, int]` tells the checker the callee will not mutate it — a *static* promise, not a runtime guarantee (the underlying object may still be a mutable `dict`).
- **`@property` without a setter (ESTABLISHED).** Exposes a read-only computed attribute; assignment raises `AttributeError` at runtime. Communicates "derived, not settable."
- **What the type system can/cannot guarantee (principle).** Checkers can enforce that *your code* does not reassign a `Final` name or mutate a `Mapping`-typed parameter, and `frozen`/`tuple`/`frozenset` give runtime shallow immutability. The type system CANNOT guarantee deep immutability, nor side-effect freedom / purity — there is no `pure`/`const` qualifier in Python's type system. A purity claim (e.g., `@deal.pure`) is either runtime-checked by a DbC library or convention-only; it is NOT checker-enforced. State the gap explicitly in contracts: distinguish "checker-enforced immutability" (limited, shallow) from "convention-only purity" (documented, unverified unless a runtime tool checks it).

### 7. Contract documentation conventions

**What belongs in the type signature vs. the docstring (decision).** The type signature carries everything the checker can verify: parameter/return types, `Optional`/union shape, generics, `Literal`/`Enum` domains, `Final`/`Self`, and `Protocol` conformance. The docstring carries everything the type system CANNOT express (see §4): **preconditions** (value ranges, non-emptiness, cross-argument relations), **postconditions** (guarantees about the return value, invariants preserved), **invariants** (object-state properties), and **error modes** (which exceptions are raised and under what conditions). Rule: if a checker can enforce it, put it in the signature; if only a human or a runtime check can enforce it, put it in the docstring (and back it with a runtime contract where it matters).

**Common docstring conventions (ESTABLISHED).** Three dominant machine-parseable styles, all supported by Sphinx (the latter two via the `sphinx.ext.napoleon` preprocessor):
- **Google style** — indented `Args:`, `Returns:`, `Raises:`, `Yields:` sections; highly readable.
- **NumPy style** — underlined `Parameters`/`Returns`/`Raises` headers with name-type-description blocks; verbose, favored in scientific code.
- **reStructuredText / Sphinx ("classic")** — `:param x:`, `:type x:`, `:returns:`, `:rtype:`, `:raises:` field lists; the reST style is the one referenced by PEP 287. PEP 257 defines the baseline docstring conventions (one-line summary, etc.).

Pick ONE style per project and enforce consistency; `Raises:`/`:raises:` is the canonical place to document error modes.

**Machine-checkable forms (ESTABLISHED).** (1) **doctest** — executable examples in docstrings (`>>> ...`) run by `python -m doctest`/pytest, keeping examples provably correct. (2) **icontract decorators** — `@require`/`@ensure`/`@invariant` make pre/postconditions executable and renderable into docs, so the contract and its documentation cannot drift. (3) **deal decorators** similarly. (4) **Type comments** (`# type:` / function `# type: (...) -> ...`) are the legacy pre-3.0-annotation form, still parsed by checkers but superseded by inline annotations; avoid in new code. The strongest contract documentation pairs a typed signature, a styled docstring (Google/NumPy/reST) with explicit `Raises`, and an executable contract (doctest or icontract/deal) for the invariants the type system cannot carry.

### 8. Open questions and version caveats

**VERSION-DEPENDENT items (pin the version in any contract spec):**
- `mypy --strict`'s exact flag set changes between releases (current set documented above for mypy 1.19). `--strict-bytes` and `--local-partial-types` became defaults in **mypy 2.0** (released May 2026); migrating from 1.x to 2.x can surface new errors.
- pyright's per-mode diagnostic-rule table changes between releases; the authoritative source is the version-matched `docs/configuration.md`. The CLI default mode is `standard`; Pylance default is `off`. pyright's default target moved to Python 3.14 in the 1.1.40x series.
- pydantic v1 vs v2 differ substantially (Rust core, renamed APIs, stricter defaults); FastAPI has dropped v1 support, accelerating v2 migration.
- `assert_type`, `reveal_type` (runtime), and `Never` all entered `typing` in Python 3.11.
- TypedDict feature set is release-bound: `Required`/`NotRequired` (3.11), `ReadOnly` (3.13), closed/extra-items (PEP 728, targeted 3.15); keyword-arg syntax removed in 3.13.
- PEP 695 native generic syntax requires Python 3.12+; PEP 649/deferred annotations are default in 3.14.

**OPEN items (no single authoritative source resolves these — flagged for the team):**
- Whether a codebase clean under `mypy --strict` is also clean under `pyright --strict`: NO — they diverge by design, but there is no authoritative cross-conformance matrix; the team must empirically pin both. (OPEN as to a canonical mapping.)
- The precise, complete strict-mode rule list for a *specific* future pyright build cannot be cited in advance; it must be read from that build's `configuration.md`. (OPEN/version-bound.)
- "design-by-contract" (the minimalist `Annotated`-based package on PyPI, distinct from icontract/deal) is explicitly marked by its author as not production-ready; treat as experimental. (OPEN maturity.)

---

## Recommendations

**Stage 1 — Pin the toolchain (do first).** Commit a `pyproject.toml` that pins exact versions of mypy (e.g., 2.1.x) and pyright (e.g., 1.1.410), the target `python_version`, and the full enabled-rule set for both. Do NOT write "use strict mode" in any spec; write the literal flag/rule lists. *Benchmark that changes this:* a checker major-version bump (mypy 1.x→2.x changed defaults) requires re-baselining and a fresh review of the enabled set.

**Stage 2 — Define the boundary.** Mandate pydantic v2 (or explicit validation) for ALL untrusted inputs — HTTP bodies, config, env, deserialized data — converting them to typed models/dataclasses at the edge. Forbid `assert` for any validation; require explicit exceptions there. *Threshold:* if a value can originate outside the process, it is boundary data and must be parsed, not assumed.

**Stage 3 — Encode the inexpressible.** For every value-range, cross-field, ordering, unit, or stateful invariant (§4), require either a pydantic validator (boundary) or an icontract/deal contract or `__post_init__` check (core), AND a docstring `Raises:`/precondition/postcondition entry. *Threshold:* any invariant the checker cannot verify must appear in BOTH a runtime check and the docstring.

**Stage 4 — Confine escape hatches.** Treat every `cast`, `# type: ignore`, and `Any` as a tracked debt: smallest scope, mandatory justifying comment, and CI gates (`--warn-redundant-casts`, `--warn-unused-ignores`, pyright `reportUnknown*`) to prevent silent growth. *Threshold:* a rising count of casts/ignores/`Any` in the report is a signal to refactor structurally rather than suppress.

**Stage 5 — Standardize documentation.** Choose one docstring style (Google/NumPy/reST) project-wide, require `Raises` on every public function, and back critical examples with doctest. *Threshold:* mixed styles in one project are a spec violation; fix before merge.

---

## Caveats

- **"Current" is release-bound.** Every flag list, default, and version statement here reflects mid-2026 stable releases; re-verify against the version-matched docs at each toolchain bump. The mypy `--strict` flag set and the pyright per-mode rule table are explicitly documented by their maintainers as subject to change between releases.
- **The task contained two factual errors, corrected here:** `assert_type` is NOT introduced by PEP 675 (PEP 675 is `LiteralString`; `assert_type` has no dedicated PEP and landed in Python 3.11); and `Never` is NOT tied to PEP 661 (PEP 661 is "Sentinel Values"; `Never` has no PEP and landed in 3.11).
- **Runtime tools enforce; the type system documents.** Static checkers verify shape, not values, history, or purity. Any claim that "strict typing guarantees correctness" is false: the type system cannot carry §4 invariants, `cast`/`Final`/`Annotated` are checker-or-metadata-only, and `assert` vanishes under `-O`.
- **Cross-checker conformance is empirical.** There is no authoritative matrix mapping `mypy --strict` clean ⇒ `pyright --strict` clean; teams must run and pin both.
- **Some maturity assessments rely on secondary sources** (e.g., Snyk's "Healthy" rating for icontract, benchmark reproductions for pydantic); these are corroborating, not primary, and should be re-checked if a dependency decision hinges on them.

---

## Sources

All URLs accessed 16 June 2026.

- CPython, "typing — Support for type hints," docs.python.org/3/library/typing.html
- CPython, "dataclasses — Data Classes," docs.python.org/3/library/dataclasses.html
- CPython, "What's New in Python 3.14," docs.python.org/3/whatsnew/3.14.html
- CPython, "assert statement" / `__debug__` and `-O` behavior, docs.python.org
- Python.org, "Python 3.14.0 release," python.org/downloads/release/python-3140/; "Status of Python versions," devguide.python.org/versions/
- typing spec, "Type checker directives" (cast, assert_type, reveal_type), typing.python.org/en/latest/spec/directives.html
- typing spec, "Typed dictionaries," typing.python.org/en/latest/spec/typeddict.html
- typing_extensions docs, typing-extensions.readthedocs.io
- PEP 484 (Type Hints), PEP 544 (Protocols), PEP 557 (Data Classes), PEP 586 (Literal), PEP 589 (TypedDict), PEP 591 (Final), PEP 593 (Annotated), PEP 612 (ParamSpec), PEP 646 (TypeVarTuple), PEP 655 (Required/NotRequired), PEP 661 (Sentinel Values), PEP 673 (Self), PEP 675 (LiteralString), PEP 688 (bytes/bytearray), PEP 695 (Type Parameter Syntax), PEP 705 (ReadOnly TypedDict), PEP 729 (typing governance), peps.python.org
- mypy docs, "The mypy command line" and "configuration file," mypy.readthedocs.io/en/stable/command_line.html, /config_file.html
- mypy docs, "Protocols and structural subtyping," mypy.readthedocs.io/en/stable/protocols.html
- mypy changelog (1.18 / 1.19 / 2.0 / 2.1), mypy.readthedocs.io/en/stable/changelog.html; The Mypy Blog, mypy-lang.blogspot.com; PyPI mypy release history
- pyright docs, "Configuration" (typeCheckingMode, diagnostic rules), github.com/microsoft/pyright/blob/main/docs/configuration.md; PyPI pyright project page (1.1.410)
- pylance-release docs, python_analysis_typeCheckingMode.md, github.com/microsoft/pylance-release
- pydantic docs, "Migration Guide" and "Validators," docs.pydantic.dev/latest/migration/, /concepts/validators/
- pydantic, "Introducing Pydantic v2 / Pre-Release," pydantic.dev/articles/pydantic-v2; The Data Quarry (independent benchmark)
- icontract docs and repo, icontract.readthedocs.io, github.com/Parquery/icontract; Snyk advisor (maintenance status)
- deal repo, github.com/life4/deal
- annotated-types, PyPI (v0.7.0), pypi.org/project/annotated-types/
- Sphinx Napoleon docs (Google/NumPy styles), sphinx-doc.org/en/master/usage/extensions/napoleon.html; PEP 257, PEP 287
- pydevtools.com handbook, "How do Python type checkers compare?" and mypy/pyright reference pages