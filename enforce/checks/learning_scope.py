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

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## The two scopes, and the only two. `project` stays here; `discipline` is
## harvested upstream as a proposed change to the corpus.
SCOPES = frozenset({"project", "discipline"})

## Fields without which an entry cannot be acted on or retrieved.
REQUIRED = ("claim", "action", "kind")


class LearningScopeCheck(TextCheck):
    """Reports a learning with no scope, an unknown scope, or nothing to act on."""

    ## Invoked as `python -m checks.learning_scope`.
    name = "learning_scope"
    ## The law/LEARN rule this check decides.
    rules = ("LEARN-004",)
    ## The ledger is JSONL.
    suffixes = (".jsonl",)

    def visit_text(self, text: str, path: Path) -> Iterator[Finding]:
        """Yield findings for each learning that is unscoped or unactionable.

        @param text the ledger's contents
        @param path the file it was read from
        @return one finding per defective entry
        """
        if not ledger.is_ledger(path):
            return

        events, _ = ledger.read(text)
        for event in events:
            if event.kind != "learn":
                continue
            identifier = str(event.payload.get("id", "?"))
            scope = event.payload.get("scope")

            if scope is None:
                yield Finding(
                    "LEARN-004", path, event.line,
                    f"{identifier} states no scope",
                    "Scope it `project` or `discipline`. An unscoped finding that "
                    "the discipline is wrong is invisible to the harvest, so every "
                    "other adopter rediscovers it.",
                )
            elif scope not in SCOPES:
                yield Finding(
                    "LEARN-004", path, event.line,
                    f"{identifier} is scoped {scope!r}, which is not one of "
                    f"{', '.join(sorted(SCOPES))}",
                    "The two scopes decide where the entry goes next; a third "
                    "means it goes nowhere.",
                )

            missing = [f for f in REQUIRED if not event.payload.get(f)]
            if missing:
                yield Finding(
                    "LEARN-004", path, event.line,
                    f"{identifier} is missing {', '.join(missing)}",
                    "A claim without an action is an observation, and retrieval "
                    "that returns observations is retrieval nobody reads twice.",
                )


if __name__ == "__main__":
    raise SystemExit(main(LearningScopeCheck()))
