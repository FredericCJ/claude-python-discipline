"""Refer to the tier, never to the model filling it.

Enforces `ALLOC-001`. A tier is a role; the model occupying it is procurement,
and procurement changes. A document naming a model is a document that is wrong
the next time one is retired, and the reasoning inside it -- which was about
capability -- becomes impossible to re-evaluate because the capability was never
written down.

**Two exemptions, both narrow and both necessary.**

A harness configuration field is a *binding*, not reasoning: something has to say
which model fills a tier, or nothing runs. It is exempt where it appears as a
configuration key, so it is made in one place and can be changed in one place.

A file that declares itself the tier-to-model mapping is exempt entirely. That is
the one document whose subject *is* the binding, and `OPEN-006` -- still open --
is precisely the decision it stands in for. Forbidding the mapping to exist would
not remove the coupling; it would scatter it.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from . import Finding, TextCheck, main

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Model names and family names, as they are actually written. Matched on whole
## words so `opusculum` and a sonnet in prose are not model references.
_MODEL = re.compile(
    r"\b(claude-[\w.-]+|gpt-[\w.-]+|o[1-9]-\w+|gemini[\w.-]*|llama-?[\w.]*"
    r"|mistral[\w.-]*|opus|sonnet|haiku)\b",
    re.IGNORECASE,
)

## A configuration key binding a tier to a model. Exempt: something has to make
## the binding, and one declared place is the whole point.
_CONFIG_KEY = re.compile(r"^\s*(model|model_name|engine)\s*[:=]", re.IGNORECASE)

## A file declaring itself the tier-to-model mapping is exempt entirely; it is the
## document whose subject is the binding.
_MAPPING_DECLARATION = re.compile(r"tier[\s-]*to[\s-]*model", re.IGNORECASE)


class NoModelNamesCheck(TextCheck):
    """Reports a model named in prose where a capability tier belongs."""

    ## Invoked as `python -m checks.no_model_names`.
    name = "no_model_names"
    ## The ops/ALLOC rule this check decides.
    rules = ("ALLOC-001",)
    ## Project documents and dispatch records are markdown.
    suffixes = (".md",)

    def visit_text(self, text: str, path: Path) -> Iterator[Finding]:
        """Yield a finding per model named outside a binding.

        @param text the file's contents
        @param path the file it was read from
        @return one finding per offending line
        """
        if _MAPPING_DECLARATION.search(text):
            return

        for number, line in enumerate(text.splitlines(), start=1):
            if _CONFIG_KEY.match(line):
                continue
            found = _MODEL.search(line)
            if found is None:
                continue
            yield Finding(
                "ALLOC-001", path, number,
                f"names the model {found.group(0)!r} where a tier belongs",
                "Refer to the capability tier -- T0, T1, T2. A tier is a role and "
                "survives procurement; a model name is wrong the next time one is "
                "retired, and takes the reasoning with it.",
            )


if __name__ == "__main__":
    raise SystemExit(main(NoModelNamesCheck()))
