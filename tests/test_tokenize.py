"""Tokenizer: naming forms and Unicode normalize to one lexical contract."""

import pytest

from glossabet.corpus.tokenize import (
    LANGUAGE_BUILTIN_TOKENS,
    MAX_IDENTIFIER_TOKENS,
    STRUCTURED_IDENTIFIER_STYLES,
    TOKEN_ORIGIN_DOMAIN,
    TOKEN_ORIGIN_LANGUAGE,
    doc_words,
    iter_identifiers,
    token_origin,
    tokenization_contract,
    tokenize_bounded_term,
    tokenize_identifier,
    tokenize_identifier_bounded,
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
        # Plural acronyms keep their trailing "s" instead of losing the
        # acronym to a phantom token (was: IDs -> ["ds"], APIs -> ["ap"]).
        ("IDs", ["ids"]),
        ("URLs", ["urls"]),
        ("APIs", ["apis"]),
        ("userIDs", ["user", "ids"]),
        ("numCPUs", ["num", "cpus"]),
        # ...but an acronym immediately followed by a Capitalized word must
        # still split, not merge — the plural rule is "s"-specific for exactly
        # this reason.
        ("XMLId", ["xml", "id"]),
        ("parseHTMLElement", ["parse", "html", "element"]),
        # Non-Latin sibling of the same fix: a lone trailing lowercase (a
        # plural/inflection) stays with the acronym run rather than orphaning
        # its last capital.
        ("ΑΒΓς", ["αβγσ"]),
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


def test_bounded_identifier_tokenization_returns_only_the_proven_prefix():
    name = "_".join(f"part{i}" for i in range(50_000))

    tokens, truncated = tokenize_identifier_bounded(name, MAX_IDENTIFIER_TOKENS)

    assert len(tokens) == MAX_IDENTIFIER_TOKENS
    assert tokens == [f"part{i}" for i in range(MAX_IDENTIFIER_TOKENS)]
    assert truncated is True


def test_truncated_term_does_not_promote_its_final_fragment_to_a_token():
    synthetic_prefix = "x" * 504 + " payment"

    assert tokenize_bounded_term("alpha payment", truncated=False) == [
        "alpha", "payment",
    ]
    assert tokenize_bounded_term("alpha payment", truncated=True) == ["alpha"]
    assert tokenize_bounded_term("alpha payment ", truncated=True) == [
        "alpha", "payment",
    ]
    assert "payment" not in tokenize_bounded_term(
        synthetic_prefix, truncated=True
    )


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


def test_python_builtin_partition_is_conservative_and_language_specific():
    python_builtins = LANGUAGE_BUILTIN_TOKENS["python"]
    assert {"dict", "len", "append", "isinstance", "sorted"} <= python_builtins
    assert not {"open", "type", "run", "match"} & python_builtins
    assert token_origin("dict", "python") == TOKEN_ORIGIN_LANGUAGE
    assert token_origin("dict", "javascript") == TOKEN_ORIGIN_DOMAIN
    assert token_origin("project", "python") == TOKEN_ORIGIN_DOMAIN


def test_plausible_domain_words_survive_cross_language_keyword_filtering():
    assert tokenize_identifier("open_type_run_match_register") == [
        "open", "type", "run", "match", "register",
    ]


def test_combining_marks_stay_inside_identifiers_and_doc_words():
    """Devanagari vowel signs and Thai tone marks are Unicode category M —
    outside ``\\w`` — yet legal identifier characters and part of the word.
    They must not shred `डेटा_सेवा` into junk or drop Hindi doc words."""
    from glossabet.corpus.tokenize import doc_words, iter_identifiers

    assert list(iter_identifiers(
        "डेटा_सेवा = 1\nडेटाService = 2\nข้อมูลService = 3\n", "python"
    )) == ["डेटा_सेवा", "डेटाService", "ข้อมูลService"]
    assert tokenize_identifier("डेटा_सेवा") == ["डेटा", "सेवा"]
    assert tokenize_identifier("डेटाService") == ["डेटा", "service"]
    assert doc_words("यह डेटा सेवा है और ข้อมูล ระบบ") == [
        "डेटा", "सेवा", "ข้อมูล", "ระบบ"
    ]
    # Hebrew with niqqud: the points stay with their letters.
    assert tokenize_identifier("שָׁלוֹם_world") == ["שָׁלוֹם", "world"]
    # In a *cased* script a combining mark takes its base letter's case for
    # boundary purposes: a Cyrillic stress mark inside a lowercase run is
    # not a case boundary (or `ударе́ниеService` shreds at the accent), and
    # the same word without the mark splits identically.
    assert tokenize_identifier("ударе\u0301ниеService") == ["ударе\u0301ние", "service"]
    assert tokenize_identifier("Ударе\u0301ниеSlužba") == ["ударе\u0301ние", "služba"]
    assert tokenize_identifier("УдарениеSlužba") == ["ударение", "služba"]


def test_doc_words_apply_the_same_unicode_contract_as_identifiers():
    """Documentation words fold exactly like identifier tokens (NFKC, then
    casefold): a compatibility ligature, a full-width spelling, and the
    German sharp s all land on the token an identifier would produce, so a
    term seen in code and in docs is one term, not two."""
    from glossabet.corpus.tokenize import doc_words

    assert doc_words("Straße STRASSE ﬁle Ｆｕｌｌｗｉｄｔｈ Café CAFÉ") == [
        "strasse", "strasse", "file", "fullwidth", "café", "café",
    ]
    assert tokenize_identifier("Straße_ﬁle_Ｆｕｌｌｗｉｄｔｈ") == [
        "strasse", "file", "fullwidth",
    ]


def test_static_mark_table_matches_the_interpreter_when_versions_agree():
    """The mark table is a literal (identical across Pythons). Where the
    running interpreter ships the same Unicode version, it must agree with
    the live data exactly; on other versions the check is skipped."""
    import unicodedata

    from glossabet.corpus.unicode_marks import MARK_RANGES, UNICODE_VERSION

    if unicodedata.unidata_version != UNICODE_VERSION:
        pytest.skip(
            f"interpreter Unicode {unicodedata.unidata_version} != table {UNICODE_VERSION}"
        )
    from_table = {
        cp for start, end in MARK_RANGES for cp in range(start, end + 1)
    }
    live = {
        cp for cp in range(0x110000)
        if unicodedata.category(chr(cp)) in ("Mn", "Mc", "Me")
    }
    assert from_table == live


def test_clojure_kebab_identifiers_are_a_structured_style():
    """`tokenization_contract()` lists clojure-kebab-case as a supported form;
    the register must credit it as word structure (like snake_case), not
    file every Clojure identifier under `flat`."""
    from glossabet.corpus.tokenize import identifier_style

    assert identifier_style("pending-work") == "kebab-case"
    assert identifier_style("worker-loop-state") == "kebab-case"
    assert identifier_style("-main") == "flat"  # a leading hyphen alone is not structure
    assert identifier_style("pending_work") == "snake_case"
    assert "kebab-case" in STRUCTURED_IDENTIFIER_STYLES
