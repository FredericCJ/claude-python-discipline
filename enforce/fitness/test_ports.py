"""The reference proves representation and semantic conformance evidence.

**Oracle: canonical contract and conformance models.** The checker joins every
internal architecture contract to one local boundary type, implementation
capabilities, a shared suite, and term-level evidence. Discrimination mutations
damage representation, fault capability, and suite selection independently.
"""

from __future__ import annotations

from checks import project
from checks.contract_conformance import ContractConformanceCheck
from decides import decides
from fixtures import reference_root


@decides("ARCH-024", "ARCH-025", "TEST-020")
def test_reference_contract_conformance() -> None:
    """The reference registry is complete without prescribing a physical triad."""
    # Construct the checker against the validated reference project declaration.
    root = reference_root()
    check = ContractConformanceCheck()
    # Attach the declaration before running the checker over its governed source root.
    check.declaration = project.parse(root / "pyproject.toml")
    findings = check.run([root / "src"])
    # Require the complete port and adapter evidence join to remain conformant.
    assert findings == [], "\n".join(finding.render(root) for finding in findings)
