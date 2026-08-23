---
id: frame/documentation
kind: frame
title: Evident Source
tokens: 1147
load_when:
  - "why document locals"
  - "comment granularity"
  - "semantic step"
  - "quasi-literate"
  - "documentation ownership"
decay: none
---

# Evident Source

Reasoning for [law/DOC], [law/DOC-NARRATION], and [law/DOC-NAMING]. This frame explains
the design; the laws carry the obligations.

## Two reading directions

Source is read structurally and procedurally.

Structural reading asks what a module, type, callable, field, parameter, result, or error
means. Doxygen is useful here because it gives named entities a stable address, connects
relationships, and projects a navigable view. Python docstrings are the storage form for
entities with a docstring slot; nearby `##` blocks are the storage form for representable
entities without one. Together they form one structured system.

Procedural reading asks how execution advances: which branch rejects an input, why an
iterator becomes a list, which representation exists between two boundaries, or why a
resource is released in a particular order. An entity page is the wrong address for this
information. Ordinary comments can sit beside the operation they explain and remain out
of the generated contract.

The split is ownership, not audience. Both layers help maintainers; only one layer owns a
given fact.

## Semantic steps

A physical line is too small a unit for useful narration. A complete operation often
spans a predicate, a transformation, several bindings, and a state update. A whole
function is often too large: one paragraph at its entrance leaves later branches and
temporary representations unaddressed.

A **semantic step** is the smallest coherent operation a reader can name in domain or
technical terms. One comment can own several adjacent statements when they jointly carry
that step. A branch or nested body creates a new locality because a comment outside it
cannot unambiguously explain every path inside it.

Association is deliberately lexical. A nearby ordinary comment block owns the next
contiguous statement or compound operation. Blank prose at file scope does not float down
to unrelated bindings, and a comment between two possible owners is treated as ambiguous
instead of being attached optimistically.

## Restatement without paraphrase

“Increment the counter” translates tokens and adds no meaning. “Record the failed attempt
before testing the retry budget” names the operation's role and order. Both mention what
the syntax does, but only the second lets a reader follow the procedure without deriving
its purpose from mutation and control flow.

This is why the entity rule against implementation narration and the implementation rule
in favor of semantic restatement are compatible. Stability differs: the entity contract
should survive an internal rewrite; the step comment is expected to move when the
procedure changes.

## Naming as local data

A generic package cannot know whether `bin`, `frame`, `channel`, or `port` is a domain
concept, a representation, or an abbreviation in a consuming repository. It can know
whether one abbreviation has two meanings in an overlapping scope, whether an identifier
violates a declared grammar, or whether generated vocabulary is indistinguishable from
canonical vocabulary.

The documentation model separates those layers. The project authors the vocabulary and
scope; the package checks internal consistency and observable uses. Anything requiring
domain understanding remains a review question rather than being laundered through a
lexical proxy.

## Where judgment remains

Syntax can establish that a comment exists, which operation it is near, whether required
fields name both boolean states, and whether generated pages contain a relationship.
Syntax cannot establish that the prose is true, that an omitted unit was actually
irrelevant, or that a chosen identifier exposes every dimension important to the domain.

That residual is not a reason to abandon mechanical checks. It is a reason to bind the
unsettled propositions to the exact reviewed content and to say what the review still
cannot prove. A changed file invalidates the earlier semantic acceptance; a current
review can still be mistaken.
