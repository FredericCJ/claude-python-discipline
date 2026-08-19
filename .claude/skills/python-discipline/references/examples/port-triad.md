---
id: examples/port-triad
kind: meta
title: A Port and Its Three Adapters
tokens: 1569
load_when:
  - "how do i write a port"
  - "contract suite example"
  - "fault schedule example"
  - "fake adapter"
  - "faulty adapter"
decay: none
---

# A Port and Its Three Adapters

The worked shape behind [ARCH-007] through [ARCH-009], [TEST-005] and [TEST-009]. Genericized
from a real project; the names are illustrative, the structure is not.

Four files. The port states the contract, three adapters implement it, and **one** suite runs
against all three. That last point is the whole design: the suite is the oracle, and an
adapter that passes it is substitutable by evidence rather than by assertion.

---

## The port

```python
"""The filesystem boundary the core is allowed to cross."""

from typing import Protocol


class FileSystemPort(Protocol):
    """Read and replace whole files, atomically with respect to other readers.

    Justification under ARCH-010: *controlling a specific effect*, and *fault
    injection* -- the core must be testable against a disk that fails.

    Ordering: `write` is not ordered against a concurrent `write` to the same
    path; callers needing that hold the writer lock (EFCT-015).
    Idempotency: `write` with identical bytes is indistinguishable from a no-op.
    """

    def read(self, path: PurePath) -> Result[bytes, PortFailure]:
        """Return a file's contents.

        @param path the file to read, which need not exist
        @return its bytes, or a failure naming why it could not be read
        """

    def write(self, path: PurePath, data: bytes) -> Result[None, PortFailure]:
        """Replace a file's contents by same-volume rename.

        Single-file-rename atomic: a reader sees the old bytes or the new ones,
        never a partial write. Says nothing about two files (see GLOSSARY).

        @param path the file to replace
        @param data the new contents
        @return nothing on success, or a failure naming the cause
        """
```

The contract states ordering, idempotency and the *qualified* atomicity claim. A port that
says only "writes a file" has published nothing a test can hold it to.

## The contract suite — written once, run three times

```python
"""The oracle for every FileSystemPort adapter (TEST-005)."""


class FileSystemPortContract:
    """Behaviour every adapter must exhibit. Subclasses supply the adapter.

    Not a base class for convenience: it is the published contract expressed as
    executable assertions, so "this adapter conforms" is a claim with evidence.
    """

    @pytest.fixture
    def port(self) -> FileSystemPort:
        """The adapter under test, supplied by the subclass.

        @return an adapter in its healthy configuration
        """
        raise NotImplementedError

    def test_a_written_file_reads_back_identically(self, port, tmp_path):
        """Round-trip: the strongest property, and the cheapest to state."""

    def test_reading_an_absent_file_fails_rather_than_raising(self, port, tmp_path):
        """An absent file is an expected outcome, so it travels the typed channel."""

    def test_a_failure_names_the_path_it_concerns(self, port, tmp_path):
        """DIAG-003: the offending value is an attribute, not prose."""
```

## The three adapters

```python
class RealFileSystem:
    """Talks to the actual disk."""

class FakeFileSystem:
    """An in-memory implementation of the same contract.

    Not a stub: it satisfies the contract suite unchanged. A fake that can drift
    from the real adapter without a test failing is worthless, and so is every
    unit test standing on it (TEST-006).
    """

class FaultyFileSystem:
    """The real adapter, driven by a fault schedule.

    In *healthy mode* -- an empty schedule -- it must pass the contract suite
    exactly as the real one does. That is what makes a fault test's failure
    attributable to the injected fault rather than to the harness.
    """
```

```python
# tests/contract/test_filesystem.py -- the suite, instantiated three times.
class TestRealFileSystem(FileSystemPortContract): ...
class TestFakeFileSystem(FileSystemPortContract): ...
class TestFaultyFileSystemHealthy(FileSystemPortContract): ...
```

## Faults as data, not as bespoke classes

```python
@dataclass(frozen=True, slots=True)
class FaultRule:
    """One injected failure, addressed by port, operation and occurrence."""

    ## Which port the rule applies to.
    port: str
    ## Which operation on it, e.g. "write".
    operation: str
    ## Which calls fail: 1-based, so (3,) means "the third write".
    occurrence: tuple[int, ...]
    ## What goes wrong -- explicit failure, timing, corruption, omission.
    fault: Fault


@dataclass(frozen=True, slots=True)
class FaultSchedule:
    """A replayable set of fault rules."""

    ## The rules, applied in order against a per-run call counter.
    rules: tuple[FaultRule, ...] = ()
```

```json
{"rules": [
  {"port": "filesystem", "operation": "write", "occurrence": [3],
   "fault": {"kind": "explicit_failure", "error": "DiskFull"}}
]}
```

**Why data.** A hand-written `FailOnThirdWriteStore` is a one-off: it cannot be serialized,
replayed, shrunk by a property test, or attached to a bug report. A schedule can. When a
generated case fails, the schedule *is* the reproduction — which is the difference between
a failure an agent can diagnose and one it can only re-run and hope for ([TEST-009]).

## What this buys

An interruption test becomes a loop over effect boundaries rather than a set of bespoke
mocks: for each *k*, run the plan with a schedule that fails at effect *k*, then assert the
repository is in the pre-state, the post-state, or a journal-recoverable hybrid — and never
an undetectable partial one ([EFCT-007], [TEST-012]).
