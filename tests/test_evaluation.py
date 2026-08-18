"""Lexical, register, drift, and structural evidence stays reproducible."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

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
    # Re-labelled deliberately in Phase 39 (layer subpackages): `coverage`
    # has three referents (ledger, corpus completeness, context omissions),
    # `run` stopped being a generic-only token once `engine_run.Run` existed,
    # and `structural` is an adjective whose noun is `structural_groups`.
    # `drift` keeps its truthful label and is the recorded open finding.
    assert manifest["self_nominations"] == {
        "required": [
            {
                "term": "plugin",
                "nomination_kind": "deserves a canonical name",
            },
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
    # Open finding (PLAN Phase 39): the dispersion heuristic reads `drift`'s
    # call-site diversity across layer subpackages as meaning diversity and
    # types it `deserves disambiguation`; the label stays truthful, so this
    # one check is expected to fail until a heuristic phase resolves it.
    assert result["self_nominations"]["passed"] is False
    assert result["self_nominations"]["checks"] == 9
    assert result["self_nominations"]["passed_checks"] == 8
    assert [f["name"] for f in result["self_nominations"]["failures"]] == [
        "required:drift"
    ]
    assert result["aggregate"]["quality"]["nomination_quality"] == round(8 / 9, 4)
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

    weakened_thresholds = deepcopy(original)
    weakened_thresholds["release_thresholds"]["passed"] = False
    thresholds_path = tmp_path / "weakened-thresholds.json"
    thresholds_path.write_text(
        json.dumps(weakened_thresholds), encoding="utf-8"
    )
    assert any(
        "thresholds are not configured and passing" in error
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


def test_evaluation_verifier_rejects_stale_or_weakened_evidence(tmp_path):
    original = json.loads(RESULTS.read_text(encoding="utf-8"))

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

    def thresholds_weakened(result):
        result["release_thresholds"]["passed"] = False

    def register_stale(result):
        result["self_register"]["actual"]["dominant_style"] = "camelCase"

    def nomination_stale(result):
        result["self_nominations"]["passed"] = False

    mutations = [
        (engine_stale, "engine version, schema, or source digest is stale"),
        (manifest_stale, "evaluation manifest digest is stale"),
        (corpus_stale, "local corpus digest is stale"),
        (external_corpus_stale, "corpus digest does not match manifest"),
        (sample_weakened, "required five-run sample"),
        (graphify_weakened, "Graphify case count is stale"),
        (structural_stale, "local structural evidence is stale"),
        (register_stale, "self register evidence is stale"),
        (nomination_stale, "self nomination evidence is stale"),
        (thresholds_weakened, "thresholds are not configured and passing"),
    ]
    for index, (mutate, expected) in enumerate(mutations):
        result = deepcopy(original)
        mutate(result)
        path = tmp_path / f"results-{index}.json"
        path.write_text(json.dumps(result), encoding="utf-8")
        assert any(
            expected in error
            for error in verify_results(path, MANIFEST, current=True)
        )


def test_partial_case_runs_refuse_check_and_default_output(tmp_path):
    base = [sys.executable, str(ROOT / "evaluation" / "run.py")]

    with_check = subprocess.run(
        [*base, "--case", "calibration-fixture", "--runs", "1", "--check",
         "--output", str(tmp_path / "r.json")],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert with_check.returncode == 2
    assert "--check gates release thresholds" in with_check.stderr

    default_output = subprocess.run(
        [*base, "--case", "calibration-fixture", "--runs", "1"],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert default_output.returncode == 2
    assert "committed release evidence" in default_output.stderr
    committed = (ROOT / "evaluation" / "results.json").read_bytes()
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

    from evaluation.run import EvaluationError, _read_manifest

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    poisoned = deepcopy(manifest)
    for source in poisoned["sources"]:
        if source.get("kind") != "local":
            source["url"] = "ext::sh -c 'touch /tmp/pwn'"
            break
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(poisoned), encoding="utf-8")

    try:
        _read_manifest(path)
        assert False, "an ext:: corpus url was accepted"
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
    from evaluation.run import EvaluationError, _read_manifest

    for bad in ("../../pwn", "/tmp/pwn", "a/../../pwn"):
        poisoned = _poison_first_source({"checkout_dir": bad})
        path = tmp_path / "corpus.json"
        path.write_text(json.dumps(poisoned), encoding="utf-8")
        try:
            _read_manifest(path)
            assert False, f"escaping checkout_dir accepted: {bad}"
        except EvaluationError as exc:
            assert "checkout_dir" in str(exc)


def test_manifest_rejects_escaping_local_path(tmp_path):
    from evaluation.run import EvaluationError, _read_manifest

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["sources"] = [{
        "id": "evil", "kind": "local", "path": "../../../etc",
        "corpus_sha256": "0" * 64, "corpus_files": 1,
        "expectations": {"register": {}},
    }]
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    try:
        _read_manifest(path)
        assert False, "escaping local path accepted"
    except EvaluationError as exc:
        assert "path must be a safe relative path" in str(exc)


def test_manifest_rejects_non_hex_commit(tmp_path):
    # A commit beginning with `-` is parsed by git as an option in a refspec
    # slot; require a 40/64-char hex object name.
    from evaluation.run import EvaluationError, _read_manifest

    poisoned = _poison_first_source({"commit": "--upload-pack=touch /tmp/pwn"})
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(poisoned), encoding="utf-8")
    try:
        _read_manifest(path)
        assert False, "a non-hex commit was accepted"
    except EvaluationError as exc:
        assert "commit must be" in str(exc)


def test_manifest_rejects_oversized_file(tmp_path):
    from evaluation.run import EvaluationError, _read_manifest
    from glossabet.runtime.artifacts import MAX_JSON_BYTES

    path = tmp_path / "corpus.json"
    path.write_bytes(b'{"x":' + b" " * (MAX_JSON_BYTES + 10) + b"1}")
    try:
        _read_manifest(path)
        assert False, "an oversized manifest was accepted"
    except EvaluationError as exc:
        assert "exceeds" in str(exc)
