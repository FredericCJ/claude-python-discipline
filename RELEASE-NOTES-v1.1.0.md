# Python Engineering Discipline — v1.1.0

A maintenance release with one theme: **v1.0.0 could not be built, and nothing said so.**

The archive builds now, it is built only from a tree that passes its own gate, and the four
defects that reached adopters are fixed. The rule corpus is unchanged — no rule was added,
removed or retagged, and the count of binding rules nothing decides is exactly what it was.

```bash
python .agent/tools/integrate.py --dry-run    # preview; writes nothing
python .agent/tools/integrate.py              # apply
python .agent/tools/integrate.py --check      # CI: present and current?
python .agent/tools/integrate.py --remove     # uninstall
```

## The headline

**`tools/release.py` could not build the archive on the machine that maintains it.** The
leak scanner derives its blocking patterns from the building account's identifiers, which
is right — the scan should protect whoever runs it, not only its author. But it escaped
each identifier as a bare literal, and this host is named `MAIN`. That compiled to a
case-insensitive `main` and matched `def main(`, `__main__` and every mention of the branch
in almost every file: thousands of blocking findings, and a build that could never complete.

Each identifier is now bounded so it matches a whole word only, and one that is a common
source word is dropped outright — **and the drop is reported**, because a scan running with
fewer signals than usual is exactly the thing that must not be silent. Three
proof-of-failure tests cover it, including the literal case: a host named `main` still
builds, and a genuine identifier is still caught.

## What else changed

**The release is gated on the gate.** `release.py` had three gates of its own — prune,
empty ledger, leak scan — and every one asks whether the *archive* is well formed. None
asked whether the corpus it was cut from is. It now runs all seven steps from
`tools/gate.py` before staging anything and refuses on any failure. `--skip-gate` exists,
prints that the archive is unverified, and must not be used to publish.

**Gate step 1 is green.** It was red: 275 findings under ruff 0.16.3, eight of them `C901`
— self-violations of `ARCH-016`, a rule this corpus enforces through that exact ruff code.
All eight are fixed by decomposition (`build_graph`, `nav`, `learn`, `vendor`), every safe
autofix is applied, and type-only imports are moved. `D401` went the other way and the
reasoning is written into the template: it demands an imperative where `DOC-009` asks for
the noun phrase that states an accessor's contract, so on `The exception types a handler
names` the two rules cannot both be obeyed, and the binding one with a mechanism wins.

The residual 131 are held by a ratchet, `tools/lint_gate.py`, built to the same design as
the `V080` one: the exact `(file, code)` pairs, not a count, so raising one integer cannot
switch it off. **No ruff code that decides a binding rule may enter the baseline**, checked
before the baseline is consulted at all — and that guard fails even for a code already
recorded, which is the only way a ratchet could quietly disable a mechanism.

**The environment is pinned and verifiable.** `environment.yml` declares it and
`tools/check_env.py` decides whether the running interpreter matches, which is what
`DEP-005` and `DEP-006` ask for. The checker imports nothing it verifies — a verifier that
needs a working environment cannot run in the one situation it exists for. CI now installs
from that declaration instead of its own copy; the copy had already drifted, pinning ruff
0.16.3 where the maintainer environment ran 0.16.2, a three-finding difference and
therefore a different verdict.

**`tokens:` no longer depends on what is installed.** `count_tokens` imported tiktoken when
present and fell back to a character ratio when absent, so `build_index.py` wrote different
bytes on two machines running the same command over the same corpus — and nothing reported
it. Every committed value was the fallback; the tokenizer branch shipped for two releases
and never once ran here. `meta/SCHEMA.md` said the field was tiktoken-measured. The ratio is
now the defined measurement, the spec says so, and **no token count changed**, which is the
confirmation the diagnosis was right.

## The four adopter-facing defects

- **`nav.py` printed paths that did not resolve.** From a consuming repository it answered
  `discipline/law/ARCH.md:51` for a file living at `.agent/discipline/law/ARCH.md:51`. Paths
  are now resolved against the tool's own root and expressed from the caller's working
  directory; in the source repository the output is unchanged.
- **`python -m checks` did not exist.** `enforce/checks/__init__.py` had documented it since
  the checks were written. It exists now, discovers every check by import rather than from a
  list, and returns one exit code.
- **An adopter got no dependency manifest.** `.agent/requirements.txt` names PyYAML and
  jsonschema, states that `learn.py`, `integrate.py` and `vendor.py` are standard-library
  only, and a build fails without it.
- **`enforce/schema/diagnostic.schema.json` was missing.** `law/DIAG` has specified the
  diagnostic envelope — the artifact the whole thesis turns on — since v1.0.0 and named this
  path as what every escaping error validates against. The directory was empty. The schema
  ships now, with tests proving it accepts a conformant record and rejects each shape it
  claims to. **It is not `DIAG-001`'s mechanism**: that rule names
  `fitness:test_envelope_conforms`, which would check that a *producer* emits a conformant
  record, and it remains unbuilt and counted.

## Known limits

Stated here rather than discovered later. The corpus exists to remove the failure mode where
a document hides what it does not do, and a release note is not exempt.

**Most binding rules are still not mechanically decided.** 61 of 167, unchanged from v1.0.0.
55 of 87 named mechanisms are still unimplemented and `tools/validate.py` still reports 106
`V080` warnings. Nothing in this release moved that number, deliberately: two artifacts were
added that look like mechanisms and are not — the envelope schema and `checks/__main__.py` —
and neither is claimed as one. **Treat an unbuilt rule as advice, not as a gate.**

**131 lint findings remain**, ratcheted and non-growing. No protected code is among them.

**Portability is verified on win32 and Python 3.13 only.** This is a downgrade from what
v1.0.0's notes implied. `.github/workflows/gate.yml` covers ubuntu, macOS and Windows and
**has never executed** — the repository has no remote, so no run has ever happened. The
hostname fix above is precisely a different-machine defect and is reasoned and tested, not
observed on another host. The archive is byte-reproducible across two builds *here*;
cross-machine reproducibility is untested.

**The documentation gate proves presence, not truth.** All 38 covered files pass presence,
style and behaviour-preservation. A reviewer pass over an earlier version of the same files
found 90 claims that were confidently false about the code they described. This release
verified the claims in the shipping documents and the executable claims — commands, paths,
counts — in the covered files, and fixed six. The wider prose re-audit has not been
repeated, and the 90 were never itemized, so it would be a fresh pass over every file.

**Doxygen is still not installed in the maintainer environment**, so
`test_doxygen_version_matches_recorded` skips and the 1.10.0 pin that two `Doxyfile`
settings depend on is unverified. `docgate.py` deliberately excludes the Doxygen build, so
"passes Doxygen" remains a release-time measurement by hand, not a property any gate
defends.

**`ARCH` and `TEST` have still never been exercised against a real hexagonal project.**
They are the largest families and the ones carrying the thesis. Expect the first real
adoption to find rules that are ambiguous or wrong at the edges. Record those with
`learn.py record --scope discipline`.

**The learning loop still has no outcomes.** 55 entries, 0 reported outcomes, nothing
promoted. Your ledger starts empty, so you begin where that measurement begins.

## Verifying what you got

```bash
python .agent/tools/vendor.py check .     # any vendored file edited in place?
python .agent/tools/integrate.py --check  # block present and current?
python .agent/tools/nav.py rule ARCH-002  # the path it prints should open
pip install -r .agent/requirements.txt    # PyYAML and jsonschema, nothing else
```

`MANIFEST.json` names both the release and a content hash over every upstream file. The
hash is what `--check` compares — a release name can be claimed, a hash can only be
computed.
