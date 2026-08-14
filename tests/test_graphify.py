"""Graphify adapter: recognized shapes map to structural groups, glossary
provenance is discounted everywhere, unknown shapes degrade gracefully, the
escape hatch works, and graphify's own artifacts never leak into the
lexical walk."""

import json

from glossarize.cli import main
from glossarize.evidence import build_evidence

GRAPH = {
    "directed": True,
    "nodes": [
        {"id": "n1", "label": "PaymentService", "community": 0,
         "source": "src/payment.py"},
        {"id": "n2", "label": "StripeGateway", "community": 0,
         "source": "src/gateway.py"},
        {"id": "n3", "label": "billing guide", "community": 0,
         "source": "docs/billing.md"},
        {"id": "n4", "label": "Payment", "community": 0,
         "source": "glossarize-out/glossary.json"},
        {"id": "n5", "label": "Parser", "community": 1,
         "source": "src/parser.py"},
        {"id": "n6", "label": "Lexer", "community": 1,
         "source": "src/lexer.py"},
    ],
    "edges": [
        {"source": "n1", "target": "n2"},
        {"source": "n1", "target": "n3"},
        {"source": "n1", "target": "n4"},
        {"source": "n5", "target": "n6"},
    ],
}


def make_repo(tmp_path, graph=GRAPH):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "payment.py").write_text("payment_service = 1\n")
    gout = tmp_path / "graphify-out"
    gout.mkdir()
    if graph is not None:
        (gout / "graph.json").write_text(json.dumps(graph))
    (gout / "GRAPH_REPORT.md").write_text(
        "graphreportword appears only in graphify output\n"
    )
    return tmp_path


def test_groups_map_with_provenance_and_discounting(tmp_path):
    structural = build_evidence(make_repo(tmp_path))["structural_groups"]
    assert structural["available"] is True
    assert structural["nodes"] == 6
    assert structural["discounted_glossary_nodes"] == 1
    groups = {g["id"]: g for g in structural["groups"]}
    g0 = groups["0"]
    assert g0["size"] == 4  # glossary node counted in size...
    assert "Payment" not in g0["members_sample"]  # ...but never shown
    assert g0["provenance"] == {"code": 2, "doc": 1, "glossary": 1}
    assert g0["members_sample"][0] == "PaymentService"  # highest degree first
    # God nodes exclude glossary provenance too.
    assert all(g["label"] != "Payment" for g in structural["god_nodes"])
    assert structural["god_nodes"][0]["label"] == "PaymentService"


def test_top_level_communities_variant_with_cohesion(tmp_path):
    graph = {
        "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        "edges": [{"source": "a", "target": "b"}],
        "communities": [
            {"id": "billing", "label": "Billing", "cohesion": 0.83,
             "nodes": ["a", "b"]},
        ],
    }
    structural = build_evidence(make_repo(tmp_path, graph))["structural_groups"]
    group = structural["groups"][0]
    assert group["label"] == "Billing" and group["cohesion"] == 0.83


def test_structure_naming_candidates_carry_reasons(tmp_path):
    naming = build_evidence(make_repo(tmp_path))["naming_candidates"]
    assert naming["structures"], "structure candidates expected"
    top = naming["structures"][0]
    assert top["kind"] == "structure"
    assert any("community of" in r for r in top["reasons"])
    assert "structures_dropped" in naming


def test_unrecognized_shape_degrades_with_warning(tmp_path):
    structural = build_evidence(
        make_repo(tmp_path, graph={"weird": True})
    )["structural_groups"]
    assert structural["available"] is False
    assert any("no recognizable node list" in w for w in structural["warnings"])


def test_corrupt_graph_degrades_with_warning(tmp_path):
    root = make_repo(tmp_path, graph=None)
    (root / "graphify-out" / "graph.json").write_text("{broken")
    structural = build_evidence(root)["structural_groups"]
    assert structural["available"] is False
    assert any("unreadable" in w for w in structural["warnings"])


def test_no_graphify_escape_hatch(tmp_path):
    root = make_repo(tmp_path)
    structural = build_evidence(root, graphify=False)["structural_groups"]
    assert structural["available"] is False and structural["warnings"] == []


def test_with_and_without_graph_stay_compatible(tmp_path):
    root = make_repo(tmp_path)
    with_graph = build_evidence(root)
    without = build_evidence(root, graphify=False)
    # Lexical evidence identical; only the structural section differs.
    assert with_graph["vocabulary"] == without["vocabulary"]
    assert with_graph["structural_groups"]["available"] is True
    assert without["structural_groups"]["available"] is False


def test_graphify_output_never_enters_lexical_walk(tmp_path):
    blob = json.dumps(build_evidence(make_repo(tmp_path)))
    assert "graphreportword" not in blob


def test_scan_cli_reports_graph_and_flag_disables(tmp_path, capsys):
    root = make_repo(tmp_path)
    assert main(["scan", str(root)]) == 0
    assert "structural group(s)" in capsys.readouterr().out
    assert main(["scan", str(root), "--no-graphify"]) == 0
    assert "structural group(s)" not in capsys.readouterr().out


def test_adapter_is_deterministic(tmp_path):
    root = make_repo(tmp_path)
    first = build_evidence(root)["structural_groups"]
    second = build_evidence(root)["structural_groups"]
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
