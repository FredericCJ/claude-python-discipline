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

## Layers permitted to import a third-party package. `ARCH-004` corners each
## dependency in one adapter; `DEP-002` is the same claim read as a question
## about position rather than about count.
MAY_DEPEND: Final[frozenset[str]] = frozenset({"adapters", "shell"})

## Modules that ship with Python and so are not dependencies to position.
STDLIB: Final[frozenset[str]] = frozenset(sys.stdlib_module_names)


def imports_of(path: Path) -> set[str]:
    """Every root module a file imports.

    @param path the module to read
    @return the top-level names imported
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".", 1)[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".", 1)[0])
    return found


# ------------------------------------------------------- DEP-005 / DEP-006


@decides("DEP-005", "DEP-006")
def test_environment_locked() -> None:
    """DEP-005, DEP-006: the environment is pinned, and something checks it.

    A lock nobody compares against is a comment. The verifier is run for real
    here rather than merely required to exist, because "the file is present" is
    exactly the standard this corpus refuses everywhere else.
    """
    assert ENVIRONMENT.is_file(), "no environment declaration; nothing is locked"
    assert VERIFIER.is_file(), "no verifier; the lock is a comment"

    finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv, no shell
        (sys.executable, str(VERIFIER), "--quiet"),
        cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=120,
    )
    assert finished.returncode == 0, (
        f"the running interpreter does not match the lock:\n{finished.stderr[-600:]}"
    )


def test_the_lock_pins_exact_versions() -> None:
    """DEP-005: a range is not a lock.

    Read through the verifier's own parser, so this test and the check cannot
    disagree about what counts as pinned.
    """
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import check_env  # ruff: ignore[import-outside-top-level] - imported here so the path insert applies

    python, pins, loose, _ = check_env.read_pins(ENVIRONMENT)
    assert python, "the interpreter itself is unpinned"
    assert pins, "the declaration pins no package"
    assert loose == [], f"unpinned requirement(s): {'; '.join(loose)}"


def test_the_verifier_can_fail(tmp_path: Path) -> None:
    """FLOW-007: drift is observed being caught, not assumed to be.

    @param tmp_path the fixture directory
    """
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import check_env  # ruff: ignore[import-outside-top-level] - imported here so the path insert applies

    drifted = tmp_path / "environment.yml"
    drifted.write_text(
        "dependencies:\n  - pip:\n      - a-package-that-is-not-installed==1.0\n",
        encoding="utf-8",
    )
    assert check_env.main(["--file", str(drifted)]) == 1


# ------------------------------------------------------------------- DEP-002


@decides("DEP-002")
def test_dependency_position() -> None:
    """DEP-002: a dependency is judged by where it sits, not by whether it is good.

    The core may import the standard library and itself. Anything else belongs to
    an adapter, where its blast radius is one module and its failure modes have
    an owner.
    """
    root = reference_root()
    package = package_root(root)
    own = package.name

    for module in sorted(package.rglob("*.py")):
        if "__pycache__" in module.parts:
            continue
        layer = next((p for p in module.parts if p in {"domain", "app", "ports",
                                                       "adapters", "shell"}), "unknown")
        if layer in MAY_DEPEND:
            continue
        foreign = {
            name for name in imports_of(module)
            if name not in STDLIB and name != own and not name.startswith("_")
        }
        assert not foreign, (
            f"{layer}/{module.name} imports {', '.join(sorted(foreign))}, which is "
            f"neither the standard library nor this package. A dependency "
            f"reachable from the core has no single owner."
        )
