"""Terminology intelligence: register stats must reflect real style, synonym
nomination must find parallel vocabularies without flagging mere relatedness,
overload nomination must find one term living disjoint lives, and all
pairwise work must be visibly bounded."""

import json
from collections import Counter, defaultdict

from glossabet.cli import main
from glossabet.evidence import build_evidence
from glossabet.terminology import (
    OVERLOAD_MODULE_ANALYSIS_CAP,
    PAIR_TOP_N,
    build_terminology,
)


def test_register_statistics(tmp_path):
    (tmp_path / "a.py").write_text(
        "class PaymentService: pass\n"
        "class BillingService: pass\n"
        "class OrderService: pass\n"
        "payment_total = 1\n"
        "billing_total = 2\n"
    )
    reg = build_evidence(tmp_path)["terminology"]["register"]
    assert reg["unique_identifiers"] == 5
    styles = reg["identifier_styles_pct"]
    assert styles["PascalCase"] == 60.0 and styles["snake_case"] == 40.0
    assert reg["token_count_distribution_pct"]["2"] == 100.0
    suffixes = {a["token"]: a["identifiers"] for a in reg["common_suffix_tokens"]}
    assert suffixes["service"] == 3 and suffixes["total"] == 2


def test_synonym_nomination_finds_parallel_vocabulary(tmp_path):
    (tmp_path / "jobs.py").write_text(
        "job_queue = 1\njob_runner = 2\nrun_job = 3\njob_queue_size = 4\n"
    )
    (tmp_path / "tasks.py").write_text(
        "task_queue = 1\ntask_runner = 2\nrun_task = 3\ntask_queue_size = 4\n"
    )
    syn = build_evidence(tmp_path)["terminology"]["synonym_candidates"]
    pairs = {(i["a"], i["b"]): i for i in syn["items"]}
    assert ("job", "task") in pairs
    assert "queue" in pairs[("job", "task")]["shared_contexts"]
    assert "*_queue" in pairs[("job", "task")]["shared_patterns"]
    assert pairs[("job", "task")]["file_overlap_rate"] == 0.0
    assert syn["considered_pairs"] > 0


def test_related_compound_terms_are_not_nominated_as_synonyms(tmp_path):
    # payment and service co-occur directly (payment_service) — related,
    # not synonymous; the co-occurrence gate must exclude the pair.
    (tmp_path / "a.py").write_text(
        "payment_service = 1\npayment_service_config = 2\n"
        "start_payment_service = 3\n"
    )
    syn = build_evidence(tmp_path)["terminology"]["synonym_candidates"]
    assert ("payment", "service") not in {(i["a"], i["b"]) for i in syn["items"]}


def test_single_shared_context_is_not_enough(tmp_path):
    # plus/minus share exactly one context (tok) — coincidence, not a
    # parallel vocabulary; must not be nominated.
    (tmp_path / "a.py").write_text("tok_plus = 1\ntok_minus = 2\n")
    syn = build_evidence(tmp_path)["terminology"]["synonym_candidates"]
    assert ("minus", "plus") not in {(i["a"], i["b"]) for i in syn["items"]}
    assert ("plus", "minus") not in {(i["a"], i["b"]) for i in syn["items"]}


def test_colocated_sibling_dimensions_are_not_synonym_candidates(tmp_path):
    (tmp_path / "report.py").write_text(
        "request_duration = 1\nresponse_duration = 2\n"
        "request_total = 3\nresponse_total = 4\n"
    )

    syn = build_evidence(tmp_path)["terminology"]["synonym_candidates"]

    assert ("request", "response") not in {
        (item["a"], item["b"]) for item in syn["items"]
    }


def test_overload_nomination_finds_disjoint_contexts(tmp_path):
    for module, contexts in (
        ("auth", ["login", "cookie"]),
        ("db", ["transaction", "commit"]),
        ("ml", ["inference", "model"]),
    ):
        d = tmp_path / module
        d.mkdir()
        lines = [f"session_{c} = 1" for c in contexts]
        (d / "code.py").write_text("\n".join(lines) + "\n")
    over = build_evidence(tmp_path)["terminology"]["overload_candidates"]
    terms = {i["term"]: i for i in over["items"]}
    assert "session" in terms
    assert len(terms["session"]["modules"]) == 3
    assert terms["session"]["dispersion"] >= 0.8


def test_test_vocabulary_does_not_drive_synonym_or_overload_signals(tmp_path):
    (tmp_path / "app.py").write_text("production_boundary = 1\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "jobs.py").write_text(
        "job_queue = 1\njob_runner = 2\nrun_job = 3\n"
    )
    (tests / "tasks.py").write_text(
        "task_queue = 1\ntask_runner = 2\nrun_task = 3\n"
    )
    for module, contexts in (
        ("auth", ["login", "cookie"]),
        ("db", ["transaction", "commit"]),
        ("ml", ["inference", "model"]),
    ):
        directory = tests / module
        directory.mkdir()
        (directory / "session.py").write_text(
            "\n".join(f"session_{context} = 1" for context in contexts) + "\n"
        )

    evidence = build_evidence(tmp_path)
    terminology = evidence["terminology"]

    pairs = {(item["a"], item["b"])
             for item in terminology["synonym_candidates"]["items"]}
    overloaded = {item["term"]
                  for item in terminology["overload_candidates"]["items"]}
    assert ("job", "task") not in pairs
    assert "session" not in overloaded
    assert terminology["scope"]["code_files"] == 1
    assert not {"job", "task", "session"} & {
        item["term"] for item in evidence["naming_candidates"]["terms"]
    }


def test_layer_comparison(tmp_path):
    (tmp_path / "a.py").write_text("execution_engine = 1\nexecution_step = 2\n")
    (tmp_path / "README.md").write_text(
        "The run pipeline drives every execution.\n"
    )
    layers = build_evidence(tmp_path)["terminology"]["layers"]
    assert "execution" in layers["shared_top"]
    assert "engine" in layers["code_only_top"]
    assert "run" in layers["doc_only_top"] or "pipeline" in layers["doc_only_top"]


def test_bounds_are_reported(tmp_path):
    (tmp_path / "a.py").write_text("alpha_beta = 1\nalpha_beta_gamma = 2\n")
    term = build_evidence(tmp_path)["terminology"]
    assert term["considered_tokens"] <= 150
    assert "vocabulary_size" in term
    assert "considered_pairs" in term["synonym_candidates"]
    assert "dropped_items" in term["synonym_candidates"]
    assert "dropped_items" in term["overload_candidates"]
    assert term["coverage"]["eligible_tokens"]["complete"] is True


def test_151st_eligible_token_is_counted_and_propagates_partial_coverage():
    token_counts = Counter({f"token{index:03}": 2 for index in range(151)})
    counters = defaultdict(Counter)
    module_contexts = defaultdict(lambda: defaultdict(set))

    terminology = build_terminology(
        Counter(), token_counts, counters, counters, counters, counters,
        module_contexts, Counter(), set(),
    )

    token_coverage = terminology["coverage"]["eligible_tokens"]
    assert token_coverage == {
        "total_items": 151,
        "included_items": PAIR_TOP_N,
        "dropped_items": 1,
        "total_items_exact": True,
        "complete": False,
        "reasons": [
            f"terminology analysis cap is the top {PAIR_TOP_N} eligible tokens"
        ],
    }
    for name in ("synonym_candidates", "overload_candidates"):
        coverage = terminology[name]["coverage"]
        assert coverage["complete"] is False
        assert coverage["total_items_exact"] is False
        assert any("eligible token input" in reason
                   for reason in coverage["reasons"])


def test_overload_module_pair_work_is_bounded_and_reported():
    module_count = OVERLOAD_MODULE_ANALYSIS_CAP + 1
    modules = {
        f"module-{index:03}": {f"context-{index:03}"}
        for index in range(module_count)
    }
    counters = defaultdict(Counter)

    terminology = build_terminology(
        Counter(),
        Counter({"session": module_count * 2}),
        counters,
        {"session": Counter({module: 2 for module in modules})},
        counters,
        counters,
        {"session": modules},
        Counter(),
        set(),
    )

    overload = terminology["overload_candidates"]
    assert overload["items"] == []
    assert overload["coverage"]["total_items_exact"] is False
    assert overload["coverage"]["complete"] is False
    assert (
        f"1 term(s) exceeded the {OVERLOAD_MODULE_ANALYSIS_CAP}-module "
        "overload analysis cap"
    ) in overload["coverage"]["reasons"]


def test_terminology_is_deterministic(tmp_path):
    (tmp_path / "a.py").write_text(
        "job_queue = 1\ntask_queue = 2\nrun_job = 3\nrun_task = 4\n"
    )
    first = build_evidence(tmp_path)["terminology"]
    second = build_evidence(tmp_path)["terminology"]
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_analyze_command_end_to_end(tmp_path, capsys):
    (tmp_path / "a.py").write_text(
        "class PaymentService: pass\npayment_total = 1\n"
    )
    assert main(["analyze", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "house register" in out
    assert "vocabulary overlaps" in out
    assert "nominations" in out  # the not-verdicts reminder
    assert (tmp_path / "glossabet-out" / "evidence.json").is_file()
