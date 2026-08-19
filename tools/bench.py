"""Measure what the corpus is for: recovery cost from a program's own output.

Every other number this repository produces measures **conformance** -- `V080`,
`D`, the mechanism census, lint findings, documentation coverage. All of them ask
whether the corpus obeys itself. None asks whether it *helps*.

The Prime Directive claims an agent meeting a defect reaches the fix from the
program's own output without re-reading the codebase. `R` is that claim, measured:
given only what a failing program printed, does the navigator reach a rule that
governs the fix, at what hop distance, and at what reading cost in tokens.

**Deterministic, with no agent in the loop.** The temptation is to measure a real
agent solving a real defect; that is noisy, expensive, and unrepeatable. What is
measured instead is the reading plan the navigator produces -- which is the thing
the corpus actually controls, and it is the same on every run.

**Never gated.** A benchmark wired into a gate becomes a target, and a targeted
benchmark stops measuring. `R` is reported. It moves or it does not, and if it
does not after a change meant to move it, that is a finding about the change.

**The derived set is the number.** Four of the twelve defects print an output that
quotes a rule id; those resolve at zero hops by string match and measure nothing.
They are the control, reported apart. See `enforce/defects.py`.

    python tools/bench.py
    python tools/bench.py --json
    python tools/bench.py --compare tools/bench_baseline.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

## The repository root, one level up from `tools/`.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent

## `enforce/` is not importable when this runs as a script.
if str(REPO_ROOT / "enforce") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "enforce"))

# Below the path insert deliberately; the module lives under `enforce/`.
import defects  # ruff: ignore[module-import-not-at-top-of-file]

if TYPE_CHECKING:
    from collections.abc import Sequence

## Where a recorded run is kept, so a later release can be compared against it.
BASELINE_PATH: Final = Path(__file__).resolve().parent / "bench_baseline.json"

## The hop distance at which a rule was named outright rather than derived. Zero
## is the Prime Directive's ideal: the output said which contract it broke.
NAMED_OUTRIGHT: Final = 0


def plan_for(output: str) -> dict[str, object]:
    """The reading plan the navigator produces for one program output.

    Shelled out rather than imported, because the CLI is what an agent actually
    invokes and a benchmark that exercises a different path measures a different
    thing.

    @param output exactly what the failing program printed
    @return the navigator's JSON payload, empty when it could not answer
    """
    finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        (sys.executable, "tools/nav.py", "--json", "context", "--error", output),
        cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=180,
    )
    if finished.returncode != 0 or not finished.stdout.strip():
        return {}
    try:
        return json.loads(finished.stdout)
    except json.JSONDecodeError:
        return {}


def measure(defect: defects.Defect) -> dict[str, object]:
    """What it costs to reach a governing rule for one defect.

    @param defect the frozen entry to measure
    @return the defect's id, whether a governing rule was reached, the hop
        distance of the nearest one, and the planned reading cost in tokens
    """
    payload = plan_for(defect.output)
    seeds = payload.get("seeds", []) if payload else []
    reached = [
        seed for seed in seeds
        if isinstance(seed, dict) and seed.get("id") in defect.governs
    ]
    return {
        "defect": defect.defect_id,
        "summary": defect.summary,
        "names_a_rule": defect.names_a_rule,
        "found": bool(reached),
        "hops": min((int(s.get("hops", 99)) for s in reached), default=None),
        "tokens": int(payload.get("tokens_planned", 0)) if payload else 0,
        "tokens_if_all": int(payload.get("tokens_if_all", 0)) if payload else 0,
    }


def summarize(results: Sequence[dict[str, object]]) -> dict[str, object]:
    """Roll one run up into the figures worth comparing between releases.

    Reported over the derived set and the control set separately. Averaging them
    together would let four trivially-resolved outputs carry eight hard ones.

    @param results one entry per defect
    @return hit rate, median cost and median hops, for each set
    """
    summary: dict[str, object] = {}
    for name, wanted in (("derived", False), ("control", True)):
        group = [r for r in results if r["names_a_rule"] is wanted]
        hits = [r for r in group if r["found"]]
        summary[name] = {
            "defects": len(group),
            "found": len(hits),
            "hit_rate": round(len(hits) / len(group), 3) if group else 0.0,
            "median_tokens": (statistics.median(int(r["tokens"]) for r in hits)
                              if hits else None),
            "median_hops": (statistics.median(int(r["hops"]) for r in hits)
                            if hits else None),
            "named_outright": sum(1 for r in hits if r["hops"] == NAMED_OUTRIGHT),
        }
    return summary


def run() -> dict[str, object]:
    """Measure every frozen defect.

    @return the per-defect results and their summary
    """
    results = [measure(defect) for defect in defects.DEFECTS]
    return {"results": results, "summary": summarize(results)}


def render(report: dict[str, object]) -> str:
    """The run as a person would want to read it.

    @param report what `run` produced
    @return the printable text
    """
    lines = ["defect  found  hops  tokens  summary"]
    for entry in report["results"]:  # type: ignore[union-attr]
        mark = "yes" if entry["found"] else "NO "
        hops = "-" if entry["hops"] is None else str(entry["hops"])
        lines.append(f"{entry['defect']:7s} {mark:5s} {hops:>4s}  "
                     f"{entry['tokens']:6d}  {entry['summary'][:52]}")
    summary = report["summary"]
    for name in ("derived", "control"):
        part = summary[name]  # type: ignore[index]
        cost = part["median_tokens"]
        lines.append(
            f"\n{name}: {part['found']}/{part['defects']} reached, "
            f"median {cost if cost is not None else 'n/a'} tokens, "
            f"median {part['median_hops']} hop(s), "
            f"{part['named_outright']} named outright"
        )
    return "\n".join(lines)


def compare(report: dict[str, object], baseline: dict[str, object]) -> list[str]:
    """How this run differs from a recorded one.

    @param report the current run
    @param baseline a previously recorded run
    @return one line per figure that moved, empty when nothing did
    """
    moved: list[str] = []
    for name in ("derived", "control"):
        now = report["summary"][name]      # type: ignore[index]
        was = baseline.get("summary", {}).get(name, {})
        moved.extend(
            f"{name}.{field}: {was.get(field)} -> {now.get(field)}"
            for field in ("found", "median_tokens", "median_hops", "named_outright")
            if was.get(field) != now.get(field)
        )
    return moved


def main(argv: list[str] | None = None) -> int:
    """Measure, report, and optionally record or compare.

    Always returns 0 when the run completed. `R` is not a gate: a benchmark that
    fails a build is a benchmark someone will make pass.

    @param argv the command line, or None to read `sys.argv`
    @return 0 when the run completed, 1 when it could not
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="emit the raw report")
    parser.add_argument("--record", action="store_true",
                        help="write this run as the recorded baseline")
    parser.add_argument("--compare", type=Path, nargs="?", const=BASELINE_PATH,
                        help="report how this run differs from a recorded one")
    arguments = parser.parse_args(argv)

    report = run()

    if arguments.json:
        print(json.dumps(report, indent=2))
    else:
        print(render(report))

    if arguments.compare is not None:
        if not arguments.compare.is_file():
            print(f"no recorded run at {arguments.compare}", file=sys.stderr)
            return 1
        moved = compare(report, json.loads(
            arguments.compare.read_text(encoding="utf-8")))
        print("\n" + ("\n".join(f"  {line}" for line in moved)
                      if moved else "  nothing moved"))

    if arguments.record:
        BASELINE_PATH.write_text(json.dumps(report, indent=2) + "\n",
                                 encoding="utf-8")
        print(f"\nrecorded to {BASELINE_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
