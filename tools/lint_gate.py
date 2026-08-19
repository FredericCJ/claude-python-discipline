"""Gate step 1: the lint findings may fall, never rise.

    python tools/lint_gate.py                     # the gate; exit 0 when nothing grew
    python tools/lint_gate.py --update-baseline --why "..."

`ruff check` over this repository reports a residual set of style findings that
predate the ratchet. Driving them to zero in one pass would be a large, risky and
mostly cosmetic change; leaving the gate red forever means nobody reads it, and a
gate nobody reads blocks nothing. This holds the middle: the exact set is
recorded, anything new is an error, and anything removed invites the ceiling down.

The design is `tools/v080_baseline.json`'s, deliberately. That ratchet records the
exact unbuilt (rule, mechanism) PAIRS rather than only a count, because raising a
single integer is the cheapest way to switch a ratchet off. The same reasoning
applies here and the same shape answers it.

**Protected codes never enter the baseline.** A ruff code named as the mechanism
behind a binding rule is not style debt -- it is the only thing deciding that
rule. `PROTECTED` below is checked before the baseline is consulted at all, so no
amount of ratcheting can switch a rule off by accident. Every one of them is at
zero as this ships; the guard exists for the day one is not.

Ruff is invoked through `sys.executable -m ruff` rather than by locating an
executable. A prior version of this repository's gate looked for `ruff` only
beside the interpreter, missed `Scripts/` on Windows, and SKIPPED ITSELF -- 766
findings went unseen behind a green run. The module form cannot miss.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

## Anchor for every path here, derived from this file rather than the working
## directory, so the gate behaves the same however it was invoked.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent

## The recorded ceiling. Kept beside this file, as `v080_baseline.json` is.
BASELINE_PATH: Final = REPO_ROOT / "tools" / "lint_baseline.json"

## Ruff codes that decide a binding rule, and therefore may never be baselined.
## Each is named as a mechanism in `discipline/law/` or in the comment beside the
## setting that selects it in `enforce/templates/pyproject.toml`. Baselining one
## would leave its rule reading as enforced while nothing decided it -- the exact
## dishonesty the corpus's `enforcement` field exists to expose.
PROTECTED: Final[frozenset[str]] = frozenset({
    "BLE001",   # DIAG-008, ERR-008 -- exceptions are never silently swallowed
    "C901",     # ARCH-016 -- module complexity stays within budget
    "D100", "D104",  # DOC-001, DOC-003 -- every element is documented
    "D205", "D400", "D415",  # DOC-006 -- a brief statement comes first
    "E722",     # DIAG-008 -- no bare except
    "G004", "G010",  # DIAG-012, DIAG-015 -- log arguments are deferred
    "PGH003",   # TYPE-003 -- escape hatches are narrow and justified
    "S101",     # DIAG-009, ERR-012 -- assertions are not validation
    "S110",     # DIAG-008 -- no try/except/pass
    "TRY300", "TRY301",  # ERR-009 -- the try body holds only what can fail
})


def run_ruff(root: Path) -> tuple[list[dict[str, object]], str]:
    """Every finding ruff reports over the repository, as data.

    @param root the repository to lint
    @return the findings, and ruff's own human-readable output for printing
    @throws RuntimeError when ruff cannot be run at all, which must never be
        mistaken for a clean tree
    """
    common = [sys.executable, "-m", "ruff", "check"]
    try:
        structured = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv, no shell
            [*common, "--output-format", "json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=root, check=False,
        )
        human = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv, no shell
            [*common, "--output-format", "concise"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=root, check=False,
        )
    except OSError as exc:
        message = f"could not run ruff: {exc}"
        raise RuntimeError(message) from exc
    if structured.returncode not in (0, 1):
        message = (
            f"ruff exited {structured.returncode}, which means it failed to run rather "
            f"than reporting a verdict:\n{structured.stderr[:400]}"
        )
        raise RuntimeError(message)
    return json.loads(structured.stdout or "[]"), human.stdout


def pairs_of(findings: Sequence[dict[str, object]], root: Path) -> set[tuple[str, str]]:
    """The findings reduced to what the ratchet compares.

    Line numbers are deliberately dropped: they churn on every edit above a
    finding and would make the baseline unreviewable. The count is what catches a
    second instance of a code already present in a file.

    @param findings ruff's structured output
    @param root the repository root, for expressing paths portably
    @return each (file, code) pair, POSIX-relative so the file reads the same on
        either platform
    """
    pairs: set[tuple[str, str]] = set()
    for finding in findings:
        code = str(finding.get("code") or "")
        raw = str(finding.get("filename") or "")
        if not code or not raw:
            continue
        path = Path(raw)
        try:
            name = path.relative_to(root).as_posix()
        except ValueError:
            name = path.as_posix()
        pairs.add((name, code))
    return pairs


def load_baseline(path: Path = BASELINE_PATH) -> tuple[int, set[tuple[str, str]]]:
    """The recorded ceiling.

    An absent baseline reads as an empty one, which makes the very first run
    demand a clean tree rather than silently accepting whatever is there.

    @param path the baseline file
    @return the recorded finding count and the recorded pairs
    """
    if not path.exists():
        return 0, set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return int(data.get("count", 0)), {(f, c) for f, c in data.get("pairs", [])}


def write_baseline(
    count: int, pairs: set[tuple[str, str]], why: str, path: Path = BASELINE_PATH,
) -> None:
    """Record a new ceiling, with the reason it moved.

    @param count the finding total being recorded
    @param pairs the exact (file, code) pairs being recorded
    @param why why the ceiling is moving, which is never optional
    @param path the baseline file to write
    """
    payload = {
        "generated_by": "tools/lint_gate.py --update-baseline",
        "note": (
            "Ratchet ceiling for gate step 1. lint_gate.py fails when a (file, code) "
            "pair appears that is not recorded here, or when the total rises. Move it "
            'with `python tools/lint_gate.py --update-baseline --why "..."`, never by '
            "hand -- the pairs must stay exactly what the tool itself measured. A code "
            "in lint_gate.PROTECTED is refused before this file is consulted."
        ),
        "count": count,
        "why": why,
        "pairs": sorted([list(pair) for pair in pairs]),
    }
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def judge(
    pairs: set[tuple[str, str]], count: int,
    recorded_pairs: set[tuple[str, str]], recorded_count: int,
) -> tuple[list[str], list[str]]:
    """Decide the run against the ceiling.

    @param pairs the (file, code) pairs found now
    @param count how many findings were reported now
    @param recorded_pairs the pairs the baseline records
    @param recorded_count the total the baseline records
    @return the errors that fail the gate, and the notices that do not
    """
    errors: list[str] = []
    notices: list[str] = []

    protected = sorted(f"{name}: {code}" for name, code in pairs if code in PROTECTED)
    errors += [f"protected code, never baselined -- {entry}" for entry in protected]

    fresh = sorted(pairs - recorded_pairs)
    errors += [f"new finding -- {name}: {code}" for name, code in fresh
               if code not in PROTECTED]

    if count > recorded_count and not fresh:
        errors.append(
            f"finding total rose from {recorded_count} to {count} with no new "
            f"(file, code) pair: an existing code gained instances"
        )

    gone = sorted(recorded_pairs - pairs)
    if gone:
        notices.append(f"{len(gone)} recorded pair(s) no longer found")
    if count < recorded_count:
        notices.append(f"total fell from {recorded_count} to {count}")
    return errors, notices


def main(argv: Sequence[str] | None = None) -> int:
    """Run ruff, judge it against the ceiling, and report.

    @param argv the command-line arguments, or None to read `sys.argv`
    @return 0 when nothing grew, 1 when something did, 2 when ruff would not run
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update-baseline", action="store_true",
                        help="record the tree as it stands as the new ceiling")
    parser.add_argument("--why", help="required with --update-baseline")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)

    try:
        findings, human = run_ruff(args.root)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    pairs = pairs_of(findings, args.root)
    count = len(findings)

    if args.update_baseline:
        if not args.why:
            print("--update-baseline needs --why; an untraced ceiling is drift",
                  file=sys.stderr)
            return 2
        blocked = sorted(code for _, code in pairs if code in PROTECTED)
        if blocked:
            print("refusing to baseline a protected code: " + ", ".join(blocked),
                  file=sys.stderr)
            return 2
        write_baseline(count, pairs, args.why, args.root / "tools" / "lint_baseline.json")
        print(f"recorded {count} finding(s) across {len(pairs)} (file, code) pair(s)")
        return 0

    recorded_count, recorded_pairs = load_baseline(args.root / "tools" / "lint_baseline.json")
    errors, notices = judge(pairs, count, recorded_pairs, recorded_count)

    if errors:
        print(human, end="" if human.endswith("\n") else "\n")
        print(f"lint gate: {len(errors)} finding(s) above the recorded ceiling",
              file=sys.stderr)
        for entry in errors:
            print(f"  {entry}", file=sys.stderr)
        print('  fix them, or move the ceiling with --update-baseline --why "..."',
              file=sys.stderr)
        return 1

    for notice in notices:
        print(f"  {notice} -- lock it in with --update-baseline")
    print(f"lint gate: {count} finding(s), none above the recorded ceiling of "
          f"{recorded_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
