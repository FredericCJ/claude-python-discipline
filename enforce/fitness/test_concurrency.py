"""Concurrency arrives with stated semantics, or it does not arrive.

**Oracle: contract.** `law/EFCT` held against a project tree.

* `EFCT-013`, `EFCT-014` -- concurrency is introduced only with stated semantics,
  and shared mutable state is guarded by a stated lock order
* `EFCT-015` -- writer exclusion is enforced; contention is a result

**These are conditional rules, and that is not a loophole.** A program with no
concurrency satisfies them completely, because there is nothing to state
semantics about -- `EFCT-016` says outright to prefer the sequential design. What
the rules forbid is *introducing* concurrency without saying what it guarantees.
So the tests fire only when the package reaches for a concurrency primitive, and
the reference package deliberately does not: its `README` names concurrency among
the things it has no positive case for.

The negative cases below therefore add concurrency to a copy and assert the check
would then demand the statement. Without them these tests would pass on the
reference and prove nothing whatsoever.

    pytest enforce/fitness/test_concurrency.py
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, Final

from decides import decides
from fixtures import broken_copy, package_root, reference_root

if TYPE_CHECKING:
    from pathlib import Path

## Modules whose presence means concurrency has been introduced.
PRIMITIVES: Final[frozenset[str]] = frozenset({
    "threading", "multiprocessing", "asyncio", "concurrent", "queue", "sched",
})

## Vocabulary a module must use once it has reached for one of those, per
## `EFCT-013` and `EFCT-014`. Stating the semantics is the requirement; achieving
## any particular one is the author's business.
_SEMANTICS = re.compile(
    r"(lock order|thread[- ]safe|not thread[- ]safe|single[- ]writer|exclusive"
    r"|serialis|serializ|happens[- ]before|guarded by|mutual exclusion|race)",
    re.IGNORECASE,
)

## Evidence that contention is reported rather than waited out. `EFCT-015` asks
## for a *result*: a caller that loses a race is told so, not blocked until the
## winner finishes and then handed a stale answer.
_CONTENTION = re.compile(r"(contention|already held|would block|busy|conflict"
                         r"|timeout|try_?lock|acquire\(.*False)", re.IGNORECASE)


def concurrent_modules(package: Path) -> dict[Path, set[str]]:
    """Every module that reaches for a concurrency primitive.

    @param package the package directory
    @return each offending module against the primitives it imports
    """
    found: dict[Path, set[str]] = {}
    for module in sorted(package.rglob("*.py")):
        if "__pycache__" in module.parts:
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        reached: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                reached |= {a.name.split(".", 1)[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                reached.add(node.module.split(".", 1)[0])
        overlap = reached & PRIMITIVES
        if overlap:
            found[module] = overlap
    return found


# ------------------------------------------------------- EFCT-013 / EFCT-014


@decides("EFCT-013", "EFCT-014")
def test_concurrency_documented() -> None:
    """EFCT-013, EFCT-014: a module using a primitive states what it guarantees.

    Vacuous on the reference by design, and the test below is what stops that
    from being a free pass.
    """
    package = package_root(reference_root())
    for module, primitives in concurrent_modules(package).items():
        text = module.read_text(encoding="utf-8")
        assert _SEMANTICS.search(text), (
            f"{module.name} imports {', '.join(sorted(primitives))} and states no "
            f"semantics. Concurrency without a stated lock order is a race "
            f"nobody has agreed to."
        )


def test_the_reference_introduces_no_concurrency() -> None:
    """The precondition, asserted rather than assumed.

    If this ever fails, the two tests either side of it stopped being vacuous and
    started being real -- which is fine, but it should be noticed rather than
    discovered.
    """
    assert concurrent_modules(package_root(reference_root())) == {}


def test_undocumented_concurrency_is_caught(tmp_path: Path) -> None:
    """The negative case, and the reason these tests are not a free pass.

    @param tmp_path the fixture directory
    """
    root = broken_copy(tmp_path, write={
        "src/refpkg/adapters/files/pooled.py":
            '"""A store that shares state across threads and says nothing."""\n\n'
            'import threading\n\n\nclass PooledStore:\n'
            '    """Shares a dictionary."""\n\n'
            '    def __init__(self):\n        """Build it."""\n'
            '        self._entries = {}\n',
    })
    offending = concurrent_modules(package_root(root))
    assert offending, "the fixture did not introduce concurrency"
    for module in offending:
        assert not _SEMANTICS.search(module.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ EFCT-015


@decides("EFCT-015")
def test_single_writer() -> None:
    """EFCT-015: where there is exclusion, losing the race is a result.

    A writer that blocks until the lock frees hands its caller a stale view and
    calls it success. Contention is information, and the caller is the only one
    who can decide what to do with it.
    """
    package = package_root(reference_root())
    for module in concurrent_modules(package):
        text = module.read_text(encoding="utf-8")
        assert _CONTENTION.search(text), (
            f"{module.name} introduces concurrency and never reports contention. "
            f"A caller that loses a race must be told, not blocked and then "
            f"handed a stale answer."
        )


def test_a_writer_that_blocks_silently_is_caught(tmp_path: Path) -> None:
    """The negative case for `EFCT-015`.

    @param tmp_path the fixture directory
    """
    root = broken_copy(tmp_path, write={
        "src/refpkg/adapters/files/locked.py":
            '"""A store that is thread-safe and blocks."""\n\n'
            'import threading\n\n\nclass LockedStore:\n'
            '    """Thread-safe by a lock order of one."""\n\n'
            '    def __init__(self):\n        """Build it."""\n'
            '        self._lock = threading.Lock()\n',
    })
    module = package_root(root) / "adapters" / "files" / "locked.py"
    text = module.read_text(encoding="utf-8")
    assert _SEMANTICS.search(text), "the fixture should state semantics"
    assert not _CONTENTION.search(text), "the fixture should not report contention"
