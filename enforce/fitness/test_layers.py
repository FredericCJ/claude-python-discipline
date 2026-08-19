"""Every test layer exists, is populated, and stays inside what it may touch.

**Oracle: contract.** `law/TEST`'s own table of layers, held against a project.

* `TEST-002`, `TEST-007`, `FLOW-010` -- each layer exists and has tests in it
* `TEST-001` -- the unit layer touches no external resource

An untested seam is not visibly untested: it looks exactly like a tested one
until it fails. That is the whole argument for `TEST-002`, and it is why an
*empty* layer directory is a failure here rather than a neutral state -- an empty
`fault/` reads, to anyone glancing at the tree, as fault coverage.

    pytest enforce/fitness/test_layers.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Final

from fixtures import broken_copy, reference_root

if TYPE_CHECKING:
    from pathlib import Path

## The five layers `law/TEST` names, each with what makes it different from the
## others. A project may add more; it may not omit one and call the suite whole.
LAYERS: Final[tuple[str, ...]] = ("unit", "contract", "integration", "fault", "property")

## Modules the unit layer may not reach. Anything here can fail for a reason
## outside the code under test, and a unit failure that the environment can cause
## is a unit failure that localizes nothing.
FORBIDDEN_IN_UNIT: Final[frozenset[str]] = frozenset({
    "os", "io", "pathlib", "socket", "subprocess", "shutil", "tempfile",
    "sqlite3", "http", "urllib", "requests", "httpx", "asyncio", "threading",
    "multiprocessing", "random", "secrets", "time", "datetime", "logging",
})


def named_tests_in(path: Path) -> list[str]:
    """Every test function a module defines.

    @param path the module to read
    @return the names beginning `test_`
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]


def imports_of(path: Path) -> set[str]:
    """Every root module a file imports.

    @param path the module to read
    @return the top-level names imported, dotted paths reduced to their root
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".", 1)[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".", 1)[0])
    return found


# ------------------------------------------- TEST-002 / TEST-007 / FLOW-010


def test_layers_populated() -> None:
    """TEST-002, TEST-007, FLOW-010: every layer exists and holds tests.

    An empty layer is worse than a missing one. A missing directory prompts the
    question; an empty one answers it wrongly.
    """
    root = reference_root()
    for layer in LAYERS:
        directory = root / "tests" / layer
        assert directory.is_dir(), (
            f"the {layer} layer does not exist. An untested seam looks exactly "
            f"like a tested one until it fails."
        )
        names = [n for module in sorted(directory.rglob("test_*.py"))
                 for n in named_tests_in(module)]
        assert names, f"the {layer} layer exists and contains no test"


def test_an_empty_layer_is_caught(tmp_path: Path) -> None:
    """The negative case: a directory that is present and proves nothing.

    @param tmp_path the fixture directory
    """
    root = broken_copy(tmp_path, drop=["tests/fault/test_containment.py"])
    populated = list((root / "tests" / "fault").rglob("test_*.py"))
    assert populated == []


# ------------------------------------------------------------------- TEST-001


def test_unit_layer_is_pure() -> None:
    """TEST-001: the unit layer imports nothing that can fail for its own reasons.

    The rule is about *localization*, not speed. A unit test that can fail
    because a directory was missing tells you nothing about the code it names.
    """
    root = reference_root()
    for module in sorted((root / "tests" / "unit").rglob("*.py")):
        reached = imports_of(module) & FORBIDDEN_IN_UNIT
        assert not reached, (
            f"{module.name} imports {', '.join(sorted(reached))} at the unit "
            f"layer. Move it to integration, or take the capability as a port."
        )


def test_an_impure_unit_test_is_caught(tmp_path: Path) -> None:
    """The negative case.

    @param tmp_path the fixture directory
    """
    root = broken_copy(tmp_path, write={
        "tests/unit/test_impure.py":
            '"""Tests. Oracle: example."""\n\nimport pathlib\n\n\n'
            'def test_it():\n    """Touches a disk."""\n'
            '    assert pathlib.Path(".").exists()\n',
    })
    reached = imports_of(root / "tests" / "unit" / "test_impure.py") & FORBIDDEN_IN_UNIT
    assert reached == {"pathlib"}
