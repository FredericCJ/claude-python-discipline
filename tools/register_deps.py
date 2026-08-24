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
    # Resolve the conventional source root whose immediate packages form the survey boundary.
    source = root / "src"
    # Refuse the target when its declared source directory is absent.
    if not source.is_dir():
        # No source root means there are no owned packages to survey.
        return []
    # Retain initialized immediate child directories in lexical path order.
    return [p for p in sorted(source.iterdir())
            if p.is_dir() and (p / "__init__.py").exists()]


def imports_of(path: Path) -> set[str]:
    """Every root module one file imports.

    @param path the module to read
    @return the top-level names it brings in, relative imports excluded
    """
    # Parse imports without importing adopter code; invalid modules contribute no dependency facts.
    try:
        # Parse imports from the module without executing adopter code.
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        # Unreadable or invalid modules contribute no trustworthy import facts.
        return set()
    # Each found element is one unique top-level import-root string; set order is deliberately
    # unordered.
    found: set[str] = set()
    # Inspect every syntax node for absolute import declarations in AST traversal order.
    for node in ast.walk(tree):
        # Record every root named by an ordinary import statement.
        if isinstance(node, ast.Import):
            # Reduce dotted aliases to unique top-level dependency roots.
            found |= {a.name.split(".", 1)[0] for a in node.names}
        # Record only absolute from-import roots; relative imports stay inside the package.
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
    # Discover every initialized package below the selected source root.
    packages = packages_of(root)
    # Each own element is one project-owned top-level package name; set order is deliberately
    # unordered.
    own = {package.name for package in packages}
    # Map each foreign import-root key to an unordered set of dotted importer-module values;
    # dependency key order is deliberately irrelevant until reporting.
    holders: dict[str, set[str]] = defaultdict(set)
    # Traverse discovered packages in lexical directory order.
    for package in packages:
        # Traverse Python modules below the current package in lexical path order.
        for module in sorted(package.rglob("*.py")):
            # Exclude interpreter cache paths from source analysis.
            if "__pycache__" in module.parts:
                # Bytecode caches are derived artifacts, never importing owners.
                continue
            # Convert the module path to its dotted importer identity, collapsing package init.
            dotted = ".".join(module.relative_to(package.parent)
                              .with_suffix("").parts).removesuffix(".__init__")
            # Classify each unique imported root reported for the current module.
            for name in imports_of(module):
                # Exclude standard-library, project-owned, tooling, and private import roots.
                if (name in STDLIB or name in own or name in IGNORED
                        or name.startswith("_")):
                    # Only third-party roots belong in the dependency registration proposal.
                    continue
                holders[name].add(dotted)
    return dict(holders)


def registered(config: Path) -> set[str]:
    """Which dependencies the contract file already names as forbidden.

    @param config the import-linter configuration
    @return every module named in any contract's `forbidden_modules`
    """
    # An absent contract file registers no dependencies.
    if not config.is_file():
        # Missing policy cannot establish ownership for any foreign import root.
        return set()
    # Decode TOML schema keys to configuration values; mapping order is deliberately unused.
    document = tomllib.loads(config.read_text(encoding="utf-8"))
    # Select the declared import-linter contract sequence, defaulting to no contracts.
    contracts = document.get("tool", {}).get("importlinter", {}).get("contracts", [])
    # Each named element is one unique forbidden top-level module root; set order is deliberately
    # unordered.
    named: set[str] = set()
    # Inspect contracts in declaration order while reducing their names to an unordered set.
    for contract in contracts:
        # Add each contract's forbidden module root to the unordered registered-name set.
        named |= {str(m).split(".", 1)[0] for m in contract.get("forbidden_modules", [])}
    return named


def emit(holders: dict[str, set[str]]) -> str:
    """The register, as the contract body an adopter pastes in.

    Each dependency is listed with the module that owns it, so the pairing
    `DEP-002` asks for is visible in the file rather than held in someone's head.

    @param holders each dependency against its importers
        Each key is a foreign import root and each value is its unordered set of
        dotted importer-module names; dependency key order is deliberately unused.
    @return the `forbidden_modules` body, with an owner comment per entry
    """
    # Render an explicit non-vacuous empty register only when no foreign import exists.
    if not holders:
        # Keep the empty state reviewable instead of omitting the contract field.
        return "forbidden_modules = []  # nothing foreign is imported at all"
    # Each lines element is one output-line string; exact TOML emission order is preserved.
    lines = ["forbidden_modules = ["]
    # Emit dependencies in lexical name order for stable contract diffs.
    for name in sorted(holders):
        # Sort dotted importer values so ownership comments are reproducible.
        owners = sorted(holders[name])
        # Name the sole owner or make shared ownership explicit in the generated comment.
        note = owners[0] if len(owners) == 1 else f"SHARED by {', '.join(owners)}"
        lines.append(f'    "{name}",  # owned by {note}')
    lines.append("]")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Survey a tree and report, emit or check its dependency register.

    @param argv the command line, or None to read `sys.argv`
    @return the process exit status
    """
    # Configure the command-line parser that defines this tool's invocation contract.
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
    # Parse target and check/apply mode before surveying foreign imports.
    arguments = parser.parse_args(argv)

    # Survey the selected source tree before choosing report, emit, or check behavior.
    holders = survey(arguments.root)

    # Emit mode prints the derived contract body and performs no completeness comparison.
    if arguments.emit:
        print(emit(holders))
        # Emission is complete once the derived contract body reaches stdout.
        return EXIT_OK

    # Resolve an explicit contract path or the conventional file beside the source tree.
    config = arguments.config or (arguments.root / "importlinter.toml")
    # Load the unique foreign roots already named by any configured contract.
    known = registered(config)
    # Sort surveyed roots absent from the register for deterministic failure reporting.
    missing = sorted(set(holders) - known)

    # Report every surveyed dependency in lexical root-name order.
    for name in sorted(holders):
        # Sort importer-module values for deterministic ownership display.
        owners = sorted(holders[name])
        # Mark whether the dependency participates in any import-linter contract.
        mark = "ok " if name in known else "NOT REGISTERED"
        # Highlight multiple importers because ARCH-004 requires a single owner.
        shared = "" if len(owners) == 1 else "  <- more than one importer"
        print(f"  {mark:15s} {name:18s} {', '.join(owners)}{shared}")
    # Distinguish a genuinely dependency-free tree from a vacuous no-package scan.
    if not holders:
        # Reuse package discovery to establish that the empty survey examined real source.
        found = packages_of(arguments.root)
        # Fail closed when no package existed to examine.
        if not found:
            print(f"  no package under {arguments.root / 'src'} -- nothing was "
                  f"examined, which is not the same as nothing being found",
                  file=sys.stderr)
            # Reject the vacuous survey because no package was available to inspect.
            return EXIT_INCOMPLETE
        print(f"  no foreign dependency across {len(found)} package(s)")

    # Check mode rejects every surveyed dependency absent from the declared register.
    if arguments.check and missing:
        print(f"\n{len(missing)} foreign import(s) the register does not name: "
              f"{', '.join(missing)}.\nAn unregistered dependency is one the "
              f"ARCH-004 contract cannot forbid, and a contract with an empty "
              f"list passes forever.", file=sys.stderr)
        # Fail check mode until every observed foreign root has a declared contract owner.
        return EXIT_INCOMPLETE
    return EXIT_OK


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    # Surface unregistered dependency ownership as command failure.
    raise SystemExit(main())
