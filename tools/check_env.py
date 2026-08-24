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

## Native tools do not agree on a version grammar: Doxygen starts with the
## version, pip prefixes it with its name, Git says ``git version``, and Node
## prefixes it with ``v``. Extract the first dotted numeric identity and stop at
## a platform suffix such as Git for Windows' ``.windows.1``.
_NATIVE_VERSION: Final = re.compile(
    r"(?<![0-9])v?([0-9]+(?:\.[0-9]+)+)(?=[^0-9]|$)",
)

## How to ask a conda-installed native tool for its version. Anything declared as
## a conda pin and absent from this table is REPORTED as unverifiable rather than
## passed over: a declared dependency nobody checks is the exact shape of defect
## this file exists to remove, and adding a pin the checker silently ignores
## would reintroduce it one entry at a time.
## Each key is one conda package name and each value is its executable-name candidates in
## preference order; package-key order is deliberately unused.
NATIVE_VERIFIERS: Final[dict[str, tuple[str, ...]]] = {
    "doxygen": ("doxygen.exe", "doxygen"),
    "git": ("git.exe", "git"),
    "graphviz": ("dot.exe", "dot"),
    "nodejs": ("node.exe", "node"),
    "pip": ("pip.exe", "pip"),
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
    # Start without an interpreter pin so its absence remains distinguishable.
    python: str | None = None
    # Map pip distribution-name keys to exact version-string values; key order is deliberately
    # unused because comparisons sort them.
    pins: dict[str, str] = {}
    # Each loose element is one complaint string for a ranged requirement; declaration order is
    # preserved.
    loose: list[str] = []
    # Map native conda package-name keys to exact version-string values; key order is
    # deliberately unused because comparisons sort them.
    conda: dict[str, str] = {}
    # Parse environment declaration lines in source order without loading YAML dependencies.
    for raw in path.read_text(encoding="utf-8").splitlines():
        # Strip explanatory comments before matching requirement grammar.
        line = raw.split("#", 1)[0]
        # Ignore blank and comment-only declaration lines.
        if not line.strip():
            # Empty declaration records carry no lock information.
            continue
        # Test the line against the exact conda interpreter grammar first.
        found_python = _PYTHON.match(line)
        # Record the sole interpreter version when the grammar matched.
        if found_python is not None:
            # Preserve the captured exact interpreter version string.
            python = found_python.group(1)
            # A matched interpreter record cannot also be a package declaration.
            continue
        # Test the remaining line against the exact pip requirement grammar.
        found = _PINNED.match(line)
        # Register a matched distribution and exact version.
        if found is not None:
            # Store the distribution/version pair after both captures are available.
            pins[found.group(1)] = found.group(2)
            # Exact pip records need no range or native-package classification.
            continue
        # Detect range operators that violate the exact-lock contract.
        vague = _LOOSE.match(line)
        # Preserve an actionable complaint for every ranged requirement.
        if vague is not None:
            loose.append(f"{vague.group(1)} is given a range, not an exact version")
            # Preserve the loose-pin defect without misclassifying its package syntax.
            continue
        # Finally test the line against an exact native conda-package pin.
        native = _CONDA.match(line)
        # Register a matched native package and exact version.
        if native is not None:
            # Store the native package/version pair after both captures are available.
            conda[native.group(1)] = native.group(2)
    # Keep interpreter, pip, lock defects, and native pins separate for precise diagnostics.
    return python, pins, loose, conda


def installed(name: str) -> str | None:
    """The version of a distribution in the running interpreter.

    @param name the distribution name as `environment.yml` spells it
    @return the installed version, or None when the distribution is absent
    """
    # Query installed metadata while treating an absent distribution as a normal negative result.
    try:
        # Metadata is authoritative for import-only Python distributions.
        return version(name)
    except PackageNotFoundError:
        # An absent distribution is the expected negative probe result, not a tool failure.
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
    @return the normalized dotted version from its `--version` output, or None
        when the binary cannot be found or refuses to report
    """
    # Locate the declared package's executable using conda-aware search precedence.
    located = locate_native(name)
    # An unavailable executable has no version; otherwise normalize its own report.
    return _ask_version(located) if located else None


def locate_native(name: str) -> str | None:
    """Where a conda-installed native tool actually is, or None when absent.

    Beside the running interpreter before PATH, because conda puts native
    binaries in `Library/bin` (Windows) or `bin` (POSIX) and prepends them to
    PATH only on ACTIVATION. Every gate step here runs `sys.executable`
    directly, so a PATH-only search finds nothing on a machine where the tool is
    correctly installed -- and the caller then reports it missing, which is the
    same wrong answer as not looking.

    Extracted so there is ONE of these. There were two: this, and a copy in
    `enforce/fitness/test_meta.py` written for the same reason a day apart. Two
    copies of a search path is how the two stop agreeing about where a tool is.

    @param name the conda package name
    @return the path to run, or None when it cannot be found at all
    """
    # Anchor conda-relative executable candidates beside the running interpreter.
    root = Path(sys.executable).parent
    # Probe declared executable spellings in package-specific preference order.
    for filename in NATIVE_VERIFIERS.get(name, (f"{name}.exe", name)):
        # Probe Windows and POSIX conda binary directories before falling back to PATH.
        for candidate in (root / "Library" / "bin" / filename,
                          root / "Scripts" / filename, root / filename,
                          root / "bin" / filename):
            # Return the first concrete executable candidate found in conda precedence order.
            if candidate.is_file():
                # Prefer the active environment over any unrelated executable on PATH.
                return str(candidate)
    # PATH remains the fallback for tools intentionally provided outside the prefix.
    return shutil.which(name)


def parse_native_version(output: str) -> str | None:
    """Extract one dotted numeric version from a native tool's output.

    @param output stdout and stderr emitted by a successful version probe
    @return the normalized numeric version, or None when none is present
    """
    # Locate the first dotted numeric token accepted by the native-version grammar.
    found = _NATIVE_VERSION.search(output)
    # Ignore vendor decoration while retaining the comparable dotted release token.
    return found.group(1) if found is not None else None


def _ask_version(executable: str) -> str | None:
    """Run `<executable> --version` and normalize its version grammar.

    @param executable the binary to run
    @return the version token, or None when the call fails
    """
    # Ask the resolved executable for its version without invoking a shell.
    finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        (executable, "--version"), capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=60,
    )
    # Enter the failure path only when the subprocess reports a nonzero status.
    if finished.returncode != 0:
        # A tool that cannot report its version cannot satisfy an exact pin.
        return None
    # Native tools vary between stdout and stderr, so parse their combined report.
    return parse_native_version(f"{finished.stdout}\n{finished.stderr}")


def drift(python: str | None, pins: dict[str, str],
          conda: dict[str, str] | None = None) -> list[str]:
    """Every way the running interpreter departs from the declaration.

    @param python the pinned interpreter version, or None when none is declared
    @param pins distribution-name keys mapped to exact pip version-string values;
        key order is deliberately unused because comparison sorts it
    @param conda conda package-name keys mapped to exact version-string values;
        key order is deliberately unused because comparison sorts it
    @return one line per departure, naming the package, the pin and what is there
    """
    # Each problems element is one human mismatch diagnostic string; interpreter, pip, then
    # conda order is preserved.
    problems: list[str] = []
    # Join the running interpreter's major, minor, and patch components in that order.
    running = ".".join(str(part) for part in sys.version_info[:3])
    # Report interpreter drift only when a pin exists and differs exactly.
    if python is not None and running != python:
        problems.append(f"python: pinned {python}, running {running}")
    # Compare pip distributions in lexical name order for deterministic diagnostics.
    for name, pinned in sorted(pins.items()):
        # Query the running interpreter's installed distribution metadata.
        found = installed(name)
        # Report a pinned Python distribution that the active environment does not install.
        if found is None:
            problems.append(f"{name}: pinned {pinned}, not installed")
        # Report exact-version drift when the distribution exists at another version.
        elif found != pinned:
            problems.append(f"{name}: pinned {pinned}, installed {found}")
    # Compare native conda tools in lexical package-name order.
    for name, pinned in sorted((conda or {}).items()):
        # Refuse a declared native package for which no executable probe is defined.
        if name not in NATIVE_VERIFIERS:
            problems.append(
                f"{name}: pinned {pinned} as a conda package, and this checker has "
                f"no way to verify it. Add it to NATIVE_VERIFIERS or remove the "
                f"pin -- a declared dependency nobody checks is not a lock."
            )
            # Never execute an undeclared probe command merely because a package is pinned.
            continue
        # Execute the package-specific version probe after verifier coverage is established.
        found = native_version(name)
        # Report a pinned native executable that cannot be resolved from the active environment.
        if found is None:
            problems.append(f"{name}: pinned {pinned}, not installed")
        # Report exact-version drift when the native tool reports another version.
        elif found != pinned:
            problems.append(f"{name}: pinned {pinned}, installed {found}")
    return problems


def main(argv: list[str] | None = None) -> int:
    """Compare the running interpreter to the lock and report the difference.

    @param argv the command-line arguments, or None to read `sys.argv`
    @return 0 when the environment matches the declaration, 1 when it does not
        and 2 when the declaration itself cannot be trusted
    """
    # Select the module summary, retaining a defensive fallback for stripped documentation.
    description = (__doc__ or "Verify the declared development environment.")
    # Configure the command-line parser that defines this tool's invocation contract.
    parser = argparse.ArgumentParser(description=description.splitlines()[0])
    parser.add_argument("--quiet", action="store_true",
                        help="print nothing when the environment matches")
    parser.add_argument("--file", type=Path, default=ENVIRONMENT_PATH,
                        help="the environment declaration to check against")
    parser.add_argument("--print-requirements", action="store_true",
                        help="emit the pins as a pip requirements file and exit")
    # Capture the validated invocation arguments that govern this execution.
    args = parser.parse_args(argv)

    # Reject an absent declaration before attempting any version comparison.
    if not args.file.exists():
        print(f"no environment declaration at {args.file}", file=sys.stderr)
        # Refuse drift analysis without the lock declaration that defines expected versions.
        return 2

    # Parse interpreter, pip, lock-defect, and native-pin dimensions together.
    python, pins, loose, conda = read_pins(args.file)

    # Requirements mode emits only exact pip pins and skips environment verification.
    if args.print_requirements:
        # So a CI job installs from the declaration instead of carrying its own
        # copy of it. The previous workflow repeated the list by hand and had
        # already drifted from the environment it claimed to mirror.
        for name, pinned in sorted(pins.items()):
            print(f"{name}=={pinned}")
        return 0

    # Reject every ranged requirement before treating the declaration as a lock.
    if loose:
        # Report lock complaints in declaration order.
        for complaint in loose:
            print(f"lock defect: {complaint}", file=sys.stderr)
        return 2
    # Refuse a declaration with no exact pip pins because it cannot constrain the gate.
    if not pins:
        print(f"{args.file} pins nothing; there is no lock to check", file=sys.stderr)
        # Refuse a vacuous lock verdict when no exact Python distributions constrain the environment.
        return 2

    # Compare every declared dimension against the running environment.
    problems = drift(python, pins, conda)
    # Report mismatch detail and fail when any environment dimension drifted.
    if problems:
        print(f"environment does not match {args.file.name}:", file=sys.stderr)
        # Preserve interpreter, pip, then native diagnostic order.
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print("  fix with: conda env update -f environment.yml --prune", file=sys.stderr)
        return 1

    # Emit the positive non-vacuity summary unless quiet mode suppressed clean output.
    if not args.quiet:
        # The conda pins are named rather than counted. They are verified by
        # running a binary rather than by reading metadata, which is the less
        # obvious half of what this command does, and a bare total would let a
        # reader assume the familiar half was all of it.
        native = f", {', '.join(sorted(conda))} verified by execution" if conda else ""
        print(f"environment matches {args.file.name}: "
              f"python {python}, {len(pins)} pinned package(s){native}")
    return 0


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    # Make environment drift observable to shell launchers and CI.
    raise SystemExit(main())
