"""Tokenizer: the four naming conventions must normalize to shared tokens."""

import pytest

from glossarize.tokenize import doc_words, tokenize_identifier


@pytest.mark.parametrize(
    "identifier, expected",
    [
        ("PaymentService", ["payment", "service"]),
        ("payment_service", ["payment", "service"]),
        ("paymentService", ["payment", "service"]),
        ("HTTPServer", ["http", "server"]),
        ("parseJSON2XML", ["parse", "json", "xml"]),  # digit runs dropped
        ("getUserByID", ["get", "user", "id"]),  # "by" is prose glue
        ("return_value", ["value"]),  # keywords dropped
        ("utf8", ["utf"]),
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
