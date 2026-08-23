"""A learning is scoped by who it is about, and says what to do.

Enforces `LEARN-004`. Two scopes exist and the difference decides where the
entry goes next: a `project` learning is about this repository and stays here; a
`discipline` learning says the discipline itself is wrong, ambiguous or missing,
and `harvest.py` exports it upstream as a proposal.

An unscoped entry is not merely untidy. It is invisible to the harvest, so a
finding that the discipline is wrong sits in one repository's notes forever while
every other adopter rediscovers it. That is the failure the scope field exists
to prevent, and it is why this check also requires the two fields that make an
entry actionable: a claim without an action is an observation, and retrieval
returning observations is retrieval nobody reads twice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import Finding, TextCheck, ledger, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Unordered learning-scope set whose each element decides local retention or upstream
## harvesting: ``project`` stays here and ``discipline`` proposes a corpus change.
SCOPES = frozenset({"project", "discipline"})

## Required payload-field elements in stable diagnostic order for actionable retrieval.
REQUIRED = ("claim", "action", "kind")


class LearningScopeCheck(TextCheck):
    """Reports a learning with no scope, an unknown scope, or nothing to act on."""

    ## Invoked as `python -m checks.learning_scope`.
    name = "learning_scope"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("LEARN-004",)
    ## File-suffix elements in deterministic matching order for JSONL ledgers.
    suffixes = (".jsonl",)

    def visit_text(self, text: str, path: Path) -> Iterator[Finding]:
        """Yield findings for each learning that is unscoped or unactionable.

        @param text the ledger's contents
        @param path the file it was read from
        @return finding elements in event then predicate order, one per defective property
        """
        # Ignore JSONL files that do not declare the learning-ledger schema.
        if not ledger.is_ledger(path):
            # Stop iteration without presenting unrelated JSONL as conforming ledger data.
            return

        # Decode event elements in append order; parsing diagnostics are owned by ``ledger``.
        events, _ = ledger.read(text)
        # Inspect each event-record element in append order.
        for event in events:
            # Only original learn events own scope and actionable payload fields.
            if event.kind != "learn":
                # Advance without applying declaration obligations to transition events.
                continue
            # Normalize the learning identity for standalone diagnostics.
            identifier = str(event.payload.get("id", "?"))
            # Select the authored scope value without coercing absence.
            scope = event.payload.get("scope")

            # Missing scope prevents routing the learning to project or discipline ownership.
            if scope is None:
                # Yield the missing-scope finding at the exact learn-event line.
                yield Finding(
                    "LEARN-004", path, event.line,
                    f"{identifier} states no scope",
                    "Scope it `project` or `discipline`. An unscoped finding that "
                    "the discipline is wrong is invisible to the harvest, so every "
                    "other adopter rediscovers it.",
                )
            # A third scope value belongs to neither supported lifecycle.
            elif scope not in SCOPES:
                # Yield the unknown-scope finding with accepted values sorted for stability.
                yield Finding(
                    "LEARN-004", path, event.line,
                    f"{identifier} is scoped {scope!r}, which is not one of "
                    f"{', '.join(sorted(SCOPES))}",
                    "The two scopes decide where the entry goes next; a third "
                    "means it goes nowhere.",
                )

            # Preserve required-field order while collecting each absent or empty payload key.
            missing = [f for f in REQUIRED if not event.payload.get(f)]
            # Any missing actionable field makes retrieval return an unusable observation.
            if missing:
                # Yield one aggregate payload finding in stable required-field order.
                yield Finding(
                    "LEARN-004", path, event.line,
                    f"{identifier} is missing {', '.join(missing)}",
                    "A claim without an action is an observation, and retrieval "
                    "that returns observations is retrieval nobody reads twice.",
                )


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(LearningScopeCheck()))
