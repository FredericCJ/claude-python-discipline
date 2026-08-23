"""Proof-of-failure tests for `validate.py`.

Every check gets a test that drives it to fire. This is the corpus's own
anti-vacuity rule turned on the tooling: a check whose passing signal is "no
output" must first be shown capable of producing a failing signal, or its silence
means nothing.

    pytest tools/test_validate.py
"""

from __future__ import annotations

import ast
import datetime as dt
import json
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

import nav
from discipline_core import (
    REPO_ROOT,
    Enforcement,
    enforcement_of,
    has_mechanical_claim,
    mechanism_is_implemented,
)
from evidence_model import VerificationState
from validate import (
    Layout,
    Severity,
    V080Baseline,
    check_v080_ratchet,
    load_documents,
    load_v080_baseline,
    run,
    write_v080_baseline,
)
from validate import (
    main as validate_main,
)

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence
    from pathlib import Path

## A rule that passes every check, so each test can break exactly one thing and
## attribute the finding to that one thing.
CONFORMANT_RULE = dedent(
    """\
    ### TYPE-001 · Domain code carries no implicit Any  [BINDING] [auto:mypy]
    Domain modules MUST NOT use `Any`, explicit or implicit.
    - **Why** `Any` erases the guarantee the diagnostic envelope depends on.
    - **Check** `mypy --strict src/`
    """
)


def write(path: Path, text: str) -> Path:
    """Put a file on disk, creating whatever directories are missing above it.

    @param path the destination
    @param text the content, dedented so a test may indent its literal to sit
        with the code around it
    @return the same destination, so a caller can go on to move or read it

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    path.parent.mkdir(parents=True, exist_ok=True)
    # Publish the externally visible effect after all required inputs are ready.
    path.write_text(dedent(text), encoding="utf-8")
    # Return the same destination, so a caller can go on to move or read it to the caller.
    return path


def module(
    root: Path,
    *,
    kind: str = "law",
    name: str = "TYPE",
    body: str = CONFORMANT_RULE,
    verified: str | None = None,
    decay: str = "years",
    title: str = "Typing and Contracts",
) -> Path:
    """Lay down a single corpus file whose defaults are already conformant.

    Every argument exists so one test can spoil one property. The defaults form a
    valid law module, which is why a test that overrides nothing must be silent.

    @param root the throwaway corpus root
    @param kind the genre, which fixes the `id:` prefix, the `kind:` line and the
        directory written to all at once, so a file laid down here always agrees
        with its own location -- provoking V004 takes moving it afterwards
    @param name the module name, doubling as the file stem and as the prefix the
        rule ids are required to match
    @param body the markdown after the front-matter, dedented separately
    @param verified the re-verification date, left out of the front-matter
        entirely when None -- which a law module may do and a fact or ops module
        is rejected for
    @param decay the freshness window V060 measures the verified date against
    @param title the front-matter heading, which the schema bounds at 3 to 60
        characters, so a short one is enough to trip V002
    @return the file written
    """
    # Each front element is one YAML front-matter line in serialized field order.
    front = [
        "---",
        f"id: {kind}/{name}",
        f"kind: {kind}",
        f"title: {title}",
        "tokens: 0",
        'load_when: ["alpha", "beta", "gamma"]',
        f"decay: {decay}",
    ]
    # Use the available-value path only when verified is present.
    if verified is not None:
        front.append(f"verified: {verified}")
    front.append("---")
    # Dedent the body on its own: joining it to the unindented front-matter first
    # would leave `dedent` with a common prefix of "" and silently do nothing.
    return write(
        root / "discipline" / kind / f"{name}.md",
        "\n".join(front) + "\n\n" + dedent(body),
    )


def codes(findings: Iterable[object]) -> list[str]:
    """Reduce findings to the identifiers a test can assert membership in.

    @param findings whatever a validation run produced
    @return one code per finding, in the order raised, duplicates kept
    """
    # Select f as the current element from findings]  # type while codes preserves traversal
    # Details: order.
    # Return one code per finding, in the order raised, duplicates kept to the caller.
    return [f.code for f in findings]  # type: ignore[attr-defined]


def run_on(root: Path) -> Sequence[object]:
    """Validate a throwaway corpus instead of the repository's own.

    @param root the directory holding a `discipline/` tree
    @return every finding, warnings included, since some checks only warn
    """
    # Return every finding, warnings included, since some checks only warn to the caller.
    return run(Layout(root))


# ---------------------------------------------------------------- the positive case


def test_conformant_corpus_is_silent(tmp_path: Path) -> None:
    """The control every other test depends on: the fixture defaults offend nothing.

    Without it, a test asserting a code appears could be satisfied by a fixture
    that was broken in some unrelated way all along.
    """
    module(tmp_path)
    assert codes(run_on(tmp_path)) == []


# ------------------------------------------------------- one failure proof per check


def test_v001_missing_front_matter(tmp_path: Path) -> None:
    """A file that will not parse is reported and dropped, not raised out of the run.

    One malformed document must not cost the report the state of the other hundred.
    """
    write(tmp_path / "discipline" / "law" / "TYPE.md", "# No front-matter here\n")
    assert "V001" in codes(run_on(tmp_path))


def test_v002_front_matter_schema_violation(tmp_path: Path) -> None:
    """Front-matter that the JSON schema rejects is reported, key by key.

    Three things are wrong here at once -- a title below the minimum length, a
    decay outside the enumeration, and a law module with no `load_when`.
    """
    write(
        tmp_path / "discipline" / "law" / "TYPE.md",
        """\
        ---
        id: law/TYPE
        kind: law
        title: T
        tokens: 0
        decay: forever
        ---
        """,
    )
    assert "V002" in codes(run_on(tmp_path))


def test_v003_id_does_not_match_filename(tmp_path: Path) -> None:
    """An id is resolved by opening the file it names, so a rename must carry it along.

    Left uncorrected, every agent that follows a citation to this module opens a
    path that no longer holds anything.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = module(tmp_path)
    # Publish the externally visible effect after all required inputs are ready.
    path.rename(path.with_name("TYPES.md"))
    assert "V003" in codes(run_on(tmp_path))


def test_v004_kind_does_not_match_directory(tmp_path: Path) -> None:
    """A law document filed under `fact/` is caught, because the genre governs what it may say.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    module(tmp_path, kind="law", name="TYPE")
    # Compute src using tmp_path / "discipline" / "law" / "TYPE.md" for later test v004 kind
    # Details: does not match directory logic.
    src = tmp_path / "discipline" / "law" / "TYPE.md"
    # Compute dst using tmp_path / "discipline" / "fact" / "TYPE.md" for later test v004 kind
    # Details: does not match directory logic.
    dst = tmp_path / "discipline" / "fact" / "TYPE.md"
    # Publish the externally visible effect after all required inputs are ready.
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Publish the externally visible effect after all required inputs are ready.
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    # Publish the externally visible effect after all required inputs are ready.
    src.unlink()
    assert "V004" in codes(run_on(tmp_path))


def test_v010_rule_in_a_non_rule_genre(tmp_path: Path) -> None:
    """Only law/ and ops/ may carry a rule at all, whatever force it claims.

    A rule housed in a fact module would expire with that module's `verified:`
    date, which is not a thing an obligation is allowed to do.
    """
    module(
        tmp_path,
        kind="fact",
        name="pytyping",
        verified="2026-06-16",
        body=CONFORMANT_RULE.replace("TYPE-001", "PYTYPING-001"),
    )
    assert "V010" in codes(run_on(tmp_path))


def test_v011_binding_in_a_frame_document(tmp_path: Path) -> None:
    """A frame document lays out the options; it may not settle one by force."""
    module(tmp_path, kind="frame", name="ARCH", body=CONFORMANT_RULE.replace("TYPE-", "ARCH-"))
    assert "V011" in codes(run_on(tmp_path))


def test_v012_law_pins_a_version(tmp_path: Path) -> None:
    """A version literal in a law module is an undated claim that will silently go stale.

    Version pins belong in a fact module, where a `verified:` date exposes their age.
    """
    module(tmp_path, body=CONFORMANT_RULE + "\nThe project runs mypy 2.3.1 in CI.\n")
    assert "V012" in codes(run_on(tmp_path))


def test_v020_duplicate_rule_id(tmp_path: Path) -> None:
    """One identifier naming two rules makes every citation ambiguous, so it is refused."""
    module(tmp_path)
    module(
        tmp_path,
        name="ERR",
        title="Errors",
        body=CONFORMANT_RULE,  # still declares TYPE-001
    )
    assert "V020" in codes(run_on(tmp_path))


def test_v021_prefix_does_not_match_module(tmp_path: Path) -> None:
    """An id must say which file holds it, so that grepping the id finds the rule."""
    module(tmp_path, name="ERR", title="Errors", body=CONFORMANT_RULE)
    assert "V021" in codes(run_on(tmp_path))


def test_v021_accepts_an_explicit_family_partition(tmp_path: Path) -> None:
    """A large rule family can split documents without renumbering public ids.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = module(
        tmp_path,
        name="TYPE-BOUNDARIES",
        body=CONFORMANT_RULE,
    )
    # Publish the externally visible effect after all required inputs are ready.
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "kind: law\n", "kind: law\nrule_prefix: TYPE\n",
        ),
        encoding="utf-8",
    )
    assert "V021" not in codes(run_on(tmp_path))


def test_v021_rejects_a_partition_prefix_unrelated_to_its_module(tmp_path: Path) -> None:
    """rule_prefix cannot become an arbitrary cross-module placement alias.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = module(
        tmp_path,
        name="ERR-BOUNDARIES",
        body=CONFORMANT_RULE,
    )
    # Publish the externally visible effect after all required inputs are ready.
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "kind: law\n", "kind: law\nrule_prefix: TYPE\n",
        ),
        encoding="utf-8",
    )
    assert "V021" in codes(run_on(tmp_path))


def test_v022_binding_without_a_check(tmp_path: Path) -> None:
    """Binding without naming the command that decides it is an unenforceable claim."""
    module(
        tmp_path,
        body="""\
        ### TYPE-001 · Domain code carries no Any  [BINDING] [auto:mypy]
        Domain modules MUST NOT use Any.
        - **Why** It erases the guarantee.
        """,
    )
    assert "V022" in codes(run_on(tmp_path))


def test_v023_binding_without_a_mechanism(tmp_path: Path) -> None:
    """A prose Check is not enough; the tag is what the enforcement ledger can count.

    Separate from V022 on purpose, and the mirror image of it: here a command is
    named with no tag to count it, there a tag is carried with no command to run.
    """
    module(
        tmp_path,
        body="""\
        ### TYPE-001 · Domain code carries no Any  [BINDING]
        Domain modules MUST NOT use Any.
        - **Check** `mypy --strict src/`
        """,
    )
    assert "V023" in codes(run_on(tmp_path))


def test_v024_overlong_title_warns(tmp_path: Path) -> None:
    """An unreadable heading is a legibility defect, not a broken contract, so it only warns.

    The severity is asserted as well as the code: a warning promoted to an error
    would fail the build over a long sentence.
    """
    # Compute long title using "Domain code carries no Any anywhere at all under any circum for
    # Details: later test v024 overlong title warns logic.
    long_title = "Domain code carries no Any anywhere at all under any circumstance"
    module(
        tmp_path,
        body=f"""\
        ### TYPE-001 · {long_title}  [BINDING] [auto:mypy]
        Domain modules MUST NOT use Any.
        - **Check** `mypy --strict src/`
        """,
    )
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = run_on(tmp_path)
    assert "V024" in codes(findings)
    # Select f as the current element from findings if f.code == "V024")  # type while test v024
    # Details: overlong title warns preserves traversal order.
    assert all(f.severity is Severity.WARN for f in findings if f.code == "V024")  # type: ignore[attr-defined]


def test_v025_retired_rule_carries_no_active_mechanism(tmp_path: Path) -> None:
    """A historical ID cannot continue to look like an executable obligation."""
    module(
        tmp_path,
        body="""\
        ### TYPE-001 · Historical rule  [RETIRED] [auto:mypy]
        Retired after its subject left scope.
        - **Check** `mypy --strict src/`
        """,
    )
    assert "V025" in codes(run_on(tmp_path))


def test_v030_advisory_without_a_justification(tmp_path: Path) -> None:
    """Demoting a rule to advice costs an argument for why no machine could decide it."""
    module(
        tmp_path,
        body="""\
        ### TYPE-001 · Prefer narrow protocols  [ADVISORY]
        Protocols SHOULD stay small.
        """,
    )
    assert "V030" in codes(run_on(tmp_path))


def test_v030_clears_once_justified(tmp_path: Path) -> None:
    """The other half of V030: a stated justification really does satisfy it.

    A check that fires on the bad input but also on the good one would forbid the
    very escape hatch the rule is meant to leave open.
    """
    module(
        tmp_path,
        body="""\
        ### TYPE-001 · Prefer narrow protocols  [ADVISORY]
        Protocols SHOULD stay small.
        - **No mechanism** "Small" is a judgment about intent that no check can make.
        """,
    )
    assert "V030" not in codes(run_on(tmp_path))


def test_v031_open_without_a_ledger_entry(tmp_path: Path) -> None:
    """An undecided rule must say, in the ledger, what question is open and what it blocks."""
    module(
        tmp_path,
        body="""\
        ### TYPE-001 · Pin the second checker  [OPEN]
        Blocked on choosing a checker.
        """,
    )
    assert "V031" in codes(run_on(tmp_path))


def test_v040_unresolved_cross_reference(tmp_path: Path) -> None:
    """A citation to a rule that does not exist sends the reader nowhere, and is caught."""
    module(
        tmp_path,
        body=CONFORMANT_RULE + "\nSee also [ERR-999] for the failure path.\n",
    )
    assert "V040" in codes(run_on(tmp_path))


def test_v040_ignores_a_backticked_example(tmp_path: Path) -> None:
    """Backticks mark an example rather than a link, so the corpus can show its own syntax.

    Without this exemption, SCHEMA.md could not document the reference form it defines.
    """
    module(tmp_path, body=CONFORMANT_RULE + "\nA reference looks like `[ERR-999]`.\n")
    assert "V040" not in codes(run_on(tmp_path))


def test_v041_dangling_document_reference(tmp_path: Path) -> None:
    """Naming a document that was never written is the source corpus's commonest defect.

    The originals carried roughly 130 of these, which is why the check exists at all.
    """
    module(tmp_path, body=CONFORMANT_RULE + "\nAs required by `PROPOSAL.md` section 4.\n")
    assert "V041" in codes(run_on(tmp_path))


def test_v041_does_not_resolve_a_reference_through_sources(tmp_path: Path) -> None:
    """Superseded material is not shipped, so resolving through it hides the defect.

    A reference that exists only under `sources/` passes in this repository and
    dangles in every vendored install -- green exactly where the validator is
    supposed to be the adopter's first check.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Compute superseded using tmp_path / "sources" / "doctrine" for later test v041 does not
    # Details: resolve a reference through sources logic.
    superseded = tmp_path / "sources" / "doctrine"
    # Publish the externally visible effect after all required inputs are ready.
    superseded.mkdir(parents=True)
    # Publish the externally visible effect after all required inputs are ready.
    (superseded / "TESTING.md").write_text("# superseded\n", encoding="utf-8")
    module(tmp_path, body=CONFORMANT_RULE + "\nSee `doctrine/TESTING.md` section 4.\n")
    assert "V041" in codes(run_on(tmp_path))


def test_v050_over_token_budget(tmp_path: Path) -> None:
    """A module too large to load is a module an agent will skip, so the ceiling binds."""
    # Preserve the observed item count used by the non-vacuity verdict.
    filler = "\n".join(f"Sentence number {n} of padding prose." for n in range(2_000))
    module(tmp_path, body=CONFORMANT_RULE + "\n" + filler)
    assert "V050" in codes(run_on(tmp_path))


def test_v060_stale_fact_warns(tmp_path: Path) -> None:
    """An expired verification date warns rather than fails, since age is not yet error.

    The date is computed from today, so the test cannot rot into a false pass the
    way a hard-coded one would.
    """
    # Compute stale using (dt.date.today() - dt.timedelta(days=400)).isoformat() for later test
    # Details: v060 stale fact warns logic.
    stale = (dt.date.today() - dt.timedelta(days=400)).isoformat()
    module(tmp_path, kind="fact", name="pytyping", verified=stale, decay="months", body="")
    assert "V060" in codes(run_on(tmp_path))


def test_v070_bare_use_of_a_banned_term(tmp_path: Path) -> None:
    """A term the sources used in conflicting senses must be qualified wherever it appears.

    The glossary is the input, not a constant: banning a term is done by writing
    a heading, and this proves the writing is what drives the check.
    """
    write(
        tmp_path / "discipline" / "meta" / "GLOSSARY.md",
        """\
        ---
        id: meta/GLOSSARY
        kind: meta
        title: Glossary
        tokens: 0
        decay: none
        ---

        ### coverage [BARE-BANNED]
        Say line coverage, branch coverage, or obligation coverage.
        """,
    )
    module(tmp_path, body=CONFORMANT_RULE + "\nThe suite must keep coverage high.\n")
    assert "V070" in codes(run_on(tmp_path))


# ------------------------------------------------- enforcement status is visible


def mechanism_resolvers() -> Iterator[tuple[str, str]]:
    """Every function in the repository that decides whether a mechanism is built.

    Recognised by shape rather than by name, so a copy reintroduced under a fresh
    name is still found: the implementation is the one function that joins
    `enforce/checks` and searches `fitness` for a definition. Test modules are
    skipped, this detector's own body being one of the shapes it looks for.

    @return each such function as its POSIX-relative file and its name
    """
    # Select directory as the current element from ("tools", "enforce") while mechanism
    # Details: resolvers preserves traversal order.
    # Advance mechanism resolvers through the current input element in declared order.
    for directory in ("tools", "enforce"):
        # Resolve the repository-confined path used by this operation before filesystem access.
        # Advance mechanism resolvers through the current input element in declared order.
        for path in sorted((REPO_ROOT / directory).rglob("*.py")):
            # Select the guarded path only after `path.stem.startswith('test_')` is satisfied.
            if path.stem.startswith("test_"):
                # Advance after the current candidate has been conclusively excluded.
                continue
            # Protect the fallible operation so expected failures remain explicitly classified.
            try:
                # Parse the Python source into the syntax tree used for structural
                # Details: fingerprinting.
                tree = ast.parse(path.read_text(encoding="utf-8"))
            # Translate the expected failure into this mechanism's stable diagnostic path.
            except (OSError, SyntaxError):  # pragma: no cover - not a corpus defect
                # Advance after the current candidate has been conclusively excluded.
                continue
            # Treat the current node as the candidate element consumed by the enclosing
            # Details: transformation.
            # Advance mechanism resolvers through the current input element in declared order.
            for node in ast.walk(tree):
                # Select the empty-or-disabled path when isinstance(node, (ast.FunctionDef,
                # Details: ast.AsyncFunctionDef)) has no usable value.
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Advance after the current candidate has been conclusively excluded.
                    continue
                # Retain the immutable source representation consumed by subsequent analysis.
                source = ast.get_source_segment(path.read_text(encoding="utf-8"), node) or ""
                # Select the guarded path only after `'"checks"' in source and '"fitness"' in
                # Details: source and ('exists()' in source)` is satisfied.
                if '"checks"' in source and '"fitness"' in source and "exists()" in source:
                    yield path.relative_to(REPO_ROOT).as_posix(), node.name


def test_the_mechanism_check_has_exactly_one_implementation() -> None:
    """Two copies would drift, and the artifacts would then disagree while both looked right.

    `validate.py` reports the absent case as V080 and `build_index.py` derives every
    rule's published status from it. A second copy is not a style complaint: it is
    two answers to "is this rule enforced", one of which is wrong and neither of
    which announces itself.
    """
    # Preserve the optional pattern match that carries the reported analysis count.
    found = sorted(mechanism_resolvers())
    assert found == [("tools/discipline_core.py", "mechanism_is_implemented")], found


def corpus(root: Path, *, built: Sequence[str] = ()) -> Path:
    """Lay down just enough tree for the mechanism resolver to answer against.

    @param root the throwaway root
    @param built the `check:` targets to create modules for, so a tag naming one
        resolves and a tag naming anything else does not
        Each element is one checker-module stem in caller order.
    @return the same root, for use as the resolution root

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Compute checks using root / "enforce" / "checks" for later corpus logic.
    checks = root / "enforce" / "checks"
    # Publish the externally visible effect after all required inputs are ready.
    checks.mkdir(parents=True, exist_ok=True)
    # Normalize the current repository path to its portable baseline key spelling.
    # Advance corpus through the current input element in declared order.
    for name in built:
        # Publish the externally visible effect after all required inputs are ready.
        (checks / f"{name}.py").write_text("", encoding="utf-8")
    # Return the same root, for use as the resolution root to the caller.
    return root


@pytest.mark.parametrize(
    ("mechanisms", "expected"),
    [
        ((), Enforcement.UNMECHANIZED),
        (("check:present",), Enforcement.MECHANIZED),
        (("check:absent",), Enforcement.UNBUILT),
        (("check:present", "check:absent"), Enforcement.UNBUILT),
        (("review",), Enforcement.REVIEW),
        (("auto:ruff:D100",), Enforcement.EXTERNAL),
        (("check:present", "review"), Enforcement.EXTERNAL),
    ],
)
def test_every_status_is_reachable(
    tmp_path: Path, mechanisms: tuple[str, ...], expected: Enforcement
) -> None:
    """Each value in the vocabulary is produced by some real mechanism set.

    A status nothing can produce is a status that means nothing, and the pairs here
    are the ones the classification must never confuse -- in particular an empty
    set, which reads as "every mechanism resolved" to anyone who forgets that a
    universal over nothing is true.

    @param tmp_path throwaway mechanism tree
    @param mechanisms mechanism tags; each element is one evidence mechanism in tuple order
    @param expected classification required for that mechanism tuple
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = corpus(tmp_path, built=["present"])
    assert enforcement_of(mechanisms, root) is expected


def test_review_only_is_never_counted_as_enforced(tmp_path: Path) -> None:
    """A person deciding a rule is not a gate deciding it.

    This is the one classification the corpus's own axiom turns on: counting
    judgment as mechanical enforcement is exactly the overstatement the status
    field was added to remove.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = corpus(tmp_path)
    assert enforcement_of(("review",), root).is_mechanical is False
    assert Enforcement.UNBUILT.is_mechanical is False
    assert Enforcement.UNMECHANIZED.is_mechanical is False
    assert Enforcement.MECHANIZED.is_mechanical is True


@pytest.mark.parametrize(
    ("mechanisms", "expected_mechanical"),
    [
        (("review",), 0),
        (("check:present",), 1),
        (("check:absent",), 0),
        (("auto:mypy",), 1),
        (("review", "check:present"), 1),
        (("review", "check:absent"), 0),
        (("auto:mypy", "check:absent"), 1),
    ],
)
def test_mechanical_claim_census_keeps_each_real_arm(
    tmp_path: Path, mechanisms: tuple[str, ...], expected_mechanical: int,
) -> None:
    """Review is excluded without hiding a working arm behind an unbuilt one.

    @param tmp_path throwaway mechanism tree
    @param mechanisms heading mechanism set
        Each element is one evidence mechanism tag; set order is deliberately unordered.
    @param expected_mechanical one when the set claims a mechanical proposition
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = corpus(tmp_path, built=["present"])
    assert has_mechanical_claim(mechanisms, root) is bool(expected_mechanical)


def test_an_unverifiable_mechanism_is_none_not_false(tmp_path: Path) -> None:
    """`auto:` and `review` are undecidable here, and undecided is not absent.

    Flattening them to False would report every externally checked rule as unbuilt
    and bury the 106 that really are.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = corpus(tmp_path, built=["present"])
    assert mechanism_is_implemented("auto:mypy", root) is None
    assert mechanism_is_implemented("review", root) is None
    assert mechanism_is_implemented("check:present", root) is True
    assert mechanism_is_implemented("check:absent", root) is False


def test_rules_json_separates_verification_from_normative_force() -> None:
    """The generated contract carries complete evidence without a synthetic verdict."""
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = REPO_ROOT / "discipline" / "rules.json"
    # Select the existing-artifact path only when `not path.exists()` is satisfied.
    if not path.exists():
        pytest.skip("discipline/rules.json not built; run tools/build_index.py")
    # Decode generated-index field keys to their JSON values; mapping key order is deliberately
    # unused.
    payload = json.loads(path.read_text(encoding="utf-8"))
    # Compute rules using payload["rules"] for later test rules json separates verification from
    # Details: normative force logic.
    rules = payload["rules"]
    # Collect unique vocabulary element values; their order is deliberately unordered.
    vocabulary = {str(value) for value in VerificationState}
    # Each unknown key is a rule id and each value is its invalid verification state; mapping key
    # order is deliberately unused.
    unknown = {
        rule["id"]: rule.get("verification", {}).get("state")
        for rule in rules
        if rule.get("verification", {}).get("state") not in vocabulary
    }
    assert unknown == {}, unknown
    # Select rule as the current element from rules) while test rules json separates
    # Details: verification from normative force preserves traversal order.
    assert all("enforcement" not in rule for rule in rules)
    # Select rule as the current element from rules) while test rules json separates
    # Details: verification from normative force preserves traversal order.
    assert all("mechanically_enforced" not in rule for rule in rules)
    # Select rule as the current element from rules) while test rules json separates
    # Details: verification from normative force preserves traversal order.
    assert all(rule["verification"].get("strategies") is not None for rule in rules)
    # Select rule as the current element from rules) while test rules json separates
    # Details: verification from normative force preserves traversal order.
    assert all("failure_mode" in rule and "migration" in rule for rule in rules)
    # Compute observations using payload["field_observations"] for later test rules json
    # Details: separates verification from normative force logic.
    observations = payload["field_observations"]
    # Collect unique referenced element values; their order is deliberately unordered.
    referenced = {observation for rule in rules for observation in rule["field_observations"]}
    assert referenced <= set(observations)
    # Bind observation to the current value used by the next test rules json separates
    # Details: verification from normative force decision.
    assert all(
        "claim" in observation and "scope" in observation for observation in observations.values()
    )


def test_index_md_carries_the_distinct_evidence_columns() -> None:
    """An agent grepping the index cannot confuse force with verifier evidence."""
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = REPO_ROOT / "discipline" / "INDEX.md"
    # Select the existing-artifact path only when `not path.exists()` is satisfied.
    if not path.exists():
        pytest.skip("discipline/INDEX.md not built; run tools/build_index.py")
    # Retain the immutable source representation consumed by subsequent analysis.
    text = path.read_text(encoding="utf-8")
    assert (
        "| Rule | Force | Verifier | Relation | Rejection | Platforms | Residual | Field | Title |"
    ) in text
    assert "`local-verifier`" in text
    assert "`external-verifier`" in text
    assert "`proxy`" in text
    assert "rule-level witnessed" in text


def test_nav_renders_a_binding_unbuilt_verifier_distinguishably() -> None:
    """The whole point, at the surface an agent actually reads.

    Two rules alike in force and unlike in whether anything decides them must not
    render alike, or the navigator has reproduced the defect it was meant to fix.
    """
    # Each available key is a navigator rule-record field and each value is its synthetic
    # content; mapping key order is deliberately unused.
    available = {
        "id": "ARCH-001",
        "label": "governed",
        "type": "rule",
        "hops": 0,
        "reason": "governs domain/",
        "force": "BINDING",
        "verification": "local-verifier",
    }
    # Each unbuilt key is a navigator rule-record field and each value is its synthetic content;
    # mapping key order is deliberately unused.
    unbuilt = {**available, "id": "ARCH-008", "verification": "unbuilt"}
    # Compute rendered using nav.render for later test nav renders a binding unbuilt verifier
    # Details: distinguishably logic.
    rendered = nav.render("applies", {"path": "p.py", "rules": [available, unbuilt], "modules": []})
    assert "ARCH-008" in rendered
    assert "[BINDING - VERIFIER NOT BUILT]" in rendered
    # Each lines key is a rendered rule id and each value is its full output row; mapping key
    # order is deliberately unused.
    lines = {row.split()[0]: row for row in rendered.splitlines() if row.startswith("  ")}
    assert lines["ARCH-001"] != lines["ARCH-008"].replace("ARCH-008", "ARCH-001")
    assert "VERIFIER NOT BUILT" not in lines["ARCH-001"]


def test_nav_warns_on_a_binding_rule_without_a_verifier() -> None:
    """`nav rule` states the availability gap without fabricating a result."""
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = REPO_ROOT / "discipline" / "rules.json"
    # Select the existing-artifact path only when `not path.exists()` is satisfied.
    if not path.exists():
        pytest.skip("discipline/rules.json not built; run tools/build_index.py")
    # Locate the structural boundary used to parse the external result safely.
    index = nav.verification_index(REPO_ROOT)
    assert index, "rules.json carried no verifier states"
    assert nav.force_tag("BINDING", "unbuilt") == "[BINDING - VERIFIER NOT BUILT]"
    assert nav.force_tag("BINDING", "local-verifier") == "[BINDING]"
    assert nav.force_tag("BINDING", "structured-review") == ("[BINDING - STRUCTURED REVIEW]")
    assert not nav.force_tag(None, "unbuilt")


# -------------------------------------------------------------- the V080 ratchet


def test_baseline_round_trips(tmp_path: Path) -> None:
    """What `write_v080_baseline` writes is exactly what `load_v080_baseline` reads back."""
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = tmp_path / "baseline.json"
    # Compute pairs using frozenset for later test baseline round trips logic.
    pairs = frozenset({("ALLOC-001", "check:x"), ("ALLOC-002", "check:y")})
    write_v080_baseline(pairs, "test fixture", path)
    # Compute loaded using load v080 baseline for later test baseline round trips logic.
    loaded = load_v080_baseline(path)
    assert loaded == V080Baseline(count=2, pairs=pairs, why="test fixture")


def test_a_hand_raised_count_is_refused(tmp_path: Path) -> None:
    """Proof-of-failure: the cheapest way to switch V081 off must not work.

    `count` and `pairs` are two statements of one fact, and only `count`
    decides whether V081 fires. Editing it upward alone would raise the ceiling
    for every rule at once, leave the pair list intact so the file still looks
    like the tool's own output, and produce no finding. The load must reject
    the disagreement instead of trusting the integer.

    @param tmp_path pytest's per-test temporary directory

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = tmp_path / "baseline.json"
    write_v080_baseline(frozenset({("ALLOC-001", "check:x")}), "test fixture", path)
    # Compute data using json.loads for later test a hand raised count is refused logic.
    data = json.loads(path.read_text(encoding="utf-8"))
    # Update test a hand raised count is refused state only after the required source facts are
    # Details: available.
    data["count"] = 9999
    # Publish the externally visible effect after all required inputs are ready.
    path.write_text(json.dumps(data), encoding="utf-8")

    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(ValueError, match="pairs"):
        load_v080_baseline(path)


@pytest.mark.parametrize("payload", [{"pairs": []}, {"count": 0}, {}])
def test_a_baseline_missing_a_field_is_refused(tmp_path: Path, payload: dict[str, object]) -> None:
    """A half-written baseline is named as one, not raised as a KeyError.

    @param tmp_path pytest's per-test temporary directory
    @param payload a JSON body lacking one or both required fields
        Each key is a candidate baseline field and each value is its malformed test content;
        mapping key order is deliberately unused.

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = tmp_path / "baseline.json"
    # Publish the externally visible effect after all required inputs are ready.
    path.write_text(json.dumps(payload), encoding="utf-8")

    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(ValueError, match="not a V080 baseline"):
        load_v080_baseline(path)


def test_missing_baseline_file_reads_as_empty(tmp_path: Path) -> None:
    """No baseline on disk is a ceiling of zero, not an unchecked ceiling.

    A fresh clone with no baseline must fail closed on the first unbuilt
    mechanism rather than pass by default because nothing was ever recorded.
    """
    assert load_v080_baseline(tmp_path / "absent.json") == V080Baseline(
        count=0, pairs=frozenset(), why=None
    )


def test_v081_fires_when_the_unbuilt_count_rises(tmp_path: Path) -> None:
    """A new rule naming a mechanism nothing has built pushes the count past the ceiling.

    Proof of failure for FLOW-007/TEST-015: the ceiling starts at zero here, so
    one unbuilt mechanism is already over it, and V081 must say so as an error.
    """
    module(tmp_path, body=CONFORMANT_RULE.replace("[auto:mypy]", "[check:not_yet_written]"))
    # Compute layout using Layout for later test v081 fires when the unbuilt count rises logic.
    layout = Layout(tmp_path)
    # Compute documents using load documents for later test v081 fires when the unbuilt count
    # Details: rises logic.
    documents, _ = load_documents(layout)
    # Hold baseline path keys mapped to their recorded behavior-fingerprint values.
    baseline = V080Baseline(count=0, pairs=frozenset(), why=None)
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = list(check_v080_ratchet(documents, layout, baseline=baseline))
    # Select f as the current element from findings] == ["V081"] while test v081 fires when the
    # Details: unbuilt count rises preserves traversal order.
    assert [f.code for f in findings] == ["V081"]
    assert findings[0].severity is Severity.ERROR
    assert "TYPE-001" in findings[0].message
    assert "not_yet_written" in findings[0].message


def test_v081_is_silent_when_a_new_rule_names_a_built_mechanism(tmp_path: Path) -> None:
    """The counterargument this ratchet must answer: a new rule with a real mechanism.

    A legitimate new rule paired with a real mechanism costs the count nothing
    and must not be blocked.

    `CONFORMANT_RULE` tags `[auto:mypy]`, which `mechanism_is_implemented` reports
    as unverifiable here (None), not absent (False) -- so it never enters the
    unbuilt set at all, and the baseline does not have to already know this rule
    to leave it alone.
    """
    module(tmp_path)  # CONFORMANT_RULE, unmodified: [auto:mypy]
    # Compute layout using Layout for later test v081 is silent when a new rule names a built
    # Details: mechanism logic.
    layout = Layout(tmp_path)
    # Compute documents using load documents for later test v081 is silent when a new rule names
    # Details: a built mechanism logic.
    documents, _ = load_documents(layout)
    # Hold baseline path keys mapped to their recorded behavior-fingerprint values.
    baseline = V080Baseline(count=0, pairs=frozenset(), why=None)
    assert list(check_v080_ratchet(documents, layout, baseline=baseline)) == []


def test_v082_warns_without_failing_when_the_unbuilt_count_falls(tmp_path: Path) -> None:
    """Building a mechanism the baseline still lists as missing is progress, not a defect.

    Proof of failure for the other direction: V082 must fire (so the drop is on
    the record) and must be a warning, never an error -- the acceptance case this
    ratchet exists to keep out of everyone's way.
    """
    module(tmp_path)  # CONFORMANT_RULE: zero unbuilt mechanisms here
    # Compute layout using Layout for later test v082 warns without failing when the unbuilt
    # Details: count falls logic.
    layout = Layout(tmp_path)
    # Compute documents using load documents for later test v082 warns without failing when the
    # Details: unbuilt count falls logic.
    documents, _ = load_documents(layout)
    # Hold baseline path keys mapped to their recorded behavior-fingerprint values.
    baseline = V080Baseline(
        count=3,
        pairs=frozenset({("X-001", "check:a"), ("X-002", "check:b"), ("X-003", "check:c")}),
        why="prior state",
    )
    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = list(check_v080_ratchet(documents, layout, baseline=baseline))
    # Select f as the current element from findings] == ["V082"] while test v082 warns without
    # Details: failing when the unbuilt count falls preserves traversal order.
    assert [f.code for f in findings] == ["V082"]
    assert findings[0].severity is Severity.WARN


def test_v08x_silent_when_the_count_matches_the_baseline(tmp_path: Path) -> None:
    """No news, no finding: an unchanged count is the ordinary, silent case."""
    module(tmp_path, body=CONFORMANT_RULE.replace("[auto:mypy]", "[check:not_yet_written]"))
    # Compute layout using Layout for later test v08x silent when the count matches the baseline
    # Details: logic.
    layout = Layout(tmp_path)
    # Compute documents using load documents for later test v08x silent when the count matches
    # Details: the baseline logic.
    documents, _ = load_documents(layout)
    # Hold baseline path keys mapped to their recorded behavior-fingerprint values.
    baseline = V080Baseline(
        count=1, pairs=frozenset({("TYPE-001", "check:not_yet_written")}), why="prior"
    )
    assert list(check_v080_ratchet(documents, layout, baseline=baseline)) == []


def test_ratchet_ignores_a_throwaway_tree_when_no_baseline_is_injected(tmp_path: Path) -> None:
    """Without an injected baseline, the check only ever compares the real repository.

    Loading the checked-in baseline (106 real pairs) against a one-rule synthetic
    fixture would report the fixture as having lost the other 105 -- which is what
    `test_conformant_corpus_is_silent` would catch, since it runs through `run()`
    exactly this way. This test pins the guard directly.
    """
    module(tmp_path, body=CONFORMANT_RULE.replace("[auto:mypy]", "[check:not_yet_written]"))
    # Compute layout using Layout for later test ratchet ignores a throwaway tree when no
    # Details: baseline is injected logic.
    layout = Layout(tmp_path)
    # Compute documents using load documents for later test ratchet ignores a throwaway tree
    # Details: when no baseline is injected logic.
    documents, _ = load_documents(layout)
    assert list(check_v080_ratchet(documents, layout)) == []


def test_update_baseline_requires_why(tmp_path: Path) -> None:
    """`--update-baseline` with no `--why` refuses, in the `learn.py calibrate --set` idiom."""
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(SystemExit):
        validate_main(["--update-baseline", "--root", str(tmp_path)])


# --------------------------------------------------------------- the real corpus


@pytest.mark.timeout(90)
def test_the_live_corpus_is_clean() -> None:
    """The repository itself passes every check."""
    # Each findings element is one live-corpus error in validator emission order.
    findings = [f for f in run() if f.severity is Severity.ERROR]  # type: ignore[attr-defined]
    # Select f as the current element from findings)  # type while test the live corpus is clean
    # Details: preserves traversal order.
    assert findings == [], "\n".join(f.render() for f in findings)  # type: ignore[attr-defined]


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    # Propagate the localized failure so callers cannot mistake it for success.
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_v051_warns_before_the_always_loaded_ceiling(tmp_path: Path) -> None:
    """The always-loaded file is warned about before it hits the wall, not at it.

    `V050` fails at the ceiling, by which point the addition has been written and
    the author is being asked to undo it. KERNEL stood at 94% of its budget with
    nobody aware, and the next router line would have breached it.

    @param tmp_path the fixture directory

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Compute kernel using tmp_path / "discipline" / "KERNEL.md" for later test v051 warns
    # Details: before the always loaded ceiling logic.
    kernel = tmp_path / "discipline" / "KERNEL.md"
    # Publish the externally visible effect after all required inputs are ready.
    kernel.parent.mkdir(parents=True, exist_ok=True)
    module(tmp_path, body=CONFORMANT_RULE)
    # Preserve the observed item count used by the non-vacuity verdict.
    filler = "\n".join(f"Padding sentence {n}." for n in range(430))
    # Publish the externally visible effect after all required inputs are ready.
    kernel.write_text(
        "---\nid: meta/KERNEL\nkind: meta\ntitle: Kernel\ntokens: 0\n"
        'load_when: ["x"]\ndecay: none\n---\n\n# Kernel\n\n' + filler + "\n",
        encoding="utf-8",
    )
    # Preserve the optional pattern match that carries the reported analysis count.
    found = codes(run_on(tmp_path))
    assert "V051" in found or "V050" in found, (
        "a nearly-full always-loaded file produced no signal at all"
    )


def test_v097_notices_a_loop_that_only_writes(tmp_path: Path) -> None:
    """A ledger with learnings and no outcomes cannot compute precision.

    The subsystem's most valuable half is knowing which learnings were noise, and
    that rested on a habit. Ninety-five recorded, two reported.

    @param tmp_path the fixture directory

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    module(tmp_path)
    # Compute ledger using tmp_path / "learning" / "ledger.jsonl" for later test v097 notices a
    # Details: loop that only writes logic.
    ledger = tmp_path / "learning" / "ledger.jsonl"
    # Publish the externally visible effect after all required inputs are ready.
    ledger.parent.mkdir(parents=True, exist_ok=True)
    # Preserve the observed item count used by the non-vacuity verdict.
    # Publish the externally visible effect after all required inputs are ready.
    ledger.write_text(
        "\n".join(
            json.dumps({
                "seq": n,
                "kind": "learn",
                "id": f"L-{n:04d}",
                "session": "S-1",
                "ts": "2026-08-19T00:00:00+00:00",
                "actor": "agent",
                "payload": {},
            })
            for n in range(1, 21)
        )
        + "\n",
        encoding="utf-8",
    )
    assert "V097" in codes(run_on(tmp_path))


def test_v097_is_silent_once_outcomes_are_reported(tmp_path: Path) -> None:
    """...and stops once the loop closes, so it is a prompt and not a nag.

    A check that keeps complaining after it has been satisfied is one people
    learn to read past, which costs every other warning beside it.

    @param tmp_path the fixture directory

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    module(tmp_path)
    # Compute ledger using tmp_path / "learning" / "ledger.jsonl" for later test v097 is silent
    # Details: once outcomes are reported logic.
    ledger = tmp_path / "learning" / "ledger.jsonl"
    # Publish the externally visible effect after all required inputs are ready.
    ledger.parent.mkdir(parents=True, exist_ok=True)
    # Preserve the observed item count used by the non-vacuity verdict.
    events = [
        {
            "seq": n,
            "kind": "learn",
            "id": f"L-{n:04d}",
            "session": "S-1",
            "ts": "2026-08-19T00:00:00+00:00",
            "actor": "agent",
            "payload": {},
        }
        for n in range(1, 11)
    ] + [
        {
            "seq": 20 + n,
            "kind": "use",
            "id": f"L-{n:04d}",
            "session": "S-1",
            "ts": "2026-08-19T00:00:00+00:00",
            "actor": "agent",
            "payload": {"outcome": "helped"},
        }
        for n in range(1, 4)
    ]
    # Select e as the current element from events) + "\n", encoding="utf-8") while test v097 is
    # Details: silent once outcomes are reported preserves traversal order.
    # Publish the externally visible effect after all required inputs are ready.
    ledger.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    assert "V097" not in codes(run_on(tmp_path))
