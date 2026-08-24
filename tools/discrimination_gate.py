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
from typing import TYPE_CHECKING, Final, cast

import import_gate
import lint_gate
import type_gate
from discipline_core import Force, has_mechanical_claim, iter_documents
from evidence_model import EVIDENCE_PATH, load_evidence

## The repository root, one level up from `tools/`.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent

## `enforce/` is not on the default path when this runs as a script. The root
## `conftest.py` does the same insert for pytest; this is the script's half.
# Prepend the local tools directory only when import resolution does not already contain it.
if str(REPO_ROOT / "enforce") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "enforce"))

# These three sit below the path insert above deliberately: they live under
# `enforce/`, which is not importable until that line has run.
import discrimination  # ruff: ignore[module-import-not-at-top-of-file]
from checks import project  # ruff: ignore[module-import-not-at-top-of-file]
from checks.__main__ import discover  # ruff: ignore[module-import-not-at-top-of-file]
from fixtures import broken_copy, reference_root  # ruff: ignore[module-import-not-at-top-of-file]

# Import annotation-only protocols without adding runtime dependencies.
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
        Each targets element represents one governed path; traversal order is preserved.
    @return the rule ids reported, empty when the tree is clean
    """
    # Each paths element represents one repository path; traversal order is preserved.
    paths = [tree / target for target in targets]
    # Each retained element is an existing target path; declaration order determines traversal.
    present = [path for path in paths if path.exists()]
    declaration = project.load(tree)
    # Collect unique reported element values; their order is deliberately unordered.
    reported: set[str] = set()
    for check in discover():
        # Bind every check to the same parsed declaration before examining the shared tree.
        check.declaration = declaration
        # Reduce emitted findings to stable rule identities; presentation details are irrelevant here.
        reported.update(finding.rule_id for finding in check.run(present))
    # Report the union so one mutation can reveal collateral rule violations.
    return reported


def damaged(mutation: discrimination.Mutation, workspace: Path) -> Path:
    """Build the tree this mutation describes.

    @param mutation the declared mutation
    @param workspace a fresh directory to build in
    @return the damaged tree's root
    @throws FileNotFoundError when a path named for damage is not there, which
        `broken_copy` raises rather than silently leaving the tree intact

    @par Effects
    Builds one isolated damaged tree beneath ``workspace``.
    """
    # Collapse write entries by path because fixture construction consumes one final body per file.
    written = dict(mutation.write)
    # Repository mutations need the discipline's own implementation and tests as their subject.
    if mutation.base == "repository":
        # Keep the copied checkout below the disposable workspace boundary.
        root = workspace / "repository"
        # Exclude caches and agent state so only governed repository material influences the proof.
        shutil.copytree(
            REPO_ROOT,
            root,
            ignore=shutil.ignore_patterns(
                ".git", ".agent", ".agents", ".claude", ".pytest_cache",
                ".ruff_cache", ".mypy_cache", ".hypothesis", "__pycache__",
                "build", "dist",
            ),
        )
        _apply_damage(root, mutation)
        # Expose the fully damaged repository to the selected fitness node.
        return root
    # Empty-base mutations describe their complete subject in the write table.
    if mutation.base == "empty":
        # Give synthetic checker subjects a dedicated root distinct from repository copies.
        root = workspace / "tree"
        # Materialize each declared path/body pair in table order for reproducible fixtures.
        for name, contents in written.items():
            # Resolve each file beneath the isolated synthetic tree.
            target = root / name
            # Create only the ancestry needed by the current synthetic file.
            target.parent.mkdir(parents=True, exist_ok=True)
            # Preserve declared LF bytes so platform newline policy cannot alter the mutation.
            target.write_text(contents, encoding="utf-8", newline="\n")
        # Return the complete synthetic subject after every declared file exists.
        return root
    # Reference-base mutations use the shared conformant fixture plus declared damage.
    return broken_copy(workspace, drop=mutation.drop, write=written or None,
                       replace=mutation.replace)


def _apply_damage(root: Path, mutation: discrimination.Mutation) -> None:
    """Apply one mutation to a repository copy with drift detection.

    @param root copied discipline repository
    @param mutation exact paths and substitutions to apply
    @throws FileNotFoundError when the declared damage no longer matches the tree

    @par Effects
    Applies the mutation's removals, writes, and substitutions to ``root``.
    """
    # Apply removals first so later writes may deliberately recreate a path.
    for relative in mutation.drop:
        # Anchor every declared removal inside the copied repository.
        target = root / relative
        # Treat a missing target as matrix drift, never as a successful mutation.
        if not target.exists():
            # Name the stale declaration so maintainers can repair the exact matrix entry.
            message = f"nothing to drop at {relative}; the repository has moved"
            # Stop before granting rejection credit to an unchanged tree.
            raise FileNotFoundError(message)
        # Directories require recursive removal; files and links use unlink semantics.
        if target.is_dir():
            shutil.rmtree(target)
        else:
            # Remove file-like targets without traversing beyond the declared path.
            target.unlink()
    # Apply complete-file writes after removals and before textual substitutions.
    for relative, body in mutation.write:
        # Anchor the new file inside the copied repository.
        target = root / relative
        # Permit a mutation to introduce a previously absent package path.
        target.parent.mkdir(parents=True, exist_ok=True)
        # Reproduce the table body exactly with stable LF newlines.
        target.write_text(body, encoding="utf-8", newline="\n")
    # Apply bounded first-occurrence substitutions last against the resulting files.
    for relative, old, new in mutation.replace:
        # Anchor the edited file inside the copied repository.
        target = root / relative
        # Refuse a vanished file because an unchanged subject cannot prove discrimination.
        if not target.exists():
            # Localize repository drift to the stale replacement entry.
            message = f"nothing to edit at {relative}; the repository has moved"
            # Abort this mutation without presenting it to a mechanism.
            raise FileNotFoundError(message)
        # Read once so membership validation and replacement use identical source bytes.
        source = target.read_text(encoding="utf-8")
        # Refuse replacement when its expected preimage no longer exists.
        if old not in source:
            # Include the missing preimage in the drift diagnostic.
            message = f"{relative} does not contain {old!r}; the repository has moved"
            # Prevent a no-op edit from earning false rejection credit.
            raise FileNotFoundError(message)
        # Limit replacement to one occurrence because each mutation declares one defect injection.
        target.write_text(
            source.replace(old, new, 1), encoding="utf-8", newline="\n"
        )


def fails_against(node: str, root: Path, *, repository: bool = False) -> bool:
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
    @param repository run the copied repository's test and implementation together
        True enables repository; false selects its disabled alternative.
    @return True when pytest reported the node as not passing
    """
    # Start from the caller environment so the proof runs under the qualified toolchain.
    environment = dict(os.environ)
    # Repository fitness nodes default to the canonical checkout unless their mutation says otherwise.
    working_directory = REPO_ROOT
    # A repository mutation must execute both tests and implementation from its copied checkout.
    if repository:
        # Remove fixture redirection because the copied repository itself is the subject.
        environment.pop("DISCIPLINE_REFERENCE", None)
        # Run pytest from the copy so imports and relative paths cannot reach the pristine checkout.
        working_directory = root
    else:
        # Redirect reference-oriented fitness nodes to the damaged fixture tree.
        environment["DISCIPLINE_REFERENCE"] = str(root)
    finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        (sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "-x", node),
        cwd=working_directory, env=environment,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False, timeout=600,
    )
    # Any non-passing pytest outcome demonstrates that the damaged subject was rejected.
    return finished.returncode != 0


def proof_passes(node: str) -> bool:
    """Whether a companion test observes its declared rule rejecting a fixture.

    A proof node constructs its own violating subject and asserts the exact rule
    diagnostic, so success is the witnessed rejection. This complements `node`,
    where a fitness mechanism is expected to fail against table-supplied damage.

    @param node pytest node id of the direct proof-of-failure case
    @return True only when pytest executes that proof successfully
    """
    # Inherit the qualified toolchain while clearing any outer fixture redirection.
    environment = dict(os.environ)
    environment.pop("DISCIPLINE_REFERENCE", None)
    finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        (sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "-x", node),
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=600,
    )
    # A direct proof witnesses rejection only when its own assertions pass.
    return finished.returncode == 0


def _ruff_codes(root: Path) -> set[str]:
    """Every ruff code reported over one tree.

    Invoked through `lint_gate.run_ruff`, which goes via `sys.executable -m ruff`
    rather than locating an executable. Its docstring records why: a prior gate
    looked beside the interpreter, missed `Scripts/` on Windows, and skipped
    itself behind a green run with 766 findings unseen.

    @param root the tree to lint
    @return the codes, as ruff spells them
    """
    # Retain Ruff findings long enough to compare complete diagnostic codes.
    findings, _ = lint_gate.run_ruff(root, config=RUFF_CONFIG)
    # Compare whole Ruff diagnostic codes, excluding any absent-code placeholders.
    return {str(finding.get("code") or "") for finding in findings}


def _mypy_output(root: Path) -> set[str]:
    """What mypy said about one tree, as a single blob to search.

    @param root the tree holding `src/`
    @return a one-element set holding the output, so every tool has one shape
    """
    # Combine the checker's captured diagnostic streams without losing emission text.
    _, _, output = type_gate.run_mypy(root)
    # Preserve output as one searchable answer because mypy embeds codes inside lines.
    return {output}


def _pyright_output(root: Path) -> set[str]:
    """What pyright said about one tree.

    @param root the tree holding `src/` and `pyrightconfig.json`
    @return a one-element set holding the output
    """
    # Combine the checker's captured diagnostic streams without losing emission text.
    _, _, output = type_gate.run_pyright(root)
    # Preserve output as one searchable answer because pyright embeds codes inside lines.
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
    # Combine the checker's captured diagnostic streams without losing emission text.
    _, output = import_gate.check(root, import_gate.DEFAULT_CONFIG, 0)
    # Preserve the report as one searchable answer because contract names are line fragments.
    return {output}


## How each `auto:` tool is run over a tree, and what its answer looks like. Ruff
## yields codes to match exactly; the others yield one blob to search, because a
## mypy code and a contract name are both substrings of a line rather than a
## field the tool hands back separately.
## Treat TOOLS as mapping elements whose keys identify fields and values carry their content;
## key order is deliberately unused.
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
        Collect unique answers element values; their order is deliberately unordered.
    @return True when the diagnostic is present
    """
    # Ruff exposes diagnostics as exact codes, unlike the text-reporting tools.
    if mutation.tool == "ruff":
        # Require equality so a shorter code cannot match an unrelated diagnostic.
        return mutation.diagnostic in answers
    # Search each opaque report for the declared diagnostic token.
    return any(mutation.diagnostic in answer for answer in answers)


def emits(mutation: discrimination.Mutation, root: Path) -> bool:
    """Whether the declared tool reports the declared diagnostic against a tree.

    @param mutation the declared mutation, whose `tool` and `diagnostic` are read
    @param root the tree to run the tool over
    @return True when the diagnostic is present in what the tool reported
    """
    # Dispatch through the declared tool and apply its matching convention uniformly.
    return _present(mutation, TOOLS[mutation.tool](root))


def provoke(mutation: discrimination.Mutation, workspace: Path) -> set[str]:
    """Apply one mutation and report which rules its mechanism then reports.

    @param mutation the declared mutation
    @param workspace a fresh directory to build the damaged tree in
    @return the rule ids observed rejecting the damaged tree
    @throws FileNotFoundError when a path named for damage is not there
    """
    # Direct proof nodes own fixture construction and certify their rule by passing.
    if mutation.proof:
        # Credit only the declared rule when its proof assertion succeeds.
        return {mutation.rule_id} if proof_passes(mutation.proof) else set()
    # All remaining strategies consume a table-described damaged tree.
    root = damaged(mutation, workspace)
    # External tools report one declared diagnostic rather than discipline rule ids.
    if mutation.tool:
        # Translate a matching tool diagnostic back to the matrix rule identity.
        return {mutation.rule_id} if emits(mutation, root) else set()
    # Fitness nodes reject damage through their own test outcome.
    if mutation.node:
        # Translate a non-passing node to the one rule whose mutation it exercises.
        return {
            mutation.rule_id
        } if fails_against(
            mutation.node, root, repository=mutation.base == "repository"
        ) else set()
    # Native checks already return every rule identity provoked by the damaged tree.
    return findings_for(root, mutation.targets)


def repository_preflight() -> list[str]:
    """Require repository-based fitness nodes to pass before mutation.

    @return one complaint for each already-red unmutated test
    """
    # Deduplicate repository node ids and sort them for deterministic preflight reporting.
    nodes = sorted({
        # Each mutation contributes its repository fitness node when one is declared.
        mutation.node
        for mutation in discrimination.MUTATIONS
        if mutation.base == "repository" and mutation.node
    })
    # Name every node that is red before damage so it cannot earn mutation credit.
    return [
        (
            f"{node}: the unmutated repository fitness test does not pass, "
            "so a damaged copy could earn false rejection credit."
        )
        # Evaluate repository nodes against the pristine canonical checkout.
        for node in nodes
        if fails_against(node, REPO_ROOT, repository=True)
    ]


def tool_preflight(reference: Path) -> list[str]:
    """Reject tool mutations whose diagnostic is already present before damage.

    @param reference conformant adopter fixture
    @return one complaint for each already-present diagnostic
    """
    # Each complaints element is a diagnostic for a mutation signature already visible on the
    # conformant fixture; registry order is preserved so damage earns no pre-existing credit.
    complaints: list[str] = []
    # Treat observed as mapping elements whose keys identify tools and whose values are unordered
    # diagnostic-answer sets; key insertion order is deliberately unused.
    observed: dict[str, set[str]] = {}
    for mutation in discrimination.MUTATIONS:
        # Native checks and fitness nodes are preflighted through their own paths.
        if not mutation.tool:
            # Skip entries outside the external-tool protocol.
            continue
        # Run each external tool once over the conformant reference.
        if mutation.tool not in observed:
            # Retain all answers needed by that tool's subsequent mutation entries.
            observed[mutation.tool] = TOOLS[mutation.tool](reference)
        # A pre-existing signature would make the post-damage observation ambiguous.
        if _present(mutation, observed[mutation.tool]):
            # Preserve matrix order when explaining which claims cannot be credited.
            complaints.append(
                f"{mutation.rule_id}: {mutation.tool} already reports "
                f"{mutation.diagnostic!r} against the CONFORMANT reference, so "
                "seeing it after the damage would prove nothing."
            )
    # Return every contaminated signature rather than stopping at the first one.
    return complaints


def run() -> tuple[int, list[str], set[str]]:
    """Apply every declared mutation and report which rules were provoked.

    @return the exit status, one complaint per broken claim, and the rules that
        were genuinely provoked
    """
    # Each complaints element is one gate-failure diagnostic; discovery and mutation order is
    # preserved for deterministic reporting.
    complaints: list[str] = []
    # Collect unique provoked element values; their order is deliberately unordered.
    provoked: set[str] = set()

    # Resolve the canonical conformant fixture shared by check and tool preflights.
    reference = reference_root()
    # Capture any native-check rule ids already present before mutation.
    dirty = findings_for(reference, ("src", "tests"))
    # A dirty reference invalidates every native-check discrimination observation.
    if dirty:
        complaints.append(
            f"the conformant reference already reports {', '.join(sorted(dirty))}. "
            f"Every result below would be crediting a mechanism with a finding it "
            f"did not earn."
        )
        # Stop before mutations can receive credit from pre-existing findings.
        return EXIT_FAILED, complaints, provoked

    # The same guard for the `auto:` tools, asked per diagnostic rather than per
    # tool. Requiring a tool to be entirely silent over the reference would be a
    # stronger claim than this gate needs and a flakier one; requiring that the
    # SPECIFIC diagnostic a mutation claims is absent before the damage is what
    # actually makes the observation mean something. Each tool is run once and
    # its answer reused, because mypy over the reference is seconds, not
    # milliseconds.
    complaints.extend(tool_preflight(reference))
    # Refuse the matrix when an external diagnostic already exists on the reference.
    if complaints:
        # Preserve the preflight diagnostics and an empty witnessed set.
        return EXIT_FAILED, complaints, provoked

    complaints.extend(repository_preflight())
    # Repository fitness nodes must also begin green before any copied damage.
    if complaints:
        # Preserve the failing node diagnostics and an empty witnessed set.
        return EXIT_FAILED, complaints, provoked

    # Isolate each mutation so no prior damage can influence a later observation.
    for mutation in discrimination.MUTATIONS:
        # Allocate a unique workspace that is removed regardless of proof outcome.
        workspace = Path(tempfile.mkdtemp(prefix="discrim-"))
        # Convert stale matrix paths into complaints while always reclaiming the workspace.
        try:
            # Record every rule identity reported after applying this one mutation.
            reported = provoke(mutation, workspace)
        # Missing damage targets indicate fixture drift, not mechanism rejection.
        except FileNotFoundError as absent:
            complaints.append(
                f"{mutation.rule_id}: the mutation names {absent}, which is not in "
                f"the tree -- the entry has drifted from the fixture"
            )
            # Continue auditing independent mutations after recording the stale entry.
            continue
        finally:
            # Remove copied repositories and synthetic fixtures on success and failure alike.
            shutil.rmtree(workspace, ignore_errors=True)

        # Credit a claim only when its own stable rule id appears after its mutation.
        if mutation.rule_id in reported:
            provoked.add(mutation.rule_id)
        else:
            # Expose collateral findings so maintainers can distinguish silence from misattribution.
            others = ", ".join(sorted(reported)) or "nothing at all"
            complaints.append(
                f"{mutation.rule_id}: {mutation.summary} -- and the checks reported "
                f"{others}. The entry claims this mechanism catches this; it does not."
            )
    # Report the aggregate verdict after every independently recoverable mutation ran.
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
        Collect unique provoked element values; their order is deliberately unordered.
    @return the gap, sorted, so the ceiling has something to name
    """
    # Compute the stable complement of witnessed ids within mechanically claimed binding rules.
    return sorted(
        # Each document contributes its binding rules in corpus traversal order before sorting.
        rule.rule_id
        for document in iter_documents(REPO_ROOT / "discipline")
        # Each rule is evaluated against evidence and the witnessed rule-id set.
        for rule in document.rules
        if rule.force is Force.BINDING
        and rule.rule_id not in provoked
        and rule.mechanisms
        and has_mechanical_claim(rule.mechanisms, REPO_ROOT, rule.rule_id)
    )


def resolved_strategy_witnesses() -> frozenset[tuple[str, str]]:
    """Resolve every matrix entry to one exact evidence strategy.

    Single-strategy rules may omit ``Mutation.mechanism`` to keep the table
    readable. Multi-strategy rules may not: a mypy observation cannot certify
    pyright merely because both share a stable rule id.

    @return exact rule/mechanism pairs represented by the matrix
    @throws ValueError when an unqualified entry is ambiguous or undeclared
    """
    # Load authoritative strategy declarations before resolving shorthand matrix entries.
    registry = load_evidence(EVIDENCE_PATH)
    # Map each rule id to its automated mechanism names; registry order is preserved but unused.
    automated = {
        # Each value is a tuple of automated mechanism names in evidence declaration order.
        rule_id: tuple(
            # Each strategy contributes its mechanism only when automation can witness it.
            strategy.mechanism for strategy in record.strategies
            if strategy.is_automated
        )
        # Each evidence record supplies the automated candidates for one stable rule id.
        for rule_id, record in registry.rules.items()
    }
    # Collect unique resolved element values; their order is deliberately unordered.
    resolved: set[tuple[str, str]] = set()
    for rule_id, mechanism in discrimination.covered_strategies():
        # Look up the exact automated strategies that this matrix entry may credit.
        candidates = automated.get(rule_id, ())
        # Retired or non-automated rules have no current strategy-level claim to ratchet.
        if not candidates:
            # Historical matrix entries remain readable after a rule is retired,
            # but an inactive rule has no current strategy to ratchet.
            continue
        # An explicit mechanism must name one strategy declared for the same rule.
        if mechanism:
            # Reject stale or cross-rule attribution before it enters the witness set.
            if mechanism not in candidates:
                # Localize the invalid attribution to its rule and mechanism.
                message = f"{rule_id} attributes rejection to undeclared {mechanism}"
                # Abort because ambiguous evidence cannot be made safe by omission.
                raise ValueError(message)
            resolved.add((rule_id, mechanism))
        # Shorthand is unambiguous only when the evidence model declares one candidate.
        elif len(candidates) == 1:
            resolved.add((rule_id, candidates[0]))
        else:
            # Explain why a multi-strategy rule requires explicit matrix attribution.
            message = (
                f"{rule_id} has {len(candidates)} automated strategies; "
                "its mutation must name one"
            )
            # Refuse to credit all candidates from one unqualified observation.
            raise ValueError(message)
    # Freeze the exact pairs so callers cannot mutate the resolved evidence set.
    return frozenset(resolved)


def undiscriminated_strategies(
    witnessed: set[tuple[str, str]] | frozenset[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Exact automated strategies with no observed rejection.

    @param witnessed resolved matrix pairs
    @return missing pairs in stable rule/mechanism order
    """
    # Load the authoritative automated strategy universe used for the complement.
    registry = load_evidence(EVIDENCE_PATH)
    # Sort exact missing pairs for stable baseline and diagnostic serialization.
    return sorted(
        (rule_id, strategy.mechanism)
        # Each evidence record contributes its strategies under the owning rule id.
        for rule_id, record in registry.rules.items()
        # Each automated strategy is one independently ratcheted claim.
        for strategy in record.strategies
        if strategy.is_automated and (rule_id, strategy.mechanism) not in witnessed
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
        Collect unique provoked element values; their order is deliberately unordered.
    @param gap the decided rules with no mutation
        Each element is a rule id lacking a discrimination witness; stable rule order is
        preserved for reproducible diagnostics.
    @param baseline the committed floor and ceiling
        Treat baseline as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @return an empty string when both hold, else what slipped and by how much
    """
    # Read the recorded rule-id witness floor through strict JSON integer validation.
    floor = _baseline_integer(baseline, "count", 0)
    # A smaller witnessed set means at least one formerly discriminating claim regressed.
    if len(provoked) < floor:
        # Recover recorded identities so the regression names the lost rules, not only a count.
        recorded = baseline.get("rules", [])
        # Reject malformed identity evidence before computing a misleading set difference.
        if not isinstance(recorded, list) or not all(isinstance(item, str) for item in recorded):
            # Explain the exact baseline shape required for loss attribution.
            message = "discrimination baseline rules must be a list of strings"
            # Treat invalid committed evidence as a gate error rather than an empty baseline.
            raise TypeError(message)
        # Compute the stable names previously recorded but absent from this run.
        lost = ", ".join(sorted(set(cast("list[str]", recorded)) - provoked))
        # Stop on the first ratchet dimension because rule-id regression dominates gap checks.
        return (f"D fell from {floor} to {len(provoked)} -- {lost} no longer "
                f"provoked. A ratchet may only rise.")

    # Read the permitted undiscriminated-rule count when older baselines provide it.
    ceiling = baseline.get("gap")
    # A larger gap means new mechanized rules arrived without witnessed rejection.
    if ceiling is not None and len(gap) > _baseline_integer(baseline, "gap", 0):
        # Report both actual and recorded counts so baseline changes remain reviewable.
        return (f"{len(gap)} decided rule(s) are undiscriminated, above the "
                f"recorded {ceiling}. A rule may not arrive carrying a mechanism "
                f"and no mutation.")
    # Preserve compatibility with baselines predating exact strategy attribution.
    strategy_floor = baseline.get("strategy_count")
    # Read the permitted exact-strategy gap independently of the witness floor.
    strategy_ceiling = baseline.get("strategy_gap")
    # Evaluate strategy ratchets only when either strategy field has been adopted.
    if strategy_floor is not None or strategy_ceiling is not None:
        # Resolve current matrix entries to exact rule/mechanism evidence pairs.
        witnessed = resolved_strategy_witnesses()
        # Detect loss of a formerly witnessed mechanism even when its rule id remains covered.
        if strategy_floor is not None and len(witnessed) < _baseline_integer(
            baseline, "strategy_count", 0
        ):
            # Explain the exact-strategy regression without conflating it with D.
            return (
                f"exact strategy coverage fell from {strategy_floor} to "
                f"{len(witnessed)}. A mechanism-level ratchet may only rise."
            )
        # Compute automated strategy claims that still lack an observed rejection.
        missing = undiscriminated_strategies(witnessed)
        # Reject growth in the mechanism-level coverage gap.
        if strategy_ceiling is not None and len(missing) > _baseline_integer(
            baseline, "strategy_gap", 0
        ):
            # Report the widened strategy gap against its recorded ceiling.
            return (
                f"{len(missing)} exact strategy claim(s) are undiscriminated, "
                f"above the recorded {strategy_ceiling}."
            )
    # An empty complaint is the explicit signal that every applicable ratchet held.
    return ""


def _baseline_integer(baseline: dict[str, object], field: str, default: int) -> int:
    """Read one integer field without accepting JSON strings or booleans.

    @param baseline decoded baseline object
        Treat baseline as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @param field field to read
    @param default value when the field is absent
    @return validated integer
    @throws TypeError when the field is not an integer
    """
    # Preserve field absence as the caller-supplied compatibility default.
    value = baseline.get(field, default)
    # JSON booleans are Python integers but are not valid quantitative evidence.
    if not isinstance(value, int) or isinstance(value, bool):
        # Name the malformed field so baseline repair is direct.
        message = f"discrimination baseline {field} must be an integer"
        # Fail closed instead of coercing strings or booleans into ratchet values.
        raise TypeError(message)
    # Return the validated count without changing its numeric value.
    return value


def read_baseline() -> dict[str, object]:
    """The committed floor, or an empty one when nothing has been recorded.

    @return the baseline document
    """
    # Bootstrap repositories without a committed ratchet at the neutral floor.
    if not BASELINE_PATH.is_file():
        # Supply all legacy fields expected by callers before first baseline creation.
        return {"count": 0, "rules": [], "why": ""}
    # Decode committed bytes without assuming the top-level JSON shape.
    loaded: object = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    # Require an object with textual field names before typed access.
    if not isinstance(loaded, dict) or not all(isinstance(key, str) for key in loaded):
        # Describe the minimum structural contract violated by the baseline.
        message = "discrimination baseline must be a JSON object with string keys"
        # Reject corrupt evidence rather than silently resetting its ratchets.
        raise TypeError(message)
    # Narrow the validated object for downstream field-specific checks.
    return cast("dict[str, object]", loaded)


def main(argv: list[str] | None = None) -> int:
    """Run every mutation, compare `D` against its floor, and report.

    @param argv the command line, or None to read `sys.argv`
    @return the process exit status

    @par Effects
    Runs discrimination proofs, prints their verdict, and optionally rewrites the baseline.
    """
    # Configure the command-line parser that defines this tool's invocation contract.
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update-baseline", action="store_true",
                        help="record the current coverage as the new floor")
    parser.add_argument("--why", help="required with --update-baseline")
    # Parse discrimination execution or baseline-update intent before loading the matrix.
    arguments = parser.parse_args(argv)

    # Argument validation before the work, not after. The matrix takes about
    # three and a half seconds; refusing a missing `--why` afterwards spent all
    # of it to reach a conclusion available immediately.
    if arguments.update_baseline and not arguments.why:
        print("--update-baseline requires --why", file=sys.stderr)
        # Refuse an unreasoned evidence-floor change before executing the mutation matrix.
        return EXIT_FAILED

    # Execute the complete proof matrix before comparing its observations to the baseline.
    status, complaints, provoked = run()
    # Emit every broken claim so one invocation supplies a complete repair list.
    for complaint in complaints:
        print(f"  {complaint}", file=sys.stderr)

    # Hold baseline path keys mapped to their recorded behavior-fingerprint values.
    baseline = read_baseline()
    floor = _baseline_integer(baseline, "count", 0)

    # Baseline updates are permitted only from a completely discriminating matrix run.
    if arguments.update_baseline:
        # Refuse to bless the current counts when any declared mutation failed.
        if status != EXIT_OK:
            print("refusing to move the floor while a declared mutation is broken",
                  file=sys.stderr)
            # Preserve the existing floor when any claimed discrimination proof is already broken.
            return EXIT_FAILED
        # Resolve exact mechanism witnesses for the strategy-level floor.
        strategies = resolved_strategy_witnesses()
        # Record the current complement as the strategy-gap ceiling.
        strategy_gap = undiscriminated_strategies(strategies)
        # Replace the baseline atomically at the file level with deterministic JSON text.
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
                "strategy_count": len(strategies),
                "strategies": [
                    # Serialize each exact pair as a named object for reviewable diffs.
                    {"rule": rule_id, "mechanism": mechanism}
                    # Sort pairs so set iteration cannot perturb committed evidence.
                    for rule_id, mechanism in sorted(strategies)
                ],
                "strategy_gap": len(strategy_gap),
                "why": arguments.why,
            }, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        # Summarize the newly committed floors and ceiling for the operator.
        print(
            f"discrimination: floor recorded at D={len(provoked)}, "
            f"S={len(strategies)}, strategy gap={len(strategy_gap)} -- "
            f"{arguments.why}"
        )
        return EXIT_OK

    # In ordinary gate mode, matrix failures take precedence over baseline comparisons.
    if status != EXIT_OK:
        print(f"discrimination: {len(complaints)} broken claim(s)", file=sys.stderr)
        # Matrix breakage takes precedence over ratchet comparison because its evidence is incomplete.
        return EXIT_FAILED
    # Compute newly mechanized rule ids that have no witnessed mutation.
    gap = undiscriminated(provoked)
    # Compare both rule-level and strategy-level observations with committed ratchets.
    slipped = ratchets_held(provoked, gap, baseline)
    # Fail on any floor decrease or ceiling increase.
    if slipped:
        print(f"discrimination: {slipped}", file=sys.stderr)
        # Fail when witnessed coverage falls or the undiscriminated strategy gap grows.
        return EXIT_FAILED

    # Resolve exact strategy evidence for the successful summary.
    strategies = resolved_strategy_witnesses()
    # Count automated claims still lacking an exact witnessed rejection.
    strategy_gap = undiscriminated_strategies(strategies)
    print(f"discrimination: D={len(provoked)}, floor {floor}, "
          f"{len(discrimination.MUTATIONS)} mutation(s) all provoking their rule; "
          f"S={len(strategies)}, {len(strategy_gap)} exact strategy claim(s) "
          f"still undiscriminated; {len(gap)} rule id(s) still undiscriminated")
    return EXIT_OK


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    # Translate the command result into the process exit status at the sole script boundary.
    raise SystemExit(main())
