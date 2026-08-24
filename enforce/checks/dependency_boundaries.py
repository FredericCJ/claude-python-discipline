"""Decide the separable static claims in v4's local dependency model.

The checker builds a module index only from this repository's declared source
roots. It reports four independent predicates:

* ``ARCH-001`` — a policy dependency crosses outward;
* ``ARCH-003`` — one adapter boundary imports another;
* ``ARCH-019`` — application orchestration imports a concrete adapter;
* ``ARCH-020`` — a declared foreign technology is directly imported outside
  its one owning adapter boundary.

Only direct imports are claimed. In particular, repository-local shell wiring
may import a real adapter and thereby reach its technology transitively; the
shell does not become a second direct owner.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from . import Check, Finding, iter_python_files

# Import annotation-only collection contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class LocalModule:
    """One indexed module and its declared architectural identity."""

    ## Absolute dotted import name within one declared source root.
    name: str
    ## Local file providing the module.
    path: Path
    ## Canonical check-layer spelling resolved from the declaration.
    role: str
    ## Independently substitutable adapter boundary, or None for shared support.
    adapter_boundary: str | None


def _module_name(path: Path, source_root: Path) -> str:
    """Convert one source file into its absolute import name.

    @param path Python source file beneath ``source_root``
    @param source_root import root declared by the repository
    @return dotted module or package name
    """
    # Derive the import-root-relative path without resolving outside the declared root.
    relative = path.relative_to(source_root)
    # Copy each relative path-segment element into mutable authored order.
    parts = list(relative.parts)
    # Package initializers represent their containing directory rather than a module stem.
    if path.name == "__init__.py":
        # Remove the trailing initializer filename from the ordered segment sequence.
        parts.pop()
    # Ordinary modules replace their filename segment with its suffix-free stem.
    else:
        # Publish the importable module identifier at the final segment position.
        parts[-1] = path.stem
    # Join the ordered import-path segment elements into one absolute dotted name.
    return ".".join(parts)


def _adapter_boundary(
    path: Path,
    root: Path,
    boundaries: Sequence[PurePosixPath],
) -> str | None:
    """Identify the declared independently substitutable adapter boundary.

    Adapter-role support code may sit outside every boundary and be imported by
    several of them. It is not thereby another adapter implementation.

    @param path adapter source file
    @param root governed repository root
    @param boundaries adapter-boundary path elements in declaration order
    @return stable relative boundary spelling, or None outside adapters
    """
    # Resolve the source to one repository-relative POSIX identity.
    relative = PurePosixPath(path.resolve().relative_to(root.resolve()).as_posix())
    # Select the first enclosing boundary element in declaration order.
    for boundary in boundaries:
        # A non-equal, non-ancestor boundary cannot own this adapter source.
        if relative != boundary and not relative.is_relative_to(boundary):
            # Advance to the next declared boundary.
            continue
        # Return the stable repository-relative owner spelling.
        return boundary.as_posix()
    # Shared adapter support outside every independent boundary has no owner identity.
    return None


def _index(check: DependencyBoundariesCheck) -> dict[str, LocalModule]:
    """Build this repository's complete local import index.

    @param check checker carrying the parsed project declaration
    @return mapping from each dotted-name key to its local-module value; insertion order
        follows declared roots and sorted files, while duplicate names leave the last value
    """
    # Select the declaration supplying source roots, roles, and adapter boundaries.
    declaration = check.declaration
    # Legacy declarations without a bounded root cannot produce a local module index.
    if declaration.root is None:
        # Return an insertion-ordered empty mapping.
        return {}
    # Map each dotted module-name key to its indexed local-module value; insertion order
    # follows declared source roots and sorted file traversal.
    indexed: dict[str, LocalModule] = {}
    # Preserve adapter-boundary path elements in declaration order.
    boundaries = declaration.adapter_boundaries
    # Expand each declared source-root element in declaration precedence order.
    for source_root in declaration.source_paths():
        # An absent root is reported by source_roles and contributes no module here.
        if not source_root.is_dir():
            # Advance without treating an empty traversal as module evidence.
            continue
        # Inspect each Python source-path element in stable descendant order.
        for path in iter_python_files([source_root]):
            # Resolve the canonical architectural role from the declaration.
            role = declaration.role_of(path)
            # Unclassified source is reported by source_roles, not indexed under guessed policy.
            if role is None:
                # Advance to the next Python file.
                continue
            # Derive the absolute import name within this declared root.
            name = _module_name(path, source_root)
            # A root-level initializer may legitimately derive an empty package name.
            if not name:
                # Advance because empty text cannot act as an import-index key.
                continue
            # Publish the module value under its dotted key, retaining last-duplicate behavior.
            indexed[name] = LocalModule(
                name=name,
                path=path,
                role=role,
                adapter_boundary=(
                    _adapter_boundary(path, declaration.root, boundaries)
                    if role == "adapters" else None
                ),
            )
    # Return the complete local import index in discovery insertion order.
    return indexed


def _absolute_imports(node: ast.Import | ast.ImportFrom, current: LocalModule) -> Iterator[str]:
    """Yield import spellings resolved relative to the current module.

    @param node import syntax node
    @param current importing local module
    @return candidate absolute-module-name elements in authored import order
    """
    # Direct imports already carry absolute module spellings.
    if isinstance(node, ast.Import):
        # Yield each alias-name element in authored order.
        yield from (alias.name for alias in node.names)
        # Stop before from-import resolution.
        return
    # Start from the explicit from-import module spelling, or empty text.
    base = node.module or ""
    # Relative from-imports must be resolved against the importing package.
    if node.level:
        # Select the current package identity, treating initializers as the package itself.
        package = (
            current.name
            if current.path.name == "__init__.py"
            else current.name.rpartition(".")[0]
        )
        # Split package-name segment elements in dotted order, or use an empty sequence.
        parts = package.split(".") if package else []
        # Translate Python's level into the number of package segments removed.
        ascend = node.level - 1
        # Preserve the package prefix after bounded ascent.
        prefix = parts[: max(0, len(parts) - ascend)]
        # Join prefix then explicit module segment elements into an absolute base.
        base = ".".join((*prefix, *(base.split(".") if base else ())))
    # A non-empty base is itself a candidate imported module or package.
    if base:
        # Yield the resolved base before any imported member candidates.
        yield base
    # Inspect each imported alias element in authored order.
    for alias in node.names:
        # Non-star members beneath a base may themselves be indexed submodules.
        if alias.name != "*" and base:
            # Yield the base-qualified member candidate.
            yield f"{base}.{alias.name}"


def _local_target(name: str, modules: Mapping[str, LocalModule]) -> LocalModule | None:
    """Resolve an import spelling to the most specific indexed local module.

    @param name absolute import spelling
    @param modules mapping from each dotted-module key to its local-module value;
        mapping order is deliberately unused
    @return imported local module or package, if any
    """
    # Preserve module-index iteration order while collecting each prefix-matching value.
    candidates = [
        module for module_name, module in modules.items()
        if name == module_name or name.startswith(f"{module_name}.")
    ]
    # Return the most specific longest module identity, or None when the import is foreign.
    return max(candidates, key=lambda module: len(module.name), default=None)


def _import_root(node: ast.Import | ast.ImportFrom) -> Iterable[tuple[str, int]]:
    """Yield direct absolute import roots and their source lines.

    @param node import syntax node
    @return top-level-root/line pair elements in authored alias order; relative imports are empty
    """
    # Direct imports expose one root package per alias element in authored order.
    if isinstance(node, ast.Import):
        # Return the immutable ordered root/line pair sequence.
        return tuple((alias.name.partition(".")[0], node.lineno) for alias in node.names)
    # Relative and module-less imports have no direct foreign absolute root.
    if node.level or node.module is None:
        # Return the ordered empty pair sequence.
        return ()
    # Return the sole absolute from-import root and source line.
    return ((node.module.partition(".")[0], node.lineno),)


def _edge_finding(source: LocalModule, target: LocalModule, line: int) -> Finding | None:
    """Classify one forbidden local dependency edge without double-reporting it.

    @param source importing local module
    @param target imported local module
    @param line import source line
    @return the one most specific finding, or None for an allowed edge
    """
    # Same-role dependencies are allowed except cross-boundary adapter coupling.
    if source.role == target.role:
        # Independent adapter boundaries may not directly import one another.
        if (
            source.role == "adapters"
            and source.adapter_boundary != target.adapter_boundary
            and target.adapter_boundary is not None
        ):
            # Return the most specific adapter-to-adapter finding for this edge.
            return Finding(
                rule_id="ARCH-003", path=source.path, line=line,
                message=(
                    f"adapter boundary {source.adapter_boundary} imports independent "
                    f"adapter boundary {target.adapter_boundary}"
                ),
                remediation="Move their composition to the repository-local shell.",
                diagnostic_id="ARCH003_ADAPTER_TO_ADAPTER",
            )
        # All other same-role edges satisfy this check's direct-import predicates.
        return None
    # Map each source-role key to its unordered set of allowed target-role values; mapping order
    # is deliberately irrelevant to direct lookup.
    allowed = {
        "domain": {"domain"},
        "ports": {"domain", "ports"},
        "app": {"domain", "ports", "app"},
        "adapters": {"domain", "ports", "adapters"},
        "shell": {"domain", "ports", "app", "adapters", "shell"},
    }
    # Application-to-adapter coupling has a dedicated more specific rule.
    if source.role == "app" and target.role == "adapters":
        # Return the concrete-adapter dependency finding.
        return Finding(
            rule_id="ARCH-019", path=source.path, line=line,
            message=f"application module imports concrete adapter {target.name}",
            remediation="Inject a port contract and select the adapter in the local shell.",
            diagnostic_id="ARCH019_APPLICATION_TO_ADAPTER",
        )
    # Any other target outside the source role's inward dependency set crosses policy outward.
    if target.role not in allowed.get(source.role, set()):
        # Return the generic outward-policy-edge finding.
        return Finding(
            rule_id="ARCH-001", path=source.path, line=line,
            message=f"{source.role} policy imports outward role {target.role}",
            remediation="Reverse the dependency or introduce a port contract toward policy.",
            diagnostic_id="ARCH001_OUTWARD_POLICY_EDGE",
        )
    # The direct edge belongs to the source role's allowed dependency set.
    return None


def _foreign_findings(
    check: DependencyBoundariesCheck,
    source: LocalModule,
    node: ast.Import | ast.ImportFrom,
) -> Iterator[Finding]:
    """Report direct technology imports outside their declared owner.

    @param check checker carrying ownership declarations
    @param source importing local module
    @param node import syntax node
    @return finding elements in imported-root order, one per owner breach
    """
    # Select the bounded repository root required for relative owner identities.
    root = check.declaration.root
    # A legacy declaration without a root cannot authorize foreign-ownership comparison.
    if root is None:
        # Stop iteration without using ambient filesystem ancestry.
        return
    # Resolve the importing module to one repository-relative POSIX identity.
    relative = PurePosixPath(source.path.resolve().relative_to(root.resolve()).as_posix())
    # Inspect each direct foreign-import-root/line pair in authored statement order.
    for import_root, line in _import_root(node):
        # Resolve the optional declared owner boundary for this root package.
        owner = check.declaration.foreign_ownership.get(import_root)
        # Undeclared technology and imports within their exact/descendant owner are allowed here.
        if owner is None or relative == owner or relative.is_relative_to(owner):
            # Advance to the next direct imported root.
            continue
        # Yield the foreign-owner breach at the exact import statement line.
        yield Finding(
            rule_id="ARCH-020", path=source.path, line=line,
            message=(
                f"foreign import {import_root!r} is owned by {owner}, "
                f"not {relative.parent}"
            ),
            remediation=(
                "Import the technology only inside its owning adapter boundary "
                "and reach that adapter through a port or local wiring."
            ),
            diagnostic_id="ARCH020_FOREIGN_OWNER_BREACH",
        )


def _module_findings(
    check: DependencyBoundariesCheck,
    source: LocalModule,
    modules: Mapping[str, LocalModule],
) -> list[Finding]:
    """Inspect all direct imports made by one local module.

    @param check checker carrying the project declaration
    @param source importing local module
    @param modules mapping from each dotted-module key to its local-module value;
        insertion order follows declared roots and sorted files
    @return finding elements in syntax and local-before-foreign order

    @par Effects
    Reads and parses the indexed source module once.
    """
    # Parse one strict UTF-8 source snapshot for direct-import inspection.
    try:
        # Build the syntax tree while retaining the source path in parser diagnostics.
        tree = ast.parse(
            source.path.read_text(encoding="utf-8"), filename=str(source.path),
        )
    # Another check reports invalid syntax; dependency classification yields no false evidence.
    except SyntaxError:
        # Yield no dependency evidence from a module another checker already found unparsable.
        return []
    # Accumulate finding elements in deterministic import and predicate order.
    findings: list[Finding] = []
    # Inspect imports to derive direct dependency edges before applying boundary predicates.
    for node in ast.walk(tree):
        # Only imports establish direct dependency edges.
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            # Skip non-import syntax because it establishes no dependency edge.
            continue
        # Track an unordered set whose each element is a local target path already reported here.
        seen_targets: set[Path] = set()
        # Inspect each candidate absolute import-name element in authored resolution order.
        for imported in _absolute_imports(node, source):
            # Resolve the most specific indexed local target, if any.
            target = _local_target(imported, modules)
            # Foreign candidates and repeated local target paths do not create another local edge.
            if target is None or target.path in seen_targets:
                # Advance to the next candidate import spelling.
                continue
            # Mark the local target consumed for this import statement.
            seen_targets.add(target.path)
            # Classify the edge into its most specific forbidden predicate, if any.
            finding = _edge_finding(source, target, node.lineno)
            # Append only a concrete forbidden-edge finding.
            if finding is not None:
                # Preserve local edge order in the module finding sequence.
                findings.append(finding)
        # Append foreign-ownership findings after local-edge findings for this import.
        findings.extend(_foreign_findings(check, source, node))
    # Return every direct dependency finding in stable syntax order.
    return findings


class DependencyBoundariesCheck(Check):
    """Inspect direct local and registered foreign imports across all source roots."""

    ## Mechanism token shared by the four independently coded predicates.
    name = "dependency_boundaries"
    ## Rule-id elements in deterministic reporting order for direct-import predicates.
    rules = ("ARCH-001", "ARCH-003", "ARCH-019", "ARCH-020")

    def run(self, _paths: Sequence[Path]) -> list[Finding]:
        """Check the complete declared source graph.

        @param _paths path elements in caller order, deliberately ignored for a complete graph
        @return finding elements in sorted source then syntax order
        """
        # Build the complete declaration-bound local module mapping.
        modules = _index(self)
        # Empty or unbounded declarations provide no safe complete dependency view.
        if not modules or self.declaration.root is None:
            # Yield no dependency findings without both bounded modules and a repository root.
            return []
        # Accumulate finding elements in sorted module-path then syntax order.
        findings: list[Finding] = []
        # Inspect each local-module value sorted by platform-neutral source path.
        for source in sorted(modules.values(), key=lambda item: item.path.as_posix()):
            # Extend with this module's local and foreign direct-edge findings.
            findings.extend(_module_findings(self, source, modules))
        # Return the complete deterministic forbidden-edge sequence.
        return findings


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    from . import main

    # Translate the checker result into the process exit status.
    raise SystemExit(main(DependencyBoundariesCheck()))
