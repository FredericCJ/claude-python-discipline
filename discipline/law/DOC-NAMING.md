---
id: law/DOC-NAMING
kind: law
rule_prefix: DOC
title: Project Naming Model
tokens: 992
load_when:
  - "identifier grammar"
  - "abbreviation"
  - "semantic dimension"
  - "generated name"
  - "documentation-model.json"
applies_to: ["**/*.py", "documentation-model.json"]
requires: ["law/DOC"]
decay: none
python: ">=3.11"
---

# Project Naming Model

Names identify concepts; documentation defines them. The discipline owns the schema and
generic consistency checks. Each governed repository owns its domain vocabulary,
dimensions, abbreviations, representations, and generated-name boundaries in the
versioned `documentation-model.json` named by `[tool.agent-discipline]`.

---

## Declaration

### DOC-022 · The project declares a strict documentation model  [BINDING] [check:documentation_model]
Every application or component repository MUST declare one local JSON model covering its
structured engine, production/test/maintenance scopes, explicit foreign and generated
ownership, controlled abbreviations, optional identifier grammars, generated-name
markers and mappings, and mechanically inferable semantic properties. Unknown fields,
duplicate ownership, escaping paths, and a missing source-root owner MUST fail.
- **Why** Domain-specific policy left in prose cannot drive a check; permissive parsing
  turns every typo into a silent waiver.
- **Check** `python -m checks.documentation_model`
- **See** [meta/SCOPE] · [frame/documentation]

---

## Semantic dimensions

### DOC-023 · Declared identifier grammars preserve dimension order  [BINDING] [check:doc_naming]
Where the model declares a scope grammar, every governed identifier in that scope MUST
match it or appear in its narrow exclusion list. Named regular-expression groups MUST
equal the declared dimensions in broad-to-specific order.
- **Why** Independent dimensions that collapse into an ad hoc token cannot be searched,
  reordered, or checked consistently. Group order makes the project's decision explicit
  without imposing one domain's dimensions on another.
- **Check** `python -m checks.doc_naming`

### DOC-024 · Abbreviations have one controlled scoped meaning  [BINDING] [check:doc_naming]
An abbreviation MUST use its exact declared spelling and one meaning in every overlapping
scope. Mechanically identifiable undeclared initialisms MUST fail. Tokens in all-uppercase
constant names, abbreviations, and contractions that syntax cannot distinguish from words
remain a [DOC-028] challenge.
- **Why** An abbreviation is cheap only while every reader expands it the same way.
- **Check** `python -m checks.doc_naming` for declarations, casing, and unambiguous
  initialisms · `python -m checks.adversarial_review` through [DOC-028] for domain judgment

---

## Representation boundaries

### DOC-025 · Generated vocabulary remains visibly derived  [BINDING] [check:doc_naming]
Every identifier carrying a declared generated marker MUST map exactly to its canonical
domain term. A mapping key without its marker MUST fail. Generated or serialization terms
MUST NOT silently redefine canonical domain vocabulary.
- **Why** Code generation should expose a representation boundary, not let tool-owned
  spelling become the language in which the domain is specified.
- **Check** `python -m checks.doc_naming`
- **See** [law/DEP] · [examples/documentation]

Topological words such as `upstream`, `downstream`, `parent`, and `child` identify
structure only. Behavioral meaning belongs in the entity contract or semantic-step
narration. Silent truncation remains prohibited by [law/API]; structure that has a Python
type belongs in that type rather than in compressed identifier punctuation.
