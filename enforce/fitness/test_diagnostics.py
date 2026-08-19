"""Every escaping error becomes a valid envelope, and its code is a contract.

**Oracle: contract.** The diagnostic envelope's published schema, and `law/DIAG`,
held against a project tree.

* `DIAG-001`, `FLOW-011` -- every escaping error produces a valid envelope, and
  the diagnosis is checked rather than assumed
* `API-011`, `DIAG-004` -- a code is versioned surface
* `DIAG-013` -- a correlation identifier ties a failure to its trace
* `ERR-015` -- no unhandled exception reaches the process boundary

This is the suite the whole thesis reduces to. `DIAG-001` is checked by building
a real error, serializing it, and validating the result against the shipped
schema -- not by looking for a function called `envelope`. `FLOW-011` says the
diagnosis is checked and not assumed, and a fitness test that merely asserted the
producer existed would be assuming it.

    pytest enforce/fitness/test_diagnostics.py
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Final

import pytest

from fixtures import package_root, reference_root

## The validator library. Imported through `importorskip` so a tree without
## it skips rather than errors -- the schema is still shipped and still
## correct; what is unavailable is the means to check it here.
jsonschema = pytest.importorskip("jsonschema", reason="jsonschema not installed")

## The published schema every escaping error validates against.
SCHEMA_PATH: Final = Path(__file__).resolve().parent.parent / "schema" / "diagnostic.schema.json"

## Where the reference package's source lives, put on the path so a real error
## can be built and serialized rather than described.
_SRC: Final = reference_root() / "src"


@pytest.fixture(scope="module")
def envelope_module() -> object:
    """The reference package's envelope producer, imported for real.

    @return the imported module
    """
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    from refpkg.shell import envelope  # ruff: ignore[import-outside-top-level]

    return envelope


@pytest.fixture(scope="module")
def validator() -> object:
    """A validator over the shipped schema.

    @return a draft 2020-12 validator
    """
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


# ------------------------------------------------------- DIAG-001 / FLOW-011


def test_envelope_conforms(envelope_module: object, validator: object) -> None:
    """DIAG-001, FLOW-011: a real error is serialized and the record validated.

    Three errors, one from each layer's family, because the `layer` field is
    derived from the family and a producer that got one right could still get
    the others wrong.

    @param envelope_module the reference's envelope producer
    @param validator the schema validator
    """
    sys.path.insert(0, str(_SRC))
    from refpkg.app.errors import (  # ruff: ignore[import-outside-top-level]
        PruneInterrupted,
    )
    from refpkg.domain.errors import InvariantViolated  # ruff: ignore[import-outside-top-level]
    from refpkg.ports.errors import ClockUnavailable  # ruff: ignore[import-outside-top-level]

    cases = {
        "domain": InvariantViolated("an instant is at or after the epoch", -1),
        "adapter": ClockUnavailable("no reading"),
        "app": PruneInterrupted(("a.log",), ("b.log",)),
    }
    for layer, error in cases.items():
        record = envelope_module.from_error(error)  # type: ignore[attr-defined]
        problems = [e.message for e in validator.iter_errors(record)]  # type: ignore[attr-defined]
        assert not problems, f"the {layer} envelope does not conform: {problems}"
        assert record["layer"] == layer, (
            f"a {layer} error serialized with layer={record['layer']!r}; the "
            f"field is derived from the error family, so this means the "
            f"families have been mixed"
        )


def test_a_chained_error_keeps_its_cause(envelope_module: object) -> None:
    """DIAG-005 in the envelope: the origin survives serialization.

    A record whose `cause_chain` is empty for a chained error has thrown away the
    half of the diagnosis that says where the failure started.

    @param envelope_module the reference's envelope producer
    """
    sys.path.insert(0, str(_SRC))
    from refpkg.app.errors import (  # ruff: ignore[import-outside-top-level]
        PruneInterrupted,
    )
    from refpkg.ports.errors import (  # ruff: ignore[import-outside-top-level]
        StoreOperation,
        StoreUnavailable,
    )

    def store_fails() -> None:
        """Raise the adapter-layer fault this test needs a real instance of."""
        raise StoreUnavailable(StoreOperation.DELETE, "disk gone")

    try:
        try:
            store_fails()
        except StoreUnavailable as cause:
            raise PruneInterrupted((), ("a.log",)) from cause
    except PruneInterrupted as caught:
        record = envelope_module.from_error(caught)  # type: ignore[attr-defined]

    assert [c["layer"] for c in record["cause_chain"]] == ["adapter"]
    assert "disk gone" in record["cause_chain"][0]["message"]


def test_a_refusal_produces_the_same_shape(envelope_module: object,
                                           validator: object) -> None:
    """ERR-001: a consumer must not need to know which channel a failure took.

    @param envelope_module the reference's envelope producer
    @param validator the schema validator
    """
    sys.path.insert(0, str(_SRC))
    from refpkg.domain.plan import Refusal  # ruff: ignore[import-outside-top-level]

    record = envelope_module.from_refusal(  # type: ignore[attr-defined]
        Refusal(code="refpkg.domain.refused", expected="a", actual="b"))
    assert not [e.message for e in validator.iter_errors(record)]  # type: ignore[attr-defined]


# ------------------------------------------------------- API-011 / DIAG-004


def test_codes_are_stable() -> None:
    """API-011, DIAG-004: every code is namespaced and no two are the same.

    A duplicated code is the failure that cannot be diagnosed at all: two
    different faults report identically, and every consumer matching on the code
    handles the wrong one half the time.
    """
    package = package_root(reference_root())
    codes: dict[str, str] = {}
    for module in sorted(package.rglob("*.py")):
        if "__pycache__" in module.parts:
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for statement in node.body:
                if not isinstance(statement, ast.Assign):
                    continue
                for target in statement.targets:
                    if getattr(target, "id", "") != "code":
                        continue
                    value = statement.value
                    if not isinstance(value, ast.Constant):
                        continue
                    code = str(value.value)
                    assert code.count(".") >= 2, (
                        f"{node.name} has code {code!r}, which names no layer"
                    )
                    assert code not in codes, (
                        f"{node.name} reuses the code {code!r}, already used by "
                        f"{codes[code]}. Two faults reporting identically cannot "
                        f"be told apart by any consumer."
                    )
                    codes[code] = node.name
    assert len(codes) >= 3, (
        f"only {len(codes)} coded error types found; this test would be nearly "
        f"vacuous"
    )


# ------------------------------------------------------------------ DIAG-013


def test_correlation_propagates() -> None:
    """DIAG-013: the envelope has somewhere for a correlation identifier to go.

    The reference does not emit one -- it is a single-process CLI with no log to
    correlate against, and `CONF-029` put distributed tracing out of scope for
    exactly that shape of program. What the schema must do is *admit* the field,
    so a program that does have a trace can tie a failure to it without changing
    the published contract.
    """
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert "correlation_id" in schema["properties"], (
        "the envelope schema has no correlation_id field, so a program with a "
        "trace could not tie a failure to it without a schema change"
    )
    assert "correlation_id" not in schema.get("required", []), (
        "correlation_id is required, which would make the envelope unusable in "
        "the single-process case CONF-029 explicitly scopes out"
    )


# ------------------------------------------------------------------- ERR-015


def test_no_unhandled_escape() -> None:
    """ERR-015: the process boundary catches everything and returns a code.

    The shell is the one module permitted to catch broadly, and it must -- an
    escaping exception at the boundary produces a traceback on stderr, which is
    prose, unparseable, and the opposite of an envelope.
    """
    package = package_root(reference_root())
    shell = package / "shell"
    entries = [m for m in sorted(shell.glob("*.py")) if m.stem in {"cli", "main"}]
    assert entries, "no process entry point found under shell/"

    for module in entries:
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        handlers = [
            h for node in ast.walk(tree) if isinstance(node, ast.Try)
            for h in node.handlers
        ]
        broad = [
            h for h in handlers
            if h.type is None or getattr(h.type, "id", "") in {"Exception", "BaseException"}
        ]
        assert broad, (
            f"{module.name} is a process entry point and catches nothing broadly. "
            f"An exception escaping here becomes a traceback, which is prose."
        )
        for handler in broad:
            emits = any(
                isinstance(n, ast.Call)
                and "envelope" in ast.dump(n)
                for n in ast.walk(handler)
            )
            assert emits, (
                f"{module.name} catches broadly and does not produce an envelope; "
                f"the failure is swallowed rather than reported."
            )


# ------------------------------------------------------------------- DIAG-001
#
# The field that closes the Prime Directive's last hop.


def test_every_envelope_names_a_rule_that_resolves(envelope_module: object) -> None:
    """DIAG-001: a failure says which contract it broke, in ids the corpus carries.

    `rule_ids` was in the published schema from the start and nothing populated
    it, so the one field that turns a diagnosis into a lookup was specified,
    shipped and dead. An agent had to infer the rule from a message.

    An unresolvable id is worse than an absent one: it sends a reader to a rule
    that does not exist and costs them the trip. So this asserts both halves --
    the ids are there, and they name rules `discipline/rules.json` actually holds.

    @param envelope_module the reference's envelope producer
    """
    sys.path.insert(0, str(_SRC))
    from refpkg.app.errors import (  # ruff: ignore[import-outside-top-level]
        PruneInterrupted,
    )
    from refpkg.domain.errors import (  # ruff: ignore[import-outside-top-level]
        InvariantViolated,
    )
    from refpkg.ports.errors import (  # ruff: ignore[import-outside-top-level]
        ClockUnavailable,
    )

    corpus = Path(__file__).resolve().parent.parent.parent / "discipline"
    index = json.loads((corpus / "rules.json").read_text(encoding="utf-8"))
    known = {rule["id"] for rule in index["rules"]}

    for error in (InvariantViolated("an instant is at or after the epoch", -1),
                  ClockUnavailable("no reading"),
                  PruneInterrupted(("a.log",), ("b.log",))):
        record = envelope_module.from_error(error)  # type: ignore[attr-defined]
        named = record.get("rule_ids") or []
        assert named, (
            f"{type(error).__name__} produces an envelope naming no rule, so a "
            f"consumer must infer the contract from prose"
        )
        unknown = sorted(set(named) - known)
        assert not unknown, (
            f"{type(error).__name__} names {unknown}, which the corpus does not "
            f"carry. An id that resolves to nothing costs a reader the trip."
        )
