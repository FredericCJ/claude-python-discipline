"""The environment is locked and verified, and every dependency has one owner.

**Oracle: contract.** `law/DEP` held against this repository and the reference.

* `DEP-005`, `DEP-006` -- the environment is locked, and a command verifies it
* `DEP-002` -- a dependency is judged by its architectural position

`DEP-005` and `DEP-006` were the two rules that made the case for the whole
environment lock: both were `[BINDING]` and both were decided by nothing, in a
repository whose generated output silently differed depending on what happened to
be installed. The lock exists now; this is what makes it a mechanism rather than
a file.

    pytest enforce/fitness/test_deps.py
"""

from __future__ import annotations

import ast
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from pathlib import Path
from typing import Final

from decides import decides
from fixtures import package_root, reference_root

## The repository root, three levels up from this file.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent.parent

## The declaration: which interpreter and which package versions this tree runs.
ENVIRONMENT: Final = REPO_ROOT / "environment.yml"

## The command that decides whether the declaration holds. Without it the lock is
## a comment, which is the distinction `DEP-006` exists to draw.
VERIFIER: Final = REPO_ROOT / "tools" / "check_env.py"

## Unordered layer-name elements permitted to import third-party packages.
## `ARCH-020` separately corners a technology in one adapter boundary.
MAY_DEPEND: Final[frozenset[str]] = frozenset({"adapters", "shell"})

## Unordered standard-library root-module-name elements exempt from positioning.
STDLIB: Final[frozenset[str]] = frozenset(sys.stdlib_module_names)


def imports_of(path: Path) -> set[str]:
    """Every root module a file imports.

    @param path the module to read
    @return unordered top-level imported-module-name elements
    """
    # Parse import declarations without importing or executing the inspected module.
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    # Accumulate unique root-module-name elements without ordering semantics.
    found: set[str] = set()
    # Visit every syntax node because imports may be nested below control flow.
    for node in ast.walk(tree):
        # Expand each direct import alias to its root package name.
        if isinstance(node, ast.Import):
            # Merge unique direct-import roots into the unordered dependency set.
            found |= {a.name.split(".", 1)[0] for a in node.names}
        # Accept only absolute from-imports with a concrete module identity.
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            # Add the imported absolute module's root package name.
            found.add(node.module.split(".", 1)[0])
    # Return the complete dependency-name set after AST traversal.
    return found


# ------------------------------------------------------- DEP-005 / DEP-006


@decides("DEP-005", "DEP-006")
def test_environment_locked(tmp_path: Path) -> None:
    """DEP-005, DEP-006: the environment is pinned, and something checks it.

    A lock nobody compares against is a comment. The verifier is run for real
    here rather than merely required to exist, because "the file is present" is
    exactly the standard this corpus refuses everywhere else.

    @param tmp_path holds a deliberately drifted declaration

    @par Effects
    Runs the environment verifier twice and writes one isolated drifted lock between
    the conformant and rejection observations.
    """
    # Establish both the durable lock and its executable verifier before invocation.
    assert ENVIRONMENT.is_file(), "no environment declaration; nothing is locked"
    assert VERIFIER.is_file(), "no verifier; the lock is a comment"

    # Run the real verifier against the active repository environment.
    finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv, no shell
        (sys.executable, str(VERIFIER), "--quiet"),
        cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=120,
    )
    # Require the supported active environment to satisfy its exact declaration.
    assert finished.returncode == 0, (
        f"the running interpreter does not match the lock:\n{finished.stderr[-600:]}"
    )
    # Materialize an impossible exact pin as the independent rejection subject.
    drifted = tmp_path / "environment.yml"
    drifted.write_text(
        "dependencies:\n  - pip:\n      - package-that-cannot-be-present==0.0.0\n",
        encoding="utf-8",
    )
    # Run the same verifier against only the deliberately drifted declaration.
    rejected = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        (sys.executable, str(VERIFIER), "--quiet", "--file", str(drifted)),
        cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=120,
    )
    # Require the verifier to distinguish the impossible lock from the control.
    assert rejected.returncode != 0, "the verifier accepted a deliberately drifted lock"


def test_the_lock_pins_exact_versions() -> None:
    """DEP-005: a range is not a lock.

    Read through the verifier's own parser, so this test and the check cannot
    disagree about what counts as pinned.
    @par Effects
    Prepends the repository tool directory to this test process's import search path.
    """
    # Make the repository-owned verifier module importable for its canonical parser.
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import check_env  # ruff: ignore[import-outside-top-level] - imported here so the path insert applies

    # Parse interpreter, exact-pin, and loose-requirement elements from the real lock.
    python, pins, loose, _ = check_env.read_pins(ENVIRONMENT)
    # Require an interpreter pin, package pins, and no range-shaped requirements.
    assert python, "the interpreter itself is unpinned"
    assert pins, "the declaration pins no package"
    assert loose == [], f"unpinned requirement(s): {'; '.join(loose)}"


def test_the_verifier_can_fail(tmp_path: Path) -> None:
    """FLOW-007: drift is observed being caught, not assumed to be.

    @param tmp_path the fixture directory

    @par Effects
    Prepends the tool import path and writes one isolated drifted environment file.
    """
    # Make the repository-owned verifier importable before constructing its subject.
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import check_env  # ruff: ignore[import-outside-top-level] - imported here so the path insert applies

    # Materialize a lock whose exact package cannot match the active environment.
    drifted = tmp_path / "environment.yml"
    drifted.write_text(
        "dependencies:\n  - pip:\n      - a-package-that-is-not-installed==1.0\n",
        encoding="utf-8",
    )
    # Require the public verifier boundary to reject the drifted declaration.
    assert check_env.main(["--file", str(drifted)]) == 1


# ------------------------------------------------------------------- DEP-002


@decides("DEP-002")
def test_dependency_position() -> None:
    """DEP-002: a dependency is judged by where it sits, not by whether it is good.

    The core may import the standard library and itself. Anything else belongs to
    an adapter, where its blast radius is one boundary and its failure modes have
    an owner.
    """
    # Resolve the single package identity used to distinguish local from foreign imports.
    root = reference_root()
    package = package_root(root)
    own = package.name

    # Inspect every Python module path in deterministic source-tree order.
    for module in sorted(package.rglob("*.py")):
        # Exclude interpreter cache paths from the authored dependency surface.
        if "__pycache__" in module.parts:
            # Advance to the next governed source module.
            continue
        # Derive the first architecture-layer element from the module path.
        layer = next((p for p in module.parts if p in {"domain", "app", "ports",
                                                       "adapters", "shell"}), "unknown")
        # Permit third-party imports at explicitly owned infrastructure boundaries.
        if layer in MAY_DEPEND:
            # Continue with the next module because placement is already acceptable.
            continue
        # Collect unordered foreign root-module-name elements reachable from core code.
        foreign = {
            name for name in imports_of(module)
            if name not in STDLIB and name != own and not name.startswith("_")
        }
        # Reject every dependency that is neither local nor standard library in the core.
        assert not foreign, (
            f"{layer}/{module.name} imports {', '.join(sorted(foreign))}, which is "
            f"neither the standard library nor this package. A dependency "
            f"reachable from the core has no single owner."
        )
