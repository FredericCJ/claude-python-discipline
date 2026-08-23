"""Run every AST check in one pass.

    python -m checks src/
    python -m checks src/ --root .

`__init__.py` has documented this command since the checks were written, and
until v1.1.0 it did not exist: `python -m checks` failed with "'checks' is a
package and cannot be directly executed". Each check was still runnable on its
own, so the gap cost nothing except that the one command a consuming project's
gate would actually want was the one that was not there.

Discovery is by import rather than by a list, so a check added to this package is
run by this command without anyone remembering to register it. A registry is one
more thing to forget, and forgetting it here means a mechanism that exists and
never runs -- which reads exactly like a mechanism that passes.

Exit status is 1 if any check found anything, 0 otherwise, so this is usable as a
single gate step.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import pkgutil
import sys
from pathlib import Path

from . import Check, Finding, describe


def discover() -> list[Check]:
    """Instantiate every check defined in this package.

    A module that fails to import is a defect worth stopping for, not one to skip
    quietly: a check that cannot load is a rule nothing decides, and the whole
    point of this command is that the set is complete.

    @return check-instance elements ordered by unique check name
    @throws ImportError when a check module cannot be imported
    """
    # Map each discovered check-name key to its sole concrete instance value; insertion order
    # is deliberately ignored because the returned sequence is sorted explicitly.
    found: dict[str, Check] = {}
    # Resolve this package module so discovery uses its actual import path.
    package = sys.modules[__package__ or "checks"]
    # Inspect each immediate child-module element in discovery order.
    for info in pkgutil.iter_modules(package.__path__):
        # Infrastructure and test modules do not define aggregate production mechanisms.
        if info.name.startswith(("__", "test_")):
            # Advance without importing modules outside the checker discovery contract.
            continue
        # Import the candidate module so concrete subclasses become inspectable.
        module = importlib.import_module(f"{__package__ or 'checks'}.{info.name}")
        # Inspect each class member pair in deterministic name order.
        for _, member in inspect.getmembers(module, inspect.isclass):
            # Retain only concrete checks defined by this exact module.
            if (issubclass(member, Check) and member is not Check
                    and not inspect.isabstract(member)
                    and member.__module__ == module.__name__):
                # Instantiate and index the mechanism under its stable unique name.
                found[member.name] = member()
    # Return instance elements sorted by stable mechanism-name key.
    return [found[name] for name in sorted(found)]


def main(argv: list[str] | None = None) -> int:
    """Run every check over the given paths and report as one result.

    @param argv argument-string elements in caller order, or None to read ``sys.argv``
    @return 0 when no check found anything, 1 when any did

    @par Effects
    Reads command-line and project state, imports every checker module, mutates each check's
    declaration, reads governed inputs, and prints findings plus one summary in that order.
    """
    # Build the aggregate command-line grammar from the package description.
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--project",
        type=Path,
        help="the governed repository's own nearest pyproject.toml",
    )
    # Parse caller-supplied arguments or the process argument vector.
    args = parser.parse_args(argv)
    # Choose the first explicit path or display root as declaration-discovery probe.
    probe = args.paths[0] if args.paths else args.root
    # Load and announce the declaration governing every discovered check.
    declaration = describe(probe, args.project)
    # Select explicit path elements, then declared roots, then the conventional fallback.
    paths = args.paths or list(declaration.source_paths()) or [Path("src")]

    # Discover concrete check-instance elements in stable mechanism-name order.
    checks = discover()
    # Accumulate finding elements in check then file traversal order.
    findings: list[Finding] = []
    # Execute each check-instance element in stable mechanism order.
    for check in checks:
        # Publish the one announced declaration before the mechanism reads inputs.
        check.declaration = declaration
        # Run the mechanism across the common caller-selected path sequence.
        found = check.run(paths)
        # Extend the aggregate while preserving this mechanism's finding order.
        findings.extend(found)
        # Print each newly found element before advancing to the next mechanism.
        for finding in found:
            # Render paths relative to the requested display root where possible.
            print(finding.render(args.root))

    # Build sorted unique rule-id elements across every discovered mechanism.
    decided = sorted({rule for check in checks for rule in check.rules})
    # Print the non-vacuous aggregate count and complete decided-rule sequence.
    print(
        f"\n{len(checks)} check(s): {len(findings)} finding(s) "
        f"[{', '.join(decided)}]"
    )
    # Translate aggregate finding presence into the stable two-state process result.
    return 1 if findings else 0


# Execute the aggregate runner only when invoked as the package entry point.
if __name__ == "__main__":
    # Translate the aggregate result into the process exit status.
    raise SystemExit(main())
