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
    # Decode the committed extraction and select its ordered candidate-record list.
    payload = yaml.safe_load(EXTRACTION.read_text(encoding="utf-8"))
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    return candidates


def test_frozen_source_and_all_claims_are_accounted_for() -> None:
    """The frozen input has one unique reviewed row for every extracted claim."""
    # Digest authenticates source bytes; rows prove every extracted proposition has one owner.
    digest = verify_commenting_source()
    # Preserve rows element values in deterministic source order.
    rows = build_claim_rows(_candidates())

    # These assertions compare source identity, census cardinality, uniqueness, and disposition.
    assert digest == COMMENTING_SHA256
    assert len(rows) == COMMENTING_CLAIM_COUNT
    assert len({row.claim_id for row in rows}) == len(rows)
    assert all(row.disposition != "UNREVIEWED" for row in rows)


def test_changed_source_is_rejected(tmp_path: Path) -> None:
    """A one-byte input mutation invalidates all previous dispositions.

    @param tmp_path isolated source copy that may be damaged safely

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # The copied input differs by one byte sequence while retaining otherwise valid Markdown.
    changed = tmp_path / "input.md"
    changed.write_bytes(COMMENTING_SOURCE.read_bytes() + b"\n")

    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(ValueError, match="input changed"):
        verify_commenting_source(changed)


def test_missing_policy_is_reported_as_unreviewed() -> None:
    """Removing an owning policy cannot silently discard its claims."""
    # Each retained policy belongs to a section other than the deliberately orphaned first one.
    policies = tuple(policy for policy in COMMENTING_POLICIES if policy.section != 1)

    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(ValueError, match="is unreviewed"):
        build_claim_rows(_candidates(), policies)


def test_duplicate_policy_is_reported_as_multiply_claimed() -> None:
    """A second apparent owner cannot overwrite the first owner's judgment."""
    # Clone the first policy's selector while changing only its review rationale.
    first = COMMENTING_POLICIES[0]
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
    # Mutate one commenting-doctrine claim without recomputing its content-derived identity.
    candidate = next(item for item in _candidates() if item.get("source") == "CD")
    # Keys retain candidate schema fields and values retain content except text; order is unused.
    altered = {**candidate, "text": f"{candidate['text']} altered"}

    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(ValueError, match="altered claim identity"):
        build_claim_rows([altered])


def test_committed_ledger_is_the_deterministic_projection() -> None:
    """The claim evidence on disk is exactly the builder's sorted projection."""
    # Preserve rows element values in deterministic source order.
    rows = build_claim_rows(_candidates())
    expected = render_claim_ledger(rows, COMMENTING_SHA256)

    assert COMMENTING_LEDGER.read_text(encoding="utf-8") == expected
    # Decode the rendered projection to assert its aggregate closed-world counters.
    parsed = json.loads(expected)
    assert parsed["unreviewed_count"] == 0
    assert parsed["multiply_claimed_count"] == 0
