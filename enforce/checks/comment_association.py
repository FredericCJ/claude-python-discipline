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
## Binding names that intentionally discard their value.
DISCARD_NAMES: Final = frozenset({"_", "__"})


@dataclass(frozen=True, slots=True)
class CommentBlock:
    """One contiguous qualifying ordinary-comment block."""

    ## Inclusive source line range and indentation column.
    start: int
    end: int
    column: int
    ## Semantic prose with comment markers removed.
    text: str
    ## True when code precedes the first marker on its line.
    trailing: bool


@dataclass(frozen=True, slots=True)
class Association:
    """The comment ownership result for one AST operation."""

    ## Exactly one block on success; absent for missing or ambiguous ownership.
    owner: CommentBlock | None
    ## Candidate owners when more than one competed.
    candidates: tuple[CommentBlock, ...]

    @property
    def ambiguous(self) -> bool:
        """Whether more than one comment could own the operation.

        @return true only for conflicting candidates
        """
        return len(self.candidates) > 1


@dataclass(frozen=True, slots=True)
class Binding:
    """One locally bound name and the statement whose comment owns it."""

    ## Exact identifier and source line.
    name: str
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
    stripped = raw.strip()
    if stripped.startswith("##") or stripped in {"#", "#!"}:
        return False
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
    @return blocks in lexical order
    """
    lines = text.splitlines()
    tokens = _comment_tokens(text, lines)
    blocks: list[CommentBlock] = []
    for row, column, prose, trailing in tokens:
        previous = blocks[-1] if blocks else None
        if (
            previous is not None
            and not trailing
            and not previous.trailing
            and previous.end + 1 == row
            and previous.column == column
        ):
            blocks[-1] = CommentBlock(
                previous.start,
                row,
                column,
                f"{previous.text} {prose}".strip(),
                trailing=False,
            )
        else:
            blocks.append(CommentBlock(row, row, column, prose, trailing))
    return tuple(blocks)


def _comment_tokens(text: str, lines: Sequence[str]) -> tuple[tuple[int, int, str, bool], ...]:
    """Tokenize qualifying comments while containing malformed-source failure.

    @param text complete Python source
    @param lines source lines used to distinguish trailing comments
    @return row, column, prose, and trailing-state tuples
    """
    try:
        stream = tokenize.generate_tokens(io.StringIO(text).readline)
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
    except (IndentationError, tokenize.TokenError):
        return ()


def associate(node: ast.AST, blocks: Sequence[CommentBlock]) -> Association:
    """Resolve the exact lexical comment owner of one AST operation.

    @param node statement or expression carrying source positions
    @param blocks qualifying comments from the same module
    @return missing, unique, or ambiguous association
    """
    line = getattr(node, "lineno", 0)
    end = getattr(node, "end_lineno", line)
    column = getattr(node, "col_offset", 0)
    candidates = tuple(
        block
        for block in blocks
        if (
            (block.trailing and line <= block.start <= end)
            or (not block.trailing and block.end == line - 1 and block.column == column)
        )
    )
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
    @param blocks qualifying ordinary comment blocks from that text
    @return each statement and exception handler mapped to its exact association
    """
    lines = text.splitlines()
    resolved: dict[ast.AST, Association] = {}
    for suite in _statement_suites(tree):
        active: CommentBlock | None = None
        previous: ast.stmt | None = None
        for statement in suite:
            if previous is not None and _blank_between(previous, statement, lines):
                active = None

            direct = associate(statement, blocks)
            preceding = tuple(block for block in direct.candidates if not block.trailing)
            trailing = tuple(block for block in direct.candidates if block.trailing)
            if preceding:
                active = preceding[-1]

            candidates = _unique_blocks((*((active,) if active is not None else ()), *trailing))
            resolved[statement] = Association(
                candidates[0] if len(candidates) == 1 else None,
                candidates,
            )
            if trailing:
                active = None
            previous = statement

    for handler in (node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)):
        direct = associate(handler, blocks)
        if direct.owner is not None or direct.ambiguous or not handler.body:
            resolved[handler] = direct
            continue
        first = handler.body[0]
        following = tuple(
            block
            for block in blocks
            if not block.trailing
            and block.end == first.lineno - 1
            and block.column == first.col_offset
        )
        resolved[handler] = Association(
            following[0] if len(following) == 1 else None,
            following,
        )
    return resolved


def _statement_suites(tree: ast.Module) -> Iterator[tuple[ast.stmt, ...]]:
    """Yield every AST field that is a statement suite.

    @param tree parsed module
    @return non-empty statement tuples, each preserving one lexical suite
    """
    for node in ast.walk(tree):
        for _field, value in ast.iter_fields(node):
            if not isinstance(value, list) or not value:
                continue
            statements = tuple(item for item in value if isinstance(item, ast.stmt))
            if statements and len(statements) == len(value):
                yield statements


def _blank_between(previous: ast.stmt, current: ast.stmt, lines: Sequence[str]) -> bool:
    """Whether a physical paragraph break separates adjacent suite statements.

    @param previous preceding statement in one suite
    @param current following statement in the same suite
    @param lines source text split without line endings
    @return true when at least one intervening line is empty or whitespace-only
    """
    start = getattr(previous, "end_lineno", previous.lineno)
    return any(not line.strip() for line in lines[start : current.lineno - 1])


def _unique_blocks(blocks: Sequence[CommentBlock]) -> tuple[CommentBlock, ...]:
    """Deduplicate candidates while preserving lexical ownership order.

    @param blocks possible direct and inherited owners
    @return candidates without repeated block identities
    """
    return tuple(dict.fromkeys(blocks))


def parent_map(tree: ast.AST) -> Mapping[ast.AST, ast.AST]:
    """Build child-to-parent links absent from Python's AST.

    @param tree parsed module
    @return every non-root node mapped to its direct parent
    """
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _statement_owner(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> ast.AST:
    """Find the nearest statement that can carry a lexical comment.

    @param node binding target or expression
    @param parents child-to-parent map
    @return nearest statement, or the original node when detached
    """
    current = node
    while current in parents and not isinstance(current, ast.stmt):
        current = parents[current]
    return current


def _names(target: ast.AST) -> Iterator[tuple[str, int]]:
    """Flatten every name introduced by one assignment-like target.

    @param target assignment, loop, with, walrus, or pattern target
    @return non-discarded identifiers with their source line
    """
    for node in ast.walk(target):
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and node.id not in DISCARD_NAMES
        ):
            yield node.id, node.lineno


def _pattern_names(pattern: ast.pattern) -> Iterator[tuple[str, int]]:
    """Flatten capture names from one structural pattern.

    @param pattern match-case pattern
    @return non-discarded captures with their source line
    """
    for node in ast.walk(pattern):
        named_capture = isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name not in {
            None,
            *DISCARD_NAMES,
        }
        if named_capture:
            yield node.name, node.lineno
        elif isinstance(node, ast.MatchMapping) and node.rest not in {None, *DISCARD_NAMES}:
            yield node.rest, node.lineno


def bindings(tree: ast.Module) -> tuple[Binding, ...]:
    """Enumerate every non-parameter local binding shape governed by v5.

    Module and class assignments remain structured Doxygen entities and are not
    returned. Function-local assignments, destructuring, loops, comprehensions,
    context aliases, exception aliases, walruses, and pattern captures are.

    @param tree parsed Python module
    @return stable binding records in source order
    """
    parents = parent_map(tree)
    found: list[Binding] = []
    for node in ast.walk(tree):
        function = _enclosing_function(node, parents)
        if function is None:
            continue
        pairs: Iterator[tuple[str, int]]
        owner: ast.AST = _statement_owner(node, parents)
        shape: str
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            pairs = (pair for target in targets for pair in _names(target))
            shape = "assignment"
            owner = node
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            pairs = _names(node.target)
            shape = "loop target"
            owner = node
        elif isinstance(node, ast.comprehension):
            pairs = _names(node.target)
            shape = "comprehension target"
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            pairs = _names(node.optional_vars)
            shape = "context-manager alias"
        elif isinstance(node, ast.ExceptHandler) and node.name is not None:
            pairs = iter(((node.name, node.lineno),))
            shape = "exception alias"
            owner = node
        elif isinstance(node, ast.NamedExpr):
            pairs = _names(node.target)
            shape = "assignment expression"
        elif isinstance(node, ast.match_case):
            pairs = _pattern_names(node.pattern)
            shape = "pattern capture"
            owner = _statement_owner(node.pattern, parents)
        else:
            continue
        found.extend(Binding(name, line, shape, owner) for name, line in pairs)
    return tuple(sorted(found, key=lambda item: (item.line, item.name, item.shape)))


def _enclosing_function(
    node: ast.AST, parents: Mapping[ast.AST, ast.AST]
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Find the callable scope owning one node.

    @param node candidate local operation
    @param parents child-to-parent map
    @return nearest function, or None at module/class scope
    """
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
    return None
