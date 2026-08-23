---
id: examples/documentation
kind: meta
title: Evident Source, Worked
tokens: 2386
load_when:
  - "how do i document this"
  - "docstring example"
  - "doxygen example"
  - "what does a good docstring look like"
decay: none
---

# Documentation, Worked

Contrast pairs for [law/DOC], [law/DOC-NARRATION], and [law/DOC-NAMING]. Every "no" here
was written by someone trying to satisfy the rule and missing the point of it; each is a
shape the checks either catch or, worse, do not.

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

## One comment owns one semantic step

```python
# no -- translates each token and leaves the procedure implicit
# Iterate over records.
for record in records:
    # Append the record path.
    paths.append(record.path)

# yes -- one comment owns the loop target, extracted value, and accumulation
# Build the canonical-path index in input order so duplicate diagnostics retain
# the same order in which the records were supplied.
for record in records:
    canonical_path = normalize(record.path)
    paths.append(canonical_path)
```

The second block does not need a separate sentence for `record`, `canonical_path`, and
`paths.append`. They are adjacent parts of one named operation. Moving the normalization
into another branch would create another semantic step and therefore another owner.

## Binding shapes

```python
# Decode the envelope once, retaining its declared kind beside the payload for dispatch.
kind, payload = decode_envelope(raw)

# Acquire the output stream for the complete emission transaction.
with output_path.open("wb") as stream:
    stream.write(payload)

try:
    persist(payload)
except OSError as problem:
    # Translate the substrate failure into the boundary error callers understand.
    raise PersistenceFailure(output_path) from problem

# Keep only accepted records while preserving their source order.
accepted = [record for record in records if record.accepted]
```

Destructuring targets, context-manager aliases, exception aliases, comprehension targets,
assignment expressions, loop targets, and pattern captures are bindings just as ordinary
assignments are. Parameters are the exception: the callable's structured contract owns
their meaning.

## Boolean and collection meaning

```python
@dataclass(frozen=True, slots=True)
class ScanPolicy:
    """Constraints applied while reading a manifest."""

    ## True permits absent optional records; false rejects the first absence.
    allow_missing: bool
    ## Patterns in evaluation order; the first matching pattern owns the record.
    patterns: tuple[str, ...]
```

“Whether missing records are allowed” leaves one state to inference. “Record patterns”
leaves element meaning and ordering to inference. The complete comments answer those
questions at the entities that own the values.

## Stable properties and temporary representations

```python
## Maximum wait in milliseconds; zero requests a non-blocking attempt.
timeout_ms: int

# Convert the configured millisecond budget to seconds for the subprocess API.
timeout_seconds = timeout_ms / 1_000
```

The stable unit belongs to the field's Doxygen contract. The local conversion belongs to
the implementation step. Repeating both in both places would create two truths to update.

## Controlled vocabulary

```python
# no -- two undeclared contractions and dimensions in an unexplained order
cfg_ch_map: dict[int, str]

# yes, when the project model declares `channel`, `identifier`, and `mapping`
# in this order and admits no contraction for them
channel_identifier_mapping: dict[int, str]
```

A different domain may deliberately declare `cfg` as the canonical abbreviation for
configuration. The package checks the declared choice; it does not choose the domain's
words.

## Generated names remain visibly derived

```python
# no -- a generated transport name looks canonical and has no origin mapping
command_frame = schema_type()

# yes -- the declared marker and mapping expose the representation boundary
generated_wire_command_frame = schema_type()
```

The project documentation model maps `generated_wire_command_frame` back to its canonical
concept. Generated vocabulary can then change without silently redefining domain terms.
