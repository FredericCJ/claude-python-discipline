"""Integration: the real adapter against a real directory, and the whole pipeline.

**Oracle: the real technology's observed behaviour** (`TEST-004`). The contract
suite already says what a store must do; this layer exists to confirm that the
filesystem actually does it, and to run the destructive path end to end against
files that really exist.

`EFCT-006` gets its assertion here: the dry run reports exactly what the apply
then does, because it *is* the apply's own plan and not a prediction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from refpkg.adapters.clock.fake import FakeClock
from refpkg.adapters.files.real import LocalFileStore
from refpkg.domain.model import SECONDS_PER_DAY, Instant, Policy
from refpkg.shell.cli import EXIT_OK, run
from refpkg.shell.composition import Wiring

# Keep the temporary-directory path type out of the runtime integration suite.
if TYPE_CHECKING:
    from pathlib import Path

## Far enough past any age limit here that mtime rounding cannot change a verdict.
NOW: Instant = Instant(100 * SECONDS_PER_DAY)


def seed(root: Path) -> None:
    """Put three files on disk with mtimes old enough to be stale.

    @param root the directory to seed
    @par Effects
    Writes each named file and resets its access and modification timestamps.
    """
    import os  # ruff: ignore[import-outside-top-level] - setting an mtime is the point of this helper

    # Materialize each fixture filename in stable lexical order.
    for name in ("a.log", "b.log", "c.log"):
        # Resolve the current file beneath the isolated integration root.
        target = root / name
        # Write deterministic content before pinning the observable timestamps.
        target.write_bytes(b"xxxx")
        os.utime(target, (1, 1))


def test_the_real_store_lists_what_was_written(tmp_path: Path) -> None:
    """The adapter reports the files that are actually there.

    @param tmp_path a real directory
    """
    # Materialize the fixture and inspect it through the real bounded adapter.
    seed(tmp_path)
    store = LocalFileStore(tmp_path)
    # Project each entry to a cross-platform bare name while preserving store order.
    assert [entry.path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
            for entry in store.entries()] == ["a.log", "b.log", "c.log"]


def test_a_dry_run_changes_nothing_on_disk(tmp_path: Path) -> None:
    """`EFCT-005`: the default for a destructive command changes nothing.

    @param tmp_path a real directory
    """
    # Execute the dry path over real files with a deterministic clock.
    seed(tmp_path)
    wiring = Wiring(store=LocalFileStore(tmp_path), clock=FakeClock(NOW))
    code, payload = run(wiring, Policy.parse(1, 0), apply_it=False)
    assert code == EXIT_OK
    assert payload["applied"] is False
    assert len(list(tmp_path.iterdir())) == 3


def test_the_dry_run_predicts_the_apply_exactly(tmp_path: Path) -> None:
    """`EFCT-006`: the dry run is the pipeline truncated, not a second path.

    Run the survey twice against the same directory -- once stopping, once
    applying -- and the set of doomed paths must be identical. It is, by
    construction, because both come from the same `survey` call shape.

    @param tmp_path a real directory
    """
    # Run the same composed pipeline once without effects and once with effects.
    seed(tmp_path)
    # Capture the dry-run payload before the shared store state is changed.
    dry = run(Wiring(store=LocalFileStore(tmp_path), clock=FakeClock(NOW)),
              Policy.parse(1, 1), apply_it=False)[1]

    # Capture the applied payload produced from the same policy and directory facts.
    wet = run(Wiring(store=LocalFileStore(tmp_path), clock=FakeClock(NOW)),
              Policy.parse(1, 1), apply_it=True)[1]

    assert dry["doomed"] == wet["doomed"]
    assert wet["deleted"] == wet["doomed"]
    assert len(list(tmp_path.iterdir())) == 1
