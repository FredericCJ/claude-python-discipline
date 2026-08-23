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
from .doc_narration import _effect_call
from .doc_style import _hash_block_text
from .documentation_model import (
    DocumentationModelError,
    SemanticProperty,
    governed_paths,
    load,
)

# Import static traversal, mapping, and path contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path

## Unordered annotation-root set whose each element denotes a collection type whose element and
## ordering semantics are not in the type itself.
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
## Prose pattern establishing that collection element, item, key, or value meaning is present.
ELEMENT_MEANING = re.compile(
    r"\b(?:each|element|elements|item|items|key|keys|value|values|maps? from)\b", re.IGNORECASE
)
## Prose pattern establishing that collection order, sequence, preservation, or sorting is present.
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

    ## Exact identifier spelling whose semantic content is inspected.
    name: str
    ## One-based source line at which the value is introduced.
    line: int
    ## Allocated documentation-owner prose, or None when no owner exists.
    text: str | None
    ## True when both Boolean states require meaning; false for a non-Boolean value.
    boolean: bool
    ## True when element and ordering semantics apply; false for a scalar value.
    collection: bool


class DocSemanticsCheck(ModuleCheck):
    """Report missing state, collection, property, and effect meaning."""

    ## Invoked as `python -m checks.doc_semantics`.
    name = "doc_semantics"
    ## Ordered rule-id elements for semantic properties then callable effects.
    rules = ("DOC-026", "DOC-027")

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Inspect every production, test, maintenance, and generated Python file.

        @param paths fallback path elements in caller order when no valid model owns discovery
        @return semantic-content finding elements in governed-file order
        """
        # Delegate the model-governed path sequence to the shared one-pass module runner.
        return super().run(governed_paths(self.declaration, paths))

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Check all mechanically inferable semantic obligations in one module.

        @param tree parsed module
        @param path source file
        @param _layer architectural layer, unused
        @return semantic-content finding elements in value then callable traversal order
        @par Effects Reads the governed source and documentation model without modifying them.
        """
        # Read the complete source text once for line, block, and association allocation.
        source = path.read_text(encoding="utf-8")
        # Preserve each source-line element in lexical order for Doxygen hash-block lookup.
        lines = source.splitlines()
        # Preserve each qualifying ordinary comment block in lexical source order.
        blocks = comment_blocks(source)
        # Load the strict project-owned semantic-property model before inspecting values.
        try:
            # Hold the complete typed model used for scope and property resolution.
            model = load(self.declaration)
        # Let the model-owning check report a malformed declaration exactly once.
        except DocumentationModelError:
            # Suppress dependent semantic output because no valid policy can be applied.
            return
        # Resolve the governed repository boundary from the parsed project declaration.
        root = self.declaration.root
        # A synthetic declaration without a root has no repository-relative property scope.
        if root is None:
            # Produce no dependent finding when scope ownership cannot be established.
            return
        # Express the source as the repository-relative POSIX path used by property scopes.
        relative = PurePosixPath(path.resolve().relative_to(root.resolve()).as_posix())

        # Resolve suite-aware narration ownership once for every documented local value.
        associations = semantic_associations(tree, source, blocks)
        # Judge each entity, parameter, and local value in stable source order.
        for value in documented_values(tree, lines, blocks, associations):
            # Yield independent state, collection, and declared-property omissions for this value.
            yield from _value_findings(value, path, model.properties_for(value.name, relative))

        # Inspect every nested callable for detectable effects and explicit purity declarations.
        for node in ast.walk(tree):
            # Synchronous and asynchronous callables share the same effect-contract allocation.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Yield each missing effect or purity field at the callable definition.
                yield from _callable_findings(node, path)


def _value_findings(
    value: DocumentedValue,
    path: Path,
    properties: Sequence[SemanticProperty],
) -> Iterator[Finding]:
    """Report state, collection, and project-property omissions for one value.

    @param value documented value subject
    @param path source file
    @param properties applicable semantic-property record elements in model order
    @return independently actionable finding elements in state, collection, then property order
    """
    # Normalize an absent documentation owner to empty prose for bounded presence checks.
    text = value.text or ""
    # A Boolean value requires explicit meanings for both true and false states.
    if value.boolean and not _both_boolean_states(text):
        # Report the exact value whose allocated prose omits one or both states.
        yield Finding(
            "DOC-026",
            path,
            value.line,
            f"boolean `{value.name}` documentation does not define both true and false",
            "State what true means and what false means at the value's documentation owner.",
            diagnostic_id="BOOLEAN_STATES",
        )
    # A collection value requires prose naming what each contained element represents.
    if value.collection and not ELEMENT_MEANING.search(text):
        # Report element semantics independently from ordering semantics.
        yield Finding(
            "DOC-026",
            path,
            value.line,
            f"collection `{value.name}` does not define its element semantics",
            "State what each element, key, and value represents.",
            diagnostic_id="COLLECTION_ELEMENTS",
        )
    # A collection value also requires its preserved, sorted, significant, or unordered policy.
    if value.collection and not ORDER_MEANING.search(text):
        # Report ordering semantics independently from element semantics.
        yield Finding(
            "DOC-026",
            path,
            value.line,
            f"collection `{value.name}` does not define ordering semantics",
            "State whether order is preserved, sorted, significant, or deliberately unordered.",
            diagnostic_id="COLLECTION_ORDER",
        )
    # Check every project-declared semantic property applicable to this identifier and path.
    for property_record in properties:
        # Select the exact project-owned semantic value expected in allocated prose.
        expected = property_record.value
        # Select the stable property-category spelling for the diagnostic contract.
        property_name = property_record.property.value
        # Case-insensitive absence is mechanically decidable; truth remains review-owned.
        if expected.casefold() not in text.casefold():
            # Report the exact missing property value at the documented value's source line.
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
    @return effect-contract finding elements in effect then purity order
    """
    # Read the callable's cleaned structured contract, or empty prose when absent.
    docstring = ast.get_docstring(node) or ""
    # Resolve the optional Doxygen Effects paragraph and its captured content.
    effects = EFFECTS_FIELD.search(docstring)
    # Detectable externally visible behavior requires a structured effects contract.
    if _has_detectable_effect(node) and effects is None:
        # Report the missing field at the exact callable definition.
        yield Finding(
            "DOC-027",
            path,
            node.lineno,
            f"{node.name}() has detectable side effects but no `@par Effects` contract",
            "Add `@par Effects` naming externally visible state changes and ordering; "
            "keep implementation sequencing in ordinary comments.",
            diagnostic_id="CALLABLE_EFFECTS",
        )
    # A callable explicitly marked pure must also say pure in its Effects paragraph.
    if _declares_pure(node) and (effects is None or "pure" not in effects.group("text").casefold()):
        # Report a missing or semantically incomplete purity field independently.
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
    @param source ordered source-line elements for Doxygen hash-block lookup
    @param blocks ordinary comment-block elements in lexical order
    @param associations optional mapping from each governed AST key to its association value;
        mapping iteration order is deliberately unused
    @return documented-value elements ordered by source line then name
    """
    # Build direct parent links for function-local versus entity-scope classification.
    parents = _parents(tree)
    # Use the supplied association mapping, or derive it once from the exact reconstructed text.
    ownership = associations or semantic_associations(tree, "\n".join(source), blocks)
    # Accumulate each parameter, assignment, and residual local value in discovery order.
    values: list[DocumentedValue] = []
    # Inspect every AST node for a parameter-owning callable or assignment-like value.
    for node in ast.walk(tree):
        # Callable contracts allocate semantic prose to their caller-supplied parameters.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Append each typed parameter record in signature order.
            values.extend(_parameter_values(node))
        # Assignment and annotated assignment values may be local or Doxygen entities.
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            # Flatten each stored name/line pair in assignment-target order.
            names = _target_names(node.targets if isinstance(node, ast.Assign) else (node.target,))
            # Infer the shared Boolean and collection category states from annotation or literal.
            boolean, collection = _value_categories(node)
            # Function-local values take prose from their ordinary semantic-step owner.
            if _inside_function(node, parents):
                # Resolve the unique owner through suite-aware mapping or direct adjacency fallback.
                owner = ownership.get(node, associate(node, blocks)).owner
                # Retain absent owner as None; otherwise retain its complete semantic prose.
                text = None if owner is None else owner.text
            # Module and class assignments take prose from their allocated Doxygen hash block.
            else:
                # Read the immediately adjacent entity block, or None when absent.
                text = _hash_block_text(source, node.lineno)
            # Append one documented-value record for every assignment name in target order.
            values.extend(
                DocumentedValue(name, line, text, boolean, collection) for name, line in names
            )

    # Index each existing name/line key to its value record; mapping order is deliberately unused.
    local_by_key = {(item.name, item.line): item for item in values}
    # Add binding shapes not already represented by assignment or parameter discovery.
    for binding in bindings(tree):
        # Construct a two-element identity tuple in name-then-line order for census lookup.
        key = (binding.name, binding.line)
        # An existing assignment value already carries stronger inferred semantic categories.
        if key in local_by_key:
            # Continue without duplicating the same local binding subject.
            continue
        # Resolve this binding shape's unique semantic-step owner or direct fallback.
        owner = ownership.get(
            binding.owner_node, associate(binding.owner_node, blocks)
        ).owner
        # Retain absent owner as None; otherwise retain its complete semantic prose.
        text = None if owner is None else owner.text
        # Append the residual binding with false Boolean and collection states unavailable
        # to syntax.
        values.append(
            DocumentedValue(
                binding.name,
                binding.line,
                text,
                boolean=False,
                collection=False,
            )
        )
    # Sort every value record by source line then spelling for deterministic findings.
    return tuple(sorted(values, key=lambda item: (item.line, item.name)))


def _parameter_values(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[DocumentedValue, ...]:
    """Extract parameter meanings from one callable's structured contract.

    @param node callable definition
    @return documented parameter-value elements in signature order, excluding self and cls
    """
    # Read the callable's cleaned structured contract, or empty prose when absent.
    docstring = ast.get_docstring(node) or ""
    # Map each documented parameter-name key to its prose value; mapping order is unused.
    records = {
        match.group("name"): match.group("text") for match in PARAMETER_FIELD.finditer(docstring)
    }
    # Retain parsed argument groups for one ordered signature flattening.
    arguments = node.args
    # Accumulate each non-receiver parameter value in signature order.
    found: list[DocumentedValue] = []
    # Traverse fixed, keyword-only, variadic, and keyword-capture elements in signature order.
    for argument in (
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        *((arguments.vararg,) if arguments.vararg is not None else ()),
        *((arguments.kwarg,) if arguments.kwarg is not None else ()),
    ):
        # Instance and class receivers carry owner identity rather than caller-supplied semantics.
        if argument.arg in {"self", "cls"}:
            # Continue to the next signature element without creating a value subject.
            continue
        # Resolve the annotation's outer unqualified type category.
        annotation = _annotation_root(argument.annotation)
        # Append the parameter, allocated prose, and inferred Boolean/collection states.
        found.append(
            DocumentedValue(
                argument.arg,
                argument.lineno,
                records.get(argument.arg),
                annotation == "bool",
                annotation in COLLECTION_TYPES,
            )
        )
    # Freeze the parameter-value elements in signature order.
    return tuple(found)


def _target_names(targets: Sequence[ast.expr]) -> tuple[tuple[str, int], ...]:
    """Flatten assignment names without treating attributes as new variables.

    @param targets assignment-target elements in source order
    @return name/line pair elements in target then AST traversal order
    """
    # Flatten each target's stored Name descendants while preserving target and AST order.
    return tuple(
        (part.id, part.lineno)
        for target in targets
        for part in ast.walk(target)
        if isinstance(part, ast.Name) and isinstance(part.ctx, ast.Store)
    )


def _value_categories(node: ast.Assign | ast.AnnAssign) -> tuple[bool, bool]:
    """Infer boolean and collection categories from annotation or literal.

    @param node assignment-like value
    @return Boolean-state flag then collection-state flag; each true means applicable and
        false means the corresponding semantic obligation does not apply
    """
    # Resolve an annotated assignment's outer type, or empty when syntax carries no annotation.
    annotation = _annotation_root(node.annotation) if isinstance(node, ast.AnnAssign) else ""
    # Hold the assigned expression used for literal category inference.
    value = node.value
    # True means annotation/literal identifies a Boolean; false means no Boolean evidence.
    boolean = annotation == "bool" or (
        isinstance(value, ast.Constant) and isinstance(value.value, bool)
    )
    # True means annotation/literal identifies a collection; false means no collection evidence.
    collection = annotation in COLLECTION_TYPES or isinstance(
        value, (ast.List, ast.Tuple, ast.Set, ast.Dict, ast.ListComp, ast.SetComp, ast.DictComp)
    )
    # Return the two inferred applicability states in their documented fixed order.
    return boolean, collection


def _annotation_root(node: ast.expr | None) -> str:
    """Read the outer unqualified name of one annotation.

    @param node annotation expression
    @return outer type name, or empty when unavailable
    """
    # A simple annotation name is already its outer unqualified category.
    if isinstance(node, ast.Name):
        # Expose the identifier directly.
        return node.id
    # A qualified annotation is categorized by its terminal attribute spelling.
    if isinstance(node, ast.Attribute):
        # Expose the terminal type name without its module qualifier.
        return node.attr
    # A parameterized annotation retains the category of its outer container expression.
    if isinstance(node, ast.Subscript):
        # Recurse into the unsubscripted value while ignoring type arguments.
        return _annotation_root(node.value)
    # Missing and composite annotations have no safely inferable outer name.
    return ""


def _both_boolean_states(text: str) -> bool:
    """Whether prose explicitly names both boolean states.

    @param text allocated documentation
    @return true only when true and false both occur as words
    """
    # Normalize allocated prose for case-insensitive exact-word state detection.
    lowered = text.casefold()
    # True means both required state words occur; false means at least one state is unexplained.
    return (
        re.search(r"\btrue\b", lowered) is not None and re.search(r"\bfalse\b", lowered) is not None
    )


def _has_detectable_effect(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Detect the bounded effect vocabulary shared with narration.

    @param node callable definition
    @return true for known effect calls or state-target assignments
    """
    # Build an unordered set whose each element is a caller-supplied parameter name.
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
    # Inspect each owned descendant in execution-tree order without entering nested definitions.
    for child in _owned_nodes(node):
        # Calls in the shared bounded effect vocabulary are detectable external sequence points.
        if isinstance(child, ast.Call) and _effect_call(child):
            # True records an externally visible method sequence point.
            return True
        # Assignments can mutate receiver or caller-owned parameter state.
        if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            # Preserve each assignment target in source order across simple and annotated forms.
            targets = child.targets if isinstance(child, ast.Assign) else (child.target,)
            # Build an unordered set whose each element is a target's base owner name or None.
            roots = {_target_root(target) for target in targets}
            # Constructors establish initial state; other receiver/parameter mutations are effects.
            if node.name != "__init__" and (
                "self" in roots or bool(roots.intersection(parameter_names))
            ):
                # True records state externally visible through an existing object or argument.
                return True
        # Deletion can remove receiver or caller-owned parameter state.
        if isinstance(child, ast.Delete):
            # Build an unordered set whose each element is a deleted target's owner name or None.
            roots = {_target_root(target) for target in child.targets}
            # Receiver or parameter membership proves externally visible state deletion.
            if "self" in roots or bool(roots.intersection(parameter_names)):
                # True records deletion visible through an existing object or argument.
                return True
    # False means none of the bounded syntactic effect signals occurred in this callable.
    return False


def _owned_nodes(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterator[ast.AST]:
    """Walk one callable without borrowing effects from nested definitions.

    @param node callable whose own behavior is inspected
    @return descendant elements in depth-first execution-tree order for this callable's scope
    """
    # Seed the LIFO work list with each body statement in reverse lexical order.
    pending = list(reversed(node.body))
    # Traverse until every owned descendant element has been yielded exactly once.
    while pending:
        # Pop the next depth-first element from the end of the work list.
        current = pending.pop()
        # Expose this owned descendant before considering its nested children.
        yield current
        # Nested definitions execute under their own callable/class contract, not this one.
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # Continue without adding the nested definition's children to this work list.
            continue
        # Push child elements in reverse AST order so later pops preserve forward traversal.
        pending.extend(reversed(list(ast.iter_child_nodes(current))))


def _target_root(node: ast.AST) -> str | None:
    """Return the base name whose attribute or item an assignment changes.

    @param node assignment target
    @return root identifier for attribute/subscript targets, otherwise None
    """
    # A simple local name has no external attribute or container owner.
    if isinstance(node, ast.Name):
        # None classifies the target as local-only state.
        return None
    # Strip attribute/subscript layers until their base expression is reached.
    current = node
    # Follow the value edge through every externally addressable target layer.
    while isinstance(current, (ast.Attribute, ast.Subscript)):
        # Advance one ownership layer toward the target's base expression.
        current = current.value
    # Expose a named base owner, or None when the base is a more complex expression.
    return current.id if isinstance(current, ast.Name) else None


def _declares_pure(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether a callable explicitly opts into the purity proposition.

    @param node callable definition
    @return true for a decorator whose terminal name is `pure`
    """
    # True means at least one decorator element has terminal name `pure`; false means no opt-in.
    return any(
        (isinstance(decorator, ast.Name) and decorator.id == "pure")
        or (isinstance(decorator, ast.Attribute) and decorator.attr == "pure")
        for decorator in node.decorator_list
    )


def _parents(tree: ast.AST) -> Mapping[ast.AST, ast.AST]:
    """Build child-to-parent links for scope classification.

    @param tree parsed module
    @return mapping from each non-root child key to its direct parent value;
        insertion order follows AST traversal
    """
    # Materialize each direct child edge while the enclosing node is known.
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _inside_function(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> bool:
    """Whether an assignment belongs to a callable rather than module/class scope.

    @param node assignment node
    @param parents mapping whose each child-AST key names its direct parent-AST value;
        mapping iteration order is deliberately unused
    @return true when a callable is encountered before the module
    """
    # Begin at the assignment and climb direct parent links toward a scope boundary.
    current = node
    # Traverse until a callable or module boundary decides local-versus-entity allocation.
    while current in parents:
        # Advance exactly one direct parent edge.
        current = parents[current]
        # The nearest callable boundary proves local semantic-step ownership.
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # True allocates the assignment to ordinary implementation narration.
            return True
        # A module reached before a callable proves entity-level Doxygen ownership.
        if isinstance(current, ast.Module):
            # False allocates the assignment to an entity hash block.
            return False
    # Detached nodes have no demonstrated callable owner and remain entity-classified.
    return False


# Run the standalone semantic-content check only at this module's process boundary.
if __name__ == "__main__":
    # Convert the check runner's stable result into the process exit status.
    raise SystemExit(main(DocSemanticsCheck()))
