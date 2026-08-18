"""Proof-of-failure tests for the AST checks.

FLOW-007: every check must be shown able to produce a failing signal before its
silence means anything. Each check gets a violating case that must fire and a
conforming case that must not.

    pytest enforce/checks/test_checks.py
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from textwrap import dedent

import pytest

from checks import Check
from checks.assert_usage import AssertUsageCheck
from checks.domain_purity import DomainPurityCheck
from checks.no_test_branches import NoTestBranchesCheck
from checks.raise_from import RaiseFromCheck


def write(tmp_path: Path, source: str, *, layer: str = "domain", name: str = "mod.py") -> Path:
    """Write a probe module inside a synthetic source tree and return its path.

    The directory shape is load-bearing: `layer_of` reads the layer off a path
    segment, so `layer` decides whether the domain-only rules apply at all.

    @param tmp_path pytest's per-test directory, used as the root of the fake tree
    @param source the module text, dedented before writing
    @param layer the segment under `src/mypkg/`; only `domain`, `app`, `adapters`
        and `shell` are recognised, anything else reads as `unknown`
    @param name the file's name -- a `test_` prefix would make every check skip
        the file, which is why the default does not have one
    @return the written file, ready to hand to a check
    """
    target = tmp_path / "src" / "mypkg" / layer / name
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


# ------------------------------------------------------------------ domain purity

def test_domain_io_import_fires(tmp_path: Path) -> None:
    """An I/O module reached from the domain is reported, import alone sufficing."""
    path = write(tmp_path, "import pathlib\n\ndef load() -> str:\n    return 'x'\n")
    assert "ARCH-002" in rules_fired(DomainPurityCheck(), path)


def test_domain_any_annotation_fires(tmp_path: Path) -> None:
    """`Any` in a domain signature is reported: it erases the contract."""
    path = write(tmp_path, "from typing import Any\n\ndef f(x: Any) -> None: ...\n")
    assert "TYPE-002" in rules_fired(DomainPurityCheck(), path)


def test_domain_literal_union_fires(tmp_path: Path) -> None:
    """A `Literal` union standing in for a named enum is reported."""
    path = write(tmp_path, "from typing import Literal\n\ndef f(s: Literal['a', 'b']) -> None: ...\n")
    assert "TYPE-006" in rules_fired(DomainPurityCheck(), path)


def test_domain_unfrozen_dataclass_fires(tmp_path: Path) -> None:
    """A bare `@dataclass` in the domain is reported: TYPE-007 wants frozen and slots both."""
    path = write(tmp_path, """
        from dataclasses import dataclass

        @dataclass
        class Outline:
            title: str
    """)
    assert "TYPE-007" in rules_fired(DomainPurityCheck(), path)


def test_domain_foreign_type_fires(tmp_path: Path) -> None:
    """A known framework type convicts on its name alone; no import has to declare it."""
    path = write(tmp_path, "def handle(request: Request) -> None: ...\n")
    assert "ARCH-013" in rules_fired(DomainPurityCheck(), path)


def test_conforming_domain_module_is_silent(tmp_path: Path) -> None:
    """Frozen slotted values, an enum and non-I/O imports leave all five rules silent."""
    path = write(tmp_path, """
        from dataclasses import dataclass
        from enum import StrEnum

        class Stage(StrEnum):
            DRAFT = "draft"
            FINAL = "final"

        @dataclass(frozen=True, slots=True)
        class Outline:
            title: str
            stage: Stage

        def rename(outline: Outline, title: str) -> Outline:
            return Outline(title=title, stage=outline.stage)
    """)
    assert rules_fired(DomainPurityCheck(), path) == set()


def test_adapter_layer_is_allowed_io(tmp_path: Path) -> None:
    """The same import outside the domain is fine -- that is the whole point."""
    path = write(tmp_path, "import pathlib\n", layer="adapters")
    assert rules_fired(DomainPurityCheck(), path) == set()


# --------------------------------------------------------------------- raise_from

def test_raise_without_from_fires(tmp_path: Path) -> None:
    """Raising inside a handler with no `from` clause is reported; the cause is lost."""
    path = write(tmp_path, """
        def load() -> None:
            try:
                parse()
            except ValueError:
                raise RuntimeError("bad")
    """)
    assert "DIAG-005" in rules_fired(RaiseFromCheck(), path)


def test_bare_except_fires(tmp_path: Path) -> None:
    """A bare handler is reported even when it does work rather than nothing."""
    path = write(tmp_path, """
        def load() -> None:
            try:
                parse()
            except:
                handle()
    """)
    assert "DIAG-008" in rules_fired(RaiseFromCheck(), path)


def test_catch_and_pass_fires(tmp_path: Path) -> None:
    """A named exception discarded by `pass` is reported under the same rule."""
    path = write(tmp_path, """
        def load() -> None:
            try:
                parse()
            except ValueError:
                pass
    """)
    assert "DIAG-008" in rules_fired(RaiseFromCheck(), path)


def test_from_none_without_reason_fires(tmp_path: Path) -> None:
    """Suppressing the cause is reported when no comment on or just above the raise argues it."""
    path = write(tmp_path, """
        def load() -> None:
            try:
                parse()
            except ValueError as err:
                raise RuntimeError("bad") from None
    """)
    assert "DIAG-007" in rules_fired(RaiseFromCheck(), path)


def test_from_none_with_a_stated_reason_is_accepted(tmp_path: Path) -> None:
    """A preceding comment is the escape hatch: suppression is allowed once argued."""
    path = write(tmp_path, """
        def load() -> None:
            try:
                parse()
            except ValueError as err:
                # The parser's internal error names an offset in a temp buffer,
                # which is meaningless to a caller.
                raise RuntimeError("bad") from None
    """)
    assert "DIAG-007" not in rules_fired(RaiseFromCheck(), path)


def test_bare_reraise_is_not_flagged(tmp_path: Path) -> None:
    """It preserves the traceback. One source document said otherwise; see CONFLICTS C4."""
    path = write(tmp_path, """
        def load() -> None:
            try:
                parse()
            except ValueError:
                record()
                raise
    """)
    assert rules_fired(RaiseFromCheck(), path) == set()


def test_explicit_chaining_is_silent(tmp_path: Path) -> None:
    """Chaining with `from err` is the conforming form and draws nothing."""
    path = write(tmp_path, """
        def load() -> None:
            try:
                parse()
            except ValueError as err:
                raise RuntimeError("bad") from err
    """)
    assert rules_fired(RaiseFromCheck(), path) == set()


# ------------------------------------------------------------------- assert_usage

def test_assert_on_a_parameter_fires(tmp_path: Path) -> None:
    """Guarding a caller-supplied argument with an assert is reported; `-O` deletes it."""
    path = write(tmp_path, """
        def save(name: str) -> None:
            assert name, "name is required"
    """)
    assert "ERR-012" in rules_fired(AssertUsageCheck(), path)


def test_assert_on_external_input_fires(tmp_path: Path) -> None:
    """Asserting over freshly parsed data is reported: that is validation, not an invariant."""
    path = write(tmp_path, """
        def load() -> None:
            assert json.loads(raw)["ok"]
    """)
    assert "ERR-012" in rules_fired(AssertUsageCheck(), path)


def test_assert_with_a_validation_message_fires(tmp_path: Path) -> None:
    """The message alone convicts: user-facing wording marks the assert as validation."""
    path = write(tmp_path, """
        def run() -> None:
            assert flag, "permission denied"
    """)
    assert "ERR-012" in rules_fired(AssertUsageCheck(), path)


def test_internal_invariant_assert_is_allowed(tmp_path: Path) -> None:
    """An assert over a locally computed value survives, which is the point of the rule."""
    path = write(tmp_path, """
        def reduce() -> None:
            total = compute()
            assert total >= 0
    """)
    assert rules_fired(AssertUsageCheck(), path) == set()


# --------------------------------------------------------------- no_test_branches

def test_env_test_branch_fires(tmp_path: Path) -> None:
    """Behaviour switched by a test-named environment variable is reported."""
    path = write(tmp_path, """
        def run() -> None:
            if os.environ.get("TESTING"):
                return
    """)
    assert "ARCH-012" in rules_fired(NoTestBranchesCheck(), path)


def test_sys_modules_probe_fires(tmp_path: Path) -> None:
    """Asking `sys.modules` whether pytest is loaded is the same defect in disguise."""
    path = write(tmp_path, """
        def run() -> None:
            if "pytest" in sys.modules:
                return
    """)
    assert "ARCH-012" in rules_fired(NoTestBranchesCheck(), path)


def test_import_probe_fires(tmp_path: Path) -> None:
    """A guarded import of the test framework is caught at module scope, outside any function."""
    path = write(tmp_path, """
        try:
            import pytest
        except ImportError:
            pytest = None
    """)
    assert "ARCH-012" in rules_fired(NoTestBranchesCheck(), path)


def test_ordinary_branch_is_silent(tmp_path: Path) -> None:
    """A branch on domain data is untouched; only test-awareness is forbidden."""
    path = write(tmp_path, """
        def run(stage: str) -> None:
            if stage == "draft":
                return
    """)
    assert rules_fired(NoTestBranchesCheck(), path) == set()


# ------------------------------------------------------------------------- shared

@pytest.mark.parametrize(
    "check",
    [DomainPurityCheck(), RaiseFromCheck(), AssertUsageCheck(), NoTestBranchesCheck()],
    ids=lambda c: c.name,
)
def test_every_check_declares_the_rules_it_enforces(check: Check) -> None:
    """No check decides anything anonymously, so a finding traces back to law.

    @param check each concrete check in turn; the list is written out by hand,
        so a new check has to be added to it to be covered here
    """
    assert check.rules, f"{check.name} enforces no named rule"
    assert all(r[:3].isupper() and "-" in r for r in check.rules)


def test_test_files_are_exempt(tmp_path: Path) -> None:
    """Tests assert and catch broadly by nature; the checks must not police them."""
    target = tmp_path / "tests" / "test_thing.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dedent("""
        def test_x() -> None:
            assert value, "must be set"
            try:
                run()
            except Exception:
                pass
    """), encoding="utf-8")
    checks: Sequence[Check] = (AssertUsageCheck(), RaiseFromCheck())
    for check in checks:
        assert rules_fired(check, target) == set(), check.name


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
