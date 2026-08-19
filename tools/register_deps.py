"""Derive the dependency register, because an empty one passes forever.

`ARCH-004` says each foreign dependency is imported in exactly one module, and it
is decided by an import-linter contract. That contract ships in
`enforce/importlinter.toml` with:

    forbidden_modules = [
        # e.g. "httpx", "sqlalchemy", "pydantic"
        # ... An empty list means no foreign dependency has been registered yet.
    ]

**An empty forbidden list always passes.** Two rules -- `ARCH-004` and `DEP-002`
-- were counted as decided on the strength of a contract that forbids nothing, in
the file every adopter copies. The comment made the vacuity look deliberate, which
is worse than an oversight: a reader who noticed the emptiness would have found a
sentence telling them it was fine.

This derives the register instead of asking for it. It walks a package, finds every
third-party import and the module that holds it, and reports which adapter owns
each dependency. `--check` fails when a tree has foreign imports and the register
does not name them -- **fail closed**, because the whole defect being fixed here is
a check that passed by having nothing to say.

    python tools/register_deps.py --root enforce/fixtures/reference
    python tools/register_deps.py --root PATH --check
    python tools/register_deps.py --root PATH --emit        # the contract body
"""

from __future__ import annotations

import argparse
import ast
import sys
import tomllib
from collections import defaultdict
from pathlib import Path
from typing import Final

## The repository root, one level up from `tools/`.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent

## Modules that ship with Python, and so are not dependencies to position.
STDLIB: Final[frozenset[str]] = frozenset(sys.stdlib_module_names)

## Import roots that are never a project's own foreign dependency: tooling that
## only ever appears in test or build code, and the private-name convention.
IGNORED: Final[frozenset[str]] = frozenset({"pytest", "hypothesis", "_pytest"})

## Exit status when the register is complete, or when nothing needed registering.
EXIT_OK: Final = 0

## Exit status when a tree has foreign imports the register does not name.
EXIT_INCOMPLETE: Final = 1


def packages_of(root: Path) -> list[Path]:
    """Every package under `<root>/src`.

    All of them, not one. The first version of this took the single package and
    returned nothing when there were several -- so a four-package tree with
    pydantic in all four of its domains reported "no foreign dependency is
    imported", which is the exact shape of silent nothing this file exists to
    remove. It was caught by pointing the tool at real code within a minute of
    writing it.

    @param root the tree holding `src/`
    @return the package directories, empty when there is no `src/` at all
    """
    source = root / "src"
    if not source.is_dir():
        return []
    return [p for p in sorted(source.iterdir())
            if p.is_dir() and (p / "__init__.py").exists()]


def imports_of(path: Path) -> set[str]:
    """Every root module one file imports.

    @param path the module to read
    @return the top-level names it brings in, relative imports excluded
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".", 1)[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".", 1)[0])
    return found


def survey(root: Path) -> dict[str, set[str]]:
    """Every foreign dependency, against the package modules that import it.

    A dependency reachable from more than one module is exactly what `ARCH-004`
    forbids, so the mapping is reported rather than reduced: the caller needs to
    see the second importer, not be told the count is wrong.

    @param root the tree holding `src/`
    @return each third-party root against the dotted module names importing it
    """
    packages = packages_of(root)
    own = {package.name for package in packages}
    holders: dict[str, set[str]] = defaultdict(set)
    for package in packages:
        for module in sorted(package.rglob("*.py")):
            if "__pycache__" in module.parts:
                continue
            dotted = ".".join(module.relative_to(package.parent)
                              .with_suffix("").parts).removesuffix(".__init__")
            for name in imports_of(module):
                if (name in STDLIB or name in own or name in IGNORED
                        or name.startswith("_")):
                    continue
                holders[name].add(dotted)
    return dict(holders)


def registered(config: Path) -> set[str]:
    """Which dependencies the contract file already names as forbidden.

    @param config the import-linter configuration
    @return every module named in any contract's `forbidden_modules`
    """
    if not config.is_file():
        return set()
    document = tomllib.loads(config.read_text(encoding="utf-8"))
    contracts = document.get("tool", {}).get("importlinter", {}).get("contracts", [])
    named: set[str] = set()
    for contract in contracts:
        named |= {str(m).split(".", 1)[0] for m in contract.get("forbidden_modules", [])}
    return named


def emit(holders: dict[str, set[str]]) -> str:
    """The register, as the contract body an adopter pastes in.

    Each dependency is listed with the module that owns it, so the pairing
    `DEP-002` asks for is visible in the file rather than held in someone's head.

    @param holders each dependency against its importers
    @return the `forbidden_modules` body, with an owner comment per entry
    """
    if not holders:
        return "forbidden_modules = []  # nothing foreign is imported at all"
    lines = ["forbidden_modules = ["]
    for name in sorted(holders):
        owners = sorted(holders[name])
        note = owners[0] if len(owners) == 1 else f"SHARED by {', '.join(owners)}"
        lines.append(f'    "{name}",  # owned by {note}')
    lines.append("]")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Survey a tree and report, emit or check its dependency register.

    @param argv the command line, or None to read `sys.argv`
    @return the process exit status
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path,
                        default=REPO_ROOT / "enforce" / "fixtures" / "reference",
                        help="the tree holding src/")
    parser.add_argument("--config", type=Path,
                        help="the contract file to check against; defaults to "
                             "importlinter.toml beside --root")
    parser.add_argument("--emit", action="store_true",
                        help="print the contract body and exit")
    parser.add_argument("--check", action="store_true",
                        help="fail when a foreign import is unregistered")
    arguments = parser.parse_args(argv)

    holders = survey(arguments.root)

    if arguments.emit:
        print(emit(holders))
        return EXIT_OK

    config = arguments.config or (arguments.root / "importlinter.toml")
    known = registered(config)
    missing = sorted(set(holders) - known)

    for name in sorted(holders):
        owners = sorted(holders[name])
        mark = "ok " if name in known else "NOT REGISTERED"
        shared = "" if len(owners) == 1 else "  <- more than one importer"
        print(f"  {mark:15s} {name:18s} {', '.join(owners)}{shared}")
    if not holders:
        found = packages_of(arguments.root)
        if not found:
            print(f"  no package under {arguments.root / 'src'} -- nothing was "
                  f"examined, which is not the same as nothing being found",
                  file=sys.stderr)
            return EXIT_INCOMPLETE
        print(f"  no foreign dependency across {len(found)} package(s)")

    if arguments.check and missing:
        print(f"\n{len(missing)} foreign import(s) the register does not name: "
              f"{', '.join(missing)}.\nAn unregistered dependency is one the "
              f"ARCH-004 contract cannot forbid, and a contract with an empty "
              f"list passes forever.", file=sys.stderr)
        return EXIT_INCOMPLETE
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
