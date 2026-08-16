"""The blinded second-reviewer lane remains independent and reproducible."""

import json
from copy import deepcopy
from pathlib import Path

from evaluation.review import verify_results


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "evaluation" / "reviewer-packet.json"
RESULTS = ROOT / "evaluation" / "reviewer-results.json"


def _contains_useful_key(value):
    if isinstance(value, dict):
        return "useful" in value or any(
            _contains_useful_key(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_useful_key(item) for item in value)
    return False


def test_committed_second_reviewer_evidence_is_genuine_and_blinded():
    assert verify_results(RESULTS, PACKET) == []
    packet = json.loads(PACKET.read_text(encoding="utf-8"))
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert not _contains_useful_key(packet["findings"])
    assert results["reviewer"]["blinded_to_primary_labels"] is True
    assert results["comparison"]["findings_reviewed"] == len(packet["findings"])
    assert results["comparison"]["secondary_usefulness_passed"] is True
    assert isinstance(results["comparison"]["disagreements"], list)


def test_reviewer_verifier_reports_empty_evidence_instead_of_crashing(
    tmp_path,
):
    packet = {
        "schema_version": 1,
        "evaluation_manifest_sha256": "0" * 64,
        "engine": {},
        "question": "q",
        "sources": [],
        "findings": [],
    }
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    mutated = deepcopy(results)
    mutated["judgments"] = []
    packet_path = tmp_path / "packet.json"
    results_path = tmp_path / "results.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    results_path.write_text(json.dumps(mutated), encoding="utf-8")

    errors = verify_results(results_path, packet_path)
    assert any("at least one judgment" in error for error in errors)
    assert any("findings are missing or malformed" in error for error in errors)


def test_reviewer_verifier_rejects_tampered_comparison(tmp_path):
    result = json.loads(RESULTS.read_text(encoding="utf-8"))
    mutated = deepcopy(result)
    mutated["comparison"]["agreement_count"] += 1
    path = tmp_path / "reviewer-results.json"
    path.write_text(json.dumps(mutated), encoding="utf-8")
    assert any(
        "comparisons or input digests are stale" in error
        for error in verify_results(path, PACKET)
    )


def test_genuine_verification_tolerates_evaluator_limit_constant_changes(
    monkeypatch,
):
    from evaluation import review

    monkeypatch.setattr(
        review,
        "TRACE_LIMITS",
        {
            **review.TRACE_LIMITS,
            "stored_output_characters": (
                review.TRACE_LIMITS["stored_output_characters"] + 1
            ),
        },
    )
    assert review.verify_results(RESULTS, PACKET) == []
    assert any(
        "identity or blinding metadata is malformed" in error
        for error in review.verify_results(RESULTS, PACKET, current=True)
    )


def test_reviewer_verifier_checks_input_currency_only_at_the_release_gate(
    tmp_path,
):
    result = json.loads(RESULTS.read_text(encoding="utf-8"))
    lagging = deepcopy(result)
    lagging["reviewer"]["input_identity"]["evaluator_sha256"] = "0" * 64
    path = tmp_path / "lagging-identity.json"
    path.write_text(json.dumps(lagging), encoding="utf-8")

    genuine_errors = verify_results(path, PACKET)
    assert not any(
        "identity or blinding metadata is malformed" in error
        for error in genuine_errors
    )
    current_errors = verify_results(path, PACKET, current=True)
    assert any(
        "identity or blinding metadata is malformed" in error
        for error in current_errors
    )

    malformed = deepcopy(result)
    malformed["reviewer"]["input_identity"]["evaluator_sha256"] = "not-a-digest"
    malformed_path = tmp_path / "malformed-identity.json"
    malformed_path.write_text(json.dumps(malformed), encoding="utf-8")
    assert any(
        "identity or blinding metadata is malformed" in error
        for error in verify_results(malformed_path, PACKET)
    )
