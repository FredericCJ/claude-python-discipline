"""The matrix is not a rubber stamp, and its ratchet can fall.

**Oracle: contract.** The declared table in `discrimination.py` is held against the
properties that make a coverage count mean anything.

`D` is a ratchet, and a ratchet invites gaming: one trivial mutation per rule would
raise the number and prove nothing. So the count is not the only thing checked.
Every entry must carry a source, exactly one rule, and a mutation whose *shape*
differs from the others — thirty copies of "delete a docstring" would be thirty
entries and one idea.

The `D` ratchet itself is exercised in `tools/test_discrimination_gate.py`; what is
here is the table's own integrity.

    pytest enforce/test_discrimination.py
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Final

import pytest

import discrimination

## How much a `source` must say before it counts as reasoned. The same proxy, and
## the same admission, as `test_decisions.py`: length cannot tell an argument from
## a paragraph of restatement. What it does decide is the case the rule is about --
## an entry that names no reason and stops.
MIN_SOURCE: Final = 60


def test_every_entry_names_one_rule() -> None:
    """A mutation provoking two rules cannot say which one discriminated.

    The same reason `broken_copy` breaks one thing at a time: with two changes in
    flight, a finding attributes to neither.
    """
    for mutation in discrimination.MUTATIONS:
        assert mutation.rule_id, f"{mutation.summary!r} names no rule"
        assert " " not in mutation.rule_id.strip(), (
            f"{mutation.rule_id!r} looks like more than one id"
        )


def test_every_entry_states_why_this_mutation() -> None:
    """`D` rising is necessary and nowhere near sufficient.

    An entry that cannot say why this mutation tests this rule is a rubber stamp,
    and a rubber stamp raises the number while leaving the mechanism unwatched --
    which is the exact condition the matrix was built to end.
    """
    for mutation in discrimination.MUTATIONS:
        assert len(mutation.source) >= MIN_SOURCE, (
            f"{mutation.rule_id} carries {len(mutation.source)} characters of "
            f"source. Name the finding it came from, or the clause it exercises."
        )


def test_mutation_shapes_differ() -> None:
    """Thirty entries of one shape are thirty entries and one idea.

    The cheapest way to inflate `D` is to repeat a single trick against every
    rule. This does not prove the mutations are *good*; it refuses the one
    degenerate case a count cannot see.
    """
    shapes = Counter(
        (bool(m.drop), bool(m.write), bool(m.replace), m.base)
        for m in discrimination.MUTATIONS
    )
    assert len(shapes) > 1, (
        f"every mutation has the same shape {next(iter(shapes))}; the matrix is "
        f"testing one idea against many rules"
    )
    commonest, count = shapes.most_common(1)[0]
    assert count < len(discrimination.MUTATIONS), (
        f"all {count} entries share the shape {commonest}"
    )


def test_every_rule_named_exists() -> None:
    """A mutation for a rule that is not in the corpus provokes nothing forever.

    @throws pytest.skip.Exception when the generated index has not been built
    """
    rules = pytest.importorskip("json").loads(
        (discrimination_root() / "rules.json").read_text(encoding="utf-8")
    )
    known = {rule["id"] for rule in rules["rules"]}
    unknown = sorted(discrimination.covered() - known)
    assert not unknown, f"mutations name rules the corpus does not carry: {unknown}"


def test_no_rule_is_declared_twice_without_reason() -> None:
    """Two mutations for one rule are allowed, and must not be duplicates.

    More than one is often right -- a rule with two clauses deserves two -- but
    two entries with the same summary are one entry written twice.
    """
    for rule_id, entries in discrimination.by_rule().items():
        summaries = [m.summary for m in entries]
        assert len(summaries) == len(set(summaries)), (
            f"{rule_id} declares the same mutation twice"
        )


def test_the_base_is_one_of_the_known_kinds() -> None:
    """An unknown base would be built by nothing and silently provoke nothing."""
    for mutation in discrimination.MUTATIONS:
        assert mutation.base in discrimination.BASES, (
            f"{mutation.rule_id} names base {mutation.base!r}, which the runner "
            f"cannot build"
        )


def test_every_entry_chooses_one_observation_mode() -> None:
    """A rejection cannot be credited simultaneously through different oracles."""
    for mutation in discrimination.MUTATIONS:
        modes = sum(bool(value) for value in (mutation.node, mutation.proof, mutation.tool))
        assert modes <= 1, f"{mutation.rule_id} declares {modes} observation modes"
        assert bool(mutation.tool) is bool(mutation.diagnostic), (
            f"{mutation.rule_id} must pair an external tool with its exact diagnostic"
        )
        if mutation.proof:
            assert not mutation.drop, f"{mutation.rule_id} proof also drops fixture paths"
            assert not mutation.write, f"{mutation.rule_id} proof also writes fixture paths"
            assert not mutation.replace, (
                f"{mutation.rule_id} duplicates damage already owned by {mutation.proof}"
            )


def discrimination_root() -> Path:
    """Where the generated rule index lives.

    @return the `discipline/` directory holding `rules.json`
    """
    return Path(__file__).resolve().parent.parent / "discipline"
