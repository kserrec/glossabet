"""Persistent glossary: round-trip fidelity, validation that rejects the
states drift detection depends on being impossible, deterministic writes,
and the show command."""

import json
import os

import pytest

from glossarize.cli import main
from glossarize.glossary import (
    GlossaryError,
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
    first = save_glossary(tmp_path, GLOSSARY).read_text()
    second = save_glossary(tmp_path, GLOSSARY).read_text()
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
    saved = json.loads(path.read_text())
    payment = next(c for c in saved["concepts"] if c["id"] == "payment")
    assert payment["scope"]["path_prefixes"] == [
        "packages/payments", "src/payments"
    ]
    assert main(["show", str(tmp_path)]) == 0
    assert "scope: packages/payments, src/payments" in capsys.readouterr().out


def test_load_raises_on_corrupt_file(tmp_path):
    out = tmp_path / "glossarize-out"
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
    out = tmp_path / "glossarize-out"
    out.mkdir()
    (out / "glossary.json").write_text('{"schema_version": 7, "concepts": []}')
    assert main(["show", str(tmp_path)]) == 1
    assert "schema_version" in capsys.readouterr().err


def test_glossary_never_contaminates_evidence(tmp_path):
    from glossarize.evidence import build_evidence

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
    out = tmp_path / "glossarize-out"
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
    out = tmp_path / "glossarize-out"
    out.mkdir()
    (out / "glossary.json").write_text(json.dumps(glossary))
    assert main(["show", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "status" in captured.err
    assert "internal error" not in captured.err.lower()


def test_oversized_glossary_refused_as_user_error(tmp_path, monkeypatch):
    monkeypatch.setattr("glossarize.glossary.MAX_JSON_BYTES", 50)
    monkeypatch.setattr("glossarize.artifacts.MAX_JSON_BYTES", 50)
    out = tmp_path / "glossarize-out"
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
    out = tmp_path / "glossarize-out"
    out.mkdir()
    (out / "glossary.json").write_text("[" * 60000 + "]" * 60000)
    with pytest.raises(GlossaryError):  # not an uncaught RecursionError
        load_glossary(tmp_path)
    assert main(["show", str(tmp_path)]) == 1


def test_wrong_top_level_glossary_json_is_clean_error(tmp_path, capsys):
    out = tmp_path / "glossarize-out"
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
    out = repo / "glossarize-out"
    out.mkdir(parents=True)
    os.symlink(outside, out / "glossary.json")

    with pytest.raises(GlossaryError, match="symlinked artifact"):
        load_glossary(repo)
