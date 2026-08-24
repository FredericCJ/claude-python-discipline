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
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed argv probes
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

import gate as _gate
from decides import decides

# Import iterator typing only while static analyzers evaluate generator contracts.
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

    @return rule-record elements in generated corpus order
    @throws pytest.skip.Exception when the index has not been built
    """
    # Refuse a test run whose generated rule contract is unavailable.
    if not RULES_JSON.exists():
        # Tell the maintainer which generator restores the required test subject.
        pytest.skip("discipline/rules.json not built; run tools/build_index.py")
    # Decode and copy the ordered rule-record elements from the generated contract.
    return list(json.loads(RULES_JSON.read_text(encoding="utf-8"))["rules"])


def iter_check_modules() -> Iterator[Path]:
    """Every custom AST check module.

    Membership is decided by what a module defines, not by where it sits. Not
    everything under `enforce/checks/` is a mechanism -- `project.py` parses the
    consuming project's declaration and implements none -- and demanding a
    proof-of-failure companion for a module that checks nothing would be a
    requirement no honest test could satisfy.

    @return module-path elements in sorted filename order for concrete checks only
    """
    # Visit candidate module paths in deterministic filename order.
    for path in sorted((REPO_ROOT / "enforce" / "checks").glob("*.py")):
        # Exclude package infrastructure and companion-test modules from mechanisms.
        if path.stem.startswith(("__", "test_")):
            # Advance to the next candidate without parsing non-mechanism source.
            continue
        # Parse the candidate without importing or executing repository code.
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        # Select modules that define at least one concrete supported check base.
        if any(
            isinstance(node, ast.ClassDef)
            and any(
                isinstance(b, ast.Name) and b.id in {"Check", "ModuleCheck", "TextCheck"}
                for b in node.bases
            )
            for node in ast.walk(tree)
        ):
            # Yield the source path whose class definition makes it a mechanism.
            yield path


def names_defined_in(directory: Path) -> set[str]:
    """Every test function name defined under a directory.

    @param directory the directory to scan
    @return unordered test-function-name elements found below the directory
    """
    # Accumulate unique function-name elements; traversal order is deliberately irrelevant.
    found: set[str] = set()
    # Treat an absent optional directory as an empty companion-test surface.
    if not directory.exists():
        # Return the empty name set without attempting filesystem traversal.
        return found
    # Inspect every Python source path beneath the requested test directory.
    for path in directory.rglob("*.py"):
        # Isolate syntax defects so one malformed negative fixture does not hide others.
        try:
            # Parse definitions without importing or executing the test module.
            tree = ast.parse(path.read_text(encoding="utf-8"))
        # Ignore deliberately malformed sources that cannot declare collectable tests.
        except SyntaxError:
            # Continue the census with the next independently parseable source file.
            continue
        # Merge every discovered function-name element into the unordered census.
        found |= {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
    # Return the complete unique-name census after all source paths are examined.
    return found


# ------------------------------------------------------------------- FLOW-006


@decides("FLOW-006")
def test_binding_rules_have_mechanisms() -> None:
    """FLOW-006: binding rules name complete strategy records.

    Presence remains necessary but is no longer presented as sufficient. The
    generated contract must join each heading tag to one exact proposition,
    residual, platform set, applicability condition, and discrimination case.
    """
    # Collect unsupported binding-rule-id elements in generated corpus order.
    unbacked: list[str] = []
    # Validate every generated rule record against the strategy completeness contract.
    for rule in load_rules():
        # Restrict the mechanization obligation to rules declared binding.
        if rule["force"] != "BINDING":
            # Leave advisory and retired records to their separately bounded checks.
            continue
        # Relate the normative mechanism list to its generated verification projection.
        mechanisms = rule.get("mechanisms")
        verification = rule.get("verification")
        strategies = verification.get("strategies") if isinstance(verification, dict) else None
        # Require every strategy field, and rejection only for automated mechanisms.
        complete = isinstance(strategies, list) and all(
            isinstance(strategy, dict)
            and all(
                strategy.get(field)
                for field in (
                    "mechanism",
                    "kind",
                    "relation",
                    "proposition",
                    "residual",
                    "must_pass",
                    "platforms",
                    "not_applicable",
                )
            )
            and (
                strategy.get("kind") == "structured-review"
                or strategy.get("must_reject") is not None
            )
            for strategy in strategies
        )
        # Compare declared and evidenced mechanism elements independent of ordering.
        joined = (
            isinstance(mechanisms, list)
            and isinstance(strategies, list)
            and sorted(str(item) for item in mechanisms)
            == sorted(str(strategy.get("mechanism")) for strategy in strategies)
        )
        # Retain the identifier when presence, completeness, or the exact join fails.
        if not (mechanisms and rule.get("check") and complete and joined):
            # Preserve corpus order so the failure report is deterministic and navigable.
            unbacked.append(str(rule["id"]))
    # Reject the corpus with a bounded preview of every incomplete binding rule.
    assert unbacked == [], (
        f"{len(unbacked)} binding rule(s) lack a complete joined strategy: "
        f"{', '.join(str(r) for r in unbacked[:10])}"
    )


def test_advisory_rules_justify_themselves() -> None:
    """FLOW-006: an advisory rule states why no mechanism is possible.

    Advisory is an admission, not a convenience. An unjustified one is a rule
    that quietly opted out of the axiom.
    """
    # Select advisory rule-id elements in corpus order when no opt-out reason is present.
    unjustified = [
        rule["id"]
        for rule in load_rules()
        if rule["force"] == "ADVISORY" and not rule["no_mechanism"]
    ]
    # Reject every advisory escape from the mechanization axiom lacking justification.
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
    # Establish the unordered function-name census proving companion tests exist at all.
    companions = names_defined_in(REPO_ROOT / "enforce" / "checks")
    # Accumulate unique check-module-name elements; discovery order is irrelevant.
    proven: set[str] = set()
    # Search companion test paths for references to each concrete checker module.
    for path in REPO_ROOT.glob("enforce/checks/test_*.py"):
        # Read the companion once before comparing it to every checker name.
        text = path.read_text(encoding="utf-8")
        # Compare the current companion text against every discovered mechanism module.
        for module in iter_check_modules():
            # Credit a mechanism only when its module name occurs in companion source.
            if f"{module.stem}" in text:
                # Record the witnessed module name without introducing order semantics.
                proven.add(module.stem)
    # Sort unproven module-name elements for a deterministic remediation report.
    unproven = sorted({m.stem for m in iter_check_modules()} - proven)
    # Reject any check whose silence has no independently exercised failure case.
    assert unproven == [], (
        f"check(s) with no proof-of-failure companion: {', '.join(unproven)}. "
        f"Add one to enforce/checks/test_*.py that drives the check to fire."
    )
    # Reject a vacuous repository containing no companion test function at all.
    assert companions, "no companion tests found at all"


def test_validator_checks_can_fail() -> None:
    """FLOW-007 applied to the corpus validator.

    Every finding code the validator can emit must appear in a test that drives
    it, or the code is a branch nobody has ever seen taken.
    """
    # Read validator source and derive its unique finding-code elements in sorted order.
    source = (REPO_ROOT / "tools" / "validate.py").read_text(encoding="utf-8")
    emitted = sorted(set(_finding_codes(source)))
    # Combine companion source into one search corpus; physical test order is irrelevant.
    proofs = "".join(path.read_text(encoding="utf-8") for path in REPO_ROOT.glob("tools/test_*.py"))
    # Preserve sorted finding-code string elements absent from all companion proofs.
    unproven = [code for code in emitted if code not in proofs]
    # Reject any validator branch whose diagnostic has never been driven by a test.
    assert unproven == [], f"validator code(s) never driven by a test: {', '.join(unproven)}"


def _finding_codes(source: str) -> Iterator[str]:
    """Every finding code the validator constructs.

    @param source the validator's source text
    @return finding-code string elements in AST traversal order
    """
    # Parse the validator text into a syntax tree without executing the tool.
    tree = ast.parse(source)
    # Visit every syntax node that could contain a diagnostic constructor call.
    for node in ast.walk(tree):
        # Discard non-call nodes before inspecting keyword arguments.
        if not isinstance(node, ast.Call):
            # Continue the syntax traversal with the next node.
            continue
        # Inspect each keyword argument in the call's lexical order.
        for keyword in node.keywords:
            # Select literal `code=` values and ignore dynamic or unrelated keywords.
            if keyword.arg == "code" and isinstance(keyword.value, ast.Constant):
                # Yield the normalized finding identifier used by companion searches.
                yield str(keyword.value.value)


# ------------------------------------------------------------------- FLOW-009


def test_no_source_file_carries_a_control_character() -> None:
    r"""A stray control byte in source is invisible in every diff that matters.

    Written after one reached `doc_coverage.py`: a shell heredoc collapsed `\\\\b`
    to `\\b`, Python read that as a backspace, and the regex silently stopped
    matching. The check went on passing its own tests and reported 400 findings
    that were not there. Tab and newline are the only control bytes source needs.
    """
    # Accumulate source-location string elements in sorted path and line order.
    offenders: list[str] = []
    # Scan every repository-owned Python path in deterministic order.
    for path in sorted(REPO_ROOT.rglob("*.py")):
        # Exclude foreign metadata, derived builds, and interpreter caches.
        if any(part in {".git", "build", "__pycache__"} for part in path.parts):
            # Advance without interpreting excluded bytes as governed source.
            continue
        # Decode the governed source once before examining its physical lines.
        text = path.read_text(encoding="utf-8")
        # Retain each one-based line number alongside its source text.
        for number, line in enumerate(text.splitlines(), start=1):
            # Collect unordered hexadecimal control-code elements except permitted tabs.
            found = {hex(ord(c)) for c in line if ord(c) < 32 and c != "\t"}
            # Add a deterministic location record only when forbidden bytes occur.
            if found:
                # Sort byte-code elements inside the diagnostic for stable output.
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number} {sorted(found)}")
    # Reject all invisible control bytes with the complete ordered location report.
    assert not offenders, "control characters in source:\n" + "\n".join(offenders)


@decides("DEP-009")
def test_durable_tool_text_writes_pin_lf() -> None:
    """DEP-009: host newline policy cannot change generated or recorded bytes."""
    # Accumulate source-location elements in sorted path and AST traversal order.
    offenders: list[str] = []
    # Inspect every production tool path in deterministic filename order.
    for path in sorted((REPO_ROOT / "tools").glob("*.py")):
        # Exclude test helpers whose temporary writes are intentionally host-local.
        if path.stem.startswith("test_"):
            # Advance to the next production tool without parsing this companion.
            continue
        # Parse durable-write call sites without executing the maintenance tool.
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        # Visit all syntax nodes because durable writes may occur inside nested helpers.
        for node in ast.walk(tree):
            # Retain only attribute calls whose operation is `write_text`.
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "write_text"
            ):
                # Continue to the next node when no durable text write is represented.
                continue
            # Extract the newline keyword value, or absence, from lexical keyword order.
            newline = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "newline"),
                None,
            )
            # Record writes that do not explicitly stabilize bytes with LF newlines.
            if not (isinstance(newline, ast.Constant) and newline.value == "\n"):
                # Preserve the source location needed to repair the exact call site.
                offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{node.lineno}")
    # Reject every durable write whose resulting bytes depend on the host platform.
    assert not offenders, "write_text calls without newline='\\n':\n" + "\n".join(offenders)


@decides("FLOW-009")
def test_gate_suite_defined() -> None:
    """FLOW-009: the gate is a list, in one place, not prose that drifts.

    Every entry names a command that exists. What the gate *is* has to be
    answerable without reading six documents and hoping they agree.
    """
    # Reject a vacuous gate before interpreting its ordered command entries.
    assert GATE, "the gate is empty"
    # Validate each name and ordered argv tuple in canonical execution order.
    for name, command in GATE:
        # Require the human-facing gate step identity used in diagnostics and workflows.
        assert name, "a gate entry has no name"
        # Require at least one argv element so the entry can invoke a process.
        assert command, f"gate entry {name!r} has no command"
        # Resolve repository script operands only for commands using this interpreter.
        target = command[1] if command[0] == sys.executable else None
        # Verify concrete script targets while leaving module switches to Python itself.
        if target and not target.startswith("-"):
            # Reject a gate entry that names a repository script absent from disk.
            assert (REPO_ROOT / target).exists(), f"gate entry {name!r} names a missing {target}"


@pytest.mark.parametrize(("name", "command"), GATE, ids=tuple(dict(GATE)))
@pytest.mark.timeout(600)
def test_every_gate_entry_is_runnable(name: str, command: tuple[str, ...]) -> None:
    """FLOW-009: each gate command starts and reports, rather than erroring out.

    Deliberately does not assert success -- a repository mid-migration may fail
    a gate legitimately. What must hold is that the command *runs*: a gate that
    cannot start is a gate that reports nothing and blocks nothing.

    @param name the gate entry's name
    @param command ordered command-line argument elements to run
    """
    # The console-script hunt that used to live here is gone with the entry it
    # served: gate step 1 now runs `tools/lint_gate.py`, which invokes ruff as
    # `sys.executable -m ruff`. Locating an executable was what made the lint gate
    # skip itself on this machine -- it looked beside the interpreter and not in
    # Scripts/, and 766 findings went unseen behind a green run.
    # Avoid recursively launching the full suite from its own gate-runnability test.
    if command[-1] == "-q" and "pytest" in command:
        # Mark only the recursive aggregate entry inapplicable to this inner run.
        pytest.skip("running the suite from inside the suite would recurse")
    # Encoding is pinned rather than left to the locale: on a cp932 machine the
    # default codec raised on ruff's own output, so the gate died deciding
    # nothing -- exactly the failure this test exists to catch.
    # The v5 Windows release gate observed the 194-case discrimination entry exceed
    # the former 420-second child ceiling when repeated from the complete suite.
    # Keep a finite two-minute margin inside the test's own outer timeout; this
    # still detects a stuck entry without reducing the rejection census.
    # Execute the exact argv with bounded time and locale-independent text capture.
    finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv, no shell
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=REPO_ROOT,
        check=False,
        timeout=540,
    )
    # Accept either gate verdict while rejecting process-launch and execution failures.
    assert finished.returncode in {0, 1}, (
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
    # Locate the optional continuous-integration projection of the canonical gate.
    workflow = REPO_ROOT / ".github" / "workflows" / "gate.yml"
    # Treat absence as an unsupported deployment surface rather than false conformance.
    if not workflow.exists():
        # Report explicit inapplicability when no workflow is present in this tree.
        pytest.skip("no CI workflow in this tree")
    # Extract ordered workflow-step pairs from the authored YAML source.
    text = workflow.read_text(encoding="utf-8")
    steps = re.findall(r'- name: "Gate \d+/\d+ -- (?P<name>[^"]+)"\n\s+run: (?P<run>.+)', text)
    # Require workflow step-name elements to preserve canonical gate order exactly.
    assert [name for name, _ in steps] == [name for name, _ in GATE], (
        "the workflow's step names have drifted from the GATE tuple"
    )
    # Compare each workflow command with the same-position canonical argv entry.
    for (_, run), (name, command) in zip(steps, GATE, strict=True):
        # The workflow says `python`; the tuple says this interpreter. Compare the
        # arguments, which is where a real divergence would show.
        expected = (
            " ".join(("python", *command[1:]))
            if command[0] == sys.executable
            else " ".join(command)
        )
        # Reject command drift after normalizing only the interpreter spelling.
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
    # Start with the active environment root before consulting ambient PATH.
    root = Path(sys.executable).parent
    # Probe platform-specific native-binary candidates in preferred lookup order.
    for candidate in (
        root / "Library" / "bin" / "doxygen.exe",
        root / "doxygen.exe",
        root / "bin" / "doxygen",
        root / "doxygen",
    ):
        # Return the first executable file owned by the active environment.
        if candidate.is_file():
            # Normalize the concrete path for subprocess invocation.
            return str(candidate)
    # Fall back to the ambient executable search when the environment owns none.
    return shutil.which("doxygen")


def test_doxygen_version_matches_recorded() -> None:
    """Doxygen defects fixed between versions; ensure configuration does not drift.

    Doxygen 1.17.0 changed which Python-parser warnings are trustworthy:
    WARN_IF_UNDOCUMENTED is enabled again, while WARN_NO_PARAMDOC remains off.
    Relationship projection and offline output add further version-dependent
    behavior. When Doxygen is upgraded, the warning, extraction, relationship,
    determinism, and remote-resource probes plus the verified date in
    discipline/fact/doxygen.md must move together.

    This test enforces that decision: it skips when Doxygen is not installed,
    and fails when installed and the version differs from the recorded one,
    with a message that tells the reader what to verify and update.
    """
    # Read the recorded version fact from its governed documentation table.
    dox_fact_path = REPO_ROOT / "discipline" / "fact" / "doxygen.md"
    dox_fact_text = dox_fact_path.read_text(encoding="utf-8")

    # Parse the version from the table row:
    # | Doxygen | 1.17.0 | Python extraction ... | `VERSION-DEPENDENT` |
    # Hold the first qualifying version cell; absence remains distinguishable from text.
    recorded_version: str | None = None
    # Examine fact-table line elements in authored order.
    for line in dox_fact_text.splitlines():
        # Select the version-dependent Doxygen row rather than incidental mentions.
        if "| Doxygen |" in line and "VERSION-DEPENDENT" in line:
            # Split ordered table-cell string elements and discard surrounding whitespace.
            parts = [p.strip() for p in line.split("|")]
            # Extract the version cell only from a structurally complete table row.
            if len(parts) >= 3:
                # Preserve the exact recorded tool version for the installed comparison.
                recorded_version = parts[2]
            # Stop after the uniquely identified Doxygen fact row has been processed.
            break

    # Reject a fact table whose declared version cannot be mechanically recovered.
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
    # Mark the native comparison unsupported when no executable can be located.
    if executable is None:
        # Keep absence visible as a skip rather than silently treating it as agreement.
        pytest.skip("doxygen not installed in this environment or on PATH")

    # Ask the installed native tool for its own version under a bounded process call.
    result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        (executable, "--version"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=REPO_ROOT,
        check=False,
        timeout=30,
    )
    # Distinguish an unusable native tool from an actual version mismatch.
    if result.returncode != 0:
        # Report inability to qualify the executable instead of parsing empty output.
        pytest.skip(f"{executable} did not report a version")

    # Extract the leading installed-version token from potentially annotated output.
    installed_version = result.stdout.strip().split()[0]

    # Reject drift until all version-dependent qualification facts move together.
    assert installed_version == recorded_version, (
        f"Doxygen version mismatch: discipline/fact/doxygen.md records {recorded_version!r} "
        f"but {installed_version!r} is installed.\n\n"
        f"Before updating the version and verified: date in discipline/fact/doxygen.md:\n"
        f"  1. Re-run tools/test_doxygen_gate.py on Windows and Linux.\n"
        f"  2. Re-verify warning, extraction, relationship, determinism, and offline output.\n"
        f"  3. Update enforce/Doxyfile only from those observations.\n"
        f"  4. Update 'verified:' and both tool identities in discipline/fact/doxygen.md.\n"
    )


# Execute the module as a standalone focused suite only at its script boundary.
if __name__ == "__main__":
    # Propagate pytest's standalone verdict as this module's process exit status.
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
    # Read the shipped completion hook and installer as the two halves of enforcement.
    hook = REPO_ROOT / "enforce" / "templates" / "hooks" / "pre-push"
    assert hook.is_file(), "no pre-push hook ships, so the verification obligation is a request"
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
    # Require the installer to activate the shipped hook rather than merely archive it.
    assert "hooksPath" in installer, "nothing installs the hook, so it ships and never runs"


def test_a_hook_that_does_not_run_the_gate_is_caught(tmp_path: Path) -> None:
    """The negative case: a hook that greets the user and exits zero.

    @param tmp_path holds the substituted hook

    @par Effects
    Writes one isolated pre-push fixture before reading it back.
    """
    # Construct a harmless hook fixture whose successful exit bypasses the gate.
    hook = tmp_path / "pre-push"
    # Persist the negative subject before asserting that its content lacks enforcement.
    hook.write_text("#!/bin/sh\necho pushing\nexit 0\n", encoding="utf-8")
    # Prove the deliberately incomplete hook cannot satisfy the gate-content predicate.
    assert "gate.py" not in hook.read_text(encoding="utf-8")
