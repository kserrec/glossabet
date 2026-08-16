"""Graphify adapter: recognized shapes map to structural groups, glossary
provenance is discounted everywhere, unknown shapes degrade gracefully, the
escape hatch works, and graphify's own artifacts never leak into the
lexical walk."""

import json
import os

from glossabet.cli import main
from glossabet.evidence import build_evidence
from glossabet.graphify import build_structural_groups

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
         "source": "glossabet-out/glossary.json"},
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

# Produced from Graphify 0.9.42's graphify.export.to_json contract. NetworkX's
# node-link exporter writes `links`; Graphify supplies `source_file`,
# `file_type`, per-node community metadata, and `built_at_commit`.
GRAPHIFY_0_9_42 = {
    "built_at_commit": "a" * 40,
    "directed": True,
    "graph": {},
    "hyperedges": [],
    "links": [
        {
            "source": "n1", "target": "n2", "relation": "calls",
            "confidence": "EXTRACTED", "confidence_score": 1.0,
        },
        {
            "source": "n1", "target": "n3", "relation": "references",
            "confidence": "EXTRACTED", "confidence_score": 1.0,
        },
    ],
    "multigraph": False,
    "nodes": [
        {
            "id": "n1", "label": "Payment Service",
            "source_file": "src/payment.py", "file_type": "code",
            "community": 7, "community_name": "Payments",
            "norm_label": "payment service",
        },
        {
            "id": "n2", "label": "Stripe Gateway",
            "source_file": "src/gateway.py", "file_type": "code",
            "community": 7, "community_name": "Payments",
            "norm_label": "stripe gateway",
        },
        {
            "id": "n3", "label": "Billing Guide",
            "source_file": "docs/billing.md", "file_type": "document",
            "community": 7, "community_name": "Payments",
            "norm_label": "billing guide",
        },
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
    assert structural["nodes"] == 5
    assert structural["source_nodes"] == 6
    assert structural["edges"] == 3
    assert structural["discounted_glossary_nodes"] == 1
    groups = {g["id"]: g for g in structural["groups"]}
    g0 = groups["0"]
    assert g0["size"] == 3
    assert "Payment" not in g0["members_sample"]
    assert g0["provenance"] == {"code": 2, "doc": 1, "glossary": 1}
    assert g0["members_sample"][0] == "PaymentService"  # highest degree first
    # God nodes exclude glossary provenance too.
    assert all(g["label"] != "Payment" for g in structural["god_nodes"])
    assert structural["god_nodes"][0]["label"] == "PaymentService"


def test_graphify_0_9_42_export_contract_is_consumed(tmp_path):
    root = make_repo(tmp_path, GRAPHIFY_0_9_42)
    structural = build_structural_groups(
        root, {"head": "a" * 40, "dirty": False}
    )

    assert structural["present"] is True
    assert structural["available"] is True
    assert structural["nodes"] == 3 and structural["edges"] == 2
    assert len(structural["groups"]) == 1
    group = structural["groups"][0]
    assert group["id"] == "7" and group["label"] == "Payments"
    assert group["cohesion"] is None and group["size"] == 3
    assert group["members_sample"] == [
        "Payment Service", "Billing Guide", "Stripe Gateway"
    ]
    assert group["member_tokens"] == [
        "billing", "gateway", "guide", "payment", "service", "stripe"
    ]
    assert group["coverage"]["member_tokens"]["complete"] is True
    assert group["provenance"] == {"code": 2, "doc": 1, "glossary": 0}
    assert structural["god_nodes"][0] == {
        "label": "Payment Service", "degree": 2
    }
    assert structural["freshness"]["status"] == "current"


def test_glossary_only_groups_are_not_usable_structure(tmp_path):
    graph = {
        "nodes": [
            {
                "id": "g1", "label": "Payment", "community": 0,
                "source": "glossabet-out/glossary.json",
            },
            {
                "id": "g2", "label": "Billing", "community": 0,
                "source": "GLOSSARY.md",
            },
        ],
        "edges": [{"source": "g1", "target": "g2"}],
    }

    evidence = build_evidence(make_repo(tmp_path, graph))
    structural = evidence["structural_groups"]

    assert structural["source_nodes"] == 2
    assert structural["nodes"] == 0
    assert structural["edges"] == 0
    assert structural["groups"] == []
    assert structural["available"] is False
    assert evidence["naming_candidates"]["structures"] == []


def test_group_cap_marks_structure_nominations_partial(tmp_path, monkeypatch):
    monkeypatch.setattr("glossabet.graphify.GROUP_CAP", 2)
    graph = {
        "nodes": [
            {"id": f"{group}-{member}", "label": f"Node{group}{member}",
             "community": group}
            for group in range(3)
            for member in range(2)
        ],
        "edges": [],
    }

    evidence = build_evidence(make_repo(tmp_path, graph))
    structural = evidence["structural_groups"]
    naming = evidence["naming_candidates"]

    assert len(structural["groups"]) == 2
    assert structural["groups_dropped"] == 1
    assert structural["groups_complete"] is False
    assert structural["coverage"]["groups"]["total_items"] == 3
    assert structural["coverage"]["groups"]["dropped_items"] == 1
    assert naming["structures_source_groups_dropped"] == 1
    assert naming["structures_dropped"] == 1
    assert naming["structures_complete"] is False


def test_default_group_cap_has_exact_threshold_coverage(tmp_path):
    graph = {
        "nodes": [
            {"id": index, "label": f"Group{index}", "community": index}
            for index in range(51)
        ],
        "edges": [],
    }

    structural = build_evidence(make_repo(tmp_path, graph))["structural_groups"]
    coverage = structural["coverage"]["groups"]

    assert len(structural["groups"]) == 50
    assert coverage["total_items"] == 51
    assert coverage["included_items"] == 50
    assert coverage["dropped_items"] == 1
    assert coverage["complete"] is False


def test_structure_candidate_detail_cap_marks_collection_partial(tmp_path):
    graph = {
        "nodes": [
            {
                "id": f"{group}-{member}",
                "label": f"Node{group}{member}",
                "community": group,
            }
            for group in range(11)
            for member in range(2)
        ],
        "edges": [],
    }

    naming = build_evidence(make_repo(tmp_path, graph))["naming_candidates"]
    coverage = naming["coverage"]["structures"]

    assert len(naming["structures"]) == 10
    assert naming["structures_dropped"] == 1
    assert naming["structures_source_groups_dropped"] == 0
    assert naming["structures_complete"] is False
    assert coverage["total_items"] == 11
    assert coverage["included_items"] == 10
    assert coverage["complete"] is False


def test_provenance_requires_exact_normalized_source_or_type(tmp_path):
    graph = {
        "nodes": [
            {
                "id": "near-dir", "label": "Near Output", "community": 0,
                "source_file": "src/glossabet-output.py",
            },
            {
                "id": "near-name", "label": "Near Glossary", "community": 0,
                "source_file": "docs/NOT_GLOSSARY.md",
            },
            {
                "id": "normalized-away", "label": "Escaped Output",
                "community": 0,
                "source_file": "glossabet-out/../src/value.py",
            },
            {
                "id": "real-file", "label": "Real Glossary", "community": 0,
                "source_file": "GLOSSARY.md",
            },
            {
                "id": "real-dir", "label": "Glossary JSON", "community": 0,
                "source_file": "glossabet-out/glossary.json",
            },
            {
                "id": "pre-rename-dir", "label": "Old Glossary JSON",
                "community": 0,
                "source_file": "glossarize-out/glossary.json",
            },
            {
                "id": "real-type", "label": "Typed Glossary", "community": 0,
                "source_file": "generated/value", "file_type": "glossary",
            },
        ],
        "edges": [],
    }

    group = build_evidence(make_repo(tmp_path, graph))["structural_groups"][
        "groups"
    ][0]

    assert group["provenance"] == {"code": 2, "doc": 1, "glossary": 4}
    assert group["size"] == 3
    assert set(group["members_sample"]) == {
        "Escaped Output", "Near Output", "Near Glossary"
    }


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
    assert structural["present"] is True
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
    assert structural["adapter_enabled"] is False
    assert structural["present"] is None
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
    first = capsys.readouterr().out
    assert "structural group(s)" in first
    assert "freshness unverified" in first
    assert main(["scan", str(root), "--no-graphify"]) == 0
    assert "structural group(s)" not in capsys.readouterr().out


def test_adapter_is_deterministic(tmp_path):
    root = make_repo(tmp_path)
    first = build_evidence(root)["structural_groups"]
    second = build_evidence(root)["structural_groups"]
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_analyze_report_prints_structure_candidates(tmp_path, capsys):
    root = make_repo(tmp_path)
    assert main(["analyze", str(root)]) == 0
    out = capsys.readouterr().out
    assert "structure community 0 — " in out
    assert "members include PaymentService" in out


def test_malformed_community_nodes_degrade_gracefully(tmp_path):
    # A community whose "nodes" is not a list used to crash the whole scan;
    # the adapter's contract is warn-and-degrade, never error.
    graph = {
        "nodes": [{"id": "a", "label": "A"}],
        "communities": [{"id": "c1", "nodes": 5}],
    }
    structural = build_evidence(make_repo(tmp_path, graph))["structural_groups"]
    assert structural["present"] is True
    assert structural["available"] is False
    assert structural["groups"] == []
    assert any("no community structure" in w for w in structural["warnings"])


def test_community_id_zero_keeps_its_id(tmp_path):
    graph = {
        "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        "communities": [
            {"id": "billing", "nodes": ["a"]},
            {"id": 0, "nodes": ["b"]},
        ],
    }
    structural = build_evidence(make_repo(tmp_path, graph))["structural_groups"]
    assert {g["id"] for g in structural["groups"]} == {"billing", "0"}


def test_oversized_graph_degrades_lexical_only(tmp_path, monkeypatch):
    import glossabet.graphify as gmod
    monkeypatch.setattr(gmod, "MAX_JSON_BYTES", 100)
    monkeypatch.setattr("glossabet.artifacts.MAX_JSON_BYTES", 100)
    graph = {"nodes": [{"id": "a", "label": "A"} for _ in range(50)]}
    structural = build_evidence(make_repo(tmp_path, graph))["structural_groups"]
    assert structural["available"] is False
    assert any("larger than" in w for w in structural["warnings"])


def test_symlinked_graph_degrades_without_reading_target(tmp_path):
    outside = tmp_path / "outside-graph.json"
    outside.write_text(json.dumps(GRAPH))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("ordinary_identifier = 1\n")
    gout = repo / "graphify-out"
    gout.mkdir()
    os.symlink(outside, gout / "graph.json")

    structural = build_evidence(repo)["structural_groups"]
    assert structural["present"] is True
    assert structural["available"] is False
    assert any("symlinked artifact" in warning
               for warning in structural["warnings"])


def test_graph_freshness_distinguishes_stale_and_dirty(tmp_path):
    root = make_repo(tmp_path, GRAPHIFY_0_9_42)
    stale = build_structural_groups(
        root, {"head": "b" * 40, "dirty": False}
    )["freshness"]
    dirty = build_structural_groups(
        root, {"head": "a" * 40, "dirty": True}
    )["freshness"]

    assert stale["status"] == "stale"
    assert "current HEAD" in stale["detail"]
    assert dirty["status"] == "unverified"
    assert "uncommitted changes" in dirty["detail"]


def test_scan_cli_surfaces_unusable_graph_warning(tmp_path, capsys):
    root = make_repo(tmp_path, {"nodes": [{"id": "only"}], "links": []})
    assert main(["scan", str(root)]) == 0
    captured = capsys.readouterr()
    assert "present, but no usable structural groups" in captured.out
    assert "no community structure" in captured.err


def test_non_finite_and_bool_cohesion_never_enter_artifacts(tmp_path):
    graph = {
        "nodes": [
            {"id": "a", "label": "Payment Service", "file_type": "code"},
            {"id": "b", "label": "Billing Guide", "file_type": "doc"},
        ],
        "links": [],
        "communities": [
            {"id": 1, "label": "Payments", "cohesion": float("nan"),
             "nodes": ["a"]},
            {"id": 2, "label": "Billing", "cohesion": True, "nodes": ["b"]},
        ],
    }
    root = make_repo(tmp_path, None)
    # json.loads accepts the bare NaN token, matching a hostile or odd
    # graph.json on disk.
    (root / "graphify-out" / "graph.json").write_text(
        json.dumps(graph).replace("NaN", "NaN")
    )
    structural = build_structural_groups(
        root, {"head": "a" * 40, "dirty": False}
    )

    assert [group["cohesion"] for group in structural["groups"]] == [None, None]
    assert "NaN" not in json.dumps(structural)
