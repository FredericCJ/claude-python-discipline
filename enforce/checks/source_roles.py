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

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


class SourceRolesCheck(Check):
    """Prove that no declared production source path is silently unclassified."""

    name = "source_roles"
    rules = ("ARCH-018",)

    def run(self, _paths: Sequence[Path]) -> list[Finding]:
        """Inspect declaration roots rather than trusting narrower CLI targets.

        A caller may point the aggregate runner at one subdirectory for a quick
        local check. That must not let another production directory disappear
        from the source-role mechanism, so a complete declaration always wins.

        @param _paths ignored caller selection; declared roots are deliberately complete
        @return one finding per absent root or unmapped Python file
        """
        roots = self.declaration.source_paths()
        if not roots:
            return []
        findings: list[Finding] = []
        for root in roots:
            if not root.exists():
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
                continue
            for source in iter_python_files([root]):
                if self.declaration.role_of(source) is not None:
                    continue
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
        return findings


if __name__ == "__main__":
    from . import main

    raise SystemExit(main(SourceRolesCheck()))
