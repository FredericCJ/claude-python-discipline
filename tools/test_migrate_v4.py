"""Behavioral tests for the conservative v3-to-v4 migrator."""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest
from tools import migrate_v4

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from pathlib import Path


def _project(tmp_path: Path, *, declaration: str = 'doc_engine = "doxygen"') -> Path:
    """Create one small v3 source tree and project declaration.

    @param tmp_path scratch repository root
    @param declaration body of the main v3 discipline table
    @return repository root

    @par Effects
    Materializes a representative v3 package tree and its project declaration.
    """
    # Establish every canonical v3 role directory so migration can infer a complete mapping.
    (tmp_path / "src/pkg/domain").mkdir(parents=True)
    # Keep application orchestration distinct from the domain fixture.
    (tmp_path / "src/pkg/app").mkdir()
    # Represent an inbound contract without prescribing an implementation technology.
    (tmp_path / "src/pkg/ports").mkdir()
    # Include one nested adapter so ownership inference crosses a directory boundary.
    (tmp_path / "src/pkg/adapters/http").mkdir(parents=True)
    # Exercise the legacy shell role alongside the other canonical roles.
    (tmp_path / "src/pkg/shell").mkdir()
    # Enumerate the production modules that make each inferred role observable.
    for path in (
        "src/pkg/__init__.py",
        "src/pkg/domain/model.py",
        "src/pkg/app/service.py",
        "src/pkg/ports/client.py",
        "src/pkg/adapters/http/client.py",
        "src/pkg/shell/cli.py",
    ):
        # Materialize each declared module without introducing irrelevant Python behavior.
        (tmp_path / path).write_text("", encoding="utf-8")
    # Preserve unrelated tables around the legacy declaration to test bounded replacement.
    body = dedent(f"""
        [project]
        name = "pkg"
        version = "1.0.0"

        [tool.setuptools.packages.find]
        where = ["src"]

        # declaration marker
        [tool.agent-discipline]
        {declaration}

        [tool.agent-discipline.layers]

        [tool.ruff]
        line-length = 99
    """).lstrip()
    # Complete the fixture only after all source paths are available for discovery.
    (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")
    # Return the repository boundary consumed by plan and apply operations.
    return tmp_path


def _diagnostic_ids(plan: migrate_v4.MigrationPlan) -> set[str]:
    """Collect stable codes from one plan.

    @param plan migration plan
    @return diagnostic ids
    """
    # Project diagnostics to their stable interface so assertions ignore presentation text.
    return {item.diagnostic_id for item in plan.diagnostics}


def test_preview_is_pure_and_exposes_complete_diff(tmp_path: Path) -> None:
    """Default operation reports intended bytes without modifying the project.

    @param tmp_path scratch repository
    """
    # Capture the pristine v3 repository so preview purity can be checked byte-for-byte.
    root = _project(tmp_path)
    # Address the sole declaration file whose bytes the migration may replace.
    project_file = root / "pyproject.toml"
    original = project_file.read_bytes()

    # Build but do not apply the proposed application migration.
    migration = migrate_v4.plan(root, "application")
    # Render the complete proposal for operator review without mutating the fixture.
    report = migrate_v4.preview(migration)

    assert project_file.read_bytes() == original
    assert "--- " in report
    assert "+++ " in report
    assert 'unit = "application"' in report
    assert "MIGRATE-V4-007_ARCHITECTURE_AUTHORING_REQUIRED" in report


def test_apply_preserves_unrelated_project_configuration(tmp_path: Path) -> None:
    """Only the bounded discipline table family changes.

    @param tmp_path scratch repository
    """
    # Seed unrelated project metadata around the discipline declaration under test.
    root = _project(tmp_path)
    migration = migrate_v4.plan(root, "application")

    migrate_v4.apply(migration)

    # Read the applied declaration together with its preserved surrounding configuration.
    result = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert result.startswith('[project]\nname = "pkg"')
    assert "# declaration marker" in result
    assert "[tool.ruff]\nline-length = 99\n" in result
    assert "[tool.agent-discipline.roles]" in result
    assert 'domain = ["src/pkg/domain"]' in result
    assert 'shell = ["src/pkg/__init__.py", "src/pkg/shell"]' in result


def test_apply_is_idempotent(tmp_path: Path) -> None:
    """A second migration sees a complete v4 declaration and changes nothing.

    @param tmp_path scratch repository
    """
    # Produce a completed component migration whose bytes become the idempotency oracle.
    root = _project(tmp_path)
    migrate_v4.apply(migrate_v4.plan(root, "component"))
    once = (root / "pyproject.toml").read_bytes()

    # Re-plan the already-current repository to prove no replacement remains.
    second = migrate_v4.plan(root, "component")
    migrate_v4.apply(second)

    assert not second.changed
    assert not second.blocked
    assert (root / "pyproject.toml").read_bytes() == once


def test_unit_kind_is_never_guessed(tmp_path: Path) -> None:
    """Application versus component intent requires an explicit operator decision.

    @param tmp_path scratch repository
    """
    # Omit unit intent deliberately so the planner must refuse semantic guessing.
    migration = migrate_v4.plan(_project(tmp_path), None)

    assert migration.blocked
    assert "MIGRATE-V4-001_UNIT_REQUIRED" in _diagnostic_ids(migration)
    # Confirm the apply boundary independently enforces the planner's blocking decision.
    with pytest.raises(ValueError, match="blocking diagnostics"):
        migrate_v4.apply(migration)


def test_unmapped_production_source_blocks_apply(tmp_path: Path) -> None:
    """An old unclassified directory cannot disappear during role migration.

    @param tmp_path scratch repository

    @par Effects
    Adds an unclassified production module to the repository fixture.
    """
    # Extend the canonical fixture with source that no legacy alias can classify.
    root = _project(tmp_path)
    (root / "src/pkg/mystery").mkdir()
    (root / "src/pkg/mystery/code.py").write_text("", encoding="utf-8")

    # Ask the planner to account for the deliberately unmapped production path.
    migration = migrate_v4.plan(root, "application")

    assert migration.blocked
    assert "MIGRATE-V4-003_UNMAPPED_SOURCE" in _diagnostic_ids(migration)


def test_legacy_shell_alias_becomes_an_explicit_role_path(tmp_path: Path) -> None:
    """A repository-specific v3 segment survives as an exact v4 mapping.

    @param tmp_path scratch repository

    @par Effects
    Adds a legacy role alias and its corresponding production module.
    """
    # Add a repository-specific CLI segment that is absent from canonical discovery.
    root = _project(tmp_path)
    (root / "src/pkg/cli").mkdir()
    (root / "src/pkg/cli/main.py").write_text("", encoding="utf-8")
    # Amend only the legacy mapping table so the explicit alias drives classification.
    project_file = root / "pyproject.toml"
    original = project_file.read_text(encoding="utf-8")
    project_file.write_text(
        original.replace(
            "[tool.agent-discipline.layers]\n",
            '[tool.agent-discipline.layers]\ncli = "shell"\n',
        ),
        encoding="utf-8",
    )

    # Translate the explicit alias into the component's v4 role declaration.
    migration = migrate_v4.plan(root, "component")

    assert not migration.blocked
    assert '"src/pkg/cli"' in migration.after.decode("utf-8")


def test_unique_arch004_import_becomes_boundary_ownership(tmp_path: Path) -> None:
    """One observed v3 technology owner translates without a semantic guess.

    @param tmp_path scratch repository

    @par Effects
    Adds a technology import and its legacy ARCH-004 contract to the fixture.
    """
    # Place the foreign import under exactly one adapter boundary.
    root = _project(tmp_path)
    (root / "src/pkg/adapters/http/client.py").write_text(
        "import httpx\n",
        encoding="utf-8",
    )
    (root / "importlinter.toml").write_text(
        dedent("""
        [tool.importlinter]
        root_packages = ["pkg"]

        [[tool.importlinter.contracts]]
        name = "ARCH-004 httpx is cornered"
        type = "forbidden"
        source_modules = ["pkg.domain", "pkg.app"]
        forbidden_modules = ["httpx"]
    """).lstrip(),
        encoding="utf-8",
    )

    # Infer ownership from the unique observed adapter rather than contract wording.
    migration = migrate_v4.plan(root, "application")
    # Decode the proposed declaration to inspect its explicit technology ownership.
    rendered = migration.after.decode("utf-8")

    assert not migration.blocked
    assert 'import_name = "httpx"' in rendered
    assert 'owner = "src/pkg/adapters/http"' in rendered
    assert "[tool.agent-discipline.capabilities]" in rendered
    assert "network_io = false" in rendered
    assert 'operational_model = "operational-model.json"' in rendered
    assert 'security_model = "security-model.json"' in rendered
    assert 'adversarial_review = "adversarial-review.json"' in rendered


def test_arch004_import_in_two_boundaries_blocks_migration(tmp_path: Path) -> None:
    """The tool refuses to invent one owner for a genuinely shared technology.

    @param tmp_path scratch repository

    @par Effects
    Adds the same technology import beneath two independent adapter boundaries.
    """
    # Create two plausible owners so repository evidence cannot select one safely.
    root = _project(tmp_path)
    (root / "src/pkg/adapters/backup").mkdir()
    for path in (
        root / "src/pkg/adapters/http/client.py",
        root / "src/pkg/adapters/backup/client.py",
    ):
        # Give each competing boundary identical evidence of technology ownership.
        path.write_text("import httpx\n", encoding="utf-8")
    (root / "importlinter.toml").write_text(
        dedent("""
        [tool.importlinter]
        [[tool.importlinter.contracts]]
        name = "ARCH-004 httpx is cornered"
        type = "forbidden"
        source_modules = ["pkg.domain"]
        forbidden_modules = ["httpx"]
    """).lstrip(),
        encoding="utf-8",
    )

    # Require the planner to surface ambiguity instead of choosing by traversal order.
    migration = migrate_v4.plan(root, "component")

    assert migration.blocked
    assert "MIGRATE-V4-004_AMBIGUOUS_OWNER" in _diagnostic_ids(migration)


def test_stale_arch004_contract_is_visible_but_not_invented(tmp_path: Path) -> None:
    """An absent old dependency gets a warning and no ownership record.

    @param tmp_path scratch repository

    @par Effects
    Adds a legacy ARCH-004 contract for a dependency absent from production code.
    """
    # Supply contract history without the source evidence required for ownership.
    root = _project(tmp_path)
    (root / "importlinter.toml").write_text(
        dedent("""
        [tool.importlinter]
        [[tool.importlinter.contracts]]
        name = "ARCH-004 retired technology"
        type = "forbidden"
        source_modules = ["pkg.domain"]
        forbidden_modules = ["oldclient"]
    """).lstrip(),
        encoding="utf-8",
    )

    # Preserve the stale signal diagnostically while declining to invent an owner.
    migration = migrate_v4.plan(root, "application")

    assert not migration.blocked
    assert "MIGRATE-V4-005_STALE_IMPORT_CONTRACT" in _diagnostic_ids(migration)
    assert 'import_name = "oldclient"' not in migration.after.decode("utf-8")


def test_crlf_bytes_outside_the_declaration_survive(tmp_path: Path) -> None:
    """Migration does not normalize a project's line-ending convention.

    @param tmp_path scratch repository

    @par Effects
    Rewrites the fixture declaration with CRLF line endings before migration.
    """
    # Start from the standard fixture so only newline representation differs.
    root = _project(tmp_path)
    # Convert the complete declaration to CRLF before asking the migrator to edit it.
    project_file = root / "pyproject.toml"
    normalized = project_file.read_bytes().replace(b"\r\n", b"\n")
    project_file.write_bytes(normalized.replace(b"\n", b"\r\n"))

    migrate_v4.apply(migrate_v4.plan(root, "application"))
    # Retain raw output bytes so newline preservation is not hidden by text decoding.
    result = project_file.read_bytes()

    assert b"[project]\r\nname" in result
    assert b"[tool.ruff]\r\nline-length" in result
    assert b"\n" not in result.replace(b"\r\n", b"")


def test_source_root_cannot_escape_to_a_parent_checkout(tmp_path: Path) -> None:
    """Build metadata cannot authorize the migrator to inspect a sibling tree.

    @param tmp_path scratch repository

    @par Effects
    Replaces the declared package root with a parent-relative path.
    """
    # Prepare a valid local tree before introducing the escaping source-root declaration.
    root = _project(tmp_path)
    # Target the build metadata that controls source discovery.
    project_file = root / "pyproject.toml"
    # Preserve all unrelated project bytes while replacing the source-root value.
    text = project_file.read_text(encoding="utf-8")
    project_file.write_text(
        text.replace('where = ["src"]', 'where = ["../peer"]'),
        encoding="utf-8",
    )

    # Plan against the hostile declaration without traversing the sibling checkout.
    migration = migrate_v4.plan(root, "component")

    assert migration.blocked
    assert "MIGRATE-V4-008_EXTERNAL_PATH" in _diagnostic_ids(migration)


def test_partial_v4_fields_are_not_discarded(tmp_path: Path) -> None:
    """An interrupted prior migration requires review instead of destructive rewrite.

    @param tmp_path scratch repository
    """
    # Seed a declaration mixing legacy structure with one already-migrated field.
    root = _project(tmp_path, declaration='doc_engine = "doxygen"\nunit = "component"')

    # Detect the interrupted state before any bounded replacement is proposed.
    migration = migrate_v4.plan(root, "component")

    assert migration.blocked
    assert "MIGRATE-V4-006_LEGACY_DECLARATION" in _diagnostic_ids(migration)


def test_existing_complete_v4_declaration_is_a_noop(tmp_path: Path) -> None:
    """The migrator never reformats or second-guesses an already migrated project.

    @param tmp_path scratch repository
    """
    # Establish a complete current declaration through the supported migration path.
    root = _project(tmp_path)
    migrate_v4.apply(migrate_v4.plan(root, "application"))
    # Capture the current bytes that a no-op plan must leave untouched.
    project_file = root / "pyproject.toml"
    before = project_file.read_bytes()

    # Permit omitted unit intent only because the existing v4 declaration is authoritative.
    migration = migrate_v4.plan(root, None)

    assert not migration.changed
    assert not migration.diagnostics
    assert project_file.read_bytes() == before


def test_cli_refuses_apply_when_unit_is_missing(tmp_path: Path) -> None:
    """The stable diagnostic reaches operators through the command entry point.

    @param tmp_path scratch repository
    """
    # Provide a legacy repository while deliberately withholding CLI unit intent.
    root = _project(tmp_path)

    # Capture the command status that automation receives for the blocked operation.
    status = migrate_v4.main(["--root", str(root), "--apply"])

    assert status == migrate_v4.EXIT_BLOCKED
    assert b'unit = "application"' not in (root / "pyproject.toml").read_bytes()
