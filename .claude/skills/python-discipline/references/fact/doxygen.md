---
id: fact/doxygen
kind: fact
title: Doxygen for Python
tokens: 2540
load_when:
  - "doxygen"
  - "documentation comment"
  - "docstring format"
  - "@param"
  - "@return"
  - "generate documentation"
  - "Doxyfile"
verified: 2026-08-18
decay: quarters
python: ">=3.11"
---

# Doxygen for Python

What the documentation engine actually does with Python. The obligations are in [law/DOC];
this is the ground truth they are satisfiable against.

Every behavioural claim below was confirmed by running the installed Doxygen against a
probe file on 2026-08-18, not read from the manual and assumed. Two of them contradict
what the manual implies.

---

## Installed version

| Tool | Version | Tag |
|---|---|---|
| Doxygen | 1.10.0 | `VERSION-DEPENDENT` |

## Two comment forms, and why both are needed

`ESTABLISHED` — Doxygen reads Python documentation from two places:

1. **Docstrings.** By default they are rendered as *preformatted text* and special commands
   are **not** interpreted. Setting `PYTHON_DOCSTRING = NO` makes Doxygen parse them as
   documentation blocks with commands enabled. A per-docstring `"""!` prefix does the same
   for one docstring.
2. **`##` comment blocks** before an element, and `##<` after one.

`ESTABLISHED` — **Python has no docstring slot for a variable.** Module-level constants,
class attributes, dataclass fields and enum members can only be documented with a `##`
block or an explicit `@var`. This is why the discipline mandates both forms rather than
picking one: docstrings where Python has a slot, `##` where it does not.

`ESTABLISHED` — a docstring is visible to `help()`, to editors and to every other Python
tool; a `##` block is visible to none of them. That asymmetry is why docstrings are the
default and `##` is the exception, not a matter of taste.

`ESTABLISHED` — the manual recommends `OPTIMIZE_OUTPUT_JAVA = YES` for Python, because
Python's structure is closer to Java's than to C's.

### The forms, as verified

```python
"""! Module summary.
@package sample
"""

## The default retry budget.
MAX_RETRIES = 3


def documented(count: int, label: str) -> bool:
    """! Decide whether a thing holds.
    @param count how many were seen
    @param label what they were called
    @return True when the thing holds
    """
```

Both elements above produced **zero warnings** under the configuration below.

## Configuration that decides a check

| Option | Default | Set to | Effect |
|---|---|---|---|
| `PYTHON_DOCSTRING` | `YES` | `NO` | docstrings become real documentation blocks, commands enabled |
| `WARN_IF_UNDOCUMENTED` | `YES` | `NO` | see *Three defects* -- it misattributes documented fields; `doc_coverage` decides presence |
| `WARN_NO_PARAMDOC` | `NO` | `NO` | see *Three defects* -- it cannot see `-> None` as void; `doc_coverage` decides completeness |
| `WARN_IF_DOC_ERROR` | `YES` | `YES` | a parameter documented that does not exist, or documented twice |
| `WARN_IF_INCOMPLETE_DOC` | `YES` | `YES` | some but not all parameters documented |
| `WARN_AS_ERROR` | `NO` | `FAIL_ON_WARNINGS` | all warnings are emitted, then the process exits non-zero |
| `EXTRACT_ALL` | `NO` | `NO` | see below — `YES` silently disables the undocumented check |
| `OPTIMIZE_OUTPUT_JAVA` | `NO` | `YES` | Python-appropriate output |

`ESTABLISHED` — `WARN_AS_ERROR = FAIL_ON_WARNINGS` reports every warning and *then* exits
non-zero. Verified: a run with three defects exited 1 and printed all three; the same tree
with the defects fixed exited 0 and printed nothing.

`ESTABLISHED` — **the generator now runs, as gate step 10.** `tools/doxygen_gate.py`
builds the reference package through this configuration on every gate run. With
`WARN_IF_DOC_ERROR` and `WARN_IF_INCOMPLETE_DOC` on under `WARN_AS_ERROR`, that decides
[DOC-005] and [DOC-010]; the generated page count decides [DOC-011]. It decides nothing
about [DOC-007], because the two settings below are off — so `DOC-007` no longer claims
`auto:doxygen` and rests on `check:doc_coverage` alone, which is what the table already
said and the rule's tag did not.

`ESTABLISHED` — **`EXTRACT_ALL = YES` automatically disables `WARN_IF_UNDOCUMENTED`.**
Turning it on to "see everything" silently switches off the check that matters.

## Two traps, both verified by execution

`ESTABLISHED` — **the check run must generate HTML.** With every output generator disabled,
and also with `GENERATE_XML` alone, Doxygen reports *fully documented* functions as having
undocumented parameters and return values. Re-enabling `GENERATE_HTML` reduced the same
tree from seven spurious errors to the one genuine one.

Measured on the probe, same sources each time:

| Output generators | Errors reported | Correct? |
|---|---|---|
| none | 2, plus "No output formats selected!" | no — false positives |
| `GENERATE_XML` only | 7 | no — every function falsely reported |
| `GENERATE_HTML` | 1 | yes |

A documentation gate that runs Doxygen with output disabled "because we only want the
warnings" therefore fails closed on correct code, which is worse than not running it: it
trains people to ignore it.

`ESTABLISHED` — a docstring written without `"""!` while `PYTHON_DOCSTRING` is left at its
default is **not** an error. It degrades silently to preformatted text, and every `@param`
in it becomes literal characters in the output. Nothing warns. This is why the setting
belongs in the project's Doxyfile rather than relying on an author remembering a marker.

## Three defects that decide who owns which rule

All three were found by running the gate over a fully migrated tree of 28 files, and each
was reduced to a minimal reproducer before being acted on. Together they are why
`enforce/Doxyfile` turns two warning classes off: not because the rules are unwanted, but
because Doxygen's Python parser decides them wrongly and a better mechanism exists.

`ESTABLISHED` — **`WARN_NO_PARAMDOC` cannot see that `-> None` is void.** It demands an
`@return` from every procedure. On this repository that was 142 false demands against 3 true
ones. `enforce/checks/doc_coverage.py` reads the return annotation instead, so it asks only
for what is actually returned. DOC-007 completeness is therefore decided by the check, and
`WARN_NO_PARAMDOC` is off.

`ESTABLISHED` — **`WARN_IF_UNDOCUMENTED` re-reports a field that is documented**, whenever a
method refers to it *bare* as `self.field`, and it points at the use rather than at the
declaration. Reproduced minimally: in one class, a `##`-documented dataclass field read as
`len(str(self.bare))` is reported undocumented, while a sibling field read as
`self.other.values()` is not, and a genuinely undocumented field is reported either way — so
the detection works and the attribution does not. Six false reports here against zero true
ones. DOC-001 and DOC-002 presence is therefore decided by `doc_coverage`, which reports at
the declaration site where the fix belongs.

`ESTABLISHED` — **a code span ending in a single period aborts the comment block.** Doxygen
emits only `end of comment block while expecting command </tt>`, naming neither the span nor
the remedy. Bisected against 1.10.0:

| Span | Parses? |
|---|---|
| `` `foo.` ``, `` `x.` ``, `` `a.b.` ``, `` `e.g.` `` | no |
| `` `...` ``, `` `.leading` ``, `` `foo.bar` ``, `` `foo` `` | yes |

The trigger is a final period preceded by anything other than another period. Write the
period outside the span. `enforce/checks/doc_style.py` reports it under DOC-010 with the
span named, so the author does not have to bisect the file to find it.

## Commands that carry a Python contract

`ESTABLISHED` — the commands relevant here are `@brief`, `@param`, `@return`, `@retval`,
`@throws` / `@exception`, `@var`, `@package`, `@note`, `@warning`, `@pre`, `@post`,
`@invariant`, `@see` and `@deprecated`.

`OPEN` — Doxygen does not natively understand Google-style `Args:` / `Returns:` sections or
NumPy-style headings. Reaching them needs an input filter, which is a second tool in the
chain and another thing to keep in step. The discipline uses Doxygen's own commands
instead, which is also why a pydocstyle *convention* must not be configured — a convention
makes the linter demand section headings the engine cannot read.

## What this means for the other checkers

`ESTABLISHED` — ruff's pydocstyle rules `D100`–`D107` check that a docstring *exists* on a
module, package, class, method, function, magic method, nested class and `__init__`. They
do not look at variables, attributes or enum members, and they do not read `##` blocks.

`ESTABLISHED` — the docstring-coverage tool commonly paired with this is no longer
maintained; ruff's `D1` family is the current path for presence.

**Consequence for [law/DOC]:** three mechanisms, each covering what the others cannot.
ruff for docstring presence, a custom check for the elements that have no docstring slot,
and Doxygen itself for parseability and parameter completeness. Only the third can confirm
the actual requirement, and only the first two run when Doxygen is absent.

---

## Sources

The Doxygen manual's configuration and "Documenting the code" pages, plus direct execution
of Doxygen 1.10.0 against a probe file on 2026-08-18. The two traps in the section above
were found by execution and are not stated in the manual. Re-verify when `verified:`
exceeds the decay window, and whenever the Doxygen major version changes.
