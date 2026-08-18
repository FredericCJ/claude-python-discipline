"""Proof-of-failure tests for `validate.py`.

Every check gets a test that drives it to fire. This is the corpus's own
anti-vacuity rule turned on the tooling: a check whose passing signal is "no
output" must first be shown capable of producing a failing signal, or its silence
means nothing.

    pytest tools/test_validate.py
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from pathlib import Path
from textwrap import dedent

import pytest

from validate import Layout, Severity, run

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
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text), encoding="utf-8")
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
    front = [
        "---",
        f"id: {kind}/{name}",
        f"kind: {kind}",
        f"title: {title}",
        "tokens: 0",
        'load_when: ["alpha", "beta", "gamma"]',
        f"decay: {decay}",
    ]
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
    return [f.code for f in findings]  # type: ignore[attr-defined]


def run_on(root: Path) -> Sequence[object]:
    """Validate a throwaway corpus instead of the repository's own.

    @param root the directory holding a `discipline/` tree
    @return every finding, warnings included, since some checks only warn
    """
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
    """
    path = module(tmp_path)
    path.rename(path.with_name("TYPES.md"))
    assert "V003" in codes(run_on(tmp_path))


def test_v004_kind_does_not_match_directory(tmp_path: Path) -> None:
    """A law document filed under `fact/` is caught, because the genre governs what it may say."""
    module(tmp_path, kind="law", name="TYPE")
    src = tmp_path / "discipline" / "law" / "TYPE.md"
    dst = tmp_path / "discipline" / "fact" / "TYPE.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
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
    long_title = "Domain code carries no Any anywhere at all under any circumstance"
    module(
        tmp_path,
        body=f"""\
        ### TYPE-001 · {long_title}  [BINDING] [auto:mypy]
        Domain modules MUST NOT use Any.
        - **Check** `mypy --strict src/`
        """,
    )
    findings = run_on(tmp_path)
    assert "V024" in codes(findings)
    assert all(f.severity is Severity.WARN for f in findings if f.code == "V024")  # type: ignore[attr-defined]


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


def test_v050_over_token_budget(tmp_path: Path) -> None:
    """A module too large to load is a module an agent will skip, so the ceiling binds."""
    filler = "\n".join(f"Sentence number {n} of padding prose." for n in range(2_000))
    module(tmp_path, body=CONFORMANT_RULE + "\n" + filler)
    assert "V050" in codes(run_on(tmp_path))


def test_v060_stale_fact_warns(tmp_path: Path) -> None:
    """An expired verification date warns rather than fails, since age is not yet error.

    The date is computed from today, so the test cannot rot into a false pass the
    way a hard-coded one would.
    """
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


# --------------------------------------------------------------- the real corpus


def test_the_live_corpus_is_clean() -> None:
    """The repository itself passes every check."""
    findings = [f for f in run() if f.severity is Severity.ERROR]  # type: ignore[attr-defined]
    assert findings == [], "\n".join(f.render() for f in findings)  # type: ignore[attr-defined]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
