"""A stale-file pruner, written to the discipline as a worked reference.

Four layers, dependencies pointing inward only (`ARCH-001`). Read
`enforce/fixtures/reference/README.md` for what each part demonstrates and why.
"""

from refpkg.shell.identity import BUILD_ID as BUILD_ID
from refpkg.shell.identity import VERSION as VERSION
from refpkg.shell.identity import runtime_identity as runtime_identity
