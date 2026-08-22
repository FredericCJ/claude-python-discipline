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

import import_gate
import lint_gate
import type_gate
from discipline_core import Force, iter_documents, mechanism_is_implemented

## The repository root, one level up from `tools/`.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent

## `enforce/` is not on the default path when this runs as a script. The root
## `conftest.py` does the same insert for pytest; this is the script's half.
if str(REPO_ROOT / "enforce") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "enforce"))

# These three sit below the path insert above deliberately: they live under
# `enforce/`, which is not importable until that line has run.
import discrimination  # ruff: ignore[module-import-not-at-top-of-file]
from checks import project  # ruff: ignore[module-import-not-at-top-of-file]
from checks.__main__ import discover  # ruff: ignore[module-import-not-at-top-of-file]
from fixtures import broken_copy, reference_root  # ruff: ignore[module-import-not-at-top-of-file]

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

## The committed floor `D` ratchets against, beside this file for the same reason
## the other baselines are: a ceiling that travels separately from its tool can be
## edited without the tool noticing.
BASELINE_PATH: Final = Path(__file__).resolve().parent / "discrimination_baseline.json"

## The ruff configuration a `tool="ruff"` mutation is judged against: the one an
## adopter copies. The reference fixture declares none of its own, so without
## this ruff would lint a temp copy under its small default rule set and report
## none of the codes the discipline names.
RUFF_CONFIG: Final = REPO_ROOT / "enforce" / "templates" / "pyproject.toml"

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
    declaration = project.load(tree)
    reported: set[str] = set()
    for check in discover():
        check.declaration = declaration
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


def _ruff_codes(root: Path) -> set[str]:
    """Every ruff code reported over one tree.

    Invoked through `lint_gate.run_ruff`, which goes via `sys.executable -m ruff`
    rather than locating an executable. Its docstring records why: a prior gate
    looked beside the interpreter, missed `Scripts/` on Windows, and skipped
    itself behind a green run with 766 findings unseen.

    @param root the tree to lint
    @return the codes, as ruff spells them
    """
    findings, _ = lint_gate.run_ruff(root, config=RUFF_CONFIG)
    return {str(finding.get("code") or "") for finding in findings}


def _mypy_output(root: Path) -> set[str]:
    """What mypy said about one tree, as a single blob to search.

    @param root the tree holding `src/`
    @return a one-element set holding the output, so every tool has one shape
    """
    _, _, output = type_gate.run_mypy(root)
    return {output}


def _pyright_output(root: Path) -> set[str]:
    """What pyright said about one tree.

    @param root the tree holding `src/` and `pyrightconfig.json`
    @return a one-element set holding the output
    """
    _, _, output = type_gate.run_pyright(root)
    return {output}


def _contract_output(root: Path) -> set[str]:
    """What import-linter said about one tree.

    Goes through `import_gate.check`, which calls the library's Python API. The
    module form exits 0 having checked nothing, and `_evict` there removes root
    packages from `sys.modules` because import-linter consults it before
    `sys.path` -- a pre-imported package silently wins otherwise, and the damaged
    copy would be checked as though it were the original.

    @param root the tree holding `src/` and the contract configuration
    @return a one-element set holding the report
    """
    _, output = import_gate.check(root, import_gate.DEFAULT_CONFIG, 0)
    return {output}


## How each `auto:` tool is run over a tree, and what its answer looks like. Ruff
## yields codes to match exactly; the others yield one blob to search, because a
## mypy code and a contract name are both substrings of a line rather than a
## field the tool hands back separately.
TOOLS: Final[dict[str, Callable[[Path], set[str]]]] = {
    "ruff": _ruff_codes,
    "mypy": _mypy_output,
    "pyright": _pyright_output,
    "import-linter": _contract_output,
}


def _present(mutation: discrimination.Mutation, answers: set[str]) -> bool:
    """Whether the declared diagnostic is in one tool's answer.

    Matching is exact for ruff, where a code is a whole token, and by substring
    for the checkers, where the diagnostic is part of a printed line.

    @param mutation the declared mutation, whose `tool` and `diagnostic` are read
    @param answers what the tool reported, as `TOOLS` returns it
    @return True when the diagnostic is present
    """
    if mutation.tool == "ruff":
        return mutation.diagnostic in answers
    return any(mutation.diagnostic in answer for answer in answers)


def emits(mutation: discrimination.Mutation, root: Path) -> bool:
    """Whether the declared tool reports the declared diagnostic against a tree.

    @param mutation the declared mutation, whose `tool` and `diagnostic` are read
    @param root the tree to run the tool over
    @return True when the diagnostic is present in what the tool reported
    """
    return _present(mutation, TOOLS[mutation.tool](root))


def provoke(mutation: discrimination.Mutation, workspace: Path) -> set[str]:
    """Apply one mutation and report which rules its mechanism then reports.

    @param mutation the declared mutation
    @param workspace a fresh directory to build the damaged tree in
    @return the rule ids observed rejecting the damaged tree
    @throws FileNotFoundError when a path named for damage is not there
    """
    root = damaged(mutation, workspace)
    if mutation.tool:
        return {mutation.rule_id} if emits(mutation, root) else set()
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

    # The same guard for the `auto:` tools, asked per diagnostic rather than per
    # tool. Requiring a tool to be entirely silent over the reference would be a
    # stronger claim than this gate needs and a flakier one; requiring that the
    # SPECIFIC diagnostic a mutation claims is absent before the damage is what
    # actually makes the observation mean something. Each tool is run once and
    # its answer reused, because mypy over the reference is seconds, not
    # milliseconds.
    already: dict[str, set[str]] = {}
    for mutation in discrimination.MUTATIONS:
        if not mutation.tool:
            continue
        if mutation.tool not in already:
            already[mutation.tool] = TOOLS[mutation.tool](reference)
        if _present(mutation, already[mutation.tool]):
            complaints.append(
                f"{mutation.rule_id}: {mutation.tool} already reports "
                f"{mutation.diagnostic!r} against the CONFORMANT reference, so "
                f"seeing it after the damage would prove nothing."
            )
    if complaints:
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


def undiscriminated(provoked: set[str]) -> list[str]:
    """Binding rules that name a working mechanism nobody has watched reject.

    The complement of `D` within the decided set, and the number `V098` reports.
    `D` on its own may only rise, which stops a mechanism that used to
    discriminate from quietly ceasing to -- but it says nothing about a NEW
    binding rule arriving with a mechanism and no mutation. That would leave `D`
    untouched while the corpus grew a rule nobody had watched work. This is the
    guard for that direction.

    @param provoked the rules just observed being rejected
    @return the gap, sorted, so the ceiling has something to name
    """
    return sorted(
        rule.rule_id
        for document in iter_documents(REPO_ROOT / "discipline")
        for rule in document.rules
        if rule.force is Force.BINDING
        and rule.rule_id not in provoked
        and rule.mechanisms
        and any(mechanism_is_implemented(m, REPO_ROOT, rule.rule_id) is not False
                for m in rule.mechanisms)
    )


def ratchets_held(provoked: set[str], gap: list[str],
                  baseline: dict[str, object]) -> str:
    """Whether either recorded number has slipped, and which way.

    Two directions, and the second is the one a rising count hides. `D` falling
    means a mechanism that used to discriminate has stopped. The gap widening
    means a rule arrived carrying a mechanism and no mutation -- which leaves `D`
    untouched, so a release adding four decided rules and one mutation reports
    progress while covering proportionally less than before.

    @param provoked the rules just observed being rejected
    @param gap the decided rules with no mutation
    @param baseline the committed floor and ceiling
    @return an empty string when both hold, else what slipped and by how much
    """
    floor = int(baseline.get("count", 0))
    if len(provoked) < floor:
        lost = ", ".join(sorted(set(baseline.get("rules", [])) - provoked))
        return (f"D fell from {floor} to {len(provoked)} -- {lost} no longer "
                f"provoked. A ratchet may only rise.")

    ceiling = baseline.get("gap")
    if ceiling is not None and len(gap) > int(ceiling):
        return (f"{len(gap)} decided rule(s) are undiscriminated, above the "
                f"recorded {ceiling}. A rule may not arrive carrying a mechanism "
                f"and no mutation.")
    return ""


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
                "gap": len(undiscriminated(provoked)),
                "why": arguments.why,
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"discrimination: floor recorded at D={len(provoked)} -- {arguments.why}")
        return EXIT_OK

    if status != EXIT_OK:
        print(f"discrimination: {len(complaints)} broken claim(s)", file=sys.stderr)
        return EXIT_FAILED
    gap = undiscriminated(provoked)
    slipped = ratchets_held(provoked, gap, baseline)
    if slipped:
        print(f"discrimination: {slipped}", file=sys.stderr)
        return EXIT_FAILED

    print(f"discrimination: D={len(provoked)}, floor {floor}, "
          f"{len(discrimination.MUTATIONS)} mutation(s) all provoking their rule; "
          f"{len(gap)} decided rule(s) still undiscriminated")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
