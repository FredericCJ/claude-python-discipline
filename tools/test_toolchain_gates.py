"""The two toolchain gate steps are observed failing, not assumed to work.

**Oracle: differential.** Each gate script is run against a tree deliberately
broken in one way, and the exit status compared against the clean run.

`FLOW-007` and `TEST-015` require every mechanism to have a companion that shows
it can fail. These two need it more than most. Both wrap a tool that *exits zero
when it checks nothing*:

* `python -m importlinter.cli lint-imports` imports the module, finds no
  `__main__` guard, prints nothing and returns 0. Wired into the gate directly it
  would have passed every run forever while reporting success.
* `mypy` pointed at a path it cannot resolve prints "Success: no issues found in
  0 source files" and returns 0. So does pyright, with `filesAnalyzed: 0`.

So each wrapper carries a vacuity guard, and the guards are what is tested here
alongside the real detection. A guard nobody has watched fire is a guard nobody
knows is wired up.

    pytest tools/test_toolchain_gates.py
"""

from __future__ import annotations

import importlib
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from pathlib import Path
from typing import Final

import pytest

import import_gate
import type_gate

## The reference package both gates are pointed at.
REFERENCE: Final = import_gate.DEFAULT_ROOT

## Directories never copied into a broken tree: build artefacts, and caches that
## could make a dropped module still importable.
_SKIP: Final[frozenset[str]] = frozenset({
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".hypothesis",
    ".import_linter_cache",
})


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A writable copy of the reference package.

    No teardown: `tmp_path` is per-test and pytest keeps the last few for
    inspection, which is what a reader wants after a negative case fails.

    @param tmp_path the per-test directory
    @return the copy's root
    """
    # Keep each destructive negative case inside its pytest-owned repository copy.
    destination = tmp_path / "reference"
    # Copy only authored fixture inputs; generated caches would make gate outcomes host-dependent.
    shutil.copytree(REFERENCE, destination,
                    ignore=shutil.ignore_patterns(*_SKIP))
    # Give the test the isolated repository root expected by each gate.
    return destination


# The import-contracts gate.


def test_contracts_hold_on_the_reference() -> None:
    """The positive case: the conformant tree keeps every contract.

    Asserted before the negative cases, because a gate that fails on correct code
    is not stricter, it is broken -- and every negative result below would then
    be meaningless.
    """
    # Establish both the machine verdict and human summary for the conformant control tree.
    status, line = import_gate.check(REFERENCE, import_gate.DEFAULT_CONFIG,
                                     import_gate.MINIMUM_CONTRACTS)
    assert status == import_gate.EXIT_OK, line
    assert "0 broken" in line


def test_a_broken_layer_is_caught(tree: Path) -> None:
    """`ARCH-001`: the domain importing an adapter breaks the layers contract.

    The single most important thing the contract says -- dependencies point
    inward -- driven by making them point outward.

    @param tree a writable copy of the reference

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Select the domain module whose new outward import violates the central layer contract.
    model = tree / "src" / "refpkg" / "domain" / "model.py"
    # Retain the immutable source representation consumed by subsequent analysis.
    text = model.read_text(encoding="utf-8")
    # Inject one adapter dependency while preserving all other reference behavior.
    model.write_text(
        text.replace("from __future__ import annotations",
                     "from __future__ import annotations\n\n"
                     "from refpkg.adapters.clock.real import SystemClock  # noqa", 1),
        encoding="utf-8",
    )
    # Capture the gate's verdict and diagnostic after the intentional architectural break.
    status, line = import_gate.check(tree, import_gate.DEFAULT_CONFIG,
                                     import_gate.MINIMUM_CONTRACTS)
    assert status == import_gate.EXIT_BROKEN, (
        f"the domain imports an adapter and the contracts still passed: {line}"
    )
    assert "broken" in line


def test_the_vacuity_guard_fires() -> None:
    """A verdict from too few contracts is refused rather than believed.

    The failure this prevents: a configuration whose `root_packages` stop
    resolving yields zero contracts and a report saying nothing is broken, which
    is indistinguishable from success at the exit status.
    """
    # Demand an impossible contract count so success can only indicate a vacuity defect.
    status, line = import_gate.check(REFERENCE, import_gate.DEFAULT_CONFIG,
                                     minimum=999)
    assert status == import_gate.EXIT_BROKEN
    assert "evaluated" in line


def test_a_missing_configuration_is_not_silence() -> None:
    """No contract file is a failure, not an empty pass."""
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(FileNotFoundError):
        import_gate.check(REFERENCE, "no-such-file.toml",
                          import_gate.MINIMUM_CONTRACTS)


def test_a_declared_nonstandard_source_root_is_used(tree: Path) -> None:
    """Import contracts resolve from the adopter's declared root, not only src.

    @param tree writable reference copy

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Move the package to a declared non-default root without changing its contents.
    (tree / "src").rename(tree / "code")

    # Evaluate the relocated package through the explicit source-root declaration.
    status, line = import_gate.check(
        tree,
        import_gate.DEFAULT_CONFIG,
        import_gate.MINIMUM_CONTRACTS,
        source_roots=(Path("code"),),
    )

    assert status == import_gate.EXIT_OK, line


def test_an_escaping_source_root_is_refused(tree: Path) -> None:
    """The import graph cannot borrow packages from a parent or sibling.

    @param tree writable reference copy
    """
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(import_gate.SourceRootError, match="escape"):
        import_gate.check(
            tree,
            import_gate.DEFAULT_CONFIG,
            import_gate.MINIMUM_CONTRACTS,
            source_roots=(Path(".."),),
        )


# The type gate.


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
def test_the_reference_is_clean(checker: str) -> None:
    """The positive case: both checkers pass over the whole package.

    @param checker which of the two is under test
    """
    # Select the real adapter named by this parameterized control case.
    runner = type_gate.run_mypy if checker == "mypy" else type_gate.run_pyright
    # Capture checker success, analyzed-file count, and diagnostic output together.
    passed, analysed, output = runner(REFERENCE)
    assert passed, f"{checker} reported findings on the reference:\n{output[-1500:]}"
    assert analysed >= type_gate.MINIMUM_FILES, (
        f"{checker} analysed only {analysed} file(s)"
    )


def test_an_untyped_definition_is_caught(tree: Path) -> None:
    """`TYPE-001`: strict mode rejects a function with no annotations.

    Run against mypy only. pyright provisions its own node on first use and takes
    an order of magnitude longer, so it is exercised by the positive case above
    and by the gate itself rather than a second time here.

    @param tree a writable copy of the reference

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Select a governed module so the new definition lies inside both checkers' census.
    model = tree / "src" / "refpkg" / "domain" / "model.py"
    # Append the smallest definition that strict typing must reject.
    model.write_text(
        model.read_text(encoding="utf-8")
        + '\n\ndef untyped(value):\n    """No annotations anywhere."""\n    return value\n',
        encoding="utf-8",
    )
    # Capture checker success, analyzed-file count, and diagnostic output together.
    passed, analysed, output = type_gate.run_mypy(tree)
    assert not passed, (
        f"mypy --strict accepted an unannotated function over {analysed} files; "
        f"strict mode is not actually in force"
    )
    assert "untyped" in output


def test_a_checker_that_examined_nothing_fails(tmp_path: Path) -> None:
    """The vacuity case: an empty tree must not read as a clean one.

    This is the whole reason `type_gate` exists as a wrapper. mypy over a package
    it cannot find exits 0 saying "no issues found in 0 source files", which at
    the exit status is exactly what success looks like.

    @param tmp_path the per-test directory

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Present a syntactically valid but source-empty layout to the wrapper's vacuity guard.
    (tmp_path / "src").mkdir()
    assert type_gate.main(["--root", str(tmp_path)]) == type_gate.EXIT_FAILED


# Both gates.


@pytest.mark.parametrize("module", [import_gate, type_gate],
                         ids=["import_gate", "type_gate"])
def test_a_vendored_copy_refuses_its_default(module: object,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """A vendored install must not report green about the shipped reference.

    `vendor.py::UPSTREAM` ships all of `tools/` and all of `enforce/`, so an
    adopter receives both scripts and the reference package they default to.
    Without this guard, `python .agent/tools/type_gate.py` in an adopter's
    repository passes -- having checked a package the adopter did not write. A
    false pass is worse than no check, because it is reported as evidence.

    @param module the gate script under test
    @param monkeypatch used to make the script believe it is vendored
    """
    monkeypatch.setattr(module, "vendored", lambda: True)
    assert module.main([]) != 0  # type: ignore[attr-defined]


@pytest.mark.parametrize("module", [import_gate, type_gate],
                         ids=["import_gate", "type_gate"])
def test_the_guard_does_not_fire_upstream(module: object) -> None:
    """...and the guard stays silent here, where the default is correct.

    The companion to the case above. A guard that fired everywhere would have
    passed that test while making both gate steps unrunnable.

    @param module the gate script under test
    """
    assert module.vendored() is False  # type: ignore[attr-defined]
    assert module.main([]) == 0  # type: ignore[attr-defined]


def _pytest_control(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run an isolated pytest control experiment.

    @param arguments pytest options and subjects
    @param cwd temporary experiment directory
    @return completed process with combined output available to the oracle
    """
    # Run a fresh pytest process so plugin behavior cannot be masked by this suite's state.
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        (sys.executable, "-m", "pytest", "-q", *arguments),
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=60,
    )


def test_pytest_timeout_terminates_a_slow_test(tmp_path: Path) -> None:
    """The real timeout plugin rejects a test beyond its finite budget.

    @param tmp_path isolated pytest project

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Name the isolated test module whose runtime deliberately exceeds the requested timeout.
    test = tmp_path / "test_slow.py"
    # Materialize a two-second test so the 50 ms timeout has a wide discrimination margin.
    test.write_text(
        "import time\n\n\ndef test_slow() -> None:\n    time.sleep(2)\n",
        encoding="utf-8",
    )
    # Preserve the external command representation and its observed completion outcome.
    finished = _pytest_control(
        "-p", "no:randomly", "--timeout=0.05", str(test), cwd=tmp_path,
    )
    # Combine the checker's captured diagnostic streams without losing emission text.
    output = finished.stdout + finished.stderr
    assert finished.returncode != 0
    assert "Timeout" in output or "timeout" in output


def test_pytest_socket_blocks_ambient_network(tmp_path: Path) -> None:
    """The real socket plugin rejects creation of an unapproved socket.

    @param tmp_path isolated pytest project

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Name the isolated test module that attempts the forbidden ambient capability.
    test = tmp_path / "test_network.py"
    # Materialize one direct socket construction for the plugin to intercept.
    test.write_text(
        "import socket\n\n\ndef test_network() -> None:\n    socket.socket()\n",
        encoding="utf-8",
    )
    # Preserve the external command representation and its observed completion outcome.
    finished = _pytest_control(
        "-p", "no:randomly", "--disable-socket", str(test), cwd=tmp_path,
    )
    # Combine the checker's captured diagnostic streams without losing emission text.
    output = finished.stdout + finished.stderr
    assert finished.returncode != 0
    assert "SocketBlockedError" in output


@pytest.mark.timeout(30)
def test_pytest_randomly_exposes_an_order_dependency(tmp_path: Path) -> None:
    """At least one bounded seed runs a consumer before its hidden producer.

    @param tmp_path isolated pytest project

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Use an external marker as the intentionally hidden dependency between two tests.
    marker = tmp_path / "produced"
    # Keep producer and consumer in one module so random ordering controls their sequence.
    test = tmp_path / "test_order.py"
    # Materialize a producer that creates the marker and a consumer that assumes it already exists.
    test.write_text(
        "from pathlib import Path\n\n"
        "MARKER = Path(__file__).with_name('produced')\n\n\n"
        "def test_producer() -> None:\n    MARKER.write_text('ready')\n\n\n"
        "def test_consumer() -> None:\n"
        "    assert MARKER.exists(), 'order dependency exposed'\n",
        encoding="utf-8",
    )
    # True means one bounded seed exposed the dependency; false means all tried orders concealed it.
    exposed = False
    # Probe a bounded deterministic seed set rather than relying on an ambient random seed.
    for seed in range(1, 11):
        # Reset cross-seed state so only the current ordering can satisfy the consumer.
        marker.unlink(missing_ok=True)
        # Preserve the external command representation and its observed completion outcome.
        finished = _pytest_control(
            f"--randomly-seed={seed}", "-p", "no:socket", str(test), cwd=tmp_path,
        )
        # Combine the checker's captured diagnostic streams without losing emission text.
        output = finished.stdout + finished.stderr
        # Enter the failure path only when the subprocess reports a nonzero status.
        if finished.returncode != 0 and "order dependency exposed" in output:
            # True means this seed exposed the dependency; false means no tried seed has exposed it.
            exposed = True
            # Stop the scan once the decisive match has been established.
            break
    assert exposed, "ten explicit randomized orders all concealed the dependency"


def test_a_stale_import_does_not_decide_the_verdict(tree: Path) -> None:
    """The graph comes from `--root`, not from whatever was imported first.

    A regression pin. import-linter resolves its root packages by import, and an
    import is served from `sys.modules` before the path is consulted -- so with
    `refpkg` already loaded from the real reference, a run against a broken copy
    came back "7 kept". Silent, directional, and a false pass.

    Importing `refpkg` here first is what makes this test the failing case for
    that defect rather than a restatement of `test_a_broken_layer_is_caught`.

    @param tree a writable copy of the reference

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    sys.path.insert(0, str(REFERENCE / "src"))
    importlib.import_module("refpkg.domain.model")

    assert "refpkg" in sys.modules, "the precondition this test rests on did not hold"

    # Select the copy's domain module while the clean upstream package remains import-cached.
    model = tree / "src" / "refpkg" / "domain" / "model.py"
    # Break only the copied module to discriminate root-based analysis from stale import reuse.
    model.write_text(
        model.read_text(encoding="utf-8").replace(
            "from __future__ import annotations",
            "from __future__ import annotations\n\n"
            "from refpkg.adapters.clock.real import SystemClock  # noqa", 1),
        encoding="utf-8",
    )
    # Capture the verdict that must be based on the requested tree despite the cached package.
    status, line = import_gate.check(tree, import_gate.DEFAULT_CONFIG,
                                     import_gate.MINIMUM_CONTRACTS)
    assert status == import_gate.EXIT_BROKEN, (
        f"the contracts were held against the already-imported reference rather "
        f"than the tree at --root: {line}"
    )
