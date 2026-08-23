"""Check mechanically inferable semantic content in documentation owners.

The mechanism checks presence of declared words and structured fields. It does
not claim that prose is true; DOC-028 assigns that residual to content-bound
adversarial review.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final

from . import Finding, ModuleCheck, main
from .comment_association import (
    Association,
    CommentBlock,
    associate,
    bindings,
    comment_blocks,
    semantic_associations,
)
from .doc_narration import EFFECT_METHODS
from .doc_style import _hash_block_text
from .documentation_model import (
    DocumentationModelError,
    SemanticProperty,
    governed_paths,
    load,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path

## Collection annotation roots whose element and ordering semantics are not in
## the type itself.
COLLECTION_TYPES: Final = frozenset({
    "dict",
    "frozenset",
    "list",
    "Mapping",
    "MutableMapping",
    "Sequence",
    "set",
    "tuple",
})
## Detectable prose fields for collection completeness.
ELEMENT_MEANING = re.compile(
    r"\b(?:each|element|elements|item|items|key|keys|value|values|maps? from)\b", re.IGNORECASE
)
ORDER_MEANING = re.compile(
    r"\b(?:order|ordered|ordering|unordered|preserv\w*|sorted|sequence)\b", re.IGNORECASE
)
## Doxygen-compatible custom effects paragraph.
EFFECTS_FIELD = re.compile(r"@par\s+Effects\b(?P<text>.*?)(?=\n\s*@|\Z)", re.IGNORECASE | re.DOTALL)
## One parameter record through the next Doxygen command.
PARAMETER_FIELD = re.compile(
    r"@param\s+\**(?P<name>\w+)\s+(?P<text>.*?)(?=\n\s*@|\Z)",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class DocumentedValue:
    """One typed or literal value and the prose allocated to it."""

    ## Identifier, source line, and documentation owner text.
    name: str
    line: int
    text: str | None
    ## Mechanically inferred semantic categories.
    boolean: bool
    collection: bool


class DocSemanticsCheck(ModuleCheck):
    """Report missing state, collection, property, and effect meaning."""

    ## Invoked as `python -m checks.doc_semantics`.
    name = "doc_semantics"
    ## Semantic property, callable effect, and truth-synchronization obligations.
    rules = ("DOC-026", "DOC-027")

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Inspect every production, test, maintenance, and generated Python file.

        @param paths ordinary source-root fallback
        @return semantic-content findings
        """
        return super().run(governed_paths(self.declaration, paths))

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Check all mechanically inferable semantic obligations in one module.

        @param tree parsed module
        @param path source file
        @param _layer architectural layer, unused
        @return semantic-content findings
        """
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        blocks = comment_blocks(source)
        try:
            model = load(self.declaration)
        except DocumentationModelError:
            return
        root = self.declaration.root
        if root is None:
            return
        relative = PurePosixPath(path.resolve().relative_to(root.resolve()).as_posix())

        associations = semantic_associations(tree, source, blocks)
        for value in documented_values(tree, lines, blocks, associations):
            yield from _value_findings(value, path, model.properties_for(value.name, relative))

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield from _callable_findings(node, path)


def _value_findings(
    value: DocumentedValue,
    path: Path,
    properties: Sequence[SemanticProperty],
) -> Iterator[Finding]:
    """Report state, collection, and project-property omissions for one value.

    @param value documented value subject
    @param path source file
    @param properties applicable project semantic-property records
    @return independently actionable content findings
    """
    text = value.text or ""
    if value.boolean and not _both_boolean_states(text):
        yield Finding(
            "DOC-026",
            path,
            value.line,
            f"boolean `{value.name}` documentation does not define both true and false",
            "State what true means and what false means at the value's documentation owner.",
            diagnostic_id="BOOLEAN_STATES",
        )
    if value.collection and not ELEMENT_MEANING.search(text):
        yield Finding(
            "DOC-026",
            path,
            value.line,
            f"collection `{value.name}` does not define its element semantics",
            "State what each element, key, and value represents.",
            diagnostic_id="COLLECTION_ELEMENTS",
        )
    if value.collection and not ORDER_MEANING.search(text):
        yield Finding(
            "DOC-026",
            path,
            value.line,
            f"collection `{value.name}` does not define ordering semantics",
            "State whether order is preserved, sorted, significant, or deliberately unordered.",
            diagnostic_id="COLLECTION_ORDER",
        )
    for property_record in properties:
        expected = property_record.value
        property_name = property_record.property.value
        if expected.casefold() not in text.casefold():
            yield Finding(
                "DOC-026",
                path,
                value.line,
                f"`{value.name}` omits declared {property_name} `{expected}`",
                "Put the declared semantic value in this entity or local-step documentation owner.",
                diagnostic_id="DECLARED_PROPERTY",
            )


def _callable_findings(
    node: ast.FunctionDef | ast.AsyncFunctionDef, path: Path
) -> Iterator[Finding]:
    """Report missing structured effect or purity declarations.

    @param node callable definition
    @param path source file
    @return effect-contract findings
    """
    docstring = ast.get_docstring(node) or ""
    effects = EFFECTS_FIELD.search(docstring)
    if _has_detectable_effect(node) and effects is None:
        yield Finding(
            "DOC-027",
            path,
            node.lineno,
            f"{node.name}() has detectable side effects but no `@par Effects` contract",
            "Add `@par Effects` naming externally visible state changes and ordering; "
            "keep implementation sequencing in ordinary comments.",
            diagnostic_id="CALLABLE_EFFECTS",
        )
    if _declares_pure(node) and (effects is None or "pure" not in effects.group("text").casefold()):
        yield Finding(
            "DOC-027",
            path,
            node.lineno,
            f"{node.name}() is marked pure but its Doxygen contract does not say so",
            "Add `@par Effects` with an explicit pure/no-effects statement.",
            diagnostic_id="CALLABLE_PURITY",
        )


def documented_values(
    tree: ast.Module,
    source: list[str],
    blocks: Sequence[CommentBlock],
    associations: Mapping[ast.AST, Association] | None = None,
) -> tuple[DocumentedValue, ...]:
    """Allocate entity, parameter, and local value semantics to their owners.

    @param tree parsed module
    @param source source lines for Doxygen hash blocks
    @param blocks ordinary comment blocks from `comment_association`
    @param associations optional semantic-step ownership map
    @return documented-value subjects in source order
    """
    parents = _parents(tree)
    ownership = associations or semantic_associations(tree, "\n".join(source), blocks)
    values: list[DocumentedValue] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            values.extend(_parameter_values(node))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = _target_names(node.targets if isinstance(node, ast.Assign) else (node.target,))
            boolean, collection = _value_categories(node)
            if _inside_function(node, parents):
                owner = ownership.get(node, associate(node, blocks)).owner
                text = None if owner is None else owner.text
            else:
                text = _hash_block_text(source, node.lineno)
            values.extend(
                DocumentedValue(name, line, text, boolean, collection) for name, line in names
            )

    local_by_key = {(item.name, item.line): item for item in values}
    for binding in bindings(tree):
        key = (binding.name, binding.line)
        if key in local_by_key:
            continue
        owner = ownership.get(
            binding.owner_node, associate(binding.owner_node, blocks)
        ).owner
        text = None if owner is None else owner.text
        values.append(
            DocumentedValue(
                binding.name,
                binding.line,
                text,
                boolean=False,
                collection=False,
            )
        )
    return tuple(sorted(values, key=lambda item: (item.line, item.name)))


def _parameter_values(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[DocumentedValue, ...]:
    """Extract parameter meanings from one callable's structured contract.

    @param node callable definition
    @return typed parameter values excluding self and cls
    """
    docstring = ast.get_docstring(node) or ""
    records = {
        match.group("name"): match.group("text") for match in PARAMETER_FIELD.finditer(docstring)
    }
    arguments = node.args
    found: list[DocumentedValue] = []
    for argument in (
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        *((arguments.vararg,) if arguments.vararg is not None else ()),
        *((arguments.kwarg,) if arguments.kwarg is not None else ()),
    ):
        if argument.arg in {"self", "cls"}:
            continue
        annotation = _annotation_root(argument.annotation)
        found.append(
            DocumentedValue(
                argument.arg,
                argument.lineno,
                records.get(argument.arg),
                annotation == "bool",
                annotation in COLLECTION_TYPES,
            )
        )
    return tuple(found)


def _target_names(targets: Sequence[ast.expr]) -> tuple[tuple[str, int], ...]:
    """Flatten assignment names without treating attributes as new variables.

    @param targets assignment targets
    @return local/entity names and their source lines
    """
    return tuple(
        (part.id, part.lineno)
        for target in targets
        for part in ast.walk(target)
        if isinstance(part, ast.Name) and isinstance(part.ctx, ast.Store)
    )


def _value_categories(node: ast.Assign | ast.AnnAssign) -> tuple[bool, bool]:
    """Infer boolean and collection categories from annotation or literal.

    @param node assignment-like value
    @return boolean and collection flags
    """
    annotation = _annotation_root(node.annotation) if isinstance(node, ast.AnnAssign) else ""
    value = node.value
    boolean = annotation == "bool" or (
        isinstance(value, ast.Constant) and isinstance(value.value, bool)
    )
    collection = annotation in COLLECTION_TYPES or isinstance(
        value, (ast.List, ast.Tuple, ast.Set, ast.Dict, ast.ListComp, ast.SetComp, ast.DictComp)
    )
    return boolean, collection


def _annotation_root(node: ast.expr | None) -> str:
    """Read the outer unqualified name of one annotation.

    @param node annotation expression
    @return outer type name, or empty when unavailable
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _annotation_root(node.value)
    return ""


def _both_boolean_states(text: str) -> bool:
    """Whether prose explicitly names both boolean states.

    @param text allocated documentation
    @return true only when true and false both occur as words
    """
    lowered = text.casefold()
    return (
        re.search(r"\btrue\b", lowered) is not None and re.search(r"\bfalse\b", lowered) is not None
    )


def _has_detectable_effect(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Detect the bounded effect vocabulary shared with narration.

    @param node callable definition
    @return true for known effect calls or state-target assignments
    """
    parameter_names = {
        argument.arg
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
            *((node.args.vararg,) if node.args.vararg is not None else ()),
            *((node.args.kwarg,) if node.args.kwarg is not None else ()),
        )
        if argument.arg not in {"self", "cls"}
    }
    for child in _owned_nodes(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr in EFFECT_METHODS
        ):
            return True
        if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = child.targets if isinstance(child, ast.Assign) else (child.target,)
            roots = {_target_root(target) for target in targets}
            if node.name != "__init__" and (
                "self" in roots or bool(roots.intersection(parameter_names))
            ):
                return True
    return False


def _owned_nodes(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterator[ast.AST]:
    """Walk one callable without borrowing effects from nested definitions.

    @param node callable whose own behavior is inspected
    @return descendants belonging to this callable's execution scope
    """
    pending = list(reversed(node.body))
    while pending:
        current = pending.pop()
        yield current
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        pending.extend(reversed(list(ast.iter_child_nodes(current))))


def _target_root(node: ast.AST) -> str | None:
    """Return the base name whose attribute or item an assignment changes.

    @param node assignment target
    @return root identifier for attribute/subscript targets, otherwise None
    """
    if isinstance(node, ast.Name):
        return None
    current = node
    while isinstance(current, (ast.Attribute, ast.Subscript)):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def _declares_pure(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether a callable explicitly opts into the purity proposition.

    @param node callable definition
    @return true for a decorator whose terminal name is `pure`
    """
    return any(
        (isinstance(decorator, ast.Name) and decorator.id == "pure")
        or (isinstance(decorator, ast.Attribute) and decorator.attr == "pure")
        for decorator in node.decorator_list
    )


def _parents(tree: ast.AST) -> Mapping[ast.AST, ast.AST]:
    """Build child-to-parent links for scope classification.

    @param tree parsed module
    @return every non-root node mapped to its direct parent
    """
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _inside_function(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> bool:
    """Whether an assignment belongs to a callable rather than module/class scope.

    @param node assignment node
    @param parents child-to-parent map
    @return true when a callable is encountered before the module
    """
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return True
        if isinstance(current, ast.Module):
            return False
    return False


if __name__ == "__main__":
    raise SystemExit(main(DocSemanticsCheck()))
