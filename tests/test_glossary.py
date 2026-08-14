"""Persistent glossary: round-trip fidelity, validation that rejects the
states drift detection depends on being impossible, deterministic writes,
and the show command."""

import json

import pytest

from glossarize.cli import main
from glossarize.glossary import (
    GlossaryError,
    load_glossary,
    save_glossary,
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
