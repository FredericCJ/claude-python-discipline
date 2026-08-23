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

# Import the fixture path protocol only during static analysis.
if TYPE_CHECKING:
    from pathlib import Path


def conformance_payload() -> dict[str, object]:
    """A smallest complete registry with one combined test implementation.

    @return JSON-ready conformance model
    """
    # Render one internal contract with real, controlled, and term-level evidence.
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
    @param payload JSON-ready mapping whose unordered keys name registry sections
        and whose values hold their serialized contents
    @return written path

    @par Effects
    Creates or replaces the repository-local conformance registry.
    """
    # Select the declaration-owned registry path consumed by the checker.
    path = root / "contract-conformance.json"
    # Publish the complete registry as stable indented JSON.
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Return the persisted registry for focused mutation probes.
    return path


def complete_tree(tmp_path: Path) -> tuple[ContractConformanceCheck, Path]:
    """Build a complete structural contract, implementations, and tests.

    @param tmp_path fixture repository
    @return configured checker and source root

    @par Effects
    Creates a complete isolated project, implementation set, tests, and registries.
    """
    # Establish the complete declared repository and its bounded production root.
    declaration, source = declared_tree(tmp_path)
    # Start from a complete architecture before making its contract internal.
    architecture = architecture_payload()
    # Select the ordered contract-record elements from the architecture model.
    contracts = architecture["contracts"]
    assert isinstance(contracts, list)
    # Select the sole contract record whose direction controls conformance scope.
    contract = contracts[0]
    assert isinstance(contract, dict)
    # Bring the contract inside the repository's implementation-conformance boundary.
    contract["direction"] = "internal"
    # Publish the architecture join before implementation and evidence artifacts.
    write_architecture(tmp_path, architecture)
    # Publish the structural port that both implementations must satisfy.
    write_python(
        source,
        "pkg/ports/client.py",
        "from typing import Protocol\n\nclass Client(Protocol):\n"
        "    def request(self) -> str: ...\n",
    )
    # Publish the production implementation named by the conformance registry.
    write_python(
        source,
        "pkg/adapters/http/real.py",
        "class RealClient:\n    def request(self) -> str:\n        return 'ok'\n",
    )
    # Publish the controllable implementation used for deterministic fault coverage.
    write_python(
        source,
        "pkg/adapters/http/controlled.py",
        "class ControlledClient:\n    def request(self) -> str:\n        return 'ok'\n",
    )
    # Select the shared suite path that registers both implementation parameters.
    suite = tmp_path / "tests/contract/test_client_contract.py"
    # Materialize and publish the common contract suite before resolving evidence ids.
    suite.parent.mkdir(parents=True)
    suite.write_text(
        'PARAMETERS = ("real", "controlled")\n\ndef test_request_succeeds(): ...\n'
        "\ndef test_requests_are_serialized(): ...\n"
        "\ndef test_equal_requests_agree(): ...\n",
        encoding="utf-8",
    )
    # Select the focused fault-suite path cited by error and timeout evidence.
    fault = tmp_path / "tests/fault/test_client.py"
    # Materialize and publish scheduled-failure evidence after the common suite.
    fault.parent.mkdir(parents=True)
    fault.write_text(
        "def test_invalid_request(): ...\n\ndef test_deadline_stops_retry(): ...\n",
        encoding="utf-8",
    )
    # Publish the conformance registry only after all referenced artifacts exist.
    write_conformance(tmp_path, conformance_payload())
    # Configure a fresh checker from the declaration owning the fixture tree.
    check = ContractConformanceCheck()
    check.declaration = declaration
    # Return the configured mechanism with its bounded production subject.
    return check, source


def _first_diagnostic(check: ContractConformanceCheck, source: Path) -> str | None:
    """Return the first diagnostic emitted by a fixture check.

    @param check configured conformance checker
    @param source fixture source root
    @return stable diagnostic id, or None for a clean run
    """
    # Preserve ordered findings so the first refusal identifies the broken invariant.
    findings = check.run([source])
    # Collapse acceptance to no diagnostic and refusal to its leading stable identity.
    return None if not findings else findings[0].diagnostic_id


def test_complete_semantic_conformance_registry_is_accepted(tmp_path: Path) -> None:
    """One controllable implementation may also supply scheduled faults.

    @param tmp_path fixture repository
    """
    # Build the complete structural contract and evidence graph as the accepting control.
    check, source = complete_tree(tmp_path)
    assert check.run([source]) == []


def test_structural_representation_requires_a_protocol(tmp_path: Path) -> None:
    """Representation intent is checked against the actual port declaration.

    @param tmp_path fixture repository
    """
    # Build the complete structural control before replacing its protocol declaration.
    check, source = complete_tree(tmp_path)
    # Publish a concrete class whose name matches but structure intent does not.
    write_python(source, "pkg/ports/client.py", "class Client:\n    pass\n")
    assert _first_diagnostic(check, source) == "CONTRACT003_REPRESENTATION"


def test_nominal_representation_and_inheritance_are_accepted(tmp_path: Path) -> None:
    """A repository may choose an abstract nominal boundary explicitly.

    @param tmp_path fixture repository
    """
    # Build the complete control before switching representation strategy.
    check, source = complete_tree(tmp_path)
    # Start from the registry whose implementation and evidence joins remain valid.
    payload = conformance_payload()
    # Select the ordered contract-record elements for the representation mutation.
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    # Select the sole contract record shared with architecture.
    contract = contracts[0]
    assert isinstance(contract, dict)
    # Declare nominal conformance before publishing an abstract base boundary.
    contract["representation"] = "nominal"
    # Publish the mutated registry and matching abstract contract.
    write_conformance(tmp_path, payload)
    write_python(
        source,
        "pkg/ports/client.py",
        "from abc import ABC, abstractmethod\n\nclass Client(ABC):\n"
        "    @abstractmethod\n    def request(self) -> str: ...\n",
    )
    # Rewrite each implementation element to inherit the same nominal boundary.
    for relative, symbol in (
        ("pkg/adapters/http/real.py", "RealClient"),
        ("pkg/adapters/http/controlled.py", "ControlledClient"),
    ):
        # Publish the current implementation at its registry-owned module path.
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
    # Build structurally conforming implementations before selecting nominal semantics.
    check, source = complete_tree(tmp_path)
    # Start from the complete registry before changing representation alone.
    payload = conformance_payload()
    # Select the ordered contract-record elements for the focused mutation.
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    # Select the sole contract record whose representation is under test.
    contract = contracts[0]
    assert isinstance(contract, dict)
    # Demand nominal inheritance while leaving implementations structurally coincident.
    contract["representation"] = "nominal"
    # Publish the contradictory registry and nominal abstract boundary.
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
    # Build the complete evidence graph before narrowing controlled capabilities.
    check, source = complete_tree(tmp_path)
    # Start from the complete implementation registry.
    payload = conformance_payload()
    # Select the ordered contract-record elements for the implementation mutation.
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    # Select the sole internal contract record.
    contract = contracts[0]
    assert isinstance(contract, dict)
    # Select its ordered real-and-controlled implementation elements.
    implementations = contract["implementations"]
    assert isinstance(implementations, list)
    # Select the controlled implementation record required for fault evidence.
    controlled = implementations[1]
    assert isinstance(controlled, dict)
    # Remove scheduled-fault control while retaining basic controllability.
    controlled["capabilities"] = ["controllable"]
    # Publish the narrowed implementation claim for validation.
    write_conformance(tmp_path, payload)
    assert _first_diagnostic(check, source) == "CONTRACT004_IMPLEMENTATION_SET"


def test_unregistered_suite_parameter_is_rejected(tmp_path: Path) -> None:
    """Every implementation must be visibly selected by the same suite source.

    @param tmp_path fixture repository

    @par Effects
    Creates a complete fixture repository, then replaces its shared suite registry.
    """
    # Build both registered implementations before narrowing suite selection.
    check, source = complete_tree(tmp_path)
    # Select the common suite whose parameter registry must cover both implementations.
    suite = tmp_path / "tests/contract/test_client_contract.py"
    # Replace the suite registry with a production-only parameter set.
    suite.write_text('PARAMETERS = ("real",)\n', encoding="utf-8")
    assert _first_diagnostic(check, source) == "CONTRACT006_SUITE_REGISTRY"


def test_missing_contract_term_trace_is_rejected(tmp_path: Path) -> None:
    """Success, every error, and each interaction term remain traceable.

    @param tmp_path fixture repository
    """
    # Build the complete term-evidence registry before removing one obligation.
    check, source = complete_tree(tmp_path)
    # Start from the complete conformance model.
    payload = conformance_payload()
    # Select the ordered contract-record elements for evidence mutation.
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    # Select the sole internal contract record.
    contract = contracts[0]
    assert isinstance(contract, dict)
    # Select its ordered term-evidence elements.
    evidence = contract["evidence"]
    assert isinstance(evidence, list)
    # Remove the final timeout term so the required term set becomes incomplete.
    evidence.pop()
    # Publish the incomplete trace registry for validation.
    write_conformance(tmp_path, payload)
    assert _first_diagnostic(check, source) == "CONTRACT005_TERM_TRACE"


def test_success_cannot_be_excused_as_not_applicable(tmp_path: Path) -> None:
    """A registry cannot replace executable happy-path evidence with prose.

    @param tmp_path fixture repository
    """
    # Build the complete executable-evidence control before excusing success.
    check, source = complete_tree(tmp_path)
    # Start from the complete conformance model.
    payload = conformance_payload()
    # Select the ordered contract-record elements for evidence mutation.
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    # Select the sole internal contract record.
    contract = contracts[0]
    assert isinstance(contract, dict)
    # Select its ordered term-evidence elements.
    evidence = contract["evidence"]
    assert isinstance(evidence, list)
    # Select the mandatory happy-path evidence record.
    success = evidence[0]
    assert isinstance(success, dict)
    # Remove executable proof and substitute an inadmissible prose excuse.
    success["test"] = None
    success["not_applicable"] = "Assumed by construction."
    # Publish the excused success claim for validation.
    write_conformance(tmp_path, payload)
    assert _first_diagnostic(check, source) == "CONTRACT005_TERM_TRACE"


def test_registry_must_cover_exactly_internal_architecture_contracts(tmp_path: Path) -> None:
    """Evidence cannot silently target a stale or differently named contract.

    @param tmp_path fixture repository
    """
    # Build the complete architecture join before changing registry identity.
    check, source = complete_tree(tmp_path)
    # Start from the complete conformance model.
    payload = conformance_payload()
    # Select the ordered contract-record elements for identity mutation.
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    # Select the sole registry contract joined to architecture.
    contract = contracts[0]
    assert isinstance(contract, dict)
    # Replace the architecture identity with a stale registry-only name.
    contract["id"] = "stale_contract"
    # Publish the broken architecture join for validation.
    write_conformance(tmp_path, payload)
    assert _first_diagnostic(check, source) == "CONTRACT002_ARCHITECTURE_JOIN"


def test_suite_path_cannot_escape_the_repository(tmp_path: Path) -> None:
    """Conformance never depends on a parent or sibling test checkout.

    @param tmp_path fixture repository
    """
    # Build the complete local evidence graph before redirecting its suite.
    check, source = complete_tree(tmp_path)
    # Start from the complete conformance model.
    payload = conformance_payload()
    # Select the ordered contract-record elements for suite-path mutation.
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    # Select the sole contract whose suite must remain repository-local.
    contract = contracts[0]
    assert isinstance(contract, dict)
    # Redirect conformance to a peer checkout outside the governed unit.
    contract["suite"] = "../peer/tests/test_contract.py"
    # Publish the escaping suite reference for validation.
    write_conformance(tmp_path, payload)
    assert _first_diagnostic(check, source) == "CONTRACT006_SUITE_REGISTRY"


def test_explicit_absence_is_valid_without_internal_contracts(tmp_path: Path) -> None:
    """Applications with no internal effect boundary need no ceremonial adapters.

    @param tmp_path fixture repository
    """
    # Establish a declared repository with no internal effect-boundary implementation.
    declaration, source = declared_tree(tmp_path)
    # Publish architecture containing no internal contract obligations.
    write_architecture(tmp_path, architecture_payload())
    # Publish an empty registry paired with an explicit local absence rationale.
    write_conformance(
        tmp_path,
        {
            "schema_version": 1,
            "contracts": [],
            "contract_absence": "No internal effect or independently varying contract exists.",
        },
    )
    # Configure the conformance mechanism from the owning project declaration.
    check = ContractConformanceCheck()
    check.declaration = declaration
    assert check.run([source]) == []
