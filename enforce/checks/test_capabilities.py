"""Proof-of-failure tests for the additive capability manifest."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from checks import project
from checks.capabilities import CapabilitiesCheck
from checks.test_architecture_checks import architecture_payload
from checks.test_project import declare, v4

# Import path typing only while static analyzers evaluate fixture contracts.
if TYPE_CHECKING:
    from pathlib import Path


def _tree(
    tmp_path: Path,
    *,
    enabled: tuple[project.Capability, ...] = (),
    source: str = "",
    filename: str = "module.py",
    published: bool = False,
) -> tuple[CapabilitiesCheck, Path]:
    """Create one locally declared capability fixture.

    @param tmp_path fixture repository
    @param enabled capability-enum elements enabled in declared tuple order
    @param source production module body
    @param filename production module basename
    @param published true when architecture carries a published contract; false
        when the representative contract remains internal
    @return configured check and source root

    @par Effects
    Writes a declaration, production module, and architecture model in the isolated
    repository before configuring a new capability checker.
    """
    # Start from a complete v4 declaration with every capability disabled.
    body = v4()
    # Enable requested capability elements in caller-declared order.
    for capability in enabled:
        # Replace only the selected manifest fact while preserving all other defaults.
        body = body.replace(
            f"{capability.value} = false",
            f"{capability.value} = true",
        )
    # Write the resulting project declaration and prepare its production source root.
    declaration_path = declare(tmp_path, body)
    source_root = tmp_path / "src/pkg"
    source_root.mkdir(parents=True)
    # Persist the requested production witness or a harmless default module.
    (source_root / filename).write_text(source or "VALUE = 1\n", encoding="utf-8")
    # Retrieve the contract-record elements from a complete architecture model.
    architecture = architecture_payload()
    contracts = architecture["contracts"]
    assert isinstance(contracts, list)
    # Select the representative first contract and set its publication direction.
    contract = contracts[0]
    assert isinstance(contract, dict)
    contract["direction"] = "published" if published else "internal"
    # Persist the modified architecture model beside the declaration.
    (tmp_path / "architecture.json").write_text(
        json.dumps(architecture), encoding="utf-8",
    )
    # Construct the checker and attach the parsed local declaration.
    check = CapabilitiesCheck()
    check.declaration = project.parse(declaration_path)
    # Return the configured mechanism with its production inventory root.
    return check, source_root


def _diagnostics(check: CapabilitiesCheck, source: Path) -> set[str | None]:
    """Collect stable diagnostics from one fixture.

    @param check configured capability check
    @param source production source root
    @return unordered emitted diagnostic-id elements
    """
    # Collapse finding records to their unique stable diagnostic identifiers.
    return {finding.diagnostic_id for finding in check.run([source])}


def test_declared_capability_may_exceed_static_inference(tmp_path: Path) -> None:
    """Intent may activate obligations that syntax cannot observe.

    @param tmp_path fixture repository
    """
    # Build a manifest whose declared sensitive-data intent exceeds static inference.
    check, source = _tree(
        tmp_path,
        enabled=(project.Capability.SENSITIVE_DATA,),
    )
    # Require declared intent to activate obligations without being called overdeclared.
    assert check.run([source]) == []


def test_published_contract_requires_public_api(tmp_path: Path) -> None:
    """The local contract model is an inference input.

    @param tmp_path fixture repository
    """
    # Build an architecture with a published contract but no public-API capability.
    check, source = _tree(tmp_path, published=True)
    # Require local contract direction to activate the missing capability diagnostic.
    assert "CAP002_UNDERDECLARED" in _diagnostics(check, source)


@pytest.mark.parametrize(
    ("source", "capability"),
    [
        ("import pathlib\n", project.Capability.FILESYSTEM_IO),
        ("import sqlite3\n", project.Capability.PERSISTENT_STATE),
        ("import socket\n", project.Capability.NETWORK_IO),
        ("import subprocess\n", project.Capability.LAUNCHES_SUBPROCESSES),
        ("import threading\n", project.Capability.CONCURRENCY),
        ("def erase(path):\n    path.unlink()\n", project.Capability.DESTRUCTIVE_EFFECTS),
        (
            "def bounded(process):\n    process.wait(timeout=1)\n",
            project.Capability.BOUNDED_LATENCY,
        ),
        (
            "import os\nTOKEN = os.getenv('SERVICE_API_KEY')\n",
            project.Capability.SENSITIVE_DATA,
        ),
    ],
)
def test_source_witness_cannot_be_declared_false(
    tmp_path: Path,
    source: str,
    capability: project.Capability,
) -> None:
    """Each narrow inference family turns its matching obligation on.

    @param tmp_path fixture repository
    @param source production source carrying one observation
    @param capability fact that observation implies
    """
    # Build one source witness while leaving its implied capability declared false.
    check, root = _tree(tmp_path, source=source)
    findings = check.run([root])
    # Require one underdeclaration finding to name the exact implied capability.
    assert any(
        finding.diagnostic_id == "CAP002_UNDERDECLARED"
        and capability.value in finding.message
        for finding in findings
    )


def test_generator_module_requires_generated_artifacts(tmp_path: Path) -> None:
    """A production build module cannot hide the derived-artifact obligation.

    @param tmp_path fixture repository
    """
    # Build a production generator-shaped module without generated-artifact intent.
    check, source = _tree(tmp_path, filename="build_schema.py")
    # Require the module identity to activate the missing capability diagnostic.
    assert "CAP002_UNDERDECLARED" in _diagnostics(check, source)


def test_lifecycle_ownership_requires_launch_authority(tmp_path: Path) -> None:
    """A repository cannot own subprocesses it says it never creates.

    @param tmp_path fixture repository
    """
    # Declare lifecycle ownership without the launch capability it logically requires.
    check, source = _tree(
        tmp_path,
        enabled=(project.Capability.OWNS_SUBPROCESS_LIFECYCLE,),
    )
    # Require the manifest relation diagnostic independently of source inference.
    assert "CAP001_MANIFEST_RELATION" in _diagnostics(check, source)


def test_test_modules_do_not_activate_production_capabilities(tmp_path: Path) -> None:
    """Harness technology is not attributed to the delivered unit.

    @param tmp_path fixture repository
    """
    # Place a network import in a test-shaped filename rather than production source.
    check, source = _tree(
        tmp_path,
        source="import socket\n",
        filename="test_harness.py",
    )
    # Require test harness technology to remain outside delivered capability inference.
    assert check.run([source]) == []
