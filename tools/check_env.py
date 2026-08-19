"""Verify the running interpreter against the pinned environment.

    python tools/check_env.py            # exit 0 when the environment matches
    python tools/check_env.py --quiet    # report only drift

The mechanism `DEP-005` and `DEP-006` name: `environment.yml` declares an exact
version for everything the seven-step gate needs, and this decides whether the
interpreter actually running matches it. A pin nothing compares against is a
comment.

Two properties are deliberate, and both matter more than they look:

* **No third-party import.** This module reads `environment.yml` with a regex
  rather than with PyYAML, and reads installed versions through
  `importlib.metadata`. A verifier that imports the packages it verifies cannot
  run in the one situation it exists for -- an environment that is wrong.
* **Drift is named, never summarised.** The output says which package, what was
  pinned and what is installed, because "environment mismatch" sends a reader
  back to a diff this tool already has in hand.

What it does NOT prove is stated in `environment.yml` beside the pins: this
compares versions, not wheel content hashes, so two builds of `ruff==0.16.3` are
assumed to be the same ruff.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Final

## Anchor for every path here, derived from this file rather than the working
## directory, so the tool behaves the same however it was invoked.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent

## The lock. Exact versions live here and nowhere else; this module only reads.
ENVIRONMENT_PATH: Final = REPO_ROOT / "environment.yml"

## A pip requirement pinned exactly, as it appears in the `pip:` block --
## `      - ruff==0.16.3`. Only `==` is recognised: a range is not a lock, so a
## line carrying one is reported rather than quietly accepted.
_PINNED: Final = re.compile(r"^\s*-\s*([A-Za-z0-9._-]+)==([A-Za-z0-9._+-]+)\s*$")

## The interpreter pin, written the way conda spells it -- `  - python=3.13.14`.
_PYTHON: Final = re.compile(r"^\s*-\s*python=([0-9][A-Za-z0-9._]*)\s*$")

## A requirement given a range instead of an exact version, which defeats the
## point of the file and is reported as a defect in the lock itself.
_LOOSE: Final = re.compile(r"^\s*-\s*([A-Za-z0-9._-]+)\s*(>=|<=|>|<|~=|!=)")

## A conda pin, written with one `=` -- `  - doxygen=1.10.0`. These are not pip
## distributions and `importlib.metadata` knows nothing about them, so each needs
## a verifier of its own. `python` is matched by `_PYTHON` above and excluded
## here.
_CONDA: Final = re.compile(r"^\s*-\s*([A-Za-z0-9._-]+)=([0-9][A-Za-z0-9._]*)\s*$")

## How to ask a conda-installed native tool for its version. Anything declared as
## a conda pin and absent from this table is REPORTED as unverifiable rather than
## passed over: a declared dependency nobody checks is the exact shape of defect
## this file exists to remove, and adding a pin the checker silently ignores
## would reintroduce it one entry at a time.
NATIVE_VERIFIERS: Final[dict[str, tuple[str, ...]]] = {
    "doxygen": ("doxygen.exe", "doxygen"),
}


def read_pins(path: Path) -> tuple[str | None, dict[str, str], list[str], dict[str, str]]:
    """Parse the declared environment without importing a YAML parser.

    Comment lines are dropped first, so the prose in `environment.yml` -- which
    names packages it is explaining rather than pinning -- is never mistaken for
    a requirement.

    @param path the environment file to read
    @return the interpreter version or None, the pip pins by distribution name,
        one complaint per requirement that was not pinned exactly, and the conda
        pins by package name
    """
    python: str | None = None
    pins: dict[str, str] = {}
    loose: list[str] = []
    conda: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0]
        if not line.strip():
            continue
        found_python = _PYTHON.match(line)
        if found_python is not None:
            python = found_python.group(1)
            continue
        found = _PINNED.match(line)
        if found is not None:
            pins[found.group(1)] = found.group(2)
            continue
        vague = _LOOSE.match(line)
        if vague is not None:
            loose.append(f"{vague.group(1)} is given a range, not an exact version")
            continue
        native = _CONDA.match(line)
        if native is not None:
            conda[native.group(1)] = native.group(2)
    return python, pins, loose, conda


def installed(name: str) -> str | None:
    """The version of a distribution in the running interpreter.

    @param name the distribution name as `environment.yml` spells it
    @return the installed version, or None when the distribution is absent
    """
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def native_version(name: str) -> str | None:
    """The version a conda-installed native tool reports, or None when absent.

    Looked for beside the running interpreter before PATH, because conda puts
    native binaries in `Library/bin` (Windows) or `bin` (POSIX) and prepends them
    to PATH only on ACTIVATION. Every gate step here runs `sys.executable`
    directly, so a PATH-only search finds nothing on a machine where the tool is
    correctly installed -- and the caller then reports it missing, which is the
    same wrong answer as not looking.

    @param name the conda package name
    @return the first whitespace-separated token of its `--version` output, or
        None when the binary cannot be found or refuses to report
    """
    root = Path(sys.executable).parent
    for filename in NATIVE_VERIFIERS.get(name, ()):
        for candidate in (root / "Library" / "bin" / filename, root / filename,
                          root / "bin" / filename):
            if candidate.is_file():
                found = _ask_version(str(candidate))
                if found is not None:
                    return found
    located = shutil.which(name)
    return _ask_version(located) if located else None


def _ask_version(executable: str) -> str | None:
    """Run `<executable> --version` and return its first token.

    @param executable the binary to run
    @return the version token, or None when the call fails
    """
    finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        (executable, "--version"), capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=60,
    )
    if finished.returncode != 0 or not finished.stdout.strip():
        return None
    return finished.stdout.strip().split()[0]


def drift(python: str | None, pins: dict[str, str],
          conda: dict[str, str] | None = None) -> list[str]:
    """Every way the running interpreter departs from the declaration.

    @param python the pinned interpreter version, or None when none is declared
    @param pins the pinned package versions by distribution name
    @param conda the pinned conda packages, checked by running each tool
    @return one line per departure, naming the package, the pin and what is there
    """
    problems: list[str] = []
    running = ".".join(str(part) for part in sys.version_info[:3])
    if python is not None and running != python:
        problems.append(f"python: pinned {python}, running {running}")
    for name, pinned in sorted(pins.items()):
        found = installed(name)
        if found is None:
            problems.append(f"{name}: pinned {pinned}, not installed")
        elif found != pinned:
            problems.append(f"{name}: pinned {pinned}, installed {found}")
    for name, pinned in sorted((conda or {}).items()):
        if name not in NATIVE_VERIFIERS:
            problems.append(
                f"{name}: pinned {pinned} as a conda package, and this checker has "
                f"no way to verify it. Add it to NATIVE_VERIFIERS or remove the "
                f"pin -- a declared dependency nobody checks is not a lock."
            )
            continue
        found = native_version(name)
        if found is None:
            problems.append(f"{name}: pinned {pinned}, not installed")
        elif found != pinned:
            problems.append(f"{name}: pinned {pinned}, installed {found}")
    return problems


def main(argv: list[str] | None = None) -> int:
    """Compare the running interpreter to the lock and report the difference.

    @param argv the command-line arguments, or None to read `sys.argv`
    @return 0 when the environment matches the declaration, 1 when it does not
        and 2 when the declaration itself cannot be trusted
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quiet", action="store_true",
                        help="print nothing when the environment matches")
    parser.add_argument("--file", type=Path, default=ENVIRONMENT_PATH,
                        help="the environment declaration to check against")
    parser.add_argument("--print-requirements", action="store_true",
                        help="emit the pins as a pip requirements file and exit")
    args = parser.parse_args(argv)

    if not args.file.exists():
        print(f"no environment declaration at {args.file}", file=sys.stderr)
        return 2

    python, pins, loose, conda = read_pins(args.file)

    if args.print_requirements:
        # So a CI job installs from the declaration instead of carrying its own
        # copy of it. The previous workflow repeated the list by hand and had
        # already drifted from the environment it claimed to mirror.
        for name, pinned in sorted(pins.items()):
            print(f"{name}=={pinned}")
        return 0

    if loose:
        for complaint in loose:
            print(f"lock defect: {complaint}", file=sys.stderr)
        return 2
    if not pins:
        print(f"{args.file} pins nothing; there is no lock to check", file=sys.stderr)
        return 2

    problems = drift(python, pins, conda)
    if problems:
        print(f"environment does not match {args.file.name}:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print("  fix with: conda env update -f environment.yml --prune", file=sys.stderr)
        return 1

    if not args.quiet:
        # The conda pins are named rather than counted. They are verified by
        # running a binary rather than by reading metadata, which is the less
        # obvious half of what this command does, and a bare total would let a
        # reader assume the familiar half was all of it.
        native = f", {', '.join(sorted(conda))} verified by execution" if conda else ""
        print(f"environment matches {args.file.name}: "
              f"python {python}, {len(pins)} pinned package(s){native}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
