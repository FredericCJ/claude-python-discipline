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

# Import annotation-only protocols without adding runtime dependencies.
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
            Each element is one declared import-root path; declaration order is preserved.
        """
        # Render every offending source-root path in declaration order for the refusal.
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
    # Resolve the repository-local import-linter configuration selected by the caller.
    configuration = root / config
    # Refuse an absent contract declaration before import-linter can report vacuous success.
    if not configuration.is_file():
        # Missing policy is a configuration defect, never a clean architecture verdict.
        raise FileNotFoundError(configuration)

    # Preserve declared import-root path elements in caller order, defaulting to `src`.
    sources = tuple(source_roots or (Path("src"),))
    # Canonicalize the repository boundary once for every confinement decision.
    exact_root = root.resolve()
    # Resolve each source-root element against the canonical boundary in declaration order.
    resolved_sources = tuple((exact_root / source).resolve() for source in sources)
    # Refuse the complete set when any resolved source path escapes the repository boundary.
    if any(not source.is_relative_to(exact_root) for source in resolved_sources):
        # Report the authored roots together so the unsafe declaration can be repaired in place.
        raise SourceRootError(exact_root, sources)
    # Map each evicted module-name key to its live module-object value; key order is unused.
    evicted: dict[str, ModuleType] = {}
    # Snapshot import-path string elements in their current resolution order for restoration.
    previous_path = list(sys.path)
    # Snapshot the process working directory so the temporary import context is reversible.
    previous_directory = Path.cwd()
    # Prepend resolved roots in reverse so their final search precedence matches declaration.
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
        # Restore the caller's exact import search path after modules and cwd are restored.
        sys.path[:] = previous_path

    # Preserve each broken contract-name element in import-linter result order.
    broken = [contract.name for contract, outcome in results if not outcome.kept]
    # Report explicit contract failures before considering the non-vacuity floor.
    if broken:
        # Format broken contract names in their evaluation order for one diagnostic line.
        listed = "; ".join(broken)
        # Return a broken verdict with every failed contract named for remediation.
        return EXIT_BROKEN, f"import contracts: {len(broken)} broken -- {listed}"
    # Refuse a vacuous run when fewer contracts were evaluated than the declared floor.
    if len(results) < minimum:
        # Return a broken verdict because too few evaluated contracts cannot prove conformance.
        return EXIT_BROKEN, (
            f"import contracts: only {len(results)} contract(s) evaluated, below "
            f"the {minimum} this tree declares. A configuration that resolves no "
            f"package reports nothing broken, which is not the same as passing."
        )
    # Return success only after the declared non-vacuity floor and every contract pass.
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
    # Normalize a single root-package string to the same iterable contract as many roots.
    if isinstance(roots, str):
        # Preserve the sole root-package value as one ordered iterable element.
        values: Iterable[object] = (roots,)
    # Reuse a caller-supplied iterable when it already represents multiple root packages.
    elif isinstance(roots, Iterable):
        # Preserve root-package elements in caller iteration order.
        values = roots
    else:
        # Represent malformed root metadata as an empty ordered element sequence.
        values = ()
    # Convert every root-package element to its canonical import-name string in order.
    names = tuple(str(name) for name in values)
    # Map matching module-name keys to live module-object values for restoration, preserving
    # the interpreter cache's iteration order.
    evicted: dict[str, ModuleType] = {
        # Retain the current module-name key and object value when any configured root owns it.
        name: module for name, module in sys.modules.items()
        # Match both the root package itself and every dotted descendant module.
        if any(name == root or name.startswith(f"{root}.") for root in names)
    }
    # Remove captured governed modules so import-linter resolves them from the selected roots.
    for name in evicted:
        # Delete the current cached module while its object remains recoverable in `evicted`.
        del sys.modules[name]
    # Return the complete restoration mapping to the guarded import context.
    return evicted


def vendored() -> bool:
    """Whether this copy is a vendored `.agent/` rather than the upstream checkout.

    `tools/` ships whole, so an adopter gets this script *and* the reference
    package it defaults to. Running it there without saying so would hold the
    contracts against the shipped reference and report green about a package the
    adopter did not write -- a false pass, which is worse than no check.

    @return True when this file sits inside a vendored install
    """
    # Report whether this tool is executing from an installed `.agent` bundle.
    return REPO_ROOT.name == ".agent"


def main(argv: list[str] | None = None) -> int:
    """Run the contracts and report.

    @param argv the command line, or None to read `sys.argv`
    @return the process exit status
    """
    # Configure the command-line parser that defines this tool's invocation contract.
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
    # Parse the governed root and import-contract declaration before boundary analysis.
    arguments = parser.parse_args(argv)

    # Preserve whether the caller explicitly selected an adopter root before default resolution.
    root = arguments.root
    # Require an explicit target root when invoked from a vendored discipline installation.
    if root is None:
        # Refuse implicit target selection inside a vendored installation.
        if vendored():
            print("import contracts: this is a vendored install, so the default "
                  "target would be the shipped reference package rather than "
                  "your code. Pass --root pointing at the tree holding your "
                  "src/ and an importlinter.toml naming your packages.",
                  file=sys.stderr)
            # Fail closed instead of accidentally analyzing the package's shipped reference tree.
            return EXIT_BROKEN
        root = DEFAULT_ROOT

    # Localize configuration and source-root failures into stable import-gate diagnostics.
    try:
        # Evaluate contracts once and retain the status/message pair for terminal publication.
        status, line = check(
            root,
            arguments.config,
            arguments.minimum,
            arguments.source_roots,
        )
    # Preserve the missing configuration path carried by the filesystem refusal.
    except FileNotFoundError as absent:
        print(f"import contracts: no configuration at {absent}", file=sys.stderr)
        # A missing contract declaration cannot yield a meaningful architecture verdict.
        return EXIT_BROKEN
    # Preserve the confinement refusal that names every escaping source root.
    except SourceRootError as problem:
        print(f"import contracts: invalid target: {problem}", file=sys.stderr)
        # Refuse roots that escape the selected repository boundary.
        return EXIT_BROKEN
    print(line, file=sys.stderr if status else sys.stdout)
    # Preserve the contract check's success or broken-architecture verdict at the CLI boundary.
    return status


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    # Translate import-contract failure into the status consumed by automation.
    raise SystemExit(main())
