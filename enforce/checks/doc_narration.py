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
from .comment_association import (
    CommentBlock,
    associate,
    bindings,
    comment_blocks,
    semantic_associations,
)
from .documentation_model import governed_paths

# Import static protocol types without adding runtime package dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

## Unordered method-name set whose each element signals an externally observable effect. This
## is a deliberately conservative proxy; project-specific effects remain in
## adversarial review and callable contracts.
EFFECT_METHODS: Final = frozenset({
    "close",
    "commit",
    "flush",
    "mkdir",
    "remove",
    "rename",
    "rmdir",
    "send",
    "unlink",
    "write",
    "write_bytes",
    "write_text",
})
## Unordered dotted-call set whose each element is an unambiguous external effect despite an
## otherwise ambiguous terminal method name. Bare `replace` is excluded because immutable strings
## and filesystem paths share that spelling; companion writes or semantic review own Path.replace.
EFFECT_FUNCTIONS: Final = frozenset({"os.replace"})
## Unordered word set whose each element merely translates common syntax into English.
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
## Word-token pattern used to compare narration vocabulary with syntax vocabulary.
WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
## Minimum count of prose word elements required before narration can add useful meaning.
MINIMUM_NARRATIVE_WORDS: Final = 4
## Ordered expressions for known scaffolding prose that mechanically restates syntax or checker
## state; order is stable only so focused diagnostics remain reproducible.
KNOWN_FILLER_SHAPES: Final = (
    re.compile(r"\bdetails\s*:", re.IGNORECASE),
    re.compile(r"\bcompute\b.+\busing\b.+\bfor later\b.+\blogic\b", re.IGNORECASE),
    re.compile(
        r"\bselect\b.+\bas the current element from\b.+\bwhile\b.+"
        r"\bpreserves traversal order\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bupdate\b.+\bstate only after the required source facts are\b.+\bavailable\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bcapture\b.+\bas the completed\b.+"
        r"\boutcome for subsequent validation or publication\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bselect the guarded path only after\b.+\bis satisfied\b", re.IGNORECASE),
    re.compile(
        r"\bselect the empty-or-disabled path when\b.+\bhas no usable value\b",
        re.IGNORECASE,
    ),
    re.compile(r"\buse the available-value path only when\b", re.IGNORECASE),
    re.compile(
        r"\bbind\b.+\bto the current value used by the next\b.+\bdecision\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bunpack\b.+\busing\b.+\bfor later\b.+\blogic\b", re.IGNORECASE),
)
## Ordered syntax/label pairs; each element maps an AST shape to its operation category.
## State and effect shapes need predicates below.
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
    ## Ordered rule-id elements for presence, association, then detectable content predicates.
    rules = ("DOC-017", "DOC-018", "DOC-019")

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Inspect production, test, and maintenance scopes from the model.

        @param paths fallback path elements in caller order when no valid model owns discovery
        @return finding elements ordered by governed file then source operation
        """
        # Delegate the model-governed path sequence to the shared one-pass module runner.
        return super().run(governed_paths(self.declaration, paths))

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Associate comments with every governed operation in one module.

        @param tree parsed module
        @param path source file
        @param _layer architectural layer, unused
        @return finding elements in source order for missing, ambiguous, or syntactic owners
        @par Effects Reads the governed source file without modifying repository state.
        """
        # Read the complete source text once for both lexical comments and AST association.
        text = path.read_text(encoding="utf-8")
        # Preserve each qualifying ordinary comment block in lexical source order.
        blocks = comment_blocks(text)
        # Identify known scaffolding blocks independently of AST coverage so stray filler cannot
        # hide merely by sitting beside an operation outside the mechanical census.
        rejected_blocks = {block for block in blocks if _known_filler(block.text)}
        # Report each rejected block once before operation-specific findings.
        yield from _known_filler_findings(blocks, rejected_blocks, path)
        # Resolve semantic-operation nodes to their unique, absent, or ambiguous comment owners.
        associations = semantic_associations(tree, text, blocks)
        # Track operation-owner nodes already checked so a local binding on the same statement
        # does not emit a duplicate semantic-content finding.
        checked_nodes: set[ast.AST] = set()
        # Judge every governed operation in stable source-position and category order.
        for operation in operations(tree):
            # Record the exact AST owner before evaluating its associated prose.
            checked_nodes.add(operation.node)
            # Reuse suite-aware ownership, falling back to direct adjacency for isolated nodes.
            association = associations.get(
                operation.node, associate(operation.node, blocks)
            )
            # Multiple candidates expose an ownership ambiguity rather than permission to choose.
            if association.ambiguous:
                # Emit the candidate count and the one-owner remediation at the operation line.
                yield Finding(
                    "DOC-018",
                    path,
                    operation.line,
                    f"{operation.kind} has {len(association.candidates)} possible comment owners",
                    "Leave exactly one ordinary comment immediately above or trailing the "
                    "operation; never make the checker guess ownership.",
                    diagnostic_id="NARRATION_AMBIGUOUS_OWNER",
                )
            # An operation with no qualifying owner lacks procedural documentation.
            elif association.owner is None:
                # Direct the author to the precise ordinary-comment allocation point.
                yield Finding(
                    "DOC-017",
                    path,
                    operation.line,
                    f"{operation.kind} has no implementation narration",
                    "Add an ordinary `#` block immediately above the operation and state "
                    "its semantic role, ordering, or reason.",
                    diagnostic_id="NARRATION_MISSING",
                )
            # A present unique owner still fails when it only translates Python tokens.
            elif association.owner not in rejected_blocks and _syntactic_only(
                operation.node, association.owner.text
            ):
                # Require technical or domain vocabulary while preserving semantic review residuals.
                yield Finding(
                    "DOC-019",
                    path,
                    operation.line,
                    f"{operation.kind} comment only paraphrases Python syntax",
                    "Name the technical or domain operation, represented information, "
                    "ordering, or constraint instead of translating tokens.",
                    diagnostic_id="NARRATION_SYNTACTIC",
                )
        # Plain local assignments are binding steps rather than control/effect operations, but
        # their ordinary comments carry the same semantic-content obligation.
        for binding in bindings(tree):
            # One statement may introduce several bindings; inspect its prose only once.
            if binding.owner_node in checked_nodes:
                # Continue after the earlier operation or binding already decided this owner.
                continue
            # Mark the owner before any absence path so later names on the statement stay deduped.
            checked_nodes.add(binding.owner_node)
            # Reuse the same suite-aware association that DOC-016 uses for binding presence.
            association = associations.get(
                binding.owner_node, associate(binding.owner_node, blocks)
            )
            # Missing and ambiguous owners are reported by coverage; only present prose belongs
            # to DOC-019's semantic-content predicate here.
            if association.owner is None:
                # Advance without duplicating DOC-016 or DOC-018 ownership diagnostics.
                continue
            # Compare the binding-step prose with its complete owning statement.
            if association.owner not in rejected_blocks and _syntactic_only(
                binding.owner_node, association.owner.text
            ):
                # Report one stable finding at the first binding introduced by the statement.
                yield Finding(
                    "DOC-019",
                    path,
                    binding.line,
                    "local-binding comment is scaffolding or only paraphrases Python syntax",
                    "State what the temporary value represents, why it exists, or how the "
                    "step contributes to the surrounding operation.",
                    diagnostic_id="NARRATION_SYNTACTIC",
                )


def operations(tree: ast.Module) -> tuple[Operation, ...]:
    """Enumerate the execution shapes governed by narrative documentation.

    @param tree parsed module
    @return operation elements ordered by source position then category
    """
    # Accumulate each governed operation before imposing the public deterministic order.
    found: list[Operation] = []
    # Inspect every AST node in traversal order for a mechanically governed shape.
    for node in ast.walk(tree):
        # Resolve the node to its stable operation category, or None when ordinary syntax.
        kind = _operation_kind(node)
        # Only governed shapes enter the externally visible operation census.
        if kind is not None:
            # Retain the node, category, and defensive source-line fallback as one record.
            found.append(Operation(node, kind, getattr(node, "lineno", 1)))
    # Sort each operation record by line and category so traversal details cannot reorder output.
    return tuple(sorted(found, key=lambda item: (item.line, item.kind)))


def _operation_kind(node: ast.AST) -> str | None:
    """Classify one AST node when its execution needs narration.

    @param node candidate syntax node
    @return stable operation label, or None for ordinary expression syntax
    """
    # Match direct control-flow and error syntax against the declared category order.
    for syntax, label in OPERATION_KINDS:
        # The first matching syntax category owns the operation label.
        if isinstance(node, syntax):
            # Expose the declared human-readable label for the finding contract.
            return label
    # Attribute and indexed assignments represent externally visible state transitions.
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and _changes_state(node):
        # Separate state transitions from ordinary local representation bindings.
        return "state transition"
    # Attribute and indexed deletion removes state rather than only a local name.
    if isinstance(node, ast.Delete) and _changes_deleted_state(node):
        # Distinguish removal from value replacement in the diagnostic category.
        return "state deletion"
    # Standalone calls to the bounded effect vocabulary expose an external sequence point.
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and _effect_call(node.value):
        # Classify the whole expression statement as the governed effect operation.
        return "externally visible effect"
    # Ordinary expressions and local-only assignments need no operation category here.
    return None


def _changes_state(node: ast.Assign | ast.AnnAssign | ast.AugAssign) -> bool:
    """Whether an assignment mutates an attribute or indexed container.

    @param node assignment-like statement
    @return true for externally visible object/container state targets
    """
    # Preserve each assignment target in source order across simple and annotated forms.
    targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
    # True means at least one target part mutates object/container state; false means local only.
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
    # True means any target part removes object/container state; false means a local name only.
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
    # Resolve a dotted callee name for explicitly qualified effect functions.
    qualified = _callee_name(node.func)
    # True means the terminal method or exact dotted function is effectful; false is ambiguous/pure.
    return (
        isinstance(node.func, ast.Attribute) and node.func.attr in EFFECT_METHODS
    ) or qualified in EFFECT_FUNCTIONS


def _callee_name(node: ast.expr) -> str:
    """Resolve a simple dotted callee name without inferring runtime types.

    @param node callee expression
    @return dotted identifier, or empty text for calls and other dynamic expressions
    """
    # A simple name is already the complete dotted representation.
    if isinstance(node, ast.Name):
        # Expose the identifier spelling directly.
        return node.id
    # An attribute extends its recursively resolved owner name.
    if isinstance(node, ast.Attribute):
        # Join owner and attribute while removing a leading dot from an unknown owner.
        return f"{_callee_name(node.value)}.{node.attr}".lstrip(".")
    # Dynamic callee expressions have no stable qualified name for this bounded proxy.
    return ""


def _syntactic_only(node: ast.AST, prose: str) -> bool:
    """Detect the narrow token-paraphrase anti-pattern without judging truth.

    Passing means only that prose adds vocabulary absent from the syntax. It
    cannot establish that the added meaning is accurate; adversarial review owns
    that residual.

    @param node governed operation
    @param prose associated ordinary comment text
    @return true when no informative extra vocabulary remains
    """
    # Reject recognized migration scaffolding before its incidental identifiers can masquerade
    # as domain vocabulary under the lexical-novelty fallback.
    if _known_filler(prose):
        # True identifies a known filler family independently of the owned AST operation.
        return True
    # Collect each normalized prose word as an unordered vocabulary set.
    prose_words = {word.lower() for word in WORD.findall(prose)}
    # Collect each normalized operation-syntax word as an unordered comparison set.
    syntax_words = {word.lower() for word in WORD.findall(ast.unparse(node))}
    # Retain each prose word absent from both the syntax and the known paraphrase vocabulary.
    informative = prose_words - syntax_words - SYNTACTIC_WORDS
    # True means prose is too short or adds no informative word; false leaves semantic review.
    return len(prose_words) < MINIMUM_NARRATIVE_WORDS or not informative


def _known_filler(prose: str) -> bool:
    """Whether prose matches one closed scaffolding family.

    @param prose normalized ordinary-comment block text
    @return true for a recognized migration template and false for every other shape
    """
    # Match the complete closed template registry without inferring truth from other prose.
    return any(shape.search(prose) is not None for shape in KNOWN_FILLER_SHAPES)


def _known_filler_findings(
    blocks: Sequence[CommentBlock], rejected: set[CommentBlock], path: Path
) -> Iterator[Finding]:
    """Report known scaffolding blocks once in lexical order.

    @param blocks ordinary-comment elements in lexical source order
    @param rejected unordered subset matching the closed filler registry
    @param path governed Python source
    @return one DOC-019 finding per rejected block
    """
    # Preserve lexical block order while selecting only mechanically recognized filler.
    for block in blocks:
        # Unrecognized prose remains under the content-bound review residual.
        if block not in rejected:
            # Continue without claiming that arbitrary prose is true or useful.
            continue
        # Localize the scaffolding itself rather than an incidental neighboring AST node.
        yield Finding(
            "DOC-019",
            path,
            block.start,
            "implementation comment matches a known narration-scaffolding template",
            "Replace the generated shape with prose authored from the actual operation, "
            "representation, ordering, constraint, or reason.",
            diagnostic_id="NARRATION_KNOWN_FILLER",
        )


# Run the standalone check command only at the module's process boundary.
if __name__ == "__main__":
    # Convert the check runner's stable status into this process's exit status.
    raise SystemExit(main(DocNarrationCheck()))
