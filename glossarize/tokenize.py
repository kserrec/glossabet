"""Identifier and document tokenization.

Normalizes PaymentService / payment_service / payment-service / paymentService
to the shared tokens ["payment", "service"]. Lexer-level only — no parsing.
"""

from __future__ import annotations

import re

IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
DOC_WORD_RE = re.compile(r"[A-Za-z][A-Za-z']+")

# Splits a hunk into words: acronym runs (HTTPServer -> HTTP, Server),
# capitalized words, lowercase runs, digit runs.
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")

# Cross-language keywords and near-universal syntax words, filtered from the
# vocabulary because they describe the language, not the domain. Deliberately
# moderate: overlaps with domain words (match, type, open) are accepted noise
# reduction — Phase 4's analysis works on what remains.
KEYWORD_TOKENS = frozenset("""
    if else elif for while return def class import from self this var let
    const function func fn true false none null nil void int str string bool
    float double char pub mod use match type struct enum impl trait end do
    then begin and or not in is as with try except catch finally raise throw
    new static public private protected final print println module open val
    mutable rec let when case switch break continue default goto extern
    sizeof typedef union unsigned signed long short auto register volatile
    assert lambda yield async await global nonlocal del pass exec require
    package interface extends implements super instanceof typeof delete
    fun some ref begin object inherit method virtual constraint functor
""".split())

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


def tokenize_identifier(name: str) -> list[str]:
    """Split an identifier into normalized lowercase tokens.

    Digit runs and keyword/short tokens are dropped.
    """
    tokens: list[str] = []
    for hunk in name.split("_"):
        for word in _CAMEL_RE.findall(hunk):
            if word.isdigit():
                continue
            token = word.lower()
            # DOC_STOPWORDS filtered here too: a lexer-level scan reads
            # comments and string literals, so prose glue leaks into
            # identifiers' vocabulary without this.
            if (
                len(token) < MIN_TOKEN_LEN
                or token in KEYWORD_TOKENS
                or token in DOC_STOPWORDS
            ):
                continue
            tokens.append(token)
    return tokens


def tokenize_term(term: str) -> list[str]:
    """Tokens of a human-written glossary term, where spaces and hyphens
    separate words the way underscores do in identifiers."""
    return tokenize_identifier(term.replace(" ", "_").replace("-", "_"))


def iter_identifiers(text: str):
    """Yield identifier spellings worth counting from source text."""
    for match in IDENTIFIER_RE.finditer(text):
        name = match.group()
        if len(name) < MIN_TOKEN_LEN or name.lower() in KEYWORD_TOKENS:
            continue
        yield name


def doc_words(text: str) -> list[str]:
    """Prose words from a documentation file, lowercased, stopwords removed."""
    words = []
    for word in DOC_WORD_RE.findall(text.lower()):
        word = word.rstrip("'")  # users' and users are one term
        if len(word) >= MIN_DOC_WORD_LEN and word not in DOC_STOPWORDS:
            words.append(word)
    return words
