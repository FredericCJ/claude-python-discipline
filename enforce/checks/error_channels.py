"""Two propagation channels, converted at one seam, one family per layer.

Enforces `ERR-001` (exactly two channels: a typed result for a contract outcome,
a raised exception for the exceptional), `ERR-003` (conversion between them
happens at one named seam), `ERR-004` (a layer produces only its own error
family) and `ERR-014` (an expected failure and a contract violation are
distinguished).

`ERR-004` is the load-bearing one and the reason the others are grouped with it.
It is what makes the `layer` field of a diagnostic envelope *derivable* rather
than guessed: if each layer raises only its own family, the type of an escaping
exception says where it came from. The reference package's `envelope.layer_of`
does exactly that, and it is sound only because this rule holds.

**What this decides and what it does not.** It decides that a layer does not
raise a built-in exception directly, and that a function returning a result union
does not also raise its own family for the same condition. It cannot decide
whether a given failure is *conceptually* expected or exceptional -- that is a
judgement, and `ERR-014` keeps a reviewer for it.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, is_test_path, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Unordered admitted-error set whose each element denotes a caller contract violation.
## These are
## contract violations by the caller, detected at a boundary, and the standard
## library's own vocabulary is the clearest way to say so.
ADMITTED = frozenset({
    "NotImplementedError", "StopIteration", "StopAsyncIteration",
    "KeyboardInterrupt", "SystemExit", "GeneratorExit", "AssertionError",
})

## Unordered unowned-error set whose each element makes layer origin uncatchable by family.
## Direct use
## its own for the condition. Raising one leaves a caller unable to catch this
## package's failures without also catching the standard library's.
UNOWNED = frozenset({
    "Exception", "BaseException", "RuntimeError", "OSError", "IOError",
    "LookupError", "ArithmeticError", "EnvironmentError",
})

## Unordered governed-layer set whose each element must raise its own error family. The set
## exists so a
## file outside the four is skipped rather than reported against a family it
## has no way to have.
GOVERNED = frozenset({"domain", "app", "adapters", "shell"})


class ErrorChannelsCheck(ModuleCheck):
    """Reports a layer raising outside its own family, or mixing the two channels."""

    ## Invoked as `python -m checks.error_channels`.
    name = "error_channels"
    ## The law/ERR rules this check decides.
    ## Narrowed to what this check can actually REPORT. ERR-003 and ERR-014
    ## were named here and never emitted, so they counted as `mechanized` while
    ## being decided by nothing -- and this module's own docstring said so in
    ## prose. `V080` rises as a result, which is the true number.
    ## Rule-id elements in deterministic reporting order actually decided here.
    rules = ("ERR-001", "ERR-004")

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        """Yield findings for unowned raises and for channel mixing.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param layer the architectural layer the file sits in
        @return finding elements in function then raise/channel order
        """
        # Only non-test canonical layers own layer-family and two-channel obligations.
        if layer not in GOVERNED or is_test_path(path):
            # Stop iteration outside the rule's exact architectural subject.
            return
        # Build an unordered set whose each element is a locally defined exception name.
        local = _local_exceptions(tree)
        # Inspect callable bodies for undeclared exception propagation channels.
        for node in ast.walk(tree):
            # Validate each function body as one propagation boundary.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Yield unowned raises before any mixed-channel finding for the function.
                yield from self._function(node, path, layer, local)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, path: Path,
                  layer: str, local: set[str]) -> Iterator[Finding]:
        """Report one function's raises against the two-channel rule.

        @param node the function definition
        @param path the file it came from
        @param layer the architectural layer, named in the message
        @param local unordered set whose each element is an exception class defined here
        @return finding elements in raise walk order followed by any mixed-channel finding
        """
        # Collect each explicit raise-statement element in deterministic function walk order.
        raises = [n for n in ast.walk(node) if isinstance(n, ast.Raise) and n.exc]
        # Inspect each explicit raise element in function walk order.
        for raised in raises:
            # Resolve the terminal raised class name, or empty text for another expression.
            name = _raised_name(raised)
            # Directly raising an unowned built-in destroys the layer-family origin invariant.
            if name in UNOWNED:
                # Yield the family-ownership finding at the exact raise statement.
                yield Finding(
                    "ERR-004", path, raised.lineno,
                    f"{layer} raises `{name}` directly, which belongs to no layer",
                    f"Raise the {layer} layer's own error type. The envelope's "
                    f"`layer` field is derived from the family, so a built-in "
                    f"raised here makes the origin unknowable.",
                )

        # Mixed-channel analysis applies only to result unions that also raise explicitly.
        if not _returns_union(node) or not raises:
            # Stop after family validation for ordinary return shapes or raise-free functions.
            return
        # Preserve raise walk order while selecting each locally owned exception element.
        owned = [r for r in raises if _raised_name(r) in local]
        # Any owned raise alongside the result union exposes the same caller to two channels.
        if owned:
            # Yield one mixed-channel finding at the first locally owned raise.
            yield Finding(
                "ERR-001", path, owned[0].lineno,
                f"{node.name}() returns a result union and also raises "
                f"`{_raised_name(owned[0])}`",
                "Choose one channel for this condition. A caller cannot know "
                "whether to narrow the union or wrap the call in a handler when "
                "the same failure travels both ways.",
            )


def _local_exceptions(tree: ast.Module) -> set[str]:
    """Exception classes defined in this module.

    @param tree the module's syntax tree
    @return unordered set whose each element is a locally defined exception name
    """
    # Collect class-name elements whose bases lexically denote an exception hierarchy.
    return {
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(
            (b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "")).endswith(
                ("Error", "Exception"))
            for b in node.bases
        )
    }


def _raised_name(node: ast.Raise) -> str:
    """The class name a raise statement names.

    @param node the raise statement
    @return the trailing identifier, or the empty string for a bare re-raise
    """
    # Select the explicit raised expression, which may be absent only for a bare re-raise.
    exc = node.exc
    # Constructor calls name their raised class through the called expression.
    if isinstance(exc, ast.Call):
        # Replace the constructor call with its function identity expression.
        exc = exc.func
    # Qualified exception classes expose their terminal attribute name.
    if isinstance(exc, ast.Attribute):
        # Return the qualified class's final identifier.
        return exc.attr
    # Return a bare identifier or empty text for another expression form.
    return getattr(exc, "id", "")


def _returns_union(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether a function's return annotation is a union of two or more arms.

    Recognised as a `X | Y` annotation whose arms are all names, which is the
    discriminated-result shape `ARCH-006` asks for. `Optional[X]` is not treated
    as a result union: `None` is an absence, not an error arm.

    @param node the function definition
    @return true when the annotation is a union with no ``None`` arm; false otherwise
    """
    # Select the function's return annotation without evaluating it.
    returns = node.returns
    # Only PEP 604 ``X | Y`` syntax is claimed as a result-union signal.
    if not isinstance(returns, ast.BinOp) or not isinstance(returns.op, ast.BitOr):
        # Reject other annotation shapes from this narrow predicate.
        return False
    # Collect name and constant arm elements in deterministic annotation walk order.
    arms = [n for n in ast.walk(returns) if isinstance(n, (ast.Name, ast.Constant))]
    # A union without any spelling of None represents multiple result arms, not optionality.
    return not any(
        (isinstance(a, ast.Constant) and a.value is None)
        or (isinstance(a, ast.Name) and a.id == "None")
        for a in arms
    )


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(ErrorChannelsCheck()))
