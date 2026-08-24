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
# Prepend the local tools directory only when import resolution does not already contain it.
if str(REPO_ROOT / "enforce") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "enforce"))

# Below the path insert deliberately; the module lives under `enforce/`.
import defects  # ruff: ignore[module-import-not-at-top-of-file]

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Sequence

## Where a recorded run is kept, so a later release can be compared against it.
BASELINE_PATH: Final = Path(__file__).resolve().parent / "bench_baseline.json"

## The hop distance at which a rule was named outright rather than derived. Zero
## is the Prime Directive's ideal: the output said which contract it broke.
NAMED_OUTRIGHT: Final = 0


def plan_for(output: str, route: str = "context") -> dict[str, object]:
    """What the navigator answers for one program output, by one route.

    Shelled out rather than imported, because the CLI is what an agent actually
    invokes and a benchmark that exercises a different path measures a different
    thing.

    Two routes are measured and reported side by side rather than one replacing
    the other. `context` answers "what should I read" with a reading plan;
    `diagnose` answers "what broke and what do I do" with the rules themselves.
    Swapping the cheaper one in silently would show a fall in cost that was really
    a change of question.

    @param output exactly what the failing program printed
    @param route the subcommand to ask, `context` or `diagnose`
    @return the navigator's JSON payload, empty when it could not answer
    """
    # Invoke the navigator CLI with the exact defect output and selected route.
    finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        (sys.executable, "tools/nav.py", "--json", route, "--error", output),
        cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=180,
    )
    # Enter the failure path only when the subprocess reports a nonzero status.
    if finished.returncode != 0 or not finished.stdout.strip():
        # Failed or silent probes contribute no benchmark observation.
        return {}
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Successful probe output is a structured timing and routing observation.
        return json.loads(finished.stdout)
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except json.JSONDecodeError:
        # Malformed child output is unusable evidence, equivalent to an absent observation.
        return {}


def measure(defect: defects.Defect) -> dict[str, object]:
    """What it costs to reach a governing rule for one defect.

    @param defect the frozen entry to measure
    @return the defect's id, whether a governing rule was reached, the hop
        distance of the nearest one, and the planned reading cost in tokens
    """
    # Decode navigator field-name keys to their result values; mapping order is deliberately
    # unused.
    payload = plan_for(defect.output)
    # Select context-plan seed records, defaulting to none when navigation failed.
    seeds = payload.get("seeds", []) if payload else []
    # Each reached element is one navigator seed mapping whose rule id governs this defect;
    # navigator order is preserved.
    reached = [
        # Interpret the current seed as a candidate governing-rule record.
        seed for seed in seeds
        if isinstance(seed, dict) and seed.get("id") in defect.governs
    ]
    # Ask the diagnosis route the same defect question for a comparable direct answer.
    answer = plan_for(defect.output, route="diagnose")
    # Each answered element is one diagnosed rule mapping whose id governs this defect; answer
    # order is preserved.
    answered = [
        # Interpret the current rule mapping as a candidate diagnosis.
        rule for rule in (answer.get("rules", []) if answer else [])
        if isinstance(rule, dict) and rule.get("id") in defect.governs
    ]
    return {
        "defect": defect.defect_id,
        "summary": defect.summary,
        "names_a_rule": defect.names_a_rule,
        "found": bool(reached),
        # Choose the minimum hop count across every governing context seed.
        "hops": min((int(s.get("hops", 99)) for s in reached), default=None),
        "tokens": int(payload.get("tokens_planned", 0)) if payload else 0,
        "tokens_if_all": int(payload.get("tokens_if_all", 0)) if payload else 0,
        "diagnosed": bool(answered),
        "diagnose_tokens": int(answer.get("tokens", 0)) if answer else 0,
    }


def summarize(results: Sequence[dict[str, object]]) -> dict[str, object]:
    """Roll one run up into the figures worth comparing between releases.

    Reported over the derived set and the control set separately. Averaging them
    together would let four trivially-resolved outputs carry eight hard ones.

    @param results per-defect metric mappings in frozen defect order; each mapping
        uses metric-name keys and scalar values, and sequence order is preserved
    @return hit rate, median cost and median hops, for each set
    """
    # Map each benchmark-set name to its aggregate metric mapping; key order is deliberately
    # unused.
    summary: dict[str, object] = {}
    # Summarize the derived set before the named-rule control set in fixed report order.
    for name, wanted in (("derived", False), ("control", True)):
        # Each group element is one per-defect metric mapping for the selected set; original
        # defect order is preserved.
        group = [r for r in results if r["names_a_rule"] is wanted]
        # Each hits element is one reached context-plan metric mapping; original defect order is
        # preserved.
        hits = [r for r in group if r["found"]]
        # Store all aggregate metrics together after both population slices are known.
        summary[name] = {
            "defects": len(group),
            "found": len(hits),
            "hit_rate": round(len(hits) / len(group), 3) if group else 0.0,
            # Compute token median over reached context plans only.
            "median_tokens": (statistics.median(int(r["tokens"]) for r in hits)
                              if hits else None),
            # Compute hop median over reached context plans only.
            "median_hops": (statistics.median(int(r["hops"]) for r in hits)
                            if hits else None),
            # Count reached context plans whose output named the rule directly.
            "named_outright": sum(1 for r in hits if r["hops"] == NAMED_OUTRIGHT),
            # Count defects for which the diagnosis route reached a governing rule.
            "diagnosed": sum(1 for r in group if r.get("diagnosed")),
            "median_diagnose_tokens": (
                # Compute diagnosis cost only across successful diagnosis records.
                statistics.median(int(r["diagnose_tokens"]) for r in group
                                  if r.get("diagnosed"))
                # Use no median when the route diagnosed nothing in this set.
                if any(r.get("diagnosed") for r in group) else None),
        }
    return summary


def run() -> dict[str, object]:
    """Measure every frozen defect.

    @return the per-defect results and their summary
    """
    # Each results element is one metric mapping for a frozen defect; benchmark roster order is
    # preserved.
    results = [measure(defect) for defect in defects.DEFECTS]
    return {"results": results, "summary": summarize(results)}


def render(report: dict[str, object]) -> str:
    """The run as a person would want to read it.

    @param report benchmark field-name keys mapped to per-defect results and set
        summaries; mapping key order is deliberately unused
    @return the printable text
    """
    # Each lines element is one printable table or summary string; table-then-summary display
    # order is preserved.
    lines = ["defect  found  hops  context  diagnose  summary"]
    # Render each per-defect metric mapping in frozen defect order.
    for entry in report["results"]:  # type: ignore[union-attr]
        # Convert context reachability to the fixed-width human verdict marker.
        mark = "yes" if entry["found"] else "NO "
        # Display a dash when no governing context seed supplied a hop count.
        hops = "-" if entry["hops"] is None else str(entry["hops"])
        # Display diagnosis tokens only when that route reached a governing rule.
        answer = str(entry["diagnose_tokens"]) if entry["diagnosed"] else "-"
        lines.append(f"{entry['defect']:7s} {mark:5s} {hops:>4s}  "
                     f"{entry['tokens']:7d}  {answer:>8s}  {entry['summary'][:44]}")
    # Select the aggregate set summaries produced alongside the per-defect rows.
    summary = report["summary"]
    # Render derived then control summaries in fixed comparison order.
    for name in ("derived", "control"):
        # Select the current set's aggregate metric mapping.
        part = summary[name]  # type: ignore[index]
        # Isolate context median cost for the nullable human rendering.
        cost = part["median_tokens"]
        lines.append(
            f"\n{name}: {part['found']}/{part['defects']} reached, "
            f"median {cost if cost is not None else 'n/a'} tokens, "
            f"median {part['median_hops']} hop(s), "
            f"{part['named_outright']} named outright; "
            f"diagnose reached {part['diagnosed']}/{part['defects']} at "
            f"median {part['median_diagnose_tokens']} tok"
        )
    return "\n".join(lines)


def compare(report: dict[str, object], baseline: dict[str, object]) -> list[str]:
    """How this run differs from a recorded one.

    @param report current benchmark field-name keys mapped to results and summaries;
        mapping key order is deliberately unused
    @param baseline recorded benchmark field-name keys mapped to results and summaries;
        mapping key order is deliberately unused
    @return one line per figure that moved, empty when nothing did
    """
    # Each moved element is one change-description string for a metric; set then field order is
    # preserved.
    moved: list[str] = []
    # Compare derived then control summaries in fixed report order.
    for name in ("derived", "control"):
        # Select current aggregate metrics for the active benchmark set.
        now = report["summary"][name]      # type: ignore[index]
        # Select recorded aggregate metrics, defaulting to an empty first-run mapping.
        was = baseline.get("summary", {}).get(name, {})
        moved.extend(
            f"{name}.{field}: {was.get(field)} -> {now.get(field)}"
            # Compare each declared benchmark metric in stable presentation order.
            for field in ("found", "median_tokens", "median_hops", "named_outright",
                          "diagnosed", "median_diagnose_tokens")
            if was.get(field) != now.get(field)
        )
    return moved


def main(argv: list[str] | None = None) -> int:
    """Measure, report, and optionally record or compare.

    Always returns 0 when the run completed. `R` is not a gate: a benchmark that
    fails a build is a benchmark someone will make pass.

    @param argv the command line, or None to read `sys.argv`
    @return 0 when the run completed, 1 when it could not

    @par Effects
    Prints the selected report and, only with `--record`, replaces the benchmark
    baseline after measurement and optional comparison complete.
    """
    # Configure the command-line parser that defines this tool's invocation contract.
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="emit the raw report")
    parser.add_argument("--record", action="store_true",
                        help="write this run as the recorded baseline")
    parser.add_argument("--compare", type=Path, nargs="?", const=BASELINE_PATH,
                        help="report how this run differs from a recorded one")
    # Capture the validated invocation arguments that govern this execution.
    arguments = parser.parse_args(argv)

    # Measure the complete frozen defect roster before selecting presentation behavior.
    report = run()

    # Choose machine-readable JSON or the stable human table without changing measurements.
    if arguments.json:
        print(json.dumps(report, indent=2))
    else:
        print(render(report))

    # Compare the current measurements only when the caller supplied a baseline report.
    if arguments.compare is not None:
        # Reject comparison when the requested baseline is not a regular file.
        if not arguments.compare.is_file():
            print(f"no recorded run at {arguments.compare}", file=sys.stderr)
            # Return the aggregate process status to the command-line boundary.
            return 1
        # Compare current metrics against the decoded recorded report.
        moved = compare(report, json.loads(
            arguments.compare.read_text(encoding="utf-8")))
        # Print every changed metric, or make an unchanged comparison explicit.
        print("\n" + ("\n".join(f"  {line}" for line in moved)
                      if moved else "  nothing moved"))

    # Record mode publishes the complete report only after all output and comparison work.
    if arguments.record:
        # Replace the baseline with deterministic indented JSON and normalized newlines.
        BASELINE_PATH.write_text(json.dumps(report, indent=2) + "\n",
                                 encoding="utf-8", newline="\n")
        print(f"\nrecorded to {BASELINE_PATH.name}")
    # Return the aggregate process status to the command-line boundary.
    return 0


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    # Preserve benchmark validation failure as the caller-visible process status.
    raise SystemExit(main())
