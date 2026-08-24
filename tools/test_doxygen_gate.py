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
    # Use the qualified executable and canonical probe; callers own only the bounded output.
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
    # Each included path is an entity/index page; page order is irrelevant to text membership.
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
    Writes only pytest-owned source projections used to exercise Doxygen gate failures.
    """
    # Confine the reduced Doxygen project and generated output to this test directory.
    root = tmp_path / "inline"
    # Create the canonical source root expected by the production configuration.
    (root / "src").mkdir(parents=True)
    # Materialize exactly the caller-supplied Python behavior probe.
    (root / "src" / "probe.py").write_text(source, encoding="utf-8")
    assert _DOXYGEN is not None
    # Keep generated output alive only long enough to capture status and diagnostics.
    with doxygen_gate.generated(
        _DOXYGEN,
        root,
        extra_configuration=settings,
    ) as result:
        # Preserve native status and both diagnostic streams before temporary output is removed.
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
    # Select an isolated writable destination for negative mutations of the reference package.
    destination = tmp_path / "reference"
    shutil.copytree(doxygen_gate.DEFAULT_ROOT, destination,
                    ignore=shutil.ignore_patterns("__pycache__", "build",
                                                  ".pytest_cache", ".mypy_cache"))
    # Return the copied repository root consumed by the gate.
    return destination


def test_the_reference_generates_cleanly() -> None:
    """The positive case, asserted first.

    A gate that failed on the conformant package would make every negative below
    meaningless, and would be reporting the fixture rather than the rule.
    """
    # The verdict and its diagnostic jointly define the positive reference result.
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
    Writes only pytest-owned source projections used to exercise Doxygen gate failures.
    """
    # Retain the exact original module so only one nonexistent parameter is introduced.
    plan = tree / "src" / "refpkg" / "domain" / "plan.py"
    original = plan.read_text(encoding="utf-8")
    target = (
        "    @param entries each file under consideration; input order is "
        "deliberately irrelevant"
    )
    assert target in original
    plan.write_text(
        original.replace(
            target,
            target + "\n    @param ghost a parameter this function does not have",
            1,
        ),
        encoding="utf-8",
    )
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
    Writes only pytest-owned source projections used to exercise Doxygen gate failures.
    """
    # Supply the expected source directory but deliberately no documentable files.
    (tmp_path / "src").mkdir()
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
    Writes only pytest-owned source projections used to exercise Doxygen gate failures.
    """
    # Give the synthetic generator a valid project root while its relation counts are patched.
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
        # Model a successful native process independently from the missing caller relation.
        finished = subprocess.CompletedProcess(("doxygen", "-"), 0, "", "")
        yield doxygen_gate.GeneratedDocumentation(
            finished=finished,
            output=tmp_path,
            source_pages=doxygen_gate.MINIMUM_FILES,
            relation_graphs=(1, 0, 1),
        )

    monkeypatch.setattr(doxygen_gate, "locate_native", lambda _name: "doxygen")
    monkeypatch.setattr(doxygen_gate, "generated", relationless)
    # This verdict isolates a missing caller graph from otherwise non-vacuous output.
    status, line = doxygen_gate.run(tmp_path, doxygen_gate.MINIMUM_FILES)

    assert status == doxygen_gate.EXIT_FAILED
    assert "caller relationship graph" in line


def test_no_src_is_refused_rather_than_passed(tmp_path: Path) -> None:
    """A tree with nothing to document is a caller error, not a clean run.

    @param tmp_path the fixture directory
    """
    # Capture only the verdict because this caller-error test is wording-independent.
    status, _ = doxygen_gate.run(tmp_path, doxygen_gate.MINIMUM_FILES)
    assert status == doxygen_gate.EXIT_FAILED


def test_the_run_leaves_the_fixture_untouched() -> None:
    """The gate writes 235 files, and none of them into the reference.

    `OUTPUT_DIRECTORY` is overridden through stdin precisely so build products do
    not land in `enforce/fixtures/reference/`, where `broken_copy` would duplicate
    them into every mutation and the release would have to prune them.
    """
    # Collect unique before element values; their order is deliberately unordered.
    # Each set element is one pre-run fixture child name; ordering is deliberately irrelevant.
    before = {p.name for p in doxygen_gate.DEFAULT_ROOT.iterdir()}
    doxygen_gate.run(doxygen_gate.DEFAULT_ROOT, doxygen_gate.MINIMUM_FILES)
    assert {p.name for p in doxygen_gate.DEFAULT_ROOT.iterdir()} == before, (
        "the documentation run left build products in the fixture"
    )


def test_an_undocumented_function_is_caught_here(tree: Path) -> None:
    """The 1.17 gate again rejects a representable entity without a contract.

    @param tree a writable copy of the reference

    @par Effects
    Writes only pytest-owned source projections used to exercise Doxygen gate failures.
    """
    # Append one representable function without a contract to an otherwise conformant module.
    model = tree / "src" / "refpkg" / "domain" / "model.py"
    model.write_text(
        model.read_text(encoding="utf-8")
        + "\n\ndef undocumented(value: int) -> int:\n    return value\n",
        encoding="utf-8",
    )
    status, line = doxygen_gate.run(tree, doxygen_gate.MINIMUM_FILES)
    assert status == doxygen_gate.EXIT_FAILED
    assert "undocumented" in line


def test_117_projects_supported_python_entities_and_contract_commands() -> None:
    """The exact target reads both comment forms and every required command."""
    # Keep generated output alive while checking entity prose and contract-section projection.
    with _generated_probe() as result:
        assert result.finished.returncode == 0, result.finished.stderr
        # Retain the immutable source representation consumed by subsequent analysis.
        body = _html_text(result.output)
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
    # Inspect XML member identities while the qualified probe output exists.
    with _generated_probe() as result:
        # Collect unique member names element values; their order is deliberately unordered.
        member_names: set[str] = set()
        for path in (result.output / "xml").glob("*.xml"):
            # Each document contributes exact extracted member names to the unordered census.
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
    # Inspect relation prose and graph artifacts within one bounded qualified generation.
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
        assert any(name.endswith("_cgraph.svg") for name in images)
        assert any(name.endswith("_icgraph.svg") for name in images)
        assert any(name.endswith("_dep.svg") for name in images)


def test_117_generated_site_has_no_remote_runtime_dependency() -> None:
    """First view works offline and AUTO Mermaid's CDN string is absent."""
    # Search every locally delivered runtime asset before the temporary site is removed.
    with _generated_probe() as result:
        # Each asset contributes decoded CSS, HTML, JavaScript, or SVG text; recursive path order
        # is deliberately irrelevant because the joined body is searched only for remote URLs.
        assets = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            # Each path is one locally generated runtime asset selected by its suffix.
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
        # Hash each generated file while its temporary output tree remains available.
        with _generated_probe(extra_configuration="") as result:
            # Each key is a relative file identity mapped to its digest; mapping order is unused.
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
    # Capture the reduced probe verdict and diagnostic for the missing-contract behavior.
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
    # Exercise the prior false-positive shape against the exact qualified version.
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
    # Preserve the known false-positive verdict that keeps this warning class disabled.
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
    # Preserve the known parser-defect verdict used by documentation wording guidance.
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
