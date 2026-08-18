"""Persistent glossary: round-trip fidelity, validation that rejects the
states drift detection depends on being impossible, deterministic writes,
and the show command."""

import io
import json
import os

import pytest

from glossabet.cli import main
from glossabet.glossary.store import (
    GlossaryError,
    MAX_VALIDATION_ERRORS,
    load_glossary,
    path_in_scope,
    save_glossary,
    scopes_overlap,
    validate_glossary,
)

GLOSSARY = {
    "schema_version": 1,
    "concepts": [
        {
            "id": "payment",
            "term": "Payment",
            "definition": "An attempt to collect money for an order.",
            "status": "canonical",
            "aliases": [
                {"term": "charge", "status": "discouraged",
                 "note": "the gateway operation only"},
            ],
        },
        {
            "id": "billing",
            "term": "Billing",
            "definition": "The subsystem executing and tracking Payments.",
            "status": "proposed",
        },
    ],
}


def test_round_trip(tmp_path):
    save_glossary(tmp_path, GLOSSARY)
    loaded = load_glossary(tmp_path)
    assert {c["id"] for c in loaded["concepts"]} == {"payment", "billing"}
    assert loaded["concepts"][1]["status"] == "canonical"  # sorted by id


def test_absent_glossary_is_none(tmp_path):
    assert load_glossary(tmp_path) is None


def test_save_is_deterministic(tmp_path):
    first = save_glossary(tmp_path, GLOSSARY).read_text(encoding="utf-8")
    second = save_glossary(tmp_path, GLOSSARY).read_text(encoding="utf-8")
    assert first == second


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda g: g.update(schema_version=99), "schema_version"),
        (lambda g: g["concepts"][0].pop("definition"), "definition"),
        (lambda g: g["concepts"][0].update(status="settled"), "settled"),
        (lambda g: g["concepts"][1].update(id="payment"), "duplicate id"),
        (lambda g: g["concepts"][1].update(term="payment"), "duplicate term"),
        (lambda g: g["concepts"][0]["aliases"][0].update(status="meh"), "meh"),
    ],
)
def test_validation_rejects(mutate, fragment):
    glossary = json.loads(json.dumps(GLOSSARY))
    mutate(glossary)
    errors = validate_glossary(glossary)
    assert errors and any(fragment in e for e in errors)


def test_save_refuses_invalid(tmp_path):
    bad = json.loads(json.dumps(GLOSSARY))
    bad["concepts"][0]["status"] = "nonsense"
    with pytest.raises(GlossaryError):
        save_glossary(tmp_path, bad)


def test_alias_cannot_map_to_multiple_concepts():
    glossary = json.loads(json.dumps(GLOSSARY))
    glossary["concepts"][1]["aliases"] = [
        {"term": "CHARGE", "status": "alias"},
    ]

    errors = validate_glossary(glossary)

    assert any("maps to multiple concepts" in error for error in errors)


def test_alias_cannot_claim_another_concepts_canonical_term():
    glossary = json.loads(json.dumps(GLOSSARY))
    glossary["concepts"][0]["aliases"].append(
        {"term": "Billing", "status": "alias"}
    )

    errors = validate_glossary(glossary)

    assert any("maps to multiple concepts" in error for error in errors)


def test_same_vocabulary_can_have_different_owners_in_disjoint_scopes():
    glossary = {
        "schema_version": 1,
        "concepts": [
            {
                "id": "auth-session",
                "term": "Session",
                "definition": "An authenticated interaction.",
                "status": "canonical",
                "scope": {"path_prefixes": ["src/auth"]},
                "aliases": [{"term": "Context", "status": "alias"}],
            },
            {
                "id": "db-session",
                "term": "Session",
                "definition": "A database unit of work.",
                "status": "canonical",
                "scope": {"path_prefixes": ["src/db"]},
                "aliases": [{"term": "Context", "status": "alias"}],
            },
        ],
    }

    assert validate_glossary(glossary) == []


def test_scope_prefixes_respect_path_component_boundaries():
    assert path_in_scope("src/auth/session.py", ("src/auth",))
    assert path_in_scope("src/auth", ("src/auth",))
    assert not path_in_scope("src/authentication/session.py", ("src/auth",))
    assert scopes_overlap(("src",), ("src/auth",))
    assert not scopes_overlap(("src/auth",), ("src/db",))


@pytest.mark.parametrize(
    "left_scope,right_scope",
    [
        (None, {"path_prefixes": ["src/auth"]}),
        ({"path_prefixes": ["src"]}, {"path_prefixes": ["src/auth"]}),
        ({"path_prefixes": ["src/auth"]}, {"path_prefixes": ["src/auth"]}),
    ],
)
def test_vocabulary_owners_must_be_unique_in_overlapping_scopes(
    left_scope, right_scope
):
    concepts = []
    for cid, scope in (("first", left_scope), ("second", right_scope)):
        concept = {
            "id": cid,
            "term": "Session",
            "definition": cid,
            "status": "canonical",
        }
        if scope is not None:
            concept["scope"] = scope
        concepts.append(concept)

    errors = validate_glossary({"schema_version": 1, "concepts": concepts})

    assert any("overlapping scopes" in error for error in errors)


def test_vocabulary_uniqueness_uses_unicode_normalization():
    glossary = {
        "schema_version": 1,
        "concepts": [
            {
                "id": "composed",
                "term": "Café",
                "definition": "Composed spelling.",
                "status": "canonical",
            },
            {
                "id": "decomposed",
                "term": "Cafe\u0301",
                "definition": "Canonically equivalent spelling.",
                "status": "canonical",
            },
        ],
    }

    assert any(
        "duplicate term" in error for error in validate_glossary(glossary)
    )


@pytest.mark.parametrize(
    "scope",
    [
        None,
        "src/auth",
        {},
        {"path_prefixes": []},
        {"path_prefixes": ["../auth"]},
        {"path_prefixes": ["src/**"]},
        {"path_prefixes": ["src/auth", "src/auth"]},
        {"paths": ["src/auth"]},
    ],
)
def test_scope_shape_rejects_ambiguous_or_nonliteral_paths(scope):
    concept = {
        "id": "session",
        "term": "Session",
        "definition": "An interaction.",
        "status": "canonical",
        "scope": scope,
    }

    assert validate_glossary({"schema_version": 1, "concepts": [concept]})


def test_save_normalizes_scope_order_and_show_reports_it(tmp_path, capsys):
    glossary = json.loads(json.dumps(GLOSSARY))
    glossary["concepts"][0]["scope"] = {
        "path_prefixes": ["src/payments", "packages/payments"]
    }

    path = save_glossary(tmp_path, glossary)
    saved = json.loads(path.read_text(encoding="utf-8"))
    payment = next(c for c in saved["concepts"] if c["id"] == "payment")
    assert payment["scope"]["path_prefixes"] == [
        "packages/payments", "src/payments"
    ]
    assert main(["show", str(tmp_path)]) == 0
    assert "scope: packages/payments, src/payments" in capsys.readouterr().out


def test_load_raises_on_corrupt_file(tmp_path):
    out = tmp_path / "glossabet-out"
    out.mkdir()
    (out / "glossary.json").write_text("{not json")
    with pytest.raises(GlossaryError):
        load_glossary(tmp_path)


def test_show_command(tmp_path, capsys):
    save_glossary(tmp_path, GLOSSARY)
    assert main(["show", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "1 canonical" in out and "1 proposed" in out
    assert "Payment — An attempt" in out
    assert "alias: charge [discouraged]" in out


def test_show_without_glossary(tmp_path, capsys):
    assert main(["show", str(tmp_path)]) == 0
    assert "no glossary yet" in capsys.readouterr().out


def test_show_reports_corrupt_glossary_as_user_error(tmp_path, capsys):
    out = tmp_path / "glossabet-out"
    out.mkdir()
    (out / "glossary.json").write_text('{"schema_version": 7, "concepts": []}')
    assert main(["show", str(tmp_path)]) == 1
    assert "schema_version" in capsys.readouterr().err


def test_glossary_never_contaminates_evidence(tmp_path):
    from glossabet.analysis.evidence import build_evidence

    (tmp_path / "a.py").write_text("ordinary_code = 1\n")
    save_glossary(tmp_path, GLOSSARY)
    blob = json.dumps(build_evidence(tmp_path))
    assert "billing" not in blob.lower()  # glossary text must not echo


def test_non_list_aliases_and_bindings_are_errors_not_crashes(tmp_path):
    # A hand-edited glossary with "aliases": null used to raise TypeError,
    # which every command then misreported as an internal defect (exit 2).
    base = {"id": "x", "term": "X", "definition": "d", "status": "canonical"}
    bad_aliases = {"schema_version": 1, "concepts": [{**base, "aliases": None}]}
    assert any("aliases must be a list" in e
               for e in validate_glossary(bad_aliases))
    bad_bindings = {"schema_version": 1,
                    "concepts": [{**base, "bindings": "nope"}]}
    assert any("bindings must be a list" in e
               for e in validate_glossary(bad_bindings))
    out = tmp_path / "glossabet-out"
    out.mkdir()
    (out / "glossary.json").write_text(json.dumps(bad_aliases))
    assert main(["show", str(tmp_path)]) == 1  # user error, not defect


@pytest.mark.parametrize("field", ["id", "term", "definition", "status"])
def test_required_concept_strings_cannot_be_whitespace(field):
    concept = {
        "id": "x", "term": "X", "definition": "A concept.",
        "status": "canonical",
    }
    concept[field] = "   "

    errors = validate_glossary({"schema_version": 1, "concepts": [concept]})

    assert any("non-empty string" in error and repr(field) in error
               for error in errors)


@pytest.mark.parametrize("ref", ["symbol:", "symbol:   "])
def test_binding_target_cannot_be_empty(ref):
    concept = {
        "id": "x", "term": "X", "definition": "A concept.",
        "status": "canonical", "bindings": [{"ref": ref}],
    }

    errors = validate_glossary({"schema_version": 1, "concepts": [concept]})

    assert any("needs a 'ref'" in error for error in errors)


@pytest.mark.parametrize("target", ["concept", "alias"])
def test_non_string_status_is_a_user_error_not_a_crash(
    tmp_path, capsys, target
):
    concept = {
        "id": "x", "term": "X", "definition": "A concept.",
        "status": "canonical",
    }
    if target == "concept":
        concept["status"] = []
    else:
        concept["aliases"] = [{"term": "Former X", "status": []}]
    glossary = {"schema_version": 1, "concepts": [concept]}

    errors = validate_glossary(glossary)

    assert any("status" in error for error in errors)
    out = tmp_path / "glossabet-out"
    out.mkdir()
    (out / "glossary.json").write_text(json.dumps(glossary))
    assert main(["show", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "status" in captured.err
    assert "internal error" not in captured.err.lower()


def test_oversized_glossary_refused_as_user_error(tmp_path, monkeypatch):
    monkeypatch.setattr("glossabet.runtime.artifacts.MAX_JSON_BYTES", 50)
    out = tmp_path / "glossabet-out"
    out.mkdir()
    (out / "glossary.json").write_text(json.dumps({
        "schema_version": 1,
        "concepts": [{"id": "x" * 200, "term": "X", "definition": "d",
                      "status": "canonical"}],
    }))
    with pytest.raises(GlossaryError, match="larger than"):
        load_glossary(tmp_path)
    assert main(["show", str(tmp_path)]) == 1


def test_deeply_nested_glossary_json_is_clean_error(tmp_path):
    out = tmp_path / "glossabet-out"
    out.mkdir()
    (out / "glossary.json").write_text("[" * 60000 + "]" * 60000)
    with pytest.raises(GlossaryError):  # not an uncaught RecursionError
        load_glossary(tmp_path)
    assert main(["show", str(tmp_path)]) == 1


def test_wrong_top_level_glossary_json_is_clean_error(tmp_path, capsys):
    out = tmp_path / "glossabet-out"
    out.mkdir()
    (out / "glossary.json").write_text("[]")
    with pytest.raises(GlossaryError, match="top level must be an object"):
        load_glossary(tmp_path)
    assert main(["show", str(tmp_path)]) == 1
    assert "top level must be an object" in capsys.readouterr().err


def test_glossary_symlink_is_rejected_without_reading_target(tmp_path):
    outside = tmp_path / "outside-glossary.json"
    outside.write_text(json.dumps(GLOSSARY))
    repo = tmp_path / "repo"
    out = repo / "glossabet-out"
    out.mkdir(parents=True)
    os.symlink(outside, out / "glossary.json")

    with pytest.raises(GlossaryError, match="symlinked artifact"):
        load_glossary(repo)


@pytest.mark.parametrize(
    "mutate,fragment",
    [
        (lambda g: g.update(typo=True), "top level has unknown field"),
        (lambda g: g["concepts"][0].update(typo=True), "concepts[0] has unknown field"),
        (
            lambda g: g["concepts"][0]["aliases"][0].update(typo=True),
            "aliases[0] has unknown field",
        ),
        (
            lambda g: g["concepts"][0].update(
                bindings=[{"ref": "symbol:Payment", "typo": True}]
            ),
            "bindings[0] has unknown field",
        ),
    ],
)
def test_unknown_glossary_fields_are_rejected_at_every_object_level(
    mutate, fragment
):
    glossary = json.loads(json.dumps(GLOSSARY))
    mutate(glossary)

    assert any(fragment in error for error in validate_glossary(glossary))


@pytest.mark.parametrize(
    "field,value",
    [
        ("term", "Payment\x1b]0;forged\x07"),
        ("id", "payment\nforged"),
        ("term", "Pay\u202ement"),
        ("definition", "Looks safe\x9b2J"),
    ],
)
def test_terminal_controls_and_bidi_formatting_are_rejected(field, value):
    glossary = json.loads(json.dumps(GLOSSARY))
    glossary["concepts"][0][field] = value

    errors = validate_glossary(glossary)

    assert any("terminal control or bidirectional" in error for error in errors)


def test_human_prose_may_contain_newlines_and_tabs():
    glossary = json.loads(json.dumps(GLOSSARY))
    glossary["concepts"][0]["definition"] = "First line.\n\tSecond line."

    assert validate_glossary(glossary) == []


def test_show_renders_prose_layout_controls_visibly(tmp_path, capsys):
    glossary = json.loads(json.dumps(GLOSSARY))
    glossary["concepts"][0]["definition"] = "First line.\n\tSecond line."
    save_glossary(tmp_path, glossary)

    assert main(["show", str(tmp_path)]) == 0

    output = capsys.readouterr().out
    assert "First line.\\n\\tSecond line." in output
    assert "First line.\n\tSecond line." not in output


def test_validation_diagnostics_are_bounded():
    glossary = {"schema_version": 1, "concepts": [None] * 500}

    errors = validate_glossary(glossary)

    assert len(errors) == MAX_VALIDATION_ERRORS
    assert "additional validation error(s) omitted" in errors[-1]


def test_concept_budget_is_checked_before_per_concept_validation(monkeypatch):
    monkeypatch.setattr("glossabet.glossary.store.MAX_GLOSSARY_CONCEPTS", 2)
    glossary = {"schema_version": 1, "concepts": [None, None, None]}

    errors = validate_glossary(glossary)

    assert errors == ["concepts exceeds the 2-concept limit"]
    assert not any("must be an object" in error for error in errors)


@pytest.mark.parametrize(
    "constant,field,values,fragment",
    [
        (
            "MAX_GLOSSARY_ALIASES",
            "aliases",
            [{"term": f"Alias {index}", "status": "alias"} for index in range(3)],
            "aliases exceeds the 2-entry limit",
        ),
        (
            "MAX_GLOSSARY_BINDINGS",
            "bindings",
            [{"ref": f"symbol:Name{index}"} for index in range(3)],
            "bindings exceeds the 2-entry limit",
        ),
        (
            "MAX_GLOSSARY_SCOPE_PREFIXES",
            "scope",
            {"path_prefixes": ["a", "b", "c"]},
            "scope path prefixes exceeds the 2-entry limit",
        ),
    ],
)
def test_aggregate_child_budgets_are_checked_before_entry_validation(
    monkeypatch, constant, field, values, fragment
):
    monkeypatch.setattr(f"glossabet.glossary.store.{constant}", 2)
    concept = {
        "id": "x", "term": "X", "definition": "A concept.",
        "status": "canonical", field: values,
    }

    errors = validate_glossary({"schema_version": 1, "concepts": [concept]})

    assert errors == [fragment]


def test_identity_and_prose_string_limits_are_independent(monkeypatch):
    concept = {
        "id": "x", "term": "T" * 21, "definition": "D" * 7,
        "status": "canonical",
    }
    monkeypatch.setattr("glossabet.glossary.store.MAX_GLOSSARY_IDENTITY_CHARS", 20)
    monkeypatch.setattr("glossabet.glossary.store.MAX_GLOSSARY_PROSE_CHARS", 6)

    errors = validate_glossary({"schema_version": 1, "concepts": [concept]})

    assert any("field 'term' exceeds 20 characters" in error for error in errors)
    assert any(
        "field 'definition' exceeds 6 characters" in error for error in errors
    )


def test_scope_character_and_inherited_ownership_work_are_bounded(monkeypatch):
    concept = {
        "id": "x", "term": "X", "definition": "A concept.",
        "status": "canonical",
        "scope": {"path_prefixes": ["abc", "def"]},
        "aliases": [
            {"term": "Former X", "status": "alias"},
            {"term": "Old X", "status": "deprecated"},
        ],
    }
    monkeypatch.setattr("glossabet.glossary.store.MAX_GLOSSARY_SCOPE_CHARACTERS", 5)
    monkeypatch.setattr(
        "glossabet.glossary.store.MAX_GLOSSARY_OWNERSHIP_SCOPE_CHARACTERS", 10
    )

    errors = validate_glossary({"schema_version": 1, "concepts": [concept]})

    assert any("5-character aggregate limit" in error for error in errors)
    assert any("10-character limit" in error for error in errors)


def test_unknown_field_diagnostic_uses_a_bounded_sample():
    glossary = {
        "schema_version": 1,
        "concepts": [],
        **{f"unknown-{index:03d}": True for index in range(100)},
    }

    errors = validate_glossary(glossary)

    assert len(errors) == 1
    assert "and 90 more" in errors[0]
    assert len(errors[0]) < 500


def test_vocabulary_owner_validation_uses_indexed_scope_lookup(monkeypatch):
    # The former implementation called scopes_overlap once for every previous
    # owner of the same word. This corpus made 7,998,000 pairwise checks. The
    # indexed implementation does not call that helper during validation.
    def pairwise_lookup_is_a_regression(*_args):
        raise AssertionError("pairwise scope comparison used")

    monkeypatch.setattr(
        "glossabet.glossary.store.scopes_overlap", pairwise_lookup_is_a_regression
    )
    concepts = [
        {
            "id": f"session-{index}",
            "term": "Session",
            "definition": "A subsystem-local session.",
            "status": "canonical",
            "scope": {"path_prefixes": [f"packages/p{index:04d}"]},
        }
        for index in range(4_000)
    ]

    assert validate_glossary({"schema_version": 1, "concepts": concepts}) == []


def test_overlapping_paths_inside_one_scope_are_rejected():
    glossary = json.loads(json.dumps(GLOSSARY))
    glossary["concepts"][0]["scope"] = {
        "path_prefixes": ["src", "src/payments"]
    }

    assert any(
        "contains overlapping paths" in error
        for error in validate_glossary(glossary)
    )
    # A sibling that sorts between the ancestor and its descendant (`-`,
    # `.`, space, digits all sort before `/`) must not hide the overlap.
    for prefixes in (
        ["src", "src-old", "src/payments"],
        ["pkg", "pkg.egg-info", "pkg/x"],
        ["a", "a b", "a/b"],
        ["src/payments", "src", "src-old"],
    ):
        glossary["concepts"][0]["scope"] = {"path_prefixes": prefixes}
        assert any(
            "contains overlapping paths" in error
            for error in validate_glossary(glossary)
        ), prefixes
    glossary["concepts"][0]["scope"] = {"path_prefixes": ["src", "src-old"]}
    assert not any(
        "overlapping" in error for error in validate_glossary(glossary)
    )


def test_save_command_validates_stdin_and_writes_atomically(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(GLOSSARY)))

    assert main(["save", str(tmp_path)]) == 0

    captured = capsys.readouterr()
    assert "saved glossary" in captured.out
    loaded = load_glossary(tmp_path)
    assert [concept["id"] for concept in loaded["concepts"]] == [
        "billing", "payment"
    ]


def test_save_command_rejects_invalid_stdin_without_writing(
    tmp_path, capsys, monkeypatch
):
    path = save_glossary(tmp_path, GLOSSARY)
    original = path.read_bytes()
    invalid = json.loads(json.dumps(GLOSSARY))
    invalid["concepts"][0]["typo"] = True
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(invalid)))

    assert main(["save", str(tmp_path)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unknown field" in captured.err
    assert path.read_bytes() == original


def test_save_command_bounds_standard_input(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("glossabet.glossary.glossary_commands.MAX_JSON_BYTES", 20)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(GLOSSARY)))

    assert main(["save", str(tmp_path)]) == 1

    assert "larger than 20 bytes" in capsys.readouterr().err
    assert not (tmp_path / "glossabet-out" / "glossary.json").exists()


def test_save_command_cannot_follow_a_glossary_symlink(
    tmp_path, capsys, monkeypatch
):
    outside = tmp_path / "outside.json"
    outside.write_text("do not replace")
    repo = tmp_path / "repo"
    out = repo / "glossabet-out"
    out.mkdir(parents=True)
    os.symlink(outside, out / "glossary.json")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(GLOSSARY)))

    assert main(["save", str(repo)]) == 1

    assert "symlinked artifact paths are not trusted" in capsys.readouterr().err
    assert outside.read_text(encoding="utf-8") == "do not replace"


def test_schema_version_must_be_the_integer_one_not_a_bool_or_float():
    for version in (True, 1.0, "1"):
        errors = validate_glossary({"schema_version": version, "concepts": []})
        assert errors and errors[0].startswith("schema_version must be 1"), version
    assert validate_glossary({"schema_version": 1, "concepts": []}) == []


def test_lone_surrogates_are_refused_at_save_so_brief_never_crashes(tmp_path):
    """A JSON `\\udcff` escape decodes to a str no UTF-8 writer can encode;
    it used to pass validation and then make `brief`/`sync-context` exit 2
    every session. Every string field goes through the same check."""
    for field, where in (
        ("term", "concepts[0] field 'term'"),
        ("definition", "concepts[0] field 'definition'"),
        ("notes", "concepts[0].notes"),
    ):
        glossary = json.loads(json.dumps(GLOSSARY))
        glossary["concepts"][0][field] = "bad \udcff char"
        errors = validate_glossary(glossary)
        # Now caught by the terminal-control check (a lone surrogate is a
        # control character to every UTF-8 stream); either message is a refusal.
        assert any(
            error.startswith(where)
            and ("lone surrogate" in error or "terminal control" in error)
            for error in errors
        ), (field, errors)
    glossary = json.loads(json.dumps(GLOSSARY))
    glossary["concepts"][0]["aliases"] = [
        {"term": "x\udcff", "status": "alias"}
    ]
    assert validate_glossary(glossary)


def test_ownership_is_keyed_by_token_sequence_and_rejects_invisible_spellings():
    """drift/validate/matching compare vocabulary by lexical tokens, so two
    concepts owning `Alpha Beta` and `AlphaBeta` (or `alpha_beta`) would be
    one ambiguous identity to every consumer; ownership is keyed the same
    way. Invisible formatting characters (ZWSP) in a term are refused."""
    glossary = {"schema_version": 1, "concepts": [
        {"id": "a", "term": "Alpha Beta", "definition": "d", "status": "canonical"},
        {"id": "b", "term": "AlphaBeta", "definition": "d", "status": "canonical"},
        {"id": "c", "term": "alpha_beta", "definition": "d", "status": "canonical"},
        {"id": "d", "term": "Alpha\u200bBeta", "definition": "d", "status": "canonical"},
    ]}
    errors = validate_glossary(glossary)
    assert any("concepts[1] duplicate term 'AlphaBeta'" in e for e in errors)
    assert any("concepts[2] duplicate term 'alpha_beta'" in e for e in errors)
    assert any("concepts[3] field 'term' contains a terminal control" in e for e in errors)
    # Disjoint scopes may still share the identity deliberately.
    scoped = {"schema_version": 1, "concepts": [
        {"id": "a", "term": "Alpha Beta", "definition": "d", "status": "canonical",
         "scope": {"path_prefixes": ["x"]}},
        {"id": "b", "term": "AlphaBeta", "definition": "d", "status": "canonical",
         "scope": {"path_prefixes": ["y"]}},
    ]}
    assert validate_glossary(scoped) == []


def test_default_ignorable_characters_are_refused_as_a_class():
    """Not four enumerated code points but Unicode's Default_Ignorable set:
    TAG-block letters, variation selectors, Hangul fillers, the combining
    grapheme joiner, the Mongolian vowel separator, interlinear annotation
    anchors — anything that renders as nothing and hides text from the human
    while a model reads it. ZWNJ/ZWJ stay allowed (Persian, Indic, emoji)."""
    hidden = {
        "TAG": "Pay\U000E0041ment",
        "VS16": "Payment\ufe0f",
        "CGJ": "Pay\u034fment",
        "filler": "Pay\u3164ment",
        "MVS": "Pay\u180ement",
        "annotation": "\ufff9IGNORE\ufffaPayment\ufffb",
    }
    for label, term in hidden.items():
        glossary = json.loads(json.dumps(GLOSSARY))
        glossary["concepts"][0]["term"] = term
        assert any("terminal control" in e for e in validate_glossary(glossary)), label
        glossary = json.loads(json.dumps(GLOSSARY))
        glossary["concepts"][0]["definition"] = f"a {term} thing"
        assert any("terminal control" in e for e in validate_glossary(glossary)), label
    glossary = json.loads(json.dumps(GLOSSARY))
    glossary["concepts"][0]["term"] = "نیم\u200cفاصله"
    assert not any("terminal control" in e for e in validate_glossary(glossary))
