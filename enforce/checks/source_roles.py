"""Reject production Python that has no declared architectural role.

This decides the narrow proposition in ``ARCH-018``: every Python file beneath
``source_roots`` matches exactly one repository-relative role path. It says
nothing about whether the chosen role is semantically correct; dependency and
effect checks decide observable consequences of that judgment separately.

    python -m checks.source_roles src/
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import Check, Finding, iter_python_files

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


class SourceRolesCheck(Check):
    """Prove that no declared production source path is silently unclassified."""

    ## Mechanism token declared by ARCH-018.
    name = "source_roles"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("ARCH-018",)

    def run(self, _paths: Sequence[Path]) -> list[Finding]:
        """Inspect declaration roots rather than trusting narrower CLI targets.

        A caller may point the aggregate runner at one subdirectory for a quick
        local check. That must not let another production directory disappear
        from the source-role mechanism, so a complete declaration always wins.

        @param _paths path elements in caller order, deliberately ignored for complete roots
        @return finding elements in root then source order, one per absent or unmapped path
        """
        # Resolve production-root path elements in declaration order.
        roots = self.declaration.source_paths()
        # A declaration with no source roots has no production files to classify here.
        if not roots:
            # Return an ordered empty finding sequence.
            return []
        # Accumulate finding elements in declaration-root then file traversal order.
        findings: list[Finding] = []
        # Validate each declared source-root element in declaration order.
        for root in roots:
            # An absent root cannot contribute a falsely clean scan.
            if not root.exists():
                # Append the missing-root diagnostic at the declaration when available.
                findings.append(
                    Finding(
                        rule_id="ARCH-018",
                        path=self.declaration.source or root,
                        line=1,
                        message=f"declared production source root {root} does not exist",
                        remediation=(
                            "Correct source_roots or restore the production tree; an "
                            "absent root cannot count as a clean scan."
                        ),
                        diagnostic_id="ARCH018_SOURCE_ROOT_MISSING",
                    )
                )
                # Advance because an absent root has no Python descendants to classify.
                continue
            # Inspect each Python source-path element in stable traversal order.
            for source in iter_python_files([root]):
                # A path resolved to any declared role has satisfied this narrow proposition.
                if self.declaration.role_of(source) is not None:
                    # Advance without judging whether the selected role is semantically wise.
                    continue
                # Append the unclassified-source finding at the exact Python file.
                findings.append(
                    Finding(
                        rule_id="ARCH-018",
                        path=source,
                        line=1,
                        message="production source matches no declared architectural role",
                        remediation=(
                            "Map this exact path beneath [tool.agent-discipline.roles] "
                            "or move it into the role that owns its policy or effect."
                        ),
                        diagnostic_id="ARCH018_UNMAPPED_SOURCE",
                    )
                )
        # Return every finding in stable declaration and source order.
        return findings


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    from . import main

    # Translate the checker result into the process exit status.
    raise SystemExit(main(SourceRolesCheck()))
