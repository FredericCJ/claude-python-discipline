"""The register is derived, fails closed, and does not mistake silence for safety.

**Oracle: differential.** The survey is driven over synthetic trees whose foreign
imports are known, and its answer compared.

`ARCH-004`'s shipped contract had an empty `forbidden_modules` list, which forbids
nothing and passes on every tree forever. The register exists to derive the list
rather than ask for it, and these are the properties that keep it from becoming
the same defect in a new place:

* an unregistered foreign import must FAIL, not be noted;
* a tree with no package must report that **nothing was examined**, which is not
  the same as nothing being found -- the first version returned an empty survey
  for a four-package tree and reported "no foreign dependency imported";
* a dependency with two importers must be reported with both, because the second
  importer is the violation and a count would hide which.

    pytest tools/test_register_deps.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import register_deps

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from pathlib import Path


def _tree(root: Path, files: dict[str, str]) -> Path:
    """Build a synthetic source tree.

    @param root the directory to build under
    @param files paths relative to the tree root, against their contents
        Treat files as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @return the tree root, holding `src/`

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Materialize each relative module-name key and source-body value in mapping iteration order.
    for name, body in files.items():
        # Resolve each declared fixture path beneath the isolated repository root.
        target = root / name
        # Create only the ancestry required by the current fixture file.
        target.parent.mkdir(parents=True, exist_ok=True)
        # Materialize the exact source or configuration body supplied by the test.
        target.write_text(body, encoding="utf-8")
    # Return the complete synthetic repository to the dependency-registration operation.
    return root


def test_the_reference_imports_nothing_foreign() -> None:
    """The positive case: a conformant package needs no register at all.

    Asserted first. A survey that reported dependencies here would be seeing the
    standard library or the package itself, and every negative below would be
    meaningless.
    """
    assert register_deps.survey(register_deps.REPO_ROOT / "enforce" / "fixtures"
                                / "reference") == {}


def test_every_package_is_surveyed_not_just_one(tmp_path: Path) -> None:
    """The defect this was caught committing, pinned.

    The first version took the single package under `src/` and returned nothing
    when there were several. Pointed at a real four-package tree with pydantic in
    all four domains, it reported "no foreign dependency is imported" -- a silent
    nothing, in the tool written to remove one.

    @param tmp_path the fixture directory
    """
    # Build two source packages importing distinct foreign roots for the complete survey census.
    root = _tree(tmp_path, {
        "src/one/__init__.py": "",
        "src/one/models.py": "import pydantic\n",
        "src/two/__init__.py": "",
        "src/two/store.py": "import yaml\n",
    })
    # Preserve the optional pattern match that carries the reported analysis count.
    found = register_deps.survey(root)
    assert set(found) == {"pydantic", "yaml"}, (
        "a multi-package tree was not fully surveyed"
    )


def test_a_dependency_with_two_importers_names_both(tmp_path: Path) -> None:
    """The second importer IS the ARCH-004 violation, so it must be shown.

    Reducing this to a count would report that something is wrong without saying
    where, which is the diagnosis the Prime Directive refuses.

    @param tmp_path the fixture directory
    """
    # Build two modules sharing one foreign root so holder provenance can be compared.
    root = _tree(tmp_path, {
        "src/pkg/__init__.py": "",
        "src/pkg/a.py": "import httpx\n",
        "src/pkg/b.py": "import httpx\n",
    })
    assert register_deps.survey(root)["httpx"] == {"pkg.a", "pkg.b"}


def test_the_standard_library_is_not_a_dependency(tmp_path: Path) -> None:
    """`json` and `pathlib` are not foreign, and registering them would be noise.

    @param tmp_path the fixture directory
    """
    # Build a package containing only standard-library and internal imports.
    root = _tree(tmp_path, {
        "src/pkg/__init__.py": "",
        "src/pkg/a.py": "import json\nimport pathlib\nfrom pkg import b\n",
        "src/pkg/b.py": "",
    })
    assert register_deps.survey(root) == {}


def test_an_unregistered_import_fails_the_check(tmp_path: Path) -> None:
    """Fail closed. The whole defect being fixed is a check that had nothing to say.

    @param tmp_path the fixture directory
    """
    # Build a package whose observed httpx import is absent from its declared register.
    root = _tree(tmp_path, {
        "src/pkg/__init__.py": "",
        "src/pkg/a.py": "import httpx\n",
        "importlinter.toml": '[tool.importlinter]\nroot_packages = ["pkg"]\n',
    })
    assert register_deps.main(["--root", str(root), "--check"]) == \
        register_deps.EXIT_INCOMPLETE


def test_a_registered_import_passes_the_check(tmp_path: Path) -> None:
    """...and a complete register is accepted, so the check is not merely strict.

    @param tmp_path the fixture directory
    """
    # Build the same package with a complete forbidden-dependency contract for httpx.
    root = _tree(tmp_path, {
        "src/pkg/__init__.py": "",
        "src/pkg/a.py": "import httpx\n",
        "importlinter.toml": (
            '[tool.importlinter]\nroot_packages = ["pkg"]\n\n'
            "[[tool.importlinter.contracts]]\n"
            'name = "ARCH-004"\ntype = "forbidden"\n'
            'source_modules = ["pkg.domain"]\n'
            'forbidden_modules = ["httpx"]\n'
        ),
    })
    assert register_deps.main(["--root", str(root), "--check"]) == \
        register_deps.EXIT_OK


def test_a_tree_with_no_package_says_nothing_was_examined(tmp_path: Path) -> None:
    """"Nothing found" and "nothing looked at" must not print the same.

    The distinction the corpus turns on: a check reporting no findings against a
    tree it never opened is indistinguishable from a clean bill of health, and is
    the failure mode this repository has now met in five separate tools.

    @param tmp_path the fixture directory
    """
    assert register_deps.main(["--root", str(tmp_path), "--check"]) == \
        register_deps.EXIT_INCOMPLETE
