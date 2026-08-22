"""Runtime identity tests. Oracle: contract."""

from refpkg import BUILD_ID, VERSION, runtime_identity


def test_runtime_identity_names_version_and_build() -> None:
    """Delivered diagnostics can distinguish the contract and exact fixture build."""
    assert runtime_identity() == {"version": VERSION, "build_id": BUILD_ID}
