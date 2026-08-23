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

from decides import decides
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

    @par Effects
    Prepends the reference source directory to the test process import path once.
    """
    # Make reference source importable only when its path is not already present.
    if str(_SRC) not in sys.path:
        # Prepend the exact reference source so its envelope producer wins resolution.
        sys.path.insert(0, str(_SRC))
    from refpkg.shell import envelope  # ruff: ignore[import-outside-top-level]

    # Return the imported producer module after establishing deterministic resolution.
    return envelope


@pytest.fixture(scope="module")
def validator() -> object:
    """A validator over the shipped schema.

    @return a draft 2020-12 validator
    """
    # Decode the schema field mapping before validating its own draft structure.
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    # Return a validator only after the published schema is structurally valid.
    return jsonschema.Draft202012Validator(schema)


# ------------------------------------------------------- DIAG-001 / FLOW-011


@decides("DIAG-001", "FLOW-011")
def test_envelope_conforms(envelope_module: object, validator: object) -> None:
    """DIAG-001, FLOW-011: a real error is serialized and the record validated.

    Three errors, one from each layer's family, because the `layer` field is
    derived from the family and a producer that got one right could still get
    the others wrong.

    @param envelope_module the reference's envelope producer
    @param validator the schema validator

    @par Effects
    Prepends the reference source directory to this test process's import path.
    """
    # Make the three concrete error families importable for real serialization.
    sys.path.insert(0, str(_SRC))
    from refpkg.app.errors import (  # ruff: ignore[import-outside-top-level]
        PruneInterrupted,
    )
    from refpkg.domain.errors import InvariantViolated  # ruff: ignore[import-outside-top-level]
    from refpkg.ports.errors import ClockUnavailable  # ruff: ignore[import-outside-top-level]

    # Map layer-name keys to representative error-instance values in diagnostic order.
    cases = {
        "domain": InvariantViolated("an instant is at or after the epoch", -1),
        "adapter": ClockUnavailable("no reading"),
        "app": PruneInterrupted(("a.log",), ("b.log",)),
    }
    # Serialize each layer and error pair in declared diagnostic order.
    for layer, error in cases.items():
        # Produce the envelope and preserve validator-error message elements in library order.
        record = envelope_module.from_error(error)  # type: ignore[attr-defined]
        problems = [e.message for e in validator.iter_errors(record)]  # type: ignore[attr-defined]
        # Require structural conformance and correct derivation of the owning layer.
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

    @par Effects
    Prepends reference source to the import path and raises then translates one
    in-process adapter fault before serializing the caught application error.
    """
    # Make concrete error types importable before constructing their real cause chain.
    sys.path.insert(0, str(_SRC))
    from refpkg.app.errors import (  # ruff: ignore[import-outside-top-level]
        PruneInterrupted,
    )
    from refpkg.ports.errors import (  # ruff: ignore[import-outside-top-level]
        StoreOperation,
        StoreUnavailable,
    )

    def store_fails() -> None:
        """Raise the adapter-layer fault this test needs a real instance of.

        @raise StoreUnavailable always, as the deliberate adapter fault subject
        """
        # Produce the origin error that must survive application-layer translation.
        raise StoreUnavailable(StoreOperation.DELETE, "disk gone")

    # Capture the translated application failure after constructing its nested cause.
    try:
        # Isolate adapter-origin construction from the outer application handler.
        try:
            # Invoke the deliberate failing adapter operation.
            store_fails()
        # Translate the expected adapter family while retaining the concrete cause.
        except StoreUnavailable as cause:
            # Raise the application-family error with explicit exception chaining.
            raise PruneInterrupted((), ("a.log",)) from cause
    # Capture the escaping application error at the simulated process boundary.
    except PruneInterrupted as caught:
        # Serialize the translated error only after the complete chain exists.
        record = envelope_module.from_error(caught)  # type: ignore[attr-defined]

    # Require both adapter layer identity and original message in ordered cause entries.
    assert [c["layer"] for c in record["cause_chain"]] == ["adapter"]
    assert "disk gone" in record["cause_chain"][0]["message"]


def test_a_refusal_produces_the_same_shape(envelope_module: object,
                                           validator: object) -> None:
    """ERR-001: a consumer must not need to know which channel a failure took.

    @param envelope_module the reference's envelope producer
    @param validator the schema validator

    @par Effects
    Prepends the reference source directory to this test process's import path.
    """
    # Make the pure refusal result type importable for real serialization.
    sys.path.insert(0, str(_SRC))
    from refpkg.domain.plan import Refusal  # ruff: ignore[import-outside-top-level]

    # Serialize a refusal through its separate producer boundary.
    record = envelope_module.from_refusal(  # type: ignore[attr-defined]
        Refusal(code="refpkg.domain.refused", expected="a", actual="b"))
    # Require zero validator-error message elements for the refusal envelope.
    assert not [e.message for e in validator.iter_errors(record)]  # type: ignore[attr-defined]


# ------------------------------------------------------- API-011 / DIAG-004


def test_codes_are_stable() -> None:
    """API-011, DIAG-004: every code is namespaced and no two are the same.

    A duplicated code is the failure that cannot be diagnosed at all: two
    different faults report identically, and every consumer matching on the code
    handles the wrong one half the time.
    """
    # Resolve the package and map code-string keys to owner-name values in source order.
    package = package_root(reference_root())
    codes: dict[str, str] = {}
    # Inspect source modules in deterministic path order.
    for module in sorted(package.rglob("*.py")):
        # Exclude interpreter cache paths from the authored diagnostic surface.
        if "__pycache__" in module.parts:
            # Advance to the next authored source module.
            continue
        # Parse error declarations without importing or executing the module.
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        # Visit every syntax node because error classes may be nested in generated code.
        for node in ast.walk(tree):
            # Discard non-class syntax before searching class-level assignments.
            if not isinstance(node, ast.ClassDef):
                # Continue the syntax traversal with the next node.
                continue
            # Inspect class-body statements in lexical order.
            for statement in node.body:
                # Restrict code discovery to ordinary assignment statements.
                if not isinstance(statement, ast.Assign):
                    # Continue with the next class-body statement.
                    continue
                # Inspect all assignment targets in lexical order.
                for target in statement.targets:
                    # Select only a class attribute named as the diagnostic code.
                    if getattr(target, "id", "") != "code":
                        # Continue with the next assignment target.
                        continue
                    # Preserve the assigned syntax value for literal validation.
                    value = statement.value
                    # Reject dynamic declarations from this literal-code census.
                    if not isinstance(value, ast.Constant):
                        # Continue with the next assignment target.
                        continue
                    # Normalize the literal public code to its string representation.
                    code = str(value.value)
                    # Require namespace depth and uniqueness before registering ownership.
                    assert code.count(".") >= 2, (
                        f"{node.name} has code {code!r}, which names no layer"
                    )
                    assert code not in codes, (
                        f"{node.name} reuses the code {code!r}, already used by "
                        f"{codes[code]}. Two faults reporting identically cannot "
                        f"be told apart by any consumer."
                    )
                    # Record the class owner after all public-code constraints pass.
                    codes[code] = node.name
    # Require a non-vacuous census spanning at least the three error families.
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
    # Decode schema field-name keys to JSON-definition values for correlation checks.
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    # Require correlation support while keeping it optional for single-process programs.
    assert "correlation_id" in schema["properties"], (
        "the envelope schema has no correlation_id field, so a program with a "
        "trace could not tie a failure to it without a schema change"
    )
    assert "correlation_id" not in schema.get("required", []), (
        "correlation_id is required, which would make the envelope unusable in "
        "the single-process case CONF-029 explicitly scopes out"
    )


# ------------------------------------------------------------------- ERR-015


@decides("ERR-015")
def test_no_unhandled_escape() -> None:
    """ERR-015: the process boundary catches everything and returns a code.

    The shell is the one module permitted to catch broadly, and it must -- an
    escaping exception at the boundary produces a traceback on stderr, which is
    prose, unparseable, and the opposite of an envelope.
    """
    # Resolve the conformant shell and collect entry-module path elements in sorted order.
    package = package_root(reference_root())
    shell = package / "shell"
    entries = [m for m in sorted(shell.glob("*.py")) if m.stem in {"cli", "main"}]
    # Reject a vacuous package with no process boundary to inspect.
    assert entries, "no process entry point found under shell/"

    # Inspect each entry module in deterministic filename order.
    for module in entries:
        # Parse boundary control flow without importing or executing the shell.
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        # Retain exception-handler node elements in AST try/handler traversal order.
        handlers = [
            h for node in ast.walk(tree) if isinstance(node, ast.Try)
            for h in node.handlers
        ]
        # Retain broad-handler node elements in their derived traversal order.
        broad = [
            h for h in handlers
            if h.type is None or getattr(h.type, "id", "") in {"Exception", "BaseException"}
        ]
        # Require a final boundary catch that prevents raw traceback escape.
        assert broad, (
            f"{module.name} is a process entry point and catches nothing broadly. "
            f"An exception escaping here becomes a traceback, which is prose."
        )
        # Inspect each broad handler in source-derived traversal order.
        for handler in broad:
            # Decide whether any call below the handler invokes envelope production.
            emits = any(
                isinstance(n, ast.Call)
                and "envelope" in ast.dump(n)
                for n in ast.walk(handler)
            )
            # Reject broad catching that swallows rather than serializes the failure.
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

    @par Effects
    Prepends the reference source directory to this test process's import path.
    """
    # Make concrete errors importable before comparing emitted rule identifiers.
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

    # Decode the generated corpus and collapse known rule-id elements to an unordered set.
    corpus = Path(__file__).resolve().parent.parent.parent / "discipline"
    index = json.loads((corpus / "rules.json").read_text(encoding="utf-8"))
    known = {rule["id"] for rule in index["rules"]}

    # Exercise representative error instances in stable family order.
    for error in (InvariantViolated("an instant is at or after the epoch", -1),
                  ClockUnavailable("no reading"),
                  PruneInterrupted(("a.log",), ("b.log",))):
        # Serialize the concrete failure and retain its declared rule-id elements.
        record = envelope_module.from_error(error)  # type: ignore[attr-defined]
        named = record.get("rule_ids") or []
        # Reject an envelope that leaves contract localization to prose inference.
        assert named, (
            f"{type(error).__name__} produces an envelope naming no rule, so a "
            f"consumer must infer the contract from prose"
        )
        # Sort rule-id string elements absent from the generated corpus for diagnosis.
        unknown = sorted(set(named) - known)
        # Reject every public identifier that resolves to no normative rule.
        assert not unknown, (
            f"{type(error).__name__} names {unknown}, which the corpus does not "
            f"carry. An id that resolves to nothing costs a reader the trip."
        )
