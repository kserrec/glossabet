"""Drift detection: the seeded scenario from the plan — a concept renamed in
new code must be caught with correct evidence — plus the other three checks,
bounds, determinism, and the no-glossary path."""

import json

from glossabet.cli import main
from glossabet.glossary.drift import build_drift
from glossabet.analysis.evidence import Limits, build_evidence
from glossabet.glossary.store import save_glossary
from glossabet.glossary.matching import EvidenceIndex

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
    """A token the glossary already owns — as a term or an alias — is a
    *watched* matter, not a parallel-term finding, but only where the owner's
    scope actually covers the occurrence: an alias owned in a disjoint scope
    does not suppress the finding elsewhere. Built so `charge` really is a
    synonym candidate of `payment` (shared contexts), so the suppression is
    exercised rather than vacuous."""
    (tmp_path / "pay").mkdir()
    (tmp_path / "pay" / "pay.py").write_text(
        "payment_record = 1\npayment_scheduler = 2\nstart_payment = 3\n"
        "payment_record_id = 4\n"
    )
    (tmp_path / "pay" / "gw.py").write_text(  # the collision happens inside pay/
        "charge_record = 1\ncharge_scheduler = 2\nstart_charge = 3\n"
    )
    evidence = build_evidence(tmp_path)
    parallel_new_terms = lambda glossary: {
        f["new_term"] for f in build_drift(evidence, glossary)["parallel_terms"]["items"]
    }

    unowned = {"schema_version": 1, "concepts": [{
        "id": "payment", "term": "Payment", "definition": "d", "status": "canonical",
    }]}
    assert "charge" in parallel_new_terms(unowned)  # the candidate is real

    owned = {"schema_version": 1, "concepts": [{
        "id": "payment", "term": "Payment", "definition": "d", "status": "canonical",
        "aliases": [{"term": "charge", "status": "discouraged"}],
    }]}
    assert "charge" not in parallel_new_terms(owned)

    # Scoped canonical `Payment` (pay/): an alias owner of `charge` whose
    # scope overlaps pay/ suppresses the finding; an alias owner in a disjoint
    # scope (billing/) does not — the token is unowned where the collision
    # happens. (A token canonical anywhere skips the pair outright, by design.)
    scoped = {"schema_version": 1, "concepts": [
        {"id": "payment", "term": "Payment", "definition": "d", "status": "canonical",
         "scope": {"path_prefixes": ["pay"]}},
        {"id": "other", "term": "Other", "definition": "d", "status": "canonical",
         "scope": {"path_prefixes": ["pay"]},
         "aliases": [{"term": "charge", "status": "discouraged"}]},
    ]}
    assert "charge" not in parallel_new_terms(scoped)
    scoped["concepts"][1]["scope"] = {"path_prefixes": ["billing"]}
    assert "charge" in parallel_new_terms(scoped)


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
    monkeypatch.setattr("glossabet.glossary.findings.FINDINGS_CAP", 1)

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
    monkeypatch.setattr("glossabet.corpus.scanner.MAX_SOURCE_FILES", 1)
    (tmp_path / "a.py").write_text("ordinary_name = 1\n")
    (tmp_path / "z.py").write_text("workspace_record = 1\n")

    drift = build_drift(build_evidence(tmp_path), glossary)

    assert drift["canonical_fading"]["items"] == []
    assert drift["coverage"]["production_corpus_complete"] is False
    assert drift["total_findings_complete"] is False


def test_terminology_cap_propagates_to_drift_collection_coverage(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("glossabet.analysis.terminology.PAIR_TOP_N", 1)
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
    assert (root / "glossabet-out" / "drift.json").is_file()
    assert (root / "glossabet-out" / "evidence.json").is_file()


def test_scoped_zero_from_a_clipped_location_sample_is_confessed(tmp_path):
    # Five lib/ files dominate the token's 5-location sample; six auth/ uses
    # of the discouraged alias are invisible to the scoped count. The check
    # must report itself suppressed, never complete-and-clean.
    for index in range(5):
        (tmp_path / f"lib{index}.py").write_text(
            ("handle_widget = 1\n") * (100 - index)
        )
    auth = tmp_path / "auth"
    auth.mkdir()
    for index in range(6):
        (auth / f"a{index}.py").write_text("handle_account = 1\n")
    glossary = {
        "schema_version": 1,
        "concepts": [
            {
                "id": "auth-account",
                "term": "Account",
                "definition": "The authenticated principal.",
                "status": "canonical",
                "scope": {"path_prefixes": ["auth"]},
                "aliases": [{"term": "handle", "status": "discouraged"}],
            }
        ],
    }
    evidence = build_evidence(tmp_path)
    drift = build_drift(evidence, glossary)

    section = drift["watched_terms_in_use"]
    assert section["items"] == []
    ledger = section["coverage"]
    assert ledger["complete"] is False
    assert any("location sample" in reason for reason in ledger["reasons"])


def test_parallel_term_scope_checks_are_bounded_against_many_owner_scopes(tmp_path):
    """The other side of the prefix-pair budget: not one concept with
    thousands of prefixes but thousands of owner concepts, each with a few
    prefixes, all owning the token a parallel candidate collides with. The
    overlap check must reach the loop (the corpus makes `run`/`execution`
    genuine synonym candidates), trip the budget, and report the section
    partial — never spend minutes and never claim completeness."""
    import time

    (tmp_path / "runs.py").write_text(
        "run_record = 1\nrun_scheduler = 2\nstart_run = 3\nrun_record_id = 4\n"
    )
    (tmp_path / "exec_new.py").write_text(
        "execution_record = 1\nexecution_scheduler = 2\nstart_execution = 3\n"
    )
    owners = 3000
    concepts = [
        {
            "id": f"run{i}",
            "term": "run",
            "definition": "d",
            "status": "canonical",
            "scope": {"path_prefixes": [f"prod/d{i}/{j}" for j in range(20)]},
        }
        for i in range(owners)
    ]
    concepts.append({
        "id": "other",
        "term": "other",
        "definition": "d",
        "status": "canonical",
        "scope": {"path_prefixes": [f"zone/z{i}" for i in range(200)]},
        "aliases": [{"term": "execution", "status": "proposed"}],
    })
    glossary = {"schema_version": 1, "concepts": concepts}

    evidence = build_evidence(tmp_path)
    start = time.monotonic()
    drift = build_drift(evidence, glossary)
    elapsed = time.monotonic() - start
    parallel = drift["coverage"]["collections"]["parallel_terms"]
    assert not parallel["complete"], "many-owner overlap work must report partial"
    assert any("budget" in reason for reason in parallel["reasons"])
    assert elapsed < 10, f"owner-scope overlap work was unbounded ({elapsed:.1f}s)"


def test_parallel_term_budget_charges_prefix_pair_work_not_owner_count(tmp_path):
    # The prior budget charged one unit per owner scope regardless of how many
    # path-prefix pairs the overlap actually compares, so a single concept
    # carrying tens of thousands of prefixes hid a 100M+ comparison behind a
    # charge of 1 and the ceiling never tripped (~279s CPU within the 50k-prefix
    # ceiling). The budget must be charged the real prefix-pair product: two
    # concepts of 6000 disjoint prefixes each, made parallel by an alias, must
    # trip the budget fast and report the section partial.
    import time

    # Shared token contexts (record/scheduler/start) make "run" and "execution"
    # parallel-term synonym candidates, so _parallel_terms actually reaches the
    # scope-overlap check.
    (tmp_path / "runs.py").write_text(
        "run_record = 1\nrun_scheduler = 2\nstart_run = 3\nrun_record_id = 4\n"
    )
    (tmp_path / "exec_new.py").write_text(
        "execution_record = 1\nexecution_scheduler = 2\nstart_execution = 3\n"
    )
    n = 6000
    concepts = [
        {
            "id": "run",
            "term": "run",
            "definition": "d",
            "status": "canonical",
            "scope": {"path_prefixes": [f"a/{i:05d}" for i in range(n)]},
        },
        {
            "id": "other",
            "term": "other",
            "definition": "d",
            "status": "canonical",
            "scope": {"path_prefixes": [f"b/{i:05d}" for i in range(n)]},
            "aliases": [{"term": "execution", "status": "proposed"}],
        },
    ]
    glossary = {"schema_version": 1, "concepts": concepts}

    evidence = build_evidence(tmp_path)
    start = time.monotonic()
    drift = build_drift(evidence, glossary)
    elapsed = time.monotonic() - start
    assert elapsed < 5, f"prefix-pair work was unbounded ({elapsed:.1f}s)"
    parallel = drift["coverage"]["collections"]["parallel_terms"]
    assert not parallel["complete"], "parallel-term section should be partial"
    assert any(
        "comparison budget" in reason for reason in parallel["reasons"]
    ), parallel["reasons"]


def test_terms_the_doc_index_cannot_hold_are_not_reported_as_fading(tmp_path):
    """`ID`/`S3` (too short, digits) and a possessive-only mention
    (`tenant's`) used to score `doc_mentions: 0, count_complete: true` and
    yield a false "canonical … is fading"; the doc index cannot represent the
    first two (so absence proves nothing) and now folds the possessive."""
    (tmp_path / "app.py").write_text(
        "id_value = 1\ns3_bucket = 2\ntenant_slice = 3\n"
    )
    (tmp_path / "README.md").write_text(
        "The ID is unique. Every ID maps to S3. S3 holds blobs; S3 again.\n"
        "Each tenant's data lives in the tenant's slice; the tenant's isolated.\n"
    )
    glossary = {"schema_version": 1, "concepts": [
        {"id": "id", "term": "ID", "definition": "d", "status": "canonical"},
        {"id": "s3", "term": "S3", "definition": "d", "status": "canonical"},
        {"id": "tenant", "term": "Tenant", "definition": "d", "status": "canonical"},
    ]}
    evidence = build_evidence(tmp_path)
    matcher = EvidenceIndex(evidence, ["ID", "S3", "Tenant"])
    assert matcher.doc_term_occurrence("ID")["count_complete"] is False
    assert matcher.doc_term_occurrence("S3")["count_complete"] is False
    assert matcher.doc_term_occurrence("Tenant") == {
        "count": 3, "count_complete": True, "scope": {"kind": "repository"},
    }
    # A term that is one doc word but splits on its apostrophe as an
    # identifier is looked up the way the doc index was built.
    (tmp_path / "README.md").write_text("O'Brien wrote it. Ask O'Brien. O'Brien.\n")
    matcher = EvidenceIndex(build_evidence(tmp_path), ["O'Brien"])
    assert matcher.doc_term_occurrence("O'Brien")["count"] == 3
    fading = build_drift(evidence, glossary)["canonical_fading"]["items"]
    assert [f["term"] for f in fading] == []


def test_compound_occurrence_file_total_stays_exact_when_only_the_sample_is_clipped(tmp_path):
    """Two matching identifiers across six files: `files: 6` is exact, so
    `files_complete` must be True even though only five locations are
    displayed (`locations_truncated` reports the display clip)."""
    for index in range(3):  # each identifier stays under the per-entry cap
        (tmp_path / f"a{index}.py").write_text("create_payment_request = 1\n")
        (tmp_path / f"b{index}.py").write_text("payment_request = 2\n")
    evidence = build_evidence(tmp_path)
    occurrence = EvidenceIndex(evidence, ["Payment Request"]).code_term_occurrence(
        "Payment Request"
    )
    assert occurrence["match_kind"] == "lexical-unit"
    assert occurrence["count"] == 6 and occurrence["count_complete"] is True
    assert occurrence["files"] == 6 and occurrence["files_complete"] is True
    assert len(occurrence["locations"]) == 5
    assert occurrence["locations_truncated"] is True


def test_compound_terms_match_only_contiguous_token_runs(tmp_path):
    """`Payment Request` is one lexical unit: an identifier that merely
    contains both words (`payment_total_request`) is not an occurrence, or a
    discouraged compound would read "still in use" and a canonical one
    "present" on evidence that never used the term. Adjacent runs match at
    any position; the class is contiguity, not the position (test-audit)."""
    (tmp_path / "a.py").write_text(
        "payment_total_request = 1\n"      # both words, not adjacent: no
        "payment_request_total = 2\n"      # adjacent at the start: yes
        "total_payment_request = 3\n"      # adjacent at the end: yes
        "request_payment = 4\n"            # reversed: no
    )
    evidence = build_evidence(tmp_path)
    occurrence = EvidenceIndex(evidence, ["Payment Request"]).code_term_occurrence(
        "Payment Request"
    )
    assert occurrence["match_kind"] == "lexical-unit"
    assert occurrence["count"] == 2 and occurrence["count_complete"] is True
    assert occurrence["locations"] == [{"path": "a.py", "count": 2}]
    # And which two: each adjacent form alone is one, each other form none.
    for identifier, expected in (
        ("payment_total_request", 0), ("request_payment", 0),
        ("payment_request_total", 1), ("total_payment_request", 1),
    ):
        (tmp_path / "a.py").write_text(f"{identifier} = 1\n")
        alone = EvidenceIndex(
            build_evidence(tmp_path), ["Payment Request"]
        ).code_term_occurrence("Payment Request")
        assert alone["count"] == expected, identifier


def test_watched_count_is_qualified_under_a_partial_corpus(tmp_path, monkeypatch):
    """When the production corpus was cut by a budget, a watched term's
    occurrence count is a floor, and the finding says so ("at least N");
    an exact-looking count under a partial corpus is a coverage lie."""
    monkeypatch.setattr("glossabet.corpus.scanner.MAX_SOURCE_FILES", 1)
    (tmp_path / "a.py").write_text("charge_request = 1\ncharge_total = 2\n")
    (tmp_path / "b.py").write_text("charge_more = 3\n")
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "payment", "term": "Payment", "definition": "d",
            "status": "canonical",
            "aliases": [{"term": "Charge", "status": "discouraged"}],
        }],
    }
    evidence = build_evidence(tmp_path)
    assert evidence["skipped"]["corpus_budget"]["complete"] is False
    drift = build_drift(evidence, glossary)
    (finding,) = drift["watched_terms_in_use"]["items"]
    assert finding["evidence"]["count_complete"] is False
    assert "at least 2 lexical occurrence(s)" in finding["summary"]
    assert drift["watched_terms_in_use"]["coverage"]["complete"] is False

    monkeypatch.setattr("glossabet.corpus.scanner.MAX_SOURCE_FILES", 10_000)
    (finding,) = build_drift(build_evidence(tmp_path), glossary)[
        "watched_terms_in_use"
    ]["items"]
    assert finding["evidence"]["count_complete"] is True
    assert "3 lexical occurrence(s)" in finding["summary"]
    assert "at least" not in finding["summary"]


def test_truncated_vocabulary_tables_make_drift_ledgers_say_so(tmp_path):
    """A tokens table cut at scan time hides occurrences the fading and
    watched checks would have counted; those ledgers must be marked
    incomplete with the vocabulary reason, not silently exact. The reason
    itself is unit-tested in test_findings; this pins that drift wires it."""
    for index in range(4):
        (tmp_path / f"m{index}.py").write_text(
            f"alpha_thing_{index} = 1\nbeta_thing_{index} = 2\ngamma_{index} = 3\n"
        )
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "alpha", "term": "Alpha", "definition": "d",
            "status": "canonical",
            "aliases": [{"term": "Gamma", "status": "discouraged"}],
        }],
    }
    full = build_evidence(tmp_path)
    assert full["vocabulary"]["tokens"]["truncated"] is None
    for section in ("canonical_fading", "watched_terms_in_use"):
        assert build_drift(full, glossary)[section]["coverage"]["complete"] is True

    cut = build_evidence(tmp_path, Limits(tokens=1))
    assert cut["vocabulary"]["tokens"]["truncated"] is not None
    drift = build_drift(cut, glossary)
    for section in ("canonical_fading", "watched_terms_in_use"):
        coverage = drift[section]["coverage"]
        assert coverage["complete"] is False, section
        assert any("tokens" in reason for reason in coverage["reasons"]), (
            section, coverage
        )


def test_compound_canonical_terms_are_not_indexed_as_their_single_words(tmp_path):
    """`Session Token` canonical must not make bare `session` a canonical
    token: overload signals are token-level, and mapping one word of a
    compound to the whole concept recreates the cross-unit false match the
    exact occurrence checks exist to prevent. (Pinned on the overload axis;
    make_repo has no synonym partner for `session`, so the parallel-term
    axis is not exercised here.)"""
    make_repo(tmp_path)  # canonical "Session" would be overloaded here
    evidence = build_evidence(tmp_path)
    single = {
        "schema_version": 1,
        "concepts": [{"id": "session", "term": "Session", "definition": "d",
                      "status": "canonical"}],
    }
    compound = {
        "schema_version": 1,
        "concepts": [{"id": "session-token", "term": "Session Token",
                      "definition": "d", "status": "canonical"}],
    }
    assert [
        f["term"] for f in build_drift(evidence, single)["canonical_overloaded"]["items"]
    ] == ["Session"]
    assert build_drift(evidence, compound)["canonical_overloaded"]["items"] == []


def test_entry_level_location_clip_makes_scoped_compound_counts_inexact(tmp_path):
    """When the identifier index itself kept only a sample of an identifier's
    locations, a scoped compound count derived from that sample is a lower
    bound: the scope's own occurrences may be the ones clipped away. Both
    the scoped count and the file total must be marked inexact — a confident
    zero here would read as "absent from code" inside the scope."""
    for index in range(4):
        (tmp_path / "other").mkdir(exist_ok=True)
        (tmp_path / "other" / f"a{index}.py").write_text("payment_request = 1\n")
    (tmp_path / "pay").mkdir()
    (tmp_path / "pay" / "z.py").write_text("payment_request = 1\n")
    evidence = build_evidence(tmp_path, Limits(locations_per_term=2))
    entry = next(
        item for item in evidence["vocabulary"]["identifiers"]["items"]
        if item["name"] == "payment_request"
    )
    assert entry["locations_truncated"] is True and entry["count"] == 5

    index = EvidenceIndex(evidence, ["Payment Request"])
    scoped = index.code_term_occurrence("Payment Request", ("pay",))
    assert scoped["count_complete"] is False
    assert scoped["files_complete"] is False
    assert scoped["locations_truncated"] is True

    unscoped = index.code_term_occurrence("Payment Request")
    assert unscoped["count"] == 5 and unscoped["count_complete"] is True
    assert unscoped["files"] == 2 and unscoped["files_complete"] is False


def test_over_long_compound_terms_are_reported_as_unmatched_not_absent(tmp_path):
    """A canonical term longer than the compound-matching cap cannot be
    looked up; the engine must say so (ledger reason, count inexact) rather
    than let a confident zero read as "absent from code". At the cap the
    term is matched normally, and other terms in the same index stay exact."""
    from glossabet.glossary.matching import MAX_COMPOUND_TERM_TOKENS

    (tmp_path / "a.py").write_text("payment_request = 1\n")
    at_cap = " ".join(f"w{i}" for i in range(MAX_COMPOUND_TERM_TOKENS))
    over = " ".join(f"w{i}" for i in range(MAX_COMPOUND_TERM_TOKENS + 1))
    evidence = build_evidence(tmp_path)

    index = EvidenceIndex(evidence, [at_cap, over])
    ledger = index.coverage["compound_terms"]
    assert ledger["total_items"] == 2 and ledger["included_items"] == 1
    assert ledger["complete"] is False
    assert any(f"{MAX_COMPOUND_TERM_TOKENS}-token" in r for r in ledger["reasons"])
    # The over-cap term is the only one affected: its neighbour in the same
    # index keeps an exact count (a bughunt found the flag was index-wide).
    assert index.code_term_occurrence(at_cap)["count_complete"] is True
    unmatched = index.code_term_occurrence(over)
    assert unmatched["count"] == 0 and unmatched["count_complete"] is False

    glossary = {"schema_version": 1, "concepts": [
        {"id": "long", "term": over, "definition": "d", "status": "canonical"},
    ]}
    drift = build_drift(evidence, glossary)
    coverage = drift["canonical_fading"]["coverage"]
    assert coverage["complete"] is False
    assert any(f"{MAX_COMPOUND_TERM_TOKENS}-token" in r for r in coverage["reasons"])
    # A "strong: absent" fading finding here would be the false claim.
    assert [f["signal_strength"] for f in drift["canonical_fading"]["items"]
            if f["term"] == over and f["signal_strength"] == "strong"] == []


def test_parallel_term_findings_are_ordered_strongest_first_under_the_cap(
    tmp_path, monkeypatch
):
    """The section keeps only the first FINDINGS_CAP findings in detail, so
    ordering is a coverage promise: the strongest parallel is what survives
    the cap, and the ledger says one was dropped."""
    make_repo(tmp_path)
    (tmp_path / "exec2.py").write_text(
        "job_record = 1\njob_scheduler = 2\nstart_job = 3\njob_record_id = 4\n"
    )
    evidence = build_evidence(tmp_path)
    full = build_drift(evidence, GLOSSARY)["parallel_terms"]
    pairs = [(f["new_term"], f["evidence"]["similarity"]) for f in full["items"]]
    assert [p[0] for p in pairs] == ["job", "execution"]
    assert pairs[0][1] > pairs[1][1]

    monkeypatch.setattr("glossabet.glossary.findings.FINDINGS_CAP", 1)
    capped = build_drift(evidence, GLOSSARY)["parallel_terms"]
    assert [f["new_term"] for f in capped["items"]] == ["job"]
    assert capped["coverage"]["total_items"] == 2
    assert capped["coverage"]["included_items"] == 1
    assert capped["coverage"]["dropped_items"] == 1
    assert capped["coverage"]["complete"] is False
