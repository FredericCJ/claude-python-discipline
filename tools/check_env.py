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


def read_pins(path: Path) -> tuple[str | None, dict[str, str], list[str]]:
    """Parse the declared environment without importing a YAML parser.

    Comment lines are dropped first, so the prose in `environment.yml` -- which
    names packages it is explaining rather than pinning -- is never mistaken for
    a requirement.

    @param path the environment file to read
    @return the interpreter version or None, the exact pins by package name, and
        one complaint per requirement that was not pinned exactly
    """
    python: str | None = None
    pins: dict[str, str] = {}
    loose: list[str] = []
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
    return python, pins, loose


def installed(name: str) -> str | None:
    """The version of a distribution in the running interpreter.

    @param name the distribution name as `environment.yml` spells it
    @return the installed version, or None when the distribution is absent
    """
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def drift(python: str | None, pins: dict[str, str]) -> list[str]:
    """Every way the running interpreter departs from the declaration.

    @param python the pinned interpreter version, or None when none is declared
    @param pins the pinned package versions by distribution name
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

    python, pins, loose = read_pins(args.file)

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

    problems = drift(python, pins)
    if problems:
        print(f"environment does not match {args.file.name}:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print("  fix with: conda env update -f environment.yml --prune", file=sys.stderr)
        return 1

    if not args.quiet:
        print(f"environment matches {args.file.name}: "
              f"python {python}, {len(pins)} pinned package(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
