"""Reconciliation: every taxonomy category must fire on its seeded mismatch,
structural checks must skip cleanly without a graph, bindings must resolve
against stable identities only, and nothing assumes one community = one
concept."""

import json

from glossarize.cli import main
from glossarize.evidence import build_evidence
from glossarize.glossary import save_glossary, validate_glossary
from glossarize.reconcile import build_validation

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
    assert validation["graph"] == {
        "present": False,
        "usable": False,
        "freshness": None,
        "warnings": [],
    }
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
    monkeypatch.setattr("glossarize.reconcile.FINDINGS_CAP", 1)

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


def test_validate_command_end_to_end(tmp_path, capsys):
    root = make_repo(tmp_path)
    assert main(["validate", str(root)]) == 0
    out = capsys.readouterr().out
    assert "unnamed structure" in out
    assert "orphaned concepts" in out
    assert "freshness unverified" in out
    assert "No one-to-one" in out
    assert (root / "glossarize-out" / "validation.json").is_file()


def test_validate_without_glossary_is_user_error(tmp_path, capsys):
    (tmp_path / "a.py").write_text("x_y = 1\n")
    assert main(["validate", str(tmp_path)]) == 1
    assert "no glossary" in capsys.readouterr().err


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
