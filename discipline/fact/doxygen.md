---
id: fact/doxygen
kind: fact
title: Doxygen for Python
tokens: 1975
load_when:
  - "doxygen"
  - "documentation comment"
  - "docstring format"
  - "@param"
  - "@return"
  - "generate documentation"
  - "Doxyfile"
verified: 2026-08-23
decay: quarters
python: ">=3.11"
---

# Doxygen for Python

What the documentation engine actually does with Python. The obligations are in
[law/DOC]; this module records which of them Doxygen 1.17.0 can decide.

Every behavioral claim below was reproduced by
`tools/test_doxygen_gate.py` against `enforce/fixtures/doxygen_probe`. The tests
run the executable, inspect generated HTML and XML, and damage reduced sources;
they do not infer capability from a configuration switch or a version string.

## Qualified tool identities

| Tool | Exact version | Purpose | Tag |
|---|---:|---|---|
| Doxygen | 1.17.0 | Python extraction and structured documentation | `VERSION-DEPENDENT` |
| Graphviz | 14.1.2 | call, caller and directory-dependency SVGs | `VERSION-DEPENDENT` |

Both are Conda pins in `environment.yml`, and `tools/check_env.py` runs
`doxygen --version` and `dot --version`. A package record without a successful
executable probe is not accepted as qualification.

## Storage forms

`ESTABLISHED` — with `PYTHON_DOCSTRING = NO`, ordinary Python docstrings become
Doxygen documentation blocks and commands such as `@param` are interpreted. At
the default `YES`, docstrings are rendered as preformatted text and commands can
silently become literal characters. A `"""!` prefix also selects Doxygen parsing
for one string, but the project setting is the reliable allocation mechanism.

`ESTABLISHED` — `##` before an entity and `##<` after an entity document Python
values that have no docstring slot. The probe proves both forms for module
values. Docstrings remain preferred wherever Python provides a slot because
`help()`, editors and other Python tooling can read them; `##` is reserved for a
named Doxygen entity without such a slot.

`ESTABLISHED` — the manual's Python recommendation
`OPTIMIZE_OUTPUT_JAVA = YES` produces the qualified entity layout.

## Extraction boundary measured at 1.17.0

| Python shape | Structured entity? | Qualified observation |
|---|---:|---|
| module, class, function and method | yes | entity page and contract text generated |
| property | yes | property accessor appears as a function member |
| enum and documented enum member | yes | class and value members generated |
| private module or class value with a default | yes | generated under `EXTRACT_PRIVATE = YES` |
| instance attribute assigned in `__init__` | yes | a nearby `##` block documents the member |
| annotation-only dataclass field | no | field is absent as a member; its preceding block may attach to the next representable field |
| local binding inside a callable | no | name occurs only in the source listing, never as a member |
| nested function | no | outer function is a member; nested definition is not |

`ESTABLISHED` — the last three rows are allocation limits, not permission to
leave the program unexplained. The AST documentation checks own annotation-only
fields, locals and nested definitions. Doxygen owns only shapes the probe proves
it can attach to without ambiguity.

## Contract commands

`ESTABLISHED` — `@brief`, `@param`, `@return`, `@retval`, `@throws` /
`@exception`, `@var`, `@package`, `@note`, `@warning`, `@pre`, `@post`,
`@invariant`, `@see` and `@deprecated` are the relevant contract vocabulary.
The probe requires rendered Parameters, Returns, Exceptions, Precondition,
Postcondition and Invariant sections. A named parameter that is absent from the
signature makes Doxygen exit non-zero.

`OPEN` — Doxygen does not natively interpret Google-style `Args:` / `Returns:`
or NumPy-style headings. Supporting those needs an input filter and creates a
second parser. The discipline uses Doxygen commands directly and does not select
a pydocstyle convention that demands headings the engine cannot read.

## Relationships and offline output

`ESTABLISHED` — `REFERENCES_RELATION` and `REFERENCED_BY_RELATION` create
textual call and caller links without Graphviz. `CALL_GRAPH`, `CALLER_GRAPH` and
`DIRECTORY_GRAPH` under `HAVE_DOT = YES` generate independent call, caller and
directory-dependency SVGs. The gate checks the relation prose and all three SVG
families; enabling the settings without a generated relationship does not pass.

`ESTABLISHED` — Doxygen 1.17's default `MERMAID_RENDER_MODE = AUTO` emits a
JavaScript asset containing a jsDelivr URL even when the source contains no
Mermaid diagram. `MERMAID_RENDER_MODE = CLI` removes that remote reference. The
v5 site uses no Mermaid feature and assumes no undeclared `mmdc` executable. The
probe rejects remote script, stylesheet or frame resources and the known CDN
string.

`ESTABLISHED` — two generations of the same probe produce a byte-identical HTML
tree. Machine-readable `Doxyfile.xml` is not part of that claim because it
records the intentionally fresh temporary output path.

## Warning behavior and residual defects

`ESTABLISHED` — `WARN_AS_ERROR = FAIL_ON_WARNINGS` emits every warning and then
exits non-zero. `GENERATE_HTML = YES` remains load-bearing: the earlier reduced
probe showed that disabling output, or generating XML alone, invents parameter
and return warnings. The gate therefore generates a temporary local site and
also counts source pages so a successful run over filtered input cannot pass.

`ESTABLISHED` — `WARN_IF_UNDOCUMENTED = YES` is usable again. The Doxygen 1.10
false warning for a documented dataclass field later read as bare `self.field`
does not reproduce on 1.17, while a genuinely undocumented function does fail.
The canonical Doxyfile therefore enables the warning.

`ESTABLISHED` — `WARN_NO_PARAMDOC` remains unusable. With
`WARN_IF_UNDOCUMENTED` enabled, Doxygen 1.17 still demands an `@return` from a
callable annotated `-> None`. `enforce/checks/doc_coverage.py` reads the return
annotation and owns parameter/result completeness, so `WARN_NO_PARAMDOC` stays
off.

`ESTABLISHED` — a code span whose final character is a single period still
aborts the block with `end of comment block while expecting command </tt>`.
Write the period outside the span. `enforce/checks/doc_style.py` reports the
offending span at its source location before an author has to diagnose Doxygen's
indirect message.

## Mechanism allocation

- Doxygen decides parseability, representable-entity presence, structured
  contract references and non-vacuous generated projection.
- `doc_coverage` decides exact AST binding documentation and parameter/result
  completeness, including shapes outside Doxygen's extraction model.
- `doc_style` decides source-local markup hazards and allocation form.
- the narration and naming checks decide ordinary implementation explanation;
  that prose is not a substitute for a Doxygen entity contract.

## Re-verifying

Run `python -m pytest tools/test_doxygen_gate.py` through both shipped
development legs. Re-run it whenever the exact Doxygen or Graphviz pin changes,
when the decay window expires, or when a Doxyfile relationship/output setting
changes. The dated release qualification artifact records platform package
builds and fixture hashes; this fact module records the behavior they imply.
