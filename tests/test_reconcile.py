"""Reconciliation: every taxonomy category must fire on its seeded mismatch,
structural checks must skip cleanly without a graph, bindings must resolve
against stable identities only, and nothing assumes one community = one
concept."""

import json
import os

import pytest

from glossabet.analysis.evidence import Limits, build_evidence
from glossabet.cli import main
from glossabet.glossary.matching import EvidenceIndex
from glossabet.glossary.reconcile import build_validation
from glossabet.glossary.store import save_glossary, validate_glossary

GLOSSARY = {
    "schema_version": 1,
    "concepts": [
        {
            "id": "payment", "term": "Payment", "status": "canonical",
            "definition": "An attempt to collect money.",
            "bindings": [
                {"ref": "symbol:payment_service"},
                {"ref": "symbol:GhostService"},  # seeded: unresolved
                {"ref": "module:pay"},
            ],
        },
        {
            "id": "workspace", "term": "Workspace", "status": "canonical",
            "definition": "A user's working area.",  # seeded: orphaned
        },
        {
            "id": "authentication", "term": "Authentication",
            "status": "canonical", "definition": "Proving who you are.",
        },
        {
            "id": "authorization", "term": "Authorization",
            "status": "canonical", "definition": "Deciding what you may do.",
        },
        {
            "id": "tenant", "term": "Tenant", "status": "canonical",
            "definition": "One customer's isolated slice.",  # seeded: fragmented
        },
        {
            "id": "run", "term": "Run", "status": "canonical",
            "definition": "A single pipeline invocation.",
        },
    ],
}

GRAPH = {
    "nodes": [
        # seeded boundary mismatch: one community mixing two canonical concepts
        {"id": 1, "label": "AuthenticationFlow", "community": 0},
        {"id": 2, "label": "AuthorizationPolicy", "community": 0},
        # seeded unnamed structure
        {"id": 3, "label": "LeaseManager", "community": 1},
        {"id": 4, "label": "SlotClaim", "community": 1},
        {"id": 5, "label": "ReaperWorker", "community": 1},
        {"id": 6, "label": "AllocationTable", "community": 1},
        {"id": 7, "label": "LeaseTimer", "community": 1},
        # seeded overloaded region: three canonical concepts in one community
        {"id": 8, "label": "PaymentFlow", "community": 2},
        {"id": 9, "label": "TenantMap", "community": 2},
        {"id": 10, "label": "RunLoop", "community": 2},
    ],
    "edges": [{"source": 3, "target": 4}],
}


def make_repo(tmp_path, graph=GRAPH):
    pay = tmp_path / "pay"
    pay.mkdir()
    (pay / "svc.py").write_text("payment_service = 1\npayment_total = 2\n")
    # tenant across 5 modules -> fragmentation
    for mod in ("a", "b", "c", "d", "e"):
        d = tmp_path / mod
        d.mkdir()
        (d / "code.py").write_text("tenant_slot = 1\n")
    # run vocabulary + a parallel execution vocabulary -> drift embed
    (tmp_path / "runs.py").write_text(
        "run_record = 1\nrun_scheduler = 2\nstart_run = 3\n"
    )
    (tmp_path / "execs.py").write_text(
        "execution_record = 1\nexecution_scheduler = 2\nstart_execution = 3\n"
    )
    if graph is not None:
        gout = tmp_path / "graphify-out"
        gout.mkdir()
        (gout / "graph.json").write_text(json.dumps(graph))
    save_glossary(tmp_path, GLOSSARY)
    return tmp_path


def validation_for(tmp_path, graph=GRAPH):
    root = make_repo(tmp_path, graph)
    return build_validation(build_evidence(root), GLOSSARY)


def test_unnamed_structure_detected(tmp_path):
    items = validation_for(tmp_path)["unnamed_structure"]["items"]
    finding = next(f for f in items if "community 1" in f["group"])
    assert finding["signal_strength"] == "strong"  # size 5
    assert "LeaseManager" in finding["evidence"]["members_sample"]


def test_boundary_mismatch_detected(tmp_path):
    items = validation_for(tmp_path)["boundary_mismatch"]["items"]
    pairs = {tuple(f["concepts"]) for f in items}
    assert ("authentication", "authorization") in pairs


def test_overloaded_region_detected(tmp_path):
    items = validation_for(tmp_path)["overloaded_structural_region"]["items"]
    finding = next(f for f in items if f["group"] == "community 2")
    assert set(finding["concepts"]) == {"payment", "run", "tenant"}


def test_orphaned_concept_detected(tmp_path):
    items = validation_for(tmp_path)["orphaned_concepts"]["items"]
    finding = next(f for f in items if f["concept_id"] == "workspace")
    assert finding["signal_strength"] == "strong"
    assert finding["evidence"]["token_counts"] == {"workspace": 0}


def test_compound_concept_is_not_satisfied_by_words_in_separate_units(tmp_path):
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "payment-request",
            "term": "Payment Request",
            "status": "canonical",
            "definition": "A request to collect payment.",
        }],
    }
    (tmp_path / "payment.py").write_text("payment_total = 1\n" * 4)
    (tmp_path / "request.py").write_text("request_queue = 1\n" * 4)

    validation = build_validation(build_evidence(tmp_path), glossary)

    finding = validation["orphaned_concepts"]["items"][0]
    assert finding["concept_id"] == "payment-request"
    assert finding["evidence"]["lexical_occurrences"] == 0


def test_unresolved_binding_is_drift_signal(tmp_path):
    items = validation_for(tmp_path)["unresolved_bindings"]["items"]
    finding = next(f for f in items if f["ref"] == "symbol:GhostService")
    assert "drift signal" in finding["summary"]
    # resolved bindings must NOT appear
    assert all(f["ref"] != "symbol:payment_service" for f in items)
    assert all(f["ref"] != "module:pay" for f in items)


def test_payment_with_resolved_bindings_is_not_orphaned(tmp_path):
    items = validation_for(tmp_path)["orphaned_concepts"]["items"]
    assert all(f["concept_id"] != "payment" for f in items)


def test_uncertain_symbol_binding_does_not_create_a_false_orphan(tmp_path):
    (tmp_path / "code.py").write_text(
        "popular_name = 1\npopular_name = 2\nrare_symbol = 3\n"
    )
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "unseen",
            "term": "Unseen",
            "definition": "A concept whose binding fell below the index cap.",
            "status": "canonical",
            "bindings": [{"ref": "symbol:rare_symbol"}],
        }],
    }
    evidence = build_evidence(tmp_path, limits=Limits(identifiers=1))

    validation = build_validation(evidence, glossary)

    assert validation["unresolved_bindings"]["items"] == []
    assert validation["orphaned_concepts"]["items"] == []
    assert validation["total_findings_complete"] is False


def test_partial_inventory_does_not_claim_missing_bindings_or_orphans(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("glossabet.corpus.walk_budget.MAX_SOURCE_FILES", 1)
    (tmp_path / "a.py").write_text("ordinary_name = 1\n")
    hidden = tmp_path / "z"
    hidden.mkdir()
    (hidden / "hidden.py").write_text("hidden_symbol = 1\n")
    glossary = {
        "schema_version": 1,
        "concepts": [
            {
                "id": kind,
                "term": f"Missing {kind.title()}",
                "definition": f"A concept bound by {kind}.",
                "status": "canonical",
                "bindings": [{"ref": ref}],
            }
            for kind, ref in (
                ("symbol", "symbol:hidden_symbol"),
                ("file", "file:z/hidden.py"),
                ("module", "module:z"),
            )
        ] + [
            # No bindings at all: the term lives only in the file the budget
            # cut. Nothing may call it orphaned on a partial corpus.
            {
                "id": "unbound", "term": "Hidden Symbol",
                "definition": "A concept with no bindings.",
                "status": "canonical",
            }
        ],
    }

    validation = build_validation(build_evidence(tmp_path), glossary)

    assert validation["unresolved_bindings"]["items"] == []
    assert validation["orphaned_concepts"]["items"] == []
    assert validation["coverage"]["production_corpus_complete"] is False
    assert validation["coverage"]["repository_corpus_complete"] is False
    collections = validation["coverage"]["collections"]
    assert collections["orphaned_concepts"]["total_items_exact"] is False
    # Every binding is merely uncertain here, and this ledger must say why.
    assert collections["unresolved_bindings"]["total_items_exact"] is False
    assert any(
        "inventory" in reason
        for reason in collections["unresolved_bindings"]["reasons"]
    ), collections["unresolved_bindings"]
    assert validation["total_findings_complete"] is False


def test_fragmentation_detected(tmp_path):
    items = validation_for(tmp_path)["fragmentation"]["items"]
    finding = next(f for f in items if f["concept_id"] == "tenant")
    assert finding["evidence"]["module_spread"] >= 5
    assert "cross-cutting" in finding["summary"]  # never a verdict


def test_drift_sections_embedded(tmp_path):
    validation = validation_for(tmp_path)
    drift_items = validation["vocabulary_drift"]["items"]
    assert any(f["new_term"] == "execution" for f in drift_items)
    assert "concept_collision" in validation


def test_without_graph_structural_checks_skip_cleanly(tmp_path):
    validation = validation_for(tmp_path, graph=None)
    assert validation["graph_available"] is False
    graph = validation["graph"]
    assert graph["present"] is False
    assert graph["usable"] is False
    assert graph["freshness"] is None
    assert graph["warnings"] == []
    assert graph["groups_dropped"] == 0
    assert graph["groups_complete"] is None
    assert graph["coverage"]["complete"] is True
    for key in ("unnamed_structure", "boundary_mismatch",
                "overloaded_structural_region"):
        assert validation[key]["skipped"] is True
        assert validation[key]["items"] == []
        assert "absent" in validation[key]["skip_reason"]
    # direction B still works
    assert validation["orphaned_concepts"]["items"]


def test_present_but_unusable_graph_skips_structural_checks(tmp_path):
    graph = {"nodes": [{"id": "a", "label": "A"}], "links": []}
    validation = validation_for(tmp_path, graph=graph)

    assert validation["graph"]["present"] is True
    assert validation["graph"]["usable"] is False
    assert validation["graph"]["warnings"]
    for key in ("unnamed_structure", "boundary_mismatch",
                "overloaded_structural_region"):
        assert validation[key]["skipped"] is True
        assert "no usable structural groups" in validation[key]["skip_reason"]


def test_usable_graph_with_no_canonical_concepts_finds_unnamed_structure(
    tmp_path,
):
    graph = {
        "nodes": [
            {"id": "a", "label": "LeaseManager", "community": 0},
            {"id": "b", "label": "SlotClaim", "community": 0},
        ],
        "edges": [{"source": "a", "target": "b"}],
    }
    root = tmp_path
    (root / "main.py").write_text("ordinary_name = 1\n")
    gout = root / "graphify-out"
    gout.mkdir()
    (gout / "graph.json").write_text(json.dumps(graph))

    validation = build_validation(
        build_evidence(root), {"schema_version": 1, "concepts": []}
    )

    assert len(validation["unnamed_structure"]["items"]) == 1
    assert validation["unnamed_structure"]["items"][0]["group"] == "community 0"


def test_graph_group_cap_makes_structural_validation_explicitly_partial(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("glossabet.analysis.graphify_groups.GROUP_CAP", 2)
    graph = {
        "nodes": [
            {"id": f"{group}-{member}", "label": f"Node{group}{member}",
             "community": group}
            for group in range(3)
            for member in range(2)
        ],
        "edges": [],
    }
    (tmp_path / "main.py").write_text("ordinary_name = 1\n")
    gout = tmp_path / "graphify-out"
    gout.mkdir()
    (gout / "graph.json").write_text(json.dumps(graph))

    validation = build_validation(
        build_evidence(tmp_path), {"schema_version": 1, "concepts": []}
    )

    assert validation["total_findings"] == 2
    assert validation["total_findings_complete"] is False
    assert validation["graph"]["groups_dropped"] == 1
    assert validation["graph"]["groups_complete"] is False
    assert validation["unnamed_structure"]["partial"] is True
    assert "group cap" in validation["unnamed_structure"]["partial_reason"]


def test_binding_validation_rejects_unstable_identities():
    glossary = json.loads(json.dumps(GLOSSARY))
    glossary["concepts"][0]["bindings"].append({"ref": "community:7"})
    errors = validate_glossary(glossary)
    assert any("not stable" in e for e in errors)


def test_validation_is_deterministic_and_bounded(tmp_path):
    root = make_repo(tmp_path)
    first = build_validation(build_evidence(root), GLOSSARY)
    second = build_validation(build_evidence(root), GLOSSARY)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    for key in ("unnamed_structure", "orphaned_concepts", "fragmentation"):
        assert "dropped_items" in first[key]


def test_validation_findings_do_not_claim_uncalibrated_confidence(tmp_path):
    validation = validation_for(tmp_path)
    for key in (
        "unnamed_structure",
        "boundary_mismatch",
        "overloaded_structural_region",
        "orphaned_concepts",
        "unresolved_bindings",
        "fragmentation",
        "vocabulary_drift",
        "concept_collision",
    ):
        for finding in validation[key]["items"]:
            assert "confidence" not in finding
            assert ("certainty" in finding) != ("signal_strength" in finding)


def test_validation_total_includes_dropped_items(tmp_path, monkeypatch):
    glossary = {
        "schema_version": 1,
        "concepts": [
            {
                "id": term,
                "term": term.title(),
                "status": "canonical",
                "definition": f"The {term} concept.",
            }
            for term in ("alpha", "beta", "gamma")
        ],
    }
    (tmp_path / "main.py").write_text("ordinary_name = 1\n")
    monkeypatch.setattr("glossabet.glossary.findings.FINDINGS_CAP", 1)

    validation = build_validation(build_evidence(tmp_path), glossary)

    assert len(validation["orphaned_concepts"]["items"]) == 1
    assert validation["orphaned_concepts"]["dropped_items"] == 2
    assert validation["total_findings"] == 3


def test_scoped_concepts_round_trip_through_lexical_validation(tmp_path):
    glossary = {
        "schema_version": 1,
        "concepts": [
            {
                "id": "auth-session",
                "term": "Session",
                "definition": "An authenticated interaction.",
                "status": "canonical",
                "scope": {"path_prefixes": ["auth"]},
            },
            {
                "id": "db-session",
                "term": "Session",
                "definition": "A database unit of work.",
                "status": "canonical",
                "scope": {"path_prefixes": ["db"]},
            },
        ],
    }
    for subsystem, contexts in (
        ("auth", ("cookie", "login", "user")),
        ("db", ("commit", "query", "transaction")),
    ):
        directory = tmp_path / subsystem
        directory.mkdir()
        directory.joinpath("session.py").write_text(
            "\n".join(f"session_{context} = 1" for context in contexts) + "\n"
        )

    validation = build_validation(build_evidence(tmp_path), glossary)

    assert validation["orphaned_concepts"]["items"] == []
    assert validation["scope_summary"] == {
        "repository": 0,
        "path_scoped": 2,
        "structural_scope_complete": False,
    }


def test_binding_that_resolves_only_outside_scope_is_reported(tmp_path):
    auth = tmp_path / "auth"
    db = tmp_path / "db"
    auth.mkdir()
    db.mkdir()
    auth.joinpath("account.py").write_text(
        "account_user = 1\naccount_login = 2\naccount_cookie = 3\n"
    )
    db.joinpath("session.py").write_text("db_session = 1\n")
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "auth-account",
            "term": "Account",
            "definition": "An authenticated identity.",
            "status": "canonical",
            "scope": {"path_prefixes": ["auth"]},
            "bindings": [{"ref": "symbol:db_session"}],
        }],
    }

    validation = build_validation(build_evidence(tmp_path), glossary)
    finding = validation["unresolved_bindings"]["items"][0]

    assert finding["kind"] == "binding-out-of-scope"
    assert finding["binding_status"] == "out-of-scope"
    assert "outside the concept scope" in finding["summary"]


def test_non_ascii_concept_round_trips_through_validation(tmp_path):
    payments = tmp_path / "payments"
    payments.mkdir()
    payments.joinpath("service.py").write_text(
        "支付Service = 1\n支付Gateway = 2\ncreate支付 = 3\n",
        encoding="utf-8",
    )
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "payment",
            "term": "支付",
            "definition": "Collecting money for an order.",
            "status": "canonical",
            "scope": {"path_prefixes": ["payments"]},
        }],
    }

    validation = build_validation(build_evidence(tmp_path), glossary)

    assert validation["orphaned_concepts"]["items"] == []
    assert validation["vocabulary_drift"]["items"] == []


def test_structural_scope_limit_is_explicit_instead_of_guessing(tmp_path):
    graph = {
        "nodes": [
            {"id": 1, "label": "SessionCookie", "community": 0},
            {"id": 2, "label": "SessionLogin", "community": 0},
        ],
        "edges": [],
    }
    gout = tmp_path / "graphify-out"
    gout.mkdir()
    gout.joinpath("graph.json").write_text(json.dumps(graph))
    auth = tmp_path / "auth"
    auth.mkdir()
    auth.joinpath("session.py").write_text(
        "session_cookie = 1\nsession_login = 2\nsession_user = 3\n"
    )
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "auth-session",
            "term": "Session",
            "definition": "An authenticated interaction.",
            "status": "canonical",
            "scope": {"path_prefixes": ["auth"]},
        }],
    }

    validation = build_validation(build_evidence(tmp_path), glossary)

    assert validation["unnamed_structure"]["skipped"] is True
    assert "do not carry repository paths" in validation["unnamed_structure"][
        "skip_reason"
    ]
    assert validation["boundary_mismatch"]["partial"] is True


def test_seventh_graph_member_participates_in_structural_matching(tmp_path):
    graph = {
        "nodes": [
            {"id": index, "label": f"Alpha{index}", "community": 0}
            for index in range(6)
        ] + [{"id": 7, "label": "PaymentGateway", "community": 0}],
        "edges": [],
    }
    (tmp_path / "main.py").write_text("payment_record = 1\n")
    gout = tmp_path / "graphify-out"
    gout.mkdir()
    gout.joinpath("graph.json").write_text(json.dumps(graph))
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "payment",
            "term": "Payment",
            "definition": "An attempt to collect money.",
            "status": "canonical",
        }],
    }

    evidence = build_evidence(tmp_path)
    group = evidence["structural_groups"]["groups"][0]
    validation = build_validation(evidence, glossary)

    assert "PaymentGateway" not in group["members_sample"]
    assert "payment" in group["member_tokens"]
    assert group["coverage"]["member_tokens"]["complete"] is True
    assert validation["unnamed_structure"]["items"] == []


def test_structural_matching_uses_inverted_token_candidates(
    tmp_path, monkeypatch
):
    graph = {
        "nodes": [
            {
                "id": index,
                "label": f"Structure{index}",
                "community": index,
            }
            for index in range(30)
        ],
        "edges": [],
    }
    (tmp_path / "main.py").write_text("ordinary_name = 1\n")
    gout = tmp_path / "graphify-out"
    gout.mkdir()
    gout.joinpath("graph.json").write_text(json.dumps(graph))
    glossary = {
        "schema_version": 1,
        "concepts": [
            {
                "id": f"concept-{index}",
                "term": f"Concept{index}",
                "definition": "A deliberately unrelated concept.",
                "status": "canonical",
            }
            for index in range(200)
        ],
    }
    calls = 0
    from glossabet.glossary import structural_validation as reconcile_module
    real_match = reconcile_module._match_strength_from_tokens

    def counted_match(*args):
        nonlocal calls
        calls += 1
        return real_match(*args)

    monkeypatch.setattr(
        reconcile_module, "_match_strength_from_tokens", counted_match
    )

    validation = build_validation(build_evidence(tmp_path), glossary)

    assert calls == 0
    work = validation["coverage"]["work"]["structural_matches"]
    assert work["total_items"] == 0
    assert work["complete"] is True


def test_structural_match_budget_reports_omitted_candidate_evaluations(
    tmp_path, monkeypatch
):
    terms = ("Alpha", "Beta", "Gamma", "Delta", "Epsilon")
    graph = {
        "nodes": [{
            "id": "all",
            "label": "AlphaBetaGammaDeltaEpsilon",
            "community": 0,
        }],
        "edges": [],
    }
    (tmp_path / "main.py").write_text("ordinary_name = 1\n")
    gout = tmp_path / "graphify-out"
    gout.mkdir()
    gout.joinpath("graph.json").write_text(json.dumps(graph))
    glossary = {
        "schema_version": 1,
        "concepts": [
            {
                "id": term.lower(), "term": term,
                "definition": f"The {term} concept.", "status": "canonical",
            }
            for term in terms
        ],
    }
    # Patch the owning module: the facade's re-export is a separate name.
    monkeypatch.setattr(
        "glossabet.glossary.structural_validation.STRUCTURAL_MATCH_BUDGET", 2
    )

    validation = build_validation(build_evidence(tmp_path), glossary)
    work = validation["coverage"]["work"]["structural_matches"]

    assert work["total_items"] == 5
    assert work["included_items"] == 2
    assert work["dropped_items"] == 3
    assert work["complete"] is False
    assert validation["boundary_mismatch"]["coverage"][
        "total_items_exact"
    ] is False
    assert validation["total_findings_complete"] is False


def test_boundary_pair_total_is_counted_while_only_details_are_retained(
    tmp_path,
):
    concept_count = 300
    graph = {
        "nodes": [{"id": "shared", "label": "Shared", "community": 0}],
        "edges": [],
    }
    (tmp_path / "main.py").write_text("shared_value = 1\n")
    gout = tmp_path / "graphify-out"
    gout.mkdir()
    gout.joinpath("graph.json").write_text(json.dumps(graph))
    glossary = {
        "schema_version": 1,
        "concepts": [
            {
                "id": f"shared-{index}", "term": "Shared",
                "definition": "One deliberately duplicated test concept.",
                "status": "canonical",
            }
            for index in range(concept_count)
        ],
    }

    boundary = build_validation(build_evidence(tmp_path), glossary)[
        "boundary_mismatch"
    ]
    expected = concept_count * (concept_count - 1) // 2

    assert len(boundary["items"]) == 10
    assert boundary["coverage"]["total_items"] == expected
    assert boundary["coverage"]["dropped_items"] == expected - 10
    assert boundary["coverage"]["total_items_exact"] is True


def test_validate_command_end_to_end(tmp_path, capsys):
    root = make_repo(tmp_path)
    assert main(["validate", str(root)]) == 0
    out = capsys.readouterr().out
    assert "unnamed structure" in out
    assert "orphaned concepts" in out
    assert "freshness unverified" in out
    assert "No one-to-one" in out
    assert (root / "glossabet-out" / "validation.json").is_file()


def test_validate_cli_surfaces_adapter_warning_and_skipped_coverage(
    tmp_path, capsys
):
    root = make_repo(
        tmp_path,
        graph={"nodes": [{"id": "a", "label": "A"}], "links": []},
    )
    assert main(["validate", str(root)]) == 0
    captured = capsys.readouterr()
    assert "graph present but no usable structural groups" in captured.out
    assert "structural checks skipped" in captured.out
    assert "graphify adapter:" in captured.err
    assert "no community structure" in captured.err


def test_scoped_sampled_fragmentation_is_confessed(tmp_path):
    # Five lib files crowd the token's 5-slot location sample; the scoped
    # concept's module spread is computed from that clipped sample, so the
    # below-threshold result must be confessed, not silently complete.
    for index in range(5):
        (tmp_path / f"lib{index}.py").write_text(
            "widget_handle = 1\n" * (50 - index)
        )
    auth = tmp_path / "auth"
    auth.mkdir()
    (auth / "a.py").write_text("account_handle = 1\n")
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "auth-handle",
            "term": "handle",
            "definition": "d",
            "status": "canonical",
            "scope": {"path_prefixes": ["auth"]},
        }],
    }
    evidence = build_evidence(tmp_path)
    validation = build_validation(evidence, glossary)

    ledger = validation["fragmentation"]["coverage"]
    assert ledger["complete"] is False
    assert any("location sample" in reason for reason in ledger["reasons"])


def test_clip_only_compound_spread_is_not_reported_as_sampled(tmp_path):
    # Six files in one module using a compound term: the display sample
    # clips to five locations but the module count is exact, so nothing
    # was suppressed and the ledger must stay complete.
    src = tmp_path / "src"
    src.mkdir()
    for index in range(6):
        (src / f"f{index}.py").write_text("payment_request = 1\n")
    # The concept is SCOPED (the guard reads `scope is not None and
    # match_kind == "token" and locations_truncated`): only a scoped compound
    # reaches the match-kind branch this test exists to pin — an unscoped one
    # short-circuits before it and proves nothing about compounds.
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "pr",
            "term": "Payment Request",
            "definition": "d",
            "status": "canonical",
            "scope": {"path_prefixes": ["src"]},
        }],
    }
    evidence = build_evidence(tmp_path)
    validation = build_validation(evidence, glossary)

    ledger = validation["fragmentation"]["coverage"]
    assert ledger["complete"] is True
    assert ledger["reasons"] == []
    # And the single-token sibling in the same scope IS suppressed when its
    # entry-level location sample was clipped: the guard fires for tokens.
    for index in range(6, 12):
        (tmp_path / "src" / f"f{index}.py").write_text("payment = 1\n")
    glossary["concepts"][0]["term"] = "Payment"
    from glossabet.analysis.evidence import Limits
    evidence = build_evidence(tmp_path, Limits(locations_per_term=2))
    ledger = build_validation(evidence, glossary)["fragmentation"]["coverage"]
    assert ledger["complete"] is False
    assert any("suppressed" in reason for reason in ledger["reasons"])


@pytest.mark.parametrize("disk_form,typed_form", [("NFD", "NFC"), ("NFC", "NFD")])
def test_paths_match_scopes_and_bindings_across_unicode_forms(
    tmp_path, disk_form, typed_form
):
    """macOS reports decomposed directory names and authors paste either
    form (a name copied from `ls` on macOS is NFD); whichever side is
    composed, a scope or file binding must still match, or a real concept
    reads as 'absent from code' and its binding as 'no longer resolves'."""
    import unicodedata

    on_disk = unicodedata.normalize(disk_form, "café")
    typed = unicodedata.normalize(typed_form, "café")
    assert on_disk != typed
    (tmp_path / on_disk).mkdir()
    (tmp_path / on_disk / "latte.py").write_text("class CafeLatte:\n    pass\n")
    glossary = {"schema_version": 1, "concepts": [{
        "id": "cafe", "term": "Cafe", "definition": "d", "status": "canonical",
        "scope": {"path_prefixes": [typed]},
        "bindings": [{"ref": f"file:{typed}/latte.py"}, {"ref": "symbol:CafeLatte"},
                     {"ref": f"module:{typed}"}],
    }]}
    evidence = build_evidence(tmp_path)
    validation = build_validation(evidence, glossary)
    assert validation["unresolved_bindings"]["items"] == []
    assert validation["orphaned_concepts"]["items"] == []
    occurrence = EvidenceIndex(evidence, ["Cafe"]).code_term_occurrence(
        "Cafe", (typed,)
    )
    assert occurrence["count"] == 1 and occurrence["count_complete"] is True


def test_only_canonical_concepts_are_judged_for_orphans_and_bindings(tmp_path):
    """Proposed and deprecated concepts are not settled vocabulary: an absent
    proposed term is not "orphaned" and its dangling binding is not a drift
    signal — those findings would push a human toward treating a proposal
    as a decision. Watched terms keep their own drift section."""
    (tmp_path / "app.py").write_text("payment_service = 1\n")
    glossary = {
        "schema_version": 1,
        "concepts": [
            {"id": "payment", "term": "Payment", "definition": "d",
             "status": "canonical", "bindings": [{"ref": "symbol:payment_service"}]},
            {"id": "ledger", "term": "Ledger", "definition": "d",
             "status": "proposed", "bindings": [{"ref": "symbol:GhostLedger"}]},
            {"id": "voucher", "term": "Voucher", "definition": "d",
             "status": "deprecated", "bindings": [{"ref": "file:missing.py"}]},
        ],
    }
    assert validate_glossary(glossary) == []
    validation = build_validation(build_evidence(tmp_path), glossary)
    assert validation["orphaned_concepts"]["items"] == []
    assert validation["unresolved_bindings"]["items"] == []
    # Flip the proposal to canonical: now it is judged, and both fire.
    glossary["concepts"][1]["status"] = "canonical"
    judged = build_validation(build_evidence(tmp_path), glossary)
    assert [f["concept_id"] for f in judged["orphaned_concepts"]["items"]] == ["ledger"]
    assert [f["ref"] for f in judged["unresolved_bindings"]["items"]] == [
        "symbol:GhostLedger"
    ]


def test_bindings_into_paths_the_scan_excluded_are_uncertain_not_unresolved(tmp_path):
    """A `file:`/`module:` binding pointing under a vendored, generated,
    configured-ignore, or sensitive path names something the scan chose not
    to read: it may well exist, so it is `uncertain` (and counted in the
    ledger reason), never the "no longer resolves — drift signal" finding
    a deleted file earns. A binding to a path nowhere on disk stays
    unresolved; a binding to an inventoried file stays resolved. (R1.)"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "core.py").write_text("core_value = 1\n")
    (tmp_path / "vendor" / "lib").mkdir(parents=True)
    (tmp_path / "vendor" / "lib" / "dep.py").write_text("dep_value = 1\n")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "out.py").write_text("out_value = 1\n")
    (tmp_path / "scratch").mkdir()
    (tmp_path / "scratch" / "notes.py").write_text("notes_value = 1\n")
    (tmp_path / ".env").write_text("SECRET=1\n")
    os.symlink(
        tmp_path.anchor,
        tmp_path / "rootlink",
        target_is_directory=True,
    )  # escaping link: in the scan's ledger
    (tmp_path / "glossabet.json").write_text(json.dumps(
        {"schema_version": 1, "ignore_paths": ["scratch"]}
    ))
    glossary = {"schema_version": 1, "concepts": [{
        "id": "core", "term": "Core", "definition": "d", "status": "canonical",
        "bindings": [
            {"ref": "file:src/core.py"},              # resolved
            {"ref": "file:vendor/lib/dep.py"},        # vendored: uncertain
            {"ref": "module:vendor/lib"},             # vendored: uncertain
            {"ref": "file:build/out.py"},             # generated: uncertain
            {"ref": "file:scratch/notes.py"},         # configured ignore: uncertain
            {"ref": "file:.env"},                     # sensitive: uncertain
            {"ref": "file:src/gone.py"},              # nowhere: unresolved
        ],
    }]}
    assert validate_glossary(glossary) == []
    evidence = build_evidence(tmp_path)
    assert evidence["skipped"]["corpus_budget"]["complete"] is True
    from glossabet.glossary.binding_validation import _resolve_bindings

    statuses = {
        b["ref"]: b["status"]
        for b in _resolve_bindings(glossary["concepts"][0], EvidenceIndex(evidence, ["Core"]))
    }
    assert statuses == {
        "file:src/core.py": "resolved",
        "file:vendor/lib/dep.py": "uncertain",
        "module:vendor/lib": "uncertain",
        "file:build/out.py": "uncertain",
        "file:scratch/notes.py": "uncertain",
        "file:.env": "uncertain",
        "file:src/gone.py": "unresolved",
    }
    validation = build_validation(evidence, glossary)
    assert [f["ref"] for f in validation["unresolved_bindings"]["items"]] == ["file:src/gone.py"]
    ledger = validation["coverage"]["collections"]["unresolved_bindings"]
    assert ledger["total_items_exact"] is False
    assert any("5 binding(s) name paths the scan did not read" in r for r in ledger["reasons"])
    # And a concept whose only bindings are excluded is not orphaned on that
    # account (uncertain bindings shield it, as under a partial corpus).
    assert validation["orphaned_concepts"]["items"] == []

    # With the repository root available (the `validate` command has it), a
    # binding to a real file the inventory never lists — not a code or doc
    # extension — is uncertain too; a hostile binding cannot probe outside
    # the root (absolute, `..`, or a link escaping it read as absent).
    (tmp_path / "Makefile").write_text("all:\n\ttrue\n")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.toml").write_text("[x]\n")
    glossary["concepts"][0]["bindings"] = [
        {"ref": "file:Makefile"}, {"ref": "file:config/settings.toml"},
        {"ref": "module:config"}, {"ref": "file:src/gone.py"},
        {"ref": "file:../outside"}, {"ref": "file:/etc/hosts"},
        {"ref": "file:rootlink/etc"},
    ]
    from glossabet.glossary.binding_validation import _exists_confined

    # The escaping link is in the scan's own omission ledger (uncertain by
    # that rule); the disk probe itself must still refuse to follow it.
    assert _exists_confined(tmp_path, "rootlink/etc") is False
    assert _exists_confined(tmp_path, "../outside") is False
    assert _exists_confined(tmp_path, "/etc/hosts") is False
    assert _exists_confined(tmp_path, "Makefile") is True
    with_root = build_validation(evidence, glossary, root=tmp_path)
    assert sorted(f["ref"] for f in with_root["unresolved_bindings"]["items"]) == [
        "file:../outside", "file:/etc/hosts", "file:src/gone.py",
    ]
    without_root = build_validation(evidence, glossary)
    assert len(without_root["unresolved_bindings"]["items"]) == 6  # rootlink/etc: ledger
    # And through the CLI, which passes the root.
    save_glossary(tmp_path, glossary)
    assert main(["validate", str(tmp_path)]) == 0
    written = json.loads((tmp_path / "glossabet-out" / "validation.json").read_text())
    assert sorted(f["ref"] for f in written["unresolved_bindings"]["items"]) == [
        "file:../outside", "file:/etc/hosts", "file:src/gone.py",
    ]
