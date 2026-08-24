"""Decide `TYPE-001` by running both type checkers over the reference package.

`TYPE-001` asks that a strict checker run and pass. Until this file existed it
was tagged `external` and the tool ran nowhere, because this repository had no
`src/` layout to check. `enforce/fixtures/reference/` is that layout, so the rule
finally has a subject.

**Both checkers, not one.** `discipline/meta/OPEN.md` `OPEN-005` decided this: a
claim that survives mypy *and* pyright is stronger than one that survives either.
The decision earned itself on first contact -- pyright in strict mode found two
defects in the reference that `mypy --strict` reported clean, a `frozenset` whose
element type nobody knew and a redundant `isinstance` hiding an exhaustiveness
guard that was doing nothing.

**The vacuity guard is the point.** Both tools exit 0 when pointed at nothing:
mypy prints "Success: no issues found in 0 source files" and pyright reports
`filesAnalyzed: 0`. A gate step that cannot tell that from success is a gate step
that decides nothing, which is the defect this whole phase exists to remove. So
the file count is parsed and compared against `MINIMUM_FILES`.

    python tools/type_gate.py
    python tools/type_gate.py --root path/to/tree --minimum 26
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from pathlib import Path
from typing import Final

## The repository root, one level up from `tools/`.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent

## The tree both checkers are pointed at.
DEFAULT_ROOT: Final = REPO_ROOT / "enforce" / "fixtures" / "reference"

## The package inside `<root>/src` to check. mypy is given the package name
## rather than a path so that `--explicit-package-bases` can resolve the
## intra-package imports; given a bare directory it reports every one of them as
## `import-not-found`, which looks like 38 findings and is really one.
PACKAGE: Final = "refpkg"

## How many files each checker must analyse before a clean verdict is believed.
MINIMUM_FILES: Final = 20

## mypy's closing line, which carries the file count on success and on failure.
_MYPY_COUNT = re.compile(r"in (\d+) source files?")

## Exit status when both checkers pass over enough files.
EXIT_OK: Final = 0

## Exit status when either reports a finding, analyses too little, or is absent.
EXIT_FAILED: Final = 1


def run_mypy(root: Path, *, config: Path | None = None) -> tuple[bool, int, str]:
    """Run `mypy --strict` over the package.

    @param root the tree holding `src/`
    @param config explicit project configuration, or None for root discovery
    @return whether it passed, how many files it analysed, and its output
    """
    # Build the child-process environment with the governed source root on its import path.
    environment = dict(os.environ, MYPYPATH=str(root / "src"))
    # Each arguments element is one process argument string; invocation order is preserved.
    arguments = [sys.executable, "-m", "mypy"]
    # Bind mypy to the project configuration only when that local file exists.
    if config is not None:
        arguments.extend(("--config-file", str(config.resolve())))
    arguments.extend(("--strict", "--explicit-package-bases", "-p", PACKAGE))
    finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        arguments,
        cwd=root, env=environment, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=600,
    )
    # Combine the checker's captured diagnostic streams without losing emission text.
    output = finished.stdout + finished.stderr
    # Extract mypy's analyzed-file count so a vacuous successful invocation still fails the gate.
    found = _MYPY_COUNT.search(output)
    # Return checker success, analyzed-file count, and diagnostics to the type gate.
    return finished.returncode == 0, int(found.group(1)) if found else 0, output


def run_pyright(root: Path) -> tuple[bool, int, str]:
    """Run pyright in strict mode over the package.

    Strictness comes from `pyrightconfig.json` beside the package rather than
    from a flag, because pyright has no `--strict`; the mode is configuration.

    @param root the tree holding `src/` and `pyrightconfig.json`
    @return whether it passed, how many files it analysed, and its output
    """
    # Execute pyright once and retain its JSON report plus any provisioning diagnostics.
    finished = subprocess.run(
        (sys.executable, "-m", "pyright", "--outputjson"),
        cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=900,
    )
    # pyright prints node-provisioning chatter before the JSON on a first run,
    # so the document is found rather than assumed to start at byte zero.
    start = finished.stdout.find("{")
    # Refuse checker output that contains no JSON report boundary.
    if start < 0:
        # Return checker failure with the unparseable captured output.
        return False, 0, finished.stdout + finished.stderr

    # Decode the located JSON suffix while keeping malformed checker output a red result.
    try:
        # Decode Pyright's report object before extracting its summary and diagnostics.
        report = json.loads(finished.stdout[start:])
    # Report malformed checker JSON with its localized decoder failure and original output.
    except json.JSONDecodeError as broken:
        # Return checker failure with the localized JSON decoding cause.
        return False, 0, f"pyright emitted no parseable report: {broken}"

    # Select the checker summary mapping that carries analyzed-file metrics.
    summary = report.get("summary", {})
    # Each problems element is one emitted error string; checker order is preserved.
    problems = [
        f"{d.get('file', '?')}: {d.get('message', '').splitlines()[0]}"
        # Project the current Pyright diagnostic record to one concise error line.
        for d in report.get("generalDiagnostics", [])
        if d.get("severity") == "error"
    ]
    # Return checker success, analyzed-file count, and diagnostics to the type gate.
    return not problems, int(summary.get("filesAnalyzed", 0)), "\n".join(problems)


def vendored() -> bool:
    """Whether this copy is a vendored `.agent/` rather than the upstream checkout.

    `tools/` ships whole, so an adopter gets this script *and* the reference
    package it defaults to. Running it there without saying so would type-check
    the shipped reference and report green about a package the adopter did not
    write -- a false pass, which is worse than no check.

    @return True when this file sits inside a vendored install
    """
    # Report whether this tool is executing from an installed `.agent` bundle.
    return REPO_ROOT.name == ".agent"


def main(argv: list[str] | None = None) -> int:
    """Run both checkers and report.

    @param argv the command line, or None to read `sys.argv`
    @return the process exit status
    """
    # Configure the command-line parser that defines this tool's invocation contract.
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--minimum", type=int, default=MINIMUM_FILES,
                        help="files each checker must analyse to count")
    # Capture the validated invocation arguments that govern this execution.
    arguments = parser.parse_args(argv)

    # Preserve whether the caller explicitly selected an adopter root before default resolution.
    root = arguments.root
    # Require an explicit target root when invoked from a vendored discipline installation.
    if root is None:
        # Refuse implicit target selection inside a vendored installation.
        if vendored():
            print("type gate: this is a vendored install, so the default target "
                  "would be the shipped reference package rather than your code. "
                  "Pass --root pointing at the tree holding your src/.",
                  file=sys.stderr)
            # Reject invocation outside a discoverable project unless the root was explicit.
            return EXIT_FAILED
        root = DEFAULT_ROOT

    # Refuse the target when its declared source directory is absent.
    if not (root / "src").is_dir():
        print(f"type gate: no src/ under {root}", file=sys.stderr)
        # Reject a project root that cannot provide the required typed source tree.
        return EXIT_FAILED

    # Start optimistic and downgrade the aggregate verdict on any checker failure or vacuity.
    status = EXIT_OK
    # Run both independent type checkers in the declared diagnostic order.
    for name, runner in (("mypy --strict", run_mypy), ("pyright strict", run_pyright)):
        # Capture checker success, analyzed-file count, and diagnostic output together.
        passed, analysed, output = runner(root)
        # Report the current mechanism when its checker outcome is unsuccessful.
        if not passed:
            print(f"type gate: {name} reported findings:\n{output[-2000:]}",
                  file=sys.stderr)
            # Preserve failure after reporting the checker's bounded diagnostic tail.
            status = EXIT_FAILED
        # Refuse a vacuous type-check run whose analyzed coverage is below the required floor.
        elif analysed < arguments.minimum:
            print(f"type gate: {name} analysed {analysed} file(s), below the "
                  f"{arguments.minimum} this tree holds. A checker pointed at "
                  f"nothing exits 0, which is not the same as passing.",
                  file=sys.stderr)
            # Preserve failure after reporting insufficient analyzed-file coverage.
            status = EXIT_FAILED
        else:
            print(f"type gate: {name} clean over {analysed} file(s)")
    return status


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    # Preserve the type gate's failure status for shell and CI callers.
    raise SystemExit(main())
