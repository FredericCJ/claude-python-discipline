"""Discrimination tests for v5 bindings, narration, semantics, and naming."""

from __future__ import annotations

import ast
import json
from pathlib import PurePosixPath
from textwrap import dedent
from typing import TYPE_CHECKING

from hypothesis import given
from hypothesis import strategies as st

from checks import Check, Finding, project
from checks.comment_association import (
    associate,
    bindings,
    comment_blocks,
    semantic_associations,
)
from checks.doc_coverage import DocCoverageCheck
from checks.doc_naming import DocNamingCheck
from checks.doc_narration import DocNarrationCheck
from checks.doc_semantics import DocSemanticsCheck

if TYPE_CHECKING:
    from pathlib import Path


def _payload() -> dict[str, object]:
    """Return a minimal complete documentation model for one source tree.

    @return mutable JSON model
    """
    return {
        "schema_version": 1,
        "engine": "doxygen",
        "scopes": [{"path": "src", "kind": "production", "ownership": "governed"}],
        "controlled_abbreviations": [],
        "identifier_grammars": [],
        "generated_names": {"markers": ["generated"], "mappings": {}},
        "semantic_properties": [],
    }


def _fixture(
    tmp_path: Path, source: str, payload: dict[str, object] | None = None
) -> tuple[Path, project.Declaration]:
    """Write one governed module and its directly constructed declaration.

    @param tmp_path fixture repository
    @param source complete Python module
    @param payload optional documentation-model override
    @return source path and declaration
    """
    module = tmp_path / "src" / "sample.py"
    module.parent.mkdir()
    module.write_text(dedent(source), encoding="utf-8")
    (tmp_path / "documentation-model.json").write_text(
        json.dumps(payload or _payload()), encoding="utf-8"
    )
    declaration = project.Declaration(
        unit=project.UnitKind.APPLICATION,
        source_roots=(PurePosixPath("src"),),
        documentation_model=PurePosixPath("documentation-model.json"),
        doc_engine="doxygen",
        doc_engine_declared=True,
        source=(tmp_path / "pyproject.toml").resolve(),
    )
    return module, declaration


def _run(check: Check, module: Path, declaration: project.Declaration) -> list[Finding]:
    """Run one check under the fixture declaration.

    @param check check instance
    @param module governed source
    @param declaration fixture model owner
    @return emitted findings
    """
    check.declaration = declaration
    return check.run([module])


def test_every_required_local_binding_shape_is_discovered() -> None:
    """Assignments, aliases, comprehensions, walruses, and captures enter the census."""
    tree = ast.parse(
        dedent(
            """
            def decode(items, manager):
                left, right = items
                for loop_item in items:
                    pass
                selected = [entry for entry in items]
                with manager() as stream:
                    pass
                try:
                    pass
                except OSError as problem:
                    pass
                if (decoded := left):
                    pass
                match right:
                    case {"value": captured, **remaining}:
                        pass
            """
        )
    )

    found = {(item.name, item.shape) for item in bindings(tree)}

    assert {
        ("left", "assignment"),
        ("right", "assignment"),
        ("loop_item", "loop target"),
        ("selected", "assignment"),
        ("entry", "comprehension target"),
        ("stream", "context-manager alias"),
        ("problem", "exception alias"),
        ("decoded", "assignment expression"),
        ("captured", "pattern capture"),
        ("remaining", "pattern capture"),
    } <= found


@given(st.integers(min_value=1, max_value=5))
def test_comment_association_survives_multiline_prose(line_count: int) -> None:
    """Adding ordinary prose lines does not change the owned assignment.

    @param line_count number of contiguous comment lines
    """
    prose = "\n".join(
        f"    # Preserve semantic context part {index}." for index in range(line_count)
    )
    source = f"def work() -> None:\n{prose}\n    value = 1\n"
    tree = ast.parse(source)
    assignment = next(node for node in ast.walk(tree) if isinstance(node, ast.Assign))

    result = associate(assignment, comment_blocks(source))

    assert result.owner is not None
    assert not result.ambiguous


def test_one_block_owns_one_contiguous_same_suite_step() -> None:
    """A semantic explanation may cover several statements without per-line filler."""
    source = dedent(
        """
        def calculate() -> int:
            # Derive and expose one calibrated domain result.
            raw = 1
            calibrated = raw + 2
            return calibrated
        """
    )
    tree = ast.parse(source)
    blocks = comment_blocks(source)
    owners = semantic_associations(tree, source, blocks)
    statements = next(
        node.body
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "calculate"
    )

    assert len({owners[statement].owner for statement in statements}) == 1


def test_blank_line_ends_a_semantic_step() -> None:
    """Paragraph separation prevents a prior explanation from floating downward."""
    source = dedent(
        """
        def calculate() -> int:
            # Derive one calibrated domain result.
            calibrated = 3

            return calibrated
        """
    )
    tree = ast.parse(source)
    blocks = comment_blocks(source)
    owners = semantic_associations(tree, source, blocks)
    return_path = next(node for node in ast.walk(tree) if isinstance(node, ast.Return))

    assert owners[return_path].owner is None


def test_a_local_binding_without_an_owner_fails_doc_016(tmp_path: Path) -> None:
    """Deleting only the local explanation turns coverage red.

    @param tmp_path fixture repository
    """
    module, declaration = _fixture(
        tmp_path,
        '''
        """! Fixture module."""
        def calculate() -> int:
            """Return the calibrated result.
            @return the calibrated result
            """
            result = 1
            return result
        ''',
    )

    findings = _run(DocCoverageCheck(), module, declaration)

    assert any(item.rule_id == "DOC-016" and "`result`" in item.message for item in findings)


def test_two_binding_owners_fail_as_ambiguous(tmp_path: Path) -> None:
    """A preceding and trailing comment cannot both claim one value.

    @param tmp_path fixture repository
    """
    module, declaration = _fixture(
        tmp_path,
        '''
        """! Fixture module."""
        def calculate() -> int:
            """Return the calibrated result.
            @return the calibrated result
            """
            # Preserve the calibrated domain value.
            result = 1  # Hold the boundary representation for return.
            # Expose the completed calculation to the caller.
            return result
        ''',
    )

    findings = _run(DocCoverageCheck(), module, declaration)

    assert any(item.diagnostic_id == "LOCAL_BINDING_AMBIGUOUS" for item in findings)


def test_missing_branch_narration_fails_doc_017(tmp_path: Path) -> None:
    """Deleting a branch explanation independently turns narration red.

    @param tmp_path fixture repository
    """
    module, declaration = _fixture(
        tmp_path,
        '''
        """! Fixture module."""
        def accept(value: int) -> int:
            """Accept a non-negative value.
            @param value candidate value
            @return the accepted value
            """
            if value < 0:
                # Reject invalid input before it reaches storage.
                raise ValueError(value)
            # Return the validated domain value unchanged.
            return value
        ''',
    )

    findings = _run(DocNarrationCheck(), module, declaration)

    assert any(
        item.rule_id == "DOC-017" and "conditional branch" in item.message for item in findings
    )


def test_syntactic_paraphrase_fails_doc_019(tmp_path: Path) -> None:
    """A comment translating a return token does not count as meaning.

    @param tmp_path fixture repository
    """
    module, declaration = _fixture(
        tmp_path,
        '''
        """! Fixture module."""
        def accept(value: int) -> int:
            """Return one accepted value.
            @param value accepted value
            @return the accepted value
            """
            # Return the value.
            return value
        ''',
    )

    findings = _run(DocNarrationCheck(), module, declaration)

    assert any(item.rule_id == "DOC-019" for item in findings)


def test_two_narration_owners_fail_doc_018(tmp_path: Path) -> None:
    """A preceding and trailing block make semantic-step ownership ambiguous.

    @param tmp_path fixture repository
    """
    module, declaration = _fixture(
        tmp_path,
        '''
        """! Fixture module."""
        def accept(value: int) -> int:
            """Return one accepted value.
            @param value accepted value
            @return the accepted value
            """
            # Preserve the accepted domain value for the public result.
            return value  # Expose the validated value without conversion.
        ''',
    )

    findings = _run(DocNarrationCheck(), module, declaration)

    assert any(item.rule_id == "DOC-018" for item in findings)


def test_boolean_and_collection_meaning_fail_independently(tmp_path: Path) -> None:
    """Both boolean states and collection content/order are separate predicates.

    @param tmp_path fixture repository
    """
    module, declaration = _fixture(
        tmp_path,
        '''
        """! Fixture module."""
        ## Whether optional entries are accepted.
        ALLOW_MISSING: bool = True
        ## Record names.
        NAMES: list[str] = []
        ''',
    )

    findings = _run(DocSemanticsCheck(), module, declaration)
    diagnostics = {item.diagnostic_id for item in findings}

    assert "BOOLEAN_STATES" in diagnostics
    assert "COLLECTION_ELEMENTS" in diagnostics
    assert "COLLECTION_ORDER" in diagnostics


def test_deleting_a_declared_unit_fails_doc_026(tmp_path: Path) -> None:
    """A model-selected unit must occur in the owning entity documentation.

    @param tmp_path fixture repository
    """
    payload = _payload()
    payload["semantic_properties"] = [
        {
            "identifier_pattern": "*_ms",
            "property": "unit",
            "value": "milliseconds",
            "scopes": ["src"],
        }
    ]
    module, declaration = _fixture(
        tmp_path,
        '"""! Fixture module."""\n## Maximum wait before timeout.\ntimeout_ms: int = 10\n',
        payload,
    )

    findings = _run(DocSemanticsCheck(), module, declaration)

    assert any(item.diagnostic_id == "DECLARED_PROPERTY" for item in findings)


def test_detectable_effect_without_contract_fails_doc_027(tmp_path: Path) -> None:
    """An observable write requires the stable callable effect paragraph.

    @param tmp_path fixture repository
    """
    module, declaration = _fixture(
        tmp_path,
        '''
        """! Fixture module."""
        def persist(path, payload) -> None:
            """Persist the encoded payload.
            @param path destination path
            @param payload encoded bytes
            """
            # Commit the complete payload to the declared destination.
            path.write_bytes(payload)
        ''',
    )

    findings = _run(DocSemanticsCheck(), module, declaration)

    assert any(item.rule_id == "DOC-027" for item in findings)


def test_constructor_and_local_projection_are_not_external_effects(tmp_path: Path) -> None:
    """Fresh-object initialization and local assembly do not mutate caller state.

    @param tmp_path fixture repository
    """
    module, declaration = _fixture(
        tmp_path,
        '''
        """! Fixture module."""
        class Record:
            """One initialized record."""
            def __init__(self, value: int) -> None:
                """Initialize the record.
                @param value stored domain value
                """
                # Establish the record's validated state before publication.
                self.value = value

        def project(value: int) -> dict[str, int]:
            """Build a detached projection.
            @param value source domain value
            @return one key mapped to the source value, with insertion order preserved
            """
            # Assemble a fresh result that shares no mutable state with the caller.
            result: dict[str, int] = {}
            result["value"] = value
            # Expose the completed detached projection.
            return result
        ''',
    )

    findings = _run(DocSemanticsCheck(), module, declaration)

    assert not any(item.rule_id == "DOC-027" for item in findings)


def test_deleting_an_abbreviation_entry_fails_doc_024(tmp_path: Path) -> None:
    """An identifiable initialism cannot outlive its controlled vocabulary row.

    @param tmp_path fixture repository
    """
    module, declaration = _fixture(
        tmp_path,
        '"""! Fixture module."""\n'
        "## Client used for the application interface.\n"
        "APIClient = object()\n",
    )

    findings = _run(DocNamingCheck(), module, declaration)

    assert any(item.rule_id == "DOC-024" and "`API`" in item.message for item in findings)


def test_constant_case_words_are_not_guessed_to_be_abbreviations(tmp_path: Path) -> None:
    """Constant casing alone cannot distinguish initialisms from ordinary words.

    @param tmp_path fixture repository
    """
    module, declaration = _fixture(
        tmp_path,
        '"""! Fixture module."""\n'
        "## Number of whole seconds in one civil day.\n"
        "SECONDS_PER_DAY = 86400\n",
    )

    findings = _run(DocNamingCheck(), module, declaration)

    assert not any(item.rule_id == "DOC-024" for item in findings)


def test_identifier_outside_a_declared_grammar_fails_doc_023(tmp_path: Path) -> None:
    """A scoped grammar rejects an identifier missing its semantic dimensions.

    @param tmp_path fixture repository
    """
    payload = _payload()
    payload["identifier_grammars"] = [
        {
            "scope": "src",
            "pattern": "^(?P<concept>[a-z]+)_(?P<role>[a-z]+)$",
            "dimensions": ["concept", "role"],
            "exclusions": [],
        }
    ]
    module, declaration = _fixture(
        tmp_path,
        '"""! Fixture module."""\n## Domain value lacking its role dimension.\nvalue = 1\n',
        payload,
    )

    findings = _run(DocNamingCheck(), module, declaration)

    assert any(item.rule_id == "DOC-023" and "`value`" in item.message for item in findings)


def test_deleting_a_generated_mapping_fails_doc_025(tmp_path: Path) -> None:
    """A visibly generated identifier cannot lose its canonical origin.

    @param tmp_path fixture repository
    """
    module, declaration = _fixture(
        tmp_path,
        '"""! Fixture module."""\n'
        "## Derived wire representation of a record.\n"
        "generated_wire_record = object()\n",
    )

    findings = _run(DocNamingCheck(), module, declaration)

    assert any(item.rule_id == "DOC-025" for item in findings)
