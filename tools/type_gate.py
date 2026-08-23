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
    environment = dict(os.environ, MYPYPATH=str(root / "src"))
    arguments = [sys.executable, "-m", "mypy"]
    if config is not None:
        arguments.extend(("--config-file", str(config.resolve())))
    arguments.extend(("--strict", "--explicit-package-bases", "-p", PACKAGE))
    finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        arguments,
        cwd=root, env=environment, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=600,
    )
    output = finished.stdout + finished.stderr
    found = _MYPY_COUNT.search(output)
    return finished.returncode == 0, int(found.group(1)) if found else 0, output


def run_pyright(root: Path) -> tuple[bool, int, str]:
    """Run pyright in strict mode over the package.

    Strictness comes from `pyrightconfig.json` beside the package rather than
    from a flag, because pyright has no `--strict`; the mode is configuration.

    @param root the tree holding `src/` and `pyrightconfig.json`
    @return whether it passed, how many files it analysed, and its output
    """
    finished = subprocess.run(
        (sys.executable, "-m", "pyright", "--outputjson"),
        cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=900,
    )
    # pyright prints node-provisioning chatter before the JSON on a first run,
    # so the document is found rather than assumed to start at byte zero.
    start = finished.stdout.find("{")
    if start < 0:
        return False, 0, finished.stdout + finished.stderr

    try:
        report = json.loads(finished.stdout[start:])
    except json.JSONDecodeError as broken:
        return False, 0, f"pyright emitted no parseable report: {broken}"

    summary = report.get("summary", {})
    problems = [
        f"{d.get('file', '?')}: {d.get('message', '').splitlines()[0]}"
        for d in report.get("generalDiagnostics", [])
        if d.get("severity") == "error"
    ]
    return not problems, int(summary.get("filesAnalyzed", 0)), "\n".join(problems)


def vendored() -> bool:
    """Whether this copy is a vendored `.agent/` rather than the upstream checkout.

    `tools/` ships whole, so an adopter gets this script *and* the reference
    package it defaults to. Running it there without saying so would type-check
    the shipped reference and report green about a package the adopter did not
    write -- a false pass, which is worse than no check.

    @return True when this file sits inside a vendored install
    """
    return REPO_ROOT.name == ".agent"


def main(argv: list[str] | None = None) -> int:
    """Run both checkers and report.

    @param argv the command line, or None to read `sys.argv`
    @return the process exit status
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--minimum", type=int, default=MINIMUM_FILES,
                        help="files each checker must analyse to count")
    arguments = parser.parse_args(argv)

    root = arguments.root
    if root is None:
        if vendored():
            print("type gate: this is a vendored install, so the default target "
                  "would be the shipped reference package rather than your code. "
                  "Pass --root pointing at the tree holding your src/.",
                  file=sys.stderr)
            return EXIT_FAILED
        root = DEFAULT_ROOT

    if not (root / "src").is_dir():
        print(f"type gate: no src/ under {root}", file=sys.stderr)
        return EXIT_FAILED

    status = EXIT_OK
    for name, runner in (("mypy --strict", run_mypy), ("pyright strict", run_pyright)):
        passed, analysed, output = runner(root)
        if not passed:
            print(f"type gate: {name} reported findings:\n{output[-2000:]}",
                  file=sys.stderr)
            status = EXIT_FAILED
        elif analysed < arguments.minimum:
            print(f"type gate: {name} analysed {analysed} file(s), below the "
                  f"{arguments.minimum} this tree holds. A checker pointed at "
                  f"nothing exits 0, which is not the same as passing.",
                  file=sys.stderr)
            status = EXIT_FAILED
        else:
            print(f"type gate: {name} clean over {analysed} file(s)")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
