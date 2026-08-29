"""The blinded second-reviewer lane remains independent and reproducible."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from evaluation.reviewer import contract, results, trace
from evaluation.reviewer.contract import ReviewerEvaluationError
from evaluation.reviewer.results import verify_results

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "evaluation" / "reviewer-packet.json"
REVIEWED_PACKETS = ROOT / "evaluation" / "reviewer-reviewed-packets"
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
    packet_output = PACKET.read_text(encoding="utf-8")
    packet = json.loads(PACKET.read_text(encoding="utf-8"))
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    trace = results["reviewer"]["trace"][0]
    reviewed_path = REVIEWED_PACKETS / f"{trace['output_sha256']}.json"
    reviewed_output = reviewed_path.read_text(encoding="utf-8")
    reviewed_packet = json.loads(reviewed_output)
    assert not _contains_useful_key(packet["findings"])
    assert (len(reviewed_output), hashlib.sha256(reviewed_output.encode()).hexdigest()) == (
        trace["output_characters"],
        trace["output_sha256"],
    )
    assert hashlib.sha256(packet_output.encode()).hexdigest() != trace["output_sha256"]
    for key in ("question", "sources", "findings"):
        assert reviewed_packet[key] == packet[key]
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
    monkeypatch.setattr(
        results,
        "TRACE_LIMITS",
        {
            **results.TRACE_LIMITS,
            "stored_output_characters": (
                results.TRACE_LIMITS["stored_output_characters"] + 1
            ),
        },
    )
    assert results.verify_results(RESULTS, PACKET) == []
    assert any(
        "identity or blinding metadata is malformed" in error
        for error in results.verify_results(RESULTS, PACKET, current=True)
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


def test_bounded_text_redacts_repo_root_and_home(tmp_path):
    # The committed reviewer-results.json must not carry the maintainer's repo
    # root or home directory even when the reviewer echoes an absolute path the
    # workspace replacement never anticipated (mirrors agent_eval redaction).
    workspace = tmp_path / "review-workspace"
    text = (
        f"ran {contract.ROOT}/scripts/x and {Path.home()}/.local/bin/codex "
        f"in {workspace}/pkg"
    )
    out = trace.bounded_text(text, workspace, limit=10_000)
    assert str(contract.ROOT) not in out
    assert str(Path.home()) not in out
    assert "<REPO>" in out and "<HOME>" in out
    assert "<REVIEW_WORKSPACE>" in out


def test_live_reviewer_trace_rejects_a_packet_read_combined_with_another_file(
    tmp_path,
):
    (tmp_path / "reviewer-packet.json").write_text(
        "blinded packet\n", encoding="utf-8"
    )
    raw = json.dumps({
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": "/usr/bin/zsh -lc 'cat reviewer-packet.json /etc/passwd'",
            "aggregated_output": "packet plus unrelated file",
            "exit_code": 0,
            "status": "completed",
        },
    })

    with pytest.raises(ReviewerEvaluationError, match="outside the blinded packet"):
        trace.parse_reviewer_trace(raw, tmp_path)

    raw = raw.replace(
        "/usr/bin/zsh -lc 'cat reviewer-packet.json /etc/passwd'",
        "/tmp/cat reviewer-packet.json",
    )
    with pytest.raises(ReviewerEvaluationError, match="outside the blinded packet"):
        trace.parse_reviewer_trace(raw, tmp_path)


def test_live_reviewer_trace_binds_cwd_and_output_to_the_isolated_packet(tmp_path):
    packet_output = "blinded packet\n"
    (tmp_path / "reviewer-packet.json").write_text(
        packet_output, encoding="utf-8"
    )
    event = {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": "/usr/bin/zsh -lc 'cat reviewer-packet.json'",
            "aggregated_output": packet_output,
            "cwd": None,
            "exit_code": 0,
            "status": "completed",
        },
    }

    commands, _usage = trace.parse_reviewer_trace(json.dumps(event), tmp_path)
    assert commands[0]["output_sha256"] == hashlib.sha256(
        packet_output.encode()
    ).hexdigest()

    outside = deepcopy(event)
    outside["item"]["cwd"] = str(tmp_path.parent)
    with pytest.raises(ReviewerEvaluationError, match="isolated workspace"):
        trace.parse_reviewer_trace(json.dumps(outside), tmp_path)

    unrelated = deepcopy(event)
    unrelated["item"]["aggregated_output"] = "PRIMARY LABELS FROM ANOTHER FILE"
    with pytest.raises(ReviewerEvaluationError, match="did not match"):
        trace.parse_reviewer_trace(json.dumps(unrelated), tmp_path)

    incomplete = deepcopy(event)
    incomplete["item"]["status"] = "failed"
    with pytest.raises(ReviewerEvaluationError, match="did not complete"):
        trace.parse_reviewer_trace(json.dumps(incomplete), tmp_path)


def test_reviewer_publication_leaves_prior_result_when_packet_retention_fails(
    tmp_path,
    monkeypatch,
):
    packet = tmp_path / "packet.json"
    retained = tmp_path / "retained"
    output = tmp_path / "results.json"
    packet.write_text("new packet\n", encoding="utf-8")
    output.write_text("prior accepted result\n", encoding="utf-8")

    real_replace = results.replace_via_temporary

    def fail_retention(target, write_payload):
        if target.parent == retained:
            raise OSError("synthetic retained-packet failure")
        return real_replace(target, write_payload)

    monkeypatch.setattr(results, "replace_via_temporary", fail_retention)

    with pytest.raises(OSError, match="synthetic retained-packet failure"):
        results.publish_review_artifacts(
            {}, output, packet.read_bytes(), retained
        )

    assert output.read_text(encoding="utf-8") == "prior accepted result\n"
    assert not list(retained.glob("*.json"))
    assert not list(retained.glob("*.tmp"))


def test_reviewer_result_failure_preserves_the_prior_evidence_pair(
    tmp_path,
    monkeypatch,
):
    packet_doc = json.loads(PACKET.read_text(encoding="utf-8"))
    packet = tmp_path / "packet.json"
    # Same reviewed payload and packet semantics, but different exact bytes.
    packet.write_text(json.dumps(packet_doc), encoding="utf-8")
    output = tmp_path / "results.json"
    prior_result = RESULTS.read_bytes()
    output.write_bytes(prior_result)
    retained = tmp_path / "retained"
    retained.mkdir()
    trace_sha256 = json.loads(prior_result)["reviewer"]["trace"][0][
        "output_sha256"
    ]
    prior_packet = REVIEWED_PACKETS / f"{trace_sha256}.json"
    (retained / prior_packet.name).write_bytes(prior_packet.read_bytes())

    assert results.verify_results(
        output,
        packet,
        reviewed_packets=retained,
    ) == []
    real_replace = results.replace_via_temporary

    def fail_result(target, write_payload):
        if target == output:
            raise OSError("synthetic result-commit failure")
        return real_replace(target, write_payload)

    monkeypatch.setattr(results, "replace_via_temporary", fail_result)

    with pytest.raises(OSError, match="synthetic result-commit failure"):
        results.publish_review_artifacts(
            {}, output, packet.read_bytes(), retained
        )

    new_sha256 = hashlib.sha256(packet.read_bytes()).hexdigest()
    assert output.read_bytes() == prior_result
    assert (retained / prior_packet.name).is_file()
    assert (retained / f"{new_sha256}.json").read_bytes() == packet.read_bytes()
    assert results.verify_results(
        output,
        packet,
        reviewed_packets=retained,
    ) == []


def test_reviewer_verifier_enforces_every_blinding_trace_and_usefulness_gate(tmp_path):
    """The verifier is the release CLI's only word on second-reviewer
    evidence, so each gate it documents must be proven to fire on its own
    input: an unblinded reviewer, a trace that ran anything but reading the
    packet (or too many commands, or a failing one), limits outside their
    ceilings, a packet carrying usefulness labels or a stale schema, and —
    kept consistent with its own recomputation so no other error masks it —
    a usefulness rate below the threshold. Genuineness mode throughout."""
    original = json.loads(RESULTS.read_text(encoding="utf-8"))
    packet = json.loads(PACKET.read_text(encoding="utf-8"))
    assert results.verify_results(RESULTS, PACKET) == []

    def verify(results_doc=None, packet_doc=None):
        results_path = tmp_path / "results.json"
        packet_path = tmp_path / "packet.json"
        results_path.write_text(json.dumps(results_doc or original), encoding="utf-8")
        packet_path.write_text(json.dumps(packet_doc or packet), encoding="utf-8")
        return results.verify_results(results_path, packet_path)

    def mutated(mutate):
        doc = deepcopy(original)
        mutate(doc)
        return doc

    metadata = "reviewer identity or blinding metadata is malformed"
    trace = "second-reviewer trace is missing or unbounded"
    for mutate, expected in (
        (lambda d: d["reviewer"].__setitem__("blinded_to_primary_labels", False), metadata),
        (lambda d: d["reviewer"].__setitem__("kind", "manual"), metadata),
        (lambda d: d["reviewer"]["execution"].__setitem__("sandbox", "workspace-write"), metadata),
        (lambda d: d["reviewer"]["execution"].__setitem__("repository_available", True), metadata),
        (lambda d: d["reviewer"]["execution"]["trace_limits"].__setitem__("commands", 0), metadata),
        (lambda d: d["reviewer"]["execution"]["trace_limits"].__setitem__(
            "commands", results.TRACE_LIMIT_CEILINGS["commands"] + 1), metadata),
        (lambda d: d["reviewer"]["input_identity"].__setitem__("prompt_sha256", "nothex"), metadata),
        (lambda d: d["reviewer"].__setitem__("trace", []), trace),
        (lambda d: d["reviewer"].__setitem__(
            "trace", d["reviewer"]["trace"] * (d["reviewer"]["execution"]["trace_limits"]["commands"] + 1)
        ), trace),
        (lambda d: d["reviewer"]["trace"][0].__setitem__("command", "cat evaluation/results.json"), trace),
        (lambda d: d["reviewer"]["trace"][0].__setitem__(
            "command", "cat reviewer-packet.json /etc/passwd"
        ), trace),
        (lambda d: d["reviewer"]["trace"][0].__setitem__("cwd", "/outside"), trace),
        (lambda d: d["reviewer"]["trace"][0].__setitem__(
            "output_sha256", "0" * 64
        ), trace),
        (lambda d: d["reviewer"]["trace"][0].__setitem__("exit_code", 1), trace),
        (lambda d: d["reviewer"]["trace"][0].__setitem__(
            "output_preview", "x" * (d["reviewer"]["execution"]["trace_limits"]["stored_output_characters"] + 2)
        ), trace),
        (lambda d: d.__setitem__("evaluation_results_sha256", "zz"), "evidence digests are malformed"),
        (lambda d: d.__setitem__("schema_version", 0), "result schema is stale"),
    ):
        errors = verify(mutated(mutate))
        assert any(expected in error for error in errors), (expected, errors)

    # Packet gates: labels leaking through, or a stale schema.
    leaking = deepcopy(packet)
    leaking["findings"][0]["useful"] = True
    assert any("contains a usefulness label" in e for e in verify(packet_doc=leaking))
    stale = deepcopy(packet)
    stale["schema_version"] = 0
    assert any("packet schema is stale" in e for e in verify(packet_doc=stale))
    duplicate = deepcopy(original)
    duplicate["comparison"]["comparisons"].append(duplicate["comparison"]["comparisons"][0])
    assert "reviewer comparison records are missing or malformed" in verify(duplicate)

    changed_review_payload = deepcopy(packet)
    changed_review_payload["question"] += " changed"
    assert trace in verify(packet_doc=changed_review_payload)

    # Usefulness threshold: mark every judgment useless and rebuild the
    # comparison honestly, so the only remaining complaint is the threshold.
    useless = deepcopy(original)
    for judgment in useless["judgments"]:
        judgment["useful"] = False
    rebuilt = results._review_results(
        packet, {"judgments": useless["judgments"]},
        results._stored_primary_labels(useless),
        evaluation_results_sha256=useless["evaluation_results_sha256"],
        reviewer=useless["reviewer"],
    )
    errors = verify(rebuilt)
    assert "second-reviewer usefulness threshold does not pass" in errors
    assert not any("comparisons or input digests are stale" in e for e in errors)
