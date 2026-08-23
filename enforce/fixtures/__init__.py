"""The reference package, and one way to break it.

Every fitness test needs two trees: a conformant one to prove it does not fire,
and a broken one to prove it does. Hand-maintaining thirty-one broken trees would
guarantee that most of them drifted out of step with the reference and quietly
stopped testing anything.

So there is one conformant tree -- `reference/` -- and `broken_copy`, which
copies it and breaks exactly one thing. The helpers live in `broken.py`; this
module only re-exports them, so a fitness test can write the sentence it is
testing:

    root = broken_copy(tmp_path, drop=["src/refpkg/adapters/clock/faulty.py"])

Nothing broken is ever committed, so pytest cannot collect it and no reader can
mistake it for an example.
"""

from __future__ import annotations

from .broken import (
    REFERENCE,
    broken_copy,
    modules_in,
    package_root,
    reference_root,
)

## Public symbol-name elements in stable export order. Re-exporting keeps one
## import path even though the helpers are implemented next door.
__all__ = [
    "REFERENCE",
    "broken_copy",
    "modules_in",
    "package_root",
    "reference_root",
]
