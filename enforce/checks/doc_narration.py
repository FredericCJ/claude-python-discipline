"""Require semantic implementation narration for governed execution steps.

This check owns ordinary single-hash comments. Doxygen entity comments are
excluded by `comment_association`; docstrings remain the structured contract and
cannot satisfy a local operation.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from . import Finding, ModuleCheck, main
from .comment_association import associate, comment_blocks, semantic_associations
from .documentation_model import governed_paths

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

## Effect-bearing method names whose call order is externally observable. This
## is a deliberately conservative proxy; project-specific effects remain in
## adversarial review and callable contracts.
EFFECT_METHODS: Final = frozenset({
    "close",
    "commit",
    "flush",
    "mkdir",
    "remove",
    "rename",
    "replace",
    "rmdir",
    "send",
    "unlink",
    "write",
    "write_bytes",
    "write_text",
})
## Words that merely translate common syntax into English.
SYNTACTIC_WORDS: Final = frozenset({
    "add",
    "append",
    "assign",
    "call",
    "check",
    "decrement",
    "else",
    "for",
    "if",
    "increment",
    "iterate",
    "loop",
    "one",
    "raise",
    "return",
    "set",
    "subtract",
    "the",
    "then",
    "to",
    "value",
    "whether",
})
WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
MINIMUM_NARRATIVE_WORDS: Final = 4
## Direct syntax-to-operation labels; state and effect shapes need predicates below.
OPERATION_KINDS: Final = (
    (ast.If, "conditional branch"),
    ((ast.For, ast.AsyncFor, ast.While), "loop progression"),
    (ast.ExceptHandler, "exception-handling path"),
    (ast.Try, "protected error-handling sequence"),
    ((ast.With, ast.AsyncWith), "resource-management sequence"),
    (ast.Match, "pattern dispatch"),
    (ast.Return, "return path"),
    (ast.Raise, "error translation or propagation"),
    (ast.Break, "loop exit"),
    (ast.Continue, "loop continuation"),
)


@dataclass(frozen=True, slots=True)
class Operation:
    """One control, state, error, or effect operation requiring narration."""

    ## AST node to which the ordinary comment attaches.
    node: ast.AST
    ## Human-readable operation category.
    kind: str
    ## Stable line used in findings.
    line: int


class DocNarrationCheck(ModuleCheck):
    """Report uncovered, ambiguous, or purely syntactic semantic steps."""

    ## Invoked as `python -m checks.doc_narration`.
    name = "doc_narration"
    ## Presence, association, and detectable content predicates.
    rules = ("DOC-017", "DOC-018", "DOC-019")

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Inspect production, test, and maintenance scopes from the model.

        @param paths ordinary source-root fallback
        @return narration findings over every governed Python file
        """
        return super().run(governed_paths(self.declaration, paths))

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Associate comments with every governed operation in one module.

        @param tree parsed module
        @param path source file
        @param _layer architectural layer, unused
        @return one finding per missing, ambiguous, or syntactic narration owner
        """
        text = path.read_text(encoding="utf-8")
        blocks = comment_blocks(text)
        associations = semantic_associations(tree, text, blocks)
        for operation in operations(tree):
            association = associations.get(
                operation.node, associate(operation.node, blocks)
            )
            if association.ambiguous:
                yield Finding(
                    "DOC-018",
                    path,
                    operation.line,
                    f"{operation.kind} has {len(association.candidates)} possible comment owners",
                    "Leave exactly one ordinary comment immediately above or trailing the "
                    "operation; never make the checker guess ownership.",
                    diagnostic_id="NARRATION_AMBIGUOUS_OWNER",
                )
            elif association.owner is None:
                yield Finding(
                    "DOC-017",
                    path,
                    operation.line,
                    f"{operation.kind} has no implementation narration",
                    "Add an ordinary `#` block immediately above the operation and state "
                    "its semantic role, ordering, or reason.",
                    diagnostic_id="NARRATION_MISSING",
                )
            elif _syntactic_only(operation.node, association.owner.text):
                yield Finding(
                    "DOC-019",
                    path,
                    operation.line,
                    f"{operation.kind} comment only paraphrases Python syntax",
                    "Name the technical or domain operation, represented information, "
                    "ordering, or constraint instead of translating tokens.",
                    diagnostic_id="NARRATION_SYNTACTIC",
                )


def operations(tree: ast.Module) -> tuple[Operation, ...]:
    """Enumerate the execution shapes governed by narrative documentation.

    @param tree parsed module
    @return stable operations ordered by source position and category
    """
    found: list[Operation] = []
    for node in ast.walk(tree):
        kind = _operation_kind(node)
        if kind is not None:
            found.append(Operation(node, kind, getattr(node, "lineno", 1)))
    return tuple(sorted(found, key=lambda item: (item.line, item.kind)))


def _operation_kind(node: ast.AST) -> str | None:
    """Classify one AST node when its execution needs narration.

    @param node candidate syntax node
    @return stable operation label, or None for ordinary expression syntax
    """
    for syntax, label in OPERATION_KINDS:
        if isinstance(node, syntax):
            return label
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and _changes_state(node):
        return "state transition"
    if isinstance(node, ast.Delete) and _changes_deleted_state(node):
        return "state deletion"
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and _effect_call(node.value):
        return "externally visible effect"
    return None


def _changes_state(node: ast.Assign | ast.AnnAssign | ast.AugAssign) -> bool:
    """Whether an assignment mutates an attribute or indexed container.

    @param node assignment-like statement
    @return true for externally visible object/container state targets
    """
    targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
    return any(
        isinstance(part, (ast.Attribute, ast.Subscript))
        for target in targets
        for part in ast.walk(target)
    )


def _changes_deleted_state(node: ast.Delete) -> bool:
    """Whether deletion removes an attribute or indexed-container member.

    @param node deletion statement
    @return true for object or container state targets
    """
    return any(
        isinstance(part, (ast.Attribute, ast.Subscript))
        for target in node.targets
        for part in ast.walk(target)
    )


def _effect_call(node: ast.Call) -> bool:
    """Whether a call's method name is a conservative effect signal.

    @param node call expression
    @return true for one of the mechanically governed effect names
    """
    return isinstance(node.func, ast.Attribute) and node.func.attr in EFFECT_METHODS


def _syntactic_only(node: ast.AST, prose: str) -> bool:
    """Detect the narrow token-paraphrase anti-pattern without judging truth.

    Passing means only that prose adds vocabulary absent from the syntax. It
    cannot establish that the added meaning is accurate; adversarial review owns
    that residual.

    @param node governed operation
    @param prose associated ordinary comment text
    @return true when no informative extra vocabulary remains
    """
    prose_words = {word.lower() for word in WORD.findall(prose)}
    syntax_words = {word.lower() for word in WORD.findall(ast.unparse(node))}
    informative = prose_words - syntax_words - SYNTACTIC_WORDS
    return len(prose_words) < MINIMUM_NARRATIVE_WORDS or not informative


if __name__ == "__main__":
    raise SystemExit(main(DocNarrationCheck()))
