"""Discrimination tests for v4's one-unit architecture mechanisms."""

from __future__ import annotations

from typing import TYPE_CHECKING

from checks import project
from checks.dependency_boundaries import DependencyBoundariesCheck
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
adapter_boundaries = [
    "src/pkg/adapters/clock",
    "src/pkg/adapters/files",
    "src/pkg/adapters/http",
]

[tool.agent-discipline.roles]
domain = ["src/pkg/domain"]
application = ["src/pkg/app"]
ports = ["src/pkg/ports"]
adapters = ["src/pkg/adapters"]
shell = ["src/pkg/__init__.py", "src/pkg/shell"]

[[tool.agent-discipline.foreign_dependencies]]
import_name = "time"
owner = "src/pkg/adapters/clock"
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


def write_python(root: Path, relative: str, body: str = '"""Fixture."""\n') -> Path:
    """Write one source module into the architecture fixture.

    @param root fixture source root
    @param relative path beneath the source root
    @param body Python source text
    @return written file
    """
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


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


def test_local_shell_may_wire_the_real_adapter(tmp_path: Path) -> None:
    """Intentional transitive technology reach does not make shell a second owner.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    write_python(source, "pkg/adapters/clock/__init__.py")
    write_python(source, "pkg/adapters/clock/real.py", "import time\n")
    write_python(source, "pkg/shell/__init__.py")
    write_python(
        source,
        "pkg/shell/composition.py",
        "from pkg.adapters.clock.real import Clock\n",
    )
    check = DependencyBoundariesCheck()
    check.declaration = declaration
    assert check.run([source]) == []


def test_application_to_concrete_adapter_has_its_own_diagnostic(
    tmp_path: Path,
) -> None:
    """Orchestration naming a concrete adapter is not mislabeled ownership.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    write_python(source, "pkg/adapters/http/__init__.py")
    write_python(source, "pkg/app/service.py", "import pkg.adapters.http\n")
    check = DependencyBoundariesCheck()
    check.declaration = declaration
    findings = check.run([source])
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH019_APPLICATION_TO_ADAPTER"
    ]


def test_second_adapter_importing_owned_technology_has_distinct_diagnostic(
    tmp_path: Path,
) -> None:
    """Direct technology ownership is independent from dependency direction.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    write_python(source, "pkg/adapters/files/__init__.py")
    write_python(source, "pkg/adapters/files/real.py", "import time\n")
    check = DependencyBoundariesCheck()
    check.declaration = declaration
    findings = check.run([source])
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH020_FOREIGN_OWNER_BREACH"
    ]


def test_domain_importing_shell_is_an_outward_policy_edge(tmp_path: Path) -> None:
    """The generic direction diagnostic remains separate from adapter selection.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    write_python(source, "pkg/shell/runtime.py")
    write_python(source, "pkg/domain/model.py", "import pkg.shell.runtime\n")
    check = DependencyBoundariesCheck()
    check.declaration = declaration
    findings = check.run([source])
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH001_OUTWARD_POLICY_EDGE"
    ]


def test_one_adapter_boundary_cannot_import_another(tmp_path: Path) -> None:
    """Adapter independence is evaluated at the boundary package, not whole role.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    write_python(source, "pkg/adapters/clock/__init__.py")
    write_python(source, "pkg/adapters/files/__init__.py")
    write_python(
        source,
        "pkg/adapters/files/real.py",
        "import pkg.adapters.clock\n",
    )
    check = DependencyBoundariesCheck()
    check.declaration = declaration
    findings = check.run([source])
    assert [finding.diagnostic_id for finding in findings] == [
        "ARCH003_ADAPTER_TO_ADAPTER"
    ]
