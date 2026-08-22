---
id: law/DOC
kind: law
title: Documentation Comments
tokens: 2392
load_when:
  - "docstring"
  - "documentation comment"
  - "doxygen"
  - "@param"
  - "@return"
  - "document this function"
  - "undocumented"
applies_to: ["**/*.py"]
grounds_on: ["fact/doxygen", "fact/py-typing"]
requires: ["law/TYPE"]
decay: none
python: ">=3.11"
---

# Documentation Comments

**Every element of the code carries a documentation comment.** Not the public surface, not
the non-obvious parts — every element. The comments are written for a full-featured Doxygen
to consume, and they are in the code whether or not documentation is ever generated.

The generated site is optional. The comments are not. A repository that never runs Doxygen
must still be one an agent can read without inferring intent from identifiers.

Two forms, because Python offers only one slot and Doxygen needs two:

- **Docstrings** for anything Python gives a docstring slot — module, package, class,
  function, method, property. Visible to `help()`, to editors and to every other tool.
- **`##` blocks** for the elements Python has no slot for — module constants, class
  attributes, dataclass fields, enum members. A `##<` block documents the element before it.

---

## Presence

### DOC-001 · Every module, class, function and method is documented  [BINDING] [auto:ruff:D100] [check:doc_coverage]
Every module, package, class, function, method, magic method and initializer MUST carry a
docstring. Private and internal elements are included: the rule is about the code, not
about its audience.
- **Why** An identifier is a hint; a contract is a statement. An agent that must infer
  intent from a name is guessing, and a wrong guess is indistinguishable from a right one.
- **Check** `ruff check` (rules `D100`–`D107`) · `python -m checks.doc_coverage`

### DOC-002 · Every named value is documented  [BINDING] [check:doc_coverage]
Module-level constants, class attributes, dataclass fields and enum members MUST carry a
documentation comment, since Python provides no docstring slot for them. Under a project
declaring Doxygen it MUST be a `##` block, which is the only form that engine reads.
- **Why** These are exactly the elements a reader most often needs and the linters cannot
  see; leaving them out makes "every element" mean "every element with a convenient slot".
- **Check** `python -m checks.doc_coverage`, which reads the declared engine
- **See** [fact/doxygen] · [DOC-014]

### DOC-003 · Documentation is present whether or not it is generated  [BINDING] [auto:ruff:D100] [check:doc_coverage]
The presence checks MUST run in the ordinary gate, not in a documentation job. A repository
that never builds documentation is held to the same standard as one that publishes it.
- **Why** Documentation tied to a build step is documentation that lapses the moment the
  build is switched off, and nobody notices until someone needs it.
- **Check** `ruff check` and `python -m checks.doc_coverage`, both in the standard gate
- **See** [law/FLOW]

---

## Form

### DOC-004 · Documentation lives in docstrings wherever Python has a slot  [BINDING] [check:doc_style]
An element with a docstring slot MUST be documented by its docstring, not by a preceding
`##` block. `##` is reserved for the elements that have no slot.
- **Why** A `##` block is invisible to `help()`, to editors and to every other Python tool,
  so documentation written there does not exist for a Python consumer.
- **Check** `python -m checks.doc_style`

### DOC-005 · Docstrings are parsed as documentation, not text  [BINDING] [auto:doxygen]
The project's Doxyfile MUST set `PYTHON_DOCSTRING` so that special commands are
interpreted.
- **Why** Left at its default, a docstring full of `@param` renders as literal characters
  and nothing warns. The failure is silent, which is the worst kind.
- **Check** `doxygen enforce/Doxyfile` with the setting in force
- **See** [fact/doxygen]

### DOC-006 · A brief statement comes first  [BINDING] [auto:ruff:D205]
The first line MUST be a single sentence stating what the element is or does, followed by a
blank line before any further detail.
- **Why** It is the line that appears in every index, every tooltip and every summary; an
  element whose first line is a continuation has no summary anywhere.
- **Check** `ruff check` (rules `D205`, `D400`, `D415`)

### DOC-007 · Every parameter, result and raised exception is documented  [BINDING] [check:doc_coverage]
A documented callable MUST document each parameter, its result, and each exception it
raises. Under a project declaring Doxygen these MUST be written `@param`, `@return` or
`@retval`, and `@throws`, which is the vocabulary that engine reads.
- **Why** These are the questions a failing call raises, and the ones a signature alone
  cannot answer: what a parameter *means*, what the result *signifies*, when it *fails*.
- **Check** `doxygen enforce/Doxyfile` with `WARN_NO_PARAMDOC` and `WARN_IF_INCOMPLETE_DOC` ·
  `python -m checks.doc_coverage`, which reads the declared engine
- **See** [DOC-014]

### DOC-008 · Types are not restated in prose  [BINDING] [check:doc_style]
Documentation MUST NOT repeat a parameter's or return value's type. The signature carries
the type; the documentation carries the meaning.
- **Why** A type written twice diverges once, and the copy the checker cannot see is the
  one that goes stale.
- **Check** `python -m checks.doc_style`
- **See** [law/TYPE]

---

## Content

### DOC-009 · Documentation states the contract, not the mechanism  [BINDING] [check:doc_style]
Documentation MUST state what an element guarantees — inputs, result, invariants, error
modes, ordering — and MUST NOT merely restate its name or narrate its implementation.
- **Why** A comment that restates the name adds a second thing to keep in step and answers
  nothing; a comment describing the implementation is wrong after the first refactor.
- **Check** `python -m checks.doc_style`
- **See** [law/API] · [frame/spec] · [examples/documentation]

### DOC-010 · A Doxygen run produces no warnings  [BINDING] [auto:doxygen]
Documentation MUST be complete and well formed enough that the engine reports nothing, with
warnings configured as errors.
- **Why** This is the only mechanism that checks the actual requirement rather than a
  proxy for it: it is the engine the comments are written for.
- **Check** `doxygen enforce/Doxyfile` with `WARN_AS_ERROR = FAIL_ON_WARNINGS`

### DOC-011 · The documentation check generates output  [BINDING] [auto:doxygen]
The Doxyfile used for checking MUST leave HTML generation enabled.
- **Why** With output disabled, the engine reports fully documented functions as
  undocumented — measured at seven false errors against one real one. A gate that fails on
  correct code is a gate people learn to ignore.
- **Check** `doxygen enforce/Doxyfile` exits 0 on a conformant tree
- **See** [fact/doxygen]

### DOC-012 · Generated documentation is not committed  [BINDING] [check:generated_provenance]
The rendered documentation tree MUST NOT be committed, and MUST be reproducible from the
committed source comments alone.
- **Why** This is the one deliberate exception to committing generated artefacts. The
  reviewable artefact here *is* the comment in the source; committing a large rendered
  tree adds diff noise on every change, which is precisely how reviewers are trained to
  wave generated diffs through.
- **Check** `python -m checks.generated_provenance`
- **See** [law/DEP]

### DOC-013 · Prefer one sentence that earns its place  [ADVISORY]
Where an element is genuinely self-evident, the documentation SHOULD be one accurate
sentence rather than a padded block.
- **No mechanism** Whether a sentence is informative or ceremonial is a reading judgment;
  [DOC-009] mechanizes the detectable half — restating the name — and no check can weigh
  the rest.
- **Why** The objection to universal documentation is that it produces filler. The answer
  is short and true, not absent.

### DOC-014 · A project declares which engine reads its documentation  [BINDING] [check:doc_coverage]
A project MUST declare its documentation engine in `[tool.agent-discipline]`. An
undeclared v4 project MUST be refused. A direct legacy invocation retains `none` only as
a conspicuous diagnostic fallback and MUST emit DOC-014 rather than a narrower green run.
- **Why** [DOC-002] and [DOC-007] name one engine's punctuation. Demanding it of a project
  documenting in another produced 1,064 findings of form against 18 of substance, which is
  how a check stops being read; leaving it undeclared and silent is worse, because a
  narrowed run and a clean one then look identical.
- **Check** `python -m checks.doc_coverage`, which prints the declaration it found and
  every rule that declaration leaves inactive
- **See** [DOC-002] · [DOC-007] · [meta/OPEN]
