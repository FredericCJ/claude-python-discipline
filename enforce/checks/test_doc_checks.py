"""Proof-of-failure tests for the documentation checks.

FLOW-007: each check is driven to fire before its silence on real code is
allowed to mean anything. The conforming cases matter as much as the violating
ones here, because a documentation rule that fires on correct code is a rule
people learn to suppress.

    pytest enforce/checks/test_doc_checks.py
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from checks import Check
from checks.doc_coverage import DocCoverageCheck
from checks.doc_style import DocStyleCheck


def write(tmp_path: Path, source: str, name: str = "mod.py") -> Path:
    """Write a probe module and return its path.

    Always under `src/mypkg/domain/`: the documentation checks ignore the layer,
    so the path only has to look like a source file, not carry a meaning.

    @param tmp_path pytest's per-test directory, used as the root of the fake tree
    @param source the module text, dedented before writing
    @param name the file's name -- a `test_` prefix would exempt it from the style
        check, so every probe here keeps the default
    @return the written file, ready to hand to a check
    """
    target = tmp_path / "src" / "mypkg" / "domain" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dedent(source), encoding="utf-8")
    return target


def rules_fired(check: Check, path: Path) -> set[str]:
    """Rule ids the check reports for one file.

    Collapses duplicates and discards line numbers, so a test asserts which rule
    spoke rather than how often or where.

    @param check any check; it is driven over this one file rather than a tree
    @param path the file to run it over
    @return every rule id reported, empty when the file conforms
    """
    return {f.rule_id for f in check.run([path])}


# ------------------------------------------------------------------- coverage


def test_an_undocumented_module_fires(tmp_path: Path) -> None:
    """A file that opens with code rather than a summary is reported."""
    path = write(tmp_path, "VALUE = 1\n")
    assert "DOC-001" in rules_fired(DocCoverageCheck(), path)


def test_an_undocumented_function_fires(tmp_path: Path) -> None:
    """DOC-001 reaches inside a documented module: the summary does not cover its callables."""
    path = write(tmp_path, '''
        """! Module."""


        def compute(count: int) -> int:
            return count
    ''')
    assert "DOC-001" in rules_fired(DocCoverageCheck(), path)


def test_an_undocumented_class_fires(tmp_path: Path) -> None:
    """A class is an element in its own right, reported by name and not by its module."""
    path = write(tmp_path, '''
        """! Module."""


        class Outline:
            pass
    ''')
    assert "DOC-001" in rules_fired(DocCoverageCheck(), path)


def test_an_undocumented_module_constant_fires(tmp_path: Path) -> None:
    """DOC-002: Python has no docstring slot for a constant, so ## is required."""
    path = write(tmp_path, '''
        """! Module."""

        MAX_RETRIES = 3
    ''')
    assert "DOC-002" in rules_fired(DocCoverageCheck(), path)


def test_a_documented_module_constant_is_accepted(tmp_path: Path) -> None:
    """A `##` block above the assignment satisfies DOC-002."""
    path = write(tmp_path, '''
        """! Module."""

        ## How many times a transient failure is retried.
        MAX_RETRIES = 3
    ''')
    assert rules_fired(DocCoverageCheck(), path) == set()


def test_a_multi_line_hash_block_is_accepted(tmp_path: Path) -> None:
    """A `##` block may continue with plain `#` lines; the search up does not stop at them."""
    path = write(tmp_path, '''
        """! Module."""

        ## How many times a transient failure is retried.
        # Chosen to stay under the port's own timeout budget.
        MAX_RETRIES = 3
    ''')
    assert rules_fired(DocCoverageCheck(), path) == set()


def test_an_undocumented_class_attribute_fires(tmp_path: Path) -> None:
    """A dataclass field needs its own `##` block; the class docstring does not cover it."""
    path = write(tmp_path, '''
        """! Module."""

        from dataclasses import dataclass


        @dataclass(frozen=True, slots=True)
        class Outline:
            """! An outline."""

            title: str
    ''')
    assert "DOC-002" in rules_fired(DocCoverageCheck(), path)


def test_a_documented_enum_member_is_accepted(tmp_path: Path) -> None:
    """Enum members are named values and are documented like any other."""
    path = write(tmp_path, '''
        """! Module."""

        from enum import StrEnum


        class Stage(StrEnum):
            """! Where a document sits in its lifecycle."""

            ## Not yet submitted for review.
            DRAFT = "draft"
            ## Accepted and no longer editable.
            FINAL = "final"
    ''')
    assert rules_fired(DocCoverageCheck(), path) == set()


def test_an_overload_stub_needs_no_docstring(tmp_path: Path) -> None:
    """An overload declares a signature; the implementation carries the contract."""
    path = write(tmp_path, '''
        """! Module."""

        from typing import overload


        @overload
        def read(name: str) -> str: ...
    ''')
    assert "DOC-001" not in rules_fired(DocCoverageCheck(), path)


def test_a_fully_documented_module_is_silent(tmp_path: Path) -> None:
    """The conforming case must stay quiet, or the rule gets suppressed."""
    path = write(tmp_path, '''
        """! Outline manipulation.

        @package mypkg.domain.mod
        """

        ## How many times a transient failure is retried.
        MAX_RETRIES = 3


        def rename(title: str) -> str:
            """! Give an outline a new title.

            @param title the replacement title, already validated
            @return the renamed outline
            """
            return title
    ''')
    assert rules_fired(DocCoverageCheck(), path) == set()


def test_an_undocumented_parameter_fires(tmp_path: Path) -> None:
    """DOC-007: a docstring that skips a parameter leaves the caller guessing."""
    path = write(tmp_path, '''
        """! Module."""


        def rename(title: str, stage: str) -> str:
            """! Give an outline a new title.

            @param title the replacement title
            @return the renamed outline
            """
            return title + stage
    ''')
    assert "DOC-007" in rules_fired(DocCoverageCheck(), path)


def test_an_undocumented_result_fires(tmp_path: Path) -> None:
    """DOC-007 covers the return value, which is the half most often skipped."""
    path = write(tmp_path, '''
        """! Module."""


        def rename(title: str) -> str:
            """! Give an outline a new title.

            @param title the replacement title
            """
            return title
    ''')
    assert "DOC-007" in rules_fired(DocCoverageCheck(), path)


def test_a_none_returning_function_is_not_asked_for_a_result(tmp_path: Path) -> None:
    """Doxygen demands @return here and is wrong; reading the annotation is not."""
    path = write(tmp_path, '''
        """! Module."""


        def emit(title: str) -> None:
            """! Write the title to the report.

            @param title the heading to emit
            """
    ''')
    assert rules_fired(DocCoverageCheck(), path) == set()


def test_a_tests_fixtures_are_not_demanded(tmp_path: Path) -> None:
    """A fixture is documented where it is defined, not at each place it is used."""
    target = tmp_path / "tests" / "test_thing.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        '"""! Tests."""\n\n\ndef test_x(tmp_path: Path) -> None:\n    """! It holds."""\n',
        encoding="utf-8",
    )
    assert rules_fired(DocCoverageCheck(), target) == set()


def test_a_helper_in_a_test_file_still_documents_its_parameters(tmp_path: Path) -> None:
    """The exemption is for `test_` functions, not for every callable beside them."""
    target = tmp_path / "tests" / "test_thing.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        '"""! Tests."""\n\n\ndef build(name: str) -> str:\n    """! Make a probe."""\n'
        "    return name\n",
        encoding="utf-8",
    )
    assert "DOC-007" in rules_fired(DocCoverageCheck(), target)


# ---------------------------------------------------------------------- style


def test_a_hash_block_where_a_docstring_belongs_fires(tmp_path: Path) -> None:
    """DOC-004: a ## block is invisible to help() and every other Python tool."""
    path = write(tmp_path, '''
        """! Module."""

        ## Give an outline a new title.
        # @param title the replacement
        def rename(title: str) -> str:
            return title
    ''')
    assert "DOC-004" in rules_fired(DocStyleCheck(), path)


def test_a_restated_type_in_a_param_fires(tmp_path: Path) -> None:
    """DOC-008: the signature carries the type; prose carries the meaning."""
    path = write(tmp_path, '''
        """! Module."""


        def rename(title: str) -> str:
            """! Give an outline a new title.

            @param title (str) the replacement title
            @return the renamed outline
            """
            return title
    ''')
    assert "DOC-008" in rules_fired(DocStyleCheck(), path)


def test_a_restated_return_type_fires(tmp_path: Path) -> None:
    """DOC-008 applies to the return value as much as to parameters."""
    path = write(tmp_path, '''
        """! Module."""


        def rename(title: str) -> str:
            """! Give an outline a new title.

            @param title the replacement title
            @return (str) the renamed outline
            """
            return title
    ''')
    assert "DOC-008" in rules_fired(DocStyleCheck(), path)


def test_documentation_that_restates_the_name_fires(tmp_path: Path) -> None:
    """DOC-009: a comment repeating the identifier answers nothing."""
    path = write(tmp_path, '''
        """! Module."""


        def parse_outline(text: str) -> str:
            """! Parses the outline."""
            return text
    ''')
    assert "DOC-009" in rules_fired(DocStyleCheck(), path)


def test_a_summary_that_adds_meaning_is_accepted(tmp_path: Path) -> None:
    """The check is conservative: a false positive here pushes authors to pad."""
    path = write(tmp_path, '''
        """! Module."""


        def parse_outline(text: str) -> str:
            """! Reject any heading that skips a depth level.

            @param text the source to read
            @return the parsed outline
            """
            return text
    ''')
    assert rules_fired(DocStyleCheck(), path) == set()


def test_a_code_span_ending_in_a_period_fires(tmp_path: Path) -> None:
    """DOC-010: Doxygen aborts the comment block, naming neither span nor remedy."""
    path = write(tmp_path, '''
        """! Module."""


        def rename(title: str) -> str:
            """! Give an outline a new title, as `A1.` does.

            @param title the replacement title
            @return the renamed outline
            """
            return title
    ''')
    assert "DOC-010" in rules_fired(DocStyleCheck(), path)


def test_an_ellipsis_span_is_accepted(tmp_path: Path) -> None:
    """`...` parses; the trigger is a final period with a non-period before it."""
    path = write(tmp_path, '''
        """! Module."""


        def rename(title: str) -> str:
            """! Give an outline a new title, written `def rename(...)` here.

            @param title the replacement title
            @return the renamed outline
            """
            return title
    ''')
    assert rules_fired(DocStyleCheck(), path) == set()


def test_tests_are_exempt_from_the_style_check(tmp_path: Path) -> None:
    """The style check skips a test path outright; only the coverage check speaks there."""
    target = tmp_path / "tests" / "test_thing.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('"""! Tests."""\n\n\ndef test_x() -> None:\n    pass\n',
                      encoding="utf-8")
    assert rules_fired(DocStyleCheck(), target) == set()


# --------------------------------------------------------- style, `##` blocks


def test_a_hash_block_with_a_restated_type_fires(tmp_path: Path) -> None:
    """DOC-008 reaches a `##` block too: doc_coverage only proves one is present."""
    path = write(tmp_path, '''
        """! Module."""

        ## @param retries (int) how many times to retry.
        MAX_RETRIES = 3
    ''')
    assert "DOC-008" in rules_fired(DocStyleCheck(), path)


def test_a_hash_block_without_a_restated_type_is_accepted(tmp_path: Path) -> None:
    """A `##` block that never names a type in prose stays silent under DOC-008."""
    path = write(tmp_path, '''
        """! Module."""

        ## How many times a transient failure is retried before giving up.
        MAX_RETRIES = 3
    ''')
    assert "DOC-008" not in rules_fired(DocStyleCheck(), path)


def test_a_hash_block_restating_the_name_fires(tmp_path: Path) -> None:
    """DOC-009 on a `##` block: a dataclass field's comment that only repeats its name."""
    path = write(tmp_path, '''
        """! Module."""

        from dataclasses import dataclass


        @dataclass(frozen=True, slots=True)
        class Outline:
            """! A heading and its position in the document."""

            ## Retry count.
            retry_count: int = 3
    ''')
    assert "DOC-009" in rules_fired(DocStyleCheck(), path)


def test_a_hash_block_that_adds_meaning_is_accepted(tmp_path: Path) -> None:
    """The same field, documented with what the count means, stays silent under DOC-009."""
    path = write(tmp_path, '''
        """! Module."""

        from dataclasses import dataclass


        @dataclass(frozen=True, slots=True)
        class Outline:
            """! A heading and its position in the document."""

            ## How many times a transient failure is retried before giving up.
            retry_count: int = 3
    ''')
    assert rules_fired(DocStyleCheck(), path) == set()


def test_a_hash_block_code_span_ending_in_a_period_fires(tmp_path: Path) -> None:
    """DOC-010 on a `##` block: the same span Doxygen cannot parse in a docstring."""
    path = write(tmp_path, '''
        """! Module."""

        ## The retry ceiling, written `MAX.` in the config file.
        MAX_RETRIES = 3
    ''')
    assert "DOC-010" in rules_fired(DocStyleCheck(), path)


def test_a_hash_block_ellipsis_span_is_accepted(tmp_path: Path) -> None:
    """`...` parses in a `##` block exactly as it does in a docstring."""
    path = write(tmp_path, '''
        """! Module."""

        ## The retry ceiling, written `MAX(...)` in the config file.
        MAX_RETRIES = 3
    ''')
    assert "DOC-010" not in rules_fired(DocStyleCheck(), path)


def test_a_multi_line_hash_block_is_checked_for_content(tmp_path: Path) -> None:
    """Content rules reach across a `##` block's plain-`#` continuation lines."""
    path = write(tmp_path, '''
        """! Module."""

        ## The retry ceiling, written `MAX.` in the config file --
        # see the deployment guide for context.
        MAX_RETRIES = 3
    ''')
    assert "DOC-010" in rules_fired(DocStyleCheck(), path)


def test_a_self_describing_hash_block_with_the_trap_inside_a_span_fires(
    tmp_path: Path,
) -> None:
    """The regression this extension guards.

    A `##` block whose own example of the trailing-dot trap is itself written
    inside the span it is warning about.
    """
    path = write(tmp_path, '''
        """! Module."""

        ## A trailing dot breaks Doxygen, e.g. a span holding `foo.` verbatim.
        TRAP = "x"
    ''')
    assert "DOC-010" in rules_fired(DocStyleCheck(), path)


def test_a_self_describing_hash_block_written_safely_is_accepted(tmp_path: Path) -> None:
    """The same explanation stays silent when the example is kept out of a code span.

    This is the form doc_style.py's own `_TRAILING_DOT_SPAN` comment actually uses.
    """
    path = write(tmp_path, '''
        """! Module."""

        ## A trailing dot breaks Doxygen -- e.g. a span holding foo. verbatim,
        ## written here without backticks so this comment does not trip its own
        ## rule.
        TRAP = "x"
    ''')
    assert rules_fired(DocStyleCheck(), path) == set()


def test_hash_block_content_is_exempt_in_tests(tmp_path: Path) -> None:
    """The style check's `##`-block content rules skip a test path just as the rest do."""
    target = tmp_path / "tests" / "test_thing.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        '"""! Tests."""\n\n## @param retries (int) how many.\nMAX_RETRIES = 3\n',
        encoding="utf-8",
    )
    assert rules_fired(DocStyleCheck(), target) == set()


def test_an_upper_case_constant_restating_its_name_fires(tmp_path: Path) -> None:
    """DOC-009 reaches an all-capitals module constant, not only a lower-case field.

    Proof-of-failure for the blind spot the `##` extension inherited: the
    identifier is split before each capital, which turns `MAX_RETRIES` into
    single letters and makes the subset test unsatisfiable. Upper case is the
    convention for exactly the elements `##` blocks document, so the rule was
    inert where it was needed most.

    @param tmp_path pytest's per-test temporary directory
    """
    path = write(tmp_path, '''
        """! Module."""

        ## Max retries.
        MAX_RETRIES = 3
    ''')
    assert "DOC-009" in rules_fired(DocStyleCheck(), path)


def test_an_upper_case_constant_that_adds_meaning_is_accepted(tmp_path: Path) -> None:
    """The same constant stays silent once its block says something the name does not.

    @param tmp_path pytest's per-test temporary directory
    """
    path = write(tmp_path, '''
        """! Module."""

        ## How many times a transient failure is replayed before the call is
        ## given up on and the error propagates to the caller.
        MAX_RETRIES = 3
    ''')
    assert rules_fired(DocStyleCheck(), path) == set()


@pytest.mark.parametrize(
    "check", [DocCoverageCheck(), DocStyleCheck()], ids=lambda c: c.name
)
def test_each_check_declares_its_rules(check: Check) -> None:
    """Every check names the rules it decides, so output traces back to law.

    @param check each documentation check in turn; the list is written out by
        hand, so a new check has to be added to it to be covered here
    """
    assert check.rules
    assert all(r.startswith("DOC-") for r in check.rules)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
