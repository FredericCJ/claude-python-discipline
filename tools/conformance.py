"""How conformant an adopting repository is, and whether it is improving.

    python .agent/tools/conformance.py                    # judge against the baseline
    python .agent/tools/conformance.py report             # what to fix, and where
    python .agent/tools/conformance.py --update-baseline --why "..."

**Until v3.2 a repository that already existed could not adopt this discipline.**
`python -m checks` printed every finding and exited 1, with no baseline and no
ratchet, so the only tree that could ever go green was one written against the
rules from its first commit. Run against four independently written hexagonal
packages, it produced 1,082 findings. Nobody fixes 1,082 findings, and a gate
that cannot go green on day one is a gate that gets deleted on day two.

This is the same ratchet `tools/lint_gate.py` has held this repository's own
findings under since v1.1.0, pointed outward. The shape is proven and its failure
modes are already solved, so the interesting parts are the two places it differs.

## The baseline lives in `overrides/`, and that is load-bearing

`vendor.py` copies `discipline/`, `enforce/` and `tools/`. It does not copy
`overrides/`, which the installer creates once and never writes again. An
adopter's baseline therefore survives every upgrade of the discipline itself --
which it must, because a baseline silently reset by an upgrade would re-open
every finding the adopter had accepted, and the next upgrade would be declined.

That property is why `ALLOC-010` can bind without the corpus ever naming a model,
and it is the same property being used here.

## `PROTECTED` is checked BEFORE the baseline

Some rules exist to be enforced from the first commit or not at all. A repository
that baselines away a silently swallowed exception, or a secret reaching a log,
and then reports itself conformant has produced a number rather than a property.
Those rules are listed below and are never consulted against the baseline: a
violation is fatal on the day of adoption, and that is the point of adopting.

The line is between rules about **evidence being destroyed** and rules about
**structure an adopter has yet to build**. Only the first belongs here; the
second is ordinary migration work, and the ratchet is what carries it.

This mirrors `lint_gate.PROTECTED`, whose fifteen ruff codes may never enter that
baseline for the same reason. Every one of them was at zero when it shipped; the
guard exists for the day one is not.

## An absent baseline means NO RATCHET YET, never zero findings

`enforce/templates/allocation.toml` taught this the hard way: it shipped with
`"your-strongest-model"`, a value that RESOLVES, so copying the template and
changing nothing satisfied the rule it was meant to force an answer to. A missing
baseline here reports every finding and exits 1 -- the same behaviour as before
this file existed -- rather than treating silence as consent.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Final

## The repository root, one level up from `tools/`.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent

## `enforce/` is not on the default path when this runs as a script, and an
## adopter runs it from `.agent/tools/`. The root `conftest.py` does the same
## insert for pytest; this is the script's half.
# Prepend the local tools directory only when import resolution does not already contain it.
if str(REPO_ROOT / "enforce") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "enforce"))

from checks import project  # ruff: ignore[module-import-not-at-top-of-file]
from checks.__main__ import discover  # ruff: ignore[module-import-not-at-top-of-file]

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Sequence

    from checks import Finding

## Where an adopter's baseline lives, relative to the project root. Under
## `overrides/` because `vendor.py` never copies that directory, so upgrading the
## discipline cannot silently reset what the adopter accepted.
BASELINE_NAME: Final = "overrides/conformance.json"

## Rules that may never enter a baseline, whatever the finding count. Each is
## load-bearing for the Prime Directive -- a failure must be machine-diagnosable
## and machine-repairable from the program's own output -- and a repository that
## suppresses one has stopped being able to make that claim at all.
##
## Deliberately short, and shortened once already by measurement. A long
## protected set is a long list of reasons not to adopt, and the ratchet is what
## handles everything else.
##
## The line drawn here is between rules about EVIDENCE BEING DESTROYED and rules
## about STRUCTURE AN ADOPTER HAS YET TO BUILD. The first cannot be migrated
## towards, because once the evidence is gone no later tooling recovers it. The
## second is ordinary migration work and belongs in the baseline.
##
## `DIAG-002` was in this set until it was run against a real codebase, where it
## produced 17 violations on day one -- every one of them an error class that
## simply did not yet name a rule id. That is annotation work, not a destroyed
## diagnosis, and putting it here meant the repository most in need of the
## discipline was the one that could not adopt it.
##
## **Every entry must be a rule the AST checks can actually report.** `DIAG-001`
## and `ERR-008` were also in this set, and neither is decided by a check --
## `DIAG-001` by a fitness test, `ERR-008` by a ruff code -- so this tool would
## never have seen either, and two of the four guards could not have fired. That
## is the vacuity this repository exists to remove, reproduced inside the guard
## against it. `test_every_protected_rule_is_reportable` now holds the line.
PROTECTED: Final[frozenset[str]] = frozenset({
    "DIAG-008",   # exceptions are never silently swallowed -- the failure that
                  # produced no output at all, which no later tooling recovers
    "DIAG-009",   # assertions are not validation; `python -O` removes them, so
                  # the check is absent in exactly the build that matters
    "ERR-012",    # the same clause from the error side
    "DIAG-014",   # secrets and personal data never reach a log or an envelope --
                  # a leak accepted into a baseline is a leak that ships, and
                  # unlike every other finding here it cannot be undone later
})

## Exit status when the tree is clean, or every finding is baselined.
EXIT_OK: Final = 0

## Exit status when a finding is new, protected, or the count has risen.
EXIT_REGRESSED: Final = 1


def findings_for(paths: Sequence[Path]) -> list[Finding]:
    """Every finding the AST checks report over the given paths.

    @param paths files or directories to walk
        Each paths element represents one repository path; traversal order is preserved.
    @return the findings, in check-name then walk order
    """
    # Each collected element is one checker finding object; checker then source-walk order is
    # preserved.
    collected: list[Finding] = []
    # Resolve the adopter's project declaration once for every discovered checker.
    declaration = project.load(paths[0] if paths else Path.cwd())
    # Execute discovered checks in their stable mechanism-name order.
    for check in discover():
        # Bind the shared declaration before collecting this check's ordered findings.
        check.declaration = declaration
        collected.extend(check.run(list(paths)))
    # Return the findings, in check-name then walk order to the caller.
    return collected


def pairs_of(findings: Sequence[Finding], root: Path) -> set[tuple[str, str]]:
    """The `(file, rule)` pairs a finding set covers.

    Pairs rather than whole findings, for the reason `lint_gate.pairs_of` gives:
    recording a line number would invalidate the baseline on the first unrelated
    edit and make it unreviewable. The COUNT is what catches a new finding in a
    file that already had one.

    @param findings sequence whose each element is one finding object; checker
        then source-walk order is preserved during reduction
    @param root the tree they were reported against, for relative paths
    @return one pair per distinct file and rule
    """
    # Collect unique `(relative path, rule id)` tuple elements; set order is deliberately
    # unordered.
    pairs: set[tuple[str, str]] = set()
    # Reduce findings in checker order even though the resulting set intentionally discards it.
    for finding in findings:
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            # Prefer a portable project-relative path for stable baselines.
            name = finding.path.relative_to(root).as_posix()
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except ValueError:
            # Preserve an external finding as an absolute POSIX path when confinement fails.
            name = finding.path.as_posix()
        pairs.add((name, finding.rule_id))
    # Return one pair per distinct file and rule to the caller.
    return pairs


def load_baseline(path: Path) -> tuple[int, set[tuple[str, str]]] | None:
    """The recorded count and pairs, or None when nothing has been recorded.

    None and a zero baseline mean different things, and conflating them is the
    defect `enforce/templates/allocation.toml` shipped: a template that satisfies
    its own rule unedited. An absent baseline is "no ratchet yet", and the caller
    reports everything.

    @param path the baseline file
    @return the count and pairs, or None when the file is absent or unreadable
    """
    # An absent or non-file baseline means the adopter has not established a ratchet.
    if not path.is_file():
        # Return the count and pairs, or None when the file is absent or unreadable to the
        # caller.
        return None
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Decode baseline field-name keys to count, pair, and audit-note values.
        data = json.loads(path.read_text(encoding="utf-8"))
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (OSError, json.JSONDecodeError):
        # Return the count and pairs, or None when the file is absent or unreadable to the
        # caller.
        return None
    # Restore the recorded count and an unordered set of `(file, rule)` tuple elements.
    return int(data.get("count", 0)), {(f, c) for f, c in data.get("pairs", [])}


def write_baseline(path: Path, count: int, pairs: set[tuple[str, str]],
                   why: str) -> None:
    """Record the current findings as the accepted floor.

    @param path the baseline file, created with its parent if absent
    @param count how many findings were reported
    @param pairs the exact `(file, rule)` pairs behind that count
        Each element is one `(relative file, rule id)` tuple; set order is
        deliberately unordered and serialization sorts it.
    @param why what is being accepted and on what understanding

    @par Effects
    Creates the parent directory when absent, then replaces the baseline with a
    deterministic sorted snapshot and its mandatory audit reason.
    """
    # Establish the adopter-owned override directory before publishing the baseline.
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace the complete baseline only after count, pairs, and audit reason are available.
    path.write_text(
        json.dumps({
            "generated_by": "python .agent/tools/conformance.py --update-baseline",
            "note": "Findings this repository has accepted for now. The count may "
                    "fall and never rise; a new (file, rule) pair fails whatever "
                    "the count does. PROTECTED rules are checked before this file "
                    "is read and can never appear in it. Project-owned: vendor.py "
                    "does not copy overrides/, so upgrading the discipline leaves "
                    "this alone.",
            "count": count,
            "pairs": sorted(pairs),
            "why": why,
        }, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def judge(findings: Sequence[Finding], root: Path,
          baseline: tuple[int, set[tuple[str, str]]] | None) -> list[str]:
    """Compare a finding set against the baseline and say what is wrong.

    Order matters and is the whole design. `PROTECTED` is evaluated FIRST, before
    the baseline is read at all, so no amount of ratcheting can switch off a rule
    the Prime Directive rests on.

    @param findings sequence whose each element is one finding object; checker
        then source-walk order is preserved for protected diagnostics
    @param root the tree they were reported against
    @param baseline the recorded floor, or None when there is no ratchet yet
    @return one complaint per regression, empty when the tree holds
    """
    # Each complaints element is one protected-rule diagnostic string; original finding order is
    # preserved before any ratchet read.
    complaints = [
        f"{finding.path.name}:{finding.line}: {finding.rule_id} is protected and "
        f"cannot be baselined -- {finding.message}"
        # Retain only findings whose rule can never enter an adopter baseline.
        for finding in findings if finding.rule_id in PROTECTED
    ]
    # Return protected failures immediately so no baseline can mask them.
    if complaints:
        # Return one complaint per regression, empty when the tree holds to the caller.
        return complaints

    # Use the absence path when baseline has no available value.
    if baseline is None:
        # Handle the non-empty or enabled findings state.
        if findings:
            complaints.append(
                f"{len(findings)} finding(s) and no baseline recorded. Fix them, "
                f'or accept them for now with --update-baseline --why "...".'
            )
        # Return one complaint per regression, empty when the tree holds to the caller.
        return complaints

    # Split the recorded ceiling into total-count and distinct-pair dimensions.
    recorded_count, recorded_pairs = baseline
    # Compute unordered current pairs absent from the accepted baseline.
    fresh = pairs_of(findings, root) - recorded_pairs
    # Report new file/rule identities before considering total-count growth.
    if fresh:
        # Sort fresh path/rule tuples for a deterministic actionable diagnostic.
        listed = ", ".join(f"{name}: {rule}" for name, rule in sorted(fresh))
        complaints.append(f"{len(fresh)} new (file, rule) pair(s) -- {listed}")
    # Catch additional instances hidden behind already recorded file/rule identities.
    elif len(findings) > recorded_count:
        complaints.append(
            f"finding total rose from {recorded_count} to {len(findings)} with no "
            f"new (file, rule) pair: an existing rule gained instances"
        )
    # Return one complaint per regression, empty when the tree holds to the caller.
    return complaints


def render_report(findings: Sequence[Finding], root: Path,
                  baseline: tuple[int, set[tuple[str, str]]] | None) -> str:
    """Say how conformant the tree is, and where the cheapest progress is.

    Adoption stalls when a thousand findings look like one undifferentiated wall,
    so the last section names the single rule-and-module pair holding the most
    findings. That is the one place where an afternoon's work moves the number.

    @param findings sequence whose each element is one finding object; checker
        then source-walk order is preserved for detailed examples
    @param root the tree they were reported against
    @param baseline the recorded floor, or None when there is no ratchet yet
    @return the report, ready to print
    """
    # Each lines element is one printable report string; overview, breakdown, then recommendation
    # order is preserved.
    lines = [f"conformance: {len(findings)} finding(s) over {root}"]

    # Use the available-value path only when baseline is present.
    if baseline is not None:
        # Split the recorded baseline into count and unordered pair dimensions.
        recorded_count, recorded_pairs = baseline
        # Reduce current findings to the same stable pair identity used by the baseline.
        current = pairs_of(findings, root)
        # Append baseline, cleared, and new-pair summaries in that fixed order.
        lines += [
            f"  baseline   {recorded_count} finding(s), {len(recorded_pairs)} pair(s)",
            f"  cleared    {len(recorded_pairs - current)} pair(s)",
            f"  new        {len(current - recorded_pairs)} pair(s)",
        ]
    else:
        lines.append("  no baseline recorded -- every finding below is unaccepted")

    # Each protected element is one protected finding object; original checker order is
    # preserved for bounded examples.
    protected = [f for f in findings if f.rule_id in PROTECTED]
    lines.append(f"  protected  {len(protected)} violation(s), which no baseline covers")
    # Append at most ten protected location/rule strings in finding order.
    lines += [f"    {f.path.name}:{f.line}: {f.rule_id}" for f in protected[:10]]

    # Count findings by rule-id key; first-seen ordering feeds deterministic tie handling.
    by_rule = Counter(f.rule_id for f in findings)
    lines.append("\nby rule:")
    # Append the twelve most frequent rule/count pairs in descending frequency order.
    lines += [f"  {rule:12s} {count:5d}" for rule, count in by_rule.most_common(12)]

    # Count non-protected findings by `(rule id, parent path)` concentration key.
    concentrated = Counter(
        # Preserve one concentration record per non-protected finding.
        (f.rule_id, f.path.parent.as_posix()) for f in findings
        if f.rule_id not in PROTECTED
    )
    # Recommend a target only when at least one migratable finding exists.
    if concentrated:
        # Select the most concentrated rule/module pair and its instance count.
        (rule, where), count = concentrated.most_common(1)[0]
        # Append the recommendation and rationale as one ordered report section.
        lines += [
            "\ncheapest next target:",
            f"  {rule} in {where} -- {count} finding(s) of one kind in one place.",
            "  A rule cleared in one module is a rule that can be cleared in the",
            "  next; a thousand scattered findings are where adoption stops.",
        ]
    # Return the report, ready to print to the caller.
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the checks over an adopting tree and judge or report.

    @param argv the command line, or None to read `sys.argv`
    @return the process exit status
    """
    # The verb is split off before argparse sees it. An optional positional verb
    # and a variadic positional path list are genuinely ambiguous to argparse,
    # which resolved `conformance.py src/` by trying to read `src/` as the verb
    # and exiting 2. Two positionals, one grammar, one of them wins; this makes
    # the choice explicit rather than leaving it to argument order.
    argument_list = list(sys.argv[1:] if argv is None else argv)
    command = "judge"
    if argument_list and argument_list[0] in {"judge", "report"}:
        # Remove the recognized verb before argparse processes the remaining path grammar.
        command = argument_list.pop(0)

    # Configure the command-line parser that defines this tool's invocation contract.
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd(),
                        help="the project root; the baseline is resolved under it")
    parser.add_argument("--update-baseline", action="store_true",
                        help="accept the current findings as the floor")
    parser.add_argument("--why", help="required with --update-baseline")
    # Capture the validated invocation arguments that govern this execution.
    arguments = parser.parse_args(argument_list)

    # Refuse an unaudited baseline update before running any checks.
    if arguments.update_baseline and not arguments.why:
        print("--update-baseline requires --why", file=sys.stderr)
        # Return the aggregate process status to the command-line boundary.
        return EXIT_REGRESSED

    # Resolve the repository-confined path used by this operation before filesystem access.
    root = arguments.root.resolve()
    # Use explicit path elements in argument order, or the conventional source root as one item.
    paths = arguments.paths or [root / "src"]
    # Resolve the project-owned baseline below the selected adopter root.
    baseline_path = root / BASELINE_NAME
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = findings_for(paths)

    # Report mode explains the current state without enforcing or changing the ratchet.
    if command == "report":
        print(render_report(findings, root, load_baseline(baseline_path)))
        # Return the aggregate process status to the command-line boundary.
        return EXIT_OK

    # Baseline-update mode first proves that no protected finding would be accepted.
    if arguments.update_baseline:
        # Each protected element is one protected finding object; checker order is preserved for
        # refusal diagnostics.
        protected = [f for f in findings if f.rule_id in PROTECTED]
        # Refuse the entire update when any non-baselinable rule is violated.
        if protected:
            # Render each protected finding in original checker order.
            for finding in protected:
                print(f"  {finding.render(root)}", file=sys.stderr)
            print(f"refusing to baseline {len(protected)} protected violation(s); "
                  f"these are the rules adopting the discipline is for",
                  file=sys.stderr)
            # Return the aggregate process status to the command-line boundary.
            return EXIT_REGRESSED
        write_baseline(baseline_path, len(findings),
                       pairs_of(findings, root), arguments.why)
        print(f"conformance: baseline recorded at {len(findings)} finding(s) -- "
              f"{arguments.why}")
        # Return the aggregate process status to the command-line boundary.
        return EXIT_OK

    # Judge current findings against the optional adopter-owned baseline.
    complaints = judge(findings, root, load_baseline(baseline_path))
    # Print regression complaints in protected/new-pair/count order.
    for complaint in complaints:
        print(f"  {complaint}", file=sys.stderr)
    # Fail with the explicit ratchet-update remedy when any regression remains.
    if complaints:
        print('fix them, or move the baseline with --update-baseline --why "..."',
              file=sys.stderr)
        # Return the aggregate process status to the command-line boundary.
        return EXIT_REGRESSED

    # Reload the accepted count for the positive summary after judgement passes.
    recorded = load_baseline(baseline_path)
    # Include the accepted ceiling only when an adopter baseline exists.
    accepted = f", {recorded[0]} accepted" if recorded else ""
    print(f"conformance: {len(findings)} finding(s){accepted}, none new")
    # Return the aggregate process status to the command-line boundary.
    return EXIT_OK


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    # Propagate the localized failure so callers cannot mistake it for success.
    raise SystemExit(main())
