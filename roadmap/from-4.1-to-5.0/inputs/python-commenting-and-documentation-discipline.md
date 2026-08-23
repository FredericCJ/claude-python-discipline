# Python Commenting and Documentation Discipline

## 1. Purpose

This document defines the commenting and documentation discipline for the Python project.

The objective is not merely to produce API reference material. The objective is to make the software **evident**: a competent reader shall be able to determine, from the source code and its associated generated documentation, what every relevant program element represents and how the program operates.

The discipline therefore combines:

1. **Doxygen documentation comments** for every element that the documentation engine can represent; and
2. **developer-facing implementation comments** written in a quasi-literate-programming style for control flow, data flow, sequencing, algorithms, transformations, and other internal behavior that the documentation engine cannot adequately capture.

The two forms are complementary. They shall not compete for ownership of the same information.

---

## 2. Documentation engine

The automatic documentation engine shall be **Doxygen 1.17**.

Python source code shall use **Doxygen documentation syntax**.

Doxygen and the Python project shall be configured to exploit the full set of Doxygen capabilities applicable to Python, including cross-references, call relationships, file documentation, namespace/module documentation, type documentation, member documentation, variable documentation, parameter documentation, return-value documentation, and other supported structural information.

Where conventional Python docstring practices conflict with the Doxygen-oriented documentation model, the Doxygen model shall take precedence.

The project shall not maintain parallel Python-docstring and Doxygen documentation systems for the same information.

---

## 3. Fundamental axioms

### 3.1 There is no such thing as self-documenting code

Code can be written in ways that materially contribute to documentation, but code does not eliminate the need for explicit documentation.

Readable syntax, expressive naming, strong typing, decomposition, and disciplined structure reduce ambiguity. They do not constitute a complete specification of meaning.

A reader shall not be required to infer the intended semantics of an element solely from:

- its implementation;
- its datatype;
- its call sites;
- its surrounding control flow;
- common programming idioms; or
- the apparent obviousness of the code.

Explicit documentation is required.

### 3.2 Documentation comments shall make the code evident

The purpose of comments is to make the code evident.

Making code evident means restating in plain English what the code does, why the relevant operation exists when that reason is not already explicit, what information is represented, and how the important steps relate to one another.

This principle deliberately rejects the rule that comments should never restate code.

A syntactic restatement is weak documentation:

```text
Increment i by one.
```

A semantic restatement makes the operation evident:

```text
Advance to the next recorded signal after processing the current entry.
```

When useful, comments may be more explicit than the implementation itself. The objective is that the reader can follow the source as a documented procedure rather than reverse-engineering its behavior from syntax.

### 3.3 The name identifies the concept; the documentation defines it

Every named program element shall have a name that contributes to understanding what it represents.

The documentation comment shall define that representation precisely.

Neither the identifier nor the documentation comment is sufficient by itself.

### 3.4 Documentation shall be located at the highest level that can express it correctly

Information shall be represented by Doxygen whenever Doxygen can express the information correctly and attach it to the appropriate program element.

Developer-facing implementation comments shall be used for information that Doxygen cannot adequately represent as structured documentation.

This rule establishes a strict precedence:

> **If Doxygen can own the information, Doxygen shall own it.**

Implementation comments shall not become an informal duplicate API-documentation system.

---

## 4. Two documentation layers

The project distinguishes two documentation layers.

### 4.1 Doxygen documentation

Doxygen documentation is the canonical documentation for all program entities and relationships that Doxygen can represent.

It is both user-facing and developer-facing in the broad sense that generated documentation may be consumed by library users, integrators, maintainers, reviewers, and developers.

For the purpose of this discipline, **everything covered by Doxygen belongs to the Doxygen documentation layer**.

Examples include:

- files and modules;
- packages and namespaces;
- classes;
- structures and records;
- enumerations;
- enumeration values;
- constants;
- global variables;
- member variables;
- fields and properties;
- functions;
- methods;
- parameters;
- return values;
- exceptions and error conditions;
- public and private members;
- relationships between documented entities;
- supported call and dependency relationships;
- documented groups and conceptual pages;
- invariants, preconditions, postconditions, units, ranges, ownership, lifecycle, and other semantic properties attached to named elements.

### 4.2 Developer-facing implementation documentation

Developer-facing implementation documentation consists of ordinary source comments that are **not intended for extraction by Doxygen**.

These comments describe how the implementation works.

Their principal subjects are:

- control flow;
- data flow;
- sequencing;
- intermediate transformations;
- algorithmic steps;
- loop progression;
- branch purpose;
- state transitions;
- interaction between successive operations;
- temporary representations;
- non-obvious language semantics;
- implementation constraints;
- local invariants;
- synchronization points;
- error-handling paths;
- recovery paths;
- resource-management sequences;
- ordering dependencies;
- reasons for apparently unusual implementation choices.

These comments shall be written in a **quasi-literate-programming style**.

The source code should read as an interleaving of plain-English explanation and executable statements.

---

## 5. Allocation rule between the two layers

The following decision rule shall be applied to every piece of documentation.

### 5.1 Use Doxygen when the information describes a documentable program entity

If the information answers questions such as:

- What is this variable?
- What does this field represent?
- What is this class responsible for?
- What does this function do?
- What does this parameter mean?
- What does the function return?
- What units does this value use?
- What are the allowed values?
- What invariant does this object maintain?
- What error can this operation report?
- What ownership rules apply?
- What is the relationship between these documented entities?

then the information belongs in Doxygen documentation.

### 5.2 Use implementation comments when the information explains execution

If the information answers questions such as:

- What happens next?
- Why is this branch entered?
- What sequence of operations is being performed?
- How is this intermediate value derived?
- Why must these operations occur in this order?
- What is this loop progressively constructing?
- What transformation is happening here?
- What language behavior makes this expression work?
- Why is this temporary representation necessary?
- How does control move through this block?

then the information belongs in ordinary developer-facing comments.

### 5.3 Do not duplicate information without reason

The same fact should not normally be maintained independently in both layers.

For example:

- The semantic meaning of `signal_paths` belongs in its Doxygen variable documentation.
- The explanation of how a Python expression constructs `signal_paths` from a nested data model belongs beside that expression as an implementation comment.

Duplication is acceptable only when the local implementation would otherwise become materially harder to understand.

---

## 6. Mandatory documentation coverage

Every named program element shall have documentation stating exactly what that element represents.

At minimum, the following shall be documented:

- every module;
- every class;
- every structure-like type;
- every enumeration;
- every enumeration member;
- every constant;
- every variable;
- every class member;
- every field;
- every property;
- every function;
- every method;
- every function and method parameter;
- every return value;
- every relevant exception or failure condition;
- every flag;
- every state value;
- every callback;
- every interface object;
- every persistent or shared resource handle.

Local variables are not exempt merely because their scope is small.

A short-lived local variable may require only a concise description, but its semantic role shall still be made explicit.

---

## 7. Required content of element documentation

Documentation shall describe semantics, not merely syntax.

A useful documentation comment answers, as applicable:

- What real or abstract concept does the element represent?
- What is its role in the surrounding abstraction?
- What are its units?
- What is its reference frame?
- What is its coordinate system?
- What is its valid range?
- What encoding or representation does it use?
- What state does it describe?
- Who owns it?
- Who may modify it?
- What is its lifetime?
- What is its source?
- What consumes it?
- What invariants apply?
- Is absence meaningful?
- Is zero meaningful?
- Is ordering meaningful?
- Does it represent raw, decoded, validated, filtered, scaled, cached, or derived information?
- Does it identify current state, requested state, previous state, or predicted state?

Not every element requires every property. Documentation shall include whichever properties are necessary to remove ambiguity.

### 7.1 Insufficient documentation

```text
Counter value.
```

This gives little more information than a datatype or identifier.

### 7.2 Acceptable documentation

```text
Sequence number of the most recently received command frame, used to detect
missing or out-of-order frames.
```

The second form states what the value represents and why the software maintains it.

---

## 8. Naming discipline

Naming is part of the documentation system.

The most influential contributor to source-level documentation is the naming of named program elements.

Names shall therefore be designed as **code-disambiguation artifacts** and, where useful, as **property encodings**.

### 8.1 Names shall express meaning

A name shall identify the domain concept, role, quantity, state, interface, or operation represented by the element.

Names whose primary meaning is an implementation accident shall be avoided unless that implementation detail is itself the relevant semantic property.

### 8.2 Names shall expose relevant semantic dimensions

When multiple independent properties are required to identify an element, those properties should be expressed explicitly.

Examples of semantic dimensions include:

- logical role;
- source;
- destination;
- boundary;
- direction;
- processing stage;
- physical quantity;
- representation;
- lifecycle state;
- validity state.

The exact dimensions are application-specific.

### 8.3 Independent semantic dimensions shall remain distinguishable

Conceptually separate properties shall not be silently fused into opaque tokens.

Names should remain mechanically understandable where practical.

For example, a naming grammar may use separators to distinguish boundary and direction rather than concatenating both into an undocumented abbreviation.

### 8.4 Names shall proceed from broad context toward specific meaning

Where several semantic components appear in one identifier, the project shall define a deterministic ordering.

A typical progression is:

```text
broad context -> interface or role -> direction -> stage -> quantity -> representation
```

The exact grammar shall be defined per project or domain.

### 8.5 Abbreviations shall form a controlled vocabulary

Every project abbreviation shall have one documented meaning within its defined scope.

Unregistered, ambiguous, overloaded, or context-dependent abbreviations should be prohibited.

Naming validation should reject unregistered abbreviations where automated validation is practical.

### 8.6 Domain semantics shall be separated from representation

Logical meaning shall remain identifiable independently of:

- transport protocol;
- serialization;
- storage representation;
- raw encoding;
- generated-code representation;
- framework naming;
- implementation suffixes.

Representation-specific information may be encoded in names where it is necessary to distinguish representations, but it shall not replace the domain concept.

### 8.7 Topological terms shall not imply behavior

Names that identify processing positions shall describe positions, not unsupported behavioral conclusions.

For example, a name meaning "after rate transition" shall not itself imply that a particular latency has occurred unless latency is separately represented.

### 8.8 Generated names shall not define domain vocabulary

Compiler-generated, code-generator-specific, framework-specific, or mechanically synthesized prefixes and suffixes shall remain distinguishable from canonical project terminology.

Generated identifiers shall not be adopted as the primary domain nomenclature merely because they appear in generated artifacts.

### 8.9 Silent truncation is prohibited

Identifiers shall not become ambiguous through silent truncation.

If an implementation imposes identifier-length constraints, the project shall use deterministic, registered abbreviations or redesign the representation.

### 8.10 Use structure to express structure

When information is naturally hierarchical, the program structure should carry that hierarchy.

Prefer:

```text
interface.route.quantity
```

or structured records/classes over repeatedly flattening the complete semantic path into every scalar identifier.

A flat identifier grammar remains appropriate where the execution environment, generated interface, serialization format, or tooling requires one.

---

## 9. Naming conventions are domain-specific

A naming convention created for one application domain shall not be copied mechanically into another.

The reusable principles are:

- identify the relevant semantic dimensions;
- define their order;
- keep independent dimensions separable;
- use a controlled vocabulary;
- preserve domain meaning independently of implementation representation;
- make names mechanically unambiguous where practical;
- use structural language constructs where they better represent the model.

The concrete tokens, abbreviations, and grammar shall be defined separately for each domain.

---

## 10. Quasi-literate implementation commenting

Implementation comments shall make the program readable as a documented procedure.

The preferred pattern is:

1. explain the purpose of the next logical operation;
2. present the code implementing that operation;
3. explain the next logical operation;
4. continue until the implementation block is complete.

Example:

```python
# Define the path of the complete structure dump for recording 27.
structure_dump = Path("can_limit027_structure.txt")

# Define the path of the schema-only dump for recording 27.
schema_dump = Path("can_limit027_schema.txt")

# Create the complete structure dump only when no previous dump exists.
if not structure_dump.is_file():
    dumpstruct.write(rec27, structure_dump, opts)

# Create the schema-only dump only when no previous schema dump exists.
if not schema_dump.is_file():
    dumpstruct.write_schema(rec27, schema_dump, opts)
```

The comments intentionally restate the operations in plain English.

The objective is not brevity. The objective is that a reader can follow the behavior without mentally translating each programming-language construct.

---

## 11. Commenting control flow

Control flow shall be documented at the level of logical operations.

### 11.1 Conditionals

Comments shall explain what condition is being tested and what entering the branch means.

Preferred:

```python
# Reject the frame when its sequence number is older than the last accepted frame.
if frame.sequence < last_sequence:
    ...
```

Less useful:

```python
# Check whether sequence is smaller.
if frame.sequence < last_sequence:
    ...
```

### 11.2 Loops

Comments shall explain what the loop traverses or constructs and, when relevant, how each iteration advances the computation.

```python
# Visit each recorded signal and add its canonical path to the output index.
for signal in recording.signals:
    ...
```

For complex loops, comments may also document:

- loop invariants;
- accumulation strategy;
- termination conditions;
- ordering requirements;
- intentionally skipped entries;
- mutation performed during each iteration.

### 11.3 Early returns

The reason for an early return shall be evident.

```python
# Nothing can be decoded from an empty payload, so terminate successfully
# without constructing a frame object.
if not payload:
    return None
```

### 11.4 Exception handling

Comments shall explain the recovery or translation policy, not merely state that an exception is caught.

```python
# Convert the filesystem-specific error into the package-level persistence
# error expected by callers.
try:
    ...
except OSError as exc:
    ...
```

### 11.5 State transitions

Where code changes state, the transition and its meaning shall be stated.

```python
# Mark the connection as synchronized only after both clocks have accepted
# the same reference epoch.
state = ConnectionState.SYNCHRONIZED
```

---

## 12. Commenting data flow and transformations

Intermediate transformations shall be documented when the relationship between source and destination is not immediately evident.

For example:

```python
# Extract one path from each signal record and materialize the generator as a
# list because the collection is traversed more than once below.
signal_paths = [signal.path for signal in recording.signals]
```

When language semantics themselves are non-obvious, the comment shall explain them.

For example, the equivalent MATLAB operation:

```matlab
% Build a directly iterable collection of all recorded-signal paths.
% The source data model stores these paths indirectly: 'rec' is a scalar
% struct whose only field, selected dynamically by the field-name variable
% 'recording', contains the recording as another scalar struct. Within that
% recording, 'Y' is a struct array with one struct element per recorded
% signal, and each element stores its signal path in the char-vector field
% 'Path'. MATLAB expands rec.(recording).Y.Path into a comma-separated list
% containing one Path char vector per element of Y; the surrounding braces
% collect that list into the cell array 'Paths'.
Paths = {rec.(recording).Y.Path};
```

This style is appropriate because the comment explains:

- the relevant data model;
- the language behavior;
- the transformation;
- the resulting representation.

A developer should not need prior knowledge of the implementation trick to understand the operation.

---

## 13. Comment granularity

Comments shall be attached to **logical operations**, not mechanically to physical lines.

A one-line statement may deserve a multi-line explanation when it performs a conceptually dense operation.

Conversely, a sequence of several obvious statements implementing one coherent operation may be introduced by a single comment.

The appropriate unit of commentary is therefore the **semantic step**.

---

## 14. Restating code in plain English

Restating what the code does is explicitly permitted and often required.

However, the restatement shall operate at a more semantic level than token-by-token translation.

### Weak

```python
# Add one to retry_count.
retry_count += 1
```

### Better

```python
# Record the failed attempt before deciding whether another retry is allowed.
retry_count += 1
```

### Weak

```python
# Iterate over items.
for item in items:
    ...
```

### Better

```python
# Validate each decoded record independently so one invalid record does not
# prevent the remaining records from being examined.
for item in items:
    ...
```

The comment shall explain the operation as a human would describe it in a technical procedure.

---

## 15. Comments and obvious code

The fact that an operation appears obvious does not, by itself, justify omitting its comment.

A simple operation may still deserve documentation because:

- it marks an important step in the procedure;
- its role is more important than its syntax;
- the surrounding sequence is easier to understand when explicitly narrated;
- the reader should not have to determine whether the operation is incidental or deliberate.

The project therefore favors **narrative completeness** over minimalist commenting.

Comments may be concise when the operation is simple.

---

## 16. Comments shall explain local reasoning where necessary

In addition to describing what an operation does, implementation comments shall document local reasoning whenever the reason is material to correctness or maintainability.

Examples include:

- why an operation occurs before another;
- why a copy is required;
- why mutation is avoided;
- why a particular representation is chosen;
- why an apparently redundant check is necessary;
- why a workaround exists;
- why a boundary condition is treated specially;
- why an optimization is safe;
- why an algorithm intentionally does not use a simpler-looking alternative.

Such comments should describe the actual engineering constraint rather than vague historical statements.

Avoid:

```python
# Do this because otherwise it breaks.
```

Prefer:

```python
# Materialize the iterator before validation because validation performs two
# independent passes over the input records.
```

---

## 17. Comments shall not preserve obsolete implementation history

Comments describe the current software.

Historical information shall not remain in source comments unless it is required to understand a current constraint.

Avoid comments such as:

```text
Changed this after the old parser failed.
```

Prefer:

```text
Use explicit UTF-8 decoding because the input format permits non-ASCII
signal names and the platform default encoding is not part of the format.
```

Version-control history is the appropriate location for obsolete implementation history.

---

## 18. Documentation of units, ranges, and representation

Any numerical value whose interpretation depends on units shall document those units.

Any value whose meaning depends on a range, encoding, resolution, scale, offset, reference frame, or coordinate system shall document those properties.

Examples:

```text
Steering-wheel angular velocity in rad/s, positive clockwise when viewed
from the driver.
```

```text
Unsigned 16-bit raw ADC sample before offset compensation.
```

```text
Elapsed time in seconds relative to the start of the current recording.
```

Units shall not be left implicit merely because they are conventional within one subsystem.

---

## 19. Documentation of boolean values and flags

Boolean variables and flags shall state what both states mean when either state could be ambiguous.

Example:

```text
True when the received frame has passed CRC, sequence, and freshness
validation; false when any validation step has failed.
```

Avoid:

```text
Whether the frame is valid.
```

when the project has several possible definitions of validity.

---

## 20. Documentation of collections

Collections shall document:

- what one element represents;
- ordering semantics, if any;
- uniqueness requirements, if any;
- ownership or mutability, if relevant;
- key semantics for mappings;
- whether absence and emptiness have distinct meanings.

Example:

```text
Recorded-signal paths in acquisition order. Each element is the canonical
path of one signal in the recording; duplicate paths are not permitted.
```

---

## 21. Documentation of functions and methods

Every function and method shall document:

- its responsibility;
- each parameter;
- its return value;
- relevant preconditions;
- relevant postconditions;
- side effects;
- externally visible state changes;
- important failure conditions;
- ownership or lifetime effects;
- relevant invariants.

The function documentation shall define **what the function means as an operation**.

The implementation comments inside the function shall explain **how that operation is carried out**.

This separation is fundamental.

---

## 22. Documentation of pure functions

Pure functions shall be identified as pure where this property is relevant to their contract.

Their documentation should make clear that they:

- do not mutate caller-visible state;
- do not perform externally visible I/O;
- derive the result solely from their explicit inputs, subject to any documented deterministic environmental assumptions.

Implementation comments shall then describe the transformation performed internally.

---

## 23. Documentation of side effects

Side effects shall never be left for the caller to infer from implementation.

If a function:

- writes a file;
- modifies an object;
- changes global state;
- sends a message;
- updates a database;
- acquires or releases a resource;
- changes process state;
- logs externally visible information;

that behavior shall be part of its Doxygen contract.

The local sequencing of those effects belongs in developer-facing implementation comments.

---

## 24. Documentation of invariants and assumptions

Important invariants and assumptions shall be explicit.

Examples include:

- a collection is sorted;
- indices are contiguous;
- an object owns a resource;
- a timestamp is monotonic;
- a buffer contains decoded rather than raw data;
- a function is called only while a lock is held;
- an input has already passed validation.

If the invariant belongs to a named object, type, function, or interface, it shall be documented through Doxygen.

If the invariant exists only during a local algorithmic phase, it shall be documented in an implementation comment at the relevant point.

---

## 25. Documentation of non-obvious language semantics

Language constructs whose behavior is essential to understanding the implementation shall be documented when a reader cannot reasonably be expected to infer the intended result immediately.

Examples include:

- dynamic attribute access;
- metaprogramming;
- generators whose single-use nature matters;
- descriptors;
- context-manager behavior;
- closures with captured state;
- unusual slicing semantics;
- overloaded operators;
- reflection;
- dynamic imports;
- aliasing-sensitive operations;
- implicit copy versus reference behavior.

The comment shall explain the language behavior in terms of the program's intent.

---

## 26. Documentation of algorithms

Algorithms shall be narrated at the level necessary for a developer to follow their progression.

For a non-trivial algorithm, comments should identify:

1. initialization;
2. the meaning of intermediate state;
3. the principal iteration or recursion step;
4. branch purposes;
5. convergence or termination;
6. construction of the result;
7. relevant complexity or numerical constraints where important.

The source should approximate a technical explanation interleaved with executable code.

If a separate design document defines the algorithm formally, the source documentation shall reference that definition through Doxygen where practical, while local comments still explain how the implementation maps onto the defined steps.

---

## 27. Documentation of interfaces and boundaries

Interfaces shall document their semantics independently of the implementation behind them.

Documentation should identify:

- what crosses the boundary;
- in which direction;
- in what representation;
- under what ownership rules;
- with what timing or ordering guarantees;
- with what validity assumptions;
- which failures may cross the boundary.

Implementation comments shall then explain local encoding, decoding, adaptation, buffering, scheduling, or dispatch behavior.

---

## 28. Comments shall remain synchronized with code

Incorrect documentation is a defect.

Whenever code changes, associated documentation comments shall be reviewed as part of the same change.

A change is incomplete when:

- an identifier changes but its documentation no longer matches;
- behavior changes but function documentation still describes the previous contract;
- an implementation sequence changes but quasi-literate comments narrate the previous sequence;
- a range, unit, representation, or invariant changes without corresponding documentation changes.

Documentation maintenance is part of code maintenance, not a separate cleanup activity.

---

## 29. Review discipline

Code review shall treat documentation defects as code defects.

Reviewers shall verify at least:

- every named element has appropriate Doxygen documentation;
- names contribute meaningful semantic information;
- abbreviations follow the controlled vocabulary;
- function contracts describe semantics rather than syntax;
- units and representations are explicit;
- implementation comments narrate control flow and data flow;
- non-obvious transformations are explained;
- comments match the implementation;
- information is allocated to Doxygen whenever Doxygen can represent it;
- developer-facing comments do not duplicate Doxygen unnecessarily;
- the resulting source can be followed as an explicit technical procedure.

---

## 30. Anti-patterns

The following practices are prohibited or strongly discouraged.

### 30.1 Undocumented named elements

```python
x = ...
```

with no documentation of what `x` represents.

### 30.2 Names used as a substitute for documentation

```python
received_validated_command_sequence_number = ...
```

does not eliminate the requirement to document the variable.

### 30.3 Documentation used as a substitute for meaningful naming

```python
# Sequence number of the most recently accepted command frame.
x = ...
```

The comment is useful, but the identifier remains inadequate.

### 30.4 Purely syntactic comments

```python
# Set x to zero.
x = 0
```

unless the semantic role of setting the value to zero is independently evident from surrounding documentation.

### 30.5 Unexplained implementation tricks

Compact code that depends on subtle language semantics shall not be left for the reader to decipher.

### 30.6 Doxygen-capable information stored only in ordinary comments

If Doxygen can attach the information to the relevant program element, the information belongs in Doxygen.

### 30.7 Parallel documentation systems

The same API contract shall not be independently maintained in Doxygen and a second Python-docstring convention.

### 30.8 Comments that describe obsolete history

Version-control history shall not be copied into source comments unless the historical fact is itself a current engineering constraint.

### 30.9 Ambiguous abbreviations

An abbreviation that has no controlled definition shall not appear in canonical names.

### 30.10 Comments that merely assert quality

Avoid comments such as:

```text
Handle this safely.
```

```text
Do the correct conversion.
```

```text
Process normally.
```

Comments shall state concrete behavior.

---

## 31. Preferred source-reading experience

A well-documented source file should be readable at two complementary levels.

### Structural reading

The reader consults Doxygen and can determine:

- what modules exist;
- what abstractions exist;
- what every named entity represents;
- what functions and methods promise;
- what data crosses interfaces;
- what relationships exist between documented entities.

### Procedural reading

The reader opens the source and can follow:

- what the implementation does first;
- what information is extracted;
- what is checked;
- what is transformed;
- why branches exist;
- how loops progress;
- how intermediate state evolves;
- what happens on failure;
- how the final result is produced.

The first level documents the software model.

The second level documents the execution of that model.

Together they make the program evident.

---

## 32. Compact decision table

| Information to document | Required location |
|---|---|
| Meaning of a module, class, function, variable, field, parameter, or return value | Doxygen |
| Units, ranges, representation, ownership, lifecycle, invariants of a named entity | Doxygen |
| Public or private API contract | Doxygen |
| Relationship between Doxygen-supported program entities | Doxygen |
| Purpose of a branch | Implementation comment |
| Meaning and progression of a loop | Implementation comment |
| Sequence of internal operations | Implementation comment |
| Local data transformation | Implementation comment |
| Non-obvious language behavior | Implementation comment |
| Local algorithmic invariant | Implementation comment |
| Reason for an implementation ordering constraint | Implementation comment |
| Information expressible correctly in both places | Doxygen first; local comment only if needed for readability |

---

## 33. Governing rule

The entire discipline can be reduced to three governing rules:

1. **Document every named element.**
2. **Use Doxygen for everything Doxygen can represent.**
3. **Narrate the remaining implementation in plain English so that the control flow, data flow, and transformations are evident from the source.**

The desired result is source code that does not merely execute correctly, but also explains itself explicitly and systematically to the developer reading it.
