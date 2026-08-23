"""The diagnostic envelope schema is well formed and actually discriminates.

`law/DIAG` specifies the envelope and names `enforce/schema/diagnostic.schema.json`
as what every escaping error validates against. The file shipped for the first
time in v1.1.0; these cases keep it from being a document nobody executes.

**This is not `DIAG-001`'s mechanism.** That rule names
`fitness:test_envelope_conforms`, which would check that a *producer* emits a
conformant record, and it remains unbuilt and counted in `enforce/ENFORCEMENT.md`.
No function here is named that, deliberately: `mechanism_is_implemented` resolves
a `fitness:` tag by looking for a function of that name, so naming one would make
the corpus report a mechanism it does not have -- the exact dishonesty the
`enforcement` field exists to expose.

What is checked here is narrower and worth having on its own: that the schema
parses, accepts a correct envelope, and rejects each shape it claims to reject.
A schema nothing has been observed to reject has not been shown to constrain
anything (`FLOW-007`).

    pytest enforce/fitness/test_diagnostic_schema.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import pytest

## The validator library. Imported through `importorskip` so a tree without
## it skips rather than errors -- the schema is still shipped and still
## correct; what is unavailable is the means to check it here.
jsonschema = pytest.importorskip("jsonschema", reason="jsonschema not installed")

## The schema under test, three levels up from this file then into enforce/.
SCHEMA_PATH: Final = (
    Path(__file__).resolve().parent.parent / "schema" / "diagnostic.schema.json"
)

## Diagnostic-field-name keys mapped to representative JSON values. Insertion
## order improves review stability but has no schema meaning.
CONFORMANT: Final[dict[str, Any]] = {
    "code": "pkg.domain.invariant.outline_cycle",
    "layer": "domain",
    "expected": "the outline graph is acyclic",
    "actual": "cycle a -> b -> a",
    "value": {"node": "a"},
    "rule_ids": ["TYPE-004", "ARCH-002"],
    "cause_chain": [{"type": "ValueError", "message": "duplicate edge"}],
    "notes": ["while loading outline.json"],
    "correlation_id": "01J9Z3',",
    "remediation": "Remove the edge b -> a; the loader rejects cycles.",
}


def validator() -> Any:
    """A validator over the shipped schema, with the schema itself checked first.

    @return a draft 2020-12 validator
    """
    # Decode the schema field mapping before asking its declared draft to validate it.
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    # Return a validator only after its own schema structure is accepted.
    return jsonschema.Draft202012Validator(schema)


def test_the_schema_file_ships() -> None:
    """law/DIAG has named this path since v1.0.0; for two releases it was absent."""
    # Require the named durable schema artifact to exist at its public contract path.
    assert SCHEMA_PATH.exists(), f"{SCHEMA_PATH} is named by DIAG-001 and missing"


def test_a_conformant_envelope_is_accepted() -> None:
    """The guard must not reject the shape the corpus documents."""
    # Require zero validator-error elements for the complete conformant control.
    assert list(validator().iter_errors(CONFORMANT)) == []


@pytest.mark.parametrize("field", ["code", "layer", "expected", "actual",
                                   "cause_chain", "remediation"])
def test_a_missing_required_field_is_rejected(field: str) -> None:
    """Each required field is required, one at a time.

    `remediation` is the one worth naming: without it the record says what broke
    and leaves the next step to be inferred, which is machine-diagnosable but not
    machine-repairable.

    @param field the field removed from an otherwise conformant envelope
    """
    # Copy diagnostic-field keys and values in insertion order, which schema ignores.
    envelope = {k: v for k, v in CONFORMANT.items() if k != field}
    # Require at least one validator-error message element for the absent required field.
    assert [e.message for e in validator().iter_errors(envelope)], (
        f"{field} is declared required and its absence was accepted"
    )


def test_a_code_that_is_not_namespaced_is_rejected() -> None:
    """DIAG-002: a greppable namespaced code, not a class name in disguise."""
    # Copy field-name keys to values in insertion order, which schema ignores.
    envelope = {**CONFORMANT, "code": "OutlineCycle"}
    # Require one or more validator-error message elements for the unqualified code.
    assert [e.message for e in validator().iter_errors(envelope)]


def test_an_unknown_layer_is_rejected() -> None:
    """ARCH-001 fixes the four layers; a fifth would make the field underivable."""
    # Copy field-name keys to values in insertion order, which schema ignores.
    envelope = {**CONFORMANT, "layer": "infrastructure"}
    # Require one or more validator-error message elements for the unknown layer.
    assert [e.message for e in validator().iter_errors(envelope)]


def test_an_adapter_fault_without_its_port_is_rejected() -> None:
    """An adapter fault names the contract it crossed, or it localizes nothing."""
    # Copy field-name keys to values in insertion order, which schema ignores.
    envelope = {**CONFORMANT, "layer": "adapter", "code": "pkg.adapter.fs.denied"}
    # Preserve validator-error message elements in the library's deterministic order.
    messages = [e.message for e in validator().iter_errors(envelope)]
    # Require the conditional diagnostic to identify the absent port contract.
    assert any("port" in m for m in messages), messages


def test_an_adapter_fault_with_its_port_is_accepted() -> None:
    """The conditional must not fire on a record that satisfies it."""
    # Copy field-name keys to values in insertion order, which schema ignores.
    envelope = {**CONFORMANT, "layer": "adapter", "code": "pkg.adapter.fs.denied",
                "port": "FileStore", "operation": "write"}
    # Require zero validator-error elements for the conditionally complete record.
    assert list(validator().iter_errors(envelope)) == []


def test_a_domain_fault_needs_no_port() -> None:
    """Requiring one everywhere would force a producer to invent it."""
    # Copy diagnostic-field keys to values in insertion order, which schema ignores.
    envelope = dict(CONFORMANT)
    # Establish port absence before proving that the schema accepts this domain record.
    assert "port" not in envelope
    assert list(validator().iter_errors(envelope)) == []


def test_a_malformed_rule_id_is_rejected() -> None:
    """Rule ids are public API; a payload carrying an invented one misleads."""
    # Copy field-name keys to values in insertion order, which schema ignores.
    envelope = {**CONFORMANT, "rule_ids": ["arch-2"]}
    # Require one or more validator-error message elements for the malformed public ID.
    assert [e.message for e in validator().iter_errors(envelope)]
