"""Lexical, register, drift, and structural evidence stays reproducible."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from evaluation.run import EVALUATION_SCHEMA_VERSION, verify_results

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evaluation" / "corpus.json"
RESULTS = ROOT / "evaluation" / "results.json"


def test_manifest_pins_licensed_varied_sources():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sources = manifest["sources"]

    assert manifest["schema_version"] == 5
    assert len(sources) == 7
    assert len({source["id"] for source in sources}) == len(sources)
    assert {source["primary_language"] for source in sources} == {
        "Python",
        "Go",
        "JavaScript/TypeScript declarations",
        "Python and Clojure multilingual fixture",
        "Python with Graphify fixture",
        "Python with capped Graphify fixture",
    }
    for source in sources:
        assert source["license_spdx"] in {"Apache-2.0", "MIT"}
        assert source["license_url"]
        assert len(source["corpus_sha256"]) == 64
        assert source["corpus_files"] > 0
        assert source["expectations"]["register"]["dominant_style"] in {
            "snake_case", "camelCase", "PascalCase", "UPPER_SNAKE"
        }
        assert isinstance(
            source["expectations"]["register"]["predominantly_multi_word"],
            bool,
        )
        if source["kind"] == "external-git":
            assert len(source["commit"]) == 40
            assert source["url"].startswith("https://github.com/")
    assert manifest["self_register"] == {
        "dominant_style": "snake_case",
        "predominantly_multi_word": True,
    }
    # `coverage` has three referents (ledger, corpus completeness, context omissions),
    # `run` stopped being a generic-only token once `command_run.Run` existed,
    # and `structural` is an adjective whose noun is `structural_groups`.
    # `drift` keeps its truthful label and is the recorded open finding.
    assert manifest["self_nominations"] == {
        "required": [
            {
                "term": "coverage",
                "nomination_kind": "deserves disambiguation",
            },
            {
                "term": "drift",
                "nomination_kind": "deserves a canonical name",
            },
        ],
        "forbidden_terms": ["json", "path", "file", "name", "root"],
        "require_all_typed": True,
    }


def test_local_calibration_case_runs_without_network(tmp_path):
    output = tmp_path / "results.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "evaluation" / "run.py"),
            "--case", "calibration-fixture",
            "--runs", "1",
            "--output", str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["schema_version"] == EVALUATION_SCHEMA_VERSION
    assert result["engine"]["version"] == "0.1.0"
    assert len(result["engine"]["source_sha256"]) == 64
    assert result["cases"][0]["corpus"]["files_hashed"] == 7
    assert len(result["cases"][0]["corpus"]["sha256"]) == 64
    assert result["aggregate"]["quality"]["false_alarms"] == 0
    assert result["aggregate"]["source_bytes"] == 903
    assert result["cases"][0]["corpus_budget"]["complete"] is True
    assert result["aggregate"]["quality"]["terminology_recall_where_complete"] == 1.0
    assert result["aggregate"]["quality"]["drift_recall_where_complete"] == 1.0
    assert result["cases"][0]["register"]["passed"] is True
    assert result["self_register"]["expected"] == {
        "dominant_style": "snake_case",
        "predominantly_multi_word": True,
    }
    assert result["self_register"]["actual"]["dominant_style"] == "snake_case"
    assert result["self_register"]["actual"]["predominantly_multi_word"] is True
    assert result["aggregate"]["quality"]["register_accuracy"] == 1.0
    # Open finding: the dispersion heuristic reads `drift`'s call-site
    # diversity across feature packages as meaning diversity and
    # types it `deserves disambiguation`; the label stays truthful, so this
    # one check is expected to fail until a heuristic phase resolves it.
    # (`plugin` left the required set on 2026-08-22: its nomination was
    # carried by the Codex evaluator living in one file, not by product code,
    # and vanished when that evaluator was split into modules.)
    assert result["self_nominations"]["passed"] is False
    assert result["self_nominations"]["checks"] == 8
    assert result["self_nominations"]["passed_checks"] == 7
    assert [f["name"] for f in result["self_nominations"]["failures"]] == [
        "required:drift"
    ]
    assert result["aggregate"]["quality"]["nomination_quality"] == round(7 / 8, 4)
    assert result["release_thresholds"] == {
        "configured": False,
        "passed": None,
        "checks": [],
    }


def test_language_semantics_case_pins_lexical_and_scope_contracts(tmp_path):
    output = tmp_path / "results.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "evaluation" / "run.py"),
            "--case", "language-semantics-fixture",
            "--runs", "1",
            "--output", str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    case = result["cases"][0]
    assert case["lexical"]["passed"] is True
    assert case["lexical"]["checks"] == 15
    assert case["drift"]["actual"] == []
    assert result["aggregate"]["quality"]["lexical_contract_rate"] == 1.0
    assert case["register"]["passed"] is True


def test_structural_cases_pin_findings_provenance_and_truncation(tmp_path):
    output = tmp_path / "results.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "evaluation" / "run.py"),
            "--case", "structural-complete-fixture",
            "--case", "structural-truncation-fixture",
            "--runs", "1",
            "--output", str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    complete, truncated = result["cases"]
    assert result["method"]["graphify_cases"] == 2
    assert complete["structural"]["actual"] == [
        "boundary-mismatch:Identity Boundary:authentication:authorization",
        "boundary-mismatch:Mixed Region:payment:run",
        "boundary-mismatch:Mixed Region:payment:tenant",
        "boundary-mismatch:Mixed Region:run:tenant",
        "fragmentation:tenant",
        "orphaned-concept:workspace",
        "overloaded-structural-region:Mixed Region",
        "unnamed-structure:Lease Boundary",
    ]
    assert complete["structural"]["false_positive"] == []
    assert complete["structural"]["false_negative"] == []
    assert complete["structural"]["contracts"] == {
        "checks": 17,
        "passed_checks": 17,
        "passed": True,
        "failures": [],
    }
    assert truncated["structural"]["actual"] == []
    assert truncated["structural"]["coverage"]["groups"] == {
        "complete": False,
        "dropped_items": 1,
        "included_items": 50,
        "reasons": ["structural group detail cap is 50 items"],
        "total_items": 51,
        "total_items_exact": True,
    }
    assert truncated["structural"]["coverage"]["validation_complete"] is False
    assert truncated["structural"]["contracts"]["passed"] is True
    assert result["aggregate"]["quality"]["structural_precision"] == 1.0
    assert (
        result["aggregate"]["quality"]["structural_recall_where_complete"]
        == 1.0
    )
    assert result["aggregate"]["quality"]["structural_contract_rate"] == 1.0


def test_committed_results_are_genuine_and_internally_consistent():
    assert verify_results(RESULTS, MANIFEST) == []


def test_genuineness_verifier_catches_internal_tampering_without_currency(
    tmp_path,
):
    original = json.loads(RESULTS.read_text(encoding="utf-8"))

    tampered_aggregate = deepcopy(original)
    tampered_aggregate["aggregate"]["quality"]["false_alarms"] += 1
    aggregate_path = tmp_path / "tampered-aggregate.json"
    aggregate_path.write_text(json.dumps(tampered_aggregate), encoding="utf-8")
    assert any(
        "aggregate is stale or internally inconsistent" in error
        for error in verify_results(aggregate_path, MANIFEST)
    )

    # Flipping the recorded verdict without the metrics behind it is
    # tampering (the checks no longer recompute), whichever way it flips.
    flipped_thresholds = deepcopy(original)
    flipped_thresholds["release_thresholds"]["passed"] = not (
        original["release_thresholds"]["passed"]
    )
    thresholds_path = tmp_path / "flipped-thresholds.json"
    thresholds_path.write_text(
        json.dumps(flipped_thresholds), encoding="utf-8"
    )
    assert any(
        "thresholds are stale" in error
        for error in verify_results(thresholds_path, MANIFEST)
    )

    dropped_check = deepcopy(original)
    dropped_check["release_thresholds"]["checks"] = [
        check
        for check in dropped_check["release_thresholds"]["checks"]
        if check["name"] != "terminology_precision_min"
    ]
    dropped_path = tmp_path / "dropped-check.json"
    dropped_path.write_text(json.dumps(dropped_check), encoding="utf-8")
    assert any(
        "thresholds are missing required checks" in error
        for error in verify_results(dropped_path, MANIFEST)
    )

    malformed_engine = deepcopy(original)
    malformed_engine["engine"]["source_sha256"] = "not-a-digest"
    engine_path = tmp_path / "malformed-engine.json"
    engine_path.write_text(json.dumps(malformed_engine), encoding="utf-8")
    assert any(
        "engine identity metadata is malformed" in error
        for error in verify_results(engine_path, MANIFEST)
    )

    method_as_list = deepcopy(original)
    method_as_list["method"] = ["not", "a", "mapping"]
    method_path = tmp_path / "method-as-list.json"
    method_path.write_text(json.dumps(method_as_list), encoding="utf-8")
    assert any(
        "required five-run sample" in error
        for error in verify_results(method_path, MANIFEST)
    )

    # Per-case score sets must be what `_score` produces: a phantom recall
    # hit (with an empty false-negative list the ratio stays 1.0 and the
    # aggregate re-derives cleanly), a hit listed as both true and false
    # positive, a "useful" key never found, or a found key also "missed"
    # are all tampering the aggregate check alone cannot see.
    def with_score(mutate, expected):
        doc = deepcopy(original)
        block = doc["cases"][0]["terminology"]
        mutate(block)
        path = tmp_path / "score-sets.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        errors = verify_results(path, MANIFEST)
        assert any(expected in error for error in errors), (expected, errors)


    with_score(lambda b: b["recall_true_positive"].append("zz:phantom"),
               "recall true positives are not a subset of true positives")
    with_score(lambda b: b["false_positive"].append(b["true_positive"][0]),
               "do not partition actual")
    with_score(lambda b: b["useful"].append("zz:never-found"),
               "useful hits are not a subset of true positives")
    with_score(lambda b: b["false_negative"].append(b["actual"][0]),
               "also recorded as found")
    with_score(lambda b: b["actual"].append(b["actual"][0]),  # duplicate, unsorted
               "not a sorted list of unique strings")


def test_evaluation_verifier_rejects_stale_or_weakened_evidence(tmp_path, monkeypatch):
    """Every staleness detector is proven on its own: the recorded results
    are first brought current (engine digest, self evidence, aggregate and
    thresholds recomputed from today's tree), that baseline is shown to carry
    no currency errors, and then each mutation must ADD its message. A
    test-audit found the earlier form passed vacuously whenever the working
    tree had moved past the recorded results — four of its ten messages were
    already in the baseline, so their mutations proved nothing.

    The per-case records are taken verbatim from the committed results, so
    this test also requires the committed local-corpus digests and scores to
    describe today's fixture trees: editing an evaluation fixture without
    regenerating results.json fails here, with the reasons listed."""
    import evaluation.run as run
    from evaluation.deterministic import scoring, sources

    real_build = run.build_evidence
    memo: dict = {}

    def memoized_build(root, **kwargs):
        key = (Path(root).resolve(), tuple(sorted(kwargs.items())))
        if key not in memo:
            memo[key] = real_build(root, **kwargs)
        return deepcopy(memo[key])

    monkeypatch.setattr(run, "build_evidence", memoized_build)

    manifest, manifest_sha256 = sources.read_manifest(MANIFEST)
    current = json.loads(RESULTS.read_text(encoding="utf-8"))
    current["engine"] = sources.engine_metadata()
    current["manifest_sha256"] = manifest_sha256
    self_evidence = run.build_evidence(ROOT, cache=False, graphify=False)
    current["self_register"] = scoring.evaluate_self_register(
        manifest["self_register"], self_evidence
    )
    current["self_nominations"] = scoring.evaluate_self_nominations(
        manifest["self_nominations"], self_evidence
    )
    current["aggregate"] = run._aggregate(
        current["cases"], current["self_register"], current["self_nominations"]
    )
    current["release_thresholds"] = run._thresholds(
        current["aggregate"], manifest["release_thresholds"]
    )
    gate_message = "evaluation release thresholds are not configured and passing"
    baseline_path = tmp_path / "current.json"
    baseline_path.write_text(json.dumps(current), encoding="utf-8")
    baseline = verify_results(baseline_path, MANIFEST, current=True)
    assert run._currency_errors(current, MANIFEST) == []
    # Whether the release gate is green is a recorded fact about the engine
    # (a threshold may legitimately be red between releases); nothing else
    # may be wrong with a document that describes today's tree.
    assert set(baseline) <= {gate_message}, baseline

    def engine_stale(result):
        result["engine"]["source_sha256"] = "0" * 64

    def manifest_stale(result):
        result["manifest_sha256"] = "0" * 64

    def corpus_stale(result):
        result["cases"][0]["corpus"]["sha256"] = "0" * 64

    def external_corpus_stale(result):
        result["cases"][2]["corpus"]["sha256"] = "0" * 64

    def sample_weakened(result):
        result["method"]["runtime_runs_per_case"] = 1

    def graphify_weakened(result):
        result["method"]["graphify_cases"] = 0

    def structural_stale(result):
        result["cases"][-2]["structural"]["contracts"]["passed"] = False

    def thresholds_tampered(result):
        # Whether they pass is a release-gate fact; genuineness requires that
        # the recorded checks recompute from the recorded metrics.
        check = result["release_thresholds"]["checks"][0]
        check["passed"] = not check["passed"]

    def register_stale(result):
        result["self_register"]["actual"]["dominant_style"] = "camelCase"

    def nomination_stale(result):
        result["self_nominations"]["passed"] = not result["self_nominations"]["passed"]

    def source_metadata_stale(result):
        result["cases"][0]["source"] = {**result["cases"][0]["source"], "kind": "external"}

    def local_register_stale(result):
        result["cases"][0]["register"]["actual"]["dominant_style"] = "camelCase"

    def threshold_targets_drifted(result):
        # Consistent with its own recomputation (genuineness clean) but the
        # stored targets no longer match the manifest: a currency matter.
        stored = result["release_thresholds"]
        stored["checks"][0]["target"] = 0.0
        stored["checks"][0]["passed"] = True
        stored["passed"] = all(check["passed"] for check in stored["checks"])

    def cases_reordered(result):
        result["cases"][0], result["cases"][1] = result["cases"][1], result["cases"][0]

    def case_renamed(result):
        result["cases"][0]["id"] = result["cases"][0]["id"] + "-renamed"

    mutations = [
        (source_metadata_stale, "source metadata is stale"),
        (local_register_stale, "local register evidence is stale"),
        (threshold_targets_drifted, "evaluation release thresholds are stale"),
        (cases_reordered, "case ids/order do not match the manifest"),
        (case_renamed, "case ids/order do not match the manifest"),
        (engine_stale, "engine version, schema, or source digest is stale"),
        (manifest_stale, "evaluation manifest digest is stale"),
        (corpus_stale, "local corpus digest is stale"),
        (external_corpus_stale, "corpus digest does not match manifest"),
        (sample_weakened, "required five-run sample"),
        (graphify_weakened, "Graphify case count is stale"),
        (structural_stale, "local structural evidence is stale"),
        (register_stale, "self register evidence is stale"),
        (nomination_stale, "self nomination evidence is stale"),
        (thresholds_tampered, "evaluation release thresholds are stale"),
    ]
    for index, (mutate, expected) in enumerate(mutations):
        result = deepcopy(current)
        mutate(result)
        path = tmp_path / f"results-{index}.json"
        path.write_text(json.dumps(result), encoding="utf-8")
        added = set(verify_results(path, MANIFEST, current=True)) - set(baseline)
        assert any(expected in error for error in added), (expected, added)

    # The release gate itself: only a recorded pass is accepted, and the gate
    # is wired into the --current path only (genuineness never judges it).
    red = deepcopy(current)
    red["release_thresholds"]["passed"] = False
    red_path = tmp_path / "red.json"
    red_path.write_text(json.dumps(red), encoding="utf-8")
    assert gate_message in verify_results(red_path, MANIFEST, current=True)
    assert gate_message not in verify_results(red_path, MANIFEST, current=False)
    assert run._release_threshold_errors({"release_thresholds": {"passed": True}}) == []
    assert run._release_threshold_errors(
        {"release_thresholds": {"passed": False}}
    ) == [gate_message]
    assert run._release_threshold_errors({}) == [gate_message]


def test_partial_case_runs_refuse_check_and_default_output(tmp_path, monkeypatch, capsys):
    """Run in-process against a scratch copy of the default output: if the
    guard ever regressed, the earlier subprocess form would have overwritten
    the committed evaluation/results.json while proving it (test-audit)."""
    import evaluation.run as run

    scratch_default = tmp_path / "results.json"
    committed = RESULTS.read_bytes()
    scratch_default.write_bytes(committed)
    monkeypatch.setattr(run, "DEFAULT_RESULTS", scratch_default)

    with pytest.raises(SystemExit) as with_check:
        run.main(["--case", "calibration-fixture", "--runs", "1", "--check",
                  "--output", str(tmp_path / "r.json")])
    assert with_check.value.code == 2
    assert "--check gates release thresholds" in capsys.readouterr().err

    with pytest.raises(SystemExit) as default_output:
        run.main(["--case", "calibration-fixture", "--runs", "1"])
    assert default_output.value.code == 2
    assert "committed release evidence" in capsys.readouterr().err
    assert scratch_default.read_bytes() == committed
    assert RESULTS.read_bytes() == committed
    assert not (tmp_path / "r.json").exists()
    assert b'"runtime_runs_per_case": 5' in committed


def test_aggregate_tolerates_an_empty_corpus_reuse_rate():
    from copy import deepcopy

    from evaluation.run import _aggregate

    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    cases = deepcopy(results["cases"])
    cases[0]["cache"]["reuse_rate"] = None

    aggregate = _aggregate(
        cases, results["self_register"], results["self_nominations"]
    )
    others = [
        case["cache"]["reuse_rate"] for case in cases[1:]
    ]
    assert aggregate["cache"]["minimum_reuse_rate"] == min(others)


def test_manifest_rejects_non_https_corpus_url(tmp_path):
    from copy import deepcopy

    from evaluation.deterministic.contract import EvaluationError
    from evaluation.deterministic.sources import read_manifest

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    poisoned = deepcopy(manifest)
    for source in poisoned["sources"]:
        if source.get("kind") != "local":
            source["url"] = "ext::sh -c 'touch /tmp/pwn'"
            break
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(poisoned), encoding="utf-8")

    try:
        read_manifest(path)
        raise AssertionError("an ext:: corpus url was accepted")
    except EvaluationError as exc:
        assert "url must be an https" in str(exc)


def _poison_first_source(overrides: dict, drop: tuple[str, ...] = ()) -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for source in manifest["sources"]:
        if source.get("kind") != "local":
            for key in drop:
                source.pop(key, None)
            source.update(overrides)
            break
    return manifest


def test_manifest_rejects_escaping_checkout_dir(tmp_path):
    # corpus.json is contributor-editable; a `..`/absolute checkout_dir joined
    # onto the temp checkout root writes attacker files outside the sandbox.
    from evaluation.deterministic.contract import EvaluationError
    from evaluation.deterministic.sources import read_manifest

    for bad in ("../../pwn", "/tmp/pwn", "a/../../pwn"):
        poisoned = _poison_first_source({"checkout_dir": bad})
        path = tmp_path / "corpus.json"
        path.write_text(json.dumps(poisoned), encoding="utf-8")
        try:
            read_manifest(path)
            raise AssertionError(f"escaping checkout_dir accepted: {bad}")
        except EvaluationError as exc:
            assert "checkout_dir" in str(exc)


def test_manifest_rejects_escaping_local_path(tmp_path):
    from evaluation.deterministic.contract import EvaluationError
    from evaluation.deterministic.sources import read_manifest

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["sources"] = [{
        "id": "evil", "kind": "local", "path": "../../../etc",
        "corpus_sha256": "0" * 64, "corpus_files": 1,
        "expectations": {"register": {}},
    }]
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    try:
        read_manifest(path)
        raise AssertionError("escaping local path accepted")
    except EvaluationError as exc:
        assert "path must be a safe relative path" in str(exc)


def test_manifest_rejects_non_hex_commit(tmp_path):
    # A commit beginning with `-` is parsed by git as an option in a refspec
    # slot; require a 40/64-char hex object name.
    from evaluation.deterministic.contract import EvaluationError
    from evaluation.deterministic.sources import read_manifest

    poisoned = _poison_first_source({"commit": "--upload-pack=touch /tmp/pwn"})
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(poisoned), encoding="utf-8")
    try:
        read_manifest(path)
        raise AssertionError("a non-hex commit was accepted")
    except EvaluationError as exc:
        assert "commit must be" in str(exc)


def test_manifest_rejects_oversized_file(tmp_path):
    from evaluation.deterministic.contract import EvaluationError
    from evaluation.deterministic.sources import read_manifest
    from glossabet.runtime.artifacts import MAX_JSON_BYTES

    path = tmp_path / "corpus.json"
    path.write_bytes(b'{"x":' + b" " * (MAX_JSON_BYTES + 10) + b"1}")
    try:
        read_manifest(path)
        raise AssertionError("an oversized manifest was accepted")
    except EvaluationError as exc:
        assert "exceeds" in str(exc)


def test_recall_where_complete_counts_only_hits_inside_the_measured_set():
    """A real-repository true positive where recall is not measured must not
    inflate the fixture-only recall figure: one incomplete case with nine
    hits plus one complete case at 1/4 is 25% recall, not 10/13."""
    from evaluation.deterministic.scoring import score_labels
    from evaluation.run import _aggregate

    def block(**overrides):
        base = {"checks": 0, "passed_checks": 0, "passed": None, "failures": []}
        base.update(overrides)
        return base

    incomplete = score_labels(
        {f"t{i}" for i in range(9)},
        {f"t{i}": {"useful": True} for i in range(9)},
        set(),  # recall not measured for this case
    )
    complete = score_labels(
        {"a"}, {k: {"useful": True} for k in "abcd"}, {"a", "b", "c", "d"}
    )
    empty = score_labels(set(), {}, set())
    cases = []
    for terminology in (incomplete, complete):
        cases.append({
            "terminology": terminology,
            "drift": empty,
            "structural": {"configured": False, "recall_complete": False,
                           **empty, "contracts": block()},
            "lexical": block(),
            "register": block(),
            "files": {"production_code": 1, "source": 1},
            "bytes": {"source_budgeted": 10},
            "corpus_budget": {"complete": True, "limits": {},
                              "used": {"walk_entries": 1}},
            "runtime_seconds": {"cold_median": 0.0, "warm_median": 0.0},
            "truncations": [],
            "cache": {"reuse_rate": None, "warm_output_matches_cold": True},
        })
    aggregate = _aggregate(cases, block(), block())
    assert aggregate["quality"]["terminology_recall_where_complete"] == 0.25
    assert aggregate["quality"]["terminology_precision"] == 1.0


def test_verifier_reports_rather_than_crashes_on_huge_integers(tmp_path):
    """An OverflowError from a 10**400 count used to escape as a traceback;
    every arithmetic failure in recomputation is a reported malformation."""
    original = json.loads(RESULTS.read_text(encoding="utf-8"))
    tampered = deepcopy(original)
    tampered["cases"][0]["runtime_seconds"]["cold_median"] = 10 ** 400
    path = tmp_path / "huge.json"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    errors = verify_results(path, MANIFEST)
    assert any("case metrics are malformed" in error for error in errors)
