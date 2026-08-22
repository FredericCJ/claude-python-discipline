"""Decide `law/ARCH`'s layering contracts by running import-linter.

Several `ARCH-*` rules retain an external import-linter strategy: the rule names
a mechanism, and the mechanism is a configured tool rather than a check written
here. Until this file existed the tool ran nowhere, so five binding rules were
decided by a config file nobody executed.

**Why this is a script and not a gate entry pointing at `lint-imports`.** The
console script is the only working entry point -- `python -m importlinter.cli`
imports the module, finds no `__main__` guard, and exits 0 having checked
nothing. A gate step invoking it that way would have passed every run, forever,
while reporting success. The console script itself lives in `Scripts/` on Windows
and `bin/` elsewhere and is not reachable from `sys.executable`, so the gate
cannot name it portably. Calling the API directly is the only invocation that is
both portable and observably doing something.

**The vacuity guard is the point.** `MINIMUM_CONTRACTS` fails the step when the
configuration yields fewer contracts than the fixture is known to declare. A
config whose `root_packages` no longer resolve produces zero contracts and a
report that says "0 broken", which reads exactly like success. That is the same
defect in a different costume, and this is what refuses it.

    python tools/import_gate.py
    python tools/import_gate.py --config path/to/importlinter.toml --root path
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import ModuleType

## The repository root, one level up from `tools/`.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent

## The tree the contracts are held against. The reference fixture is the only
## `src/` layout in this repository; without it these rules have no subject.
DEFAULT_ROOT: Final = REPO_ROOT / "enforce" / "fixtures" / "reference"

## The contract file, relative to the root above.
DEFAULT_CONFIG: Final = "importlinter.toml"

## How many contracts the configuration must yield before a "0 broken" verdict is
## believed. The reference declares nine; a run producing fewer has stopped
## seeing the package rather than started agreeing with it.
##
## It was seven until v3.1, when writing discrimination mutations for the eight
## rules tagged `auto:import-linter` found that four of them were named by no
## contract at all. `EFCT-001` and `DEP-001` now have one each. `API-004` and
## `EFCT-012` still do not: both are about a private persistent representation,
## and the reference has no separate raw-storage module to corner.
MINIMUM_CONTRACTS: Final = 9

## Exit status when every contract holds.
EXIT_OK: Final = 0

## Exit status when a contract is broken, or when too few were evaluated to
## believe the verdict.
EXIT_BROKEN: Final = 1


class SourceRootError(ValueError):
    """A configured import root would read outside the governed repository."""

    def __init__(self, root: Path, sources: Sequence[Path]) -> None:
        """Name the refused root and values in one actionable diagnostic.

        @param root governed repository root
        @param sources configured repository-relative values
        """
        values = ", ".join(str(source) for source in sources)
        super().__init__(f"source roots escape {root}: {values}")


def check(
    root: Path,
    config: str,
    minimum: int,
    source_roots: Sequence[Path] | None = None,
) -> tuple[int, str]:
    """Run every contract in `config` against the package rooted at `root`.

    import-linter resolves `root_packages` by import, so `root/src` must be on
    the path and the configuration path must be resolvable from the working
    directory. Both are set here and restored afterwards, because a gate step
    that leaves `sys.path` mutated changes what the steps after it see.

    @param root the directory holding `src/` and the contract file
    @param config the contract file's name, relative to `root`
    @param minimum how many contracts must be evaluated for the verdict to count
    @param source_roots repository-relative import roots, or src when omitted
    @return the exit status, and the line to print
    @throws FileNotFoundError when the contract file is absent, because a missing
        config is the one case where reporting "nothing broken" would be a lie
    """
    configuration = root / config
    if not configuration.is_file():
        raise FileNotFoundError(configuration)

    sources = tuple(source_roots or (Path("src"),))
    exact_root = root.resolve()
    resolved_sources = tuple((exact_root / source).resolve() for source in sources)
    if any(not source.is_relative_to(exact_root) for source in resolved_sources):
        raise SourceRootError(exact_root, sources)
    evicted: dict[str, ModuleType] = {}
    previous_path = list(sys.path)
    previous_directory = Path.cwd()
    for source in reversed(resolved_sources):
        sys.path.insert(0, str(source))
    os.chdir(root)
    try:
        # A private name, deliberately. import-linter exposes no public way to
        # register the built-in contract types, and `create_report` does not do
        # it for itself -- the console script is the only caller that does. The
        # alternative is reimplementing the registry here, which would drift.
        # If this name disappears in a later version the import raises and every
        # test in tools/test_toolchain_gates.py fails at once, which is a
        # louder failure than the silence this file exists to prevent.
        from importlinter.application.use_cases import (  # ruff: ignore[import-outside-top-level]
            _register_contract_types,  # ruff: ignore[import-private-name]
            create_report,
            read_user_options,
        )
        from importlinter.configuration import (  # ruff: ignore[import-outside-top-level]
            configure,
        )

        # Two steps the console script performs before dispatching, and which
        # `create_report` does not do for itself. Without `configure()` the
        # settings registry is empty and `read_user_options` raises KeyError on
        # USER_OPTION_READERS; without the type registration every contract
        # raises NoSuchContractType. Both are at least loud, unlike the silent
        # success `python -m importlinter.cli` produces.
        configure()  # type: ignore[no-untyped-call]  # private untyped tool API
        options = read_user_options(config_filename=config)
        _register_contract_types(options)
        evicted = _evict(options.session_options.get("root_packages", ()))
        report = create_report(options)
        results = list(report.get_contracts_and_checks())
    finally:
        sys.modules.update(evicted)
        os.chdir(previous_directory)
        sys.path[:] = previous_path

    broken = [contract.name for contract, outcome in results if not outcome.kept]
    if broken:
        listed = "; ".join(broken)
        return EXIT_BROKEN, f"import contracts: {len(broken)} broken -- {listed}"
    if len(results) < minimum:
        return EXIT_BROKEN, (
            f"import contracts: only {len(results)} contract(s) evaluated, below "
            f"the {minimum} this tree declares. A configuration that resolves no "
            f"package reports nothing broken, which is not the same as passing."
        )
    return EXIT_OK, f"import contracts: {len(results)} kept, 0 broken"


def _evict(roots: object) -> dict[str, ModuleType]:
    """Remove the named packages from `sys.modules`, returning what was removed.

    import-linter builds its graph by importing the root packages, and an import
    is satisfied from `sys.modules` before the path is consulted. So a caller who
    has already imported the package -- another test in the same session, most
    obviously -- gets a graph of the tree imported *first*, whatever `--root`
    said. That failure is silent and directional: pointed at a broken copy, the
    contracts come back kept.

    Found by exactly that route. `test_a_broken_layer_is_caught` passed alone and
    failed in the full suite, because `enforce/fitness/test_diagnostics.py`
    imports `refpkg` to build a real error. Under `pytest-randomly` it would have
    been an intermittent pass -- which `TEST-018` calls a defect in the harness,
    and this one was a defect in the subject.

    @param roots the root package names from the contract configuration
    @return each evicted module name against the module object, for restoring
    """
    if isinstance(roots, str):
        values: Iterable[object] = (roots,)
    elif isinstance(roots, Iterable):
        values = roots
    else:
        values = ()
    names = tuple(str(name) for name in values)
    evicted: dict[str, ModuleType] = {
        name: module for name, module in sys.modules.items()
        if any(name == root or name.startswith(f"{root}.") for root in names)
    }
    for name in evicted:
        del sys.modules[name]
    return evicted


def vendored() -> bool:
    """Whether this copy is a vendored `.agent/` rather than the upstream checkout.

    `tools/` ships whole, so an adopter gets this script *and* the reference
    package it defaults to. Running it there without saying so would hold the
    contracts against the shipped reference and report green about a package the
    adopter did not write -- a false pass, which is worse than no check.

    @return True when this file sits inside a vendored install
    """
    return REPO_ROOT.name == ".agent"


def main(argv: list[str] | None = None) -> int:
    """Run the contracts and report.

    @param argv the command line, or None to read `sys.argv`
    @return the process exit status
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=None,
                        help="the tree holding src/ and the contract file")
    parser.add_argument("--config", default=DEFAULT_CONFIG,
                        help="the contract file, relative to --root")
    parser.add_argument("--minimum", type=int, default=MINIMUM_CONTRACTS,
                        help="how many contracts must be evaluated")
    parser.add_argument(
        "--source-root",
        action="append",
        type=Path,
        dest="source_roots",
        help="repository-relative import root; repeat for multiple roots",
    )
    arguments = parser.parse_args(argv)

    root = arguments.root
    if root is None:
        if vendored():
            print("import contracts: this is a vendored install, so the default "
                  "target would be the shipped reference package rather than "
                  "your code. Pass --root pointing at the tree holding your "
                  "src/ and an importlinter.toml naming your packages.",
                  file=sys.stderr)
            return EXIT_BROKEN
        root = DEFAULT_ROOT

    try:
        status, line = check(
            root,
            arguments.config,
            arguments.minimum,
            arguments.source_roots,
        )
    except FileNotFoundError as absent:
        print(f"import contracts: no configuration at {absent}", file=sys.stderr)
        return EXIT_BROKEN
    except SourceRootError as problem:
        print(f"import contracts: invalid target: {problem}", file=sys.stderr)
        return EXIT_BROKEN
    print(line, file=sys.stderr if status else sys.stdout)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
