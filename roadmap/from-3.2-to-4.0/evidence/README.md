# Frozen v3 evidence

This directory is the reproducible input to the v4 work. It records what was
actually present and what actually ran before v4 changed the rule model. It is
evidence about the discipline and five standalone adopters; it is not a verdict
about the SIGSIM parent application.

- `baseline.json` records immutable commits, vendored releases, environment
  digests, repository sizes, commands, timings, and gate outcomes.
- `findings.json` classifies each harvested observation and preserves the local
  evidence that made it actionable.
- `scope.json` is the negative boundary: it prevents later work from turning a
  component observation into a parent-repository or whole-system obligation.

## Reproduction contract

All Windows commands use
`C:\Users\frede\miniforge3\envs\claude\python.exe`. The discipline baseline was
also run in an isolated Linux checkout with Python 3.13.14 and Doxygen 1.10.0 in
a micromamba environment named `claude`. Its Python packages came from:

```text
python tools/check_env.py --print-requirements
python -m pip install -r gate-requirements.txt
python tools/gate.py
```

The Windows discipline run used the same final command. Adopter commands and
the one corrected invocation needed to reproduce an intended gate are retained
verbatim in `baseline.json`.

The source adopter worktrees were clean before and after measurement. No parent
or sibling checkout was read by an adopter gate. The independent Linux clone
was detached at the recorded discipline commit. Manual ledger observations are
marked `observed`; they cannot satisfy a future automated gate.

## Interpretation limits

A zero exit code means only that every listed step accepted that checkout. In
particular, it does not erase the v3 evidence gaps: 14 named mechanisms were
unbuilt, 93 rules classified as mechanically decided had no must-reject case,
and mutation testing produced no Windows verdict. Those facts are inputs to the
v4 evidence model, not retroactive failures assigned to adopter product code.
