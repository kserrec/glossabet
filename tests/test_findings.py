"""glossabet.findings: the finding record, capped section, evidence-omission
derivation, and section renderer that drift and validation share."""

import pytest

from glossabet.glossary.findings import (
    empty_section,
    FindingsDocumentView,
    FINDINGS_CAP,
    capped_section,
    collection_limitations,
    finding,
    mark_incomplete,
    print_sections,
    vocabulary_omission_reasons,
)


def test_finding_requires_exactly_one_epistemic_status():
    observed = finding("k", "s", {"count": 1}, certainty="observed")
    assert observed["certainty"] == "observed" and "signal_strength" not in observed
    heuristic = finding("k", "s", {"x": 1}, signal_strength="weak", concept_id="c")
    assert heuristic["signal_strength"] == "weak" and heuristic["concept_id"] == "c"
    with pytest.raises(ValueError):
        finding("k", "s", {})
    with pytest.raises(ValueError):
        finding("k", "s", {}, certainty="observed", signal_strength="weak")
    # Evidence is optional (binding findings carry none); scope only when given.
    bare = finding("k", "s", certainty="observed")
    assert "evidence" not in bare and "scope" not in bare


def test_capped_section_reports_the_cap_and_keeps_totals_honest():
    items = [{"kind": "k", "certainty": "observed", "summary": str(i)} for i in range(FINDINGS_CAP + 2)]
    section = capped_section(items, "demo", incomplete_reasons=[])
    assert len(section["items"]) == FINDINGS_CAP
    assert section["dropped_items"] == 2
    assert section["coverage"]["total_items_exact"] is True
    assert section["coverage"]["reasons"] == [
        f"demo finding detail cap is {FINDINGS_CAP} items"
    ]
    # An upstream omission makes the total inexact and is reported first.
    partial = capped_section(items[:1], "demo", incomplete_reasons=["upstream cut"])
    assert partial["coverage"]["total_items_exact"] is False
    assert partial["coverage"]["reasons"] == ["upstream cut"]
    # A known-larger total is honoured without inventing detail.
    known = capped_section(items[:1], "demo", incomplete_reasons=[], total_items=5)
    assert known["dropped_items"] == 4
    assert known["coverage"]["reasons"] == [
        f"demo finding detail cap is {FINDINGS_CAP} items"
    ]
    # A skipped or scope-limited check is an empty section with its reason.
    skipped = empty_section("no graph")
    assert skipped == {
        "items": [], "dropped_items": 0,
        "coverage": {"total_items": 0, "included_items": 0, "dropped_items": 0,
                     "total_items_exact": True, "complete": False,
                     "reasons": ["no graph"]},
    }
    assert empty_section("scoped", total_items_exact=False)["coverage"][
        "total_items_exact"] is False
    marked = mark_incomplete(section, "scope limited")
    assert marked["coverage"]["total_items_exact"] is False
    assert marked["coverage"]["reasons"][-1] == "scope limited"


def test_evidence_omissions_and_limitations_are_derived_in_one_place():
    evidence = {"vocabulary": {
        "tokens": {"truncated": {"dropped_terms": 3}},
        "identifiers": {"truncated": None},
        "doc_terms": {"truncated": None},
    }}
    assert vocabulary_omission_reasons(
        evidence, ("tokens", "identifiers", "doc_terms")
    ) == ["vocabulary.tokens omitted entries needed for exact matching"]
    assert vocabulary_omission_reasons(
        evidence, ("tokens",), "vocabulary.{name} cut"
    ) == ["vocabulary.tokens cut"]
    collections = {
        "a": {"total_items_exact": False, "reasons": ["r1", "r2"]},
        "b": {"total_items_exact": True, "reasons": ["ignored"]},
        "c": {"total_items_exact": False, "reasons": ["r2", "r3"]},
    }
    assert collection_limitations(collections) == ["r1", "r2", "r3"]
    assert collection_limitations(collections, skip=lambda k: k == "c") == ["r1", "r2"]


def test_renderer_prints_every_branch_from_a_hand_built_document(capsys):
    document = {
        "one": {
            "items": [
                finding(
                    "k", "line\x1b[31m one", {
                        "shared_contexts": ["ctx"],
                        "locations": [{"path": "a.py"}, {"path": "b.py"}],
                        "modules": [{"path": "m"}],
                    },
                    signal_strength="strong",
                    scope={"kind": "path-prefixes", "path_prefixes": ["src"]},
                ),
            ],
            "dropped_items": 2,
        },
        "empty": {"items": [], "dropped_items": 0},
        "skipped": {"items": [finding("k", "x", certainty="observed")], "skipped": True},
    }
    titles = {"one": "first", "empty": "second", "skipped": "third"}
    print_sections(FindingsDocumentView(document), titles, detail=True)
    out = capsys.readouterr().out
    assert out == (
        "\n== first ==\n"
        "line\\x1b[31m one [signal strong]\n"
        "    scope: src\n"
        "    shared contexts: ctx\n"
        "    e.g. a.py, b.py\n"
        "    modules: m\n"
        "... and 2 more not shown\n"
    )
    print_sections(FindingsDocumentView(document), titles, detail=False)
    assert capsys.readouterr().out == (
        "\n== first ==\nline\\x1b[31m one [signal strong]\n... and 2 more not shown\n"
    )
