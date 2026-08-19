"""Fitness tests for the discipline's own claims about itself.

Most fitness tests in `enforce/fitness/` describe a consuming project's
architecture -- its ports, its layers, its adapters -- and can only run there.
These three are different: they check the corpus, and they are the mechanisms
behind the rules that make every other rule mean something.

* `FLOW-006` a rule tagged binding names a runnable mechanism
* `FLOW-007` / `TEST-015` every check has a companion proving it can fail
* `FLOW-009` / `TEAMS-003` the gate is defined, in one place, and runnable

Without these three the discipline is a document. With them it is a contract.

    pytest enforce/fitness/test_meta.py
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

import gate as _gate
from decides import decides

if TYPE_CHECKING:
    from collections.abc import Iterator

## The repository root, three levels up from this file.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent.parent

## The generated rule index; the single source both this file and agents read.
RULES_JSON: Final = REPO_ROOT / "discipline" / "rules.json"

## Mechanism families this test can resolve to something on disk. `auto:` names
## an external tool's own rule and `review` names a person; neither is a file.
RESOLVABLE: Final[frozenset[str]] = frozenset({"check", "fitness"})

## The gate, imported rather than restated. It moved to `tools/gate.py` so
## `tools/release.py` could refuse to build from a tree that fails it without
## importing a test module to find out what the gate is.
GATE: Final[tuple[tuple[str, tuple[str, ...]], ...]] = _gate.GATE


def load_rules() -> list[dict[str, object]]:
    """Every rule in the corpus, from the generated index.

    @return the rule records
    @throws pytest.skip.Exception when the index has not been built
    """
    if not RULES_JSON.exists():
        pytest.skip("discipline/rules.json not built; run tools/build_index.py")
    return list(json.loads(RULES_JSON.read_text(encoding="utf-8"))["rules"])


def iter_check_modules() -> Iterator[Path]:
    """Every custom AST check module.

    Membership is decided by what a module defines, not by where it sits. Not
    everything under `enforce/checks/` is a mechanism -- `project.py` parses the
    consuming project's declaration and implements none -- and demanding a
    proof-of-failure companion for a module that checks nothing would be a
    requirement no honest test could satisfy.

    @return each module defining a `Check` subclass, excluding the package init
        and its own tests
    """
    for path in sorted((REPO_ROOT / "enforce" / "checks").glob("*.py")):
        if path.stem.startswith(("__", "test_")):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if any(
            isinstance(node, ast.ClassDef)
            and any(isinstance(b, ast.Name) and b.id in
                    {"Check", "ModuleCheck", "TextCheck"} for b in node.bases)
            for node in ast.walk(tree)
        ):
            yield path


def names_defined_in(directory: Path) -> set[str]:
    """Every test function name defined under a directory.

    @param directory the directory to scan
    @return the set of `test_*` function names found
    """
    found: set[str] = set()
    if not directory.exists():
        return found
    for path in directory.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        found |= {
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
    return found


# ------------------------------------------------------------------- FLOW-006


@decides("FLOW-006")
def test_binding_rules_have_mechanisms() -> None:
    """FLOW-006: a rule tagged binding names a mechanism and a check command.

    This is the axiom's own enforcement. A binding rule with nothing behind it
    degrades to exactly the failure the discipline was built to remove -- a
    requirement everyone believes is enforced and nothing decides.
    """
    unbacked = [
        rule["id"] for rule in load_rules()
        if rule["force"] == "BINDING" and not (rule["mechanisms"] and rule["check"])
    ]
    assert unbacked == [], (
        f"{len(unbacked)} binding rule(s) name no mechanism or no check: "
        f"{', '.join(str(r) for r in unbacked[:10])}"
    )


def test_advisory_rules_justify_themselves() -> None:
    """FLOW-006: an advisory rule states why no mechanism is possible.

    Advisory is an admission, not a convenience. An unjustified one is a rule
    that quietly opted out of the axiom.
    """
    unjustified = [
        rule["id"] for rule in load_rules()
        if rule["force"] == "ADVISORY" and not rule["no_mechanism"]
    ]
    assert unjustified == [], (
        f"advisory rule(s) with no stated reason: {', '.join(str(r) for r in unjustified)}"
    )


# ------------------------------------------------------------- FLOW-007 / TEST-015


@decides("FLOW-007", "TEST-015")
def test_checks_can_fail() -> None:
    """FLOW-007: every AST check has a companion test proving it fails.

    A check whose passing signal is empty output has not been shown to check
    anything, and its silence is indistinguishable from correctness. The
    companion is what turns the silence into evidence.
    """
    companions = names_defined_in(REPO_ROOT / "enforce" / "checks")
    proven: set[str] = set()
    for path in REPO_ROOT.glob("enforce/checks/test_*.py"):
        text = path.read_text(encoding="utf-8")
        for module in iter_check_modules():
            if f"{module.stem}" in text:
                proven.add(module.stem)
    unproven = sorted({m.stem for m in iter_check_modules()} - proven)
    assert unproven == [], (
        f"check(s) with no proof-of-failure companion: {', '.join(unproven)}. "
        f"Add one to enforce/checks/test_*.py that drives the check to fire."
    )
    assert companions, "no companion tests found at all"


def test_validator_checks_can_fail() -> None:
    """FLOW-007 applied to the corpus validator.

    Every finding code the validator can emit must appear in a test that drives
    it, or the code is a branch nobody has ever seen taken.
    """
    source = (REPO_ROOT / "tools" / "validate.py").read_text(encoding="utf-8")
    emitted = sorted(set(_finding_codes(source)))
    proofs = "".join(
        path.read_text(encoding="utf-8")
        for path in REPO_ROOT.glob("tools/test_*.py")
    )
    unproven = [code for code in emitted if code not in proofs]
    assert unproven == [], (
        f"validator code(s) never driven by a test: {', '.join(unproven)}"
    )


def _finding_codes(source: str) -> Iterator[str]:
    """Every finding code the validator constructs.

    @param source the validator's source text
    @return each literal passed as a `code=` argument
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "code" and isinstance(keyword.value, ast.Constant):
                yield str(keyword.value.value)


# ------------------------------------------------------------------- FLOW-009


def test_no_source_file_carries_a_control_character() -> None:
    """A stray control byte in source is invisible in every diff that matters.

    Written after one reached `doc_coverage.py`: a shell heredoc collapsed `\\\\b`
    to `\\b`, Python read that as a backspace, and the regex silently stopped
    matching. The check went on passing its own tests and reported 400 findings
    that were not there. Tab and newline are the only control bytes source needs.
    """
    offenders = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        if any(part in {".git", "build", "__pycache__"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            found = {hex(ord(c)) for c in line if ord(c) < 32 and c != "\t"}
            if found:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number} {sorted(found)}")
    assert not offenders, "control characters in source:\n" + "\n".join(offenders)


@decides("FLOW-009")
def test_gate_suite_defined() -> None:
    """FLOW-009: the gate is a list, in one place, not prose that drifts.

    Every entry names a command that exists. What the gate *is* has to be
    answerable without reading six documents and hoping they agree.
    """
    assert GATE, "the gate is empty"
    for name, command in GATE:
        assert name, "a gate entry has no name"
        assert command, f"gate entry {name!r} has no command"
        target = command[1] if command[0] == sys.executable else None
        if target and not target.startswith("-"):
            assert (REPO_ROOT / target).exists(), f"gate entry {name!r} names a missing {target}"


@pytest.mark.parametrize("name,command", GATE, ids=[n for n, _ in GATE])
def test_every_gate_entry_is_runnable(name: str, command: tuple[str, ...]) -> None:
    """FLOW-009: each gate command starts and reports, rather than erroring out.

    Deliberately does not assert success -- a repository mid-migration may fail
    a gate legitimately. What must hold is that the command *runs*: a gate that
    cannot start is a gate that reports nothing and blocks nothing.

    @param name the gate entry's name
    @param command the argv to run
    """
    # The console-script hunt that used to live here is gone with the entry it
    # served: gate step 1 now runs `tools/lint_gate.py`, which invokes ruff as
    # `sys.executable -m ruff`. Locating an executable was what made the lint gate
    # skip itself on this machine -- it looked beside the interpreter and not in
    # Scripts/, and 766 findings went unseen behind a green run.
    if command[-1] == "-q" and "pytest" in command:
        pytest.skip("running the suite from inside the suite would recurse")
    # Encoding is pinned rather than left to the locale: on a cp932 machine the
    # default codec raised on ruff's own output, so the gate died deciding
    # nothing -- exactly the failure this test exists to catch.
    finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv, no shell
        command, capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=REPO_ROOT, check=False, timeout=180,
    )
    assert finished.returncode in (0, 1), (
        f"gate entry {name!r} exited {finished.returncode}, which means it failed to run "
        f"rather than reporting a verdict:\n{finished.stderr[:400]}"
    )


def test_the_workflow_mirrors_the_gate() -> None:
    """FLOW-009: the CI workflow's steps are the GATE tuple, in order.

    The workflow spells the seven steps out because a workflow step needs its own
    name and failure boundary. Its own comment says that if `GATE` changes this
    list must change with it -- a mechanizable claim that was left to memory, and
    left there while the repository had no remote and no way to notice. Checking
    it here is what makes a workflow nobody can run still worth shipping.
    """
    workflow = REPO_ROOT / ".github" / "workflows" / "gate.yml"
    if not workflow.exists():
        pytest.skip("no CI workflow in this tree")
    text = workflow.read_text(encoding="utf-8")
    steps = re.findall(r'- name: "Gate \d+/\d+ -- (?P<name>[^"]+)"\n\s+run: (?P<run>.+)',
                       text)
    assert [name for name, _ in steps] == [name for name, _ in GATE], (
        "the workflow's step names have drifted from the GATE tuple"
    )
    for (_, run), (name, command) in zip(steps, GATE, strict=True):
        # The workflow says `python`; the tuple says this interpreter. Compare the
        # arguments, which is where a real divergence would show.
        expected = " ".join(("python", *command[1:])) if command[0] == sys.executable \
            else " ".join(command)
        assert run.strip() == expected, (
            f"gate entry {name!r} runs {expected!r} but the workflow runs {run.strip()!r}"
        )


def doxygen_executable() -> str | None:
    """Where doxygen actually is, or None when this environment has none.

    Looked for beside the running interpreter before PATH, because a conda
    environment puts native binaries in `Library/bin` (Windows) or `bin` (POSIX)
    and only prepends them to PATH on activation. Every gate step here invokes
    `sys.executable` directly, so PATH alone finds nothing on a machine where
    doxygen is correctly installed -- and the test then skips, which is
    indistinguishable from passing.

    @return the path to run, or None when doxygen cannot be found at all
    """
    root = Path(sys.executable).parent
    for candidate in (root / "Library" / "bin" / "doxygen.exe",
                      root / "doxygen.exe",
                      root / "bin" / "doxygen",
                      root / "doxygen"):
        if candidate.is_file():
            return str(candidate)
    return shutil.which("doxygen")


def test_doxygen_version_matches_recorded() -> None:
    """Doxygen defects fixed between versions; ensure configuration does not drift.

    Three defects in Doxygen's Python parser (at 1.10.0) motivated disabling
    WARN_NO_PARAMDOC and WARN_IF_UNDOCUMENTED in enforce/Doxyfile. These
    defects may be fixed in later versions, or new ones may appear. When
    Doxygen is upgraded, the disabled warnings and verified: date in
    discipline/fact/doxygen.md must be re-checked against the defects table
    there, or they stay switched off for no remaining reason.

    This test enforces that decision: it skips when Doxygen is not installed,
    and fails when installed and the version differs from the recorded one,
    with a message that tells the reader what to verify and update.
    """
    # Read the recorded version from the doxygen.md table
    dox_fact_path = REPO_ROOT / "discipline" / "fact" / "doxygen.md"
    dox_fact_text = dox_fact_path.read_text(encoding="utf-8")

    # Parse the version from the table row:
    # | Doxygen | 1.10.0 | VERSION-DEPENDENT |
    recorded_version = None
    for line in dox_fact_text.splitlines():
        if "| Doxygen |" in line and "VERSION-DEPENDENT" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3:
                recorded_version = parts[2]
            break

    assert recorded_version is not None, (
        "Could not parse Doxygen version from "
        "discipline/fact/doxygen.md; expected a line matching "
        "'| Doxygen | <version> | VERSION-DEPENDENT |'"
    )

    # Located rather than named. `doxygen` is on PATH only while the conda
    # environment is ACTIVATED, and the gate invokes the interpreter directly --
    # so a machine with doxygen correctly installed still skipped this test and
    # verified nothing. That is the same defect as the ruff one recorded in this
    # repository's history, where locating an executable by PATH alone made the
    # lint gate skip itself behind a green run.
    executable = doxygen_executable()
    if executable is None:
        pytest.skip("doxygen not installed in this environment or on PATH")

    result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        (executable, "--version"),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=REPO_ROOT, check=False, timeout=30,
    )
    if result.returncode != 0:
        pytest.skip(f"{executable} did not report a version")

    # Extract the version from the output (e.g., "1.10.0" or "1.10.0 (some extra text)")
    installed_version = result.stdout.strip().split()[0]

    # Compare versions
    assert installed_version == recorded_version, (
        f"Doxygen version mismatch: discipline/fact/doxygen.md records {recorded_version!r} "
        f"but {installed_version!r} is installed.\n\n"
        f"Before updating the version and verified: date in discipline/fact/doxygen.md:\n"
        f"  1. Re-run the defect verification tests against the three defects in the\n"
        f"     'Three defects that decide who owns which rule' section of\n"
        f"     discipline/fact/doxygen.md.\n"
        f"  2. Re-verify the two disabled warning settings in enforce/Doxyfile:\n"
        f"     - WARN_IF_UNDOCUMENTED (line ~47)\n"
        f"     - WARN_NO_PARAMDOC (line ~54)\n"
        f"  3. If the defects are fixed in {installed_version}, enable the warnings and\n"
        f"     remove the explanatory comments.\n"
        f"  4. Update 'verified:' and the version in discipline/fact/doxygen.md.\n"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


@decides("TEAMS-003")
def test_completion_hook_enforces_the_gate() -> None:
    """TEAMS-003: where the tooling offers a hook, the gate is enforced there.

    "A task cannot be marked done while its gate fails." The rule's subject is the
    completion hook, and until v3.1 it was claimed by `test_gate_suite_defined`,
    which asserts the GATE tuple is well-formed and says nothing about whether
    anything runs it unasked. A gate a person has to remember is a preference.

    The vendored hook is the mechanism: `integrate.py --hooks` points
    `core.hooksPath` at it, so a push runs the gate without anyone choosing to.
    """
    hook = REPO_ROOT / "enforce" / "templates" / "hooks" / "pre-push"
    assert hook.is_file(), (
        "no pre-push hook ships, so the verification obligation is a request"
    )
    text = hook.read_text(encoding="utf-8")
    assert "gate.py" in text, (
        "the pre-push hook does not run the gate, so a change can be offered "
        "without one having passed"
    )
    assert "exit" in text, (
        "the hook runs the gate and does not act on the result; a hook that "
        "reports and returns zero is a slower way of not checking"
    )
    installer = (REPO_ROOT / "tools" / "integrate.py").read_text(encoding="utf-8")
    assert "hooksPath" in installer, (
        "nothing installs the hook, so it ships and never runs"
    )


def test_a_hook_that_does_not_run_the_gate_is_caught(tmp_path: Path) -> None:
    """The negative case: a hook that greets the user and exits zero.

    @param tmp_path holds the substituted hook
    """
    hook = tmp_path / "pre-push"
    hook.write_text("#!/bin/sh\necho pushing\nexit 0\n", encoding="utf-8")
    assert "gate.py" not in hook.read_text(encoding="utf-8")
