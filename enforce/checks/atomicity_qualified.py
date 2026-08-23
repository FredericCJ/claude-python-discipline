"""An atomicity claim says what it is atomic with respect to.

Enforces `EFCT-008`. The bare word is banned by `meta/GLOSSARY.md`, and the ban
came from a real disagreement: one source document said operations "should
normally be atomic" while another declared that a contract saying `atomic` without
qualification is itself a documentation defect. `CONF-012` resolved it the second
way, and this is that resolution mechanized.

The reason is that the word alone carries no information a caller can act on.
Atomic against a concurrent reader in the same process, against another process,
against a power failure, against a partial network write -- these are four
different guarantees with four different costs, and the word is identical for all
of them. A caller who assumes the strongest one has been told nothing and
believes they have been told everything.

Reads docstrings and comments alike. A claim in a comment beside the code is
exactly as load-bearing as one in the docstring, and rather more likely to be the
one a maintainer trusts.
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

## The banned word in any of its forms.
_ATOMIC = re.compile(r"\batomic(ally|ity)?\b", re.IGNORECASE)

## Qualifications that make the claim mean something. Any of these near the word
## satisfies the rule; the list is the vocabulary the glossary settled on.
_QUALIFIED = re.compile(
    r"(with respect to|w\.r\.t\.|within|against|across|per\b|relative to"
    r"|not atomic|non-atomic|no atomicity|is not|never atomic)",
    re.IGNORECASE,
)

## How far from the word a qualification may sit and still be read as qualifying
## it. One line either side: further than that and a reader will not connect them.
_WINDOW = 1


class AtomicityQualifiedCheck(ModuleCheck):
    """Reports a bare atomicity claim in a docstring or a comment."""

    ## Invoked as `python -m checks.atomicity_qualified`.
    name = "atomicity_qualified"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("EFCT-008",)

    def visit_module(self, _tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield a finding per unqualified use of the word.

        Read from source lines rather than the syntax tree, so a claim in a
        comment is caught as well as one in a docstring.

        @param _tree the module's syntax tree, unused: comments are not in it
        @param path the file it was parsed from
        @param _layer the architectural layer, unused -- the rule binds everywhere
        @return finding elements in source-line order, one per bare claim

        @par Effects
        Reads the source file at ``path`` once so comments absent from the AST remain visible.
        """
        # Read and split one strict UTF-8 source snapshot while retaining line order.
        lines = path.read_text(encoding="utf-8").splitlines()
        # Examine each source-line element in increasing one-based order.
        for number, line in enumerate(lines, start=1):
            # Lines without an atomicity word cannot contain the prohibited bare claim.
            if _ATOMIC.search(line) is None:
                # Advance without building an unnecessary qualification window.
                continue
            # Join the matching line and one neighboring line each side in source order.
            context = "\n".join(
                lines[max(0, number - 1 - _WINDOW): number + _WINDOW]
            )
            # Any accepted nearby qualification gives the claim actionable scope.
            if _QUALIFIED.search(context):
                # Advance because this occurrence states what it is atomic against.
                continue
            # Yield the bare-claim finding at the exact matching source line.
            yield Finding(
                "EFCT-008", path, number,
                "an atomicity claim with nothing to be atomic with respect to",
                "Say against what: a concurrent reader, another process, a power "
                "failure, a partial write. Those are four guarantees at four "
                "costs, and the bare word is identical for all of them.",
            )


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(AtomicityQualifiedCheck()))
