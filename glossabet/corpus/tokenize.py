"""Unicode-aware identifier and document tokenization.

Normalizes camelCase, PascalCase, snake_case, and supported kebab-case names
to shared case-folded tokens. This is deliberately a lexical approximation,
not a parser: language syntax determines which matches are real identifiers.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from typing import TypedDict

from glossabet.corpus.unicode_marks import mark_class_body

# Clojure's ordinary word-like identifiers use hyphens. Other supported
# languages treat ``a-b`` as subtraction or two tokens, so the source iterator
# joins hyphenated spans only where the language contract makes that useful.
_KEBAB_IDENTIFIER_LANGUAGES = frozenset({"clojure"})
# ``\w`` misses combining marks (Devanagari vowel signs, Thai tone marks,
# niqqud, harakat), which are legal identifier-continue characters and part
# of the word; every word class below admits them after a first letter.
# ZWNJ/ZWJ (category Cf) are legal identifier characters that join or
# separate glyphs inside one Persian/Indic word; they continue a word too.
_MARK = f"[{mark_class_body()}\u200c\u200d]"
_WORD_CHAR = rf"(?:\w|{_MARK})"
_LETTER = r"[^\W\d_]"
_LETTER_RUN = rf"{_LETTER}(?:{_LETTER}|{_MARK})*"
_IDENTIFIER_BASE = rf"(?:[^\W\d]|_){_WORD_CHAR}*"
_IDENTIFIER_RE = re.compile(_IDENTIFIER_BASE)
_KEBAB_IDENTIFIER_RE = re.compile(
    rf"{_IDENTIFIER_BASE}(?:-{_IDENTIFIER_BASE})*"
)
_WORD_HUNK_RE = re.compile(rf"{_WORD_CHAR}+")
_DOC_WORD_RE = re.compile(rf"{_LETTER_RUN}(?:['’]{_LETTER_RUN})*")
# Order matters. An acronym run followed by a lone lowercase ``s`` is a plural
# (``IDs`` -> ``ids``, ``URLs`` -> ``urls``): the ``s`` stays with the run, the
# same way ordinary plurals keep their ``s``. This alternative must come before
# the acronym-boundary rule below, which would otherwise orphan the run's last
# capital (``IDs`` -> ``I`` + ``Ds`` -> the ``I`` is dropped as too short and
# ``ds`` is a phantom token). It is deliberately ``s``-specific, not "any single
# lowercase", so acronym-then-CamelWord names like ``XMLId`` still split into
# ``xml`` + ``id`` rather than merging to ``xmlid``.
_ASCII_WORD_RE = re.compile(
    r"[A-Z]{2,}s(?![a-z])"
    r"|[A-Z]+(?=[A-Z][a-z])"
    r"|[A-Z]?[a-z]+\d*"
    r"|[A-Z]+\d*"
    r"|\d+"
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
# Derived token work for one source identifier. The bounded tokenizer stops
# after one extra accepted token, so this is a work/memory boundary rather
# than a slice applied after an arbitrarily large list has been built.
MAX_IDENTIFIER_TOKENS = 64

STRUCTURED_IDENTIFIER_STYLES = frozenset({
    "snake_case",
    "camelCase",
    "PascalCase",
    "UPPER_SNAKE",
    "kebab-case",  # Clojure's ordinary multi-word form (see iter_identifiers)
})


class TokenizationContract(TypedDict):
    """The persisted ``vocabulary.normalization`` record."""

    unicode_normalization: str
    identifier_characters: str
    acronyms: str
    digits: str
    forms: list[str]
    parser_backed: bool


def tokenization_contract() -> TokenizationContract:
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


def term_words(term: str) -> list[str]:
    """Every normalized word of a term, in order, *before* the keyword,
    stopword, and length filters ``tokenize_identifier`` applies. This is the
    identity a human means by a term: ``Limit Function`` and ``Limit`` are
    different terms even though the lexical matcher drops ``function`` as a
    keyword; ``AlphaBeta``, ``Alpha Beta``, and ``alpha_beta`` are the same."""
    normalized = (
        term if term.isascii() else unicodedata.normalize("NFKC", term)
    )
    return [
        word.lower() if word.isascii()
        else unicodedata.normalize("NFKC", word).casefold()
        for hunk in _identifier_hunks(normalized)
        for word in _split_case_and_digits(hunk)
    ]


def tokenize_identifier(name: str) -> list[str]:
    """Split an identifier into normalized lowercase tokens.

    Acronym runs stay intact (``HTTPServer`` -> ``http``, ``server``). A plural
    acronym keeps its trailing ``s`` (``IDs`` -> ``ids``, ``URLs`` -> ``urls``)
    rather than orphaning the run's last capital. A digit run is retained as a
    suffix of the preceding word (``HTTP2Server`` -> ``http2``, ``server``);
    standalone numeric hunks are dropped. Unicode is normalized with NFKC and
    case-folded. Keyword and short tokens are dropped.
    """
    return list(_iter_identifier_tokens(name))


def tokenize_identifier_bounded(
    name: str, limit: int = MAX_IDENTIFIER_TOKENS
) -> tuple[list[str], bool]:
    """Return at most ``limit`` tokens and whether another token exists.

    After whole-string Unicode normalization, token production is lazy: once
    the first omitted accepted token proves truncation, no further tokens are
    materialized or folded into downstream views. The returned list is the
    exact retained prefix and ``truncated`` is honest without constructing an
    omitted-token list.
    """
    if limit < 0:
        raise ValueError("identifier token limit must be non-negative")
    tokens: list[str] = []
    for token in _iter_identifier_tokens(name):
        if len(tokens) == limit:
            return tokens, True
        tokens.append(token)
    return tokens, False


def _iter_identifier_tokens(name: str) -> Iterator[str]:
    normalized = name if name.isascii() else unicodedata.normalize("NFKC", name)
    for hunk in _iter_identifier_hunks(normalized):
        for word in _iter_split_case_and_digits(hunk):
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
            yield token


def tokenize_term(term: str) -> list[str]:
    """Tokens of a human-written glossary term, where spaces and hyphens
    separate words the way underscores do in identifiers."""
    return tokenize_identifier(term)


def tokenize_bounded_term(term: str, *, truncated: bool) -> list[str]:
    """Tokenize a retained term prefix without trusting a clipped word.

    When a character cap cut the input, the final word hunk may only be a
    prefix of the real word (``payment`` from ``paymentgateway``). Complete
    earlier hunks remain sound positive evidence. A trailing separator proves
    the preceding hunk complete, so nothing is discarded in that case.
    """
    normalized = (
        term if term.isascii() else unicodedata.normalize("NFKC", term)
    )
    if truncated:
        searchable = normalized.replace("_", " ")
        final_hunk = None
        for match in _WORD_HUNK_RE.finditer(searchable):
            final_hunk = match
        if final_hunk is not None and final_hunk.end() == len(searchable):
            normalized = normalized[:final_hunk.start()]
    return tokenize_identifier(normalized)


def _iter_identifier_hunks(name: str) -> Iterator[str]:
    for match in _WORD_HUNK_RE.finditer(name.replace("_", " ")):
        yield match.group()


def _identifier_hunks(name: str) -> list[str]:
    return list(_iter_identifier_hunks(name))


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


def _iter_split_case_and_digits(hunk: str) -> Iterator[str]:
    if not hunk:
        return
    if hunk.isascii():
        for match in _ASCII_WORD_RE.finditer(hunk):
            yield match.group()
        return

    def kinded_characters() -> Iterator[tuple[str, str]]:
        previous_kind = "letter"
        for index, char in enumerate(hunk):
            kind = _kind(char)
            # A combining mark continues the character it attaches to, so
            # for boundary purposes it takes that character's kind (a
            # leading mark is a plain letter).
            if kind == "mark":
                kind = previous_kind if index else "letter"
            yield char, kind
            previous_kind = kind

    characters = iter(kinded_characters())
    previous = next(characters, None)
    if previous is None:
        return
    current = next(characters, None)
    following = next(characters, None)
    after_following = next(characters, None)
    word = [previous[0]]
    while current is not None:
        char, current_kind = current
        previous_kind = previous[1]
        next_kind = following[1] if following is not None else None
        next_next_kind = after_following[1] if after_following is not None else None
        boundary = (
            (
                current_kind == "upper"
                and previous_kind in {"lower", "digit", "letter"}
            )
            or (
                # Acronym run ending before a CamelWord (``ΑΒΓδεζ`` -> ``αβ`` +
                # ``γδεζ``): split before the run's last capital. But require
                # the following lowercase run to be *two or more* letters, so a
                # lone trailing lowercase — an inflectional/plural suffix like
                # ``ΑΒΓς`` — stays with the run instead of orphaning its last
                # capital. Mirrors the ``s``-plural rule in the ASCII path.
                current_kind == "upper"
                and previous_kind == "upper"
                and next_kind == "lower"
                and next_next_kind == "lower"
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
            yield "".join(word)
            word = [char]
        else:
            word.append(char)
        previous = current
        current = following
        following = after_following
        after_following = next(characters, None)
    yield "".join(word)


def _split_case_and_digits(hunk: str) -> list[str]:
    return list(_iter_split_case_and_digits(hunk))


def iter_identifiers(text: str, language: str | None = None) -> Iterator[str]:
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
        if word.endswith(("'s", "’s")):  # tenant's and tenant are one term
            word = word[:-2]
        if len(word) >= MIN_DOC_WORD_LEN and word not in DOC_STOPWORDS:
            words.append(word)
    return words



def identifier_style(name: str) -> str:
    """Classify one identifier spelling's casing convention.

    Returns a style from ``STRUCTURED_IDENTIFIER_STYLES`` when the spelling
    carries internal word structure, otherwise ``upper`` or ``flat``.
    """
    core = name.strip("_")
    if "-" in core.strip("-"):
        # Only the Clojure iterator joins hyphenated spans into one spelling,
        # so an internal hyphen is that language's word structure.
        return "kebab-case"
    if "_" in core:
        return "UPPER_SNAKE" if core.isupper() else "snake_case"
    if core.isupper():
        return "upper"
    if core[:1].isupper():
        return "PascalCase" if any(c.islower() for c in core) else "upper"
    if any(c.isupper() for c in core):
        return "camelCase"
    return "flat"
