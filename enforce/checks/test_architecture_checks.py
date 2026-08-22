"""Discrimination tests for v4's one-unit architecture mechanisms."""

from __future__ import annotations

from typing import TYPE_CHECKING

from checks import project
from checks.source_roles import SourceRolesCheck

if TYPE_CHECKING:
    from pathlib import Path


def declared_tree(tmp_path: Path) -> tuple[project.Declaration, Path]:
    """Create a smallest complete role-mapped application fixture.

    @param tmp_path fixture repository
    @return parsed declaration and its source root
    """
    project_file = tmp_path / "pyproject.toml"
    project_file.write_text(
        """[tool.agent-discipline]
unit = "application"
source_roots = ["src"]

[tool.agent-discipline.roles]
domain = ["src/pkg/domain"]
shell = ["src/pkg/__init__.py", "src/pkg/shell"]
""",
        encoding="utf-8",
    )
    source = tmp_path / "src/pkg/domain"
    source.mkdir(parents=True)
    (source / "model.py").write_text('"""Policy."""\n', encoding="utf-8")
    package = tmp_path / "src/pkg/__init__.py"
    package.parent.mkdir(parents=True, exist_ok=True)
    package.write_text('"""Public package."""\n', encoding="utf-8")
    return project.parse(project_file), tmp_path / "src"


def test_source_roles_accepts_a_complete_partition(tmp_path: Path) -> None:
    """The positive reference proves explicit roles do not create findings.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    check = SourceRolesCheck()
    check.declaration = declaration
    assert check.run([source]) == []


def test_source_roles_rejects_an_unmapped_source_directory(tmp_path: Path) -> None:
    """A newly seeded directory cannot disappear from role-scoped checks.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    hidden = source / "pkg/services/orphan.py"
    hidden.parent.mkdir(parents=True)
    hidden.write_text('"""Unowned policy."""\n', encoding="utf-8")
    check = SourceRolesCheck()
    check.declaration = declaration
    findings = check.run([source / "pkg/domain"])
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH018_UNMAPPED_SOURCE"
    ]


def test_source_roles_rejects_an_absent_declared_root(tmp_path: Path) -> None:
    """A typo in source_roots cannot turn an empty walk into conformance.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    source.rename(tmp_path / "moved")
    check = SourceRolesCheck()
    check.declaration = declaration
    findings = check.run([tmp_path])
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH018_SOURCE_ROOT_MISSING"
    ]
