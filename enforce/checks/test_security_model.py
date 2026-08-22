"""Proof-of-failure tests for local trust and data-classification records."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from checks import project
from checks.security_model import SecurityModelCheck
from checks.test_architecture_checks import architecture_payload
from checks.test_project import declare, v4

if TYPE_CHECKING:
    from pathlib import Path

## One repository-local behavior test cited by every fixture record.
EVIDENCE = "tests/test_security.py::test_boundary"


def security_payload(*, sensitive: bool = False) -> dict[str, object]:
    """Build one complete local security model.

    @param sensitive whether to include an activated sensitive data class
    @return JSON-ready model
    """
    return {
        "schema_version": 1,
        "trust_boundaries": [{
            "id": "request_entry",
            "contracts": ["request_contract"],
            "inbound_trust": "untrusted",
            "assumptions": ["The caller can supply malformed input."],
            "validations": ["Parse into the typed request before policy use."],
            "trust_ceases_at": "The typed request is rendered to an external response.",
            "evidence": EVIDENCE,
        }],
        "data_classes": [{
            "id": "request_content",
            "classification": "secret" if sensitive else "internal",
            "sources": ["request_entry"],
            "allowed_roles": ["adapters", "application", "domain"],
            "allowed_sinks": ["structured_response"],
            "retention": "Held for one request and then released.",
            "redaction": "Raw content is excluded from diagnostic detail.",
            "evidence": EVIDENCE,
        }],
        "sensitive_data_absence": (
            None if sensitive else "The fixture intentionally handles no secret data."
        ),
    }


def _tree(
    tmp_path: Path,
    *,
    sensitive: bool = False,
    payload: dict[str, object] | None = None,
) -> tuple[SecurityModelCheck, Path]:
    """Create one complete security-model fixture repository.

    @param tmp_path fixture repository
    @param sensitive enabled sensitive-data capability
    @param payload optional security model override
    @return configured checker and production source root
    """
    body = v4()
    if sensitive:
        body = body.replace("sensitive_data = false", "sensitive_data = true")
    declaration_path = declare(tmp_path, body)
    source = tmp_path / "src/pkg"
    source.mkdir(parents=True)
    (source / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    evidence = tmp_path / "tests/test_security.py"
    evidence.parent.mkdir()
    evidence.write_text("def test_boundary(): ...\n", encoding="utf-8")
    (tmp_path / "architecture.json").write_text(
        json.dumps(architecture_payload()), encoding="utf-8",
    )
    (tmp_path / "security-model.json").write_text(
        json.dumps(payload or security_payload(sensitive=sensitive)), encoding="utf-8",
    )
    check = SecurityModelCheck()
    check.declaration = project.parse(declaration_path)
    return check, source


def _diagnostic(check: SecurityModelCheck, source: Path) -> str | None:
    """Return the first stable diagnostic from one fixture.

    @param check configured security checker
    @param source production source root
    @return diagnostic id or None for acceptance
    """
    findings = check.run([source])
    return None if not findings else findings[0].diagnostic_id


def _records(payload: dict[str, object], key: str) -> list[dict[str, object]]:
    """Narrow one mutable record array in a JSON fixture.

    @param payload JSON-ready model
    @param key root record-array field
    @return mutable records
    """
    value = payload[key]
    assert isinstance(value, list)
    assert all(isinstance(item, dict) for item in value)
    return cast("list[dict[str, object]]", value)


def test_complete_local_security_model_is_accepted(tmp_path: Path) -> None:
    """Every contract has trust and every data flow has an exposure policy.

    @param tmp_path fixture repository
    """
    check, source = _tree(tmp_path)
    assert check.run([source]) == []


def test_sensitive_capability_with_classification_is_accepted(tmp_path: Path) -> None:
    """A classified record and null absence satisfy sensitive activation.

    @param tmp_path fixture repository
    """
    check, source = _tree(tmp_path, sensitive=True)
    assert check.run([source]) == []


def test_every_architecture_contract_requires_one_boundary(tmp_path: Path) -> None:
    """A local contract cannot silently bypass trust decisions.

    @param tmp_path fixture repository
    """
    payload = security_payload()
    _records(payload, "trust_boundaries")[0]["contracts"] = ["unknown_contract"]
    check, source = _tree(tmp_path, payload=payload)
    assert _diagnostic(check, source) == "SECMODEL002_CONTRACT_JOIN"


def test_boundary_requires_validation_before_trust(tmp_path: Path) -> None:
    """An untrusted entry cannot establish trust through an empty checklist.

    @param tmp_path fixture repository
    """
    payload = security_payload()
    _records(payload, "trust_boundaries")[0]["validations"] = []
    check, source = _tree(tmp_path, payload=payload)
    assert _diagnostic(check, source) == "SECMODEL001_SCHEMA"


def test_boundary_evidence_cannot_escape_the_repository(tmp_path: Path) -> None:
    """A sibling's test cannot satisfy this repository's trust claim.

    @param tmp_path fixture repository
    """
    payload = security_payload()
    _records(payload, "trust_boundaries")[0]["evidence"] = "../peer/test.py"
    check, source = _tree(tmp_path, payload=payload)
    assert _diagnostic(check, source) == "SECMODEL003_TRUST_BOUNDARY"


def test_data_source_must_join_a_trust_boundary(tmp_path: Path) -> None:
    """A classified flow cannot enter through an unnamed boundary.

    @param tmp_path fixture repository
    """
    payload = security_payload()
    _records(payload, "data_classes")[0]["sources"] = ["peer_endpoint"]
    check, source = _tree(tmp_path, payload=payload)
    assert _diagnostic(check, source) == "SECMODEL005_EXPOSURE"


def test_data_exposure_names_only_local_roles(tmp_path: Path) -> None:
    """A peer or integrator cannot become this repository's data owner.

    @param tmp_path fixture repository
    """
    payload = security_payload()
    _records(payload, "data_classes")[0]["allowed_roles"] = ["system_integrator"]
    check, source = _tree(tmp_path, payload=payload)
    assert _diagnostic(check, source) == "SECMODEL005_EXPOSURE"


def test_sensitive_class_cannot_hide_behind_false_capability(tmp_path: Path) -> None:
    """A secret classification refutes sensitive_data=false.

    @param tmp_path fixture repository
    """
    payload = security_payload()
    _records(payload, "data_classes")[0]["classification"] = "secret"
    check, source = _tree(tmp_path, payload=payload)
    assert _diagnostic(check, source) == "SECMODEL004_CLASSIFICATION"


def test_sensitive_capability_requires_a_sensitive_class(tmp_path: Path) -> None:
    """An enabled capability cannot be satisfied by a prose absence.

    @param tmp_path fixture repository
    """
    check, source = _tree(
        tmp_path,
        sensitive=True,
        payload=security_payload(sensitive=False),
    )
    assert _diagnostic(check, source) == "SECMODEL004_CLASSIFICATION"
