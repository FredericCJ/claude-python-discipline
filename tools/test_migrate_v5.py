"""Behavioral tests for the conservative v4-to-v5 documentation migrator."""

from __future__ import annotations

import json
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest
from tools import migrate_v5

if TYPE_CHECKING:
    from pathlib import Path


def _project(tmp_path: Path, *, engine: str = "none", unit: str = "application") -> Path:
    """Create a complete synthetic v4 project with conventional owned scopes.

    @param tmp_path scratch repository root
    @param engine former structured-documentation selection
    @param unit application or single-component repository shape
    @return repository root
    """
    (tmp_path / "src/pkg").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "src/pkg/__init__.py").write_text('"""Package."""\n', encoding="utf-8")
    (tmp_path / "tests/test_pkg.py").write_text('"""Tests."""\n', encoding="utf-8")
    (tmp_path / "tools/build.py").write_text('"""Build."""\n', encoding="utf-8")
    project = dedent(f"""
        [project]
        name = "pkg"
        version = "1.0.0"

        [tool.pytest.ini_options]
        testpaths = ["tests"]

        # v4 declaration marker
        [tool.agent-discipline]
        unit = "{unit}"
        source_roots = ["src"]
        architecture = "architecture.json"
        contract_conformance = "contract-conformance.json"
        operational_model = "operational-model.json"
        security_model = "security-model.json"
        adversarial_review = "adversarial-review.json"
        doc_engine = "{engine}"

        [tool.agent-discipline.capabilities]
        public_api = false

        [tool.agent-discipline.roles]
        domain = ["src/pkg"]

        [tool.ruff]
        line-length = 99
    """).lstrip()
    (tmp_path / "pyproject.toml").write_text(project, encoding="utf-8")
    return tmp_path


def _diagnostics(migration: migrate_v5.MigrationPlan) -> set[str]:
    """Collect stable diagnostic identifiers from one plan.

    @param migration migration plan
    @return distinct diagnostic identifiers
    """
    return {item.diagnostic_id for item in migration.diagnostics}


@pytest.mark.parametrize("engine", ["none", "sphinx"])
@pytest.mark.parametrize("unit", ["application", "component"])
def test_legacy_engine_migrates_both_repository_shapes(
    tmp_path: Path,
    engine: str,
    unit: str,
) -> None:
    """One package migrates application and single-component v4 declarations.

    @param tmp_path scratch repository root
    @param engine former v4 engine
    @param unit supported one-repository shape
    """
    root = _project(tmp_path, engine=engine, unit=unit)
    migration = migrate_v5.plan(root)

    assert not migration.blocked
    assert "MIGRATE-V5-003_AUTHORING_REQUIRED" in _diagnostics(migration)
    migrate_v5.apply(migration)

    project = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'doc_engine = "doxygen"' in project
    assert 'documentation_model = "documentation-model.json"' in project
    assert '[tool.agent-discipline-gate]\ndoxyfile = "Doxyfile"' in project
    model = json.loads((root / "documentation-model.json").read_text(encoding="utf-8"))
    assert [(item["path"], item["kind"]) for item in model["scopes"]] == [
        ("src", "production"),
        ("tests", "tests"),
        ("tools", "maintenance"),
    ]
    doxyfile = (root / "Doxyfile").read_text(encoding="utf-8")
    assert 'PROJECT_NAME           = "pkg"' in doxyfile
    assert 'INPUT                  = "src"' in doxyfile


def test_preview_is_pure_and_shows_every_created_artifact(tmp_path: Path) -> None:
    """Default operation reports declaration, model, and Doxyfile without writes.

    @param tmp_path scratch repository root
    """
    root = _project(tmp_path)
    before = (root / "pyproject.toml").read_bytes()

    report = migrate_v5.preview(migrate_v5.plan(root))

    assert (root / "pyproject.toml").read_bytes() == before
    assert not (root / "documentation-model.json").exists()
    assert not (root / "Doxyfile").exists()
    assert "documentation-model.json" in report
    assert "Doxyfile" in report
    assert "MIGRATE-V5-003_AUTHORING_REQUIRED" in report


def test_apply_preserves_unrelated_tables_and_is_idempotent(tmp_path: Path) -> None:
    """The bounded edit retains project bytes and a second plan is a no-op.

    @param tmp_path scratch repository root
    """
    root = _project(tmp_path, engine="doxygen")
    migrate_v5.apply(migrate_v5.plan(root))
    once = (root / "pyproject.toml").read_bytes()

    second = migrate_v5.plan(root)
    migrate_v5.apply(second)

    assert not second.changed
    assert not second.blocked
    assert (root / "pyproject.toml").read_bytes() == once
    assert b"# v4 declaration marker" in once
    assert "[tool.ruff]\nline-length = 99\n" in once.decode().replace("\r\n", "\n")


def test_existing_artifacts_are_never_overwritten(tmp_path: Path) -> None:
    """Project-authored model and Doxyfile bytes remain project-owned.

    @param tmp_path scratch repository root
    """
    root = _project(tmp_path)
    (root / "documentation-model.json").write_text("project model\n", encoding="utf-8")
    (root / "Doxyfile").write_text("project doxyfile\n", encoding="utf-8")

    migration = migrate_v5.plan(root)
    migrate_v5.apply(migration)

    assert (root / "documentation-model.json").read_text(encoding="utf-8") == "project model\n"
    assert (root / "Doxyfile").read_text(encoding="utf-8") == "project doxyfile\n"
    assert "MIGRATE-V5-005_DOXYFILE_REVIEW" in _diagnostics(migration)


def test_unclassified_python_requires_scope_review(tmp_path: Path) -> None:
    """A non-conventional Python subtree stays visible instead of being guessed.

    @param tmp_path scratch repository root
    """
    root = _project(tmp_path)
    (root / "scripts").mkdir()
    (root / "scripts/deploy.py").write_text('"""Deployment."""\n', encoding="utf-8")

    migration = migrate_v5.plan(root)

    assert "MIGRATE-V5-004_SCOPE_REVIEW" in _diagnostics(migration)
    assert "scripts/deploy.py" in migrate_v5.preview(migration)


def test_incomplete_v4_declaration_blocks_without_writes(tmp_path: Path) -> None:
    """A v3 or partial declaration cannot be silently promoted to v5.

    @param tmp_path scratch repository root
    """
    root = _project(tmp_path)
    project = root / "pyproject.toml"
    project.write_text(
        project.read_text(encoding="utf-8").replace(
            'architecture = "architecture.json"\n', ""
        ),
        encoding="utf-8",
    )
    migration = migrate_v5.plan(root)

    assert migration.blocked
    assert "MIGRATE-V5-001_NOT_V4" in _diagnostics(migration)
    with pytest.raises(migrate_v5.MigrationError, match="blocking diagnostics"):
        migrate_v5.apply(migration)
    assert not (root / "documentation-model.json").exists()


def test_artifact_path_cannot_escape_to_a_sibling(tmp_path: Path) -> None:
    """A declaration cannot authorize the migration to write outside its root.

    @param tmp_path scratch repository root
    """
    root = _project(tmp_path)
    project = root / "pyproject.toml"
    project.write_text(
        project.read_text(encoding="utf-8").replace(
            'doc_engine = "none"',
            'doc_engine = "none"\ndocumentation_model = "../peer/model.json"',
        ),
        encoding="utf-8",
    )

    migration = migrate_v5.plan(root)

    assert migration.blocked
    assert "MIGRATE-V5-002_UNSAFE_PATH" in _diagnostics(migration)


def test_apply_refuses_a_project_changed_after_preview(tmp_path: Path) -> None:
    """A stale plan cannot replace concurrent project edits.

    @param tmp_path scratch repository root
    """
    root = _project(tmp_path)
    migration = migrate_v5.plan(root)
    project = root / "pyproject.toml"
    project.write_text(project.read_text(encoding="utf-8") + "# concurrent\n", encoding="utf-8")

    with pytest.raises(migrate_v5.MigrationError, match="changed after"):
        migrate_v5.apply(migration)
