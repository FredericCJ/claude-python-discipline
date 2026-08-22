"""Build and version identity emitted at the process boundary."""

from collections.abc import Mapping

## Version of the worked reference contract and package surface.
VERSION = "4.0.0-reference"
## Reproducible build identity for the source fixture shipped in this release.
BUILD_ID = "discipline-reference-v4"


def runtime_identity() -> Mapping[str, str]:
    """Return the identity fields emitted with runtime diagnostics.

    @return immutable-facing version and build-id mapping
    """
    return {"version": VERSION, "build_id": BUILD_ID}
