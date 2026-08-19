"""Make `refpkg` importable to the fixture's own suites.

The reference package is not installed and must not be: it exists to be *read* and
to be *scanned* by the fitness tests, not to be a dependency of the repository
that ships it. Putting its `src/` on the path here scopes that to this directory
alone, which is what a `conftest.py` is for.
"""

from __future__ import annotations

import sys
from pathlib import Path

## The reference package's source root, two levels up from this file then into src.
_SRC = Path(__file__).resolve().parent.parent / "src"

if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
