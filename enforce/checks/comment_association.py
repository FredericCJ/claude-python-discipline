"""Lexically associate ordinary comments with Python semantic operations.

The grammar is intentionally small and deterministic. A qualifying full-line
comment block immediately above a statement starts a semantic step and owns the
contiguous statements in that same AST suite until a blank line or another
qualifying block. A qualifying trailing comment owns only its statement. A
compound statement's owner also owns binding targets introduced by that compound
and by comprehensions in its directly owned expression. Two possible owners are
ambiguity, never a guess.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

# Import static collection contracts without runtime package dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

## Tool directives and typing syntax carry machine instructions, not meaning.
DIRECTIVE = re.compile(
    r"^#\s*(?:noqa\b|type:\s|fmt:\s|ruff:\s|pylint:\s|pragma:\s|nosec\b|cov:\s)",
    re.IGNORECASE,
)
## Section bars and punctuation-only blocks do not explain an operation.
SEPARATOR = re.compile(r"^#(?:\s*[-=~_*#]){3,}\s*$")
## Conservative commented-out-code shapes. Prose that happens to mention an
## identifier remains eligible; executable punctuation and keywords do not.
COMMENTED_CODE = re.compile(
    r"^#\s*(?:def |class |if |elif |else:|for |while |try:|except |with |return\b|raise\b|"
    r"import |from |[A-Za-z_]\w*\s*(?:=|\(|\[))"
)
## Unordered binding-name set whose each element intentionally discards its value.
DISCARD_NAMES: Final = frozenset({"_", "__"})


@dataclass(frozen=True, slots=True)
class CommentBlock:
    """One contiguous qualifying ordinary-comment block."""

    ## Inclusive one-based source line at which the comment block begins.
    start: int
    ## Inclusive one-based source line at which the comment block ends.
    end: int
    ## Zero-based indentation column shared by every full-line block element.
    column: int
    ## Semantic prose with comment markers removed.
    text: str
    ## True when code precedes the marker; false for a full-line comment block.
    trailing: bool


@dataclass(frozen=True, slots=True)
class Association:
    """The comment ownership result for one AST operation."""

    ## Exactly one block on success; absent for missing or ambiguous ownership.
    owner: CommentBlock | None
    ## Candidate owner elements in lexical order when zero, one, or several competed.
    candidates: tuple[CommentBlock, ...]

    @property
    def ambiguous(self) -> bool:
        """Whether more than one comment could own the operation.

        @return true only for conflicting candidates
        """
        # True means at least two candidates compete; false means missing or unique ownership.
        return len(self.candidates) > 1


@dataclass(frozen=True, slots=True)
class Binding:
    """One locally bound name and the statement whose comment owns it."""

    ## Exact local identifier spelling introduced by the binding.
    name: str
    ## One-based source line at which the identifier is introduced.
    line: int
    ## Binding form used in actionable findings.
    shape: str
    ## AST operation to which narration attaches.
    owner_node: ast.AST


def _qualifying(raw: str) -> bool:
    """Whether one comment token carries possible semantic narration.

    @param raw token text including its marker
    @return false for directives, separators, commented code, and empty markers
    """
    # Normalize surrounding whitespace while retaining the leading comment marker.
    stripped = raw.strip()
    # Doxygen blocks, empty markers, and shebangs belong to other information channels.
    if stripped.startswith("##") or stripped in {"#", "#!"}:
        # False excludes the token from procedural narration ownership.
        return False
    # True admits semantic prose; false rejects any recognized machine or code-like shape.
    return not (
        DIRECTIVE.match(stripped)
        or SEPARATOR.match(stripped)
        or COMMENTED_CODE.match(stripped)
        or stripped.startswith("# type: ignore")
    )


def comment_blocks(text: str) -> tuple[CommentBlock, ...]:
    """Extract qualifying comment blocks without interpreting their truth.

    Consecutive full-line comments at the same indentation become one block.
    A trailing comment is always its own block because executable text separates
    it from comments on adjacent lines.

    @param text complete Python source
    @return qualifying block elements in lexical order
    """
    # Preserve each source line in lexical order for trailing-token classification.
    lines = text.splitlines()
    # Preserve each qualifying comment token in lexical source order.
    tokens = _comment_tokens(text, lines)
    # Accumulate each contiguous block in lexical order as tokens are folded.
    blocks: list[CommentBlock] = []
    # Fold every token record into either the prior compatible block or a new owner.
    for row, column, prose, trailing in tokens:
        # Select the immediately preceding block, or None before the first token.
        previous = blocks[-1] if blocks else None
        # Adjacent full-line tokens at equal indentation constitute one semantic prose block.
        if (
            previous is not None
            and not trailing
            and not previous.trailing
            and previous.end + 1 == row
            and previous.column == column
        ):
            # Replace the final block with its extended line range and joined prose.
            blocks[-1] = CommentBlock(
                previous.start,
                row,
                column,
                f"{previous.text} {prose}".strip(),
                trailing=False,
            )
        # A trailing, differently indented, or separated token starts its own block.
        else:
            # Append the independent lexical owner after every earlier block.
            blocks.append(CommentBlock(row, row, column, prose, trailing))
    # Freeze the ordered comment-block elements for deterministic association.
    return tuple(blocks)


def _comment_tokens(text: str, lines: Sequence[str]) -> tuple[tuple[int, int, str, bool], ...]:
    """Tokenize qualifying comments while containing malformed-source failure.

    @param text complete Python source
    @param lines ordered source-line elements used to distinguish trailing comments
    @return token tuples in lexical order, each carrying row, column, prose, and trailing state
    """
    # Tokenize through Python's lexical grammar so hashes inside strings never become comments.
    try:
        # Stream source tokens lazily from the complete in-memory module text.
        stream = tokenize.generate_tokens(io.StringIO(text).readline)
        # Materialize qualifying token records in the tokenizer's lexical order.
        return tuple(
            (
                token.start[0],
                token.start[1],
                token.string[1:].strip(),
                bool(lines[token.start[0] - 1][: token.start[1]].strip()),
            )
            for token in stream
            if token.type == tokenize.COMMENT and _qualifying(token.string)
        )
    # Malformed source has no safe lexical ownership interpretation; parsing reports it elsewhere.
    except (IndentationError, tokenize.TokenError):
        # Return an ordered empty token sequence rather than inventing partial owners.
        return ()


def associate(node: ast.AST, blocks: Sequence[CommentBlock]) -> Association:
    """Resolve the exact lexical comment owner of one AST operation.

    @param node statement or expression carrying source positions
    @param blocks qualifying comment elements in lexical order from the same module
    @return missing, unique, or ambiguous association
    """
    # Read the operation's inclusive starting line, defaulting to zero for detached nodes.
    line = getattr(node, "lineno", 0)
    # Read the inclusive ending line, falling back to the operation start.
    end = getattr(node, "end_lineno", line)
    # Read the operation indentation column, defaulting to the module boundary.
    column = getattr(node, "col_offset", 0)
    # Admit the decorator-expression offset alternative while retaining an unordered set.
    preceding_columns = (
        {column, column - 1} if isinstance(node, ast.expr) and column > 0 else {column}
    )
    # Preserve each directly adjacent or same-statement trailing candidate in lexical order.
    candidates = tuple(
        block
        for block in blocks
        if (
            (block.trailing and line <= block.start <= end)
            or (
                not block.trailing
                and block.end == line - 1
                and block.column in preceding_columns
            )
        )
    )
    # Expose the sole owner only when exactly one candidate exists; otherwise retain candidates.
    return Association(candidates[0] if len(candidates) == 1 else None, candidates)


def semantic_associations(
    tree: ast.Module,
    text: str,
    blocks: Sequence[CommentBlock],
) -> Mapping[ast.AST, Association]:
    """Resolve comment ownership for complete same-suite semantic steps.

    A full-line block immediately preceding the first statement starts a step.
    It continues across adjacent statements in the same AST body and stops at a
    blank line, a new qualifying full-line block, or a trailing-comment boundary.
    Nested suites start with no inherited owner, so prose above ``if`` or ``for``
    cannot float into their bodies. Exception handlers additionally admit the
    natural first-body explanation used beside an ``except`` header.

    @param tree parsed module whose statement suites define ownership boundaries
    @param text exact module text used to detect blank-line boundaries
    @param blocks qualifying ordinary comment elements in lexical order from that text
    @return mapping from each governed statement/handler key to its association value;
        insertion order follows suite traversal then exception-handler traversal
    """
    # Preserve each source line in lexical order for blank-paragraph boundary detection.
    lines = text.splitlines()
    # Map each governed AST key to its resolved association value in deterministic insertion order.
    resolved: dict[ast.AST, Association] = {}
    # Resolve ownership independently inside every lexical statement suite.
    for suite in _statement_suites(tree):
        # Carry the active full-line owner, or None before a step starts or after it ends.
        active: CommentBlock | None = None
        # Carry the prior statement, or None before the first suite element, for blank detection.
        previous: ast.stmt | None = None
        # Process each statement element in its lexical suite order.
        for statement in suite:
            # A physical paragraph boundary terminates inherited semantic-step ownership.
            if previous is not None and _blank_between(previous, statement, lines):
                # Clear the active owner before resolving the statement after the blank line.
                active = None

            # Resolve comments directly adjacent to or trailing this statement.
            direct = associate(statement, blocks)
            # Preserve each full-line direct candidate in lexical order.
            preceding = tuple(block for block in direct.candidates if not block.trailing)
            # Preserve each same-statement trailing candidate in lexical order.
            trailing = tuple(block for block in direct.candidates if block.trailing)
            # The nearest preceding block starts a new semantic step for this suite.
            if preceding:
                # Select the last direct full-line element as the nearest lexical owner.
                active = preceding[-1]

            # Combine the inherited owner and trailing elements, preserving lexical uniqueness.
            candidates = _unique_blocks((*((active,) if active is not None else ()), *trailing))
            # Record a unique owner only for one candidate; retain all candidates otherwise.
            resolved[statement] = Association(
                candidates[0] if len(candidates) == 1 else None,
                candidates,
            )
            # A trailing owner applies to this statement only and terminates inherited ownership.
            if trailing:
                # Clear the active block before the next suite statement.
                active = None
            # Retain this statement as the ordered predecessor for the next boundary check.
            previous = statement

    # Give each exception handler its header owner or natural first-body explanation.
    for handler in (node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)):
        # Resolve any comment directly adjacent to the handler header.
        direct = associate(handler, blocks)
        # A unique/ambiguous direct result or empty body needs no body-based fallback.
        if direct.owner is not None or direct.ambiguous or not handler.body:
            # Preserve the direct result exactly for this handler key.
            resolved[handler] = direct
            # Continue to the next handler without borrowing body narration.
            continue
        # Select the first handler-body statement as the only natural fallback anchor.
        first = handler.body[0]
        # Preserve each full-line block directly preceding that first body statement.
        following = tuple(
            block
            for block in blocks
            if not block.trailing
            and block.end == first.lineno - 1
            and block.column == first.col_offset
        )
        # Record the sole fallback owner only in the one-candidate state.
        resolved[handler] = Association(
            following[0] if len(following) == 1 else None,
            following,
        )
    # Expose the deterministic statement/handler association mapping.
    return resolved


def _statement_suites(tree: ast.Module) -> Iterator[tuple[ast.stmt, ...]]:
    """Yield every AST field that is a statement suite.

    @param tree parsed module
    @return non-empty statement tuple elements, each preserving one lexical suite order
    """
    # Inspect every AST node for fields Python represents as homogeneous statement lists.
    for node in ast.walk(tree):
        # Inspect each named child field in its AST declaration order.
        for _field, value in ast.iter_fields(node):
            # Empty or non-list fields cannot represent a statement suite.
            if not isinstance(value, list) or not value:
                # Continue to the next AST field without constructing an empty suite.
                continue
            # Retain each statement element from the candidate list in lexical order.
            statements = tuple(item for item in value if isinstance(item, ast.stmt))
            # A suite is valid only when every list element is a statement.
            if statements and len(statements) == len(value):
                # Yield the complete ordered suite as one ownership boundary.
                yield statements


def _blank_between(previous: ast.stmt, current: ast.stmt, lines: Sequence[str]) -> bool:
    """Whether a physical paragraph break separates adjacent suite statements.

    @param previous preceding statement in one suite
    @param current following statement in the same suite
    @param lines ordered source-line elements split without line endings
    @return true when at least one intervening line is empty or whitespace-only
    """
    # Start immediately after the prior statement's inclusive ending line.
    start = getattr(previous, "end_lineno", previous.lineno)
    # True means at least one intervening source element is blank; false keeps one paragraph.
    return any(not line.strip() for line in lines[start : current.lineno - 1])


def _unique_blocks(blocks: Sequence[CommentBlock]) -> tuple[CommentBlock, ...]:
    """Deduplicate candidates while preserving lexical ownership order.

    @param blocks candidate owner elements in direct/inherited lexical order
    @return candidate elements in first-seen order without repeated block identities
    """
    # Use insertion-ordered mapping keys to preserve the first occurrence of each immutable block.
    return tuple(dict.fromkeys(blocks))


def parent_map(tree: ast.AST) -> Mapping[ast.AST, ast.AST]:
    """Build child-to-parent links absent from Python's AST.

    @param tree parsed module
    @return mapping from each non-root child key to its direct parent value;
        insertion order follows AST traversal
    """
    # Materialize each direct child edge while the enclosing node is known.
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _statement_owner(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> ast.AST:
    """Find the nearest statement that can carry a lexical comment.

    @param node binding target or expression
    @param parents mapping whose each child-AST key names its direct parent-AST value;
        mapping iteration order is deliberately unused
    @return nearest statement, or the original node when detached
    """
    # Begin at the binding target or expression whose lexical statement owner is required.
    current = node
    # Climb direct parent links until the first statement boundary or a detached root.
    while current in parents and not isinstance(current, ast.stmt):
        # Advance exactly one AST edge toward the module root.
        current = parents[current]
    # Return the nearest statement, or the original detached node when no parent edge exists.
    return current


def _names(target: ast.AST) -> Iterator[tuple[str, int]]:
    """Flatten every name introduced by one assignment-like target.

    @param target assignment, loop, with, walrus, or pattern target
    @return non-discarded identifier/line pair elements in AST traversal order
    """
    # Inspect every descendant of the assignment-like target for stored names.
    for node in ast.walk(target):
        # Admit only store-context names whose spelling does not declare intentional discard.
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and node.id not in DISCARD_NAMES
        ):
            # Expose the exact identifier and one-based binding line as one record.
            yield node.id, node.lineno


def _pattern_names(pattern: ast.pattern) -> Iterator[tuple[str, int]]:
    """Flatten capture names from one structural pattern.

    @param pattern match-case pattern
    @return non-discarded capture/line pair elements in AST traversal order
    """
    # Inspect every descendant of the structural pattern for string-valued captures.
    for node in ast.walk(pattern):
        # True means a name/star capture exists and is neither absent nor a discard spelling.
        named_capture = isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name not in {
            None,
            *DISCARD_NAMES,
        }
        # Ordinary and star patterns expose their accepted capture through `name`.
        if named_capture:
            # Yield the non-null capture spelling and one-based pattern line.
            yield node.name, node.lineno
        # Mapping-rest patterns expose their capture through a distinct string field.
        elif isinstance(node, ast.MatchMapping) and node.rest not in {None, *DISCARD_NAMES}:
            # Yield the non-null rest capture and one-based mapping-pattern line.
            yield node.rest, node.lineno


def bindings(tree: ast.Module) -> tuple[Binding, ...]:
    """Enumerate every non-parameter local binding shape governed by v5.

    Module and class assignments remain structured Doxygen entities and are not
    returned. Function-local assignments, destructuring, loops, comprehensions,
    context aliases, exception aliases, walruses, and pattern captures are.

    @param tree parsed Python module
    @return binding record elements ordered by source line, name, then shape
    """
    # Build the child-to-parent map needed for callable scope and statement ownership.
    parents = parent_map(tree)
    # Accumulate each discovered binding record before imposing the public stable order.
    found: list[Binding] = []
    # Inspect every AST node for one of the explicitly governed binding shapes.
    for node in ast.walk(tree):
        # Resolve the nearest callable owner, or None for module/class scope.
        function = _enclosing_function(node, parents)
        # Module and class bindings remain Doxygen entities rather than local narration subjects.
        if function is None:
            # Continue to the next AST node without duplicating entity coverage.
            continue
        # Declare the ordered name/line pair stream selected by the shape dispatch below.
        pairs: Iterator[tuple[str, int]]
        # Default ownership to the nearest statement containing this binding node.
        owner: ast.AST = _statement_owner(node, parents)
        # Declare the stable human-readable binding-shape label for findings.
        shape: str
        # Assignments own their direct stored targets and attach narration to the assignment itself.
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            # Preserve each assignment target in source order across simple and annotated forms.
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            # Flatten every target's non-discarded names in target then AST order.
            pairs = (pair for target in targets for pair in _names(target))
            # Classify every assignment variant under the stable shared finding label.
            shape = "assignment"
            # The assignment statement is the precise lexical narration owner.
            owner = node
        # Loop targets are owned by the compound loop operation.
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            # Flatten every non-discarded target name in AST order.
            pairs = _names(node.target)
            # Identify the distinct loop-target binding form for remediation.
            shape = "loop target"
            # Attach the target to the compound loop header's narration.
            owner = node
        # Comprehension targets attach to the containing expression or outer decorator expression.
        elif isinstance(node, ast.comprehension):
            # Flatten every non-discarded comprehension-target name in AST order.
            pairs = _names(node.target)
            # Identify the distinct comprehension-target binding form.
            shape = "comprehension target"
            # Prefer an attachable outer decorator expression for a nested comprehension.
            owner = _decorator_owner(node, parents) or owner
        # Context-manager aliases bind only when an `as` target is present.
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            # Flatten every non-discarded alias target name in AST order.
            pairs = _names(node.optional_vars)
            # Identify the context-manager alias form for localized findings.
            shape = "context-manager alias"
        # Exception handlers carry an optional string-valued alias.
        elif isinstance(node, ast.ExceptHandler) and node.name is not None:
            # Expose the sole alias as a one-element ordered iterator.
            pairs = iter(((node.name, node.lineno),))
            # Identify the exception-alias form for localized findings.
            shape = "exception alias"
            # Attach exception aliases to the handler whose narration explains translation.
            owner = node
        # Assignment expressions bind names inside a containing expression.
        elif isinstance(node, ast.NamedExpr):
            # Flatten every non-discarded walrus target name in AST order.
            pairs = _names(node.target)
            # Identify the assignment-expression form for localized findings.
            shape = "assignment expression"
        # Match cases can introduce multiple structural-pattern captures.
        elif isinstance(node, ast.match_case):
            # Flatten every non-discarded pattern capture in AST order.
            pairs = _pattern_names(node.pattern)
            # Identify the pattern-capture form for localized findings.
            shape = "pattern capture"
            # Attach captures to the nearest statement owning the pattern syntax.
            owner = _statement_owner(node.pattern, parents)
        # Every other AST node introduces no independently governed local binding.
        else:
            # Continue the census without constructing an uninitialized binding record.
            continue
        # Materialize one binding record per discovered pair using the shared shape and owner.
        found.extend(Binding(name, line, shape, owner) for name, line in pairs)
    # Sort each record by source line, spelling, and shape to remove AST traversal instability.
    return tuple(sorted(found, key=lambda item: (item.line, item.name, item.shape)))


def _decorator_owner(
    node: ast.AST,
    parents: Mapping[ast.AST, ast.AST],
) -> ast.expr | None:
    """Return the decorator expression containing a nested binding.

    A function definition's AST line starts at ``def``, while human narration
    must sit above the first decorator. Treating the definition as owner would
    therefore make a decorator comprehension impossible to document. The outer
    decorator expression has the attachable lexical line and remains unique.

    @param node binding nested somewhere in a decorator expression
    @param parents mapping whose each child-AST key names its direct parent-AST value;
        mapping iteration order is deliberately unused
    @return outer decorator expression, or None outside decorators
    """
    # Begin at the nested binding and climb toward a statement or definition boundary.
    current = node
    # Traverse direct parents until the binding is classified inside or outside a decorator.
    while current in parents:
        # Read the direct parent while retaining `current` as its child edge.
        parent = parents[current]
        # A definition boundary can confirm whether the child is one of its decorators.
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # True means the current expression is an outer decorator; false means another child.
            attachable = current in parent.decorator_list and isinstance(current, ast.expr)
            # Return the attachable expression or the explicit non-decorator alternative.
            return current if attachable else None
        # A statement reached first proves the nested binding is outside decorator expressions.
        if isinstance(parent, ast.stmt):
            # Return no decorator owner and let the ordinary statement owner stand.
            return None
        # Advance one parent edge while preserving the child relationship for the next iteration.
        current = parent
    # A detached node cannot belong to a definition's decorator list.
    return None


def _enclosing_function(
    node: ast.AST, parents: Mapping[ast.AST, ast.AST]
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Find the callable scope owning one node.

    @param node candidate local operation
    @param parents mapping whose each child-AST key names its direct parent-AST value;
        mapping iteration order is deliberately unused
    @return nearest function, or None at module/class scope
    """
    # Begin at the candidate operation and climb direct parent links toward callable scope.
    current = node
    # Traverse until the nearest function definition is found or the node becomes detached.
    while current in parents:
        # Advance exactly one direct parent edge.
        current = parents[current]
        # The first enclosing synchronous or asynchronous function owns local binding semantics.
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Return the nearest callable without borrowing an outer nested function.
            return current
    # None means the candidate is at module/class scope or detached from the parsed tree.
    return None
