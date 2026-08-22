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

    @return one instance per concrete `Check` subclass, ordered by check name
    @throws ImportError when a check module cannot be imported
    """
    found: dict[str, Check] = {}
    package = sys.modules[__package__ or "checks"]
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith(("__", "test_")):
            continue
        module = importlib.import_module(f"{__package__ or 'checks'}.{info.name}")
        for _, member in inspect.getmembers(module, inspect.isclass):
            if (issubclass(member, Check) and member is not Check
                    and not inspect.isabstract(member)
                    and member.__module__ == module.__name__):
                found[member.name] = member()
    return [found[name] for name in sorted(found)]


def main(argv: list[str] | None = None) -> int:
    """Run every check over the given paths and report as one result.

    @param argv command-line arguments, or None to read `sys.argv`
    @return 0 when no check found anything, 1 when any did
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--project",
        type=Path,
        help="the governed repository's own nearest pyproject.toml",
    )
    args = parser.parse_args(argv)
    probe = args.paths[0] if args.paths else args.root
    declaration = describe(probe, args.project)
    paths = args.paths or list(declaration.source_paths()) or [Path("src")]

    checks = discover()
    findings: list[Finding] = []
    for check in checks:
        check.declaration = declaration
        found = check.run(paths)
        findings.extend(found)
        for finding in found:
            print(finding.render(args.root))

    decided = sorted({rule for check in checks for rule in check.rules})
    print(
        f"\n{len(checks)} check(s): {len(findings)} finding(s) "
        f"[{', '.join(decided)}]"
    )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
