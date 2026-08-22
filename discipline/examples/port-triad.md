---
id: examples/port-triad
kind: meta
title: Contract Conformance Without a File Triad
tokens: 1211
load_when:
  - "how do i write a port"
  - "contract suite example"
  - "fault schedule example"
  - "fake adapter"
  - "faulty adapter"
decay: none
---

# Contract Conformance Without a File Triad

The filename is retained so old links resolve. The v3 physical triad it once taught is
retired by [ARCH-025]. v4 requires the three observations—real behavior, controlled state,
and scheduled failure—not three classes or filenames.

## Contract and representation

The canonical `architecture.json` owns operation inputs, outcomes, errors, ordering,
idempotency, concurrency, and timeout. `contract-conformance.json` joins that contract id
to its Python representation. This example chooses structural typing; `nominal` with an
abstract boundary and explicit inheritance is equally valid.

```python
from typing import Protocol


class FileStore(Protocol):
    """Read and replace whole files through typed outcomes."""

    def read(self, path: PurePath) -> Result[bytes, PortFailure]: ...

    def write(
        self, path: PurePath, data: bytes,
    ) -> Result[None, PortFailure]: ...
```

The boundary exists because the architecture model names filesystem representation and
failure translation as volatile decisions with concrete replacement scenarios. A generic
“may replace later” docstring is not evidence ([ARCH-021]).

## Implementations by capability

```python
class RealFileStore:
    """Translate the contract to the host filesystem."""


class ControlledFileStore:
    """Hold deterministic state and execute a replayable fault schedule."""
```

The controlled implementation supplies both v4 test capabilities. Splitting it into a
healthy fake and a faulty decorator is also valid when that makes ownership clearer.

```json
{
  "id": "file_store_port",
  "module": "package.ports.files",
  "symbol": "FileStore",
  "representation": "structural",
  "implementations": [
    {
      "id": "real_store",
      "module": "package.adapters.files.real",
      "symbol": "RealFileStore",
      "kind": "real",
      "capabilities": [],
      "parameter": "real"
    },
    {
      "id": "controlled_store",
      "module": "package.adapters.files.controlled",
      "symbol": "ControlledFileStore",
      "kind": "test",
      "capabilities": ["controllable", "scheduled_fault"],
      "parameter": "controlled"
    }
  ],
  "suite": "tests/contract/test_file_store.py"
}
```

The full schema also traces every operation success, declared error, ordering,
idempotency, concurrency, and timeout term to an exact test node. Only the last four may
carry an explicit non-applicability rationale; successful behavior and published failures
always need executable evidence ([TEST-020]).

## One suite, every implementation

```python
BUILDERS: tuple[tuple[str, Callable[[], FileStore]], ...] = (
    ("real", build_real_store),
    ("controlled", build_controlled_store),
)


@pytest.fixture(params=BUILDERS, ids=lambda item: item[0])
def store(request: pytest.FixtureRequest) -> FileStore:
    """A fresh implementation selected by the shared registry parameter."""
    _, build = request.param
    return build()


def test_written_bytes_read_back_identically(store: FileStore) -> None: ...


def test_absent_read_returns_the_published_failure(store: FileStore) -> None: ...
```

The registry checker proves that symbols, capability labels, suite paths, parameters, and
term traces are complete. It does not claim that a label makes a double deterministic or
that a test's assertion is a sound oracle. The project gate executes collection and the
suite; scheduled-fault discrimination and adversarial review own the semantic residual.

## Faults remain data

```python
@dataclass(frozen=True, slots=True)
class FaultRule:
    """One operation occurrence and the failure it must produce."""

    operation: str
    occurrence: tuple[int, ...]
    fault: PortFailure


@dataclass(frozen=True, slots=True)
class FaultSchedule:
    """Replayable failures applied against a per-run call counter."""

    rules: tuple[FaultRule, ...] = ()
```

A schedule can be serialized, replayed, shrunk, and attached to a diagnostic. A bespoke
`FailOnThirdWriteStore` cannot. An empty schedule is the healthy configuration in which
the controlled implementation runs through the shared contract suite; non-empty schedules
drive containment and interruption cases ([TEST-009], [TEST-012]).
