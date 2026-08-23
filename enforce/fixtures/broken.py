"""The reference package, and one way to break it.

Every fitness test needs two trees: a conformant one to prove it does not fire,
and a broken one to prove it does. Hand-maintaining thirty-one broken trees would
guarantee that most of them drifted out of step with the reference and quietly
stopped testing anything.

So there is one conformant tree -- `reference/` -- and `broken_copy`, which
copies it and breaks exactly one thing. A negative case then reads as the
sentence it is testing: *remove scheduled-fault capability and
`test_reference_contract_conformance` must fire*. Nothing broken is ever
committed, so pytest cannot collect it and no
reader can mistake it for an example.

    root = broken_copy(tmp_path, replace=[("contract-conformance.json", old, new)])
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Final

# Import collection protocols only while static analyzers evaluate fixture contracts.
if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

## The conformant tree, beside this file.
REFERENCE: Final = Path(__file__).resolve().parent / "reference"

## Unordered directory-name elements excluded from fixture copies. Build artifacts
## slow negative cases, while stale bytecode can keep a dropped module importable.
_SKIP: Final[frozenset[str]] = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache",
                                          ".mypy_cache", ".hypothesis"})


## The variable that lets a caller point every fitness suite at a different tree.
##
## The suites were written against a constant, which made them unmutable: the
## discrimination matrix could hold the 70 rules decided by AST checks to account
## and not the 53 decided by fitness tests, because there was no way to run one
## against a damaged copy. Thirteen modules would have needed a `--root`
## parameter each; this is the same seam in one function.
##
## Deliberately an environment variable rather than an argument. A fitness test
## is invoked by pytest, which passes no arguments of ours, so the value has to
## arrive out of band or not at all.
REFERENCE_VARIABLE: Final = "DISCIPLINE_REFERENCE"


def reference_root() -> Path:
    """The conformant reference package's root, or whatever was pointed at.

    Honours `DISCIPLINE_REFERENCE` so a caller -- in practice
    `tools/discrimination_gate.py` -- can run a fitness suite against a copy
    broken in exactly one way and require it to fail. A fitness test that passes
    against a tree damaged in the way it exists to catch is the same defect as a
    check that reports nothing, and until this seam existed nothing could tell.

    @return the directory holding `src/` and `tests/`
    @throws FileNotFoundError when the tree is missing, which would make every
        fitness test vacuous rather than failing -- and which matters more for an
        override than for the default, since a mistyped path would otherwise turn
        the whole suite green
    """
    # Resolve an explicit discrimination override before falling back to the fixture.
    named = os.environ.get(REFERENCE_VARIABLE)
    root = Path(named).resolve() if named else REFERENCE
    # Refuse a subject that lacks the source root required by every fitness test.
    if not (root / "src").is_dir():
        # Preserve whether the invalid path came from caller-controlled configuration.
        origin = f" (from {REFERENCE_VARIABLE})" if named else ""
        message = f"the reference package is missing from {root}{origin}"
        # Stop before a missing subject can make downstream checks vacuously green.
        raise FileNotFoundError(message)
    # Return the validated project root used by all subsequent fixture operations.
    return root


def broken_copy(
    tmp_path: Path,
    *,
    drop: Sequence[str] = (),
    write: Mapping[str, str] | None = None,
    replace: Sequence[tuple[str, str, str]] = (),
) -> Path:
    """A copy of the reference with exactly the named damage done to it.

    Each keyword is a different way to break one thing, and a negative case
    should use one of them: a test breaking two things at once cannot say which
    one the check caught.

    @param tmp_path a fresh directory to build the copy in
    @param drop relative-path string elements deleted in declared application order
    @param write relative-path keys mapped to content-text values; mapping order is
        preserved but insignificant because each key owns an independent file
    @param replace relative-path, old-text, and new-text triple elements applied in order
    @return the root of the broken copy
    @throws FileNotFoundError when a path named for dropping or replacing is not
        there -- silently doing nothing would leave the negative case asserting
        against an unbroken tree, which is the one outcome that must not happen
    @par Effects
    Creates an isolated fixture tree, then applies requested deletions, writes, and
    replacements in that order beneath it.
    """
    # Reserve one deterministic destination for the damaged fixture tree.
    root = tmp_path / "broken"
    # Copy the conformant control while excluding caches that could mask mutations.
    shutil.copytree(
        reference_root(), root,
        ignore=lambda _directory, names: [n for n in names if n in _SKIP],
    )

    # Apply every requested deletion in caller-declared order.
    for relative in drop:
        # Resolve the current deletion target inside the isolated fixture root.
        target = root / relative
        # Refuse drift when the requested control subject no longer exists.
        if not target.exists():
            # Name the stale relative path so the mutation declaration can be repaired.
            message = f"nothing to drop at {relative}; the reference has moved"
            # Stop rather than crediting a mutation that changed no fixture content.
            raise FileNotFoundError(message)
        # Select recursive removal only for a directory-shaped mutation target.
        if target.is_dir():
            # Remove the isolated subtree represented by the declared path.
            shutil.rmtree(target)
        else:
            # Remove the isolated file represented by the declared path.
            target.unlink()

    # Apply independent file-content entries from the optional write mapping.
    for relative, body in (write or {}).items():
        # Resolve each output path and make its parent available before the write.
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        # Persist exact UTF-8 fixture content at the declared relative path.
        target.write_text(body, encoding="utf-8")

    # Apply literal substitutions sequentially so overlapping mutations stay explicit.
    for relative, old, new in replace:
        # Resolve the current substitution subject within the isolated copy.
        target = root / relative
        # Refuse a declaration whose target disappeared from the conformant fixture.
        if not target.exists():
            # Identify the stale relative path in the resulting fixture diagnostic.
            message = f"nothing to edit at {relative}; the reference has moved"
            # Stop before an absent substitution subject earns false rejection credit.
            raise FileNotFoundError(message)
        # Read the current text after all earlier ordered mutations have completed.
        text = target.read_text(encoding="utf-8")
        # Refuse a literal mutation whose expected control text has drifted.
        if old not in text:
            # Name both the target and missing old text for direct declaration repair.
            message = f"{relative} does not contain {old!r}; the reference has moved"
            # Stop rather than writing an unchanged or ambiguously substituted fixture.
            raise FileNotFoundError(message)
        # Replace exactly the first declared occurrence and persist deterministic text.
        target.write_text(text.replace(old, new, 1), encoding="utf-8")

    # Return the fully mutated project root after every requested operation succeeds.
    return root


def package_root(root: Path) -> Path:
    """The single package directory under a project's `src/`.

    @param root the project root
    @return the package directory
    @throws FileNotFoundError when `src/` holds no package, or more than one
    """
    # Select package-directory path elements in sorted name order beneath `src`.
    candidates = [
        p for p in sorted((root / "src").iterdir())
        if p.is_dir() and p.name not in _SKIP
    ] if (root / "src").is_dir() else []
    # Refuse both missing and ambiguous package layouts through one bounded contract.
    if len(candidates) != 1:
        # Report the observed cardinality alongside the exact source directory.
        message = f"expected exactly one package under {root / 'src'}, found {len(candidates)}"
        # Stop before a caller could silently select an arbitrary package candidate.
        raise FileNotFoundError(message)
    # Return the only package path proven to satisfy the single-package fixture shape.
    return candidates[0]


def modules_in(directory: Path) -> list[Path]:
    """Every importable module directly inside a directory, excluding its init.

    @param directory the directory to list; a missing one yields nothing
    @return module-path elements in sorted filename order with package init excluded
    """
    # Treat a missing or non-directory subject as an empty module surface.
    if not directory.is_dir():
        # Return an empty ordered sequence without attempting directory traversal.
        return []
    # Return sorted importable module paths after excluding init and cache artifacts.
    return sorted(
        p for p in directory.glob("*.py")
        if p.name != "__init__.py" and "__pycache__" not in p.parts
    )
