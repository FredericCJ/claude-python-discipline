"""Proof-of-failure tests for the boundary, logging, metaprogramming and redaction checks.

`FLOW-007` and `TEST-015`. Each check gets a fixture it must reject and one it
must accept, because a companion that drives only the failing case is how an
over-reporting check ships.

Two of the accepting cases below are load-bearing rather than decorative. Acting
on absence (`if not p.exists(): create(p)`) and a literal `getattr(x, "name")`
are both extremely common and both correct; a check reporting either would be
switched off within a day of anyone running it.

    pytest enforce/checks/test_safety_checks.py
"""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

from checks import project
from checks.boundary_parsing import BoundaryParsingCheck
from checks.log_once import LogOnceCheck
from checks.no_magic_in_domain import NoMagicInDomainCheck
from checks.redaction import RedactionCheck

if TYPE_CHECKING:
    from pathlib import Path

    from checks import Check


def fired(check: Check, tmp_path: Path, source: str, *,
          layer: str = "domain", name: str = "mod.py") -> set[str]:
    """Rule ids a check reports for one synthetic module.

    @param check the mechanism under test
    @param tmp_path pytest's per-test directory, used as the root of a fake tree
    @param source the module text, dedented before writing
    @param layer the segment under `src/mypkg/`, which decides layer scoping
    @param name the file's name; a `test_` prefix makes every check skip it
    @return every rule id reported, empty when the module conforms
    """
    target = tmp_path / "src" / "mypkg" / layer / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dedent(source), encoding="utf-8")
    check.declaration = project.DEFAULT
    return {f.rule_id for f in check.run([target])}


# ------------------------------------- ERR-011/013 / TYPE-005/010/011/012


def test_newtype_fires(tmp_path: Path) -> None:
    """TYPE-005 via CONF-015: a NewType announces a constraint it cannot enforce.

    @param tmp_path the fixture directory
    """
    assert "TYPE-005" in fired(BoundaryParsingCheck(), tmp_path, """
        \"\"\"M.\"\"\"
        from typing import NewType
        UserId = NewType("UserId", int)
    """)


def test_isinstance_against_a_protocol_fires(tmp_path: Path) -> None:
    """TYPE-010: a shape check reads like a contract check and is not one.

    @param tmp_path the fixture directory
    """
    assert "TYPE-010" in fired(BoundaryParsingCheck(), tmp_path, """
        \"\"\"M.\"\"\"
        from typing import Protocol
        class Store(Protocol):
            \"\"\"A contract.\"\"\"
            def get(self):
                \"\"\"Fetch.\"\"\"
        def use(x):
            \"\"\"Check the shape and hope.\"\"\"
            if isinstance(x, Store):
                return x.get()
            return None
    """)


def test_probe_then_leap_fires(tmp_path: Path) -> None:
    """ERR-013: every one of the eight findings in real code was this shape.

    @param tmp_path the fixture directory
    """
    assert "ERR-013" in fired(BoundaryParsingCheck(), tmp_path, """
        \"\"\"M.\"\"\"
        def tidy(p):
            \"\"\"Race between the question and the answer.\"\"\"
            if p.exists():
                p.unlink()
    """, layer="adapters")


def test_acting_on_absence_is_silent(tmp_path: Path) -> None:
    """Creating when missing does not race to *use* presence.

    Load-bearing: without it the check reports most guarded creation anyone
    writes, and a check that noisy is a check that gets switched off.

    @param tmp_path the fixture directory
    """
    assert fired(BoundaryParsingCheck(), tmp_path, """
        \"\"\"M.\"\"\"
        def ensure(p):
            \"\"\"Create only when missing.\"\"\"
            if not p.exists():
                p.write_text("")
    """, layer="adapters") == set()


def test_isinstance_against_an_ordinary_class_is_silent(tmp_path: Path) -> None:
    """Narrowing a union is not the shape the rule refuses.

    @param tmp_path the fixture directory
    """
    assert fired(BoundaryParsingCheck(), tmp_path, """
        \"\"\"M.\"\"\"
        def use(x):
            \"\"\"Narrow an ordinary union.\"\"\"
            if isinstance(x, int):
                return x
            return 0
    """) == set()


# ------------------------------------------------------- DIAG-010 / DIAG-015


def test_logging_and_reraising_fires(tmp_path: Path) -> None:
    """DIAG-010: one fault logged at three levels reads as three incidents.

    @param tmp_path the fixture directory
    """
    assert "DIAG-010" in fired(LogOnceCheck(), tmp_path, """
        \"\"\"M.\"\"\"
        import logging
        log = logging.getLogger(__name__)
        def load(p):
            \"\"\"Log it and pass it on anyway.\"\"\"
            try:
                return p.read_text()
            except OSError:
                log.error("could not read")
                raise
    """, layer="adapters")


def test_interpolating_the_exception_fires(tmp_path: Path) -> None:
    """DIAG-015: the payload becomes prose at the one moment it was needed.

    @param tmp_path the fixture directory
    """
    assert "DIAG-015" in fired(LogOnceCheck(), tmp_path, """
        \"\"\"M.\"\"\"
        import logging
        log = logging.getLogger(__name__)
        def load(p):
            \"\"\"Discard the traceback and the chain.\"\"\"
            try:
                return p.read_text()
            except OSError as exc:
                log.error(f"could not read: {exc}")
                return None
    """, layer="adapters")


def test_logging_the_exception_as_structure_is_silent(tmp_path: Path) -> None:
    """Handling it here, once, with everything kept.

    @param tmp_path the fixture directory
    """
    assert fired(LogOnceCheck(), tmp_path, """
        \"\"\"M.\"\"\"
        import logging
        log = logging.getLogger(__name__)
        def load(p):
            \"\"\"Keep the traceback.\"\"\"
            try:
                return p.read_text()
            except OSError:
                log.exception("could not read")
                return None
    """, layer="adapters") == set()


# ------------------------------------------------------------------ ARCH-015


def test_a_computed_getattr_in_the_domain_fires(tmp_path: Path) -> None:
    """The case found four times in real domain code.

    @param tmp_path the fixture directory
    """
    assert "ARCH-015" in fired(NoMagicInDomainCheck(), tmp_path, """
        \"\"\"M.\"\"\"
        def read(obj, field):
            \"\"\"Resolve a name nobody can enumerate.\"\"\"
            return getattr(obj, field)
    """)


def test_a_metaclass_in_the_domain_fires(tmp_path: Path) -> None:
    """A metaclass changes what a class *is* somewhere else in the tree.

    @param tmp_path the fixture directory
    """
    assert "ARCH-015" in fired(NoMagicInDomainCheck(), tmp_path, """
        \"\"\"M.\"\"\"
        class Thing(metaclass=type):
            \"\"\"Built elsewhere.\"\"\"
    """)


def test_a_literal_getattr_is_silent(tmp_path: Path) -> None:
    """A readable default is not metaprogramming.

    Load-bearing for the same reason as the absence case above.

    @param tmp_path the fixture directory
    """
    assert fired(NoMagicInDomainCheck(), tmp_path, """
        \"\"\"M.\"\"\"
        def read(obj):
            \"\"\"Resolve a name a reader can see.\"\"\"
            return getattr(obj, "name", None)
    """) == set()


def test_magic_outside_the_domain_is_silent(tmp_path: Path) -> None:
    """An adapter may need getattr to bridge a foreign library's shape.

    @param tmp_path the fixture directory
    """
    assert fired(NoMagicInDomainCheck(), tmp_path, """
        \"\"\"M.\"\"\"
        def read(obj, field):
            \"\"\"Bridge a foreign shape.\"\"\"
            return getattr(obj, field)
    """, layer="adapters") == set()


# ------------------------------------------------------------------ DIAG-014


def test_a_secret_passed_to_a_logger_fires(tmp_path: Path) -> None:
    """The remedy for this one is a rotation, not a code change.

    @param tmp_path the fixture directory
    """
    assert "DIAG-014" in fired(RedactionCheck(), tmp_path, """
        \"\"\"M.\"\"\"
        import logging
        log = logging.getLogger(__name__)
        def connect(user, password):
            \"\"\"Record what must not be recorded.\"\"\"
            log.info("connecting as %s with %s", user, password)
    """, layer="adapters")


def test_a_secret_in_an_envelope_field_fires(tmp_path: Path) -> None:
    """The `value` field is carried verbatim to whoever reads the error.

    @param tmp_path the fixture directory
    """
    assert "DIAG-014" in fired(RedactionCheck(), tmp_path, """
        \"\"\"M.\"\"\"
        def envelope(api_key):
            \"\"\"Publish the offending input.\"\"\"
            return {"code": "pkg.auth.rejected", "value": api_key}
    """, layer="adapters")


def test_an_ordinary_value_is_silent(tmp_path: Path) -> None:
    """Redaction pulls against the rest of law/DIAG; it must not pull too far.

    @param tmp_path the fixture directory
    """
    assert fired(RedactionCheck(), tmp_path, """
        \"\"\"M.\"\"\"
        import logging
        log = logging.getLogger(__name__)
        def connect(user, host):
            \"\"\"Record what should be recorded.\"\"\"
            log.info("connecting as %s to %s", user, host)
    """, layer="adapters") == set()
