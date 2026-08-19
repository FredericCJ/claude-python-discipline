"""Documentation says what an element guarantees, in a form Doxygen can read.

Enforces DOC-004 (docstrings where Python has a slot), DOC-008 (types are not
restated in prose), DOC-009 (the contract, not the name and not the mechanism)
and DOC-010 (no code span that breaks the Doxygen build). DOC-008/009/010 apply
equally to `##` blocks: `doc_coverage` proves one is present; this module reads
what it says.

Deliberately narrow. Whether a sentence is *informative* is a reading judgment no
check can make; what is checkable is the detectable half — documentation that
merely restates the identifier, that duplicates a type the signature already
carries, or that is written in a form the engine will not parse.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, is_test_path, main
from .doc_coverage import EXEMPT_NAMES, _named_assignments

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Words that carry no information when they are all a docstring adds.
FILLER = frozenset({
    "a", "an", "the", "this", "that", "of", "for", "to", "and", "or", "is", "it",
    "helper", "function", "method", "class", "module", "utility", "wrapper",
    "returns", "return", "get", "gets", "set", "sets", "do", "does", "handle",
    "handles", "process", "processes", "simple", "basic", "internal",
})

## A type restated in prose -- naming a parameter's type in parens or after a
## colon following its name, when the signature already carries it. Written
## here without the literal trigger spelled out in full: this block is itself
## read by the check it describes, so an example in the exact shape it hunts
## for would flag its own comment.
_TYPE_IN_PROSE = re.compile(
    r"@param\s+\**\w+\s*(?:\(\s*(?:int|str|bool|float|bytes|list|dict|set|tuple|"
    r"Path|Sequence|Mapping|Iterable|Iterator|Optional|Any)\b[^)]*\)|"
    r":\s*(?:int|str|bool|float|bytes|list|dict|set|tuple)\b)",
    re.IGNORECASE,
)

## The return-value counterpart of the pattern above: a type named in parens or
## after a colon, following @return or @returns -- again the signature's job.
_TYPE_IN_RETURN = re.compile(
    r"@(?:return|returns)\s*(?:\(\s*(?:int|str|bool|float|bytes|list|dict|set|tuple|"
    r"None)\s*\)|(?:int|str|bool|float|bytes|list|dict|set|tuple|None)\s*:)",
    re.IGNORECASE,
)

## Word tokens, for comparing a summary against an identifier.
_WORD = re.compile(r"[a-z0-9]+")

## A code span whose content ends in a single period, which Doxygen cannot parse.
## Established by bisection against doxygen 1.10.0: a span holding foo. or x. or
## a.b. aborts the comment block, while one holding an ellipsis, a leading dot,
## foo.bar or plain foo is read normally -- so the trigger is a final period
## preceded by anything but another period. The examples here are deliberately
## written without code spans around them: an earlier draft of this very comment
## put them in spans and broke the documentation build, which is how the gap
## below was found. Doxygen catches this too, but reports only an unclosed inline
## code tag, naming neither the span nor the remedy.
##
## This check now reads a `##` block like this one as well as a docstring, so
## a span written the broken way here would flag its own comment -- which is
## exactly how the gap this paragraph once described was found and closed.
_TRAILING_DOT_SPAN = re.compile(r"`([^`\n]*[^.`]\.)`")


class DocStyleCheck(ModuleCheck):
    """Report documentation that is unparseable, redundant or empty of content."""

    ## Invoked as `python -m checks.doc_style`.
    name = "doc_style"
    ## The law/DOC rules this check decides.
    rules = ("DOC-004", "DOC-008", "DOC-009", "DOC-010")

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield findings for every badly formed documentation comment in `tree`.

        @param tree the parsed module
        @param path the file it came from
        @param _layer the architectural layer, unused here
        @return findings for documentation that will not carry its contract
        """
        if is_test_path(path):
            # A test may legitimately pin the very shape these rules police;
            # is_test_path's own docstring says exactly that.
            return
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

        yield from self._hash_block_content(tree, path, source)

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

        for span in _TRAILING_DOT_SPAN.findall(docstring):
            yield Finding(
                "DOC-010", path, lineno,
                f"{name}: the code span `{span}` ends in a period, which breaks "
                f"the Doxygen build",
                "Move the period outside the span: write `foo`. rather than "
                '`foo.`. Doxygen reports this only as "end of comment block '
                "while expecting command </tt>\", naming neither the file's real "
                "problem nor the fix.",
            )

        if _restates_the_name(name, docstring):
            yield Finding(
                "DOC-009", path, lineno,
                f"{name}: the documentation only restates the name",
                "Say what it guarantees -- the result, the invariant, the failure mode. "
                "A comment that repeats the identifier answers nothing.",
            )

    def _hash_block_content(self, tree: ast.Module, path: Path,
                            source: list[str]) -> Iterator[Finding]:
        """Report a `##` block that restates a name, a type, or breaks the Doxygen build.

        The same content rules DOC-008/DOC-009/DOC-010 hold docstrings to,
        applied to the `##` blocks documenting module constants, class
        attributes, dataclass fields and enum members -- forms
        `doc_coverage` locates but never reads the text of, since it only
        proves a block is present.

        @param tree the parsed module
        @param path the file it came from
        @param source the file's lines, for reading the block's text
        @return findings for every badly formed `##` block
        """
        for target, lineno in _named_assignments_in(tree.body):
            if target in EXEMPT_NAMES:
                continue
            yield from self._hash_block_at(target, target, lineno, path, source)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for target, lineno in _named_assignments_in(node.body):
                if target in EXEMPT_NAMES:
                    continue
                yield from self._hash_block_at(
                    target, f"{node.name}.{target}", lineno, path, source,
                )

    def _hash_block_at(self, bare_name: str, display_name: str, lineno: int,
                       path: Path, source: list[str]) -> Iterator[Finding]:
        """Report content faults in the `##` block documenting one named value.

        Silent when no block is found: absence is DOC-002's business, not
        this check's.

        @param bare_name the identifier alone, for the restates-the-name test
        @param display_name the identifier as shown in a finding, qualified
            with its class when the value is an attribute
        @param lineno the 1-based line the value is bound on
        @param path the file it came from
        @param source the file's lines
        @return findings for a restated type, a broken code span, or a
            summary that adds nothing beyond the name
        """
        text = _hash_block_text(source, lineno)
        if text is None:
            return

        for pattern, rule, message in (
            (_TYPE_IN_PROSE, "DOC-008", "a parameter's type is restated in the prose"),
            (_TYPE_IN_RETURN, "DOC-008", "the return type is restated in the prose"),
        ):
            if pattern.search(text):
                yield Finding(
                    rule, path, lineno,
                    f"{display_name}: {message}",
                    "The signature carries the type; the documentation carries the "
                    "meaning. A type written twice diverges once.",
                )

        for span in _TRAILING_DOT_SPAN.findall(text):
            yield Finding(
                "DOC-010", path, lineno,
                f"{display_name}: the code span `{span}` ends in a period, which "
                f"breaks the Doxygen build",
                "Move the period outside the span: write `foo`. rather than "
                '`foo.`. Doxygen reports this only as "end of comment block '
                "while expecting command </tt>\", naming neither the file's real "
                "problem nor the fix.",
            )

        if _restates_the_name(bare_name, text):
            yield Finding(
                "DOC-009", path, lineno,
                f"{display_name}: the documentation only restates the name",
                "Say what it guarantees -- the result, the invariant, the failure mode. "
                "A comment that repeats the identifier answers nothing.",
            )


def _named_assignments_in(statements: list[ast.stmt]) -> Iterator[tuple[str, int]]:
    """Every name bound at the top of a module or class body, with its line.

    Thin pass-through over `doc_coverage._named_assignments`, one statement
    at a time, so this module walks a body the same way `doc_coverage` does
    rather than a second, differently-behaved way.

    @param statements a module's or a class's top-level statements
    @return pairs of bound name and the 1-based line it was bound on
    """
    for statement in statements:
        yield from _named_assignments(statement)


def _hash_block_text(source: list[str], lineno: int) -> str | None:
    """The text of the `##` block documenting the value bound at `lineno`.

    Walks upward exactly as `doc_coverage._has_hash_block` does -- through
    contiguous `#`-prefixed lines, stopping at the first that is not one --
    so presence and content agree on what counts as the block. Returns the
    text with each line's leading `#` markers and surrounding space removed
    and joined back into reading order.

    @param source the file's lines
    @param lineno the 1-based line the value is bound on
    @return the block's text, or None when no `##` line precedes it
    """
    collected: list[str] = []
    saw_hash_block = False
    index = lineno - 2
    while index >= 0:
        line = source[index].strip()
        if line.startswith("##"):
            saw_hash_block = True
            collected.append(line[2:].strip())
            index -= 1
            continue
        if line.startswith("#"):
            collected.append(line[1:].strip())
            index -= 1
            continue
        break
    if not saw_hash_block:
        return None
    return "\n".join(reversed(collected))


def _restates_the_name(name: str, docstring: str) -> bool:
    """Whether a docstring's summary adds nothing beyond the identifier.

    True only when every informative word in the first line already appears in
    the name. Conservative on purpose: a false positive here would push authors
    toward padding, which is the failure this rule exists to avoid.

    An all-capitals name is split on its underscores alone. Splitting it before
    each capital instead turns `MAX_RETRIES` into eleven single letters, which
    no summary can be a subset of -- so the rule was silent on exactly the
    elements a `##` block documents, module constants and enum members, where
    upper case is the convention rather than the exception.

    @param name the element's identifier
    @param docstring its docstring
    @return True when the summary carries no word the name does not
    """
    summary = docstring.strip().splitlines()[0] if docstring.strip() else ""
    words = {_stem(w) for w in _WORD.findall(summary.lower()) if w not in FILLER}
    if not words or len(words) > 4:
        return False
    split_name = (name if name.isupper() else re.sub(r"(?<!^)(?=[A-Z])", " ", name)).lower()
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
