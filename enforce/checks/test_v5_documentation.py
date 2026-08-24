"""Discrimination tests for v5 bindings, narration, semantics, and naming."""

from __future__ import annotations

import ast
import json
from pathlib import PurePosixPath
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest
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

# Import the fixture path protocol only during static analysis.
if TYPE_CHECKING:
    from pathlib import Path


def _payload() -> dict[str, object]:
    """Return a minimal complete documentation model for one source tree.

    @return mutable JSON model
    """
    # Render the minimal governed scope with empty controlled-vocabulary extensions.
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

    @par Effects
    Creates one isolated governed module and its documentation-model artifact.
    """
    # Select the sole production module governed by the fixture documentation scope.
    module = tmp_path / "src" / "sample.py"
    # Materialize and publish normalized source before constructing its declaration.
    module.parent.mkdir()
    module.write_text(dedent(source), encoding="utf-8")
    # Publish either the focused override or the minimal complete documentation model.
    (tmp_path / "documentation-model.json").write_text(
        json.dumps(payload or _payload()), encoding="utf-8"
    )
    # Construct the direct declaration that owns the module and model paths.
    declaration = project.Declaration(
        unit=project.UnitKind.APPLICATION,
        source_roots=(PurePosixPath("src"),),
        documentation_model=PurePosixPath("documentation-model.json"),
        doc_engine="doxygen",
        doc_engine_declared=True,
        source=(tmp_path / "pyproject.toml").resolve(),
    )
    # Return the persisted module together with its configured model owner.
    return module, declaration


def _run(check: Check, module: Path, declaration: project.Declaration) -> list[Finding]:
    """Run one check under the fixture declaration.

    @param check check instance
    @param module governed source
    @param declaration fixture model owner
    @return emitted findings

    @par Effects
    Rebinds the supplied check to the fixture's documentation declaration.
    """
    # Fix the check's project model before evaluating the governed source entity.
    check.declaration = declaration
    # Return ordered finding elements exactly as emitted by the focused mechanism.
    return check.run([module])


def test_every_required_local_binding_shape_is_discovered() -> None:
    """Assignments, aliases, comprehensions, walruses, and captures enter the census."""
    # Parse one function containing every locally governed binding shape.
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

    # Collect unordered `(name, shape)` tuple elements for every discovered binding.
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


def test_a_decorator_comprehension_uses_the_decorator_as_owner() -> None:
    """Narration above a decorator can own bindings created in its expression."""
    # Normalize a decorated test whose identifier comprehension is preceded by narration.
    source = dedent(
        """
        values = ("first", "second")
        # Derive each display identity in declared parameter order.
        @decorate(ids=[value for value in values])
        def test_case() -> None:
            pass
        """
    )
    # Parse the decorated source into its ownership syntax tree.
    tree = ast.parse(source)
    # Select the decorator comprehension target from discovered binding elements.
    target = next(item for item in bindings(tree) if item.name == "value")

    # Associate the target's owning decorator expression with lexical comment blocks.
    result = associate(target.owner_node, comment_blocks(source))

    assert result.owner is not None


@given(st.integers(min_value=1, max_value=5))
def test_comment_association_survives_multiline_prose(line_count: int) -> None:
    """Adding ordinary prose lines does not change the owned assignment.

    @param line_count number of contiguous comment lines
    """
    # Preserve the requested number of semantic comment lines in increasing index order.
    prose = "\n".join(
        # Render each one-based prose element as part of the same contiguous block.
        f"    # Preserve semantic context part {index}." for index in range(line_count)
    )
    # Embed the variable-length prose immediately above one governed assignment.
    source = f"def work() -> None:\n{prose}\n    value = 1\n"
    # Parse the generated source into its ownership syntax tree.
    tree = ast.parse(source)
    # Select the sole assignment node whose owner must remain stable.
    assignment = next(node for node in ast.walk(tree) if isinstance(node, ast.Assign))

    # Associate the assignment with lexical blocks after varying only prose length.
    result = associate(assignment, comment_blocks(source))

    assert result.owner is not None
    assert not result.ambiguous


def test_one_block_owns_one_contiguous_same_suite_step() -> None:
    """A semantic explanation may cover several statements without per-line filler."""
    # Normalize one function whose contiguous statements form a coherent semantic step.
    source = dedent(
        """
        def calculate() -> int:
            # Derive and expose one calibrated domain result.
            raw = 1
            calibrated = raw + 2
            return calibrated
        """
    )
    # Parse the function and extract its lexical comment blocks.
    tree = ast.parse(source)
    blocks = comment_blocks(source)
    # Resolve semantic ownership for every executable node in the function.
    owners = semantic_associations(tree, source, blocks)
    # Select the ordered statement elements belonging to the `calculate` suite.
    statements = next(
        # Match the target function element among all syntax-tree nodes.
        node.body
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "calculate"
    )

    # Require every statement element to resolve to one shared ownership block.
    assert len({owners[statement].owner for statement in statements}) == 1


def test_blank_line_ends_a_semantic_step() -> None:
    """Paragraph separation prevents a prior explanation from floating downward."""
    # Normalize a function whose return is separated from narration by a blank line.
    source = dedent(
        """
        def calculate() -> int:
            # Derive one calibrated domain result.
            calibrated = 3

            return calibrated
        """
    )
    # Parse the function and extract its lexical comment blocks.
    tree = ast.parse(source)
    blocks = comment_blocks(source)
    # Resolve semantic ownership after paragraph separation.
    owners = semantic_associations(tree, source, blocks)
    # Select the return path that must remain unowned.
    return_path = next(node for node in ast.walk(tree) if isinstance(node, ast.Return))

    assert owners[return_path].owner is None


def test_a_local_binding_without_an_owner_fails_doc_016(tmp_path: Path) -> None:
    """Deleting only the local explanation turns coverage red.

    @param tmp_path fixture repository
    """
    # Materialize an otherwise documented callable with one unexplained local result.
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

    # Preserve coverage findings from the focused owner-absence probe.
    findings = _run(DocCoverageCheck(), module, declaration)

    # Require one finding element to name both DOC-016 and the unowned result.
    assert any(item.rule_id == "DOC-016" and "`result`" in item.message for item in findings)


def test_two_binding_owners_fail_as_ambiguous(tmp_path: Path) -> None:
    """A preceding and trailing comment cannot both claim one value.

    @param tmp_path fixture repository
    """
    # Materialize one local binding claimed by preceding and trailing explanations.
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

    # Preserve coverage findings from the focused ambiguity probe.
    findings = _run(DocCoverageCheck(), module, declaration)

    # Require one finding element to carry the stable ambiguous-owner diagnostic.
    assert any(item.diagnostic_id == "LOCAL_BINDING_AMBIGUOUS" for item in findings)


def test_missing_branch_narration_fails_doc_017(tmp_path: Path) -> None:
    """Deleting a branch explanation independently turns narration red.

    @param tmp_path fixture repository
    """
    # Materialize a conditional whose nested refusal is narrated but branch choice is not.
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

    # Preserve narration findings from the focused branch-ownership probe.
    findings = _run(DocNarrationCheck(), module, declaration)

    # Require one finding element to identify the missing conditional-branch meaning.
    assert any(
        item.rule_id == "DOC-017" and "conditional branch" in item.message for item in findings
    )


def test_syntactic_paraphrase_fails_doc_019(tmp_path: Path) -> None:
    """A comment translating a return token does not count as meaning.

    @param tmp_path fixture repository
    """
    # Materialize a return whose comment merely restates the syntax token.
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

    # Preserve narration findings from the focused paraphrase probe.
    findings = _run(DocNarrationCheck(), module, declaration)

    # Require one finding element to identify semantic-content failure.
    assert any(item.rule_id == "DOC-019" for item in findings)


@pytest.mark.parametrize(
    "comment",
    [
        "Compute result using calculate for later accept logic.",
        (
            "Select item as the current element from items while accept preserves "
            "traversal order."
        ),
        "Update accept state only after the required source facts are available.",
        (
            "Capture result as the completed accept outcome for subsequent validation "
            "or publication."
        ),
        "Select the guarded path only after value is negative is satisfied.",
        "Select the empty-or-disabled path when value has no usable value.",
        "Use the available-value path only when value is present.",
        "Bind result to the current value used by the next accept decision.",
        "Unpack left and right using result for later accept logic.",
        "Resolve the branch. Details: usable value.",
    ],
)
def test_known_scaffolding_prose_fails_doc_019(tmp_path: Path, comment: str) -> None:
    """Migration templates do not gain meaning from incidental identifier words.

    @param tmp_path fixture repository
    @param comment known filler text
    """
    # Materialize one return path whose owner carries the selected scaffolding template.
    module, declaration = _fixture(
        tmp_path,
        f'''\
        """! Fixture module."""
        def accept(value: int) -> int:
            """Return one accepted value.
            @param value accepted value
            @return the accepted value
            """
            # {comment}
            return value
        ''',
    )

    # Preserve narration findings from the focused known-filler probe.
    findings = _run(DocNarrationCheck(), module, declaration)

    # Require the selected template to fail through the stable semantic-content rule.
    assert any(item.rule_id == "DOC-019" for item in findings)


def test_plain_binding_scaffolding_fails_doc_019(tmp_path: Path) -> None:
    """A local assignment cannot hide filler outside the operation census.

    @param tmp_path fixture repository
    """
    # Materialize a plain binding with template prose and a separately meaningful return owner.
    module, declaration = _fixture(
        tmp_path,
        '''
        """! Fixture module."""
        def calculate() -> int:
            """Return one calibrated value.
            @return the calibrated value
            """
            # Compute result using calibrate for later calculate logic.
            result = 1
            # Expose the calibrated domain value as the public result.
            return result
        ''',
    )

    # Preserve narration findings from the assignment-only filler probe.
    findings = _run(DocNarrationCheck(), module, declaration)

    # Require exactly the binding step to carry the semantic-content diagnostic.
    assert [item.rule_id for item in findings] == ["DOC-019"]


def test_stray_scaffolding_comment_fails_doc_019(tmp_path: Path) -> None:
    """Filler receives no safe harbor beside syntax outside the operation census.

    @param tmp_path fixture repository
    """
    # Materialize a filler block beside an assertion, which is not itself a governed operation.
    module, declaration = _fixture(
        tmp_path,
        '''
        """! Fixture module."""
        def verify(value: int) -> None:
            """Verify one accepted value.
            @param value accepted value
            """
            # Select the guarded path only after value is positive is satisfied.
            assert value > 0
        ''',
    )

    # Preserve narration findings from the source-wide known-filler scan.
    findings = _run(DocNarrationCheck(), module, declaration)

    # Require the stray block to carry the dedicated scaffolding diagnostic exactly once.
    assert [item.diagnostic_id for item in findings] == ["NARRATION_KNOWN_FILLER"]


def test_two_narration_owners_fail_doc_018(tmp_path: Path) -> None:
    """A preceding and trailing block make semantic-step ownership ambiguous.

    @param tmp_path fixture repository
    """
    # Materialize one return path claimed by preceding and trailing narration.
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

    # Preserve narration findings from the focused owner-ambiguity probe.
    findings = _run(DocNarrationCheck(), module, declaration)

    # Require one finding element to identify duplicate semantic owners.
    assert any(item.rule_id == "DOC-018" for item in findings)


def test_boolean_and_collection_meaning_fail_independently(tmp_path: Path) -> None:
    """Both boolean states and collection content/order are separate predicates.

    @param tmp_path fixture repository
    """
    # Materialize entity blocks omitting both boolean states and collection semantics.
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

    # Preserve semantic findings from the combined but independently decidable probe.
    findings = _run(DocSemanticsCheck(), module, declaration)
    # Collect unordered diagnostic-id string elements from every emitted finding.
    diagnostics = {item.diagnostic_id for item in findings}

    assert "BOOLEAN_STATES" in diagnostics
    assert "COLLECTION_ELEMENTS" in diagnostics
    assert "COLLECTION_ORDER" in diagnostics


def test_deleting_a_declared_unit_fails_doc_026(tmp_path: Path) -> None:
    """A model-selected unit must occur in the owning entity documentation.

    @param tmp_path fixture repository
    """
    # Start from the unordered model mapping whose keys name views and values hold rules.
    payload = _payload()
    # Declare milliseconds as a required semantic property for timeout identifiers.
    payload["semantic_properties"] = [
        {
            "identifier_pattern": "*_ms",
            "property": "unit",
            "value": "milliseconds",
            "scopes": ["src"],
        }
    ]
    # Materialize a matching timeout entity whose prose omits its declared unit.
    module, declaration = _fixture(
        tmp_path,
        '"""! Fixture module."""\n## Maximum wait before timeout.\ntimeout_ms: int = 10\n',
        payload,
    )

    # Preserve semantic findings from the focused declared-property probe.
    findings = _run(DocSemanticsCheck(), module, declaration)

    # Require one finding element to identify the absent declared property.
    assert any(item.diagnostic_id == "DECLARED_PROPERTY" for item in findings)


def test_detectable_effect_without_contract_fails_doc_027(tmp_path: Path) -> None:
    """An observable write requires the stable callable effect paragraph.

    @param tmp_path fixture repository
    """
    # Materialize a filesystem write with narration but no callable effects paragraph.
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

    # Preserve semantic findings from the focused missing-contract probe.
    findings = _run(DocSemanticsCheck(), module, declaration)

    # Require one finding element to identify the callable-effects obligation.
    assert any(item.rule_id == "DOC-027" for item in findings)


def test_immutable_string_replace_is_not_a_detectable_effect(tmp_path: Path) -> None:
    """An ambiguous method spelling cannot turn a pure text rewrite into an effect.

    @param tmp_path fixture repository
    """
    # Materialize an immutable string transformation as the pure accepting control.
    module, declaration = _fixture(
        tmp_path,
        '''
        """! Fixture module."""
        def rewrite(text: str) -> str:
            """Substitute one token in detached text.
            @param text immutable source text
            @return detached text containing the substitution
            """
            # Produce detached text without changing the caller's immutable source.
            return text.replace("old", "new")
        ''',
    )

    # Preserve semantic findings from the ambiguous method-name control.
    findings = _run(DocSemanticsCheck(), module, declaration)

    # Require every finding element to exclude the callable-effects rule.
    assert not any(item.rule_id == "DOC-027" for item in findings)


def test_qualified_os_replace_remains_a_detectable_effect(tmp_path: Path) -> None:
    """Exact operating-system replacement remains in the bounded effect vocabulary.

    @param tmp_path fixture repository
    """
    # Materialize the qualified operating-system namespace replacement effect.
    module, declaration = _fixture(
        tmp_path,
        '''
        """! Fixture module."""
        import os

        def publish(source: str, destination: str) -> None:
            """Publish staged bytes at their destination.
            @param source staged filesystem path
            @param destination final filesystem path
            """
            # Replace the destination namespace entry with respect to concurrent readers.
            os.replace(source, destination)
        ''',
    )

    # Preserve semantic findings from the exact qualified-effect probe.
    findings = _run(DocSemanticsCheck(), module, declaration)

    # Require one finding element to retain the callable-effects obligation.
    assert any(item.rule_id == "DOC-027" for item in findings)


def test_container_member_deletion_is_a_detectable_effect(tmp_path: Path) -> None:
    """Deleting caller-visible indexed state requires an effect contract.

    @param tmp_path fixture repository
    """
    # Materialize deletion from caller-visible indexed store state.
    module, declaration = _fixture(
        tmp_path,
        '''
        """! Fixture module."""
        class Store:
            """One mutable store."""
            def remove(self, key: str) -> None:
                """Remove one stored value.
                @param key stored identity
                """
                # Remove the selected member from externally visible store state.
                del self.values[key]
        ''',
    )

    # Preserve semantic findings from the container-mutation probe.
    findings = _run(DocSemanticsCheck(), module, declaration)

    # Require one finding element to retain the callable-effects obligation.
    assert any(item.rule_id == "DOC-027" for item in findings)


def test_constructor_and_local_projection_are_not_external_effects(tmp_path: Path) -> None:
    """Fresh-object initialization and local assembly do not mutate caller state.

    @param tmp_path fixture repository
    """
    # Materialize fresh-object initialization and detached local projection together.
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

    # Preserve semantic findings from both pure local-state controls.
    findings = _run(DocSemanticsCheck(), module, declaration)

    # Require every finding element to exclude the callable-effects rule.
    assert not any(item.rule_id == "DOC-027" for item in findings)


def test_deleting_an_abbreviation_entry_fails_doc_024(tmp_path: Path) -> None:
    """An identifiable initialism cannot outlive its controlled vocabulary row.

    @param tmp_path fixture repository
    """
    # Materialize an API initialism with no controlled-vocabulary declaration.
    module, declaration = _fixture(
        tmp_path,
        '"""! Fixture module."""\n'
        "## Client used for the application interface.\n"
        "APIClient = object()\n",
    )

    # Preserve naming findings from the missing-abbreviation probe.
    findings = _run(DocNamingCheck(), module, declaration)

    # Require one finding element to identify both DOC-024 and the API token.
    assert any(item.rule_id == "DOC-024" and "`API`" in item.message for item in findings)


def test_constant_case_words_are_not_guessed_to_be_abbreviations(tmp_path: Path) -> None:
    """Constant casing alone cannot distinguish initialisms from ordinary words.

    @param tmp_path fixture repository
    """
    # Materialize ordinary all-capitals words as the abbreviation false-positive control.
    module, declaration = _fixture(
        tmp_path,
        '"""! Fixture module."""\n'
        "## Number of whole seconds in one civil day.\n"
        "SECONDS_PER_DAY = 86400\n",
    )

    # Preserve naming findings from the ordinary constant-word control.
    findings = _run(DocNamingCheck(), module, declaration)

    # Require every finding element to exclude the controlled-abbreviation rule.
    assert not any(item.rule_id == "DOC-024" for item in findings)


def test_identifier_outside_a_declared_grammar_fails_doc_023(tmp_path: Path) -> None:
    """A scoped grammar rejects an identifier missing its semantic dimensions.

    @param tmp_path fixture repository
    """
    # Start from the unordered model mapping whose keys name views and values hold rules.
    payload = _payload()
    # Declare a scoped two-dimensional identifier grammar for production source.
    payload["identifier_grammars"] = [
        {
            "scope": "src",
            "pattern": "^(?P<concept>[a-z]+)_(?P<role>[a-z]+)$",
            "dimensions": ["concept", "role"],
            "exclusions": [],
        }
    ]
    # Materialize a one-dimensional identifier missing its required role segment.
    module, declaration = _fixture(
        tmp_path,
        '"""! Fixture module."""\n## Domain value lacking its role dimension.\nvalue = 1\n',
        payload,
    )

    # Preserve naming findings from the scoped grammar probe.
    findings = _run(DocNamingCheck(), module, declaration)

    # Require one finding element to identify both DOC-023 and the malformed name.
    assert any(item.rule_id == "DOC-023" and "`value`" in item.message for item in findings)


def test_deleting_a_generated_mapping_fails_doc_025(tmp_path: Path) -> None:
    """A visibly generated identifier cannot lose its canonical origin.

    @param tmp_path fixture repository
    """
    # Materialize a leading generated marker with no canonical-origin mapping.
    module, declaration = _fixture(
        tmp_path,
        '"""! Fixture module."""\n'
        "## Derived wire representation of a record.\n"
        "generated_wire_record = object()\n",
    )

    # Preserve naming findings from the missing generated-origin probe.
    findings = _run(DocNamingCheck(), module, declaration)

    # Require one finding element to identify the generated-name mapping rule.
    assert any(item.rule_id == "DOC-025" for item in findings)


def test_generated_concept_mentioned_inside_a_name_is_not_a_marker(tmp_path: Path) -> None:
    """A generated-output predicate is not itself generated vocabulary.

    @param tmp_path fixture repository
    """
    # Materialize `generated` as an interior predicate concept, not a leading marker.
    module, declaration = _fixture(
        tmp_path,
        '''
        """! Fixture module."""
        def is_generated_output(value: object) -> bool:
            """Whether a value represents generated output.
            @param value candidate value
            @return true for generated output; false for authored output
            """
            # Distinguish generated output from the authored alternative.
            return value is not None
        ''',
    )

    # Preserve naming findings from the interior-concept control.
    findings = _run(DocNamingCheck(), module, declaration)

    # Require every finding element to exclude generated-origin mapping.
    assert not any(item.rule_id == "DOC-025" for item in findings)
