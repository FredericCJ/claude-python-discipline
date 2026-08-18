"""Documentation says what an element guarantees, in a form Doxygen can read.

Enforces DOC-004 (docstrings where Python has a slot), DOC-008 (types are not
restated in prose) and DOC-009 (the contract, not the name and not the mechanism).

Deliberately narrow. Whether a sentence is *informative* is a reading judgment no
check can make; what is checkable is the detectable half — documentation that
merely restates the identifier, that duplicates a type the signature already
carries, or that is written in a form the engine will not parse.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

from . import Check, Finding, is_test_path, main

## Words that carry no information when they are all a docstring adds.
FILLER = frozenset({
    "a", "an", "the", "this", "that", "of", "for", "to", "and", "or", "is", "it",
    "helper", "function", "method", "class", "module", "utility", "wrapper",
    "returns", "return", "get", "gets", "set", "sets", "do", "does", "handle",
    "handles", "process", "processes", "simple", "basic", "internal",
})

## A type restated in prose, e.g. "@param count (int) how many".
_TYPE_IN_PROSE = re.compile(
    r"@param\s+\**\w+\s*(?:\(\s*(?:int|str|bool|float|bytes|list|dict|set|tuple|"
    r"Path|Sequence|Mapping|Iterable|Iterator|Optional|Any)\b[^)]*\)|"
    r":\s*(?:int|str|bool|float|bytes|list|dict|set|tuple)\b)",
    re.IGNORECASE,
)

## "@return (bool) ..." or "@return bool: ..." -- the signature already says so.
_TYPE_IN_RETURN = re.compile(
    r"@(?:return|returns)\s*(?:\(\s*(?:int|str|bool|float|bytes|list|dict|set|tuple|"
    r"None)\s*\)|(?:int|str|bool|float|bytes|list|dict|set|tuple|None)\s*:)",
    re.IGNORECASE,
)

## Word tokens, for comparing a summary against an identifier.
_WORD = re.compile(r"[a-z0-9]+")


class DocStyleCheck(Check):
    """Report documentation that is unparseable, redundant or empty of content."""

    ## Invoked as `python -m checks.doc_style`.
    name = "doc_style"
    ## The law/DOC rules this check decides.
    rules = ("DOC-004", "DOC-008", "DOC-009")

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        """Yield findings for every badly formed documentation comment in `tree`.

        @param tree the parsed module
        @param path the file it came from
        @param layer the architectural layer, unused here
        @return findings for documentation that will not carry its contract
        """
        source = path.read_text(encoding="utf-8").splitlines()

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            docstring = ast.get_docstring(node)
            if docstring is None:
                # Absence is DOC-001's business, not this check's.
                yield from self._misplaced_block(node, path, source)
                continue
            yield from self._content(node, docstring, path)

    def _misplaced_block(self, node: ast.AST, path: Path,
                         source: list[str]) -> Iterator[Finding]:
        """Report a `##` block used where a docstring belongs.

        @param node the element
        @param path the file it came from
        @param source the file's lines
        @return one finding when documentation was written in the wrong form
        """
        lineno = getattr(node, "lineno", 1)
        index = lineno - 2
        while index >= 0 and source[index].strip().startswith("#"):
            if source[index].strip().startswith("##"):
                name = getattr(node, "name", "element")
                yield Finding(
                    "DOC-004", path, lineno,
                    f"{name} is documented with a ## block instead of a docstring",
                    "Move it into the docstring; a ## block is invisible to help(), "
                    "to editors and to every other Python tool.",
                )
                return
            index -= 1

    def _content(self, node: ast.AST, docstring: str, path: Path) -> Iterator[Finding]:
        """Report a docstring that restates the name or duplicates a type.

        @param node the documented element
        @param docstring its docstring
        @param path the file it came from
        @return findings for redundant or contentless documentation
        """
        lineno = getattr(node, "lineno", 1)
        name = getattr(node, "name", "")

        for pattern, rule, message in (
            (_TYPE_IN_PROSE, "DOC-008", "a parameter's type is restated in the prose"),
            (_TYPE_IN_RETURN, "DOC-008", "the return type is restated in the prose"),
        ):
            if pattern.search(docstring):
                yield Finding(
                    rule, path, lineno,
                    f"{name}: {message}",
                    "The signature carries the type; the documentation carries the "
                    "meaning. A type written twice diverges once.",
                )

        if _restates_the_name(name, docstring):
            yield Finding(
                "DOC-009", path, lineno,
                f"{name}: the documentation only restates the name",
                "Say what it guarantees -- the result, the invariant, the failure mode. "
                "A comment that repeats the identifier answers nothing.",
            )


def _restates_the_name(name: str, docstring: str) -> bool:
    """Whether a docstring's summary adds nothing beyond the identifier.

    True only when every informative word in the first line already appears in
    the name. Conservative on purpose: a false positive here would push authors
    toward padding, which is the failure this rule exists to avoid.

    @param name the element's identifier
    @param docstring its docstring
    @return True when the summary carries no word the name does not
    """
    summary = docstring.strip().splitlines()[0] if docstring.strip() else ""
    words = {_stem(w) for w in _WORD.findall(summary.lower()) if w not in FILLER}
    if not words or len(words) > 4:
        return False
    split_name = re.sub(r"(?<!^)(?=[A-Z])", " ", name).lower()
    from_name = {_stem(w) for w in _WORD.findall(split_name)}
    return words <= from_name


def _stem(word: str) -> str:
    """A crude root, so `parses`, `parsing` and `parse` compare equal.

    Both sides of the comparison are stemmed the same way, so the stem only has
    to be consistent, not linguistically correct.

    @param word one lowercase word
    @return its root form
    """
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    return word.removesuffix("s").removesuffix("e")


if __name__ == "__main__":
    raise SystemExit(main(DocStyleCheck()))
