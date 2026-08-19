"""The gate: every command a change must pass before it is offered.

One definition, in one place. `FLOW-009` requires the gate to exist somewhere
runnable rather than in prose that drifts, and three things now read it:

* `enforce/fitness/test_meta.py` proves each entry names a real file and starts;
* `tools/release.py` refuses to build an archive from a tree that fails it;
* `.github/workflows/gate.yml` spells the same nine steps out, because a
  workflow step needs its own name and failure boundary --
  `test_meta.py::test_the_workflow_mirrors_the_gate` is what keeps that copy
  honest.

Kept as data rather than as a script so a caller can decide what to do with a
failure. Running it is `subprocess`; deciding about it is the caller's business.

It lives under `tools/` rather than `enforce/` for two practical reasons: both
readers already have `tools/` importable -- the test through `conftest.py`, the
release script by sitting in it -- and `tools/` is inside the documentation
gate's covered set, where `enforce/gate.py` would not have been.
"""

from __future__ import annotations

import sys
from typing import Final

## Every command a change must pass, in the order a person would want them: the
## cheap and specific first, the whole test suite last, so the fastest signal
## arrives first. `sys.executable` rather than a bare `python`, because a bare
## `python` on a machine with more than one environment is a coin toss -- and on
## the machine this was written on it resolves to an interpreter with no pytest,
## where the suite reports nothing and looks like it passed.
GATE: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("format and lint", (sys.executable, "tools/lint_gate.py")),
    ("rule corpus", (sys.executable, "tools/validate.py")),
    ("navigation graph", (sys.executable, "tools/build_graph.py", "--check")),
    ("generated artefacts", (sys.executable, "tools/build_index.py", "--check")),
    ("skill mirror", (sys.executable, "tools/build_skill_mirror.py", "--check")),
    ("documentation", (sys.executable, "tools/docgate.py", "--all")),
    # Two structural checks over enforce/fixtures/reference/, added once that
    # fixture gave them a subject. Both are wrapped in a script rather than named
    # directly, because both underlying tools exit 0 when pointed at nothing --
    # `python -m importlinter.cli` checks no contract and says nothing at all,
    # and mypy reports "no issues found in 0 source files". A gate entry that
    # cannot tell that from success is the defect these entries exist to remove,
    # so each wrapper asserts how much it actually examined.
    ("import contracts", (sys.executable, "tools/import_gate.py")),
    ("types", (sys.executable, "tools/type_gate.py")),
    ("tests", (sys.executable, "-m", "pytest", "-q")),
)
