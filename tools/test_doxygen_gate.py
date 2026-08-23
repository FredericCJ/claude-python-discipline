"""Doxygen is watched catching something, and watched refusing to be vacuous.

**Oracle: differential.** The generator runs over the conformant reference and over
copies damaged in ways `law/DOC` names, and the verdicts are compared.

For the whole of its life in this repository Doxygen was installed, pinned, and
invoked only as `--version`. Four rules were `external` on it. A tool that reports
what version it is decides nothing about documentation, and these are what make
the difference visible.

**What this gate does and does not decide, measured rather than assumed.**
`enforce/Doxyfile` disables `WARN_NO_PARAMDOC` because 1.17.0 still demands a
return description from `-> None` procedures. `discipline/fact/doxygen.md`
records that residual. `WARN_IF_UNDOCUMENTED` is enabled again because the 1.10
field-attribution false positive no longer reproduces. Doxygen therefore decides
representable entity presence, while `DOC-007` completeness and unrepresentable
Python binding shapes remain owned by `check:doc_coverage`.

    pytest tools/test_doxygen_gate.py
"""

from __future__ import annotations

import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- inert result fixture
from contextlib import contextmanager
from hashlib import sha256
from typing import TYPE_CHECKING, Final

import pytest

import doxygen_gate

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from contextlib import AbstractContextManager
    from pathlib import Path

## Skip rather than fail where the binary is absent: `check_env.py` already fails
## the environment for a missing pin, and a second failure for one cause is noise.
_DOXYGEN: Final = doxygen_gate.locate_native("doxygen")

## Applied to every test here: the gate needs the binary, and `check_env.py`
## already fails the environment when the pin is missing. A second failure for
## one cause is noise a reader learns to skim.
pytestmark = pytest.mark.skipif(_DOXYGEN is None,
                                reason="doxygen is not installed in this environment")


def _generated_probe(
    extra_configuration: str = "GENERATE_XML=YES\n",
) -> AbstractContextManager[doxygen_gate.GeneratedDocumentation]:
    """Generate the version-qualification fixture for one bounded inspection.

    @param extra_configuration settings appended after the canonical Doxyfile
    @return a context manager whose output exists for the duration of the context
    """
    assert _DOXYGEN is not None
    # Return a context manager whose output exists for the duration of the context to the
    # Details: caller.
    return doxygen_gate.generated(
        _DOXYGEN,
        doxygen_gate.PROBE_ROOT,
        extra_configuration=extra_configuration,
    )


def _html_text(output: Path) -> str:
    """Join generated pages while excluding syntax-highlighted source listings.

    @param output Doxygen output root
    @return the text of entity and index pages
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    # Return the text of entity and index pages to the caller.
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (output / "html").glob("*.html")
        if not path.name.endswith("_source.html")
    )


def _run_inline_source(
    tmp_path: Path,
    source: str,
    settings: str,
) -> tuple[int, str]:
    """Run one reduced behavior probe through the canonical configuration.

    @param tmp_path isolated fixture directory
    @param source complete Python module text
    @param settings final Doxygen overrides for the behavior under test
    @return native exit status and combined diagnostics

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = tmp_path / "inline"
    # Publish the externally visible effect after all required inputs are ready.
    (root / "src").mkdir(parents=True)
    # Publish the externally visible effect after all required inputs are ready.
    (root / "src" / "probe.py").write_text(source, encoding="utf-8")
    assert _DOXYGEN is not None
    # Capture result as the completed run inline source outcome for subsequent validation or
    # Details: publication.
    # Confine the acquired resource to this operation and release it on every exit.
    with doxygen_gate.generated(
        _DOXYGEN,
        root,
        extra_configuration=settings,
    ) as result:
        # Return native exit status and combined diagnostics to the caller.
        return (
            result.finished.returncode,
            f"{result.finished.stdout}\n{result.finished.stderr}",
        )


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A writable copy of the reference package.

    @param tmp_path the per-test directory
    @return the copy's root
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    destination = tmp_path / "reference"
    shutil.copytree(doxygen_gate.DEFAULT_ROOT, destination,
                    ignore=shutil.ignore_patterns("__pycache__", "build",
                                                  ".pytest_cache", ".mypy_cache"))
    # Return the copy's root to the caller.
    return destination


def test_the_reference_generates_cleanly() -> None:
    """The positive case, asserted first.

    A gate that failed on the conformant package would make every negative below
    meaningless, and would be reporting the fixture rather than the rule.
    """
    # Preserve the current decoded diagnostic line before location normalization.
    status, line = doxygen_gate.run(doxygen_gate.DEFAULT_ROOT,
                                    doxygen_gate.MINIMUM_FILES)
    assert status == doxygen_gate.EXIT_OK, line


def test_a_documented_parameter_that_does_not_exist_is_caught(tree: Path) -> None:
    """DOC-005: a docstring is parsed as documentation, so it can be wrong.

    The case that proves the gate reads the docstrings rather than merely reading
    the files: `@param ghost` names an argument the signature does not have, and
    only a parser can tell.

    @param tree a writable copy of the reference

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Compute plan using tree / "src" / "refpkg" / "domain" / "plan.py" for later test a
    # Details: documented parameter that does not exist is caught logic.
    plan = tree / "src" / "refpkg" / "domain" / "plan.py"
    # Compute original using plan.read text for later test a documented parameter that does not
    # Details: exist is caught logic.
    original = plan.read_text(encoding="utf-8")
    # Resolve the repository-confined path used by this operation before filesystem access.
    target = (
        "    @param entries each file under consideration; input order is "
        "deliberately irrelevant"
    )
    assert target in original
    # Publish the externally visible effect after all required inputs are ready.
    plan.write_text(
        original.replace(
            target,
            target + "\n    @param ghost a parameter this function does not have",
            1,
        ),
        encoding="utf-8",
    )
    # Preserve the current decoded diagnostic line before location normalization.
    status, line = doxygen_gate.run(tree, doxygen_gate.MINIMUM_FILES)
    assert status == doxygen_gate.EXIT_FAILED
    assert "ghost" in line


def test_generating_nothing_is_not_generating_cleanly(tmp_path: Path) -> None:
    """DOC-011: an empty run is a failed run.

    Written expecting the failure every other tool here has -- exiting 0 over an
    empty input -- and Doxygen 1.17.0 does not share it: it reports "No
    files to be processed" and fails on its own. The assertion is on the VERDICT
    rather than the wording, so it holds either way, and the module docstring was
    corrected rather than the test bent to fit the claim.

    @param tmp_path the fixture directory

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    (tmp_path / "src").mkdir()
    # Preserve the current decoded diagnostic line before location normalization.
    status, line = doxygen_gate.run(tmp_path, doxygen_gate.MINIMUM_FILES)
    assert status == doxygen_gate.EXIT_FAILED
    assert "no files to be processed" in line.lower() or "source page" in line


def test_a_projection_without_every_relation_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DOC-029: enabled but unexercised relations cannot earn a green verdict.

    @param tmp_path fixture directory
    @param monkeypatch isolated gate substitution

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    (tmp_path / "src").mkdir()

    @contextmanager
    def relationless(
        _executable: str,
        _root: Path,
        *,
        extra_configuration: str = "",
    ) -> Iterator[doxygen_gate.GeneratedDocumentation]:
        """Yield a successful projection whose caller relation is empty.

        @param _executable ignored executable selected by the gate
        @param _root ignored fixture root
        @param extra_configuration ignored Doxygen override
        @return successful generation record with one absent relation family
        """
        del extra_configuration
        # Preserve the external command representation and its observed completion outcome.
        finished = subprocess.CompletedProcess(("doxygen", "-"), 0, "", "")
        yield doxygen_gate.GeneratedDocumentation(
            finished=finished,
            output=tmp_path,
            source_pages=doxygen_gate.MINIMUM_FILES,
            relation_graphs=(1, 0, 1),
        )

    monkeypatch.setattr(doxygen_gate, "locate_native", lambda _name: "doxygen")
    monkeypatch.setattr(doxygen_gate, "generated", relationless)
    # Preserve the current decoded diagnostic line before location normalization.
    status, line = doxygen_gate.run(tmp_path, doxygen_gate.MINIMUM_FILES)

    assert status == doxygen_gate.EXIT_FAILED
    assert "caller relationship graph" in line


def test_no_src_is_refused_rather_than_passed(tmp_path: Path) -> None:
    """A tree with nothing to document is a caller error, not a clean run.

    @param tmp_path the fixture directory
    """
    # Capture status as the completed test no src is refused rather than passed outcome for
    # Details: subsequent validation or publication.
    status, _ = doxygen_gate.run(tmp_path, doxygen_gate.MINIMUM_FILES)
    assert status == doxygen_gate.EXIT_FAILED


def test_the_run_leaves_the_fixture_untouched() -> None:
    """The gate writes 235 files, and none of them into the reference.

    `OUTPUT_DIRECTORY` is overridden through stdin precisely so build products do
    not land in `enforce/fixtures/reference/`, where `broken_copy` would duplicate
    them into every mutation and the release would have to prune them.
    """
    # Collect unique before element values; their order is deliberately unordered.
    before = {p.name for p in doxygen_gate.DEFAULT_ROOT.iterdir()}
    doxygen_gate.run(doxygen_gate.DEFAULT_ROOT, doxygen_gate.MINIMUM_FILES)
    # Select p as the current element from doxygen_gate.DEFAULT_ROOT.iterdir()} == before, (
    # Details: while test the run leaves the fixture untouched preserves traversal order.
    assert {p.name for p in doxygen_gate.DEFAULT_ROOT.iterdir()} == before, (
        "the documentation run left build products in the fixture"
    )


def test_an_undocumented_function_is_caught_here(tree: Path) -> None:
    """The 1.17 gate again rejects a representable entity without a contract.

    @param tree a writable copy of the reference

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    model = tree / "src" / "refpkg" / "domain" / "model.py"
    # Publish the externally visible effect after all required inputs are ready.
    model.write_text(
        model.read_text(encoding="utf-8")
        + "\n\ndef undocumented(value: int) -> int:\n    return value\n",
        encoding="utf-8",
    )
    # Preserve the current decoded diagnostic line before location normalization.
    status, line = doxygen_gate.run(tree, doxygen_gate.MINIMUM_FILES)
    assert status == doxygen_gate.EXIT_FAILED
    assert "undocumented" in line


def test_117_projects_supported_python_entities_and_contract_commands() -> None:
    """The exact target reads both comment forms and every required command."""
    # Capture result as the completed test 117 projects supported python entities and contract
    # Details: commands outcome for subsequent validation or publication.
    # Confine the acquired resource to this operation and release it on every exit.
    with _generated_probe() as result:
        assert result.finished.returncode == 0, result.finished.stderr
        # Retain the immutable source representation consumed by subsequent analysis.
        body = _html_text(result.output)
        # Select phrase as the current element from ( while test 117 projects supported python
        # Details: entities and contract commands preserves traversal order.
        # Advance test 117 projects supported python entities and contract commands through the
        # Details: current input element in declared order.
        for phrase in (
            "Number of attempts permitted",
            "Limit documented after its declaration",
            "Private module state remains extractable",
            "Internal calibration offset",
            "Parameters",
            "Returns",
            "Exceptions",
            "Precondition",
            "Postcondition",
            "Invariant",
        ):
            assert phrase in body


def test_117_exposes_its_local_and_nested_definition_limits() -> None:
    """Locals, nested functions and annotation-only fields are not entities."""
    # Capture result as the completed test 117 exposes its local and nested definition limits
    # Details: outcome for subsequent validation or publication.
    # Confine the acquired resource to this operation and release it on every exit.
    with _generated_probe() as result:
        # Collect unique member names element values; their order is deliberately unordered.
        member_names: set[str] = set()
        # Resolve the repository-confined path used by this operation before filesystem access.
        # Advance test 117 exposes its local and nested definition limits through the current
        # Details: input element in declared order.
        for path in (result.output / "xml").glob("*.xml"):
            # Compute xml using path.read text for later test 117 exposes its local and nested
            # Details: definition limits logic.
            xml = path.read_text(encoding="utf-8", errors="strict")
            member_names.update(
                re.findall(
                    r"<memberdef\b.*?<name>([^<]+)</name>",
                    xml,
                    flags=re.DOTALL,
                ),
            )
        assert {
            "RETRY_LIMIT",
            "TRAILING_LIMIT",
            "_PRIVATE_LIMIT",
            "complete",
            "_offset_celsius",
            "PENDING",
            "COMPLETE",
            "kelvin",
        } <= member_names
        assert "celsius" not in member_names
        assert "validated_celsius" not in member_names
        assert "scale" not in member_names


def test_117_generates_text_call_caller_and_dependency_relations() -> None:
    """Enabled relationship features produce evidence, not merely settings."""
    # Capture result as the completed test 117 generates text call caller and dependency
    # Details: relations outcome for subsequent validation or publication.
    # Confine the acquired resource to this operation and release it on every exit.
    with _generated_probe() as result:
        # Retain the immutable source representation consumed by subsequent analysis.
        body = _html_text(result.output)
        assert "References" in body
        assert "Referenced by" in body
        assert "Here is the call graph" in body
        assert "Here is the caller graph" in body
        assert "Directory dependency graph" in body
        # Collect unique images element values; their order is deliberately unordered.
        images = {path.name for path in (result.output / "html").glob("*.svg")}
        # Normalize the current repository path to its portable baseline key spelling.
        assert any(name.endswith("_cgraph.svg") for name in images)
        # Normalize the current repository path to its portable baseline key spelling.
        assert any(name.endswith("_icgraph.svg") for name in images)
        # Normalize the current repository path to its portable baseline key spelling.
        assert any(name.endswith("_dep.svg") for name in images)


def test_117_generated_site_has_no_remote_runtime_dependency() -> None:
    """First view works offline and AUTO Mermaid's CDN string is absent."""
    # Capture result as the completed test 117 generated site has no remote runtime dependency
    # Details: outcome for subsequent validation or publication.
    # Confine the acquired resource to this operation and release it on every exit.
    with _generated_probe() as result:
        # Resolve the repository-confined path used by this operation before filesystem access.
        assets = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in (result.output / "html").rglob("*")
            if path.suffix in {".css", ".html", ".js", ".svg"}
        )
        assert "cdn.jsdelivr.net" not in assets
        assert not re.search(
            r"<(?:script|link|iframe)[^>]+(?:src|href)=\"https?://",
            assets,
            flags=re.IGNORECASE,
        )


def test_117_output_is_byte_deterministic_for_the_same_fixture() -> None:
    """Two clean generations have the same members and bytes."""

    def snapshot() -> dict[str, str]:
        """Hash the locally delivered HTML tree by relative identity.

        @return relative output-path keys mapped to SHA-256 digest strings;
            mapping key order is deliberately unused
        """
        # Capture result as the completed snapshot outcome for subsequent validation or
        # Details: publication.
        # Confine the acquired resource to this operation and release it on every exit.
        with _generated_probe(extra_configuration="") as result:
            # Resolve the repository-confined path used by this operation before filesystem
            # Details: access.
            # Return the completed snapshot result to its caller.
            return {
                path.relative_to(result.output / "html").as_posix(): sha256(
                    path.read_bytes(),
                ).hexdigest()
                for path in (result.output / "html").rglob("*")
                if path.is_file()
            }

    assert snapshot() == snapshot()


def test_117_warns_about_an_undocumented_element(tmp_path: Path) -> None:
    """`WARN_IF_UNDOCUMENTED` now finds a genuine missing function contract."""
    # Capture diagnostic, status as the completed test 117 warns about an undocumented element
    # Details: outcome for subsequent validation or publication.
    status, diagnostic = _run_inline_source(
        tmp_path,
        '"""! Probe module.\n@package probe\n"""\n\n'
        "def undocumented(value: int) -> int:\n"
        "    return value\n",
        "WARN_IF_UNDOCUMENTED=YES\nWARN_NO_PARAMDOC=NO\n",
    )
    assert status != 0
    assert "undocumented" in diagnostic


def test_117_no_longer_misattributes_a_documented_field_use(tmp_path: Path) -> None:
    """The 1.10 bare `self.field` false warning is fixed in 1.17."""
    # Capture diagnostic, status as the completed test 117 no longer misattributes a documented
    # Details: field use outcome for subsequent validation or publication.
    status, diagnostic = _run_inline_source(
        tmp_path,
        '"""! Probe module.\n@package probe\n"""\n\n'
        "from dataclasses import dataclass\n\n"
        "@dataclass\n"
        "class Item:\n"
        '    """! One item."""\n\n'
        "    ## Documented value.\n"
        "    bare: int = 1\n\n"
        "    def size(self) -> int:\n"
        '        """! Measure its text.\n'
        "        @return the text length\n"
        '        """\n'
        "        return len(str(self.bare))\n",
        "WARN_IF_UNDOCUMENTED=YES\nWARN_NO_PARAMDOC=NO\n",
    )
    assert status == 0, diagnostic


def test_117_still_misclassifies_none_as_a_return_value(tmp_path: Path) -> None:
    """`WARN_NO_PARAMDOC` remains unusable for annotated procedures."""
    # Capture diagnostic, status as the completed test 117 still misclassifies none as a return
    # Details: value outcome for subsequent validation or publication.
    status, diagnostic = _run_inline_source(
        tmp_path,
        '"""! Probe module.\n@package probe\n"""\n\n'
        "def consume(value: int) -> None:\n"
        '    """! Consume one value.\n'
        "    @param value value to consume\n"
        '    """\n'
        "    return None\n",
        "WARN_IF_UNDOCUMENTED=YES\nWARN_NO_PARAMDOC=YES\n",
    )
    assert status != 0
    assert "return type" in diagnostic


def test_117_still_rejects_a_code_span_ending_in_a_period(tmp_path: Path) -> None:
    """The reduced 1.10 markup defect remains present in 1.17."""
    # Capture diagnostic, status as the completed test 117 still rejects a code span ending in a
    # Details: period outcome for subsequent validation or publication.
    status, diagnostic = _run_inline_source(
        tmp_path,
        '"""! Probe module.\n@package probe\n"""\n\n'
        "def name() -> str:\n"
        '    """! Return `thing.` safely.\n'
        "    @return the name\n"
        '    """\n'
        '    return "thing"\n',
        "WARN_IF_UNDOCUMENTED=YES\nWARN_NO_PARAMDOC=NO\n",
    )
    assert status != 0
    assert "end of comment block" in diagnostic
