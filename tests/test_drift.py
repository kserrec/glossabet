"""Drift detection: the seeded scenario from the plan — a concept renamed in
new code must be caught with correct evidence — plus the other three checks,
bounds, determinism, and the no-glossary path."""

import json

from glossarize.cli import main
from glossarize.drift import build_drift
from glossarize.evidence import Limits, build_evidence
from glossarize.glossary import save_glossary
from glossarize.matching import EvidenceIndex

GLOSSARY = {
    "schema_version": 1,
    "concepts": [
        {
            "id": "run",
            "term": "Run",
            "definition": "A single invocation of the pipeline.",
            "status": "canonical",
            "aliases": [
                {"term": "charge", "status": "discouraged",
                 "note": "wrong domain, never adopted"},
            ],
        },
        {
            "id": "workspace",
            "term": "Workspace",
            "definition": "A user's working area.",
            "status": "canonical",
        },
        {
            "id": "session",
            "term": "Session",
            "definition": "One connected interaction.",
            "status": "canonical",
        },
    ],
}


def make_repo(tmp_path):
    # Established vocabulary: run_* (canonical Run).
    (tmp_path / "runs.py").write_text(
        "run_record = 1\nrun_scheduler = 2\nstart_run = 3\nrun_record_id = 4\n"
    )
    # Seeded drift: new code says execution_* for the same shapes.
    (tmp_path / "exec_new.py").write_text(
        "execution_record = 1\nexecution_scheduler = 2\nstart_execution = 3\n"
    )
    # Discouraged term still spreading.
    (tmp_path / "gateway.py").write_text(
        "charge_request = 1\ncharge_total = 2\n"
    )
    # Canonical "Session" living three disjoint lives.
    for module, contexts in (
        ("auth", ["login", "cookie"]),
        ("db", ["transaction", "commit"]),
        ("ml", ["inference", "model"]),
    ):
        d = tmp_path / module
        d.mkdir()
        (d / "code.py").write_text(
            "\n".join(f"session_{c} = 1" for c in contexts) + "\n"
        )
    # "Workspace" appears nowhere: canonical-fading.
    save_glossary(tmp_path, GLOSSARY)
    return tmp_path


def drift_for(tmp_path):
    root = make_repo(tmp_path)
    return build_drift(build_evidence(root), GLOSSARY)


def test_seeded_rename_is_detected_with_evidence(tmp_path):
    parallel = drift_for(tmp_path)["parallel_terms"]["items"]
    finding = next(f for f in parallel if f["new_term"] == "execution")
    assert finding["canonical_term"] == "Run"
    assert finding["concept_id"] == "run"
    assert "record" in finding["evidence"]["shared_contexts"]
    assert finding["signal_strength"] in ("strong", "moderate")


def test_discouraged_term_in_use(tmp_path):
    in_use = drift_for(tmp_path)["watched_terms_in_use"]["items"]
    finding = next(f for f in in_use if f["term"] == "charge")
    assert finding["status"] == "discouraged"
    assert finding["evidence"]["count"] == 2
    assert finding["evidence"]["locations"][0]["path"] == "gateway.py"


def test_compound_watched_term_requires_one_lexical_unit(tmp_path):
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "request",
            "term": "Request",
            "definition": "A submitted operation.",
            "status": "canonical",
            "aliases": [{
                "term": "Payment Request",
                "status": "discouraged",
            }],
        }],
    }
    (tmp_path / "payment.py").write_text("payment_total = 1\n" * 3)
    (tmp_path / "request.py").write_text("request_queue = 1\n" * 3)

    drift = build_drift(build_evidence(tmp_path), glossary)

    assert drift["watched_terms_in_use"]["items"] == []


def test_compound_watched_term_reports_a_real_identifier_unit(tmp_path):
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "request",
            "term": "Request",
            "definition": "A submitted operation.",
            "status": "canonical",
            "aliases": [{
                "term": "Payment Request",
                "status": "discouraged",
            }],
        }],
    }
    (tmp_path / "payment.py").write_text("payment_request = 1\n")

    drift = build_drift(build_evidence(tmp_path), glossary)
    finding = drift["watched_terms_in_use"]["items"][0]

    assert finding["term"] == "Payment Request"
    assert finding["evidence"]["match_kind"] == "lexical-unit"
    assert finding["certainty"] == "observed"
    assert "confidence" not in finding


def test_canonical_fading(tmp_path):
    fading = drift_for(tmp_path)["canonical_fading"]["items"]
    finding = next(f for f in fading if f["term"] == "Workspace")
    assert finding["signal_strength"] == "strong"
    assert finding["evidence"]["token_counts"] == {"workspace": 0}


def test_canonical_overloaded(tmp_path):
    over = drift_for(tmp_path)["canonical_overloaded"]["items"]
    finding = next(f for f in over if f["term"] == "Session")
    assert len(finding["evidence"]["modules"]) >= 3


def test_terms_already_in_glossary_are_not_parallel_findings(tmp_path):
    # "charge" parallels nothing as a *new* term — it's a known alias and
    # belongs to the watched check, not the parallel check.
    parallel = drift_for(tmp_path)["parallel_terms"]["items"]
    assert all(f["new_term"] != "charge" for f in parallel)


def test_bounds_and_determinism(tmp_path):
    root = make_repo(tmp_path)
    first = build_drift(build_evidence(root), GLOSSARY)
    second = build_drift(build_evidence(root), GLOSSARY)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    for key in ("parallel_terms", "watched_terms_in_use",
                "canonical_fading", "canonical_overloaded"):
        assert "dropped_items" in first[key]


def test_findings_use_observation_or_signal_strength_not_confidence(tmp_path):
    drift = drift_for(tmp_path)
    for key in (
        "parallel_terms",
        "watched_terms_in_use",
        "canonical_fading",
        "canonical_overloaded",
    ):
        for finding in drift[key]["items"]:
            assert "confidence" not in finding
            assert ("certainty" in finding) != ("signal_strength" in finding)


def test_total_findings_includes_dropped_items(tmp_path, monkeypatch):
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "terms",
            "term": "Current",
            "definition": "Current term.",
            "status": "proposed",
            "aliases": [
                {"term": term, "status": "discouraged"}
                for term in ("alpha", "beta", "gamma")
            ],
        }],
    }
    (tmp_path / "terms.py").write_text("alpha = 1\nbeta = 2\ngamma = 3\n")
    monkeypatch.setattr("glossarize.drift.FINDINGS_PER_KIND_CAP", 1)

    drift = build_drift(build_evidence(tmp_path), glossary)

    assert len(drift["watched_terms_in_use"]["items"]) == 1
    assert drift["watched_terms_in_use"]["dropped_items"] == 2
    assert drift["total_findings"] == 3


def test_same_canonical_term_is_checked_independently_in_disjoint_scopes(tmp_path):
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
    auth = tmp_path / "auth"
    auth.mkdir()
    auth.joinpath("session.py").write_text(
        "session_cookie = 1\nsession_login = 2\nsession_user = 3\n"
    )

    drift = build_drift(build_evidence(tmp_path), glossary)

    fading = drift["canonical_fading"]["items"]
    assert [finding["concept_id"] for finding in fading] == ["db-session"]
    assert fading[0]["scope"] == {
        "kind": "path-prefixes", "path_prefixes": ["db"]
    }


def test_scoped_watched_alias_ignores_uses_in_another_subsystem(tmp_path):
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "auth-account",
            "term": "Account",
            "definition": "An authenticated identity.",
            "status": "canonical",
            "scope": {"path_prefixes": ["auth"]},
            "aliases": [{"term": "Handle", "status": "discouraged"}],
        }],
    }
    db = tmp_path / "db"
    db.mkdir()
    db.joinpath("records.py").write_text("handle_record = 1\n")

    outside = build_drift(build_evidence(tmp_path), glossary)
    assert outside["watched_terms_in_use"]["items"] == []

    auth = tmp_path / "auth"
    auth.mkdir()
    auth.joinpath("account.py").write_text("handle_account = 1\n")
    inside = build_drift(build_evidence(tmp_path), glossary)
    finding = inside["watched_terms_in_use"]["items"][0]
    assert finding["concept_id"] == "auth-account"
    assert finding["evidence"]["locations"][0]["path"] == "auth/account.py"


def test_scoped_reuse_does_not_look_like_a_global_concept_collision(tmp_path):
    concepts = []
    for subsystem in ("auth", "db", "ml"):
        directory = tmp_path / subsystem
        directory.mkdir()
        contexts = {
            "auth": ("cookie", "login", "user"),
            "db": ("commit", "transaction", "query"),
            "ml": ("model", "inference", "batch"),
        }[subsystem]
        directory.joinpath("session.py").write_text(
            "\n".join(f"session_{context} = 1" for context in contexts) + "\n"
        )
        concepts.append({
            "id": f"{subsystem}-session",
            "term": "Session",
            "definition": f"The {subsystem} meaning.",
            "status": "canonical",
            "scope": {"path_prefixes": [subsystem]},
        })

    drift = build_drift(
        build_evidence(tmp_path),
        {"schema_version": 1, "concepts": concepts},
    )

    assert drift["canonical_overloaded"]["items"] == []
    assert drift["scope_summary"] == {"repository": 0, "path_scoped": 3}


def test_partial_overload_module_details_cannot_prove_scoped_collision(tmp_path):
    contexts_by_subsystem = {
        "a": ("apple", "apricot"),
        "b": ("banana", "berry"),
        "c": ("cherry", "citrus"),
        "d": ("date", "dragonfruit"),
        "e": ("elderberry", "evergreen"),
    }
    for subsystem, contexts in contexts_by_subsystem.items():
        directory = tmp_path / subsystem
        directory.mkdir()
        directory.joinpath("session.py").write_text(
            "\n".join(f"session_{context} = 1" for context in contexts)
            + "\n"
        )
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "abc-session",
            "term": "Session",
            "definition": "The session shared by three selected subsystems.",
            "status": "canonical",
            "scope": {"path_prefixes": ["a", "b", "c"]},
        }],
    }

    drift = build_drift(build_evidence(tmp_path), glossary)
    coverage = drift["canonical_overloaded"]["coverage"]

    assert drift["canonical_overloaded"]["items"] == []
    assert coverage["total_items_exact"] is False
    assert coverage["complete"] is False
    assert any(
        "scoped overload check(s) omitted" in reason
        for reason in coverage["reasons"]
    )


def test_truncated_locations_cannot_prove_a_scoped_term_is_absent(tmp_path):
    for subsystem in ("a", "z"):
        directory = tmp_path / subsystem
        directory.mkdir()
        directory.joinpath("session.py").write_text("session_record = 1\n")
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "z-session",
            "term": "Session",
            "definition": "The z subsystem session.",
            "status": "canonical",
            "scope": {"path_prefixes": ["z"]},
        }],
    }
    evidence = build_evidence(tmp_path, limits=Limits(locations_per_term=1))

    drift = build_drift(evidence, glossary)

    assert drift["canonical_fading"]["items"] == []


def test_partial_production_corpus_cannot_prove_a_term_is_absent(
    tmp_path, monkeypatch
):
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "workspace",
            "term": "Workspace",
            "definition": "A user's working area.",
            "status": "canonical",
        }],
    }
    monkeypatch.setattr("glossarize.scanner.MAX_SOURCE_FILES", 1)
    (tmp_path / "a.py").write_text("ordinary_name = 1\n")
    (tmp_path / "z.py").write_text("workspace_record = 1\n")

    drift = build_drift(build_evidence(tmp_path), glossary)

    assert drift["canonical_fading"]["items"] == []
    assert drift["coverage"]["production_corpus_complete"] is False
    assert drift["total_findings_complete"] is False


def test_terminology_cap_propagates_to_drift_collection_coverage(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("glossarize.terminology.PAIR_TOP_N", 1)
    (tmp_path / "terms.py").write_text(
        "alpha_value = 1\nalpha_record = 2\n"
        "beta_value = 3\nbeta_record = 4\n"
    )
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "alpha", "term": "Alpha", "status": "canonical",
            "definition": "The alpha concept.",
        }],
    }

    drift = build_drift(build_evidence(tmp_path), glossary)
    coverage = drift["parallel_terms"]["coverage"]

    assert coverage["complete"] is False
    assert coverage["total_items_exact"] is False
    assert any("eligible token input" in reason
               for reason in coverage["reasons"])
    assert drift["total_findings_complete"] is False


def test_compound_matching_budget_suppresses_unproven_absence(tmp_path):
    (tmp_path / "terms.py").write_text(
        "aaa_other = 1\npayment_request = 2\n"
    )
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "payment-request", "term": "Payment Request",
            "status": "canonical", "definition": "A payment request.",
        }],
    }
    evidence = build_evidence(tmp_path)
    matcher = EvidenceIndex(
        evidence, ["Payment Request"], compound_start_budget=1
    )

    drift = build_drift(evidence, glossary, matcher=matcher)
    work = drift["coverage"]["work"]["matching"][
        "compound_match_positions"
    ]

    assert work["complete"] is False
    assert work["dropped_items"] > 0
    assert drift["canonical_fading"]["items"] == []
    assert drift["canonical_fading"]["coverage"][
        "total_items_exact"
    ] is False


def test_build_drift_indexes_duplicate_compound_terms_once(tmp_path):
    (tmp_path / "terms.py").write_text(
        "ordinary_value = 1\nrequest_queue = 2\n"
    )
    concept_count = 500
    glossary = {
        "schema_version": 1,
        "concepts": [
            {
                "id": f"payment-request-{index}",
                "term": "Payment Request",
                "status": "canonical",
                "definition": "A deliberately duplicated scaling fixture.",
            }
            for index in range(concept_count)
        ],
    }

    drift = build_drift(build_evidence(tmp_path), glossary)
    work = drift["coverage"]["work"]["matching"][
        "compound_match_positions"
    ]

    assert work["complete"] is True
    assert work["total_items"] < 20
    assert drift["canonical_fading"]["coverage"]["total_items"] == concept_count


def test_drift_command_end_to_end(tmp_path, capsys):
    root = make_repo(tmp_path)
    assert main(["drift", str(root)]) == 0
    out = capsys.readouterr().out
    assert "paralleling canonical vocabulary" in out
    assert "still in use" in out
    assert "fading" in out
    assert "not verdicts" in out
    assert (root / "glossarize-out" / "drift.json").is_file()
    assert (root / "glossarize-out" / "evidence.json").is_file()


def test_drift_without_glossary_is_user_error(tmp_path, capsys):
    (tmp_path / "a.py").write_text("x_y = 1\n")
    assert main(["drift", str(tmp_path)]) == 1
    assert "no glossary" in capsys.readouterr().err
