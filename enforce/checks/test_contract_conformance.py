"""Proof-of-failure tests for semantic boundary conformance evidence."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from checks.contract_conformance import ContractConformanceCheck
from checks.test_architecture_checks import (
    architecture_payload,
    declared_tree,
    write_architecture,
    write_python,
)

if TYPE_CHECKING:
    from pathlib import Path


def conformance_payload() -> dict[str, object]:
    """A smallest complete registry with one combined test implementation.

    @return JSON-ready conformance model
    """
    return {
        "schema_version": 1,
        "contract_absence": None,
        "contracts": [
            {
                "id": "request_contract",
                "module": "pkg.ports.client",
                "symbol": "Client",
                "representation": "structural",
                "implementations": [
                    {
                        "id": "real_client",
                        "module": "pkg.adapters.http.real",
                        "symbol": "RealClient",
                        "kind": "real",
                        "capabilities": [],
                        "parameter": "real",
                    },
                    {
                        "id": "controlled_client",
                        "module": "pkg.adapters.http.controlled",
                        "symbol": "ControlledClient",
                        "kind": "test",
                        "capabilities": ["controllable", "scheduled_fault"],
                        "parameter": "controlled",
                    },
                ],
                "suite": "tests/contract/test_client_contract.py",
                "evidence": [
                    {
                        "operation": "request",
                        "term": "success",
                        "error": None,
                        "test": "tests/contract/test_client_contract.py::test_request_succeeds",
                        "not_applicable": None,
                    },
                    {
                        "operation": "request",
                        "term": "error",
                        "error": "invalid_request",
                        "test": "tests/fault/test_client.py::test_invalid_request",
                        "not_applicable": None,
                    },
                    {
                        "operation": "request",
                        "term": "ordering",
                        "error": None,
                        "test": (
                            "tests/contract/test_client_contract.py::"
                            "test_requests_are_serialized"
                        ),
                        "not_applicable": None,
                    },
                    {
                        "operation": "request",
                        "term": "idempotency",
                        "error": None,
                        "test": "tests/contract/test_client_contract.py::test_equal_requests_agree",
                        "not_applicable": None,
                    },
                    {
                        "operation": "request",
                        "term": "concurrency",
                        "error": None,
                        "test": None,
                        "not_applicable": "The contract serializes all calls before this boundary.",
                    },
                    {
                        "operation": "request",
                        "term": "timeout",
                        "error": None,
                        "test": "tests/fault/test_client.py::test_deadline_stops_retry",
                        "not_applicable": None,
                    },
                ],
            }
        ],
    }


def write_conformance(root: Path, payload: dict[str, object]) -> Path:
    """Write one conformance registry fixture.

    @param root fixture repository
    @param payload JSON-ready model
    @return written path
    """
    path = root / "contract-conformance.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def complete_tree(tmp_path: Path) -> tuple[ContractConformanceCheck, Path]:
    """Build a complete structural contract, implementations, and tests.

    @param tmp_path fixture repository
    @return configured checker and source root
    """
    declaration, source = declared_tree(tmp_path)
    architecture = architecture_payload()
    contracts = architecture["contracts"]
    assert isinstance(contracts, list)
    contract = contracts[0]
    assert isinstance(contract, dict)
    contract["direction"] = "internal"
    write_architecture(tmp_path, architecture)
    write_python(
        source,
        "pkg/ports/client.py",
        "from typing import Protocol\n\nclass Client(Protocol):\n"
        "    def request(self) -> str: ...\n",
    )
    write_python(
        source,
        "pkg/adapters/http/real.py",
        "class RealClient:\n    def request(self) -> str:\n        return 'ok'\n",
    )
    write_python(
        source,
        "pkg/adapters/http/controlled.py",
        "class ControlledClient:\n    def request(self) -> str:\n        return 'ok'\n",
    )
    suite = tmp_path / "tests/contract/test_client_contract.py"
    suite.parent.mkdir(parents=True)
    suite.write_text(
        'PARAMETERS = ("real", "controlled")\n\ndef test_request_succeeds(): ...\n'
        "\ndef test_requests_are_serialized(): ...\n"
        "\ndef test_equal_requests_agree(): ...\n",
        encoding="utf-8",
    )
    fault = tmp_path / "tests/fault/test_client.py"
    fault.parent.mkdir(parents=True)
    fault.write_text(
        "def test_invalid_request(): ...\n\ndef test_deadline_stops_retry(): ...\n",
        encoding="utf-8",
    )
    write_conformance(tmp_path, conformance_payload())
    check = ContractConformanceCheck()
    check.declaration = declaration
    return check, source


def _first_diagnostic(check: ContractConformanceCheck, source: Path) -> str | None:
    """Return the first diagnostic emitted by a fixture check.

    @param check configured conformance checker
    @param source fixture source root
    @return stable diagnostic id, or None for a clean run
    """
    findings = check.run([source])
    return None if not findings else findings[0].diagnostic_id


def test_complete_semantic_conformance_registry_is_accepted(tmp_path: Path) -> None:
    """One controllable implementation may also supply scheduled faults.

    @param tmp_path fixture repository
    """
    check, source = complete_tree(tmp_path)
    assert check.run([source]) == []


def test_structural_representation_requires_a_protocol(tmp_path: Path) -> None:
    """Representation intent is checked against the actual port declaration.

    @param tmp_path fixture repository
    """
    check, source = complete_tree(tmp_path)
    write_python(source, "pkg/ports/client.py", "class Client:\n    pass\n")
    assert _first_diagnostic(check, source) == "CONTRACT003_REPRESENTATION"


def test_nominal_representation_and_inheritance_are_accepted(tmp_path: Path) -> None:
    """A repository may choose an abstract nominal boundary explicitly.

    @param tmp_path fixture repository
    """
    check, source = complete_tree(tmp_path)
    payload = conformance_payload()
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    contract = contracts[0]
    assert isinstance(contract, dict)
    contract["representation"] = "nominal"
    write_conformance(tmp_path, payload)
    write_python(
        source,
        "pkg/ports/client.py",
        "from abc import ABC, abstractmethod\n\nclass Client(ABC):\n"
        "    @abstractmethod\n    def request(self) -> str: ...\n",
    )
    for relative, symbol in (
        ("pkg/adapters/http/real.py", "RealClient"),
        ("pkg/adapters/http/controlled.py", "ControlledClient"),
    ):
        write_python(
            source,
            relative,
            f"from pkg.ports.client import Client\n\nclass {symbol}(Client):\n"
            "    def request(self) -> str:\n        return 'ok'\n",
        )
    assert check.run([source]) == []


def test_nominal_implementation_must_inherit_the_contract(tmp_path: Path) -> None:
    """A nominal declaration cannot be satisfied by structural coincidence.

    @param tmp_path fixture repository
    """
    check, source = complete_tree(tmp_path)
    payload = conformance_payload()
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    contract = contracts[0]
    assert isinstance(contract, dict)
    contract["representation"] = "nominal"
    write_conformance(tmp_path, payload)
    write_python(
        source,
        "pkg/ports/client.py",
        "from abc import ABC, abstractmethod\n\nclass Client(ABC):\n"
        "    @abstractmethod\n    def request(self) -> str: ...\n",
    )
    assert _first_diagnostic(check, source) == "CONTRACT003_REPRESENTATION"


def test_missing_scheduled_fault_capability_is_rejected(tmp_path: Path) -> None:
    """A controllable healthy double does not cover foreign failure behavior.

    @param tmp_path fixture repository
    """
    check, source = complete_tree(tmp_path)
    payload = conformance_payload()
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    contract = contracts[0]
    assert isinstance(contract, dict)
    implementations = contract["implementations"]
    assert isinstance(implementations, list)
    controlled = implementations[1]
    assert isinstance(controlled, dict)
    controlled["capabilities"] = ["controllable"]
    write_conformance(tmp_path, payload)
    assert _first_diagnostic(check, source) == "CONTRACT004_IMPLEMENTATION_SET"


def test_unregistered_suite_parameter_is_rejected(tmp_path: Path) -> None:
    """Every implementation must be visibly selected by the same suite source.

    @param tmp_path fixture repository
    """
    check, source = complete_tree(tmp_path)
    suite = tmp_path / "tests/contract/test_client_contract.py"
    suite.write_text('PARAMETERS = ("real",)\n', encoding="utf-8")
    assert _first_diagnostic(check, source) == "CONTRACT006_SUITE_REGISTRY"


def test_missing_contract_term_trace_is_rejected(tmp_path: Path) -> None:
    """Success, every error, and each interaction term remain traceable.

    @param tmp_path fixture repository
    """
    check, source = complete_tree(tmp_path)
    payload = conformance_payload()
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    contract = contracts[0]
    assert isinstance(contract, dict)
    evidence = contract["evidence"]
    assert isinstance(evidence, list)
    evidence.pop()
    write_conformance(tmp_path, payload)
    assert _first_diagnostic(check, source) == "CONTRACT005_TERM_TRACE"


def test_success_cannot_be_excused_as_not_applicable(tmp_path: Path) -> None:
    """A registry cannot replace executable happy-path evidence with prose.

    @param tmp_path fixture repository
    """
    check, source = complete_tree(tmp_path)
    payload = conformance_payload()
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    contract = contracts[0]
    assert isinstance(contract, dict)
    evidence = contract["evidence"]
    assert isinstance(evidence, list)
    success = evidence[0]
    assert isinstance(success, dict)
    success["test"] = None
    success["not_applicable"] = "Assumed by construction."
    write_conformance(tmp_path, payload)
    assert _first_diagnostic(check, source) == "CONTRACT005_TERM_TRACE"


def test_registry_must_cover_exactly_internal_architecture_contracts(tmp_path: Path) -> None:
    """Evidence cannot silently target a stale or differently named contract.

    @param tmp_path fixture repository
    """
    check, source = complete_tree(tmp_path)
    payload = conformance_payload()
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    contract = contracts[0]
    assert isinstance(contract, dict)
    contract["id"] = "stale_contract"
    write_conformance(tmp_path, payload)
    assert _first_diagnostic(check, source) == "CONTRACT002_ARCHITECTURE_JOIN"


def test_suite_path_cannot_escape_the_repository(tmp_path: Path) -> None:
    """Conformance never depends on a parent or sibling test checkout.

    @param tmp_path fixture repository
    """
    check, source = complete_tree(tmp_path)
    payload = conformance_payload()
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    contract = contracts[0]
    assert isinstance(contract, dict)
    contract["suite"] = "../peer/tests/test_contract.py"
    write_conformance(tmp_path, payload)
    assert _first_diagnostic(check, source) == "CONTRACT006_SUITE_REGISTRY"


def test_explicit_absence_is_valid_without_internal_contracts(tmp_path: Path) -> None:
    """Applications with no internal effect boundary need no ceremonial adapters.

    @param tmp_path fixture repository
    """
    declaration, source = declared_tree(tmp_path)
    write_architecture(tmp_path, architecture_payload())
    write_conformance(
        tmp_path,
        {
            "schema_version": 1,
            "contracts": [],
            "contract_absence": "No internal effect or independently varying contract exists.",
        },
    )
    check = ContractConformanceCheck()
    check.declaration = declaration
    assert check.run([source]) == []
