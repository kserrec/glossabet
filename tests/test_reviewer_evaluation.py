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


def test_committed_second_reviewer_evidence_is_current_and_blinded():
    assert verify_results(RESULTS, PACKET) == []
    packet = json.loads(PACKET.read_text(encoding="utf-8"))
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert not _contains_useful_key(packet["findings"])
    assert results["reviewer"]["blinded_to_primary_labels"] is True
    assert results["comparison"]["findings_reviewed"] == len(packet["findings"])
    assert results["comparison"]["secondary_usefulness_passed"] is True
    assert isinstance(results["comparison"]["disagreements"], list)


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
