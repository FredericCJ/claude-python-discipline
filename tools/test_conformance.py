"""The adopter ratchet is watched refusing in each of the ways it must.

**Oracle: differential.** A tree of known conformance is judged against a
baseline of known content, and the verdict compared.

The property that matters is not that a baselined tree goes green -- that is easy
and would be satisfied by a file containing the word "yes". It is that a baselined
tree **still fails on the next regression**, in both directions the baseline can
be fooled: a new `(file, rule)` pair, and an existing rule gaining instances in a
file that already had one.

Above both sits `PROTECTED`, which no baseline may cover at all.

    pytest tools/test_conformance.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import conformance
from checks import Finding, project
from checks.__main__ import discover

if TYPE_CHECKING:
    import pytest

## A module violating DOC-001: a public function with no documentation at all.
## Chosen because DOC-001 is NOT protected, so it can legitimately be baselined --
## which is what most of these tests need to exercise.
UNDOCUMENTED = "def widget(value):\n    return value\n"

## A second, different undocumented function, for raising the count inside a file
## the baseline already covers.
UNDOCUMENTED_TWICE = (
    "def widget(value):\n    return value\n\n\n"
    "def gadget(value):\n    return value\n"
)


def tree(root: Path, **modules: str) -> Path:
    """Build a scratch project with the given modules under `src/`.

    @param root the directory to build in
    @param modules file stem to source, written under `src/`
    @return the project root
    """
    source = root / "src"
    source.mkdir(parents=True, exist_ok=True)
    for stem, body in modules.items():
        (source / f"{stem}.py").write_text(body, encoding="utf-8")
    return root


def judge(root: Path) -> int:
    """Run the ratchet over a scratch project.

    @param root the project root
    @return the exit status
    """
    return conformance.main(["--root", str(root), str(root / "src")])


def accept(root: Path, why: str = "adoption") -> int:
    """Record the current findings as the accepted floor.

    @param root the project root
    @param why the reason written into the baseline
    @return the exit status
    """
    return conformance.main(
        ["--root", str(root), str(root / "src"), "--update-baseline", "--why", why]
    )


def test_a_clean_tree_passes_without_a_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A greenfield project needs no baseline and must not be asked for one.

    @param tmp_path the scratch directory
    """
    root = tree(tmp_path, widget='"""A module."""\n')
    monkeypatch.setattr(conformance, "findings_for", lambda _paths: [])
    assert judge(root) == conformance.EXIT_OK


def test_project_declaration_reaches_every_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The migration ratchet evaluates checks under the adopter's v5 declaration.

    @param tmp_path scratch repository
    @param monkeypatch substitutes one declaration-observing check
    """
    root = tree(tmp_path, widget='"""A module."""\n')
    declaration = root / "pyproject.toml"
    declaration.write_text(
        "[tool.agent-discipline]\n"
        'unit = "application"\n'
        'source_roots = ["src"]\n'
        'architecture = "architecture.json"\n'
        'contract_conformance = "contract-conformance.json"\n'
        'operational_model = "operational-model.json"\n'
        'security_model = "security-model.json"\n'
        'adversarial_review = "adversarial-review.json"\n'
        'doc_engine = "doxygen"\n'
        'documentation_model = "documentation-model.json"\n\n'
        "[tool.agent-discipline.capabilities]\n"
        "public_api = false\nfilesystem_io = false\npersistent_state = false\n"
        "generated_artifacts = false\nnetwork_io = false\n"
        "launches_subprocesses = false\nowns_subprocess_lifecycle = false\n"
        "concurrency = false\ndestructive_effects = false\n"
        "bounded_latency = false\nsensitive_data = false\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "documentation-model.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "engine": "doxygen",
                "scopes": [
                    {"path": "src", "kind": "production", "ownership": "governed"}
                ],
                "controlled_abbreviations": [],
                "identifier_grammars": [],
                "generated_names": {"markers": ["generated", "derived"], "mappings": {}},
                "semantic_properties": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class DeclarationProbe:
        """One check that records the declaration supplied by conformance."""

        ## Declaration installed by the migration ratchet before the check runs.
        declaration = project.DEFAULT

        def run(self, _paths: list[Path]) -> list[Finding]:
            """Require the parsed declaration at the check boundary.

            @param _paths governed source paths, unused by this declaration probe
            @return no findings after the assertion succeeds
            """
            assert self.declaration.source == declaration.resolve()
            return []

    monkeypatch.setattr(conformance, "discover", lambda: [DeclarationProbe()])
    assert conformance.findings_for([root / "src"]) == []


def test_an_unbaselined_finding_fails(tmp_path: Path) -> None:
    """No baseline means no ratchet yet, never zero findings.

    `enforce/templates/allocation.toml` shipped a value that resolved, so copying
    the template and changing nothing satisfied the rule. Silence must not read
    as consent here either.

    @param tmp_path the scratch directory
    """
    root = tree(tmp_path, widget=UNDOCUMENTED)
    assert judge(root) == conformance.EXIT_REGRESSED


def test_a_baselined_tree_goes_green(tmp_path: Path) -> None:
    """The property that makes adoption possible at all.

    Asserted before every refusal below, because a ratchet that fails on an
    accepted tree is not stricter, it is broken.

    @param tmp_path the scratch directory
    """
    root = tree(tmp_path, widget=UNDOCUMENTED)
    assert accept(root) == conformance.EXIT_OK
    assert (root / conformance.BASELINE_NAME).is_file()
    assert judge(root) == conformance.EXIT_OK


def test_a_new_file_with_the_same_rule_still_fails(tmp_path: Path) -> None:
    """The first way a baseline can be fooled: a new `(file, rule)` pair.

    @param tmp_path the scratch directory
    """
    root = tree(tmp_path, widget=UNDOCUMENTED)
    assert accept(root) == conformance.EXIT_OK
    (root / "src" / "gadget.py").write_text(UNDOCUMENTED, encoding="utf-8")
    assert judge(root) == conformance.EXIT_REGRESSED


def test_more_of_the_same_rule_in_a_baselined_file_still_fails(
    tmp_path: Path,
) -> None:
    """The second way, and the one pairs alone would miss.

    The new finding is in a file the baseline already covers, under a rule the
    baseline already accepts, so the pair set does not change. Only the count
    catches it -- which is exactly why `lint_gate` records both.

    @param tmp_path the scratch directory
    """
    root = tree(tmp_path, widget=UNDOCUMENTED)
    assert accept(root) == conformance.EXIT_OK
    (root / "src" / "widget.py").write_text(UNDOCUMENTED_TWICE, encoding="utf-8")
    assert judge(root) == conformance.EXIT_REGRESSED


def test_clearing_a_finding_does_not_fail(tmp_path: Path) -> None:
    """The ratchet may fall freely; that is the direction it exists to allow.

    @param tmp_path the scratch directory
    """
    root = tree(tmp_path, widget=UNDOCUMENTED_TWICE)
    assert accept(root) == conformance.EXIT_OK
    (root / "src" / "widget.py").write_text(UNDOCUMENTED, encoding="utf-8")
    assert judge(root) == conformance.EXIT_OK


def test_a_protected_rule_is_refused_before_the_baseline_is_read(
    tmp_path: Path,
) -> None:
    """No amount of ratcheting switches off a rule the Directive rests on.

    The baseline here explicitly lists the protected pair and claims a count that
    covers it. It is not consulted: `judge` evaluates `PROTECTED` first.

    @param tmp_path the scratch directory
    """
    root = tree(tmp_path)
    baseline = root / conformance.BASELINE_NAME
    baseline.parent.mkdir(parents=True, exist_ok=True)
    protected = min(conformance.PROTECTED)
    baseline.write_text(
        json.dumps({"count": 99, "pairs": [["src/widget.py", protected]]}),
        encoding="utf-8",
    )
    finding = Finding(
        rule_id=protected, path=root / "src" / "widget.py", line=1,
        message="a protected rule was violated",
        remediation="fix it; it cannot be baselined",
    )
    complaints = conformance.judge([finding], root,
                                   conformance.load_baseline(baseline))
    assert complaints
    assert "protected" in complaints[0]


def test_a_protected_violation_will_not_be_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--update-baseline` refuses to write a protected rule into the file.

    Recording one would make the refusal above unreachable forever after, which
    is how a guard stops guarding.

    @param tmp_path the scratch directory
    @param monkeypatch used to substitute what the checks report
    """
    root = tree(tmp_path)
    protected = min(conformance.PROTECTED)
    monkeypatch.setattr(conformance, "findings_for", lambda _paths: [
        Finding(
            rule_id=protected, path=root / "src" / "widget.py", line=1,
            message="a protected rule was violated",
            remediation="fix it; it cannot be baselined",
        )
    ])
    assert accept(root) == conformance.EXIT_REGRESSED
    assert not (root / conformance.BASELINE_NAME).exists()


def test_moving_the_baseline_requires_a_reason(tmp_path: Path) -> None:
    """A ratchet moved without a written reason is indistinguishable from drift.

    @param tmp_path the scratch directory
    """
    root = tree(tmp_path, widget=UNDOCUMENTED)
    assert conformance.main(["--root", str(root), "--update-baseline"]) == \
        conformance.EXIT_REGRESSED
    assert not (root / conformance.BASELINE_NAME).exists()


def test_the_baseline_lives_where_vendoring_will_not_touch_it() -> None:
    """The property the whole design rests on, asserted rather than assumed.

    `vendor.py` copies `discipline/`, `enforce/` and `tools/`. If the baseline
    ever moved under one of them, every upgrade would silently reset what the
    adopter had accepted, and the next upgrade would be declined.
    """
    assert conformance.BASELINE_NAME.startswith("overrides/")
    vendor = (Path(__file__).resolve().parent / "vendor.py").read_text(
        encoding="utf-8")
    assert "overrides" not in vendor.split("UPSTREAM")[-1][:400]


def test_an_unreadable_baseline_is_treated_as_absent(tmp_path: Path) -> None:
    """A corrupt baseline must report everything, never pass silently.

    The failure mode being avoided is a truncated write leaving a file that
    parses as nothing and reads as consent.

    @param tmp_path the scratch directory
    """
    root = tree(tmp_path, widget=UNDOCUMENTED)
    baseline = root / conformance.BASELINE_NAME
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_text("{ not json", encoding="utf-8")
    assert conformance.load_baseline(baseline) is None
    assert judge(root) == conformance.EXIT_REGRESSED


def test_every_protected_rule_is_reportable() -> None:
    """A guard naming a rule this tool cannot report can never fire.

    `DIAG-001` and `ERR-008` were both in `PROTECTED` when it was written. Neither
    is decided by an AST check -- `DIAG-001` by a fitness test, `ERR-008` by a ruff
    code -- so `conformance.py`, which runs only the checks, would never have seen
    either. Two of the four guards were inert, which is precisely the vacuity this
    repository exists to remove, reproduced inside the guard against it.
    """
    reportable = {rule for check in discover() for rule in check.rules}
    unreportable = sorted(conformance.PROTECTED - reportable)
    assert not unreportable, (
        f"{', '.join(unreportable)} cannot be reported by any AST check, so "
        f"protecting {'them' if len(unreportable) > 1 else 'it'} guards nothing"
    )


def test_the_report_names_a_concrete_next_target(tmp_path: Path) -> None:
    """Adoption stalls when a thousand findings look like one wall.

    @param tmp_path the scratch directory
    """
    root = tree(tmp_path, widget=UNDOCUMENTED, gadget=UNDOCUMENTED)
    rendered = conformance.render_report(
        conformance.findings_for([root / "src"]), root, None)
    assert "cheapest next target" in rendered
    assert "no baseline recorded" in rendered


if __name__ == "__main__":
    raise SystemExit(sys.exit(0))
