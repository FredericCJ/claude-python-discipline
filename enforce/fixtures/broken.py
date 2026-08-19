"""The reference package, and one way to break it.

Every fitness test needs two trees: a conformant one to prove it does not fire,
and a broken one to prove it does. Hand-maintaining thirty-one broken trees would
guarantee that most of them drifted out of step with the reference and quietly
stopped testing anything.

So there is one conformant tree -- `reference/` -- and `broken_copy`, which
copies it and breaks exactly one thing. A negative case then reads as the
sentence it is testing: *drop the faulty adapter and `test_port_triad` must
fire*. Nothing broken is ever committed, so pytest cannot collect it and no
reader can mistake it for an example.

    root = broken_copy(tmp_path, drop=["src/refpkg/adapters/clock/faulty.py"])
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

## The conformant tree, beside this file.
REFERENCE: Final = Path(__file__).resolve().parent / "reference"

## Directories never copied: build artefacts that would slow every negative case
## and, in the case of a stale `__pycache__`, could make a dropped module still
## importable.
_SKIP: Final[frozenset[str]] = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache",
                                          ".mypy_cache", ".hypothesis"})


def reference_root() -> Path:
    """The conformant reference package's root.

    @return the directory holding `src/` and `tests/`
    @throws FileNotFoundError when the reference is missing, which would make
        every fitness test vacuous rather than failing
    """
    if not (REFERENCE / "src").is_dir():
        message = f"the reference package is missing from {REFERENCE}"
        raise FileNotFoundError(message)
    return REFERENCE


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
    @param drop paths, relative to the root, to delete
    @param write paths to create or overwrite, against their new contents
    @param replace `(path, old, new)` triples applied as literal substitutions
    @return the root of the broken copy
    @throws FileNotFoundError when a path named for dropping or replacing is not
        there -- silently doing nothing would leave the negative case asserting
        against an unbroken tree, which is the one outcome that must not happen
    """
    root = tmp_path / "broken"
    shutil.copytree(
        reference_root(), root,
        ignore=lambda _directory, names: [n for n in names if n in _SKIP],
    )

    for relative in drop:
        target = root / relative
        if not target.exists():
            message = f"nothing to drop at {relative}; the reference has moved"
            raise FileNotFoundError(message)
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

    for relative, body in (write or {}).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")

    for relative, old, new in replace:
        target = root / relative
        if not target.exists():
            message = f"nothing to edit at {relative}; the reference has moved"
            raise FileNotFoundError(message)
        text = target.read_text(encoding="utf-8")
        if old not in text:
            message = f"{relative} does not contain {old!r}; the reference has moved"
            raise FileNotFoundError(message)
        target.write_text(text.replace(old, new, 1), encoding="utf-8")

    return root


def package_root(root: Path) -> Path:
    """The single package directory under a project's `src/`.

    @param root the project root
    @return the package directory
    @throws FileNotFoundError when `src/` holds no package, or more than one
    """
    candidates = [
        p for p in sorted((root / "src").iterdir())
        if p.is_dir() and p.name not in _SKIP
    ] if (root / "src").is_dir() else []
    if len(candidates) != 1:
        message = f"expected exactly one package under {root / 'src'}, found {len(candidates)}"
        raise FileNotFoundError(message)
    return candidates[0]


def modules_in(directory: Path) -> list[Path]:
    """Every importable module directly inside a directory, excluding its init.

    @param directory the directory to list; a missing one yields nothing
    @return the module files, sorted, with `__init__.py` left out
    """
    if not directory.is_dir():
        return []
    return sorted(
        p for p in directory.glob("*.py")
        if p.name != "__init__.py" and "__pycache__" not in p.parts
    )
