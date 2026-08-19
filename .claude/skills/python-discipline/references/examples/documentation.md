---
id: examples/documentation
kind: meta
title: Documentation, Worked
tokens: 1373
load_when:
  - "how do i document this"
  - "docstring example"
  - "doxygen example"
  - "what does a good docstring look like"
decay: none
---

# Documentation, Worked

Contrast pairs for [law/DOC]. Every "no" here was written by someone trying to satisfy the
rule and missing the point of it; each is a shape the checks either catch or, worse, do not.

The project's Doxyfile sets `PYTHON_DOCSTRING = NO`, so an ordinary triple-quoted docstring
**is** a Doxygen block. There is no `"""!` marker to remember.

---

## The summary line

```python
# no -- restates the name, so the reader learns nothing (DOC-009, caught)
def parse_outline(text: str) -> Outline:
    """Parses the outline."""

# yes -- states what the caller gets and what it refuses
def parse_outline(text: str) -> Outline:
    """Build an outline, rejecting any heading that skips a depth level."""
```

The first satisfies every presence check and fails the reader. `doc_style` catches this particular
shape because every informative word already appears in the identifier — but it can only
catch the obvious cases, which is why [DOC-013] exists as judgment rather than mechanism.

## Parameters

```python
# no -- the type is already in the signature (DOC-008, caught)
@param count (int) the count of items
@param path (Path) the path

# yes -- says what the value means, and what is assumed of it
@param count how many were seen before the window closed
@param path the manifest, which need not exist yet
```

A type written twice diverges once, and the copy the checker cannot see is the one that
goes stale.

## Returns and failures

```python
# no -- says nothing the signature did not
@return the result

# yes -- says what the value signifies, and when there is none
@return the renamed outline; the argument is not mutated
@throws InvariantViolation when the title would collide with a sibling
```

`@throws` is the half most often skipped, and the half a caller most needs: a signature
cannot express which exceptions cross a boundary, because Python has no checked exceptions.

## Values with no docstring slot

Python offers nowhere to attach a docstring to a constant, a class attribute, a dataclass
field or an enum member. Doxygen reads a `##` block for exactly these.

```python
# no -- invisible to Doxygen; `#:` is Sphinx's convention, not this one
#: How many times a transient failure is retried.
MAX_RETRIES = 3

# yes
## How many times a transient failure is retried, before the port gives up.
MAX_RETRIES = 3


@dataclass(frozen=True, slots=True)
class Outline:
    """A document's heading structure, as parsed and validated."""

    ## The title as authored; already normalized by `parse_outline`.
    title: str
    ## Where this sits in its lifecycle. Never moves backwards.
    stage: Stage
```

## Where the documentation goes

```python
# no -- a ## block above a function is invisible to help(), to editors and to
# every other Python tool (DOC-004, caught)
## Give an outline a new title.
# @param title the replacement
def rename(outline: Outline, title: str) -> Outline: ...

# yes -- the docstring is the slot Python gives you; use it
def rename(outline: Outline, title: str) -> Outline:
    """Give an outline a new title, leaving its stage untouched.

    @param outline the outline to rename
    @param title the replacement, already validated by the parsing constructor
    @return a new outline; the argument is not mutated
    """
```

`##` is for the elements with no slot, and only those.

## A literal @ in prose

```python
# no -- Doxygen parses @overload as a command and reports a phantom symbol
"""True when it carries an @overload decorator."""

# yes -- either escape it, or make the docstring raw
r"""True when it carries an \@overload decorator."""
"""True when it carries an `@overload` decorator."""
```

This one is silent until the documentation build runs, which is why the build is a gate
rather than an afterthought.

## Tests are code

```python
# no -- a test with no docstring says only what it does, never what it protects
def test_v096_ledger_and_index_disagree(tmp_path): ...

# yes
def test_v096_ledger_and_index_disagree(tmp_path: Path) -> None:
    """An index holding fewer events than the ledger answers from stale data.

    The ledger is the record. The moment the derived store can disagree with it,
    the record stops being the record.
    """
```

A test name states the behaviour; its docstring states why that behaviour matters, which is
what tells a later reader whether a failure is a real regression or a stale expectation.

## The honest minimum

Where an element genuinely is self-evident, one accurate sentence is the right answer, and
padding it is worse than leaving it short:

```python
def render(self) -> str:
    """Format the failure for a terminal.

    @return a single line naming the gate, the file and the problem
    """
```

The objection to documenting everything is that it produces filler. The answer is short and
true — not absent.
