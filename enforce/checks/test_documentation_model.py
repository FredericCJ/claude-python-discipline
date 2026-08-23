"""Executable contract for the strict project-owned documentation model."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import pytest

from checks import project
from checks.documentation_model import (
    DocumentationModelCheck,
    DocumentationModelError,
    Ownership,
    governed_paths,
    parse,
)

# Import path typing only while static analyzers evaluate fixture contracts.
if TYPE_CHECKING:
    from pathlib import Path


def _declaration(
    tmp_path: Path, unit: project.UnitKind = project.UnitKind.APPLICATION
) -> project.Declaration:
    """Build the bounded declaration needed to relate model scopes to source roots.

    @param tmp_path fixture repository
    @param unit application or independently developed component
    @return declaration pointing at the fixture model
    """
    # Construct the selected unit with one bounded source root and model path.
    return project.Declaration(
        unit=unit,
        source_roots=(PurePosixPath("src"),),
        documentation_model=PurePosixPath("documentation-model.json"),
        doc_engine="doxygen",
        doc_engine_declared=True,
        source=(tmp_path / "pyproject.toml").resolve(),
    )


def _payload() -> dict[str, object]:
    """Return one complete model with every schema family represented.

    @return field-name keys mapped to JSON values in stable fixture-review order
    """
    # Return a fresh complete mapping so each negative test can mutate one field safely.
    return {
        "schema_version": 1,
        "engine": "doxygen",
        "scopes": [
            {"path": "src", "kind": "production", "ownership": "governed"},
            {"path": "tests", "kind": "tests", "ownership": "governed"},
            {
                "path": "src/pkg/generated",
                "kind": "production",
                "ownership": "generated",
            },
            {
                "path": "src/pkg/vendor",
                "kind": "production",
                "ownership": "foreign",
            },
        ],
        "controlled_abbreviations": [
            {"token": "api", "meaning": "application programming interface", "scopes": ["src"]}
        ],
        "identifier_grammars": [
            {
                "scope": "src/pkg/domain",
                "pattern": "^(?P<concept>[a-z]+)_(?P<role>[a-z]+)$",
                "dimensions": ["concept", "role"],
                "exclusions": ["__all__"],
            }
        ],
        "generated_names": {
            "markers": ["generated"],
            "mappings": {"generated_wire_record": "record"},
        },
        "semantic_properties": [
            {
                "identifier_pattern": "*_ms",
                "property": "unit",
                "value": "milliseconds",
                "scopes": ["src"],
            }
        ],
    }


def _write(tmp_path: Path, payload: dict[str, object]) -> Path:
    """Write one model as deterministic JSON.

    @param tmp_path fixture repository
    @param payload field-name keys mapped to JSON values; insertion order is
        preserved in the fixture text but is not semantically significant
    @return written model path

    @par Effects
    Writes or replaces one documentation-model JSON file in the isolated repository.
    """
    # Resolve the canonical model location in the isolated repository.
    path = tmp_path / "documentation-model.json"
    # Serialize the supplied JSON-compatible mapping before returning its path.
    path.write_text(json.dumps(payload), encoding="utf-8")
    # Expose the written subject to parser-focused tests.
    return path


@pytest.mark.parametrize("unit", list(project.UnitKind))
def test_application_and_component_models_round_trip(
    tmp_path: Path, unit: project.UnitKind
) -> None:
    """Both governed repository shapes use the identical strict schema.

    @param tmp_path fixture repository
    @param unit supported repository shape
    """
    # Write and parse a fresh complete model for the parametrized repository shape.
    model = parse(_write(tmp_path, _payload()), _declaration(tmp_path, unit))

    # Require representative values from every schema family to survive round-trip.
    assert model.engine == "doxygen"
    assert model.schema_version == 1
    assert model.generated_names.mappings["generated_wire_record"] == "record"
    assert model.semantic_properties[0].value == "milliseconds"


def test_unknown_fields_fail_instead_of_becoming_waivers(tmp_path: Path) -> None:
    """A misspelled field cannot be silently ignored.

    @param tmp_path fixture repository
    """
    # Rename one field in a fresh payload to simulate a plausible schema typo.
    payload = _payload()
    payload["controlled_abbrevivations"] = payload.pop("controlled_abbreviations")

    # Require the strict parser to reject rather than ignore the unknown field.
    with pytest.raises(DocumentationModelError, match="DOCMODEL-003"):
        parse(_write(tmp_path, payload), _declaration(tmp_path))


@pytest.mark.parametrize("unsafe", ["../peer", "/absolute", "C:/peer", "."])
def test_scope_paths_cannot_escape_or_claim_the_repository(tmp_path: Path, unsafe: str) -> None:
    """Every ownership decision remains inside a specific local path.

    @param tmp_path fixture repository
    @param unsafe invalid scope spelling
    """
    # Replace the first scope path in a fresh model with the parametrized unsafe value.
    payload = _payload()
    scopes = payload["scopes"]
    assert isinstance(scopes, list)
    scopes[0] = {"path": unsafe, "kind": "production", "ownership": "governed"}

    # Require every escape or whole-repository claim to fail with the path diagnostic.
    with pytest.raises(DocumentationModelError, match="DOCMODEL-004"):
        parse(_write(tmp_path, payload), _declaration(tmp_path))


def test_overlapping_abbreviation_meanings_fail(tmp_path: Path) -> None:
    """One token cannot mean two things in intersecting scopes.

    @param tmp_path fixture repository
    """
    # Append a conflicting meaning to the controlled-abbreviation record elements.
    payload = _payload()
    abbreviations = payload["controlled_abbreviations"]
    assert isinstance(abbreviations, list)
    abbreviations.append({
        "token": "api",
        "meaning": "adapter protocol input",
        "scopes": ["src/pkg"],
    })

    # Require intersecting scopes for one token to preserve exactly one meaning.
    with pytest.raises(DocumentationModelError, match="DOCMODEL-008"):
        parse(_write(tmp_path, payload), _declaration(tmp_path))


def test_generated_and_foreign_subtrees_are_excluded(tmp_path: Path) -> None:
    """Most-specific foreign/generated ownership overrides a governed parent.

    @param tmp_path fixture repository
    """
    # Parse the complete ownership hierarchy before probing most-specific matches.
    model = parse(_write(tmp_path, _payload()), _declaration(tmp_path))

    # Require governed, generated, and foreign subjects to resolve independently.
    assert model.ownership_of(tmp_path / "src/pkg/domain/model.py", tmp_path) is Ownership.GOVERNED
    assert (
        model.ownership_of(tmp_path / "src/pkg/generated/model.py", tmp_path) is Ownership.GENERATED
    )
    assert model.ownership_of(tmp_path / "src/pkg/vendor/model.py", tmp_path) is Ownership.FOREIGN


def test_the_check_reports_the_exact_schema_diagnostic(tmp_path: Path) -> None:
    """Model refusal remains actionable through ordinary check aggregation.

    @param tmp_path fixture repository
    """
    # Replace the sole supported engine with a legacy alternative in a fresh payload.
    payload = _payload()
    payload["engine"] = "sphinx"
    _write(tmp_path, payload)
    # Configure the aggregate check against the invalid fixture declaration.
    check = DocumentationModelCheck()
    check.declaration = _declaration(tmp_path)

    # Execute ordinary check aggregation rather than calling the parser directly.
    findings = check.run([])

    # Require one actionable rule and model diagnostic pair.
    assert len(findings) == 1
    assert findings[0].rule_id == "DOC-022"
    assert findings[0].diagnostic_id == "DOCMODEL-001"


def test_explicit_inventory_target_intersects_governed_scopes(tmp_path: Path) -> None:
    """A focused check does not unexpectedly inventory every model scope.

    @param tmp_path fixture repository

    @par Effects
    Writes a model plus one production and one test module in the isolated repository.
    """
    # Prepare a complete model and create source subjects in declared scope order.
    payload = _payload()
    # Materialize each relative module path before writing its minimal source.
    for relative in ("src/pkg/domain/model.py", "tests/unit/test_model.py"):
        # Resolve the current governed path and ensure its parent package exists.
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        # Persist a documented module as the inventory selection subject.
        path.write_text('"""! Fixture module."""\n', encoding="utf-8")
    # Write the model after all paths exist, then construct its declaration.
    _write(tmp_path, payload)
    declaration = _declaration(tmp_path)

    # Select only the explicit domain subtree from all governed model scopes.
    selected = governed_paths(declaration, (tmp_path / "src/pkg/domain",))

    # Require focused inventory to exclude the otherwise governed test scope.
    assert selected == ((tmp_path / "src/pkg/domain/model.py").resolve(),)
