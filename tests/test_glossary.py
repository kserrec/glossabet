"""Persistent glossary: round-trip fidelity, validation that rejects the
states drift detection depends on being impossible, deterministic writes,
and the show command."""

import io
import json
import os
import unicodedata

import pytest

import glossabet.glossary.model as glossary_model
import glossabet.glossary.schema as glossary_schema
import glossabet.glossary.scope as glossary_scope
import glossabet.glossary.store as glossary_store
from glossabet.cli import main
from glossabet.glossary.model import BINDING_KINDS, STATUSES
from glossabet.glossary.schema import (
    MAX_VALIDATION_ERRORS,
    checked_glossary,
    validate_glossary,
)
from glossabet.glossary.scope import path_in_scope, scopes_overlap
from glossabet.glossary.store import (
    GlossaryError,
    glossary_sha256,
    load_glossary,
    save_glossary,
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


def test_store_reexports_only_the_historical_compatibility_surface():
    owners = {
        "BINDING_KINDS": glossary_model,
        "GLOSSARY_SCHEMA_VERSION": glossary_model,
        "SCOPE_PATHS_KEY": glossary_model,
        "STATUSES": glossary_model,
        "checked_glossary": glossary_schema,
        "validate_glossary": glossary_schema,
        "concept_scope": glossary_scope,
        "path_in_scope": glossary_scope,
        "scope_evidence": glossary_scope,
        "scopes_overlap": glossary_scope,
    }
    persistence_exports = {
        "GLOSSARY_FILE",
        "GlossaryError",
        "glossary_sha256",
        "load_glossary",
        "save_glossary",
    }
    assert set(glossary_store.__all__) == persistence_exports | owners.keys()
    for name, owner in owners.items():
        assert getattr(glossary_store, name) is getattr(owner, name)


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


def test_duplicate_vocabulary_within_one_concept_is_rejected():
    """Two aliases that fold to the same word, or an alias that repeats the
    concept's own term, are one entry declared twice with (possibly) two
    statuses — the reader could not tell which status applies. Distinct
    from the cross-concept rule, which the neighbouring tests pin."""
    def concept(aliases):
        return {"schema_version": 1, "concepts": [{
            "id": "payment", "term": "Payment", "definition": "d",
            "status": "canonical", "aliases": aliases,
        }]}

    for aliases in (
        [{"term": "charge", "status": "discouraged"},
         {"term": "Charge", "status": "deprecated"}],       # case fold
        [{"term": "Cafe\u0301", "status": "alias"},
         {"term": "Caf\u00e9", "status": "alias"}],           # NFKC fold
        [{"term": "Payment", "status": "discouraged"}],      # own term
        [{"term": "payments", "status": "alias"},
         {"term": "Payments", "status": "alias"}],
    ):
        errors = validate_glossary(concept(aliases))
        assert any("within concept 'payment'" in error for error in errors), (
            aliases, errors
        )
    assert validate_glossary(concept(
        [{"term": "charge", "status": "discouraged"},
         {"term": "billing", "status": "alias"}]
    )) == []


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


def test_scope_identity_is_nfc_for_duplicates_ancestry_and_comparison():
    composed = unicodedata.normalize("NFC", "café")
    decomposed = unicodedata.normalize("NFD", "café")
    assert composed != decomposed

    concept = {
        "id": "cafe",
        "term": "Cafe",
        "definition": "A subsystem.",
        "status": "canonical",
        "scope": {"path_prefixes": [composed, decomposed]},
    }
    errors = validate_glossary({"schema_version": 1, "concepts": [concept]})
    assert any("contains duplicate paths" in error for error in errors)

    concept["scope"] = {
        "path_prefixes": [composed, f"{decomposed}/orders"]
    }
    errors = validate_glossary({"schema_version": 1, "concepts": [concept]})
    assert any("contains overlapping paths" in error for error in errors)
    assert scopes_overlap((composed,), (f"{decomposed}/orders",))

    # NFC does not collapse paths that are merely similar spellings.
    concept["scope"] = {"path_prefixes": ["cafe", composed]}
    assert validate_glossary({"schema_version": 1, "concepts": [concept]}) == []
    assert not scopes_overlap(("cafe",), (composed,))


@pytest.mark.parametrize("ancestor_first", [True, False])
def test_vocabulary_ownership_rejects_canonically_equivalent_scopes(
    ancestor_first,
):
    composed = unicodedata.normalize("NFC", "café")
    decomposed = unicodedata.normalize("NFD", "café")
    scopes = [composed, f"{decomposed}/orders"]
    if not ancestor_first:
        scopes.reverse()
    concepts = [
        {
            "id": f"owner-{index}",
            "term": "Session",
            "definition": "A subsystem-local session.",
            "status": "canonical",
            "scope": {"path_prefixes": [scope]},
        }
        for index, scope in enumerate(scopes)
    ]

    errors = validate_glossary({"schema_version": 1, "concepts": concepts})

    assert any("overlapping scopes" in error for error in errors)


@pytest.mark.parametrize(
    "left_scope,right_scope",
    [
        (None, {"path_prefixes": ["src/auth"]}),
        ({"path_prefixes": ["src"]}, {"path_prefixes": ["src/auth"]}),
        ({"path_prefixes": ["src/auth"]}, {"path_prefixes": ["src/auth"]}),
        # Both orders: the check must not depend on which owner is declared
        # first (descendant-then-ancestor, scoped-then-global).
        ({"path_prefixes": ["src/auth"]}, {"path_prefixes": ["src"]}),
        ({"path_prefixes": ["src/auth"]}, None),
        # Multi-prefix scopes overlap on any one prefix.
        ({"path_prefixes": ["docs", "src/auth/session"]},
         {"path_prefixes": ["src/auth"]}),
        ({"path_prefixes": ["src/auth"]},
         {"path_prefixes": ["src/auth/session", "docs"]}),
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


def test_save_and_load_use_one_nfc_scope_identity(tmp_path):
    composed = unicodedata.normalize("NFC", "café")
    decomposed = unicodedata.normalize("NFD", "café")
    assert composed != decomposed

    def document(prefix):
        return {
            "schema_version": 1,
            "concepts": [{
                "id": "cafe",
                "term": "Cafe",
                "definition": "A subsystem.",
                "status": "canonical",
                "scope": {"path_prefixes": [prefix, "src"]},
            }],
        }

    first = save_glossary(tmp_path, document(decomposed)).read_bytes()
    second = save_glossary(tmp_path, document(composed)).read_bytes()
    assert first == second
    assert glossary_sha256(document(decomposed)) == glossary_sha256(
        document(composed)
    )
    persisted = json.loads(second)
    assert persisted["concepts"][0]["scope"]["path_prefixes"] == [
        composed, "src"
    ]

    # Loading an accepted schema-1 file written before this canonicalization
    # returns the same internal scope identity without rewriting the file.
    path = tmp_path / "glossabet-out" / "glossary.json"
    path.write_text(
        json.dumps(document(decomposed), ensure_ascii=False), encoding="utf-8"
    )
    original = path.read_bytes()
    loaded = load_glossary(tmp_path)
    assert loaded is not None
    assert path.read_bytes() == original
    assert loaded["concepts"][0]["scope"]["path_prefixes"] == [
        composed, "src"
    ]


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

    assert any("terminal control, bidirectional-format, or invisible" in error for error in errors)


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
    monkeypatch.setattr("glossabet.glossary.schema.MAX_GLOSSARY_CONCEPTS", 2)
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
    monkeypatch.setattr(f"glossabet.glossary.schema.{constant}", 2)
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
    monkeypatch.setattr("glossabet.glossary.schema.MAX_GLOSSARY_IDENTITY_CHARS", 20)
    monkeypatch.setattr("glossabet.glossary.schema.MAX_GLOSSARY_PROSE_CHARS", 6)

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
    monkeypatch.setattr("glossabet.glossary.schema.MAX_GLOSSARY_SCOPE_CHARACTERS", 5)
    monkeypatch.setattr(
        "glossabet.glossary.schema.MAX_GLOSSARY_OWNERSHIP_SCOPE_CHARACTERS", 10
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
        "glossabet.glossary.scope.scopes_overlap", pairwise_lookup_is_a_regression
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


def test_save_command_routes_json_null_to_schema_validation(
    tmp_path, capsys, monkeypatch
):
    """A successfully parsed JSON null is invalid glossary data, not an input
    failure. It must reach the schema validator and produce its diagnostic."""
    monkeypatch.setattr("sys.stdin", io.StringIO("null"))

    assert main(["save", str(tmp_path)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "refusing to save invalid glossary: top level must be an object" in (
        captured.err
    )
    assert "standard input is unreadable" not in captured.err
    assert not (tmp_path / "glossabet-out" / "glossary.json").exists()


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
        errors = validate_glossary(glossary)
        assert any("invisible character (U+" in e for e in errors), (label, errors)
        # Prose tolerates emoji presentation/keycap selectors (a display hint,
        # "❤️"); every other invisible character is refused there too.
        glossary = json.loads(json.dumps(GLOSSARY))
        glossary["concepts"][0]["definition"] = f"a {term} thing"
        errors = validate_glossary(glossary)
        if label == "VS16":
            assert errors == []
        else:
            assert any("invisible character (U+" in e for e in errors), (label, errors)
    glossary = json.loads(json.dumps(GLOSSARY))
    glossary["concepts"][0]["term"] = "نیم\u200cفاصله"
    assert not any("invisible character" in e for e in validate_glossary(glossary))
    glossary["concepts"][0]["definition"] = "I \u2764\ufe0f this 1\ufe0f\u20e3"
    assert validate_glossary(glossary) == []


def test_hostile_glossary_family_never_raises_and_accepted_documents_survive_every_consumer(tmp_path):
    """Seeded family of glossary documents — from valid-but-odd (Kelvin sign,
    ligatures, Turkish dotted I, full-width digits, RTL scripts, emoji,
    long strings, scoped and bound concepts) to malformed (wrong types,
    NaN, lone surrogates, RLO, NUL, managed-block markers inside terms).
    Validation is deterministic and returns strings; every document it
    ACCEPTS then survives every consumer: save→load→save is byte-stable,
    `show` prints UTF-8, the brief stays under its byte cap, the managed
    block re-analyzes as current and re-syncs as current for both agents,
    and validation/drift are NaN-clean. No single test asserts that
    multi-consumer invariant. Ported from a hunter (test-audit)."""
    import contextlib
    import copy
    import random

    from glossabet.agent.brief import MAX_BRIEF_BYTES, build_brief, build_managed_brief
    from glossabet.agent.context_sync import sync_context
    from glossabet.agent.managed_context import analyze_managed_block, render_block
    from glossabet.analysis.evidence import build_evidence
    from glossabet.glossary.drift import build_drift
    from glossabet.glossary.glossary_commands import _print_glossary
    from glossabet.glossary.reconcile import build_validation
    from glossabet.glossary.repository_glossary import repository_glossary_section
    from glossabet.glossary.store import glossary_sha256

    rng = random.Random(20260818)
    rlo, lone, low_lone, esc, nul, zwsp = (
        "\u202e", "\ud800", "\udcff", "\x1b[0m", "\x00", "\u200b"
    )
    strings = [
        "Payment Service", "payment service", "PAYMENT SERVICE", "Session",
        "session", "Ledger", "K", "K", "k", "ﬁle", "file", "ﬁ",
        "fi", "İstanbul", "istanbul", "ıstanbul", "I", "i", "ı", "ß", "ss",
        "SS", "Café", "Café", "cafe", "ｆｕｌｌ", "full", "①", "1", "Ⅸ",
        "ix", "", " ", "  x  ", "x" * 200, "x" * 1024, "x" * 1025, "\t",
        "a\nb", "a\tb", "a b", rlo, esc, nul, rlo + "reversed", "עברית",
        "مرحبا", "🙂", "a🙂b", lone, "a" + low_lone + "b",
        "<!-- glossabet:managed-context", "<!-- glossabet:managed-context:end -->",
        "-- glossabet", "\ufeff", "a" + zwsp + "b", zwsp, "src", "src/auth",
        "symbol:x", "::", ":", "µ", "μ", "Ω", "Ω", "Å", "Å", "℮",
        "ͅ", "ι", "ς", "σ", "Σ", "ǅ", "ǆ", "Ǆ", "…", "...", "1e400",
        "\\n", "\\u202e", "* not markdown *", "`code`", "# heading", "payment",
        "service", "sess ion", "Session Store", "session_token",
        "SessionStore", "pay.py",
    ]
    sane = [
        "Payment Service", "Session", "Ledger", "K", "K", "ﬁle", "file",
        "İstanbul", "istanbul", "ı", "ß", "ss", "Café", "Café", "ｆｕｌｌ",
        "full", "①", "1", "Ⅸ", "ix", "x" * 200, "x" * 1024, "עברית", "مرحبا",
        "🙂", "a🙂b", "µ", "μ", "Ω", "Ω", "Å", "Å", "ς", "σ", "Σ",
        "ǅ", "ǆ", "…", "payment", "service", "Session Store", "session_token",
        "SessionStore", "pay.py", "Payment-Request", "payment_request",
        "PaymentRequest", "sess ion", "Ledger Entry", "ledger", "auth session",
        "Token",
    ]
    statuses = ["canonical", "proposed", "alias", "discouraged", "deprecated",
                "unknown", "Canonical", "CANONICAL", "", "x", None, 1, True,
                ["canonical"]]
    valid_statuses = ["canonical", "canonical", "canonical", "proposed", "alias",
                      "discouraged", "deprecated", "unknown"]
    paths = [
        "src", "src/auth", "src/billing", "src/auth/session.py", "docs", "src/",
        "/src", "src/../x", "src//x", "*", "src\\x", "", " src", "x" * 1024,
        "src/auth/x", "src/auth/x/y", "src" + nul, "src\n", "K", "K",
        "src-old", "src/../src", ".", "..", "src/.", "срц", "src/🙂",
        "src" + low_lone, "docs/g.md", "GLOSSARY.md", "glossabet-out",
        "graphify-out/graph.json",
    ]
    sane_paths = ["src", "src/auth", "src/billing", "src/auth/session.py", "docs",
                  "src-old", "K", "K", "src/🙂", "x" * 100, "srс"]
    refs = [
        "symbol:payment_service", "symbol:SessionStore", "file:src/billing/pay.py",
        "module:src/billing", "module:src.billing", "file:docs/g.md", "symbol:",
        "symbol: ", ":x", "::x", "symbol::x", "symbol:a:b", "graph:1",
        "community:0", "Symbol:x", "symbol:K", "symbol:ﬁle",
        "file:GLOSSARY.md", "file:src" + low_lone, "symbol:" + rlo + "x",
        "file:../x", "file:/etc/passwd", "module:", "x", "", "symbol:x" * 300,
    ]
    sane_refs = [
        "symbol:payment_service", "symbol:SessionStore", "file:src/billing/pay.py",
        "module:src/billing", "module:src.billing", "file:docs/g.md",
        "symbol:K", "symbol:ﬁle", "file:GLOSSARY.md", "symbol:a:b",
        "module:src", "file:src/auth/session.py", "symbol:x" * 300,
        "symbol:session_token", "symbol:PaymentRequest",
    ]

    def s():
        return rng.choice(strings)

    def ss():
        return rng.choice(sane) if rng.random() < 0.75 else s()

    def scalar():
        return rng.choice([None, True, False, 0, 1, -1, 1.5, float("nan"), 10 ** 400,
                           [], {}, [1], {"a": 1}, "x", ""])

    def maybe(value, p=0.9):
        return value if rng.random() < p else scalar()

    def scope():
        r = rng.random()
        if r < 0.6:
            return {"path_prefixes": maybe([
                maybe(rng.choice(paths), 0.95)
                for _ in range(rng.choice([1, 1, 1, 2, 3, 0, 50]))
            ])}
        if r < 0.7:
            return {"path_prefixes": maybe(rng.choice(paths)), "extra": 1}
        return scalar()

    def alias():
        entry = {}
        if rng.random() < 0.95:
            entry["term"] = maybe(s())
        if rng.random() < 0.95:
            entry["status"] = maybe(rng.choice(statuses))
        if rng.random() < 0.3:
            entry["note"] = maybe(s())
        if rng.random() < 0.05:
            entry["x"] = 1
        return entry if rng.random() < 0.95 else scalar()

    def binding():
        entry = {}
        if rng.random() < 0.95:
            entry["ref"] = maybe(rng.choice(refs))
        if rng.random() < 0.05:
            entry["kind"] = "symbol"
        return entry if rng.random() < 0.95 else scalar()

    def concept(index):
        entry = {}
        if rng.random() < 0.97:
            entry["id"] = maybe(rng.choice([f"c{index}", f"c{rng.randint(0, 3)}", s()]))
        if rng.random() < 0.97:
            entry["term"] = maybe(s())
        if rng.random() < 0.97:
            entry["definition"] = maybe(rng.choice([s(), "A definition.", "def\nwith\nlines"]))
        if rng.random() < 0.97:
            entry["status"] = maybe(rng.choice(statuses))
        if rng.random() < 0.4:
            entry["scope"] = scope()
        if rng.random() < 0.5:
            entry["aliases"] = maybe([alias() for _ in range(rng.choice([0, 1, 1, 2, 5]))])
        if rng.random() < 0.5:
            entry["bindings"] = maybe([binding() for _ in range(rng.choice([0, 1, 1, 2, 5]))])
        if rng.random() < 0.2:
            entry["notes"] = maybe(s())
        if rng.random() < 0.05:
            entry[s()] = scalar()
        return entry if rng.random() < 0.96 else scalar()

    def valid_concept(index):
        entry = {
            "id": rng.choice([f"c{index}", f"c{index}", s()]),
            "term": ss(),
            "definition": rng.choice(["A definition.", ss(), "def\nlines"]),
            "status": rng.choice(valid_statuses),
        }
        if rng.random() < 0.4:
            entry["scope"] = {"path_prefixes": [
                rng.choice(sane_paths if rng.random() < 0.8 else paths)
                for _ in range(rng.choice([1, 1, 2]))
            ]}
        if rng.random() < 0.5:
            entry["aliases"] = [
                {"term": ss(), "status": rng.choice(valid_statuses),
                 **({"note": s()} if rng.random() < 0.3 else {})}
                for _ in range(rng.choice([1, 1, 2, 4]))
            ]
        if rng.random() < 0.5:
            entry["bindings"] = [
                ({"ref": rng.choice(sane_refs)} if rng.random() < 0.8 else binding())
                for _ in range(rng.choice([1, 1, 2]))
            ]
        if rng.random() < 0.2:
            entry["notes"] = ss()
        if rng.random() < 0.1:
            entry[rng.choice(list(entry))] = scalar()
        return entry

    def glossary():
        if rng.random() < 0.8:
            return {"schema_version": 1, "concepts": [
                valid_concept(i) for i in range(rng.choice([1, 2, 3, 4, 8, 30]))
            ]}
        doc = {}
        if rng.random() < 0.95:
            doc["schema_version"] = rng.choice([1, 1, 1, 1, "1", 1.0, True, 2, None])
        if rng.random() < 0.97:
            doc["concepts"] = maybe([concept(i) for i in range(rng.choice([0, 1, 2, 3, 4, 8, 30]))])
        if rng.random() < 0.05:
            doc[s()] = scalar()
        return doc if rng.random() < 0.97 else scalar()

    root = tmp_path
    (root / "src" / "auth").mkdir(parents=True)
    (root / "src" / "billing").mkdir(parents=True)
    (root / "src" / "auth" / "session.py").write_text(
        "session_token = 1\nclass SessionStore: pass\npayment_service=2\nledger=3\n"
    )
    (root / "src" / "billing" / "pay.py").write_text(
        "payment_service = 1\nclass PaymentRequest: pass\nsession=1\n"
    )
    (root / "docs").mkdir()
    (root / "docs" / "g.md").write_text("payment service session token ledger\n")
    (root / "GLOSSARY.md").write_text(
        "# Glossary\n\n**Payment Service** — thing\n\n**Session** — other\nLedger is old.\n",
        encoding="utf-8",
    )
    evidence = build_evidence(root)

    dumped = accepted = 0
    for case in range(150):
        doc = glossary()
        try:
            text = json.dumps(doc)
        except (ValueError, TypeError):
            continue
        doc = json.loads(text)
        dumped += 1
        errors = validate_glossary(doc)
        assert errors == validate_glossary(copy.deepcopy(doc)), f"case {case}: nondeterministic"
        assert all(isinstance(error, str) for error in errors), case
        if errors:
            continue
        accepted += 1
        path = save_glossary(root, doc)
        loaded = load_glossary(root)
        assert loaded is not None, case
        first_bytes = path.read_bytes()
        save_glossary(root, loaded)
        assert path.read_bytes() == first_bytes, f"case {case}: save not idempotent"
        glossary_sha256(loaded)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            _print_glossary(loaded)
        buffer.getvalue().encode("utf-8")
        brief = build_brief(loaded, {"head": "a" * 40, "dirty": False})
        assert len(brief.encode("utf-8")) <= MAX_BRIEF_BYTES, case
        build_managed_brief(loaded)
        block = render_block(loaded)
        assert analyze_managed_block(block, loaded).status == "current", case
        for agent in ("codex", "claude"):
            sync_context(root, loaded, agent)
            _, outcome = sync_context(root, loaded, agent)
            assert outcome == "current", f"case {case}: second sync {outcome}"
        validation = build_validation(
            evidence, loaded,
            repository_glossary=repository_glossary_section(root, evidence, loaded),
        )
        json.dumps(validation, allow_nan=False)
        json.dumps(build_drift(evidence, loaded), allow_nan=False)
        for name in ("AGENTS.md", "CLAUDE.md"):
            (root / name).unlink(missing_ok=True)
    assert dumped >= 100 and accepted >= 15, (dumped, accepted)


def test_checked_glossary_is_the_only_typed_boundary():
    """Untrusted JSON becomes a ``GlossaryDocument`` only after every
    validation rule accepted it; a rejected document yields the same
    diagnostics ``validate_glossary`` reports, in the same order."""
    document, errors = checked_glossary(GLOSSARY)
    assert document is GLOSSARY and errors == []
    for hostile in (None, [], "x", {"schema_version": 2, "concepts": 3}):
        document, errors = checked_glossary(hostile)
        assert document is None
        assert errors == validate_glossary(hostile) and errors


def test_schema_literals_match_the_accepted_sets():
    """The ``Literal`` types in ``glossary.model`` and the runtime sets the
    validator enforces are one definition, never two drifting copies."""
    assert STATUSES == {
        "canonical", "proposed", "alias", "discouraged", "deprecated", "unknown"
    }
    assert BINDING_KINDS == {"symbol", "file", "module"}
