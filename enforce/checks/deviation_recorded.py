"""Every suppression says what it gives up and why.

Enforces `FLOW-008` (a deviation from an advisory rule is recorded in the change)
and `FLOW-012` (report what happened, including what did not).

A suppression comment is the smallest possible deviation record, and the one
place a deviation is guaranteed to be visible at the moment it matters. `# noqa`
with nothing after it says a rule was set aside; it does not say by whom, for
what, or under what condition it could be removed. The next reader has three
choices -- trust it, investigate it, or delete it and find out -- and all three
are worse than a sentence.

This repository already made the argument for itself: every relaxation in
`enforce/templates/pyproject.toml` names why it applies, and an unjustified
ignore is called a defect there in as many words. This is that convention,
mechanized.

**What this decides and what it does not.** It decides that a suppression carries
prose. It cannot decide that the prose is *true*, which is `DOC-013`'s problem
and a reviewer's.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    import ast
    from collections.abc import Iterator
    from pathlib import Path

## A suppression comment in any of the forms this toolchain admits, with whatever
## follows it captured so the reason can be weighed.
_SUPPRESSION = re.compile(
    r"#\s*(?P<kind>noqa|ruff:\s*ignore|type:\s*ignore|pragma:\s*no\s*cover|mypy:\s*disable)"
    r"(?P<codes>\[[^\]]*\]|:[^\s#]*)?"
    r"(?P<reason>.*)$",
    re.IGNORECASE,
)

## The shortest run of prose that can carry a reason. Below this the text is a
## code, a stray dash, or an emoticon.
MIN_REASON = 8


class DeviationRecordedCheck(ModuleCheck):
    """Reports a suppression comment that states no reason."""

    ## Invoked as `python -m checks.deviation_recorded`.
    name = "deviation_recorded"
    ## Rule-id elements in deterministic reporting order decided by this check.
    ## Narrowed to what this check can actually REPORT. FLOW-012
    ## were named here and never emitted, so they counted as `mechanized` while
    ## being decided by nothing -- and this module's own docstring said so in
    ## prose. `V080` rises as a result, which is the true number.
    rules = ("FLOW-008",)

    def visit_module(self, _tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield a finding for each unexplained suppression in the file.

        Read from the source text rather than the syntax tree, because comments
        never reach an AST -- which is also why they are free under the
        documentation gate's behaviour oracle.

        @param _tree the module's syntax tree, unused: comments are not in it
        @param path the file it was parsed from
        @param _layer the architectural layer, unused -- the rule binds everywhere
        @return finding elements in source-line order, one per bare suppression

        @par Effects
        Reads the source file at ``path`` once because suppression comments are absent from ASTs.
        """
        # Examine each decoded source-line element in increasing one-based order.
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(),
                                      start=1):
            # Search the current line for one admitted suppression-comment form.
            found = _SUPPRESSION.search(line)
            # A line without a suppression has no deviation-record obligation.
            if found is None:
                # Advance to the next source line.
                continue
            # Normalize surrounding punctuation away from the authored reason prose.
            reason = found.group("reason").strip(" -:#")
            # Sufficient prose meets the deliberately shallow mechanical predicate.
            if len(reason) >= MIN_REASON:
                # Advance without claiming the reason is semantically true.
                continue
            # Yield the bare-suppression finding at its exact source line.
            yield Finding(
                "FLOW-008", path, number,
                f"`{found.group('kind').strip()}` suppression states no reason",
                "Say what it gives up and why it is safe here, after a dash. An "
                "unexplained suppression leaves the next reader to trust it, "
                "investigate it, or delete it and find out.",
            )


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(DeviationRecordedCheck()))
