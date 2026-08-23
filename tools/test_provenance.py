"""Claim-level provenance fails closed on every unreviewed source change."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from build_provenance import (
    COMMENTING_CLAIM_COUNT,
    COMMENTING_LEDGER,
    COMMENTING_POLICIES,
    COMMENTING_SHA256,
    COMMENTING_SOURCE,
    ClaimPolicy,
    build_claim_rows,
    render_claim_ledger,
    verify_commenting_source,
)

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Sequence

## The committed mechanical census consumed by the provenance builder.
EXTRACTION = Path(__file__).with_name("extraction.yaml")


def _candidates() -> Sequence[dict[str, object]]:
    """Load the same extracted statements the production builder consumes.

    @return candidate dictionaries from the committed extraction
    """
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    payload = yaml.safe_load(EXTRACTION.read_text(encoding="utf-8"))
    # Compute candidates using payload["candidates"] for later candidates logic.
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    # Return candidate dictionaries from the committed extraction to the caller.
    return candidates


def test_frozen_source_and_all_claims_are_accounted_for() -> None:
    """The frozen input has one unique reviewed row for every extracted claim."""
    # Derive digest from verify commenting source for the next test frozen source and all claims
    # Details: are accounted for decision.
    digest = verify_commenting_source()
    # Preserve rows element values in deterministic source order.
    rows = build_claim_rows(_candidates())

    assert digest == COMMENTING_SHA256
    assert len(rows) == COMMENTING_CLAIM_COUNT
    # Select row as the current element from rows}) == len(rows) while test frozen source and
    # Details: all claims are accounted for preserves traversal order.
    assert len({row.claim_id for row in rows}) == len(rows)
    # Select row as the current element from rows) while test frozen source and all claims are
    # Details: accounted for preserves traversal order.
    assert all(row.disposition != "UNREVIEWED" for row in rows)


def test_changed_source_is_rejected(tmp_path: Path) -> None:
    """A one-byte input mutation invalidates all previous dispositions.

    @param tmp_path isolated source copy that may be damaged safely

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Derive changed from tmp_path / "input.md" for the next test changed source is rejected
    # Details: decision.
    changed = tmp_path / "input.md"
    # Publish the externally visible effect after all required inputs are ready.
    changed.write_bytes(COMMENTING_SOURCE.read_bytes() + b"\n")

    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(ValueError, match="input changed"):
        verify_commenting_source(changed)


def test_missing_policy_is_reported_as_unreviewed() -> None:
    """Removing an owning policy cannot silently discard its claims."""
    # Select policies, policy as the current element from COMMENTING_POLICIES if policy.section
    # Details: != 1) while test missing policy is reported as unreviewed preserves traversal order.
    policies = tuple(policy for policy in COMMENTING_POLICIES if policy.section != 1)

    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(ValueError, match="is unreviewed"):
        build_claim_rows(_candidates(), policies)


def test_duplicate_policy_is_reported_as_multiply_claimed() -> None:
    """A second apparent owner cannot overwrite the first owner's judgment."""
    # Derive first from COMMENTING_POLICIES[0] for the next test duplicate policy is reported as
    # Details: multiply claimed decision.
    first = COMMENTING_POLICIES[0]
    # Derive duplicate from ClaimPolicy for the next test duplicate policy is reported as
    # Details: multiply claimed decision.
    duplicate = ClaimPolicy(
        section=first.section,
        disposition="retained",
        targets=("law/DOC",),
        reason="Deliberate collision used to prove duplicate detection.",
    )

    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(ValueError, match="multiply claimed"):
        build_claim_rows(_candidates(), (*COMMENTING_POLICIES, duplicate))


def test_changed_claim_identity_is_rejected() -> None:
    """A stale identity cannot be attached to altered claim text."""
    # Treat the current candidate, item as the candidate element consumed by the enclosing
    # Details: transformation.
    candidate = next(item for item in _candidates() if item.get("source") == "CD")
    # Treat altered as mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    altered = {**candidate, "text": f"{candidate['text']} altered"}

    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(ValueError, match="altered claim identity"):
        build_claim_rows([altered])


def test_committed_ledger_is_the_deterministic_projection() -> None:
    """The claim evidence on disk is exactly the builder's sorted projection."""
    # Preserve rows element values in deterministic source order.
    rows = build_claim_rows(_candidates())
    # Derive expected from render claim ledger for the next test committed ledger is the
    # Details: deterministic projection decision.
    expected = render_claim_ledger(rows, COMMENTING_SHA256)

    assert COMMENTING_LEDGER.read_text(encoding="utf-8") == expected
    # Derive parsed from json.loads for the next test committed ledger is the deterministic
    # Details: projection decision.
    parsed = json.loads(expected)
    assert parsed["unreviewed_count"] == 0
    assert parsed["multiply_claimed_count"] == 0
