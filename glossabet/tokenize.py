"""Unicode-aware identifier and document tokenization.

Normalizes camelCase, PascalCase, snake_case, and supported kebab-case names
to shared case-folded tokens. This is deliberately a lexical approximation,
not a parser: language syntax determines which matches are real identifiers.
"""

from __future__ import annotations

import re
import unicodedata

# Clojure's ordinary word-like identifiers use hyphens. Other supported
# languages treat ``a-b`` as subtraction or two tokens, so the source iterator
# joins hyphenated spans only where the language contract makes that useful.
_KEBAB_IDENTIFIER_LANGUAGES = frozenset({"clojure"})
_IDENTIFIER_BASE = r"(?:[^\W\d]|_)\w*"
_IDENTIFIER_RE = re.compile(_IDENTIFIER_BASE)
_KEBAB_IDENTIFIER_RE = re.compile(
    rf"{_IDENTIFIER_BASE}(?:-{_IDENTIFIER_BASE})*"
)
_WORD_HUNK_RE = re.compile(r"\w+")
_DOC_WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
_ASCII_WORD_RE = re.compile(
    r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+\d*|[A-Z]+\d*|\d+"
)

# Cross-language keywords and near-universal syntax words, filtered from the
# vocabulary because they describe syntax rather than either the language or
# project domain vocabulary. Deliberately ambiguous words such as ``match``,
# ``open``, ``register``, and ``type`` remain available as domain evidence.
KEYWORD_TOKENS = frozenset("""
    if else elif for while return def class import from self this var let
    const function func fn true false none null nil void int str string bool
    float double char pub mod use struct enum impl trait end do
    then begin and or not in is as with try except catch finally raise throw
    new static public private protected final print println module val
    mutable rec let when case switch break continue default goto extern
    sizeof typedef union unsigned signed long short auto volatile
    assert lambda yield async await global nonlocal del pass exec require
    package interface extends implements super instanceof typeof delete
    fun some ref begin object inherit method virtual constraint functor
""".split())

# Source-language vocabulary is retained in evidence but does not compete with
# project vocabulary for terminology/naming budgets. These sets are
# intentionally conservative: an unlisted token remains domain vocabulary.
# The Python set starts with unambiguous builtins and ubiquitous operations
# observed in the repository and evaluation corpus; plausible domain words
# such as ``open``, ``type``, ``run``, and ``match`` stay out.
LANGUAGE_BUILTIN_TOKENS: dict[str, frozenset[str]] = {
    "python": frozenset(
        """
        append bytearray callable classmethod delattr dict divmod enumerate
        frozenset getattr hasattr isinstance issubclass len memoryview repr
        reversed setattr sorted staticmethod tuple
        """.split()
    ),
}

TOKEN_ORIGIN_LANGUAGE = "language"
TOKEN_ORIGIN_DOMAIN = "domain"

# Words too common in prose to carry naming signal.
DOC_STOPWORDS = frozenset("""
    the a an and or of to in is it for on with as by at be this that are was
    were from not no yes but if then than so such can could should would will
    may might must have has had do does did done into over under between all
    any each which what when where who whom whose why how there here they them
    their its our your his her she he we you i one two also more most some only
    other same own just about after before during without within these those
    been being through per via use used using new
""".split())

MIN_TOKEN_LEN = 2
MIN_DOC_WORD_LEN = 3


def tokenization_contract() -> dict:
    """Machine-readable summary of the lexical normalization semantics."""
    return {
        "unicode_normalization": "NFKC+casefold",
        "identifier_characters": "Unicode-word; nonnumeric-start",
        "acronyms": "preserved-run",
        "digits": "suffix-to-preceding-word; standalone-dropped",
        "forms": ["camelCase", "PascalCase", "snake_case", "clojure-kebab-case"],
        "parser_backed": False,
    }


def token_origin(token: str, language: str | None) -> str:
    """Classify one normalized token at one source-language occurrence.

    Languages without a curated set, and tokens deliberately omitted from a
    set, remain domain evidence. Aggregation promotes a token to ``domain`` if
    any occurrence is domain-origin, so one language's builtin cannot erase a
    same-spelled project concept used in another language.
    """
    language_tokens = LANGUAGE_BUILTIN_TOKENS.get(language or "", ())
    if token in language_tokens:
        return TOKEN_ORIGIN_LANGUAGE
    return TOKEN_ORIGIN_DOMAIN


def tokenize_identifier(name: str) -> list[str]:
    """Split an identifier into normalized lowercase tokens.

    Acronym runs stay intact (``HTTPServer`` -> ``http``, ``server``). A digit
    run is retained as a suffix of the preceding word (``HTTP2Server`` ->
    ``http2``, ``server``); standalone numeric hunks are dropped. Unicode is
    normalized with NFKC and case-folded. Keyword and short tokens are dropped.
    """
    normalized = (
        name if name.isascii() else unicodedata.normalize("NFKC", name)
    )
    tokens: list[str] = []
    for hunk in _identifier_hunks(normalized):
        for word in _split_case_and_digits(hunk):
            token = (
                word.lower() if word.isascii()
                else unicodedata.normalize("NFKC", word).casefold()
            )
            if token.isdigit():
                continue
            # DOC_STOPWORDS are filtered here too: a lexer-level scan reads
            # comments and string literals, so prose glue otherwise leaks into
            # identifiers' vocabulary.
            if len(token) < MIN_TOKEN_LEN:
                continue
            if token in KEYWORD_TOKENS or token in DOC_STOPWORDS:
                continue
            tokens.append(token)
    return tokens


def tokenize_term(term: str) -> list[str]:
    """Tokens of a human-written glossary term, where spaces and hyphens
    separate words the way underscores do in identifiers."""
    return tokenize_identifier(term)


def _identifier_hunks(name: str) -> list[str]:
    return _WORD_HUNK_RE.findall(name.replace("_", " "))


def _kind(char: str) -> str:
    if char.isascii():
        if "0" <= char <= "9":
            return "digit"
        if "A" <= char <= "Z":
            return "upper"
        if "a" <= char <= "z":
            return "lower"
        return "letter"
    if char.isdigit():
        return "digit"
    if unicodedata.category(char).startswith("M"):
        return "mark"
    if char.isupper():
        return "upper"
    if char.islower():
        return "lower"
    return "letter"


def _split_case_and_digits(hunk: str) -> list[str]:
    if not hunk:
        return []
    if hunk.isascii():
        return _ASCII_WORD_RE.findall(hunk)
    kinds = [_kind(char) for char in hunk]
    words: list[str] = []
    current = [hunk[0]]
    for index in range(1, len(hunk)):
        char = hunk[index]
        current_kind = kinds[index]
        previous_kind = kinds[index - 1]
        next_kind = kinds[index + 1] if index + 1 < len(hunk) else None
        boundary = (
            (
                current_kind == "upper"
                and previous_kind in {"lower", "digit", "letter"}
            )
            or (
                current_kind == "upper"
                and previous_kind == "upper"
                and next_kind == "lower"
            )
            or (
                current_kind in {"upper", "lower", "letter"}
                and previous_kind == "digit"
            )
            or (
                current_kind == "letter"
                and previous_kind in {"upper", "lower"}
            )
            or (
                current_kind in {"upper", "lower"}
                and previous_kind == "letter"
            )
        )
        if boundary:
            words.append("".join(current))
            current = [char]
        else:
            current.append(char)
    words.append("".join(current))
    return words


def iter_identifiers(text: str, language: str | None = None):
    """Yield conservative Unicode identifier spellings from source text.

    Unicode word characters with a nonnumeric start supply the lexical rule.
    Source sigils, Rust/OCaml apostrophes, and Ruby/Elixir ``?``/``!`` suffixes
    act as boundaries while the underlying word is retained. Clojure alone
    joins internal hyphens into one spelling; all other forms split there.
    """
    normalized_text = (
        text if text.isascii() else unicodedata.normalize("NFKC", text)
    )
    pattern = (
        _KEBAB_IDENTIFIER_RE
        if language in _KEBAB_IDENTIFIER_LANGUAGES
        else _IDENTIFIER_RE
    )
    for match in pattern.finditer(normalized_text):
        name = match.group()
        if len(name) < MIN_TOKEN_LEN or name.casefold() in KEYWORD_TOKENS:
            continue
        yield name


def doc_words(text: str) -> list[str]:
    """Prose words from a documentation file, lowercased, stopwords removed."""
    words = []
    normalized_text = (
        text if text.isascii() else unicodedata.normalize("NFKC", text)
    )
    for match in _DOC_WORD_RE.finditer(normalized_text):
        raw = match.group()
        word = raw.lower() if raw.isascii() else raw.casefold()
        word = word.rstrip("'’")  # users' and users are one term
        if len(word) >= MIN_DOC_WORD_LEN and word not in DOC_STOPWORDS:
            words.append(word)
    return words


STRUCTURED_IDENTIFIER_STYLES = frozenset({
    "snake_case",
    "camelCase",
    "PascalCase",
    "UPPER_SNAKE",
})


def identifier_style(name: str) -> str:
    """Classify one identifier spelling's casing convention.

    Returns a style from ``STRUCTURED_IDENTIFIER_STYLES`` when the spelling
    carries internal word structure, otherwise ``upper`` or ``flat``.
    """
    core = name.strip("_")
    if "_" in core:
        return "UPPER_SNAKE" if core.isupper() else "snake_case"
    if core.isupper():
        return "upper"
    if core[:1].isupper():
        return "PascalCase" if any(c.islower() for c in core) else "upper"
    if any(c.isupper() for c in core):
        return "camelCase"
    return "flat"
