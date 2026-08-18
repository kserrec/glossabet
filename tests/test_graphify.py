"""Graphify adapter: recognized shapes map to structural groups, glossary
provenance is discounted everywhere, unknown shapes degrade gracefully, the
escape hatch works, and graphify's own artifacts never leak into the
lexical walk."""

import json
import os

from glossabet.cli import main
from glossabet.analysis.evidence import build_evidence, write_evidence
from glossabet.analysis.graphify import build_structural_groups

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
    monkeypatch.setattr("glossabet.analysis.graphify.GROUP_CAP", 2)
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
    monkeypatch.setattr("glossabet.runtime.artifacts.MAX_JSON_BYTES", 100)
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
    # json.dumps emits the bare NaN token by default, matching a hostile
    # or odd graph.json on disk.
    (root / "graphify-out" / "graph.json").write_text(json.dumps(graph))
    structural = build_structural_groups(
        root, {"head": "a" * 40, "dirty": False}
    )

    assert [group["cohesion"] for group in structural["groups"]] == [None, None]
    assert "NaN" not in json.dumps(structural)


def test_fallback_communities_shape_tolerates_duplicates_empties_and_report_nodes(tmp_path):
    """The explicit ``communities`` list is a set of sets: duplicate member
    ids do not inflate a group, two entries with one id are one community,
    an empty ``links`` list falls through to a legacy ``edges`` list, an
    empty ``label`` falls through to ``name``/``id``, and a node sourced from
    the root GLOSSABET.md report is glossary provenance (discounted)."""
    graph = {
        "nodes": [
            {"id": "n1", "label": "", "name": "Alpha", "source_file": "a.py"},
            {"id": "n2", "label": "Beta", "source_file": "b.py"},
            {"id": "n3", "label": "Gamma", "source_file": "c.py"},
            {"id": "n4", "label": "ReportWord", "source_file": "GLOSSABET.md"},
        ],
        "links": [],
        "edges": [{"source": "n1", "target": "n2"}],
        "communities": [
            {"id": 0, "nodes": ["n1", "n1", "n1", "n2"]},
            {"id": 0, "nodes": ["n3", "n4"]},
        ],
    }
    root = make_repo(tmp_path, graph)
    structural = build_structural_groups(root, {"head": None, "dirty": None})

    assert structural["edges"] == 1
    assert structural["discounted_glossary_nodes"] == 1
    groups = {g["id"]: g for g in structural["groups"]}
    assert list(groups) == ["0"]
    group = groups["0"]
    assert group["size"] == 3  # n1, n2, n3 once each; the report node discounted
    assert sorted(group["members_sample"]) == ["Alpha", "Beta", "Gamma"]
    assert group["provenance"] == {"code": 3, "doc": 0, "glossary": 1}


def test_astronomical_cohesion_and_giant_labels_degrade_instead_of_crashing(tmp_path):
    """A JSON integer beyond float range used to make math.isfinite raise
    (exit 2); a finite-but-huge float made the derived score `inf` and the
    evidence unwritable; a 1 MB label ballooned the artifact. Cohesion is
    usable only within a stated bound; labels and member-token sets are
    capped with their own ledgers."""
    huge_label = "L" * 5000
    graph = {
        "nodes": [
            {"id": "n1", "label": "Alpha", "source_file": "a.py"},
            {"id": "n2", "label": huge_label, "source_file": "b.py"},
            {"id": "n3", "label": "Gamma", "source_file": "c.py"},
        ],
        "edges": [],
        "communities": [
            {"id": 0, "nodes": ["n1", "n2"], "cohesion": 10 ** 400},
            {"id": 1, "nodes": ["n3"], "cohesion": 1e308, "label": huge_label},
        ],
    }
    root = make_repo(tmp_path, graph)
    evidence = build_evidence(root)  # must serialize: allow_nan=False downstream
    write_evidence(root, evidence)
    groups = {g["id"]: g for g in evidence["structural_groups"]["groups"]}
    assert groups["0"]["cohesion"] is None and groups["1"]["cohesion"] is None
    assert len(groups["1"]["label"]) == 512 and groups["1"]["label_truncated"] is True
    assert groups["0"]["label_truncated"] is False
    for candidate in evidence["naming_candidates"]["structures"]:
        assert candidate["score"] < 10 ** 6
    assert all(
        len(label) <= 512 for g in groups.values() for label in g["members_sample"]
    )


def test_graph_input_work_is_bounded_before_any_member_is_materialized(tmp_path, monkeypatch):
    """A hostile graph under the size cap can list communities × members in
    the millions; the adapter used to stringify, sort, and tokenize every
    pair (1.3 GB, 30 s) before its output caps applied. The reference count
    is judged from list lengths first; over budget, the graph is present but
    unusable and the run stays lexical-only — quickly."""
    graph = {
        "nodes": [{"id": i, "label": f"n{i}", "source_file": "a.py"} for i in range(1000)],
        "edges": [],
        "communities": [
            {"id": c, "nodes": list(range(1000))} for c in range(1100)
        ],
    }
    root = make_repo(tmp_path, graph)
    # "Before any member is materialized" is proven structurally: the
    # community materializer must not run at all when the budget is exceeded.
    from glossabet.analysis import graphify as graphify_module

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("communities were materialized over budget")

    monkeypatch.setattr(graphify_module, "_groups_from_communities", must_not_run)
    structural = build_structural_groups(root, {"head": None, "dirty": None})
    monkeypatch.undo()
    assert structural["present"] is True
    assert structural["available"] is False
    assert any("work budget" in w for w in structural["warnings"])
    # A graph just under the budget still loads.
    graph["communities"] = graph["communities"][:900]
    (root / "graphify-out" / "graph.json").write_text(json.dumps(graph))
    assert build_structural_groups(root, {"head": None, "dirty": None})["available"] is True


def test_graph_label_tokenizing_is_budgeted_and_memoized(tmp_path, monkeypatch):
    """Under the reference budget a graph could still cost minutes: every
    community re-tokenized each member's 512-char label. Labels are
    tokenized once per node and the total label characters are budgeted."""
    label = " ".join(f"tok{i}" for i in range(80))[:512]
    nodes = [{"id": f"n{i}", "label": label + str(i)} for i in range(1000)]
    communities = [
        {"id": f"c{j}", "nodes": [f"n{i}" for i in range(1000)]} for j in range(300)
    ]
    root = make_repo(tmp_path, {"nodes": nodes, "edges": [], "communities": communities})
    # Memoization is proven by counting: 1000 distinct labels listed in 300
    # communities must be tokenized 1000 times, not 300,000 (a wall-clock
    # bound alone would be runner-dependent and burn a minute when it fails).
    from glossabet.analysis import graphify as graphify_module

    calls = []
    real_tokenize = graphify_module.tokenize_term
    monkeypatch.setattr(
        graphify_module, "tokenize_term",
        lambda label: calls.append(label) or real_tokenize(label),
    )
    structural = build_structural_groups(root, {"head": None, "dirty": None})
    assert structural["available"] is True
    assert len(calls) == 1000

    # Over the label-character budget: refused before any tokenizing at all.
    many = [{"id": f"n{i}", "label": "x" * 512} for i in range(10_000)]
    (root / "graphify-out" / "graph.json").write_text(json.dumps({
        "nodes": many, "edges": [],
        "communities": [{"id": 0, "nodes": [f"n{i}" for i in range(10_000)]}],
    }))
    calls.clear()
    structural = build_structural_groups(root, {"head": None, "dirty": None})
    assert structural["available"] is False
    assert any("tokenizing budget" in w for w in structural["warnings"])
    assert calls == []


def test_member_token_cap_is_stated_and_the_first_tokens_survive(tmp_path):
    """A community with more distinct member tokens than the cap keeps a
    bounded, sorted prefix and a ledger that says how many were dropped and
    why — never a silently trimmed list that reconciliation would read as
    the whole community. At the cap, complete."""
    from glossabet.analysis.graphify import MEMBER_TOKEN_CAP

    def graph_with(token_count):
        return {
            "nodes": [
                {"id": i, "label": f"tok{i:05d}", "community": 0}
                for i in range(token_count)
            ],
        }

    root = make_repo(tmp_path, graph_with(MEMBER_TOKEN_CAP))
    (group,) = build_structural_groups(root, {"head": None, "dirty": None})["groups"]
    assert len(group["member_tokens"]) == MEMBER_TOKEN_CAP
    assert group["coverage"]["member_tokens"]["complete"] is True

    (tmp_path / "graphify-out" / "graph.json").write_text(
        json.dumps(graph_with(MEMBER_TOKEN_CAP + 5))
    )
    (group,) = build_structural_groups(root, {"head": None, "dirty": None})["groups"]
    ledger = group["coverage"]["member_tokens"]
    assert len(group["member_tokens"]) == MEMBER_TOKEN_CAP
    assert group["member_tokens"] == sorted(group["member_tokens"])
    assert group["member_tokens"][0] == "tok00000"
    assert ledger["complete"] is False
    assert ledger["total_items"] == MEMBER_TOKEN_CAP + 5
    assert ledger["dropped_items"] == 5
    assert any(str(MEMBER_TOKEN_CAP) in reason for reason in ledger["reasons"])


def test_hostile_graph_family_degrades_deterministically_never_raises(tmp_path):
    """Seeded family of hostile graphify-out/graph.json documents (junk
    types, NaN/inf/astronomical cohesion, lone surrogates and RLO in labels,
    self-referential ids, provenance paths pointing at the glossary or the
    report, six stamp shapes): the adapter must produce the same
    NaN-clean structural section twice, and evidence, validation, and
    drift built on it must serialize — graph problems warn and fall back to
    lexical evidence, never exit 2. Ported from a hunter that failed
    against the pre-fix adapter in under a second (OverflowError)."""
    import random

    from glossabet.analysis.graphify import structure_candidates
    from glossabet.glossary.drift import build_drift
    from glossabet.glossary.reconcile import build_validation

    glossary = {"schema_version": 1, "concepts": [
        {"id": "payment", "term": "Payment Service", "definition": "d",
         "status": "canonical",
         "aliases": [{"term": "Stripe Gateway", "status": "alias"}],
         "bindings": [{"ref": "symbol:payment_service"}]},
        {"id": "billing", "term": "Billing", "definition": "d", "status": "canonical"},
        {"id": "old", "term": "Ledger", "definition": "d", "status": "deprecated"},
    ]}
    weird = [
        None, True, False, 0, 1, -1, 7, 1.5, -0.0, float("nan"), float("inf"),
        -float("inf"), 10 ** 400, 10 ** 300, 1e308, 1.7e307, -1e308, 2 ** 63,
        "", " ", "a", "n1", "n2", "0", "1", "PaymentService", "K", "ﬁ", "K",
        "İ", "\u202e", "\x00", "\x1b[31m", "x" * 5000,
        "glossabet-out/glossary.json", "GLOSSARY.md", "docs/a.md", "src/x.py",
        "../../etc", "glossary", "doc", "code", "\ud800",
    ]
    stamps = [
        {"head": "a" * 40, "dirty": False}, {"head": "a" * 40, "dirty": True},
        {"head": None, "dirty": None}, {"head": "b" * 40, "dirty": False},
        None, {"head": 5, "dirty": "x"},
    ]
    rng = random.Random(20260818)

    def scalar():
        return rng.choice(weird)

    def junk(depth=0):
        r = rng.random()
        if depth > 3 or r < 0.5:
            return scalar()
        if r < 0.75:
            return [junk(depth + 1) for _ in range(rng.randint(0, 4))]
        return {
            (str(scalar()) if rng.random() < 0.5 else rng.choice(
                ["id", "label", "name", "nodes", "source", "target", "community",
                 "cohesion", "file_type", "type", "source_file"])): junk(depth + 1)
            for _ in range(rng.randint(0, 4))
        }

    def maybe(value):
        return value if rng.random() < 0.8 else junk()

    def node(index):
        entry = {}
        if rng.random() < 0.9:
            entry[rng.choice(["id", "name", "id"])] = maybe(rng.choice([f"n{index}", index, str(index)]))
        if rng.random() < 0.8:
            entry["label"] = maybe(rng.choice([f"Label{index}", "", f"Payment Service {index}", "Billing"]))
        if rng.random() < 0.5:
            entry["community"] = maybe(rng.randint(0, 3))
        if rng.random() < 0.3:
            entry["community_name"] = maybe(rng.choice(["Payments", "Billing", ""]))
        if rng.random() < 0.5:
            entry[rng.choice(["source_file", "source", "file", "path", "origin"])] = maybe(rng.choice([
                "src/x.py", "docs/a.md", "GLOSSARY.md", "glossabet-out/g.json",
                "./glossabet-out/../src/x.py", "glossarize-out\\x", "GLOSSABET.md",
                "", " ", "K.md",
            ]))
        if rng.random() < 0.3:
            entry[rng.choice(["file_type", "type", "kind"])] = maybe(rng.choice([
                "code", "doc", "glossary", "Glossary ", "ｇlossary", "markdown", "document",
            ]))
        if rng.random() < 0.1:
            entry[str(junk())] = junk()
        return entry if rng.random() < 0.92 else junk()

    def edge(ids):
        entry = {}
        if rng.random() < 0.9:
            entry[rng.choice(["source", "from", "a"])] = maybe(rng.choice(ids) if ids else "z")
        if rng.random() < 0.9:
            entry[rng.choice(["target", "to", "b"])] = maybe(rng.choice(ids) if ids else "z")
        return entry if rng.random() < 0.92 else junk()

    def community(ids, index):
        entry = {}
        if rng.random() < 0.8:
            entry[rng.choice(["id", "label", "name"])] = maybe(rng.choice([index, str(index), f"c{index}", 0, "Billing", ""]))
        if rng.random() < 0.5:
            entry["label"] = maybe(rng.choice(["Payments", "", "Billing"]))
        if rng.random() < 0.9:
            entry["nodes"] = maybe([maybe(rng.choice(ids)) if ids else junk() for _ in range(rng.randint(0, 6))])
        if rng.random() < 0.6:
            entry["cohesion"] = maybe(rng.choice([0.5, 0.83, 1, 0, -1, 2 ** 70, 10 ** 400, 1e308, 1e-320, float("nan"), True]))
        return entry if rng.random() < 0.92 else junk()

    def graph():
        doc = {}
        nodes = [node(i) for i in range(rng.choice([0, 1, 2, 3, 5, 10, 60]))]
        ids = [
            str(item.get("id", item.get("name"))) for item in nodes
            if isinstance(item, dict) and (item.get("id") is not None or item.get("name") is not None)
        ]
        if rng.random() < 0.95:
            doc["nodes"] = nodes if rng.random() < 0.9 else junk()
        if rng.random() < 0.8:
            doc[rng.choice(["links", "edges"])] = maybe([edge(ids) for _ in range(rng.randint(0, 12))])
        if rng.random() < 0.3:
            doc["edges"] = maybe([edge(ids) for _ in range(rng.randint(0, 5))])
        if rng.random() < 0.5:
            doc["communities"] = maybe([community(ids, i) for i in range(rng.randint(0, 5))])
        if rng.random() < 0.6:
            doc["built_at_commit"] = maybe(rng.choice(["a" * 40, "a" * 7, "A" * 40, " a" * 3, "b" * 40, "abc"]))
        if rng.random() < 0.2:
            doc[str(junk())] = junk()
        return (doc if rng.random() < 0.97 else junk()), rng.choice(stamps)

    root = tmp_path
    (root / "src").mkdir()
    (root / "src" / "payment.py").write_text(
        "payment_service = 1\nclass StripeGateway: pass\nbilling_guide=2\n"
    )
    (root / "docs").mkdir()
    (root / "docs" / "billing.md").write_text(
        "# Billing\nThe payment service talks to the stripe gateway.\n"
    )
    (root / "graphify-out").mkdir()
    dumped = 0
    for case in range(150):
        document, stamp = graph()
        try:
            text = json.dumps(document)  # bare NaN and lone surrogates: what a hostile file holds
        except (ValueError, TypeError):
            continue
        dumped += 1
        (root / "graphify-out" / "graph.json").write_text(
            text, encoding="utf-8", errors="surrogatepass"
        )
        first = build_structural_groups(root, stamp)
        second = build_structural_groups(root, stamp)
        assert (
            json.dumps(first, sort_keys=True, allow_nan=False)
            == json.dumps(second, sort_keys=True, allow_nan=False)
        ), f"case {case}: nondeterministic"
        structure_candidates(first)
        evidence = build_evidence(root)
        json.dumps(evidence, sort_keys=True, allow_nan=False)
        json.dumps(build_validation(evidence, glossary), sort_keys=True, allow_nan=False)
        json.dumps(build_drift(evidence, glossary), sort_keys=True, allow_nan=False)
    assert dumped >= 100
