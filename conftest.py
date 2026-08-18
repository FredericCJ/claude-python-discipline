"""Make `tools/` and `enforce/` importable so their suites run from the repo root.

`tools/test_validate.py` imports `validate`; `enforce/checks/test_checks.py` imports
`checks`. Both are ordinary packages that happen not to live on the default path.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

for _subdir in ("tools", "enforce"):
    _path = str(_ROOT / _subdir)
    if _path not in sys.path:
        sys.path.insert(0, _path)
