# Software Engineering Doctrine — UBEATS v2

**Status:** Binding · Revision 5
**Audience:** Every contributor to UBEATS v2, human or automated agent, with no
assumed prior knowledge of this project or of the document it is adapted from.
**Applies to:** `ubeats/` (the package), `tests/`, `contracts/`, and every ADR
in `architecture/adr/`.
**Does not apply to:** `git` hooks written as shell scripts (the one mandated
exception to "Python only" — see §3), which are thin and call the Python CLI.
**Citation convention:** "the source guidelines" (or "source guidelines §N")
refers to `Software Engineering Style Guidelines.md`, the document this
doctrine adapts. A bare `§N` in this document refers to this document's own
section N. Other documents cite this one as `Doctrine §N`. The two numbering
schemes coincide through §43; from §44 onward this document has no
source-guideline counterpart (§44 itself is the first example).

---

## 0. What this document is and is not

This doctrine is an **adaptation**, not a copy, of a general-purpose software
engineering style guide (`Software Engineering Style Guidelines.md`, hereafter
"the source guidelines") that was written for a different kind of program: a
requirements-management tool with a graphical client, a compiled core, and a
SQLite database. UBEATS v2 has none of those three things. It has a
command-line and agent-facing client, a Python core, and a filesystem of TOML
and Typst files with no query engine underneath it.

Every section below re-expresses the source guideline's underlying concern —
not its surface vocabulary — in terms of *this* project: the `Document` model
described in `PROPOSAL.md` §7, the ports and adapters of §8, the plan/apply
pipeline of §9, and the CLI of §10. Where the source guideline's literal
recommendation does not survive translation (most consequentially, "the core
should be a compiled binary"), this document says so explicitly, states what
is gained and lost, and prescribes binding compensating rules rather than
quietly dropping the concern.

Each rule below is tagged:

- **[BINDING]** — violating it is a defect. It has a stated enforcement
  mechanism (an automated CI gate, an architectural fitness test, or a named
  review-checklist item) in §46.
- **[ADVISORY]** — a strong default that may be departed from with a stated
  reason recorded in the change (commit message or ADR). Advisory rules are
  not enforced mechanically, but a reviewer may block a change that departs
  from one without explanation.

A rule with no tag is framing, not a rule.

---

## 1. Purpose and engineering philosophy

UBEATS v2 exists to make documents whose *structure and metadata* are as
trustworthy as compiled software: something a tool can check without running
the whole system, something an automated agent can query without guessing,
something a reviewer can validate before a single byte changes on disk.

The objective is not merely a working document generator. It is a system in
which:

- the shape of a document (its outline, its metadata, its lifecycle state) is
  a value a program can inspect in milliseconds, not a fact only the Typst
  compiler knows;
- a destructive operation (moving a section, deleting a file, cutting a
  release) is validated in full *before* it touches disk;
- the two localizations — English and Japanese — have their catalog *keys*
  checked complete by a mechanical test, not by a contributor remembering to
  update two files (key presence only — a catalog entry whose Japanese value
  is untranslated English still passes that check; see `FAILURE-MODES.md`
  FM-21, FM-22);
- an automated agent and a human author are, from the system's point of view,
  the same kind of client, subject to the same validation.

This doctrine therefore favors, in order of how load-bearing each is to this
specific rebuild:

1. a functional core with effects pushed to the edge (§7–§9) — this is the
   direct fix for the failure mode recorded in `PROPOSAL.md` §3.4 that
   destroyed 8,023 files;
2. explicit, versioned contracts at every boundary a client or an agent can
   observe (§4, §5, §30);
3. a document model that makes invalid structures unrepresentable rather than
   merely rejected at validation time (§10, §11);
4. compensations for the one place this project trades away static
   guarantees on principle — the Python core (§3);
5. testing that treats the architecture itself as the thing under test, not
   only the code inside it (§14–§27).

Abstraction is adopted here when it buys a verification boundary: something
that can be substituted, tested in isolation, observed, or made to fail on
command. Abstraction adopted for its own sake — a port with one real adapter
and no plausible second one, a class hierarchy with no test that exploits it —
is rejected on sight. §6 gives the exact test.

---

## 2. Separation of core and clients

The source guidelines separate a GUI from an application core. UBEATS v2 has
no GUI. Its clients are the CLI (`ubeats`), automated agents driving that same
CLI, git hooks, and text editors opening authored files directly. The
underlying concern is identical to the source's: **authoritative behavior
belongs in one place, and every way of reaching the system goes through the
same door.**

```text
┌──────────────────────────────────────────────────────┐
│  clients:  CLI  ·  agents  ·  git hooks  ·  editors   │
│                                                        │
│  presentation of results                              │
│  invocation of commands                               │
│  (editors: authoring of prose only, see §5)           │
└───────────────────────┬────────────────────────────────┘
                        │ structured commands / structured results
                        ▼
┌──────────────────────────────────────────────────────┐
│                imperative shell + core                │
│  domain semantics · validation · lifecycle            │
│  plan construction · persistence control · rendering  │
└──────────────────────────────────────────────────────┘
```

No client — not the CLI's own presentation layer, not an agent, not a git
hook — is permitted to be an alternative authority on domain semantics.
Concretely, **[BINDING]** no client may:

- reimplement outline validation, lifecycle transition rules, or
  bilingual-completeness checks to decide locally whether an operation is
  allowed;
- write to `outline.toml`, or anything under `generated/`, as a substitute
  for issuing a command — these are the command-managed classes (§5). Hand
  authoring `document.toml` or `terminology.toml` directly is a different,
  legitimate class of file access, addressed below and in §5, not an
  exception to this bullet;
- silently repair a malformed request before sending it — a client that
  detects a plausible fix must surface it as a suggestion in the rejected
  result (the `suggestion` field of `InvalidCommand`, §12), never apply it
  unasked.

A text editor opening `prose/**/*.typ`, `document.toml`, or `terminology.toml`
is not violating this rule: these are the project's **authored** file
classes (§5) — content whose authoritative form *is* what a human typed, not
merely tolerated for a "trivial scalar correction." An editor is never
authoritative over whether the result is *valid*, though: only the next
`ubeats verify` or command invocation is, exactly as §5's authored-file rule
states.

Presentation-level convenience (a shell completion suggesting valid section
IDs, an editor extension warning about an obviously malformed date) may
duplicate a core rule for responsiveness, exactly as the source guidelines
permit for GUI-level validation. **[ADVISORY]** Such duplication must be
demonstrably harmless if wrong — it must never be the only check performed
before a mutation reaches the core.

---

## 3. The Python core: the one deliberate departure

### 3.1 The tension, stated plainly

The source guidelines' §3 is unambiguous: long-lived application cores should
be compiled binaries, and dynamic languages should not become the
implementation language for a core merely because early development is
convenient. `PROPOSAL.md` §4.3 mandates the opposite for this project: **Python
is the only scripting language**, and that mandate applies to `ubeats/domain/`
— the functional core — exactly as much as it applies to the CLI shell around
it.

This doctrine does not resolve that tension by redefining "core" until it
disappears, and does not resolve it by quietly dropping the source's concern.
It states the trade honestly and prescribes what is owed in return.

### 3.2 What a compiled core would have bought, and does not exist here

A statically compiled core with a sum-type-capable type system would give,
essentially for free:

- **exhaustiveness at build time** — a compiler that refuses to build a
  program with an unhandled variant of a closed enumeration (an unhandled
  `DomainError` kind, an unhandled `LifecycleStage`);
- **a single self-contained deployable artifact**, insulated from drift in
  whatever interpreter or package set happens to be installed on a given
  machine;
- **a whole class of "this ran, but on the wrong kind of value" defects made
  unrepresentable**, not merely tested against;
- **failure moved earlier** — a mismatched type is a build failure, not a
  runtime `AttributeError` three function calls downstream of the mistake.

Python's runtime does not provide any of these on its own. `mypy` performs
exhaustiveness checking, but it is best-effort and can be defeated by `Any`
leaking across a boundary, by a missing or wrong third-party type stub, or by
`# type: ignore`. A frozen dataclass prevents reassignment but not, by itself,
constructing one with a value that violates a domain invariant. None of this
is fixed by writing "idiomatic" Python; it requires deliberate, enforced
discipline, which is what the remainder of this section prescribes.

### 3.3 What is not lost

Two of the source's underlying motivations survive the substitution intact,
because they are properties of *architecture*, not of the compiler:

- process boundary and predictable deployment — the CLI is still one
  installed entry point running in one process per invocation, exactly as a
  compiled binary would be (§10.1);
- controlled runtime behavior and testability of the exact delivered
  artifact — §39 (test the delivered boundaries) applies to the installed
  `ubeats` executable regardless of what language built it.

### 3.4 The binding compensations

These seven rules are not aspirations. Each has a stated, mechanical
enforcement in §46, and each exists specifically to recover — not fully, see
§3.5 — a property the compiled-core alternative would have given for free.

1. **[BINDING] `mypy --strict` on the entire package, a CI build gate.**
   `ubeats/domain/` is additionally forbidden from using `Any` anywhere in its
   signatures or bodies, including through `# type: ignore` on a line that
   would otherwise widen a type to `Any`. This is the closest available
   substitute for a compiler that refuses to build.

2. **[BINDING] Domain types are immutable.** Every type in `ubeats/domain/`
   that represents a value (as opposed to a Protocol or a pure function) is
   `@dataclass(frozen=True, slots=True)`. Collections in domain signatures are
   `tuple`, not `list`; `Mapping`, not `dict`. This is what makes "every
   operation returns a new `Document`" (`PROPOSAL.md` §7.1) actually true
   rather than a comment nobody enforces.

3. **[BINDING] Distinct types for distinct concepts.** `SectionId`,
   `DocumentVersion`, `SchemaVersion`, `ModelDigest` and every comparable
   identifier are, at minimum, `NewType` aliases — but an identifier that
   carries a well-formedness rule a caller could violate (`SectionId`,
   `Slug`, `DocumentId`; `ARCHITECTURE.md` §2.1) MUST be a **frozen wrapper
   dataclass with a `parse()` constructor returning `Result[T, DomainError]`**,
   never a bare `NewType`. A `NewType` alias has no validating constructor —
   `SectionId(raw)` type-checks under `mypy --strict` even when `raw` is
   malformed, which defeats the entire point of this rule. `LocaleTag` is
   covered by rule 4 below (it is a closed set, not an open identifier
   space): it is a `StrEnum`, never a `Literal["en", "ja"]`, because a
   `Literal` has no validating constructor either. In all cases: never a bare
   `str` or `int` passed positionally. A function signature that takes three
   `str` parameters where one is a section identifier, one is a title, and
   one is a locale tag is a defect: nothing stops a caller from passing them
   in the wrong order, and nothing did in v1.

4. **[BINDING] Closed sets are enumerations.** `LifecycleStage`,
   `DomainError` kind, `FileEffect`/`ExternalEffect` variant (ADR-0002),
   document class, `LocaleTag`, and every other value drawn from a known
   finite set is a Python `Enum`/`StrEnum` (or a tagged union of frozen
   dataclasses where the variants carry different data), never a free string
   compared with `==`. A new variant must be added at the definition site,
   where every `match`/`if` chain that is missing a case is what
   `mypy --strict`'s exhaustiveness checking (rule 1) is there to catch.

5. **[BINDING] Validating constructors at every boundary.** Any value
   entering `ubeats/domain/` from a TOML file, a CLI argument, an environment
   variable, or an adapter's return value is constructed through a function
   that returns `Result[T, DomainError]` (§12) — never `cast()`, never a bare
   constructor call trusted to have been given good data. A domain type's
   `__init__` may assume its invariants hold; the *only* place invariants are
   checked is the validating constructor, and every external value passes
   through exactly one such constructor before it is treated as that type
   anywhere else.

6. **[BINDING] A single hash-locked environment.** Dependencies are pinned by
   content hash in a lockfile (not merely by version range); `ubeats doctor`
   verifies the installed environment matches the lock before running any
   other command; the distribution mechanism (the "distribution mechanism"
   row of `PROPOSAL.md` §16's open-question register) must, whichever way it
   is decided, ship that same lock. This is the substitute for "a single
   self-contained artifact insulated from runtime environment drift."

7. **[BINDING] Mutation testing on domain rules as a substitute for
   exhaustiveness.** `ubeats/domain/rules/`, `ubeats/domain/lifecycle/`, and
   `ubeats/domain/planning/` carry a mandatory mutation-testing gate (detailed
   in §23). Where a compiler would refuse to build code with an unhandled
   case, mutation testing is the mechanism that asks the weaker but still
   checkable question: *if this logic were subtly wrong, would a test
   fail?*

This list is closed. A contributor who believes an eighth compensation is
needed opens an ADR; a contributor who believes one of the seven is
unaffordable for a given change does not quietly skip it — they open an ADR
arguing for a doctrine amendment. Neither happens inside a routine pull
request.

### 3.5 What is honestly not recovered

The compensations above reduce risk; they do not eliminate the underlying
gap. The specific residual risk, matching `PROPOSAL.md`'s **FM-24**, is: a
value can still reach a domain function through a path that is technically
type-correct at every individual step — a `**kwargs` forwarder, an
`isinstance` narrowing that a future refactor quietly weakens, a third-party
stub that is wrong about a boundary type — and execute successfully with a
semantically incorrect argument, discovered only at runtime, possibly after
committing a plan.

This is accepted, not solved. The seven compensations are defense in depth
against it: the validating constructor stops most malformed values before
they are a domain type at all; frozen types stop most accidental mutation;
mutation testing stops most logic errors that a wrong-but-typed value would
have to survive. No claim is made that this equals what a sum-type-capable
compiled language would guarantee. §16 (risk R3) tracks this as an accepted,
monitored risk, not a closed one.

---

## 4. Contracts are first-class engineering artifacts

Every boundary a client, an agent, or another program can observe is governed
by an explicit, written contract — not by whatever the current implementation
happens to do. This applies to the CLI's JSON envelope (§10.2), to every port
in `ubeats/ports/` (§8), and to the persisted model file formats (§5).

**[BINDING]** A contract for a command or a port must specify, wherever
applicable: accepted inputs and their validation rules; the shape of a
successful result; every `DomainError` and `InfrastructureError` variant it
can produce and under what condition; whether repeating the same request is
safe (idempotency); ordering or sequencing assumptions; concurrency
assumptions (§41); versioning and compatibility behavior (§38); and, where
relevant, atomicity behavior (§29).

**[BINDING]** The implementation is not the contract. A consumer — including
another module inside `ubeats/` — must not depend on a property that is true
of the current adapter but not written into its contract: filesystem write
ordering not documented as guaranteed, a TOML key ordering not part of the
published schema, an error message string matched by substring instead of a
`DomainError.kind` value. Enforcement: contract tests (§17) are written
against the *published* contract, not against a snapshot of current adapter
behavior; a contract test that would fail against a hypothetical
second-conformant adapter, but does not, is itself a defect.

For example, `FileSystemPort` specifies exactly this vocabulary (`ARCHITECTURE.md`
§4.1) and no other:

```text
read_text(p) -> Result[str, InfrastructureError]
read_bytes(p) -> Result[bytes, InfrastructureError]
write_atomic(p, data) -> Result[None, InfrastructureError]
move(src, dst) -> Result[None, InfrastructureError]
delete(p) -> Result[None, InfrastructureError]
list_tree(p) -> Result[tuple[RelPath, ...], InfrastructureError]
probe(p) -> Result[PathFacts, InfrastructureError]
```

a consumer must not additionally rely on the real adapter's specific
directory-entry ordering, on write timing, or on any caching behavior not
named in the port's contract documentation under `ubeats/ports/`.

---

## 5. Public commands, private representations

The source guidelines separate a private SQLite schema from a public
application API. UBEATS v2 has no database, but the same separation is even
more consequential here, because it is the direct fix for the root cause
recorded in `PROPOSAL.md` §3.1 — a model that lived only inside the
compiler's own language.

```text
document.toml, terminology.toml   AUTHORED (see class 2 below)
outline.toml                       COMMAND-MANAGED (see class 1 below)
generated/**  (rendered Typst source)   COMMAND-MANAGED, NEVER HAND-EDITED
prose/**/*.typ                          AUTHORED — like class 2, prose-shaped
ubeats CLI command surface              PUBLIC
```

This resolves an earlier inconsistency between this document and
`PROPOSAL.md` §10.4 (which tells an author to "fill `document.toml`" as an
ordinary authoring step): the two are not in tension once `document.toml`'s
own file class is stated precisely, below.

**[BINDING]** Clients interact with **command-managed** files through
commands — `ubeats section move`, `ubeats section rename`, `ubeats release
bump` — not by constructing TOML by hand or scripting edits to it. Prefer

```text
ubeats section move scope --to background
ubeats section rename scope --title-en "Scope" --title-ja "スコープ"
ubeats release bump --minor
```

over a script or an agent editing `outline.toml`'s array order directly, for
exactly the reason the source guidelines give for preferring
`CreateRequirement` over `InsertRow`: the command passes through validation,
produces a plan, and is answerable to the same contract every other client
uses. A hand-edit bypasses all three. `ubeats release bump` additionally
writes `document.toml`'s `version` and history fields — this is a command
writing an authored file on the author's behalf, not a contradiction of
class 2 below; the author remains free to make the same edit by hand.

**Three classes of file, three different rules, stated once here because
they are easy to conflate:**

1. **Command-managed files (`outline.toml`, `generated/**`).** **[BINDING]**
   MUST NOT be hand-edited as a substitute for issuing a command.
   `outline.toml` carries exactly the invariants (`ARCHITECTURE.md` §2.3)
   that a hand-edit could silently violate — a duplicate `SectionId`, a
   dangling `BodyRef`, a cycle — and only the command path constructs a
   plan, previews it, and validates it before commit; `generated/**` is
   additionally the direct output of a pure function
   (`render(doc, facts)`), so a hand-edit is, by definition, silently
   inconsistent with the model the moment it happens (§44 gives the full
   rule set and its enforcement for `generated/**` specifically).

2. **Authored data files (`document.toml`, `terminology.toml`).**
   **[BINDING]** These are a genuine authoring surface, not a "model file"
   merely tolerated for scalar corrections — per `PROPOSAL.md` §7.4 they are
   deliberately TOML, human-editable, precisely so an author can "fill
   `document.toml`" (`PROPOSAL.md` §10.4) or add a glossary entry directly,
   the same way they edit prose. Nothing about editing them is a second,
   weaker path: the *next* load of the model (by any command, including a
   plain `ubeats verify`) re-runs full validation, and any invariant
   violation surfaces as `InvariantViolation` or `CorruptModel` exactly as
   if a defective adapter had produced it — the same way a `git commit
   --amend` defers correctness to the next `git status`. **[ADVISORY]**
   Where a change to one of these files is genuinely cross-field or could
   interact with `Lifecycle` state (a version bump, for instance), prefer
   the corresponding command (`ubeats release bump`) over a hand-edit, both
   because the command constructs a plan an author can review with
   `--dry-run` and because it keeps the file's history attributable to a
   specific, named operation — but a hand-edit is never rejected merely for
   being a hand-edit, only for the invariant violations it happens to cause.

3. **Authored prose (`prose/**/*.typ`).** **[BINDING]** The same authored
   treatment as class 2, prose-shaped. Prose content is authoritative
   exactly as the human author wrote it. No command generates, rewrites, or
   "corrects" prose content. The one thing a command *does* own inside a
   prose file is the single generated import line described in
   `PROPOSAL.md` §7.3 — **ADR-0003**, to be written in P0 — `ubeats verify`
   checks that line's presence and correctness without touching anything
   else in the file.

This mirrors the source guidelines' underlying point exactly: internal
representation (TOML layout, generated Typst structure, `SectionId`
encoding) may evolve without forcing every client to change, *because*
clients were never depending on it — they were depending on the command
surface. The reverse guarantee also holds: the command surface changes only
under the versioning discipline of §38, precisely because it, and not the
file layout, is the public contract.

---

## 6. Hexagonal modular architecture

`ubeats/domain/` is the center. External systems are reached exclusively
through ports defined by the core; adapters implement those ports.

```text
                    ┌──────────────────┐
                    │  ubeats/domain/  │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
        FileSystemPort  TypstPort   PdfInspectorPort  ... (see PROPOSAL.md §8)
              │              │              │
              ▼              ▼              ▼
        real/fake/faulty adapters, one triad per port
```

**[BINDING]** Dependencies point inward: `ubeats/domain/` imports nothing
from `ubeats/adapters/`, `ubeats/shell/`, or `ubeats/app/`. This is checked
mechanically, not by review (§46, fitness test 1).

**[BINDING]** A port is justified — and may be merged — only when it buys at
least one of: replacing the implementation without touching the core;
independently testing the core against a fake; a named behavioral contract
(§4); controlling an effect (§8); fault injection (§18, §22); observing an
interaction; isolating the core from an unstable external technology; or
supporting more than one real adapter. **Every port's ADR (template in
Appendix A) must name which of these it claims.** A pull request introducing
a port whose ADR cannot name one of these justifications is a request to wrap
a standard-library call for its own sake, and is rejected — the current port
inventory (`PROPOSAL.md` §8: `FileSystemPort`, `TypstPort`,
`PdfInspectorPort`, `VcsPort`, `ClockPort`, `TranslationPort`,
`ArtifactSourcePort`, `EnvironmentPort`, and `ProseScannerPort` — nine ports,
ADR-0001) is the expected shape of the system, not a floor to be added to
casually.

**[BINDING]** JSON/TOML serialization, string formatting, pure path
*computation* (joining, slugifying — as opposed to path *access*, which is a
port), and hashing are explicitly **not** ports. They are pure functions
living in `ubeats/domain/` or a shared pure utility module.

**[BINDING] Carve-out: why `ProseScannerPort` is a port and not "just
serialization."** A lexical scanner over Typst source looks, on the surface,
like the kind of pure parsing function the previous paragraph excludes from
port status — and ADR-0001 §"Alternatives rejected" confirms it genuinely
*could* live in `domain/` as a pure `str -> ProseFacts` function without
violating the functional-core rule (§7). It is placed behind a port anyway,
on grounds independent of purity: **containment of external change.** What
will change over the system's life is not the scanner's logic but *Typst's
surface syntax* — new authoring macros, new construct forms — and the
architecture's purpose is to keep that external instability out of the core,
exactly as `TypstPort` keeps compiler-version drift out of the core. JSON/TOML
serialization and path computation earn their carve-out because their
*format* is a project-owned constant, not an externally evolving surface;
`ProseScannerPort` fails that test on purpose, because Typst's grammar is not
a project-owned constant. Purity was never the only criterion for port
status; containment of external change is the other, and it is what decides
this case (ADR-0001).

---

## 7. Functional core, imperative shell — and the placement test

`ubeats/domain/` takes values and returns values. It never touches a
filesystem, a clock, a subprocess, a network socket, or process/environment
state. The conceptual shape of every domain operation is:

```text
Document (current model)
    +
Command
    │
    ▼
domain logic (pure)
    │
    ▼
Result[Plan, DomainError]      — for mutating operations
RenderedTree                   — for render(doc, facts); TOTAL, never a Result
```

`render` is deliberately not in the `Result`-returning family above it: it is
total, by construction (§26, `TESTING.md` binding property 6), so wrapping
its return in `Result` would imply a failure mode that does not exist. Any
input that could make rendering impossible is caught earlier, by a
validating constructor or a gate reading `ProseFacts` (ADR-0001) — never
inside `render` itself.

The imperative shell (`ubeats/app/`, `ubeats/shell/`) performs every effect:

```text
parse CLI arguments
    ↓
load Document from disk (FileSystemPort)
    ↓
invoke domain: plan(model, command) -> Result[Plan, DomainError]
    ↓
preflight the Plan's file_effects + stage + commit (FileSystemPort, journal)
    ↓
if external_effects: run them in order (irreversible; confirmed or
--allow-irreversible; ADR-0002)
    ↓
present the Result (JSON envelope or human text)
```

### 7.1 The placement test

Before writing a function, ask: **does this function need to know what time
it is, what is on disk, or what another program says?**

- **No** → it belongs in `ubeats/domain/`. It is a pure function of its
  arguments.
- **Yes, and that is its whole job** → it belongs in `ubeats/adapters/`,
  behind a port.
- **Yes, and it sequences one or more of the above** → it belongs in
  `ubeats/app/` or `ubeats/shell/`, and it MUST NOT contain a business rule
  (an invariant check, a validation decision, a rendering choice) that could
  instead live in `ubeats/domain/`.

**[BINDING]** Applying this test is not optional for new code; it is checked
in review and, for the "no I/O in domain" half, mechanically (§46, fitness
test 2).

This buys, concretely, for this project: `outline` algebra, lifecycle
transitions, publication-gate evaluation, i18n catalog resolution, and
`render(doc, facts) -> RenderedTree` are all testable without a compiler, a
filesystem, or a clock — which is the direct fix for `PROPOSAL.md` §3.1's
13-minute, compiler-dependent test suite. The domain unit suite's budget
(`TESTING.md` §1.1; summarized in `PROPOSAL.md` §12.1) is under ten
seconds precisely because nothing in it can be slow.

Side effects are not forbidden; §9 and §29 describe exactly how and where
they are concentrated and controlled.

---

## 8. Make effects explicit

**[BINDING]** A domain function's signature must not hide an external
dependency behind convenience. Effects that must be explicit parameters
(never ambient reads) anywhere they influence domain logic include: the
current time (`ClockPort`, injected as a value — e.g. `evaluate_lifecycle(now,
document)`, never `datetime.now()` called inside `ubeats/domain/`);
filesystem contents; subprocess results (Typst compilation, git state); PDF
inspection results; translation-memory state; randomness; and generated
identifiers, wherever they affect observable behavior (`SectionId`
generation, for instance, must be either deterministic from inputs or
supplied by the caller — never a bare `uuid4()` call buried inside a domain
constructor).

This is the same rule as §7's placement test applied at the level of an
individual function signature rather than a module boundary, and it is what
makes `plan()` reproducible: `PROPOSAL.md` §12.3's binding property "`plan()`
is deterministic: same model + same command ⇒ identical plan" is only
achievable if every effect the plan construction could depend on was passed
in as a value.

---

## 9. Commands over raw mutation — the plan/apply model

Domain state changes are represented as explicit commands (`section.move`,
`release.bump`, `translate.refresh` — the full verb inventory is
`PROPOSAL.md` §10.1), never as ad hoc field mutation. A command expresses
intent; the core decides whether that intent is valid and, if so, produces a
complete description of the resulting effects before anything is applied.

```text
command
    ↓
core: validate against current Document
    │
    ├── DomainError ───────────────────────► nothing touched, ever
    │
    └── Plan { model_before digest, model_after, file_effects, external_effects }
              │           (each effect carries its own `reason` — no separate
              │            `rationale` field, ADR-0002)
    shell: preflight the WHOLE plan's file_effects (existence, writability,
              │            digest match)
              │
              ├── Refusal ─────────────────► nothing touched
              │
              └── stage → commit (atomic renames) → journal discarded
                            │
                            ├── failure at any step → rollback from journal
                            │
                            └── if external_effects: run in order — irreversible,
                                confirmed or --allow-irreversible; partial
                                completion reported, never hidden (ADR-0002)
```

This is the direct, deliberate answer to `PROPOSAL.md` §3.4's incident: a
function that computed *and* performed a destructive change in the same pass
destroyed 8,023 files across three independently discovered fault
conditions, and reported success while doing it. A plan/apply split makes
that specific class of defect structurally impossible, because there is no
code path in which "compute what to delete" and "delete it" are the same
step.

**[BINDING]** Every command that mutates persisted state MUST be implemented
as `plan(model, command) -> Result[Plan, DomainError]` in `ubeats/domain/`,
followed by `apply(plan) -> Result[Applied, ApplyFailure]` in
`ubeats/shell/exec/`. A command implementation that performs a write inside
the function that also decides *whether* to write is a defect, full stop,
regardless of how small the write is.

**[BINDING]** `--dry-run` on any consequential command is not a separate code
path to maintain — it is the pipeline stopping after `Plan` is produced and
printing it. If a command's dry-run output can diverge from what apply
actually does, the command is not implemented per this section (§46, fitness
test — every consequential command's CLI wiring calls the shared
plan-then-optionally-apply path).

**[ADVISORY]** For a command whose plan can be large or consequential
(bulk section reorganization, a release gate), consider whether each
effect's `reason` (there is no separate `rationale` field — ADR-0002 rule 6
puts the explanation on the effect itself, supplied by the planner) should
be one full human-readable sentence rather than a terse label — this is
what makes `--dry-run` output actually reviewable by a person, not merely
machine-parseable.

---

## 10. Prefer explicit state transitions

The document's lifecycle (`PROPOSAL.md` §7.1, `lifecycle: Lifecycle`) is not
a free-form string. It is a closed `LifecycleStage` enumeration with an
explicit transition table, matching the existing UBEATS v1 tag progression
(`v0.1-init` → `vX.Y-draft` → `vX.Y-review.k` → `vX.Y-prepublish` → `vX.Y`)
but now enforced as *domain logic*, not as a pre-commit hook parsing tag
strings after the fact.

```text
Draft ──► Review.k ──► Prepublish ──► Published
```

**[BINDING]** An illegal transition (e.g. removing the draft marker below
version 1.0, or bumping the version without an accompanying history row) is
rejected by `ubeats/domain/lifecycle/` as `IllegalTransition`, before any
file is touched — not discovered later by a pre-commit hook shelling out to
inspect the working tree. The pre-commit hook, where one still exists for
git-specific reasons, becomes a thin caller of `ubeats release gate`,
consistent with §2.

**[BINDING]** Where a lifecycle rule exists, it must be represented in the
type system such that an invalid combination is either unrepresentable (a
`Published` document type that has no `draft: bool` field to accidentally
leave `true`) or explicitly checked by a validating constructor (§3.4, rule
5) — never left as an unconstrained field trusted to be consistent by
convention.

---

## 11. Strong typing as a design tool

Static types here exist to communicate domain structure, not merely to
satisfy `mypy`. This section restates and cross-references §3.4's binding
rules 2–4 in their design-intent form:

**[BINDING]** `SectionId`, `LocaleTag`, `DocumentVersion`, `SchemaVersion`,
`ModelDigest`, `Slug`, `DocumentId` are distinct types, not interchangeable
`str`. A function that could accept a `Slug` where a `SectionId` was meant,
and compile/type-check cleanly while doing so, is a defect in the type
design, not merely a hypothetical risk — this is precisely the "four
concerns conflated into one string" defect class `PROPOSAL.md` §7.2
documents for v1's filename-based ordering, generalized to every other
identifier in the system. As §3.4 rule 3 details: `SectionId`, `Slug` and
`DocumentId` carry well-formedness rules and are therefore frozen wrapper
dataclasses with a `parse()` constructor, never `NewType` — a `NewType` has
no constructor and validates nothing, so it does not actually stop the
"wrong kind of value" defect this section exists to prevent.

**[BINDING]** A domain concept with a known closed set of values — document
class, `LifecycleStage`, `DomainError` kind, `FileEffect`/`ExternalEffect`
variant, `LocaleTag` (`en` / `ja`, nothing else) — is an enumeration
(`StrEnum` where the values are also strings, as for `LocaleTag`) or a
tagged union, never a string compared with `==` scattered across the
codebase, and never a `Literal` (which, like `NewType`, has no validating
constructor).

**[ADVISORY]** Type sophistication must remain proportional to benefit. A
generic, higher-kinded abstraction that makes `ubeats/domain/outline/`
harder for a newcomer to read, in service of a substitution that is never
actually exercised, is over-engineering exactly as much here as it would be
anywhere else. If a reviewer cannot explain what invalid state a given type
construction prevents, within one sentence, reconsider it.

---

## 12. Explicit error semantics

Errors are part of the contract (§4), not an afterthought. `ubeats/domain/`
never raises an exception for an expected condition; it returns
`Result[T, DomainError]`. The taxonomy (from `PROPOSAL.md` §7.5) is closed:

```text
DomainError
├── NotFound(kind, id)
├── InvalidCommand(field, reason, suggestion)
├── InvariantViolation(invariant, detail)
├── Conflict(what, existing)
├── IllegalTransition(from_state, to_state)
├── UnsupportedSchema(found, supported)
└── CorruptModel(where, detail)

InfrastructureError                                  # produced only by adapters
├── PortFailure(port, cause)
├── Timeout(port, budget)
├── ContractViolation(port, expectation, observed)    # a non-conformant adapter — a bug
└── ExternalToolFailure(tool, exit_code, diagnostics)
```

**[BINDING]** `ubeats/domain/` may only ever produce a `DomainError`. Only
`ubeats/adapters/` may produce an `InfrastructureError`. If a domain function
is tempted to return `PortFailure`, the effect that could fail does not
belong in the domain function (§7, §8).

**[BINDING]** A new failure category is added to the enumeration at its
definition site, not represented as a string reason inside an existing
generic variant — this is what lets `mypy --strict`'s exhaustiveness checking
(§3.4, rule 1) catch a missing case at every `match` over `DomainError`.

Example of the distinction this taxonomy exists to preserve: rejecting
`ubeats release gate` because the document is still in `Draft` at version 1.0
(`IllegalTransition`) is not the same *kind* of event as `ubeats build`
failing because the disk is full (`PortFailure` wrapping an
`InfrastructureError` from `FileSystemPort`). A client, a log, and a test
suite must all be able to tell these apart without string-matching a message.

---

## 13. Expected failure versus contract violation

**[BINDING]** `ContractViolation` (§12) is reserved specifically for the case
where an adapter returns something its own port contract (§4) forbids — for
example, `FileSystemPort.read_text` after a successful `write_atomic` to the
same path returning `NotFound`. This is not equivalent to a legitimate,
contract-conformant failure such as `PortFailure(FileSystemPort, DiskFull)`,
and the two must never be collapsed into the same handling path.

Both are tested, deliberately and separately (§18, §19): the faulty adapter
family must be able to produce *conformant* failures (a real disk-full
condition, correctly reported) and, distinctly, *non-conformant* behavior (a
`FileSystemPort` fake that lies about having written something) — because
the latter is how a boundary's undocumented assumptions are found before a
real, buggy adapter finds them in production.

---

## 14. Testing is an architectural activity

`doctrine/TESTING.md` is the binding testing doctrine in full; this document
states the architectural consequence: **a component that cannot be exercised
independently is an architecture defect, to be fixed by changing the
boundary, not by writing a harder test.** If testing `ubeats/domain/outline/`
in isolation turns out to require a filesystem, that is evidence a port was
skipped, not evidence that outline logic is inherently hard to test.

**[BINDING]** Testing is not primarily a demonstration that nominal examples
work. Every domain rule and every port contract must be exercised against
both accepted and rejected inputs (§15), and every port must be exercised
against deliberately non-conformant behavior (§18–§19), not merely against
its real adapter's current, correct behavior.

---

## 15. Unit tests

**[BINDING]** `ubeats/domain/` must be substantially testable with no
database, no network, no filesystem, no OS state, no wall clock, and no real
subprocess — this is the whole point of §7. The unit suite's time budget
(under ten seconds, `PROPOSAL.md` §12.1) is itself a binding constraint,
enforced mechanically (§46, fitness test 7): a suite that needs any of the
above to run at all would blow that budget immediately, so the budget is a
proxy for the architectural property, not merely a performance target.

**[BINDING]** Unit tests assert domain invariants (*"a plan for a rejected
command never contains an effect"*), not merely mirror the implementation's
internal function calls. A test that would still pass after `plan()`'s
internal decomposition changed, provided the observable contract held, is
correctly scoped; a test that breaks on refactoring alone is testing
implementation, not behavior.

---

## 16. Integration tests

**[BINDING]** Integration tests exercise real technology: `ubeats/domain/` ↔
real Typst compilation, real PDF inspection of a real build, real git
operations against a real repository, the model round-tripping through real
TOML parsing. They are not replaceable by mocked unit tests, and mocked unit
tests are not replaceable by them — a fake `TypstPort` verifies the core's
logic against a controlled model of the compiler; an integration test
verifies that the real compiler actually behaves the way the fake assumes.
Both are required; §17 is what keeps them from silently diverging.

---

## 17. Port contract tests

**[BINDING]** Every port in `ubeats/ports/` has one contract test suite,
written against the published contract (§4), and that same suite runs
against every adapter implementing the port: **real, fake, and
faulty-in-healthy-mode** (the faulty adapter with the module-level `NONE`
schedule constant armed — `TESTING.md` §2.1, §3.2 — which must behave exactly like a conformant
adapter before it is trusted to inject faults anywhere else). The
healthy-mode qualifier is load-bearing, not decorative: a faulty adapter
running a schedule is expected to misbehave (§18–§19), so it is only the
unarmed configuration that this suite's pass/fail signal covers.

```text
FileSystemPortContract
        │
        ├── RealFileSystemAdapter
        ├── InMemoryFileSystemAdapter   (fake)
        └── FaultyFileSystemAdapter     (schedule-driven, §22)
```

This is not three separate test files that happen to look similar; it is one
parametrized suite. **[BINDING]** If the fake and the real adapter can
diverge in observable behavior without any test failing, the fake is
worthless for every test elsewhere in the suite that relies on it standing in
for the real thing — this is `PROPOSAL.md`'s **FM-02**, one of its
highest-severity failure modes, and it is the single most important reason
this rule is binding rather than advisory.

---

## 18. Deliberately broken components — the faulty adapter family

**[BINDING]** Every port — unconditionally, with no "meaningful failure
modes" qualifier — has, in addition to its real and fake adapters, a
**faulty** adapter, driven by a fault schedule (§22), living in
`ubeats/adapters/faulty/`. This is deliberately unconditional: a port
judged to have no meaningful failure mode today is exactly the port whose
failure mode gets discovered in production, and fitness test 3 (§46, "every
`Protocol` under `ports/` has at least one real, one fake, and one faulty
implementation") enforces the same thing mechanically — a qualifier here
that the fitness test does not also encode would make the two disagree.
Representative examples for this project's ports:

```text
FailNthWriteFileSystem      DelayedTypstCompile
ReadOnlyFileSystem          CorruptQueryResultTypst
StaleReadFileSystem         MalformedPdfMetadataInspector
DuplicatingVcsAdapter       FrozenClock / JumpingClock
InterruptedRenameFileSystem TranslationMemoryUnavailable
```

**[BINDING]** These are not test doubles used once and discarded; they are
reusable instruments answering one recurring question for every consumer of
that port: *what does the rest of the system do when this component fails or
becomes untrustworthy?* Every command whose plan touches `FileSystemPort`
with more than one effect must be tested against at least the interruption
variants in §29's table using this family.

---

## 19. Fault propagation and containment

**[BINDING]** For every pairing of a faulty adapter feeding a healthy
consumer, a test asserts one of: the consumer detects the fault and returns a
distinguishable error; the consumer rejects the tainted input outright; the
consumer enters a safe, inspectable state; or the consumer degrades correctly
where partial operation is legitimate. **A consumer silently propagating
corrupted or stale data to the next component, or continuing as if nothing
happened, is a defect, discovered by exactly this kind of test — not by
review, because this class of bug is invisible to review.**

The specific case this project has already lost time to: `PROPOSAL.md` §3.6
records a "goldens unchanged" check that silently resolved against the wrong
git repository and reported success on empty output — a healthy-looking
component (the CI script) consuming a faulty one (an uninitialized
submodule) without detecting it. §21's fault-model category for this is
*omission*, and §46's anti-vacuity rule exists specifically because of it.

---

## 20. Architectural mutation testing

**[BINDING]** In addition to code-level mutation testing (§23), boundary
behavior is mutated deliberately, using the faulty adapter family (§18) and
fault schedules (§22):

```text
valid FileSystemPort.read_text result ──► stale-but-valid result
one Typst compile invocation          ──► duplicated invocation
atomic rename reported as complete    ──► partial apparent completion
```

The purpose is identical to code-level mutation testing: find the assumption
that was never written into a contract (§4) and is currently protected only
by every adapter, real and fake, happening to agree on undocumented behavior.
**[ADVISORY]** New ports should have at least one architectural mutation
scenario considered at ADR time (Appendix A, "fault model" field), even if
the corresponding faulty adapter is implemented later.

---

## 21. Fault models

Every port with a real, external-facing adapter has an explicit fault model
covering the categories relevant to it, drawn from:

- **explicit failure** — `Err(DiskFull)`, a compiler exiting non-zero with
  diagnostics;
- **omission** — an expected write never happens; a hook never fires;
- **timing failure** — Typst compilation stalls past a budget;
- **value corruption** — `PdfInspectorPort` returns metadata for the wrong
  PDF revision;
- **state inconsistency** — a path reported to exist by `list_tree()` returns
  `NotFound` from `read_text()`/`read_bytes()`;
- **stale state** — a cached translation-memory read after the sidecar
  changed;
- **duplication** — a git hook invoked twice for one commit;
- **reordering** — a multi-effect plan's renames observed out of order by a
  concurrent reader;
- **partial effect** — a crash mid-commit leaves some, not all, staged files
  renamed (§29);
- **protocol violation** — a Typst subprocess emits diagnostics in an
  unexpected schema version.

**[BINDING]** `FileSystemPort` and `TypstPort` — the two ports on the
project's critical path for data loss and for release correctness — must
have every applicable category above represented by at least one test, not
merely the categories that were easy to think of first.

---

## 22. Fault schedules as data

**[BINDING]** Faults injected by `ubeats/adapters/faulty/` are configured as
data, not hard-coded per mock class. `TESTING.md` §3.2's structured form —
`FaultSchedule(rules=(FaultRule(port=..., operation=..., occurrence=...,
fault=...), ...))` — is canonical; this document does not define a second,
keyword-argument shape (`FaultSchedule(fail_write=3)` and similar were an
earlier, incompatible sketch and are retired). For example, "fail the 3rd
`FileSystemPort.write_atomic` call":

```python
FaultSchedule(rules=(
    FaultRule(port="filesystem", operation="write_atomic", occurrence=(3,),
              fault=ExplicitFailure(error="DiskFull")),
))
```

The same mechanism serves deterministic regression tests, property-based
tests (§26), and fuzzing campaigns (§25). **[BINDING]** A property-based test
or fuzzer that discovers a failing fault schedule must be able to persist
that exact schedule as a new regression test case — a failing run that cannot
be replayed exactly is not an actionable bug report.

---

## 23. Mutation testing

**[BINDING]** Mutation testing runs against `ubeats/domain/rules/`,
`ubeats/domain/lifecycle/`, and `ubeats/domain/planning/`, with a minimum
mutation-score threshold enforced as a CI gate (the specific numeric
threshold is set and revised in `doctrine/TESTING.md`; this document binds
the requirement, not the number). This is §3.4's rule 7, restated as a
testing rule: it is this project's best available substitute for a
compiler's exhaustiveness guarantee over `DomainError` and `LifecycleStage`
handling.

**[BINDING]** A surviving mutant is investigated, not merely tallied. Each
survivor is classified as: a missing test (fix it), dead/redundant code
(remove it), a semantically equivalent mutant (document why and exclude it
explicitly, not silently), or evidence that the decision logic itself is
under-specified (open an issue against the domain rule, not against the
test).

The most valuable target for this technique in this project is exactly the
kind of logic the source guidelines call out: publication-gate evaluation,
outline-invariant checks, and lifecycle-transition validation — dense
boolean decision logic where ordinary line/branch coverage can look complete
while hiding an untested condition interaction.

---

## 24. MC/DC

**[BINDING]** Modified condition/decision coverage is applied to compound
publication-gate and validation decisions — for example, a release gate that
requires `no_placeholders AND no_unresolved_markers AND
bilingual_catalogs_complete AND lifecycle_transition_legal`. Ordinary branch
coverage can be satisfied while one of those four conditions never
independently determines the outcome in any test; MC/DC is the mechanism
that catches it.

**[ADVISORY]** MC/DC complements mutation testing and semantic
(property-based, §26) testing; achieving MC/DC on a decision whose domain
meaning is itself wrong proves nothing. Do not treat MC/DC coverage as a
substitute for a reviewer asking "is this gate actually the right gate."

---

## 25. Fuzzing

**[BINDING]** Every interface that parses externally-influenced or
structured data is a fuzzing target: TOML model files loaded from disk,
migration input from v1 documents (`MIGRATION.md`), the CLI's `--json`
command input where structured, terminology/glossary records, and any
translation-memory sidecar consumed by `TranslationPort`.

**[BINDING]** Fuzzing targets the following properties, not merely the
absence of a crash:

```text
must not raise an unhandled exception
must not write any file when the parsed input is ultimately invalid
must not corrupt an already-persisted, valid Document
must not violate a domain invariant it would otherwise enforce
must return a bounded, structured diagnostic (never hang)
```

**[ADVISORY]** Prefer fuzzing at the level of the parsed, typed
representation (a generated `Document` or `SectionNode` tree) in addition to
raw bytes — this finds domain-logic bugs that byte-level fuzzing of a TOML
parser alone would not reach.

---

## 26. Property-based testing

**[BINDING]** The following properties (already listed as binding in
`PROPOSAL.md` §12.3) are the minimum property suite for the domain core, and
each must have an executing test, not merely be a design aspiration written
in a document:

```text
Applying a rejected command never modifies any file.
plan() is deterministic: same model + same command => identical plan.
Moving a section then moving it back restores the original outline exactly.
Every user-visible string key resolves in BOTH locale catalogs.
Rendering is total: no valid (Document, ProseFacts) pair can make render() raise.
A section's SectionId is preserved across move, rename and reorder.
Interrupting apply() at any file-effect step leaves, before recovery, the
  pre-state, the post-state, or a recoverable hybrid with a journal present;
  after recovery, only the pre-state or the post-state (ADR-0002 scopes this
  to file_effects).
Round-trip: parse(serialize(model)) == model.
```

**[ADVISORY]** New domain features should be accompanied by at least one new
property, phrased as an invariant that should hold across the *whole*
generated input space, not a single hand-picked example. Prefer a property
over ten hand-written examples whenever the property can be stated precisely.

---

## 27. Test real failure modes too

**[BINDING]** Faulty adapters (§18) make faults deterministic and
inexpensive, but they encode this project's *current belief* about how
things fail — they are not proof that belief is complete. In addition to
them, destructive tests against real infrastructure are required at
integration/E2E level, at minimum:

```text
kill the ubeats process mid-apply (after staging, before commit)
corrupt a document.toml file on disk and load it
deny write permission on a target directory and run a command that writes to it
exhaust available disk space during a large build
open two ubeats processes against the same repository concurrently
run against a repository whose schema_version predates the current one
```

**[BINDING]** Where a real-infrastructure test discovers a fault mode the
faulty-adapter family did not model, that fault mode is added to §21's
taxonomy and to the faulty adapter, not merely fixed and forgotten — this is
how the synthetic fault model stays honest against reality over time.

---

## 28. Persistence ownership

**[BINDING]** Command-managed persistence (`outline.toml`, `generated/**`)
has exactly one owner: `ubeats/domain/` via the plan/apply pipeline (§9),
executed by `ubeats/shell/exec/`. No client — CLI, agent, or git hook —
writes to either other than through that pipeline. This is what guarantees
that every *structural* mutation, regardless of which client initiated it,
passes through the same validation, the same plan construction, and the
same recoverable-apply discipline.

```text
CLI ──────┐
Agent ────┼── ubeats commands ──► domain: plan() ──► shell: apply() ──► disk
Git hook ─┘
```

for `outline.toml` and `generated/**` — never

```text
CLI ────┐
Agent ──┼──► outline.toml / generated/**  (direct writes)
Hook ───┘
```

`document.toml` and `terminology.toml` are the **authored** class (§5,
class 2): a human or an editor may write them directly, and `ubeats release
bump` writing `document.toml`'s `version`/history fields is a command doing
the same authoring on the author's behalf, not a second ownership path for
the same data. What every write — command-issued or hand-typed — shares is
that it is re-validated at the *next* load, never trusted on the strength of
its origin.

---

## 29. Transactions and partial failure on a filesystem without transactions

This is the direct retargeting of the source guidelines' persistence-atomicity
concern onto this project's actual substrate — a Windows filesystem, not a
database — and it deserves to be stated with no ambiguity, because assuming
more atomicity than the platform provides is exactly how §3.4's incident
happened.

### 29.1 What Windows actually gives

**There is no cross-file transaction on Windows.** There is no operation that
atomically replaces the contents of two or more files at once, no rollback
journal built into NTFS that the filesystem itself exposes to an application,
nothing equivalent to a database `COMMIT` spanning multiple files. What *is*
available and reliably atomic:

- a single-file rename/replace within the same volume (`MoveFileEx` with
  `MOVEFILE_REPLACE_EXISTING`, which is what a "stage then rename" write
  reduces to at the OS level) — this either fully succeeds or fully fails,
  with no observable half-written intermediate state for *that one file*;
- nothing more. Any guarantee spanning multiple files is something this
  project's own code must build, not something the platform hands over.

### 29.2 What the plan/apply pipeline builds on top of that

**This section, and the guarantee it describes, is scoped to a `Plan`'s
`file_effects` (ADR-0002).** `external_effects` (compile, commit, tag, push)
run after the file phase completes, have no journal, and are governed by
§9's ordering/reporting rules, not by this section's pre/post-state
invariant.

Given only single-file atomic rename as a primitive, `ubeats/shell/exec/`
constructs the following, and **[BINDING]** no command may claim a stronger
guarantee than this in its contract (§4) without a specific, reviewed
mechanism beyond what is described here:

```text
1. preflight the whole Plan's file_effects (§9) — refuse before touching
   anything if any effect looks unsatisfiable (missing source, occupied
   destination, unwritable target, a non-empty RemoveDir target, stale
   model digest)
2. stage every new byte into a journal directory (no target file touched yet)
3. commit: apply each file_effect as one atomic single-file rename, in the
   Plan's stated order, recording each completed rename in the journal
4. on full success: discard the journal
5. on failure at any step: roll back completed renames from the journal,
   restoring every touched file to its pre-plan content
6. only then, if the Plan has external_effects: run them in order, with no
   journal and no rollback — a partial completion here is reported, never
   hidden (§9, ADR-0002)
```

**[BINDING]** For every command whose plan can contain more than one effect,
the fault-injection test matrix from the source guidelines' original
transactional table is mandatory, retargeted:

```text
fail before staging begins
fail during staging (before any target file is touched)
fail between commit of effect k and effect k+1, for every k
fail after the last commit, before journal discard
```

Each of these must be shown to leave the repository in one of exactly two
states: the full pre-plan state, or the full post-plan state — **never** a
mix, and never silently. Where the current implementation cannot yet
guarantee this for a specific effect type, that gap is stated explicitly in
the command's contract and tracked as a failure mode in `FAILURE-MODES.md`
(this is `PROPOSAL.md`'s **FM-03**), not silently assumed to be safe.

### 29.3 What is explicitly NOT guaranteed, and must be stated as such

**[BINDING]** The following limits are real and must never be papered over
by a command's contract implying otherwise:

- **No cross-process isolation during the commit window.** A second process
  reading files while `ubeats/shell/exec/` is between renames k and k+1 can
  observe a genuinely partial state — this is a property of the filesystem,
  not a defect in the journal design. §41's single-writer lock policy exists
  *because* this section cannot promise otherwise; it is the mitigation, not
  a redundant precaution.
- **A crash inside the OS-level rename call itself** (not before, not after
  — the vanishingly rare window of the syscall itself) is outside what any
  userspace journal can observe or repair; NTFS's own rename atomicity is
  the only guarantee operating in that instant, and this project inherits it
  rather than improving on it.
- **The journal itself is a file**, subject to the same single-file-rename
  atomicity and no more; `ubeats doctor` reporting "a journal is present and
  needs recovery" after an interruption is the expected, designed-for
  outcome of a crash during commit — not a secondary failure.

**[BINDING]** Every port and command contract (§4) that involves multi-effect
persistence must state its atomicity guarantee using the vocabulary of this
section explicitly (pre-state/post-state guarantee, single-writer assumption,
journal recovery behavior) rather than the word "atomic" left undefined. A
contract that says "atomic" with no further qualification is treated as a
documentation defect.

---

## 30. Protocol design for automation

**[BINDING]** Every `ubeats` command supports `--json` and emits the
versioned envelope defined in `PROPOSAL.md` §10.2 (`"schema":
"ubeats.result/1"`, `ok`, structured `error` with a `kind` drawn from §12's
taxonomy, `effects_planned`, `effects_applied`). Machine-readable output is
not a secondary mode bolted onto a human-oriented CLI; it is the primary
interface, and human-readable text is a **presenter** built over the same
result object (§4). There is exactly one source of truth for what a command
did.

**[BINDING]** Every consequential command supports `--dry-run`, which is the
plan-construction half of §9's pipeline with the apply half skipped — never a
separately maintained simulation.

---

## 31. Agentic use does not relax validation

**[BINDING]** An automated agent is an ordinary client (§2). It receives no
privileged access to model files, no relaxed validation, no separate code
path. An invalid request from an agent is rejected by `ubeats/domain/`
exactly as an invalid request from a human-driven CLI invocation would be,
with the same `DomainError` and the same `--json` envelope.

**[BINDING]** The architecture assumes an agent can send a malformed request,
repeat a command it already ran, act on stale knowledge of the document's
state (mitigated by the model-digest check in §9's preflight), or
misunderstand the current lifecycle stage. None of these are special cases
requiring bespoke handling — they are the same conditions a human client can
produce, and the same rejection and idempotency mechanisms (§9, §28) cover
them.

---

## 32. Observability

**[BINDING]** A rejected or failed command's result must carry enough
structure to answer, without inspecting logs: what was requested; whether
validation passed; which invariant (if any) rejected it; whether a plan was
constructed; whether apply was attempted; whether it committed; which port
(if any) failed; and which schema/contract version was in effect. This is
the `--json` envelope's job (§30, §10.2), and it is deliberately not
delegated to logging.

**[ADVISORY]** Logs remain useful for diagnosis and post-mortem analysis, and
should be structured (not free text) wherever practical, but a client must
never be required to parse a log to learn something the structured result
should already contain.

---

## 33. Dependency policy

**[ADVISORY]** Use mature, well-maintained third-party libraries rather than
reimplementing solved problems (TOML parsing, JSON Schema validation,
mutation testing tooling) — but keep the asymmetry from the source
guidelines §33's underlying principle strict at the domain boundary:

```text
ubeats/domain/                 ubeats/adapters/ , ubeats/shell/
-----------------------        -----------------------------
small                          feature-rich where justified
deterministic                  technology-specific
few dependencies                dependency-heavy where justified
highly testable                 replaceable
```

**[BINDING]** `ubeats/domain/` may depend only on the Python standard
library's non-I/O modules and small, pure, vetted utility libraries with no
transitive I/O surface (a validation/parsing helper is acceptable; an HTTP
client is not, regardless of how convenient). Any dependency added to
`ubeats/domain/`'s import graph is reviewed specifically for whether it
performs I/O anywhere in its own implementation — a dependency that is pure
today but could change that in a minor version is a risk noted in the
dependency's ADR or pinned tightly enough that an upgrade is a reviewed
event, not automatic.

---

## 34. Avoid framework-dominated domain models

**[BINDING]** `Document`, `SectionNode`, and the other domain types (§7 of
`PROPOSAL.md`) are not TOML-library row objects, not `argparse.Namespace`
instances, not a serialization library's generated class, and not whatever a
future web or IPC framework's request object happens to look like. Each
boundary translates explicitly:

```text
TOML table (tomllib)
   ↓  validating constructor (§3.4 rule 5)
Document (domain type)
   ↓  render()
generated Typst source (a plain string value)
```

**[ADVISORY]** This costs more explicit code than passing one library object
through every layer would. It is worth it because it keeps `ubeats/domain/`
free of a change in `tomllib`'s API, a CLI argument-parsing library's
conventions, or a serialization library's decorators ever becoming, by
accretion, part of the domain model's actual shape.

---

## 35. Prefer explicit mapping over hidden magic

**[ADVISORY]** Code generation, decorators, and light reflection are not
forbidden — the `render(doc, facts) -> RenderedTree` pipeline is itself a form of
code generation, and dataclass-based validation makes reasonable use of
Python's data model. **[BINDING]** Wherever such a mechanism is used inside
`ubeats/domain/` or at a port boundary, it must remain possible to answer, by
reading the code (not by running it and observing): what code runs, when it
runs, what state it changes, and what happens when it fails. A metaprogramming
technique that makes any of those four questions require a debugger to answer
is not used in `ubeats/domain/`, regardless of how much boilerplate it would
save.

---

## 36. Replaceability should be real

**[BINDING]** For every port, `PROPOSAL.md`'s three-adapter requirement (§8:
real, fake, faulty) must be exercisable without invasive changes to the
consumer — meaning the domain and app-layer code that calls a port through
its Protocol type must not need to change, or even be aware, which of the
three adapters is wired in. This is verified directly: the same contract
suite (§17) already proves this by running unmodified against all three.

**[BINDING]** If wiring a fake or faulty adapter in place of the real one for
a given test requires reconfiguring unrelated parts of the application (not
just the dependency-injection point for that one port), the boundary is not
clean and the port's design is revisited before the test is written around
the workaround.

---

## 37. Keep the domain independent of test doubles

**[BINDING]** `ubeats/domain/` and `ubeats/app/` must contain no
test-specific conditional logic (`if os.environ.get("UBEATS_TEST"):` or
equivalent). Testability comes exclusively from substituting an adapter
behind a port (§36), never from a runtime branch inside production code that
exists only to behave differently under test. The real adapter and the
faulty adapter for a given port satisfy the exact same Protocol and are
interchangeable from the consumer's point of view — that symmetry is the
whole value of §18's faulty-adapter family, and a test-mode branch would
defeat it by making the "test path" behave differently in kind, not just in
data, from production.

---

## 38. Version contracts deliberately

**[BINDING]** The CLI's JSON envelope carries an explicit schema identifier
(`"schema": "ubeats.result/1"`, §30); the persisted model carries an explicit
`schema_version` (`PROPOSAL.md` §7.1, §14, **FM-08**). Both are versioned
intentionally, and compatibility policy is answered explicitly, not left to
accidental parser tolerance:

- **Model schema changes** ship with a migration and a migration test
  (loading a document at the previous `schema_version` must either succeed
  after migration or fail with `UnsupportedSchema`, never silently
  misinterpret old data).
- **Result envelope changes** that add an optional field are non-breaking;
  changes that remove or repurpose a field bump the schema number, and
  `ubeats explain <command>` (§10.5) publishes the current contract so a
  client can check compatibility before depending on a field.
- **Command surface changes** (a verb removed or its meaning changed) follow
  the same discipline as the source guidelines' broader point: a client
  should never discover an incompatibility by having its request silently
  misinterpreted.

**[ADVISORY]** Prefer additive, optional fields over breaking changes
wherever the underlying semantics allow it; reserve a schema version bump for
changes that cannot be made additive.

---

## 39. Test the delivered boundaries

**[BINDING]** Library-level (unit, property, contract) tests are necessary
but not sufficient. The E2E layer (`PROPOSAL.md` §12.1) exercises the
*installed* `ubeats` executable as an external process would see it:

```text
install ubeats from the locked environment
    ↓
invoke a command as a subprocess, exactly as a git hook or an agent would
    ↓
observe stdout/--json output and exit code (§10.3)
    ↓
interrupt mid-apply (§29)
    ↓
re-invoke, observe journal recovery
    ↓
verify the on-disk model and generated tree are consistent
```

This is what catches defects that exist only at the process boundary — an
argument-parsing edge case, an exit-code mismatch, an environment-variable
assumption that unit tests, running inside the same process as the test
runner, cannot see.

---

## 40. Prefer determinism

**[BINDING]** Sources of nondeterminism are controlled wherever they could
affect an observable result: the clock is `ClockPort`, injected (§8); random
or generated identifiers are either derived deterministically from inputs or
supplied explicitly by a caller; test temporary paths are isolated per test;
iteration over any domain collection that could affect output order uses an
explicitly ordered type (`tuple`, not `set`, per §3.4 rule 2).

**[BINDING]** A failing property-based or fuzz-generated test case must be
reproducible from its recorded input and fault schedule (§22, §26) — a
flaky, unreproducible failure is treated as a bug in the test harness's
determinism control, investigated with the same priority as a domain defect,
not dismissed as "flaky" and rerun.

---

## 41. Concurrency requires explicit semantics

**[BINDING]** UBEATS v2's default concurrency policy is **single-writer**:
one `ubeats` process may hold the mutation path (plan/apply, §9) against a
given repository at a time, enforced by an advisory lock file with a
documented stale-lock recovery procedure. This is a **decided** lead ruling,
not an open question — it no longer appears in `PROPOSAL.md` §16's register
— and is recorded formally by a forthcoming **ADR-0004**; this section states
the binding policy in the meantime and is superseded by that ADR's text, not
by silent drift. Lock contention is a `Conflict` `DomainError`, exit 1 (§12,
§46 row 24) — not an `InfrastructureError`. This policy exists precisely
because §29.3 cannot promise cross-process isolation during a commit window
at the filesystem level alone.

**[BINDING]** Any component introducing concurrency beyond this default
(parallel builds of independent documents, for instance, which do not share
a lock) must state explicitly: ownership of the lock; ordering guarantees (or
their absence) between concurrent operations; cancellation and shutdown
behavior; and stale-state handling. Concurrency is never introduced merely
because Python's `asyncio` or `multiprocessing` makes it syntactically
convenient.

**[ADVISORY]** Concurrency-specific bugs (lock contention, stale-lock
recovery correctness) should have dedicated tests; do not assume ordinary
integration tests, which typically run single-writer by construction, will
surface them.

---

## 42. Failures should be observable but contained

**[BINDING]** The intended shape of every failure is:

```text
fault
  ↓
detected at the port boundary that owns it (adapter, or preflight in shell)
  ↓
converted to a defined DomainError / InfrastructureError (§12)
  ↓
the specific operation is rejected or, where explicitly contracted, degraded
  ↓
every unrelated, already-valid part of the Document remains valid
```

**[BINDING]** An unhandled Python exception escaping `ubeats/domain/` or
`ubeats/app/` into the CLI's top-level handler is a defect, not acceptable
control flow — it is caught, converted to `CorruptModel` or
`ExternalToolFailure` with full diagnostic detail attached, and reported
through the normal result envelope (§30), never allowed to print a bare
traceback to a client expecting a `DomainError`.

---

## 43. Simplicity is still a requirement

**[BINDING]** None of the rigor in this document licenses needless
complexity. Prefer the simplest mechanism that provides the required
contract, isolation, observability, test seam, and failure behavior — a
direct function call over an unjustified port (§6); a plain dataclass over
elaborate generic type machinery when the simpler form communicates the same
invariant (§11); TOML tables over a bespoke binary format when TOML
adequately represents the model (§5).

**[ADVISORY]** When reviewing a change, ask whether removing a layer of
indirection would lose any of: substitutability actually exercised by a test
(§36), a contract actually depended upon by more than one consumer (§4), or
an isolation boundary actually protecting the domain from an unstable
external technology (§7). If the answer to all three is no, the layer is
ceremony, not architecture, and should be removed or never added.

---

## 44. Rules for generated artefacts

This section does not exist in the source guidelines. It exists because of
this project's own history: `PROPOSAL.md` §3.1 records a finished prose file
that sat in the repository for weeks, included by nothing, absent from every
PDF, undetected because nothing could tell "authored" and "generated" apart
well enough to check. UBEATS v2 makes that distinction structural.

**[BINDING]** Everything under `generated/**` is a build artifact of the pure
function `render(doc, facts) -> RenderedTree`. It is never hand-edited (§5).
The following rules make that enforceable rather than aspirational:

1. **Provenance header.** Every generated file begins with a machine-readable
   header identifying: the generator's own version, the `ModelDigest` of the
   `Document` (or `SectionNode`) it was generated from, and an explicit,
   unambiguous "DO NOT EDIT — regenerate with `ubeats build`" marker.
   **[BINDING]** The header MUST NOT include a wall-clock timestamp or any
   other value that would differ between two regenerations of an *unchanged*
   model — doing so would directly contradict rule 3 below, and is exactly
   the kind of accidental nondeterminism §40 forbids.

2. **Hash manifest.** A manifest (committed alongside the generated tree,
   e.g. one entry per generated file, each keyed to the `ModelDigest` it was
   produced from) records the expected hash of every generated file at last
   regeneration. **[BINDING]** `ubeats verify` recomputes this manifest and
   fails with a dedicated error (distinct from `CorruptModel`, since the
   model itself may be perfectly valid — the generated tree has simply
   drifted from it) if any generated file's hash does not match what
   regenerating the current model would produce.

3. **Idempotence and byte-stability.** **[BINDING]** Regenerating from an
   unchanged model MUST produce byte-identical output, every time, on every
   machine. This is what makes rules 1 and 2 meaningful — a hash comparison
   is only a useful drift detector if "no drift" and "regenerate again" are
   the same outcome. This is verified by the golden test suite
   (`PROPOSAL.md` §12.1, §12.3's binding property "Rendering is total") and
   additionally by a dedicated regenerate-twice-and-diff property test.

4. **Committed for review, gated by regeneration, not by trust.**
   **[ADVISORY]** Generated Typst source SHOULD be committed to version
   control, specifically so reviewers can see the rendering consequence of a
   model change in a normal diff, without running the toolchain locally.
   **[BINDING]** Regardless of whether it is committed, the generated tree's
   correctness is never established by "it's in the diff and looks right" —
   it is established by the CI regeneration check (rule 5) succeeding.

5. **CI enforcement.** **[BINDING]** CI runs a regenerate-and-compare step
   (conceptually `ubeats build --check-generated`, or the equivalent
   invoked from the golden test suite): regenerate from each model in the
   working tree and fail the build if the result differs from what is
   currently on disk under `generated/**`, or if any provenance header or
   manifest entry is stale.

**[BINDING]** This section's rules apply, without modification, to any future
generated artifact class this project adds (a generated citation record, a
generated index) — "generated" is defined by *how the file comes to exist*,
not by which specific directory it happens to live in today.

---

## 45. Decision heuristic

When making an implementation decision anywhere in UBEATS v2, ask, in this
domain's terms:

1. Does this belong in `ubeats/domain/`, or does it need to know the time,
   what is on disk, or what another program says (§7.1)? If the latter,
   which port owns that knowledge, and does that port already exist?
2. What is the contract at this boundary (§4) — inputs, outputs, error
   variants, atomicity, versioning — and is it written down anywhere a
   consumer could find it without reading the implementation?
3. Which assumptions here are currently implicit — an ordering, a timing
   behavior, a filesystem property this project does not actually control
   (§29.1) — and would a reviewer unfamiliar with the code discover them by
   reading the contract alone?
4. Can the consumer of this be tested against a fake, without the real
   Typst compiler, the real filesystem, or a real PDF library (§17, §36)?
5. Can the provider be tested against its own published contract
   independently of any specific consumer (§17)?
6. What happens if this component fails explicitly (§13) — is that failure
   a `DomainError` (a legitimate rejection) or an `InfrastructureError` (an
   adapter problem), and is that distinction preserved all the way to the
   client (§12, §30)?
7. What happens if this component behaves *incorrectly but plausibly* — a
   `ContractViolation` (§13) — rather than failing outright? Would anything
   downstream notice?
8. Can a fault here propagate into an otherwise healthy part of the
   `Document` or the generated tree (§19)? What specifically stops it?
9. Can the logic here be expressed as a pure function of its inputs (§7,
   §8)? If not, is that because an effect is genuinely intrinsic to it, or
   because the effect was never separated out?
10. Can this be exercised by mutation testing, a fuzzer, or a property test
    (§23, §25, §26) — and if the answer is no because the logic lives
    outside `ubeats/domain/`, should it move?
11. Does this abstraction earn its place under §6's justification list, and
    can that justification be written into one ADR sentence?
12. Could the concrete adapter behind this be replaced later — a different
    PDF library, a different translation backend — without changing
    `ubeats/domain/`'s semantics (§36)?
13. Is the complexity here justified by an actual requirement in
    `PROPOSAL.md` or `FEATURE-PARITY.md`, or is it solving a problem this
    project does not have?

If these cannot be answered clearly, the boundary under discussion needs
further design work before code is written against it — and, per Appendix A,
before an ADR is filed claiming it is settled.

---

## 46. How this doctrine is enforced

No rule in this document that lacks an enforcement mechanism is treated as
binding in practice, regardless of its tag — a "binding" rule with nothing
checking it degrades to the same failure mode as `PROPOSAL.md` §3.6's
vacuous verification. The table below is the authoritative cross-reference;
`doctrine/TESTING.md` owns the detailed implementation of each CI-checked
row.

| # | Rule | Section | Mechanism |
|---|---|---|---|
| 1 | No `Any` in `ubeats/domain/`; `mypy --strict` package-wide | §3.4-1 | CI gate |
| 2 | Domain value types are frozen, slotted dataclasses; `tuple`/`Mapping` in signatures | §3.4-2 | CI lint rule + fitness test |
| 3 | Identifiers are distinct types, never bare `str`/`int` | §3.4-3, §11 | Review checklist + `mypy --strict` catches many cases |
| 4 | Closed sets are enumerations | §3.4-4, §11 | Review checklist; `mypy --strict` exhaustiveness on `match` |
| 5 | External values pass through a validating constructor returning `Result` | §3.4-5 | Fitness test (no bare construction of domain types outside their constructor module) |
| 6 | Environment is hash-locked; `doctor` verifies it | §3.4-6 | CI gate + `ubeats doctor` |
| 7 | Mutation-score threshold on `rules/`, `lifecycle/`, `planning/` | §3.4-7, §23 | CI gate |
| 8 | `domain/` imports nothing from `adapters/`, `shell/`, `app/` | §6, §7 | Fitness test 1 |
| 9 | `domain/` imports no I/O-capable stdlib module | §7, §8 | Fitness test 2 |
| 10 | Every port has ≥1 real, ≥1 fake, ≥1 faulty adapter | §6, §18, §36 | Fitness test 3 |
| 11 | Every port has a contract suite run against every adapter | §17 | Fitness test 4 |
| 12 | Every port's ADR names its §6 justification | §6 | Review checklist (PR template requires ADR link) |
| 13 | Module complexity budget | §43 | CI lint gate |
| 14 | Domain unit suite completes within budget | §14, §15 | CI timing gate (fitness test 7) |
| 15 | Mutating commands implement `plan()` then `apply()`, never combined | §9 | Fitness test (shared command-dispatch path) + review checklist |
| 16 | `--dry-run` cannot diverge from `apply()` | §9, §30 | Property test (same Plan for dry-run and real run given same inputs) |
| 17 | Multi-effect plans tested at every interruption point | §29.2 | CI gate: fault-schedule matrix required per command with >1 effect type |
| 18 | Generated files carry provenance header with no timestamp | §44-1 | Fitness test / lint on `generated/**` |
| 19 | Hash manifest matches regeneration | §44-2 | CI regenerate-and-compare gate |
| 20 | Regeneration is idempotent and byte-stable | §44-3 | Golden suite + regenerate-twice property test |
| 21 | `DomainError`/`InfrastructureError` taxonomy respected at each layer | §12 | Fitness test (domain functions' return-type signatures) + mutation testing |
| 22 | Every check has a proof-of-failure companion test | §46.1 below | Review checklist, spot-audited |
| 23 | i18n catalogs stay complete in both locales | §1, §26 | Property test (binding, §12.3) |
| 24 | Single-writer lock semantics | §41 | Contract test + concurrency-specific integration test |
| 25 | No unhandled exception escapes `domain/`/`app/` to the CLI boundary | §42 | E2E test + fitness test on top-level exception handling |

### 46.1 The two rules this project already learned the hard way

Carried forward unchanged from `PROPOSAL.md` §12.7, because both were
observed causing real damage in v1 and are binding without qualification:

1. **[BINDING] No check may pass vacuously.** Every automated check —
   fitness test, contract test, CI gate — must have a companion test proving
   it *fails* when the condition it guards is actually violated. A check
   whose passing signal is "empty output" or "command exited 0" must first
   be proven capable of producing a non-empty, failing signal in the same
   environment it runs in.
2. **[BINDING] A test that changes shape must justify its new shape.** Any
   change to a test's fixtures, generators, or assertions must state, in the
   change itself, whether the coverage it previously provided is preserved —
   and mutation testing (§23) is the mechanism that confirms the claim,
   not merely the honor system.

---

## 47. Summary

```text
             independent clients
       CLI  ·  agents  ·  git hooks  ·  editors
                    │
          explicit, versioned command contract (§4, §30, §38)
                    │
                    ▼
          ┌───────────────────┐
          │ imperative shell  │   plan execution · journal · rollback (§9, §29)
          │                   │   presentation · exit codes (§10.3, §30)
          └─────────┬─────────┘
                    │
                    ▼
          ┌───────────────────┐
          │ functional core   │   Document · Outline · lifecycle (§7, §10)
          │  (Python, §3)     │   render(doc, facts) -> Typst source
          │                   │   plan(model, command) -> Result
          └─────────┬─────────┘
                    │
                   ports (§6, §8)
                    │
    ┌────────┬───────┼────────┬─────────┬──────────┐
    ▼        ▼       ▼        ▼         ▼          ▼
 FileSys   Typst   PdfInsp   Vcs      Clock   Translation / Artifact
  real/fake/faulty adapters, one contract-tested triad per port (§17, §18)
```

The engineering philosophy this doctrine enforces is: specify every boundary
a client can reach; keep authoritative logic pure and deterministic wherever
the domain allows it; push every effect to the edge and make it explicit;
build destructive operations as validate-then-plan-then-apply, never as
compute-and-mutate in one step; be honest, in writing, about what a Python
core does and does not guarantee, and compensate for the gap with typing
discipline and mutation testing rather than pretending the gap is closed;
and challenge every claimed guarantee — especially the filesystem's — with a
test that tries to break it rather than a comment that assumes it.

Correct behavior on well-formed input is necessary and not sufficient. This
project additionally requires evidence that: invalid documents are rejected,
not merely discouraged; contracts hold across every adapter that claims to
satisfy them; a filesystem interruption during a plan's commit never leaves
an undetected partial state; a corrupted or misbehaving adapter cannot
silently contaminate a healthy one; generated output can always be
regenerated and never silently diverges from the model that produced it; and
a human author and an automated agent, sending the same command, are
answered by exactly the same rule.

---

## Appendix A — Architecture Decision Record template

`PROPOSAL.md` §8 requires an ADR for every port; §6 requires that ADR to name
its justification from this doctrine's list. Use this template for every ADR
in `architecture/adr/`, one file per decision, numbered sequentially
(`ADR-0001`, `ADR-0002`, …), never renumbered or deleted once merged
(superseded ADRs are marked, not removed).

```markdown
# ADR-NNNN: <short, decision-stated title>

## Status
Proposed | Accepted | Superseded by ADR-XXXX | Deprecated

## Context
What problem or boundary is this decision about? What is currently true
that makes this decision necessary? Reference the relevant doctrine
section(s) and, if applicable, the specific FAILURE-MODES.md entry or
PROPOSAL.md section this responds to.

## Decision
State the decision in one or two sentences, as a rule someone could follow
without reading the rest of this document.

## Justification (required for any new port — Doctrine §6)
Which of the following does this decision buy? Name at least one; a port
ADR that cannot check one of these boxes is not ready to merge.

- [ ] replacing the implementation without touching the core
- [ ] independently testing the core against a fake
- [ ] a named behavioral contract (Doctrine §4)
- [ ] controlling a specific effect (Doctrine §8)
- [ ] fault injection (Doctrine §18, §22)
- [ ] observing an interaction
- [ ] isolating the core from an unstable external technology
- [ ] supporting more than one real adapter

## Contract (for a port ADR — Doctrine §4)
- Accepted inputs / preconditions:
- Output semantics / postconditions:
- Error variants and the condition each is produced under (Doctrine §12):
- Idempotency:
- Ordering / concurrency assumptions (Doctrine §41):
- Atomicity guarantee, stated in Doctrine §29's vocabulary — pre/post-state
  only, single-writer assumption, journal recovery, or "not applicable":
- Versioning / compatibility behavior (Doctrine §38):

## Fault model (for a port ADR — Doctrine §21)
Which fault categories apply (explicit failure, omission, timing, value
corruption, state inconsistency, stale state, duplication, reordering,
partial effect, protocol violation)? What does the faulty adapter for this
port need to be able to simulate?

## Adapters (for a port ADR — Doctrine §36)
- Real:
- Fake:
- Faulty:
- Contract test suite location:

## Alternatives considered
What else was considered, and why was it rejected? Include "do nothing" /
"no port, direct call" explicitly if that was a real alternative — this is
where §6's "unnecessary abstraction" check is answered on the record.

## Consequences
What becomes easier? What becomes harder? What doctrine sections does this
decision newly obligate the codebase to satisfy (e.g., "this adds a port,
therefore fitness tests 3 and 4 now cover it")?

## Enforcement
Which row(s) of Doctrine §46 apply to this decision, and are any new CI
gates, fitness tests, or review-checklist items required as a result of it?
```

---

## Appendix B — Revision log

| Rev | Change |
|---|---|
| 1 | Initial doctrine: adapted the source guidelines to this project across 46 numbered sections plus the ADR template |
| 2 | Propagated ADR-0001 and ADR-0002 (`render` is total and locale-from-model, §7; `DomainError` replaces `Rejection` throughout, §9; `FileEffect`/`ExternalEffect` split with no separate `rationale` field, §9, §29); scoped §29's pre/post-state guarantee to the file phase and made lock contention exit 1 (§41, decided pending ADR-0004, no longer an open question); resolved the `document.toml`/`terminology.toml` (authored) vs `outline.toml` (command-managed) contradiction with `PROPOSAL.md` §10.4 (§2, §5, §28); made `SectionId`/`Slug`/`DocumentId` validating wrapper dataclasses and `LocaleTag` a `StrEnum`, never `NewType`/`Literal` (§3.4 rule 3, §11); removed the "faulty adapters exist where the port has meaningful failure modes" qualifier, made it unconditional (§18); stated the healthy-mode qualifier on the contract-suite scope explicitly (§17); retired the incompatible keyword-argument `FaultSchedule` sketch in favor of `TESTING.md` §3.2's structured form (§22); fixed the `FileSystemPort` vocabulary to the frozen `read_text`/`read_bytes`/`write_atomic`/`move`/`delete`/`list_tree`/`probe` set throughout (§4, §13, §20, §21); fixed the dangling "PROPOSAL.md §33" and "TESTING.md §14" citations (§33, §7); adopted and stated the `source guidelines §N` / `Doctrine §N` citation convention in the header and throughout. |
| 3 | *(No entry.)* This document was not touched in revision 3 of the document set; the row is kept so the gap between 2 and 4 is explicit rather than silent. |
| 4 | §6: added `ProseScannerPort` as the ninth port to the inventory (ADR-0001 — this document had never been updated past the original eight-port list) and added a binding carve-out explaining why a lexical scanner is a port rather than the "serialization" the same section excludes: it is containment of external change (Typst's evolving surface syntax), not purity, that decides the case, per ADR-0001's own "Alternatives rejected" note that the scanner could technically live in `domain/`. §18: verified the "unconditional, no meaningful-failure-modes qualifier" fix recorded in revision 2 is intact and consistent with §36 and §46 row 10 — no further change needed; no other section in this document was found retaining the qualifier. |
| 5 | Final coherence sweep. The status line read a stale "Revision 2" while this log's own highest row was already 4 — corrected to 5, and this row and row 3 fill the log so it is contiguous. §1 overclaimed that the two localizations "are guaranteed complete by construction" — corrected to state precisely what the mechanical check actually delivers (catalog *key* presence, not translation correctness; `FAILURE-MODES.md` FM-21/FM-22 cover the gap). No other content changes. |
