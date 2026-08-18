# TESTING.md — Binding Testing Doctrine for UBEATS v2

**Status:** Binding · Revision 5. Every contributor — human or agent — follows this document.
**Audience:** An engineer with no prior knowledge of UBEATS. Read `PROPOSAL.md`
first for product context; this document assumes its vocabulary (`Document`,
`Outline`, `SectionId`, `Plan`, `FileEffect`/`ExternalEffect` (ADR-0002),
`Result[T, DomainError]`, `ProseFacts` (ADR-0001), the port list in §8, the
package layout in §6.1).
**Relationship to other doctrine documents:** `doctrine/SOFTWARE-ENGINEERING.md`
states the architectural style this doctrine tests *against*. Where this
document says "the core," it means `ubeats/domain/` as defined there.
**Tooling assumption:** the test runner is **pytest**; property-based tests use
**hypothesis**. Both are already implied by the `tests/property/` layout in
`PROPOSAL.md` §6.1 and are treated as fixed. Two further tool choices are
genuinely open and are called out explicitly where they arise: the mutation
-testing engine (§7.2) and the network-blocking mechanism (§11.2). Record
whichever is chosen as a P0 decision in `architecture/adr/`.
**Citation convention:** `source guidelines §N` cites the general-purpose
style guide this project adapts from; `Doctrine §N` cites
`doctrine/SOFTWARE-ENGINEERING.md`. A bare `§N` in this document is
self-referential (a section of this file).

---

## 0. The one sentence that explains this whole document

v1's model lived inside a file the compiler had to run to understand, so
almost nothing was testable without the compiler; v2's model is data, so
almost everything is testable without it. This doctrine exists to make sure
that inversion is *kept*, not merely achieved once and eroded — the same way
v1's suite quietly grew to 13 minutes without anyone deciding that it should.

---

## 1. The layers

### 1.1 The table

| Layer | Directory | Scope | May depend on | Enforced budget |
|---|---|---|---|---|
| Unit | `tests/unit/` | `domain/` only | nothing — no filesystem, no clock, no subprocess, no network | **200 ms per test** (enforced); ~10 s total (reported, non-blocking — §10.2) |
| Property | `tests/property/` | `domain/` invariants over generated inputs | nothing | < 60 s |
| Golden | `tests/golden/` | `render(doc, facts) -> RenderedTree`, byte-compared | nothing (no compiler) | < 20 s |
| Contract | `tests/contract/` | one suite per port, run against every adapter | real technology for real adapters; nothing for fake/faulty | < 3 min |
| Fault | `tests/fault/` | faulty adapters, fault schedules, interruption of `apply()` | fakes and faulty adapters only | < 2 min |
| Integration | `tests/integration/` | real Typst subprocess, real PDF library, real git | real technology | < 5 min |
| E2E | `tests/e2e/` | the installed `ubeats` binary as a subprocess | everything | runs pre-landing (not per-commit; see §12) |

These budgets are not aspirations. §10 makes the top four of them (unit,
property, golden, and the import-boundary rules) into an **executable fitness
test that fails the build**. A budget nobody checks is a wish, and a wish is
what v1 had.

### 1.2 Why the pyramid inverts

In v1, the authoritative document model was `metadata.typ` — Typst source.
Every tool that needed to answer a question as simple as "what is this
document's title" had to invoke the Typst compiler as a subprocess and parse
its output. Consequences, all observed and recorded in `PROPOSAL.md` §3.1:

- verification scripts could not run without a compiler and a built PDF;
- structural questions ("does this section actually appear in the output?")
  required a full build, because membership was encoded in `#include`
  statements the compiler resolved, not in anything a tool could inspect;
- the full suite took **13 minutes**, dominated by end-to-end tests that
  spawned real compilers against scratch git repositories, because that was
  the *only* layer capable of answering most questions.

v2's thesis (`PROPOSAL.md` §5) is that the document is data and Typst is a
rendering adapter reached through a port. This changes what a test needs:

- a question about outline structure is answered by `domain/outline/`
  directly — no filesystem, no compiler, no subprocess;
- a question about whether a command is legal is answered by `plan()` — pure;
- a question about what Typst source would be produced is answered by
  `render()` — pure, golden-tested, no compiler;
- only the question "does the generated source actually compile to a
  conformant artifact" needs the real compiler, and that question is asked at
  exactly two layers (contract, integration), not by default at every layer.

The result is not "fewer tests." It is the **same** rigor, redistributed so
that most of it runs in milliseconds. A test suite where 90% of assertions
need nothing is not a lesser suite than one where 90% need a compiler — it is
a more honest one, because it stops billing every question against the
slowest possible answer.

### 1.3 What belongs in each layer

**Unit** (`tests/unit/`). Domain rules, outline algebra, lifecycle
transitions, i18n resolution, gate evaluation, plan construction. Both the
accepted path and every rejected path (adapted from source guidelines §15). A unit
test constructs a `Document` (or a fragment of one) by hand or via a builder,
calls a pure function, and asserts on the returned value or `DomainError`.
No test in this directory may import `pathlib`, `subprocess`, `socket`,
`datetime.now`, or anything from `ubeats/adapters/`. §10 enforces this
mechanically; do not rely on discipline alone.

**Property** (`tests/property/`). The same domain code, exercised over
generated input spaces rather than hand-picked examples (adapted from
source guidelines §26). See §6.

**Golden** (`tests/golden/`). `render(doc, facts)` output, byte-compared
against committed fixtures. No compiler runs here — a golden test answers
"did the *generated source* change," not "does it still typeset correctly."
See §8.

**Contract** (`tests/contract/`). One behavioural-contract suite per port,
executed against every adapter that implements that port (real, fake, and
the faulty adapter in its healthy/no-fault-scheduled mode). This is the
central mechanism of the whole doctrine — see §2.

**Fault** (`tests/fault/`). The faulty adapters, this time *with* schedules
armed: deliberately broken components (§3), fault propagation (§4), and
interruption of the plan/apply pipeline (§5). This layer answers "what
happens when something goes wrong," which is a different and equally
important question from "does the happy path work."

**Integration** (`tests/integration/`). Real boundaries, adapted from
source guidelines §16: `render()` output actually compiles under the real Typst
binary; the compiled PDF actually carries the metadata the model declared;
`VcsPort`'s real adapter actually moves files under real git. Integration
tests are not replaced by contract tests against fakes — a fake tests a
*model* of the dependency; integration tests the dependency itself.

**E2E** (`tests/e2e/`). The installed `ubeats` console entry point launched
as a subprocess, adapted from source guidelines §39. This is the only layer that
tests the thing that actually ships: argument parsing, exit codes, `--json`
envelopes, and — critically — crash-and-restart consistency, since nothing
below this layer launches a second process against a repository left behind
by a killed first one.

---

## 2. Port contract suites

This is the mechanism that makes the whole pyramid trustworthy rather than
merely fast. Without it, "the fake filesystem passes" and "the real
filesystem passes" are two unrelated facts.

### 2.1 What it is

A port contract suite is a single set of test methods, written once against
the **port's `Protocol`**, expressing everything a consumer is entitled to
assume about that port's behaviour. It is instantiated — not copy-pasted —
against every adapter:

```text
FileSystemPortContract
        │
        ├── RealFileSystemAdapter        (tests/contract/test_filesystem_real.py)
        ├── FakeFileSystemAdapter        (tests/contract/test_filesystem_fake.py)
        └── FaultyFileSystemAdapter,     (tests/contract/test_filesystem_faulty_healthy.py)
            schedule = NO_FAULTS
```

This is source guidelines §17 applied literally: the same contract, run against
every implementation, proving substitutability rather than merely proving
that each implementation individually does something reasonable.

### 2.2 How to write one

Write the contract as a mixin class with an abstract `port` fixture. Each
adapter's test module supplies the fixture; it supplies nothing else.

```python
# tests/contract/filesystem_port_contract.py
import pytest
from ubeats.ports.filesystem import FileSystemPort
from ubeats.domain.model.paths import RelPath, PathKind
from ubeats.domain.errors import PortFailure

class FileSystemPortContract:
    """Behavioural contract for FileSystemPort. Instantiated against every
    adapter (real, fake, faulty-healthy). Do not add adapter-specific
    assertions here — this class must remain adapter-blind. The port's
    vocabulary is frozen (`ARCHITECTURE.md` §4.1): read_text, read_bytes,
    write_atomic, move, delete, list_tree, probe — no other method names.
    Every call is against `RelPath` (`TYPES.md` §2, `ARCHITECTURE.md` §1):
    `ports/` never imports `pathlib`, and neither does this contract."""

    @pytest.fixture
    def port(self) -> FileSystemPort:
        raise NotImplementedError("supplied by the concrete test module")

    def test_read_text_after_write_atomic_returns_written_text(self, port: FileSystemPort):
        port.write_atomic(RelPath("a.txt"), b"hello")
        result = port.read_text(RelPath("a.txt"))
        assert result.unwrap() == "hello"

    def test_read_bytes_after_write_atomic_returns_written_bytes(self, port: FileSystemPort):
        port.write_atomic(RelPath("a.bin"), b"\x00\x01")
        assert port.read_bytes(RelPath("a.bin")).unwrap() == b"\x00\x01"

    def test_read_of_missing_path_is_a_port_failure(self, port: FileSystemPort):
        # FileSystemPort returns Result[..., InfrastructureError] — never
        # DomainError. `NotFound` is a DomainError variant (TYPES.md §13) and
        # belongs to the core's own rejection taxonomy, not an adapter's; a
        # missing path is reported as `PortFailure` (the flat-union
        # InfrastructureError variant, PROPOSAL.md §7.5), keeping the two
        # taxonomies separate by construction.
        result = port.read_bytes(RelPath("missing.txt"))
        assert result.is_err()
        assert isinstance(result.unwrap_err(), PortFailure)
        assert result.unwrap_err().port == "filesystem"

    def test_write_then_delete_then_read_is_a_port_failure(self, port: FileSystemPort):
        port.write_atomic(RelPath("a.txt"), b"x")
        port.delete(RelPath("a.txt"))
        assert port.read_bytes(RelPath("a.txt")).is_err()

    def test_write_atomic_is_visible_whole_or_not_at_all(self, port: FileSystemPort):
        port.write_atomic(RelPath("a.txt"), b"old")
        port.write_atomic(RelPath("a.txt"), b"new" * 10_000)
        # a concurrent-looking read (not literally concurrent in this test —
        # concurrency guarantees have their own dedicated suite, see
        # doctrine/SOFTWARE-ENGINEERING.md §41) must never see a partial write
        assert port.read_bytes(RelPath("a.txt")).unwrap() in (b"old", b"new" * 10_000)

    def test_list_tree_reflects_writes_and_deletes(self, port: FileSystemPort):
        port.write_atomic(RelPath("d/a.txt"), b"")
        port.write_atomic(RelPath("d/b.txt"), b"")
        assert set(port.list_tree(RelPath("d")).unwrap()) == {RelPath("d/a.txt"), RelPath("d/b.txt")}
        port.delete(RelPath("d/a.txt"))
        assert set(port.list_tree(RelPath("d")).unwrap()) == {RelPath("d/b.txt")}

    def test_move_makes_source_absent_and_destination_present(self, port: FileSystemPort):
        port.write_atomic(RelPath("a.txt"), b"x")
        port.move(RelPath("a.txt"), RelPath("b.txt"))
        assert port.read_bytes(RelPath("a.txt")).is_err()
        assert port.read_bytes(RelPath("b.txt")).unwrap() == b"x"

    # --- probe / PathFacts: the load-bearing preflight primitive (Doctrine
    # §29) — previously unpublished as a contract. These cases exist
    # specifically because a wrong or under-tested probe is how "preflight
    # is total" quietly becomes false in practice. `PathFacts`' real fields
    # (`TYPES.md` §2) are `kind: PathKind`, `writable`, `read_only_attr`,
    # `is_reparse_point` — there is no `exists` field; existence is
    # `kind != PathKind.MISSING`.

    def test_probe_of_missing_path_reports_missing_kind(self, port: FileSystemPort):
        facts = port.probe(RelPath("missing.txt")).unwrap()
        assert facts.kind is PathKind.MISSING

    def test_probe_of_existing_writable_file_reports_writable(self, port: FileSystemPort):
        port.write_atomic(RelPath("a.txt"), b"x")
        facts = port.probe(RelPath("a.txt")).unwrap()
        assert facts.kind is PathKind.FILE
        assert facts.writable is True
        assert facts.read_only_attr is False

    def test_probe_of_read_only_file_reports_not_writable(self, port: FileSystemPort):
        port.write_atomic(RelPath("a.txt"), b"x")
        port.set_read_only_for_test(RelPath("a.txt"))  # adapter-local test hook, not on the Protocol
        facts = port.probe(RelPath("a.txt")).unwrap()
        assert facts.writable is False
        assert facts.read_only_attr is True

    def test_probe_reports_writable_write_then_fails(self, port: FileSystemPort):
        # the case §9.2 of PROPOSAL.md exists to name explicitly: preflight is
        # not total, because a condition can arise in the window between
        # probe and apply. This test does not assert the write must fail
        # here — no port can guarantee that on its own — it asserts that
        # WHEN it does (simulated via the adapter's fault-injection hook,
        # never a hand-rolled race), the contract's error is well-formed and
        # the read-back shows no partial write, exactly like any other
        # write_atomic failure.
        port.write_atomic(RelPath("a.txt"), b"old")
        facts = port.probe(RelPath("a.txt")).unwrap()
        assert facts.writable is True
        with self.locked_between_probe_and_apply(port, RelPath("a.txt")):
            result = port.write_atomic(RelPath("a.txt"), b"new")
            assert result.is_err()
        assert port.read_bytes(RelPath("a.txt")).unwrap() == b"old"

    def test_probe_reports_reparse_point(self, port: FileSystemPort):
        port.make_reparse_point_for_test(RelPath("link"), target=RelPath("real"))
        facts = port.probe(RelPath("link")).unwrap()
        assert facts.is_reparse_point is True
```

Each adapter then gets a one-fixture test module:

```python
# tests/contract/test_filesystem_real.py
from .filesystem_port_contract import FileSystemPortContract
from ubeats.adapters.real.filesystem import RealFileSystemAdapter

class TestFileSystemPortContract_Real(FileSystemPortContract):
    @pytest.fixture
    def port(self, tmp_path):
        return RealFileSystemAdapter(root=tmp_path)
```

```python
# tests/contract/test_filesystem_fake.py
from .filesystem_port_contract import FileSystemPortContract
from ubeats.adapters.fake.filesystem import FakeFileSystemAdapter

class TestFileSystemPortContract_Fake(FileSystemPortContract):
    @pytest.fixture
    def port(self):
        return FakeFileSystemAdapter()
```

```python
# tests/contract/test_filesystem_faulty_healthy.py
from .filesystem_port_contract import FileSystemPortContract
from ubeats.adapters.faulty.filesystem import FaultyFileSystemAdapter
from ubeats.adapters.faulty.schedule import NONE

class TestFileSystemPortContract_FaultyHealthy(FileSystemPortContract):
    @pytest.fixture
    def port(self):
        # the faulty adapter with an empty schedule MUST behave exactly like
        # a conformant adapter — this is what proves the faulty adapter is
        # itself trustworthy before it is used to inject faults in §3.
        return FaultyFileSystemAdapter(schedule=NONE)
```

Three test modules, ~6 lines of adapter-specific code each, one behavioural
specification. Adding a fourth adapter later — say a network filesystem
adapter — is a fourth module in this shape, not a fourth hand-written test
file.

### 2.3 What belongs in a contract test, and what does not

**Belongs — consumer-observable behaviour:**
- return values and their meaning (`read` after `write` returns what was
  written);
- error taxonomy (`PortFailure` — the `InfrastructureError` variant — on a
  missing path, not "some exception," and never `DomainError`'s `NotFound`,
  which is a core rejection, not an adapter failure — §2.2's frozen
  vocabulary);
- ordering guarantees the port actually promises (`list` reflects prior
  writes in the same session);
- atomicity guarantees the port actually promises (`write_atomic` is
  never observed half-written);
- idempotency where the port claims it (`delete` of an already-deleted path
  is not an error, if and only if the port's documented contract says so).

**Does not belong — implementation detail:**
- whether the real adapter uses `os.replace` or a temp-file-then-rename
  dance to achieve atomicity;
- whether the fake adapter stores bytes in a `dict` or a `list`;
- internal caching, retry counts, buffering, or logging;
- filesystem layout that the port does not expose (directory structure the
  adapter uses for bookkeeping);
- performance characteristics beyond the layer's time budget.

If a test needs to know *how* an adapter achieves a guarantee rather than
*whether* it holds, the test belongs in that adapter's own unit tests under
`tests/integration/` or as an adapter-only test — never in the shared
contract, because the shared contract must remain something the fake can
also satisfy.

### 2.4 The worthless-fake rule

**A fake that can diverge from its real counterpart without a test failing
is worthless.** This is `PROPOSAL.md` FM-02, one of the highest-severity
failure modes in the project, and it is the reason §2.2's three-module
pattern is mandatory rather than a style suggestion.

Concretely: if `FakeFileSystemAdapter.delete` on a missing path silently
succeeds while `RealFileSystemAdapter.delete` on a missing path returns
`NotFound`, then every unit and application test that runs against the fake
is testing a filesystem that does not exist, and a bug that depends on that
exact difference will pass every test except the slow ones nobody runs
locally. The contract suite is what catches this — it runs the *identical*
assertion against both, so divergence is a contract test failure, not a
production incident.

**Enforcement:** every port listed in `PROPOSAL.md` §8 MUST have exactly one
contract suite, and that suite MUST be instantiated against its real, fake,
and faulty-healthy adapters before any of those three adapters may be used
by application code. §10 turns "every port has a contract suite executed
against every adapter" into a fitness test.

---

## 3. Deliberately defective adapters, driven by fault schedules as data

### 3.1 Why data, not bespoke mock classes

A fault is configuration, not a hand-written class (adapted from source
guidelines §18, §21, §22). This buys reuse: the same schedule mechanism drives
deterministic regression tests, property tests generating random schedules,
fuzzing campaigns, and exact replay of a schedule that found a bug. A
hand-written `FailOnThirdWriteStore` class buys none of that — it is a
one-off.

### 3.2 The schedule format

```python
# ubeats/adapters/faulty/schedule.py
from dataclasses import dataclass
from typing import Union

@dataclass(frozen=True, slots=True)
class ExplicitFailure:
    error: str                      # maps to an InfrastructureError variant

@dataclass(frozen=True, slots=True)
class Omission:
    pass                             # call returns Ok(...) but the effect never happened

@dataclass(frozen=True, slots=True)
class Delay:
    delay_ms: int

@dataclass(frozen=True, slots=True)
class Corruption:
    describe: str                    # human label; the faulty adapter knows how to corrupt its own return type

@dataclass(frozen=True, slots=True)
class StaleRead:
    versions_behind: int

@dataclass(frozen=True, slots=True)
class Duplication:
    pass

@dataclass(frozen=True, slots=True)
class Reorder:
    swap_with_occurrence: int

@dataclass(frozen=True, slots=True)
class PartialEffect:
    fraction: float                  # 0.0 < fraction < 1.0 of the effect that becomes observable

@dataclass(frozen=True, slots=True)
class ProtocolViolation:
    describe: str

Fault = Union[
    ExplicitFailure, Omission, Delay, Corruption, StaleRead,
    Duplication, Reorder, PartialEffect, ProtocolViolation,
]

@dataclass(frozen=True, slots=True)
class FaultRule:
    port: str            # "filesystem", "typst", "pdf_inspector", "vcs", ...
    operation: str        # "write", "compile", "commit", ...
    occurrence: tuple[int, ...]   # 1-based call ordinals this rule fires on, per (port, operation)
    fault: Fault

@dataclass(frozen=True, slots=True)
class FaultSchedule:
    rules: tuple[FaultRule, ...] = ()

# NONE is a MODULE-LEVEL constant, not a dataclass field. An earlier draft
# wrote `NONE: "FaultSchedule"` as an annotated attribute inside the class
# body of a frozen, slotted dataclass — `@dataclass` treats any annotated
# class-body attribute as a field, so that class failed to import at all
# (`TypeError: non-default argument 'NONE' follows default argument 'rules'`,
# raised at class-definition time, before any test ever ran). The fix is to
# keep the constant out of the class entirely:
NONE = FaultSchedule(rules=())
```

A faulty adapter wraps a fake adapter, keeps a per-`(port, operation)` call
counter, and before delegating to the fake checks whether the current call
ordinal matches any rule's `occurrence`. If it does, it applies that rule's
`Fault` instead of delegating normally. This is intentionally the *only*
branching a faulty adapter contains — everything else is the fake's normal,
conformant behaviour, which is what lets a faulty adapter with `NONE`
(imported from `ubeats.adapters.faulty.schedule`) satisfy the same contract
suite as the real adapter (§2.2).

Schedules serialize directly to JSON/TOML for replay and for fuzzing-campaign
persistence:

```json
{
  "rules": [
    {"port": "filesystem", "operation": "write", "occurrence": [3],
     "fault": {"kind": "explicit_failure", "error": "DiskFull"}},
    {"port": "typst", "operation": "compile", "occurrence": [2, 5],
     "fault": {"kind": "timing_delay", "delay_ms": 5000}}
  ]
}
```

### 3.3 Worked example

"Fail the third write" — this is the schedule that reproduces the class of
incident described in `PROPOSAL.md` §3.4 (a mid-pass filesystem failure
during a multi-file destructive operation):

```python
from ubeats.domain.errors import PortFailure

def test_apply_fails_third_write_leaves_pre_state(tmp_path):
    plan = build_plan_with_five_write_effects()   # from a unit-tested planning fixture
    schedule = FaultSchedule(rules=(
        FaultRule(port="filesystem", operation="write_atomic", occurrence=(3,),
                  fault=ExplicitFailure(error="DiskFull")),
    ))
    faulty_fs = FaultyFileSystemAdapter(
        delegate=FakeFileSystemAdapter(seed=snapshot(tmp_path)),
        schedule=schedule,
    )

    outcome = apply(plan, filesystem=faulty_fs, journal=RealJournal(tmp_path))

    assert outcome.is_err()
    # InfrastructureError is a flat union of frozen dataclasses (TYPES.md
    # §13.1) — never nested classes — so this is a direct isinstance check
    # against the imported variant, not `InfrastructureError.PortFailure`.
    assert isinstance(outcome.unwrap_err(), PortFailure)
    # the invariant from §5: pre-state or post-state, never a hybrid
    assert snapshot(tmp_path) == pre_state_snapshot
```

### 3.4 Fault category catalogue, mapped to this system

Fault injection MUST be organized around these ten categories (adapted from
source guidelines §21), not accumulated as unrelated special-case mocks. The table
gives at least one concrete, plausible occurrence per category for the ports
this system actually has. `ProseScannerPort` (ADR-0001) is included because
fault injection over the scanner is one of ADR-0001's own stated
justifications for putting it behind a port at all (FM-51's mitigations) —
a column-less port here would leave that claim untested.

| Category | `FileSystemPort` | `TypstPort` | `PdfInspectorPort` | `VcsPort` | `TranslationPort` | `ProseScannerPort` |
|---|---|---|---|---|---|---|
| **Explicit failure** | `write_atomic` returns `DiskFull` / `PermissionDenied` | `compile` returns nonzero exit + diagnostics | file open denied | `commit` returns non-zero (hook rejected, lock held) | model load fails (missing weights file) | `scan` returns `PortFailure` on an unreadable or non-UTF-8 file |
| **Omission** | `write_atomic` reports success but the byte range is never flushed | `compile` exits 0 but emits no PDF | `read_metadata` returns success with an empty field set | `tag` reports success but no tag exists afterward | `translate` returns success with zero segments translated | `scan` succeeds but **misses a construct that is actually present** — a `#todo` inside a form the lexical pass does not recognize (FM-51) |
| **Timing** | `write_atomic` stalls on a slow/locked network share | `compile` exceeds the configured budget on a pathological input | large-PDF metadata scan stalls | `status` stalls on a huge or corrupted `.git` | translation stalls past budget on a long segment | `scan` stalls on a pathologically long or deeply nested prose fragment |
| **Value corruption** | `read_bytes(A)` returns bytes belonging to `B` (path-mixing bug) | `query` returns JSON describing a *different* document than the one just compiled | metadata reports title/keywords from a previous build | `status` lists files that were never touched this session | a segment comes back translated into the wrong target locale | `scan` **reports a construct that is not actually in the source** — a phantom `AssetRef` or marker attributed to the wrong line |
| **State inconsistency** | `probe(A).exists -> True`, `read_bytes(A) -> NotFound` | `compile` reports success, but the PDF is absent from the declared output path | conformance marker present, XMP metadata absent (mutually contradictory) | `status` clean, but `diff` non-empty | translation-memory reports a segment `reviewed`, sidecar has no reviewer record | `facts.construct_counts` disagrees with `facts.asset_refs`/`facts.markers` for the same scan (internally contradictory `ProseFacts`) |
| **Stale state** | `read_bytes` returns pre-write content immediately after a completed `write_atomic` | `query` reflects the previous source version, not the one just compiled | metadata reflects the PDF from the prior build directory | `status` reflects the tree before the last `move` | a translation-memory read reflects a segment before its last `refresh` | `scan` **returns facts for a stale `content_digest`** — a cached result served after the source changed |
| **Duplication** | `write_atomic` is applied twice (double flush) | `compile` emits the same diagnostic twice | — | `commit` produces two commits for one call | the same segment is emitted twice in a translation batch | the same marker or `TermUse` is reported twice for one occurrence |
| **Reordering** | two `write_atomic`s land in the reverse of call order | `query` results arrive out of request order under concurrency | — | `move` then `commit` observed as `commit` then `move` | segment results returned out of input order | `facts.terms_used` is returned out of source order (breaks first-use-expansion logic, which depends on order) |
| **Partial effect** | `write_atomic` becomes visible with only a prefix of the new bytes | `compile` writes a truncated PDF before erroring | — | a multi-file `move` moves some files and not others | a batch translation completes some segments, silently drops the rest | `scan` returns facts computed from only a prefix of a large file, silently dropping constructs past the truncation point |
| **Protocol violation** | — | `query` returns malformed JSON, or JSON that does not match the published schema | metadata scan returns a shape `PdfInspectorPort` never promises | a hook script writes to stdout in a way the parser cannot frame | model reports a locale pair the port has no contract for | `scan` **fails to classify a construct** and reports a `ConstructKind` outside the closed enum, or leaves a gate-relevant construct unclassified without naming the line (violates ADR-0001 mitigation 2) |
| **Preflight-window race** | `probe(A)` reports writable; a lock, ACL change, or reparse-point substitution then makes the subsequent `write_atomic(A)`/`move(A, B)`/`delete(A)` fail anyway | n/a | n/a | n/a | n/a | n/a |

Every cell above is a legitimate `FaultRule` in some adapter's test schedule.
A port's contract suite (§2) tells you what the adapter is supposed to do;
this table tells you what to make it do wrong on purpose. The **preflight-
window race** row is `FileSystemPort`-specific and exists because
`PROPOSAL.md` §9.2 states plainly that preflight is not total: a condition
arising *between* `probe` and the apply that follows it cannot be observed
by any preflight, on any OS. `test_probe_reports_writable_write_then_fails`
(§2.2) is the contract-level shape of this case; the fault-schedule form
here is what lets it be reproduced deterministically rather than as a
hand-built race.

---

## 4. Fault propagation testing

### 4.1 The pattern

When one component misbehaves, the interesting question is rarely "does the
misbehaving component fail" — it obviously does, that is what was injected.
The interesting question is what the **next, healthy** component does about
it (adapted from source guidelines §19):

```text
healthy consumer
      │
poisoned adapter          <- fault injected here
      │
healthy downstream consumer
```

For every fault in §3.4, a fault-propagation test asserts exactly one of
four outcomes, and states which one is expected and why:

1. **Detects and rejects** — the healthy consumer returns a `DomainError` or
   `InfrastructureError` and performs no further effect. This is the
   default expectation for anything reaching the shell from a port.
2. **Detects and contains** — the healthy consumer recognizes the fault,
   degrades in a documented way, and does not propagate corrupted data
   further (rare; must be explicitly justified in the contract).
3. **Propagates an explicit error unchanged** — acceptable if the consumer
   has nothing useful to add and the error is already well-formed.
4. **Silently corrupts** — **never acceptable**. Any test that finds this is
   a defect, not a fault-tolerance data point.

### 4.2 Worked example

```python
from ubeats.domain.errors import ContractViolation

def test_malformed_typst_query_response_is_rejected_not_propagated():
    schedule = FaultSchedule(rules=(
        FaultRule(port="typst", operation="query", occurrence=(1,),
                  fault=ProtocolViolation(describe="query returns non-JSON body")),
    ))
    faulty_typst = FaultyTypstAdapter(delegate=FakeTypstAdapter(), schedule=schedule)
    spy_pdf = SpyPdfInspectorAdapter(delegate=FakePdfInspectorAdapter())

    use_case = VerifyUseCase(typst=faulty_typst, filesystem=FakeFileSystemAdapter(),
                              pdf_inspector=spy_pdf, vcs=FakeVcsAdapter())

    result = use_case.run(document)

    assert result.is_err()
    # flat-union isinstance check (TYPES.md §13.1), same as §3.3 — never
    # `InfrastructureError.ContractViolation` as a nested-class access.
    assert isinstance(result.unwrap_err(), ContractViolation)
    assert result.unwrap_err().port == "typst"
    # the healthy component downstream must never have been reached with
    # data derived from the malformed response
    assert spy_pdf.call_count == 0
```

`SpyPdfInspectorAdapter` here is a thin wrapper (delegating to a fake,
recording calls) used purely to observe whether corrupted information
reached a healthy neighbour — it is not itself a contract-tested adapter and
must never be used outside `tests/fault/`.

Every `ContractViolation` case in §3.4's "Protocol
violation" and "Value corruption" rows MUST have at least one test in this
shape. This is what exit code 4 (`PROPOSAL.md` §10.3) exists to make
possible: a non-conformant component is a different, detectable event from a
legitimate failure, and this layer is what proves the distinction is real
rather than aspirational.

---

## 5. Interruption testing for the plan/apply model

### 5.1 The invariant

`PROPOSAL.md` §9 describes the plan/apply pipeline built specifically to
prevent the incident in §3.4 (a "clean the sections directory" routine that
computed and performed deletion in one pass, and under three independent
fault conditions destroyed content while reporting success — one case
destroyed 8,023 files). This section is scoped to a `Plan`'s `file_effects`
(ADR-0002) — `external_effects` have no journal and are a different, weaker
guarantee entirely (§5.3 below).

The pipeline gives **recoverability, not atomicity**, and the invariant must
be stated precisely enough to say what is true *before* recovery runs as
well as after, because a version of this invariant that only describes the
post-recovery state is not a testable guarantee about a crash — it is a
guarantee about a *second* command that a real crash does not cooperatively
invoke on its own:

> **Before recovery runs** (immediately after an interruption), the
> repository is in the pre-state, the post-state, or a **recoverable hybrid
> with a journal present** — a state a fresh `ubeats` invocation can
> deterministically complete or reverse, purely from the journal's intent
> record.
>
> **After recovery runs**, the repository is in the pre-state or the
> post-state. Never a hybrid, and never a state recovery could not resolve.

This MUST be tested at **every** file-effect boundary of **every** plan shape
the domain can produce, not sampled, and MUST test both halves of the
invariant — the immediate post-interruption state and the post-recovery
state — as two separate assertions, not one.

### 5.2 The harness

For a plan with file effects `[e1, e2, ..., en]`, there are `n + 1`
boundaries: before `e1`, between every adjacent pair, and after `en`. A
generic harness parametrizes over all of them:

```python
# tests/fault/interruption_harness.py
def boundaries(plan: Plan) -> range:
    return range(len(plan.file_effects) + 1)

def interruption_schedule_at(boundary: int) -> FaultSchedule:
    """Fail the operation that would perform file_effect `boundary` (0-based).
    boundary == len(file_effects) means: succeed through every file effect,
    then fail during journal finalization — the 'after the last effect'
    case."""
    ...

@pytest.mark.parametrize("boundary", boundaries(SAMPLE_PLAN))
def test_interruption_leaves_recoverable_state_and_recovery_resolves_it(boundary, tmp_path):
    pre_state = seed_repository(tmp_path)
    plan = build_plan_against(pre_state)
    faulty_fs = FaultyFileSystemAdapter(
        delegate=RealFileSystemAdapter(root=tmp_path),
        schedule=interruption_schedule_at(boundary),
    )

    outcome = apply(plan, filesystem=faulty_fs, journal=RealJournal(tmp_path))
    post_state_if_committed = expected_post_state(plan)

    # Half 1 of the invariant — BEFORE recovery runs. A hybrid is allowed
    # here, but only a *recoverable* one: a journal must be present that
    # unambiguously identifies how to reach pre-state or post-state.
    observed = snapshot(tmp_path)
    if observed not in (pre_state, post_state_if_committed):
        assert journal_present_and_well_formed(tmp_path, plan), (
            f"boundary {boundary}: repository is in a hybrid state with no "
            f"recoverable journal — this is the guarantee actually failing, "
            f"not merely an untested case"
        )

    # Half 2 of the invariant — AFTER recovery runs. No real crash calls
    # apply() again cooperatively; a fresh process (here, a fresh adapter
    # instance) must be able to finish the job unassisted.
    if outcome.is_err():
        recovered = resume_or_rollback(root=tmp_path, filesystem=RealFileSystemAdapter(tmp_path))
        assert recovered in (pre_state, post_state_if_committed), (
            f"boundary {boundary}: recovery did not resolve to pre- or post-state"
        )
```

This test MUST run once per `FileEffect` variant (`WriteFile`, `MoveFile`,
`DeleteFile`, `CreateDir`, `RemoveDir`) and once per representative plan
shape produced by each `app/` use case (`section add`, `section move`,
`build`, `translate refresh`, etc.) — a use case that never exercised its own
interruption boundaries has not met this doctrine's bar, regardless of how
green its happy-path tests are.

### 5.3 External effects have no journal, and are tested differently

`external_effects` (`RunCompile`, `VcsCommit`, `VcsTag`, `VcsPush` —
ADR-0002) run only after every `file_effect` has committed, have no journal,
and cannot be rolled back. Their interruption test is not "does the
repository return to pre-state" (it cannot) but "is the partial completion
reported accurately": a plan with three external effects, interrupted after
the second, MUST be shown — by a dedicated test, not the harness above — to
report the first two as completed, the third as not-run, and the plan as a
whole as `is_reversible = False` from the moment it was constructed, never
only after the fact.

**§10 turns "did every step boundary get a test" into a coverage check**, not
a matter of the author remembering: the fitness suite MUST assert, for every
`Plan`-shape fixture registered under `tests/fault/plans/`, that a test
exists parametrized over the full `boundaries(plan)` range, and — for any
such `Plan` whose `external_effects` is non-empty — that the phase-boundary
test of §5.4 also exists for it; MUST fail if a new use case adds plan
shapes without a corresponding interruption test module.

### 5.4 The boundary between the two phases

§5.2 covers interruption *within* the file phase; §5.3 covers interruption
*within* the external sequence, once it has started. Neither covers the
window ADR-0002's Consequences section names explicitly as a new required
test shape: **after the journal is removed (the file phase has fully
committed to its post-state) and before the first external effect has
begun.** This is a distinct boundary, not an instance of either neighbour:

- unlike every boundary in §5.2, there is no journal left to consult —
  recoverability from a journal is not the question, because the file phase
  is already, unambiguously, done;
- unlike every boundary in §5.3, zero external effects have run, so there is
  no partial external completion to report — the question is whether the
  system reports that correctly (as *zero completed, zero attempted*, not as
  an unknown or partially-observed state) rather than assuming an
  interruption here means anything failed.

```python
# tests/fault/interruption_harness.py (extends §5.2's harness)
def test_interruption_after_file_phase_commits_before_first_external_effect_runs(tmp_path):
    pre_state = seed_repository(tmp_path)
    plan = build_plan_with_file_and_external_effects(pre_state)  # e.g. release publish
    post_file_state = expected_post_file_state(plan)

    # simulate: file phase completes and its journal is discarded, then the
    # process is interrupted before RunCompile/VcsCommit/... is invoked —
    # never inside the external sequence itself (that is §5.3's shape).
    faulty_external = FaultyExternalRunner(
        delegate=RealExternalRunner(root=tmp_path),
        schedule=interrupt_before_first_external_effect(),
    )
    outcome = apply(plan, filesystem=RealFileSystemAdapter(tmp_path),
                     journal=RealJournal(tmp_path), external=faulty_external)

    # the file phase's own invariant (§5.1) already holds unconditionally —
    # this boundary starts only once it does, so there is no hybrid case
    # to check here, unlike §5.2's boundaries.
    assert snapshot(tmp_path) == post_file_state
    assert not journal_present(tmp_path)  # already removed; nothing to recover

    # the load-bearing assertion: partial completion is reported accurately
    # (ADR-0002 rule 5) even when "partial" means "none of them ran yet."
    report = outcome.external_effects_report()
    assert report.completed == ()
    assert report.first_not_run is plan.external_effects[0]
    assert plan.is_reversible is False  # true from construction (ADR-0002 rule 3), not only now

    # a fresh invocation must recognize the file phase is already done (its
    # digest matches post_file_state) and either resume the external phase
    # cleanly from external_effects[0], or refuse and report this exact
    # state — but it MUST NOT re-attempt any file_effect, since none of them
    # are pending and no journal claims otherwise.
    resumed = resume_or_refuse(root=tmp_path, filesystem=RealFileSystemAdapter(tmp_path))
    assert resumed.file_effects_reattempted == 0
```

This test MUST exist for every registered `Plan`-shape fixture whose
`external_effects` is non-empty (currently: `ubeats release publish`) — §10.1
rule 8 makes this a coverage check, not a convention.

---

## 6. Property-based testing

### 6.1 Why, and the tool

Hand-picked examples test the cases the author thought of. Property tests
generate broad input spaces and check invariants that must hold regardless
(adapted from source guidelines §26). This doctrine uses **hypothesis**. A failing
example is automatically shrunk to a minimal reproduction, and MUST be
promoted into a literal `@example(...)` in the test (see §11.3) so the
regression survives independent of any local cache.

### 6.2 Binding properties (minimum set — extend freely, never shrink)

Each property below MUST exist as an executable hypothesis test before P1
exits (`PROPOSAL.md` §15.1). Strategies are sketched, not exhaustive.

**1. Outline algebra is closed.** Any sequence of valid `insert` / `move` /
`promote` / `demote` operations produces a tree: single parent per node, no
cycles, no duplicate `SectionId`.

```python
@given(ops=st.lists(outline_operation_strategy(), min_size=1, max_size=50))
def test_outline_stays_well_formed_under_any_valid_operation_sequence(ops):
    outline = EMPTY_OUTLINE
    for op in ops:
        result = apply_outline_op(outline, op)
        if result.is_ok():
            outline = result.unwrap()
    assert is_well_formed(outline)   # single parent, acyclic, unique ids
```

**2. Move is its own inverse.** Moving a section then moving it back
restores the original outline exactly (already stated in `PROPOSAL.md`
§12.3).

```python
@given(outline=outline_strategy(), section=st.data())
def test_move_then_move_back_is_identity(outline, section):
    node_id, old_parent = pick_movable_node(outline, section)
    moved = move(outline, node_id, to=other_parent(outline, node_id, section)).unwrap()
    restored = move(moved, node_id, to=old_parent).unwrap()
    assert restored == outline
```

**3. `plan()` is deterministic.** Same model + same command => byte-identical
`Plan` (already stated in `PROPOSAL.md` §12.3). This MUST hold across
repeated calls within a process **and** across process restarts with the
same inputs, since determinism across restarts is what makes `--dry-run`
trustworthy.

**4. A rejected command mutates nothing.** If `plan()` or `apply()` returns
an error, no `Effect` was executed and the on-disk model (in the relevant
harness) is unchanged.

**5. Locale catalog parity.** Every key resolvable in the `en:` table is
resolvable in the `ja:` table and vice versa — no orphan keys either way.

```python
@given(key=st.sampled_from(sorted(set(EN_KEYS) | set(JA_KEYS))))
def test_every_key_resolves_in_both_catalogs(key):
    assert key in EN_KEYS
    assert key in JA_KEYS
```

**6. `render()` is total.** No valid `Document`/`ProseFacts` pair — however
generated — makes `render(doc, facts)` raise. Every path returns a
`RenderedTree` (never an exception, and never a `Result` — §7 of
`SOFTWARE-ENGINEERING.md`); if the model itself is invalid, that invalidity
was already caught by a validating constructor before `render()` was ever
called, and if a gate-relevant construct is unclassifiable in `facts`, that
is caught by the publication gate (ADR-0001), not by `render` refusing.

**7. Serialization round-trips.** `parse(serialize(model)) == model` for
every valid `Document` the strategy can build (TOML persistence, `PROPOSAL.md`
§7.4).

**8. `SectionId` is stable.** A node's `SectionId` is unchanged by `move`,
`rename`, `reorder`, `promote`, and `demote` — only `delete` (and its
sub-tree) removes an id, and no other operation ever reuses a removed id.

**9. Rendering is idempotent under re-invocation.** `render(doc, facts)`
called twice on the same inputs, in the same process or a fresh one, is byte
-identical — no hidden dependency on wall-clock time, dict iteration order,
or random identifiers leaking into generated source (adapted from source
guidelines §40).

**10. Document identity survives reorganization.** The citation record and
`Identity` fields are unaffected by any sequence of outline operations that
does not explicitly change them — moving sections around must never
perturb the doc-id, revision, or citation key.

**11. A plan's effects are well-formed in isolation from execution order
concerns that would make replay ill-defined.** No `Effect` in a `Plan`
targets a path that a *later* `Effect` is responsible for creating; i.e. the
effect sequence is already a valid topological order of its own
dependencies. (This is checked structurally on the `Plan` value, not by
executing it — it is a pure property of `plan()`'s output.)

**12. The model digest catches staleness.** If the on-disk model changes
between `plan()` and `apply()`, `apply()` always refuses — for any mutation
to the pre-state, however small, that changes its digest.

**13. Lifecycle transitions are a closed relation.** For any `Lifecycle`
state and any requested transition, the result is either a member of the
explicitly declared transition table or `IllegalTransition` — there is no
third outcome, and no transition mutates state when rejected.

**14. Gate evaluation is deterministic and side-effect-free.** Evaluating a
publication gate against the same `(Document, ProseFacts)` pair twice in a
row yields the same verdict and the same finding list, in the same order —
`facts` must be held constant across both calls exactly like `doc`, since
`publication_gate(doc, facts)` (ADR-0001, §7.4) depends on both.

**15. Heading depth matches tree depth in both locales.** For every node in
a rendered outline, the emitted heading level equals `1 + ancestor count`,
independent of locale, independent of which siblings exist.

Failing examples discovered by any of the above MUST be persisted per §11.3
— never left to hypothesis's local example database alone.

---

## 7. Mutation testing

### 7.1 Where it is mandatory

Mutation testing is **mandatory** on:

- `domain/rules/` — validation and invariants;
- `domain/lifecycle/` — the state-machine transition table and its guards;
- `domain/planning/` — command-to-`Plan` construction.

These are the modules where a subtly wrong comparison, an inverted boolean,
or a swapped branch is both plausible to write and expensive to ship — a
lifecycle guard that is one character too permissive silently authorizes an
illegal transition; a planning bug can silently produce a `Plan` missing an
effect. Ordinary coverage cannot distinguish "this line ran" from "this
line's logic was actually verified" (adapted from source guidelines §23, §20).

Mutation testing elsewhere in `domain/` is encouraged but not gating.
`app/`, `shell/`, and `adapters/` are explicitly **not** mutation-testing
targets — their correctness is established by the contract, fault, and
integration layers instead, because mutating an adapter's implementation
detail (as opposed to a port's contract) produces mostly equivalent mutants
and wastes the signal.

### 7.2 Tool — open decision

This doctrine is written tool-agnostically: any engine capable of mutating
Python source and running the affected pytest subset per mutant satisfies
it (e.g. an AST-mutation tool such as `mutmut` or a mutation-testing engine
such as `cosmic-ray`). **The specific tool is an open P0 decision**
(`PROPOSAL.md` §15.1), to be recorded in `architecture/adr/`. The
requirements below (score reporting, survivor disposition, CI scoping) apply
regardless of which engine is chosen.

### 7.3 Disposition of surviving mutants

A mutation score is not the goal; understanding every survivor is. For each
surviving mutant on a mandatory module, the author MUST record one of:

| Disposition | Meaning | Required action |
|---|---|---|
| **Missing test** | the mutant represents a real behavioural difference nothing asserts on | write the missing test; re-run |
| **Redundant code** | the mutated code has no observable effect on any documented behaviour | remove the code, or explain in a comment why it exists (e.g. defense-in-depth) |
| **Equivalent mutant** | the mutation cannot change observable behaviour under any input (proven, not assumed) | record the proof inline as a comment next to the mutated line; suppress that specific mutant only |
| **Insufficiently specified behaviour** | the contract genuinely does not say what should happen here | escalate — this is a contract gap, not a test gap; fix the contract (ADR) before suppressing |
| **Overly complex decision logic** | the surviving mutant is a symptom of a condition that is hard to test because it is hard to reason about | simplify the logic; do not merely add a test around the complexity |

**Enforcement:** a suppression (mutant marked equivalent or accepted) MUST be
committed as a line-referenced entry in a per-module ledger (e.g.
`tests/mutation/ledger/planning.toml`), not a bare tool-specific inline
skip comment with no rationale. A PR that increases the ledger MUST justify
each new entry in the PR description; `regression-verifier`-equivalent
review for this project checks the ledger diff against the code diff.

### 7.4 MC/DC for compound gate decisions

Branch coverage hides untested condition interactions in compound boolean
decisions (adapted from source guidelines §24). UBEATS v2's publication gate is
exactly such a decision:

```python
def publication_gate(doc: Document, facts: ProseFacts) -> Result[None, DomainError]:
    ok = (
        no_placeholders(facts)
        and all_required_fields_present(doc)
        and doc.lifecycle.state is LifecycleState.APPROVED
        and not is_watermarked(doc.translation)
    )
    ...
```

Per ADR-0001, placeholder/todo/unresolved markers are facts about prose, not
facts about the model — `no_placeholders` reads `facts.markers`, never
`doc`. The other three conditions genuinely are `Document`-only concerns
(required fields, lifecycle state, translation-state watermarking), so they
keep taking `doc`. This changes what `no_placeholders` is called with; it
does not change the compound decision's shape, so the MC/DC case table below
is unaffected and remains valid as stated — four conditions, same isolation
pairs, only the first condition's *source* (`facts` instead of `doc`)
differs.

MC/DC requires, for each of the four conditions, at least one pair of test
cases where that condition alone flips while the others are held fixed, and
the outcome flips too:

| Case | `no_placeholders(facts)` | `fields_present(doc)` | `state == APPROVED` | `not watermarked` | Gate result | Isolates |
|---|---|---|---|---|---|---|
| A | T | T | T | T | pass | baseline |
| B | F | T | T | T | reject | `no_placeholders` |
| C | T | F | T | T | reject | `fields_present` |
| D | T | T | F | T | reject | `state == APPROVED` |
| E | T | T | T | F | reject | `not watermarked` |

Five cases, each pytest-parametrized, each asserting both the boolean
outcome **and** which `DomainError` (an `InvariantViolation` naming the
specific failed condition, not a second, competing error type) was
reported — a gate that rejects for the right *aggregate* reason but the
wrong *stated* reason is still a defect, because the reason is what the
writer or agent acts on.
MC/DC MUST be applied to every compound decision in `domain/rules/` gates
and to `domain/lifecycle/` transition guards with more than one condition.
It complements, and never substitutes for, the property and mutation
coverage of the same code (source guidelines §24).

---

## 8. Golden tests on generated Typst source

### 8.1 Keeping them meaningful

A golden test's entire value is that a reviewer can look at its diff and
know whether it is expected. That value is destroyed by two habits: goldens
so large that one meaningful line change is buried in incidental churn, and
goldens nobody can explain the purpose of. Both MUST be prevented
structurally, not by reviewer vigilance alone:

- **One construct per fixture.** A golden fixture exercises exactly one
  rendering rule or one narrow combination (e.g. "a two-level outline in
  `ja`," "a figure with a pinned size and a caption," "an acronym on first
  use"). Do not golden-test whole assembled documents as the primary
  mechanism — reserve one or two whole-document goldens per document class
  for structural sanity, and put everything else in small, targeted
  fixtures under `tests/golden/render/<construct>/`.
- **Every fixture carries a one-line intent.** Each golden file
  `tests/golden/render/<construct>/<case>.typ` has a sibling
  `<case>.intent.md` stating, in one sentence, what would have to be true
  of `render()` for this fixture to be correct — e.g. *"a level-2 JA
  section heading uses `2.1節`, not `Section 2.1`."* A golden without an
  intent file does not merge.
- **Fixtures are named for the behaviour, not the input.** Prefer
  `heading_numbering_ja_level2.typ` over `case17.typ`.

### 8.2 Reviewing a golden diff

A reviewer of a golden diff MUST be able to answer, from the diff and the
intent file alone:

1. Which rendering rule changed, and is that rule's change intentional
   (visible in the same PR's `domain/render/` diff)?
2. Does the new output still satisfy the fixture's stated intent? If the
   intent itself needed to change, the intent file's diff must say why.
3. Is any *other* fixture's output touched by this diff that the PR's
   description does not mention? An unexplained multi-fixture diff is a
   signal the change was broader than intended.

A golden diff with no corresponding `domain/render/` source diff in the same
PR MUST be treated as suspicious by default — see §8.3.

### 8.3 Preventing "just regenerate the goldens"

The failure mode this guards against: a developer runs the build, sees a
golden test fail, and reflexively re-runs the fixture-regeneration script
without reading the diff, because that is faster than understanding it. This
is exactly the mechanism that let v1's checks silently weaken over time
(`PROPOSAL.md` §3.6, §12.7).

Binding rules:

1. **Regeneration requires a reason.** The regeneration script MUST require
   `--reason "<text>"`, and MUST write that text into the fixture's
   `.intent.md` (either confirming the existing intent or replacing it —
   silently leaving a stale intent file that no longer matches the fixture
   is itself a defect the CI check below catches).
2. **CI blocks unexplained golden changes.** A PR that changes files under
   `tests/golden/render/**/*.typ` MUST also change at least one of:
   `ubeats/domain/render/**`, or the corresponding `.intent.md`. A golden
   diff with neither is rejected automatically, before human review — this
   is the single highest-leverage guard against the reflex, because it
   removes the option rather than relying on the reviewer noticing.
3. **No bulk regeneration in one commit across unrelated fixtures — enforced
   by review, not by CI.** If a change to shared rendering infrastructure
   (e.g. a shared heading-numbering helper) legitimately touches many
   fixtures at once, the PR description MUST name the shared change and the
   fixtures it is expected to move. Whether a given `domain/render/` diff is
   "large enough to plausibly justify" the number of fixtures it moved is
   **not implementable as a CI gate** — there is no size threshold that
   cannot be gamed by padding an unrelated diff, and no threshold small
   enough to catch every real case without also flagging legitimate refactors.
   This is therefore a named **review rule**, not a fitness test: the
   reviewer checks the named shared change against the actual fixture diff
   and rejects a mismatch on inspection. Rule 2's CI gate (some
   `domain/render/` diff exists) remains a real, mechanical check; rule 3's
   *proportionality* judgment does not get the same mechanical treatment,
   and this document says so rather than claiming a heuristic it cannot
   enforce.
4. **Golden tests are a required part of the pre-commit budget (§1.1), not
   opt-in.** A construct with no golden coverage is a rendering rule that
   can regress silently — treat "no golden test for this rendering rule" as
   equivalent in severity to "no unit test for this validation rule."

---

## 9. Two anti-patterns the predecessor suffered, as binding rules

### 9.1 No vacuous checks

**The incident.** A "goldens are unchanged" check in v1 ran a git command
against an uninitialized submodule. Git silently resolved the command
against the parent repository instead, matched nothing, and returned empty
output. Empty output was treated as "no drift found" and reported as a
**pass** — proving nothing (`PROPOSAL.md` §3.6, §12.7, FM-23).

**The rule.** Every check — a test assertion, a CI gate, a verification
script, an `ubeats verify` finding category — MUST have a companion test
that proves the check **fails** when the condition it guards is violated.
A check whose passing state is "empty output," "no findings," or "zero
matches" MUST additionally have a companion test that first demonstrates the
check is capable of producing non-empty output / findings / matches **in the
same execution environment**, using a fixture that deliberately violates the
guarded condition. A check that has never been observed to fail has not
been shown to check anything.

**Worked example for this system.** `ubeats verify --strict` includes an
"orphan prose file" finding: a prose file under `prose/**` not referenced by
any `SectionNode.body` in the outline. The historical bug class this guards
against is exactly a v1-shaped one: a scan that silently matches nothing
because of a misconfigured glob, a wrong root, or a resolution that quietly
falls back to the wrong tree.

```python
def test_orphan_prose_check_detects_a_real_orphan(tmp_repo):
    write_well_formed_document(tmp_repo)
    write_prose_file(tmp_repo, "prose/never_referenced.typ", body="orphaned content")
    result = verify(tmp_repo, strict=True)
    assert result.is_err()
    findings = result.unwrap_err().findings
    assert any(f.kind == "OrphanProseFile" and f.path.name == "never_referenced.typ"
               for f in findings)

def test_orphan_prose_check_passes_on_a_well_formed_document(tmp_repo):
    write_well_formed_document(tmp_repo)   # every prose file referenced
    result = verify(tmp_repo, strict=True)
    assert result.is_ok()

def test_orphan_prose_check_actually_scanned_something(tmp_repo):
    # this is the test that would have caught the v1 incident: it does not
    # just check the verdict, it checks that the checker engaged with a
    # non-trivial candidate set, so a silently-empty scan cannot pass by
    # accident when the fixture guarantees candidates exist
    write_well_formed_document(tmp_repo, prose_file_count=5)
    stats = verify(tmp_repo, strict=True, collect_stats=True)
    assert stats.prose_files_scanned == 5
```

The third test is the load-bearing one and MUST be present for **any** check
whose clean-pass state is emptiness: an "empty output = pass" check without
a companion assertion that the scan actually touched a non-trivial candidate
set is not distinguishable, by its own output, from a check that scanned
nothing.

**General procedure for adding any new check:**

1. Write the fixture that violates the guarded condition first.
2. Prove the check fails against it (this is the check's proof of life).
3. Write the fixture that satisfies the guarded condition.
4. Prove the check passes against it.
5. If the check's pass state is "no findings," add a scan-engagement
   assertion (step 3's fixture, but asserting the scanned-count/considered
   -count is non-zero) as a distinct, third test.
6. Only then is the check allowed to gate CI.

### 9.2 No silent test weakening

**The incident.** During v1 maintenance, tests were modified to accommodate
implementation changes and continued passing while covering strictly less
than before — an assertion loosened, a fixture simplified, a case quietly
dropped, with no record that anything had been given up (`PROPOSAL.md`
§3.6, §12.7).

**The rule.** Any diff that alters a test's fixtures, mocks, or assertions
MUST state, in the PR description, whether test coverage was **preserved**,
**reduced with justification**, or **increased**. "Reduced" requires a
named reason (e.g. "behaviour X was intentionally removed in this PR, see
ADR-00NN") — it may never be the unstated side effect of making a test pass
again. Mutation testing on the affected module (§7) MUST be re-run and MUST
NOT show a new surviving mutant that the prior test configuration would have
killed; if it does, the reduction is real regardless of what the PR
description claims, and the PR is blocked.

**Reviewer checklist — apply to every PR touching `tests/`:**

- [ ] Does this diff change an assertion's operator or strength (e.g. `==`
  weakened to `in`, an exact match weakened to a substring or a `startswith`,
  a specific exception type weakened to `Exception`, a specific error kind
  weakened to "any error")?
- [ ] Does this diff change fixture data in a way that removes a case
  previously exercised (fewer generated examples, a smaller outline, a
  shorter fault schedule, a `hypothesis` strategy narrowed)?
- [ ] Does this diff delete a test? If so, is there a replacement covering
  the same behaviour, or an explicit, named reason the behaviour no longer
  needs coverage (not merely "it was flaky")?
- [ ] Does this diff comment out, `xfail`, or `skip` a previously-enforced
  assertion without a linked issue and a removal date?
- [ ] Does the PR description explicitly state "coverage preserved" /
  "coverage reduced because ___" / "coverage increased"? A test-touching PR
  with no such statement MUST be sent back, not approved on the assumption
  that silence means preservation.
- [ ] If coverage is claimed reduced-with-justification, was mutation
  testing (§7) re-run on the affected mandatory module, and does the ledger
  (§7.3) show no new unexplained survivor?
- [ ] If this diff touches a *check* (as opposed to a domain test), does
  §9.1's proof-of-failure companion test still exist and still pass?

A PR that fails any checked item is not landable regardless of green CI —
green CI is necessary and, per this whole section, explicitly **not
sufficient**.

---

## 10. Architectural fitness tests

### 10.1 The mandatory list

These run as ordinary pytest tests under `tests/fitness/`, and their failure
fails the build exactly like any other test failure — "architectural" is a
description of what they check, not a lesser enforcement tier.

1. `domain/` imports nothing from `adapters/`, `shell/`, or `app/`.
2. `domain/` imports no I/O-capable standard-library module: `os`, `io`,
   `pathlib`, `subprocess`, `socket`, `shutil`, `tempfile`, `datetime.now`
   (the module is allowed; the call is not — see the AST-based check below),
   `random` (unseeded), `time`.
3. Every `Protocol` under `ports/` has at least one real, one fake, and one
   faulty implementation registered under `adapters/real/`, `adapters/fake/`,
   `adapters/faulty/` respectively.
4. Every port listed in (3) has a contract suite under `tests/contract/`,
   and that suite is instantiated against every adapter found in (3) — real,
   fake, and the faulty adapter specifically **in its healthy mode**
   (`schedule=NONE`, §2.1, §3.2). A new adapter with no corresponding
   contract instantiation fails this check, not just a code review; a
   faulty-adapter instantiation that arms a fault schedule instead of `NONE`
   does not satisfy this rule.
5. No module in `domain/` exceeds a configured cyclomatic-complexity budget
   (value fixed in P0, recorded in `architecture/adr/`).
6. `mypy --strict` passes repository-wide; `domain/` additionally forbids
   `Any` anywhere in its own source (adapted from `PROPOSAL.md` §4.4).
7. **No single unit test (`tests/unit/`) exceeds its per-test budget of
   200 ms** — this per-test timeout, not a suite-total wall-clock number, is
   the enforced gate for the unit layer (§10.2's revised rationale explains
   why). The unit suite's **< 10 s** total remains a reported, non-blocking
   number tied to a named CI machine class (§10.2). The property suite's
   **< 60 s** and golden suite's **< 20 s** totals are unaffected by this
   change and remain enforced wall-clock gates.
8. Every `Plan`-shape fixture registered under `tests/fault/plans/` has a
   corresponding interruption test parametrized over its full boundary
   range (§5.2) — a use case that produces a new `Plan` shape with no
   matching interruption module fails this check. For any such `Plan` shape
   whose `external_effects` is non-empty, this additionally requires the
   file-phase/external-phase boundary test of §5.4 — a `Plan` shape with
   external effects and no matching phase-boundary test fails this check
   too, not merely the file-phase boundaries.
9. Every port in `PROPOSAL.md` §8's table exists with an ADR under
   `architecture/adr/` stating which justification (from source guidelines §6) it
   claims — an unjustified port is flagged, addressing risk R2.
10. Every member of `ConstructKind` (`domain/model/prose_facts.py`,
    `TYPES.md` §10) has BOTH a rendering rule under `domain/render/` AND a
    scanner rule in the real `ProseScannerPort` adapter. A `ConstructKind`
    with one and not the other fails this check. This is the mechanism that
    pins the prose scanner's vocabulary to the authoring macros — ADR-0001's
    open follow-up ("a new authoring construct requires a scanner rule in
    the same change — enforced by a fitness test") is only real once this
    rule exists here, not merely promised in the ADR.

### 10.2 An unenforced budget is a wish — and a wall-clock total is a flaky one

v1's suite did not become 13 minutes long in one commit. It grew there
gradually, one reasonable-looking end-to-end test at a time, because nothing
in the system ever measured the total and objected. By the time it mattered,
"the suite is slow" was an accepted fact of life rather than a regression
anyone could point at. A budget that lives only in a table in this document
(§1.1) or in `PROPOSAL.md` §12.1 is exactly as enforceable as v1's
undocumented expectation that tests should be fast — that is, not
enforceable at all.

**A wall-clock total gate on the unit suite (`assert elapsed < 10.0`) is the
wrong mechanism for the unit layer specifically, even though the underlying
property it stands for is real.** It is flaky by construction — CI machine
load, cold caches, and neighbor contention all move the number independent
of the code — and it is gameable in a way that destroys the exact property
it is a proxy for: adding worker parallelism drives wall-clock time down
while doing nothing to stop an individual test from doing real I/O or
sleeping for a second, which is what the budget was supposed to catch.

Rule 7 therefore replaces the wall-clock total, for the unit layer only,
with two mechanisms that do not have this problem:

1. **A per-test timeout is the enforced gate.** Every test under
   `tests/unit/` MUST complete within **200 ms**, checked per test (e.g. a
   `pytest` plugin failing any individual test that exceeds it), not summed.
   A per-test timeout is not defeated by parallelism — it catches the
   individual slow/blocking test directly, which is the actual defect this
   doctrine cares about, regardless of how many workers ran alongside it.
2. **The suite total is reported, not blocking, and tied to a named CI
   machine class.** CI prints the unit suite's total wall-clock time on its
   standard runner class every run, and a human reviews the trend; it does
   not fail the build on its own. This keeps the *visibility* v1 lacked
   (§10's whole point) without making the gate itself flaky.

**The real guarantee remains fitness test 2 — no I/O-capable import in
`domain/`.** The per-test timeout and the reported total are both proxies
for "the unit suite stays fast because nothing in it can be slow"; the
import-boundary fitness test is what actually *prevents* the condition that
would make a test slow in the first place (no filesystem, no subprocess, no
network, no unseeded sleep-inducing randomness), rather than merely
detecting its symptom after the fact. Keep both: the import check for
prevention, the per-test timeout for the case something slips through it
anyway (a slow pure computation, a `for` loop with a wrong bound), and the
reported total for early warning while it is still cheap to fix.

### 10.3 Worked fitness test examples

```python
# tests/fitness/test_core_has_no_io_imports.py
import ast
from pathlib import Path

FORBIDDEN_IMPORTS = {"os", "io", "pathlib", "subprocess", "socket", "shutil",
                      "tempfile", "random"}

def test_domain_imports_no_io_capable_module():
    violations = []
    for path in Path("ubeats/domain").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = _imported_module_names(node)
            hit = names & FORBIDDEN_IMPORTS
            if hit:
                violations.append((path, hit))
    assert not violations, f"I/O-capable imports found in domain/: {violations}"

def test_this_check_actually_detects_a_planted_violation(tmp_path, monkeypatch):
    # anti-vacuity companion, per §9.1: prove the AST scan can fail
    planted = tmp_path / "ubeats" / "domain" / "_planted_violation.py"
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text("import subprocess\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    violations = _scan_for_io_imports(Path("ubeats/domain"))
    assert violations, "the fitness check failed to detect a deliberately planted violation"
```

```python
# tests/fitness/test_every_port_has_three_adapters_and_a_contract.py
def test_every_port_has_real_fake_faulty_and_a_contract_suite():
    for port_name, protocol in discover_ports("ubeats/ports"):
        assert find_adapter("ubeats/adapters/real", port_name), f"{port_name}: no real adapter"
        assert find_adapter("ubeats/adapters/fake", port_name), f"{port_name}: no fake adapter"
        assert find_adapter("ubeats/adapters/faulty", port_name), f"{port_name}: no faulty adapter"
        contract = find_contract_suite("tests/contract", port_name)
        assert contract, f"{port_name}: no contract suite"
        assert contract.instantiated_against(("real", "fake", "faulty")), (
            f"{port_name}: contract suite not run against all three adapter kinds"
        )
```

```python
# tests/fitness/test_unit_suite_per_test_budget.py
# Enforced via pytest's --timeout=0.2 (per-test) on tests/unit/, or an
# equivalent plugin hook; sketched here as an explicit check for clarity.
def test_no_unit_test_exceeds_its_per_test_budget():
    per_test_elapsed = run_pytest_and_time_each_test(["tests/unit", "-q"])
    over_budget = {name: t for name, t in per_test_elapsed.items() if t >= 0.2}
    assert not over_budget, f"unit tests over the 200ms per-test budget: {over_budget}"

# tests/fitness/test_unit_suite_total_reported.py
# NON-BLOCKING: reports the total on the named CI machine class; never
# fails the build by itself (§10.2).
def test_unit_suite_total_is_reported(ci_machine_class):
    elapsed = run_pytest_and_time(["tests/unit", "-q"])
    report_metric("unit_suite_total_seconds", elapsed, machine_class=ci_machine_class)
```

The second and third examples MUST themselves have a proof-of-failure
companion per §9.1: a test that registers a port with a missing faulty
adapter, or a fixture suite that deliberately overruns the budget, and
asserts the fitness check flags it. Skipping that companion for a fitness
test is the same defect as skipping it for any other check.

---

## 11. Test naming, organization, and determinism

### 11.1 Layout and naming

Directory layout mirrors `PROPOSAL.md` §6.1's `tests/` tree exactly:
`unit/`, `contract/`, `property/`, `golden/`, `integration/`, `e2e/`,
`fitness/`, plus `tests/fault/` for §3–§5. Mirror the package structure
within each: `tests/unit/domain/outline/test_move.py` tests
`ubeats/domain/outline/move.py`.

Test names state the unit under test, the condition, and the expected
outcome, in that order, so a failing test name alone (as it appears in a CI
log with no further context) tells a reader what broke:

```text
test_outline_move__into_own_descendant__is_rejected
test_apply__interrupted_before_third_write__leaves_pre_state
test_filesystem_contract__read_after_write__returns_written_bytes
test_publication_gate__watermarked_translation__rejects_with_translation_reason
```

Prefer this over names that restate the implementation (`test_move_1`,
`test_move_edge_case`) — a property or unit test's name should be readable
as a specification sentence.

### 11.2 Determinism controls

Adapted from source guidelines §40, applied concretely:

- **No wall-clock.** No test, at any layer below `e2e/`, may call
  `datetime.now()`, `time.time()`, or equivalent. Time enters the domain
  only via `ClockPort`; tests inject `FrozenClock(instant)` or, where
  time progression matters, `JumpingClock(sequence)` — both are fake
  adapters with their own contract suite (§2) alongside the real clock
  adapter.
- **No network.** Nothing below `tests/integration/` and `tests/e2e/` may
  open a socket, including to `localhost`. This MUST be enforced, not
  merely documented — e.g. via a network-blocking fixture or plugin applied
  autouse to `tests/unit/`, `tests/property/`, `tests/golden/`,
  `tests/contract/`, and `tests/fault/`. **The specific mechanism (a
  dedicated plugin vs. a hand-rolled `monkeypatch.setattr(socket, "socket",
  ...)` autouse fixture) is an open decision**, recorded alongside the
  mutation-testing tool choice in §7.2's ADR.
- **No ordering dependence.** Tests MUST NOT rely on execution order or
  shared mutable module-level state. CI runs the suite with randomized test
  order (a fixed, logged seed per run) specifically to surface hidden
  coupling; a test that only passes in file-declaration order is a defect,
  not a false alarm.
- **No unseeded randomness.** `random` and hypothesis both require explicit,
  logged seeds. A CI run's seed MUST be printed in its output and MUST be
  re-usable to reproduce a failure locally (`pytest --randomly-seed=NNNN`
  or equivalent for whatever ordering tool is chosen; `hypothesis` already
  prints a reproducing seed and `@example` on failure).
- **No unstable generated identifiers in observable output.** Anything a
  golden test or a serialization round-trip test observes MUST NOT contain
  a freshly generated UUID, a PID, a hostname, or similar — if an identifier
  is needed, it comes from `ClockPort`/an injected id generator that tests
  control.

### 11.3 Seeds and regression persistence

A hypothesis failure prints a minimal counterexample and a seed. The seed
alone is not sufficient for a durable regression fixture, because a local
`.hypothesis/` example database is not guaranteed to exist on the next
machine that runs the suite (a fresh CI runner, a different contributor).
**The counterexample MUST be promoted into the test file as an explicit
`@example(...)`**, committed, so the regression is permanent and
machine-independent:

```python
@given(outline=outline_strategy(), facts=prose_facts_strategy())
@example(outline=OUTLINE_WITH_DEEPLY_NESTED_SINGLE_CHILD_CHAIN,
         facts=EMPTY_PROSE_FACTS)  # found by CI run 2026-xx-xx, see issue #NNN
def test_render_is_total(outline, facts):
    render(document_with(outline), facts)   # must not raise
```

The same discipline applies to fault schedules discovered by a fuzzing
campaign (§3, §6): a schedule that broke an invariant MUST be committed as a
literal fixture under `tests/fault/regressions/<short-description>.json` and
loaded by a dedicated regression test, not left to a random-schedule
generator to rediscover by chance.

---

## 12. What CI runs, and when

### 12.1 Per-commit (local pre-commit hook and/or pre-push; fast loop)

- `tests/unit/` (per-test 200 ms gate enforced; ~10 s total reported, non-blocking — §10.2)
- `tests/property/` (< 60 s)
- `tests/golden/` (< 20 s)
- `tests/fitness/` import-boundary and per-test-budget checks
- `mypy --strict` on changed files at minimum (full run if it stays fast
  enough to keep this loop under roughly two minutes total)

This loop MUST stay fast enough that a contributor runs it before every
push without being tempted to skip it. If it grows past a couple of minutes,
that is itself a fitness-test violation of the same kind as §10.2 warns
against, and must be addressed (parallelization, narrower change-scoped
runs), not silently tolerated.

### 12.2 Pre-landing (PR merge gate; blocking; target well under the sum of
the layer budgets in §1.1, since layers run in parallel)

Everything in §12.1, at full (non-change-scoped) settings, plus:

- `tests/contract/` — every port, every adapter (real + fake + faulty
  -healthy)
- `tests/fault/` — faulty adapters with schedules armed, fault-propagation
  tests (§4), interruption tests (§5) for every registered `Plan` shape
- `tests/integration/` — real Typst, real PDF inspection, real git
- `tests/e2e/` — a curated smoke set: at least one exercise of every CLI
  verb group from `PROPOSAL.md` §10.1, and at least one crash-and-restart
  scenario; the *full* E2E campaign runs nightly (§12.3), not on every PR,
  to keep this gate tractable
- diff-scoped mutation testing (§7) on any touched file under
  `domain/rules/`, `domain/lifecycle/`, `domain/planning/`, with the ledger
  (§7.3) checked for unexplained new survivors
- the §9.1 anti-vacuity requirement (any new or changed check has its
  proof-of-failure companion) and the §9.2 checklist, enforced as part of
  required review for any PR touching `tests/`
- golden-diff justification per §8.3 (the `domain/render/` ↔ golden
  co-change requirement)

**This gate blocks merge.** All of the above MUST be green, `mypy --strict`
MUST be green, and the §9.2 checklist MUST be explicitly completed for any
test-touching PR. There is no "merge with a known-red pre-landing check and
fix later" path.

### 12.3 Nightly / scheduled (does not block an individual landing; blocks
the next release/cutover milestone if red)

- the **full** E2E campaign: every documented CLI workflow, the full
  crash/kill/restart matrix, all six document classes in both locales
- the **full**, non-diff-scoped mutation testing sweep across all of
  `domain/rules/`, `domain/lifecycle/`, `domain/planning/`, with the ledger
  updated
- extended property and fuzzing campaigns: hypothesis run with a
  substantially larger example count and longer per-test deadline than the
  pre-landing default
- destructive real-infrastructure testing, adapted from source guidelines §27:
  killing the process mid-persistence, corrupting a model file on disk,
  denying filesystem permissions, exhausting disk capacity in a sandboxed
  environment, terminating a subprocess mid-compile, restarting `ubeats`
  between operations, running against an older on-disk schema version
- the **parity oracle** (`PROPOSAL.md` §15.2) against the full reference
  corpus, from phase P4 onward
- `ubeats doctor` / dependency-lock verification
- if applicable, a re-run of the golden suite against any newly pinned
  Typst version, to surface risk R4 before it reaches a release

**A nightly failure MUST be triaged the same day it is observed** and
either fixed forward or explicitly waived with a named owner and a recorded
reason — silently letting a nightly stay red is exactly the failure mode
§9's rules exist to prevent, only at a different cadence. A red nightly
blocks any release or cutover milestone (`PROPOSAL.md` §15.1's phase exit
criteria, §15.2's parity oracle) until resolved.

### 12.4 Summary — what blocks a landing

A PR merges only when, together:

1. every §12.1 and §12.2 check is green;
2. `mypy --strict` is green, with `domain/` additionally `Any`-free;
3. every fitness test in §10.1 is green;
4. no check introduced or modified by the PR is vacuous (§9.1's
   proof-of-failure companion exists and passes);
5. if the PR touches `tests/`, the §9.2 checklist is completed in the PR
   description and mutation testing confirms no unexplained coverage
   reduction on mandatory modules;
6. any golden diff is accompanied by a `domain/render/` diff or an updated
   `.intent.md`, per §8.3.

Green CI is necessary. Per §9.2, it is explicitly not sufficient on its own
— the checklist and the mutation-testing confirmation are independent gates
that a merely-green run does not satisfy by itself.

---

## Appendix — Revision log

| Rev | Change |
|---|---|
| 1 | Initial testing doctrine: layers, contract suites, fault schedules, fault propagation, interruption testing, property/mutation/MC/DC, golden tests, anti-vacuity rules, fitness tests, naming/determinism, CI schedule |
| 2 | Fixed the `FaultSchedule.NONE` class definition, which did not import as written — `NONE` moved to a module-level constant (§3.2); retired the incompatible keyword-argument `FaultSchedule(fail_write=3)` form wherever it appeared (canonical structured form only); scoped §5's interruption invariant to `file_effects` and corrected it to permit a recoverable hybrid-with-journal state before recovery runs, requiring pre-or-post-state only after (§5.1–§5.2), and added §5.3 for `external_effects`' weaker, unjournaled guarantee (ADR-0002); rewrote §2.2's contract-suite example onto the frozen `FileSystemPort` vocabulary and added the previously unpublished `probe`/`PathFacts` contract cases, including "probe reports writable, write then fails" (§2.2); added the preflight-window-race fault-schedule case to the `FileSystemPort` fault table (§3.4); replaced the unit suite's flaky, gameable wall-clock total gate with an enforced per-test 200 ms timeout plus a reported, non-blocking total tied to a named CI machine class, keeping the no-I/O-imports fitness test as the real guarantee (§1.1, §10.1 rule 7, §10.2, §10.3, §12.1); demoted §8.3's "large enough to plausibly justify" bulk-regeneration check from an implied CI heuristic to an explicit review rule; replaced `GateRejection` with `DomainError` (§7.4); updated `render()` signature references to `render(doc, facts) -> RenderedTree`, total, throughout; added the `source guidelines §N` / `Doctrine §N` citation convention to the header and fixed two line-wrapped citations it had missed on first pass. |
| 3 | *(No entry.)* This document was not touched in revision 3 of the document set; the row is kept so the gap between 2 and 4 is explicit rather than silent. |
| 4 | Propagated the ADR-0001 "prose facts, not `Document`" decision into the three places revision 2 claimed but did not actually fix: §7.4's publication-gate signature is now `publication_gate(doc, facts)` with `no_placeholders(facts)` (MC/DC table re-verified valid — the four-condition shape is unchanged); §6 property 14 now holds `facts` constant alongside `doc` across repeated gate evaluation; §11.3's regression-persistence example now calls `render(document_with(outline), facts)`, two arguments. Rewrote §2.2's contract-suite example to stop violating its own frozen-vocabulary docstring: `RelPath` throughout (no `pathlib` import — `ARCHITECTURE.md` §1, `TYPES.md` §2), `PathFacts` assertions corrected to the real fields (`kind: PathKind`, `writable`, `read_only_attr`, `is_reparse_point` — there is no `exists`), missing-path assertions corrected from `DomainError`'s `NotFound` to `InfrastructureError`'s `PortFailure` (`FileSystemPort` never returns a `DomainError`), and §2.3's `atomic_replace` corrected to `write_atomic`; also corrected §2.3's own `NotFound`-on-missing-path bullet to the same `PortFailure` vocabulary for consistency. Rewrote §3.3 and §4.2's `InfrastructureError.PortFailure`/`.ContractViolation` nested-class-style access as flat-union `isinstance` checks against imported variants (`TYPES.md` §13.1 rejects nested classes). Added the `ProseScannerPort` column to §3.4's fault catalogue (ADR-0001 names fault injection over the scanner as a justification for the port; the catalogue could not honor that claim without a column), covering misses-a-construct, reports-a-phantom-construct, stale-`content_digest`, and fails-to-classify faults. Added §10.1 rule 10: every `ConstructKind` has both a rendering rule and a scanner rule, mechanically checked — the fitness test that makes ADR-0001's open follow-up a real, enforced rule rather than a promise. Added §5.4: the file-phase/external-phase boundary (after the journal is removed, before the first external effect runs) — a shape distinct from both §5.2 (no journal to consult; the file phase is unconditionally done) and §5.3 (zero external effects have run, so "partial completion" must report as zero-completed, not unknown); wired into §10.1 rule 8's coverage check for any `Plan` shape with non-empty `external_effects`. |
| 5 | Final coherence sweep. The status line stated no revision number at all despite this log's existing rows — added "Revision 5" and filled the previously silent gap at revision 3 (row above) so the log is contiguous. Cross-references, FM-NN and ADR citations, terminology, and absolute-claim language checked against the rest of the set; no other content changes. |
