---
id: law/DOC-NARRATION
kind: law
rule_prefix: DOC
title: Implementation Narration
tokens: 1372
load_when:
  - "local variable comment"
  - "semantic step"
  - "control flow comment"
  - "data flow comment"
  - "quasi-literate"
  - "comment association"
applies_to: ["**/*.py"]
requires: ["law/DOC"]
decay: none
python: ">=3.11"
---

# Implementation Narration

Ordinary single-hash comments explain execution that Doxygen cannot attach to a stable
entity: local bindings, control and data flow, transformations, branch purpose, state
transitions, errors, resource sequencing, and temporary representations.

This is the procedural layer. [law/DOC] owns entity contracts. A `##` block or docstring
cannot satisfy a rule here, and an ordinary comment cannot replace entity documentation.

The unit is a **semantic step**, not a physical line. One block may explain a compound
operation and the bindings it introduces. Linter directives, type comments, commented-out
code, separators, and Doxygen blocks carry no narrative credit.

---

## Local bindings

### DOC-016 · Every local binding has semantic documentation  [BINDING] [check:doc_coverage]
Every non-parameter name bound inside a callable MUST resolve to an ordinary comment that
states what the value represents in that operation. This includes assignments,
destructuring, loop and comprehension targets, context-manager aliases, exception aliases,
assignment expressions, and pattern captures. Parameters remain owned by [DOC-007].
- **Why** A type and identifier constrain shape and hint at purpose; neither defines the
  temporary representation or its role in the procedure.
- **Check** `python -m checks.doc_coverage`; each finding names the binding shape, name,
  line, expected owner, and remediation.
- **See** [DOC-002] · [frame/documentation] · [examples/documentation]

---

## Semantic operations

### DOC-017 · Governed execution steps are narrated  [BINDING] [check:doc_narration]
Every governed branch, loop, return path, loop exit or continuation, exception path,
resource sequence, pattern dispatch, state transition, and mechanically identifiable
external effect MUST have ordinary implementation narration.
- **Why** These are the points where execution changes direction, representation, state,
  or the outside world. Leaving them implicit forces a reader to execute the syntax
  mentally before deciding what procedure it implements.
- **Check** `python -m checks.doc_narration`
- **See** [law/FLOW] · [law/ERR] · [law/EFCT]

### DOC-018 · A semantic step has exactly one nearby owner  [BINDING] [check:doc_narration]
A qualifying full-line block immediately above the first statement starts a semantic step
and owns contiguous statements in that same AST suite until a blank line or another
qualifying block. A qualifying trailing comment owns only its statement and ends an
inherited step. A compound operation also owns the bindings introduced by its target and
directly contained expression. Nested suites inherit nothing; an exception handler may use
the first comment inside its body. Zero owners and multiple owners MUST fail; distant
file-level prose MUST NOT float into a local step.
- **Why** A checker choosing arbitrarily creates documentation that appears attached while
  a reader can reasonably attach it elsewhere. Ambiguity is information, not permission.
- **Check** `python -m checks.doc_narration`

### DOC-019 · Narration states semantics, not Python tokens  [BINDING] [check:doc_narration]
Implementation narration MUST name the technical or domain operation, represented
information, ordering, constraint, or reason. It MUST NOT merely translate syntax such as
“iterate over items,” “set the value,” or “return the result.” Known migration-scaffolding
forms such as “compute X using Y for later Z logic,” syntax copied into a “guarded path,”
and placeholder “Details” clauses MUST NOT receive credit merely because identifiers add
lexical novelty. Semantic restatement is permitted here and is distinct from implementation
narration inside an entity contract.
- **Why** Token paraphrase adds another line to maintain without reducing inference.
  Semantic narration lets the source be followed as a documented procedure.
- **Check** `python -m checks.doc_narration` rejects the narrow case in which no
  informative vocabulary exists outside the operation's syntax and rejects its closed set
  of known scaffolding templates. Truth and adequacy remain [DOC-028] review residuals.
- **See** [DOC-009] · [meta/CONFLICTS] · [examples/documentation]

---

## Current truth

Comments MUST describe the current procedure, never obsolete history, an expired
workaround, or a quality assertion. Durable rationale belongs in the current contract or
an applicable decision record; version control owns chronology. Detectable directives and
commented-out code receive no credit under [DOC-016]–[DOC-019]. Semantic obsolescence is
challenged under [DOC-028].

Generated Python is held to the same rules. Its generator owns the correction; editing the
derived file is not remediation.
