"""Reconciliation: every taxonomy category must fire on its seeded mismatch,
structural checks must skip cleanly without a graph, bindings must resolve
against stable identities only, and nothing assumes one community = one
concept."""

import json

from glossabet.cli import main
from glossabet.analysis.evidence import Limits, build_evidence
from glossabet.glossary.store import save_glossary, validate_glossary
from glossabet.glossary.reconcile import build_validation

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
    monkeypatch.setattr("glossabet.corpus.scanner.MAX_SOURCE_FILES", 1)
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
        ],
    }

    validation = build_validation(build_evidence(tmp_path), glossary)

    assert validation["unresolved_bindings"]["items"] == []
    assert validation["orphaned_concepts"]["items"] == []
    assert validation["coverage"]["production_corpus_complete"] is False
    assert validation["coverage"]["repository_corpus_complete"] is False
    assert validation["coverage"]["collections"]["orphaned_concepts"][
        "total_items_exact"
    ] is False
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
    from glossabet.glossary import reconcile as reconcile_module
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
    monkeypatch.setattr("glossabet.glossary.reconcile.STRUCTURAL_MATCH_BUDGET", 2)

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
    # Six single-module files using a compound term: the display sample
    # clips to five locations but the module count is exact, so nothing
    # was suppressed and the ledger must stay complete.
    src = tmp_path / "src"
    src.mkdir()
    for index in range(6):
        (src / f"f{index}.py").write_text("payment_request = 1\n")
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "pr",
            "term": "Payment Request",
            "definition": "d",
            "status": "canonical",
        }],
    }
    evidence = build_evidence(tmp_path)
    validation = build_validation(evidence, glossary)

    ledger = validation["fragmentation"]["coverage"]
    assert ledger["complete"] is True
    assert ledger["reasons"] == []
