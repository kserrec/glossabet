"""Tokenizer: naming forms and Unicode normalize to one lexical contract."""

import pytest

from glossabet.tokenize import (
    doc_words,
    iter_identifiers,
    tokenization_contract,
    tokenize_identifier,
)


@pytest.mark.parametrize(
    "identifier, expected",
    [
        ("PaymentService", ["payment", "service"]),
        ("payment_service", ["payment", "service"]),
        ("paymentService", ["payment", "service"]),
        ("HTTPServer", ["http", "server"]),
        ("parseJSON2XML", ["parse", "json2", "xml"]),
        ("getUserByID", ["get", "user", "id"]),  # "by" is prose glue
        ("return_value", ["value"]),  # keywords dropped
        ("utf8", ["utf8"]),
        ("ÜberHTTP2Server", ["über", "http2", "server"]),
        ("ΔοκιμήClient", ["δοκιμή", "client"]),
        ("支付Service", ["支付", "service"]),
        ("Cafe\u0301Service", ["café", "service"]),
        ("version_2_value", ["version", "value"]),
        ("_private_thing", ["thing"]),  # "private" is a keyword token
        ("x", []),  # too short
    ],
)
def test_tokenize_identifier(identifier, expected):
    assert tokenize_identifier(identifier) == expected


def test_doc_words_filters_stopwords_and_short_words():
    words = doc_words("The Payment gateway is a boundary, and it is ours.")
    assert "payment" in words and "gateway" in words and "boundary" in words
    assert "the" not in words and "is" not in words and "it" not in words


def test_doc_words_strip_possessive_apostrophes():
    assert doc_words("the users' guide to the system") == [
        "users", "guide", "system",
    ]
    assert doc_words("don't panic") == ["don't", "panic"]


def test_iter_identifiers_uses_unicode_identifier_rules_and_source_sigils():
    assert list(iter_identifiers("$résumé_session = @HTTP2Client.ready?")) == [
        "résumé_session",
        "HTTP2Client",
        "ready",
    ]


def test_clojure_kebab_case_is_one_lexical_unit_only_for_clojure():
    assert list(iter_identifiers("pending-work", "clojure")) == ["pending-work"]
    assert list(iter_identifiers("pending-work", "python")) == ["pending", "work"]
    assert tokenize_identifier("pending-work") == ["pending", "work"]


def test_unicode_document_words_are_normalized_and_casefolded():
    assert doc_words("Über CAFÉ and данные") == ["über", "café", "данные"]


def test_tokenization_contract_is_explicitly_lexical():
    contract = tokenization_contract()
    assert contract["unicode_normalization"] == "NFKC+casefold"
    assert contract["digits"] == "suffix-to-preceding-word; standalone-dropped"
    assert contract["parser_backed"] is False
