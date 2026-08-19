"""Decide whether each mechanism has been watched rejecting something.

`V080` counted whether a mechanism *exists*. This counts whether it
**discriminates**: for each rule, one declared mutation is applied to a throwaway
tree and the rule must be reported. A rule nobody has watched fire is a rule whose
mechanism might do nothing, and `ARCH-013` was exactly that for as long as it was
counted `mechanized`.

`D` is the number of rules covered. It is a ratchet in the same shape as
`tools/lint_gate.py` and `tools/v080_baseline.json`: it may rise, it may not fall,
and moving the floor takes `--update-baseline --why "..."`.

**Two failure directions, both fatal, and the second is the quiet one.**

* A declared mutation that does NOT provoke its rule is a broken claim — the entry
  says the mechanism catches this and it does not.
* A mutation that provokes its rule *while the unmutated reference is also dirty*
  proves nothing. So the conformant tree is checked first and must be silent; a
  green run over a tree that was already failing would credit the mechanism with
  a finding it did not earn.

    python tools/discrimination_gate.py
    python tools/discrimination_gate.py --update-baseline --why "..."
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Final

## The repository root, one level up from `tools/`.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent

## `enforce/` is not on the default path when this runs as a script. The root
## `conftest.py` does the same insert for pytest; this is the script's half.
if str(REPO_ROOT / "enforce") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "enforce"))

# These three sit below the path insert above deliberately: they live under
# `enforce/`, which is not importable until that line has run.
import discrimination  # ruff: ignore[module-import-not-at-top-of-file]
from checks.__main__ import discover  # ruff: ignore[module-import-not-at-top-of-file]
from fixtures import broken_copy, reference_root  # ruff: ignore[module-import-not-at-top-of-file]

if TYPE_CHECKING:
    from collections.abc import Sequence

## The committed floor `D` ratchets against, beside this file for the same reason
## the other baselines are: a ceiling that travels separately from its tool can be
## edited without the tool noticing.
BASELINE_PATH: Final = Path(__file__).resolve().parent / "discrimination_baseline.json"

## Exit status when every declared mutation provoked its rule and `D` held.
EXIT_OK: Final = 0

## Exit status when a mutation failed to provoke, or `D` fell.
EXIT_FAILED: Final = 1


def findings_for(tree: Path, targets: Sequence[str]) -> set[str]:
    """Every rule id the checks report against one tree.

    Runs the whole check set rather than the one check the entry expects, because
    a mutation that provokes a *different* rule than the one declared is a fact
    worth seeing, and narrowing the run would hide it.

    @param tree the root to check
    @param targets paths under the root to point the checks at
    @return the rule ids reported, empty when the tree is clean
    """
    paths = [tree / target for target in targets]
    present = [path for path in paths if path.exists()]
    reported: set[str] = set()
    for check in discover():
        reported.update(finding.rule_id for finding in check.run(present))
    return reported


def damaged(mutation: discrimination.Mutation, workspace: Path) -> Path:
    """Build the tree this mutation describes.

    @param mutation the declared mutation
    @param workspace a fresh directory to build in
    @return the damaged tree's root
    @throws FileNotFoundError when a path named for damage is not there, which
        `broken_copy` raises rather than silently leaving the tree intact
    """
    written = dict(mutation.write)
    if mutation.base == "empty":
        root = workspace / "tree"
        for name, contents in written.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8")
        return root
    return broken_copy(workspace, drop=mutation.drop, write=written or None,
                       replace=mutation.replace)


def fails_against(node: str, root: Path) -> bool:
    """Whether one fitness test fails when pointed at a damaged tree.

    The suites read their subject through `fixtures.reference_root()`, which
    honours `DISCIPLINE_REFERENCE`. Setting it here is what lets a fitness-decided
    rule be held to the same standard as a check-decided one: the mechanism must
    be watched rejecting something.

    A node that ERRORS rather than fails counts as failing. Either way the tree
    did not pass, and distinguishing them would credit a broken suite as a
    working one.

    @param node the pytest node id to run
    @param root the damaged tree the suite should reject
    @return True when pytest reported the node as not passing
    """
    finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        (sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "-x", node),
        cwd=REPO_ROOT, env={**os.environ, "DISCIPLINE_REFERENCE": str(root)},
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False, timeout=600,
    )
    return finished.returncode != 0


def provoke(mutation: discrimination.Mutation, workspace: Path) -> set[str]:
    """Apply one mutation and report which rules its mechanism then reports.

    @param mutation the declared mutation
    @param workspace a fresh directory to build the damaged tree in
    @return the rule ids observed rejecting the damaged tree
    @throws FileNotFoundError when a path named for damage is not there
    """
    root = damaged(mutation, workspace)
    if mutation.node:
        return {mutation.rule_id} if fails_against(mutation.node, root) else set()
    return findings_for(root, mutation.targets)


def run() -> tuple[int, list[str], set[str]]:
    """Apply every declared mutation and report which rules were provoked.

    @return the exit status, one complaint per broken claim, and the rules that
        were genuinely provoked
    """
    complaints: list[str] = []
    provoked: set[str] = set()

    reference = reference_root()
    dirty = findings_for(reference, ("src", "tests"))
    if dirty:
        complaints.append(
            f"the conformant reference already reports {', '.join(sorted(dirty))}. "
            f"Every result below would be crediting a mechanism with a finding it "
            f"did not earn."
        )
        return EXIT_FAILED, complaints, provoked

    for mutation in discrimination.MUTATIONS:
        workspace = Path(tempfile.mkdtemp(prefix="discrim-"))
        try:
            reported = provoke(mutation, workspace)
        except FileNotFoundError as absent:
            complaints.append(
                f"{mutation.rule_id}: the mutation names {absent}, which is not in "
                f"the tree -- the entry has drifted from the fixture"
            )
            continue
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

        if mutation.rule_id in reported:
            provoked.add(mutation.rule_id)
        else:
            others = ", ".join(sorted(reported)) or "nothing at all"
            complaints.append(
                f"{mutation.rule_id}: {mutation.summary} -- and the checks reported "
                f"{others}. The entry claims this mechanism catches this; it does not."
            )
    return (EXIT_FAILED if complaints else EXIT_OK), complaints, provoked


def read_baseline() -> dict[str, object]:
    """The committed floor, or an empty one when nothing has been recorded.

    @return the baseline document
    """
    if not BASELINE_PATH.is_file():
        return {"count": 0, "rules": [], "why": ""}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    """Run every mutation, compare `D` against its floor, and report.

    @param argv the command line, or None to read `sys.argv`
    @return the process exit status
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update-baseline", action="store_true",
                        help="record the current coverage as the new floor")
    parser.add_argument("--why", help="required with --update-baseline")
    arguments = parser.parse_args(argv)

    # Argument validation before the work, not after. The matrix takes about
    # three and a half seconds; refusing a missing `--why` afterwards spent all
    # of it to reach a conclusion available immediately.
    if arguments.update_baseline and not arguments.why:
        print("--update-baseline requires --why", file=sys.stderr)
        return EXIT_FAILED

    status, complaints, provoked = run()
    for complaint in complaints:
        print(f"  {complaint}", file=sys.stderr)

    baseline = read_baseline()
    floor = int(baseline.get("count", 0))

    if arguments.update_baseline:
        if status != EXIT_OK:
            print("refusing to move the floor while a declared mutation is broken",
                  file=sys.stderr)
            return EXIT_FAILED
        BASELINE_PATH.write_text(
            json.dumps({
                "generated_by": "tools/discrimination_gate.py --update-baseline",
                "note": "D -- rules with at least one mutation observed provoking "
                        "them. May rise, never fall. The entries are in "
                        "enforce/discrimination.py and are meant to be read; the "
                        "count alone says nothing about whether they are good.",
                "count": len(provoked),
                "rules": sorted(provoked),
                "why": arguments.why,
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"discrimination: floor recorded at D={len(provoked)} -- {arguments.why}")
        return EXIT_OK

    if status != EXIT_OK:
        print(f"discrimination: {len(complaints)} broken claim(s)", file=sys.stderr)
        return EXIT_FAILED
    if len(provoked) < floor:
        lost = ", ".join(sorted(set(baseline.get("rules", [])) - provoked))
        print(f"discrimination: D fell from {floor} to {len(provoked)} -- {lost} no "
              f"longer provoked. A ratchet may only rise.", file=sys.stderr)
        return EXIT_FAILED
    print(f"discrimination: D={len(provoked)}, floor {floor}, "
          f"{len(discrimination.MUTATIONS)} mutation(s) all provoking their rule")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
