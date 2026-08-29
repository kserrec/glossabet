"""Reviewer judgment comparison, retention, and offline verification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation.harness.io import (
    file_sha256,
    is_sha256_hex,
    replace_via_temporary,
)
from evaluation.reviewer.contract import (
    DEFAULT_MANIFEST,
    DEFAULT_PACKET,
    DEFAULT_RESULTS,
    DEFAULT_REVIEW_RESULTS,
    DEFAULT_REVIEWED_PACKETS,
    REVIEW_SCHEMA_VERSION,
    SECONDARY_USEFULNESS_THRESHOLD,
    TRACE_LIMIT_CEILINGS,
    TRACE_LIMITS,
    ReviewerEvaluationError,
    json_sha256,
    read_json,
    reviewer_input_identity,
)
from evaluation.reviewer.packet import (
    expected_packet,
    packet_genuineness_errors,
    packet_output_identity,
    same_review_payload,
)
from evaluation.reviewer.trace import is_packet_only_command


def _primary_labels(manifest: dict) -> dict[str, bool]:
    labels: dict[str, bool] = {}
    for source in manifest["sources"]:
        source_id = source["id"]
        for surface in ("terminology", "drift", "structural"):
            expectation = source.get("expectations", {}).get(surface)
            if not isinstance(expectation, dict):
                continue
            for item in expectation.get("correct", []):
                key = f"{source_id}|{surface}|{item['key']}"
                if key in labels:
                    raise ReviewerEvaluationError(
                        f"duplicate primary review key: {key}"
                    )
                labels[key] = item["useful"]
    return labels


def _normalized_judgments(response: dict, expected_keys: list[str]) -> list[dict]:
    raw = response.get("judgments")
    if not isinstance(raw, list):
        raise ReviewerEvaluationError("review response needs a judgments list")
    judgments: dict[str, dict] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise ReviewerEvaluationError(
                "each reviewer judgment must be an object"
            )
        key = item.get("review_key")
        useful = item.get("useful")
        reason = item.get("reason")
        if (
            not isinstance(key, str)
            or key in judgments
            or not isinstance(useful, bool)
            or not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > 1000
        ):
            raise ReviewerEvaluationError(
                f"malformed or duplicate reviewer judgment: {key!r}"
            )
        judgments[key] = {
            "review_key": key,
            "useful": useful,
            "reason": reason.strip(),
        }
    if set(judgments) != set(expected_keys):
        missing = sorted(set(expected_keys) - set(judgments))
        extra = sorted(set(judgments) - set(expected_keys))
        raise ReviewerEvaluationError(
            f"review judgments do not match packet (missing={missing}, extra={extra})"
        )
    return [judgments[key] for key in expected_keys]


def build_review_results(
    packet: dict,
    response: dict,
    manifest: dict,
    *,
    evaluation_results_sha256: str,
    reviewer: dict,
) -> dict:
    return _review_results(
        packet,
        response,
        _primary_labels(manifest),
        evaluation_results_sha256=evaluation_results_sha256,
        reviewer=reviewer,
    )


def _review_results(
    packet: dict,
    response: dict,
    primary: dict[str, bool],
    *,
    evaluation_results_sha256: str,
    reviewer: dict,
) -> dict:
    expected_keys = [item["review_key"] for item in packet["findings"]]
    judgments = _normalized_judgments(response, expected_keys)
    if not judgments:
        raise ReviewerEvaluationError(
            "review results need at least one judgment"
        )
    comparisons = []
    disagreements = []
    secondary_useful = 0
    agreement_count = 0
    for judgment in judgments:
        key = judgment["review_key"]
        primary_useful = primary.get(key, False)
        agrees = primary_useful == judgment["useful"]
        secondary_useful += judgment["useful"]
        agreement_count += agrees
        comparison = {
            "review_key": key,
            "primary_useful": primary_useful,
            "secondary_useful": judgment["useful"],
            "agrees": agrees,
        }
        comparisons.append(comparison)
        if not agrees:
            disagreements.append({
                **comparison,
                "secondary_reason": judgment["reason"],
            })
    count = len(judgments)
    usefulness_rate = round(secondary_useful / count, 4)
    agreement_rate = round(agreement_count / count, 4)
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "packet_sha256": json_sha256(packet),
        "evaluation_results_sha256": evaluation_results_sha256,
        "reviewer": reviewer,
        "judgments": judgments,
        "comparison": {
            "findings_reviewed": count,
            "secondary_useful": secondary_useful,
            "secondary_usefulness_rate": usefulness_rate,
            "secondary_usefulness_threshold": SECONDARY_USEFULNESS_THRESHOLD,
            "secondary_usefulness_passed": (
                usefulness_rate >= SECONDARY_USEFULNESS_THRESHOLD
            ),
            "agreement_count": agreement_count,
            "agreement_rate": agreement_rate,
            "comparisons": comparisons,
            "disagreements": disagreements,
        },
    }


def publish_review_artifacts(
    result: dict,
    output_path: Path,
    reviewed_packet: bytes,
    reviewed_packets: Path,
) -> None:
    """Retain immutable input before atomically committing its result."""
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    packet_sha256 = hashlib.sha256(reviewed_packet).hexdigest()
    reviewed_packet_path = reviewed_packets / f"{packet_sha256}.json"

    if reviewed_packet_path.exists():
        if (
            reviewed_packet_path.is_symlink()
            or reviewed_packet_path.read_bytes() != reviewed_packet
        ):
            raise ReviewerEvaluationError(
                "retained reviewed packet conflicts with its content digest"
            )
    else:
        def write_packet_copy(temporary: Path) -> None:
            temporary.write_bytes(reviewed_packet)

        replace_via_temporary(reviewed_packet_path, write_packet_copy)

    def write_result(temporary: Path) -> None:
        temporary.write_text(serialized, encoding="utf-8")

    # The result is the commit marker: a retained-packet failure must leave the
    # previously accepted result untouched.
    replace_via_temporary(output_path, write_result)


def _trace_output_matches_packet(
    packet: dict,
    packet_output: str,
    output_characters: object,
    output_sha256: object,
    reviewed_packets: Path,
) -> bool:
    """Bind one trace to the current or its exact retained blinded packet."""
    identity = (output_characters, output_sha256)
    if identity == packet_output_identity(packet_output):
        return True
    if (
        not isinstance(output_characters, int)
        or isinstance(output_characters, bool)
        or not is_sha256_hex(output_sha256)
    ):
        return False
    reviewed_packet_path = reviewed_packets / f"{output_sha256}.json"
    try:
        reviewed_packet = read_json(
            reviewed_packet_path,
            "retained reviewed packet",
        )
        reviewed_output = reviewed_packet_path.read_text(encoding="utf-8")
    except (ReviewerEvaluationError, OSError, UnicodeError):
        return False
    return (
        packet_output_identity(reviewed_output) == identity
        and not packet_genuineness_errors(reviewed_packet)
        and same_review_payload(packet, reviewed_packet)
    )


def _stored_primary_labels(results: dict) -> dict[str, bool]:
    comparison = results.get("comparison")
    comparisons = (
        comparison.get("comparisons") if isinstance(comparison, dict) else None
    )
    if not isinstance(comparisons, list):
        raise ReviewerEvaluationError(
            "reviewer comparison records are missing or malformed"
        )
    labels: dict[str, bool] = {}
    for item in comparisons:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("review_key"), str)
            or not isinstance(item.get("primary_useful"), bool)
            or item["review_key"] in labels
        ):
            raise ReviewerEvaluationError(
                "reviewer comparison records are missing or malformed"
            )
        labels[item["review_key"]] = item["primary_useful"]
    return labels


def verify_results(
    review_path: Path = DEFAULT_REVIEW_RESULTS,
    packet_path: Path = DEFAULT_PACKET,
    manifest_path: Path = DEFAULT_MANIFEST,
    evaluation_path: Path = DEFAULT_RESULTS,
    *,
    current: bool = False,
    reviewed_packets: Path = DEFAULT_REVIEWED_PACKETS,
) -> list[str]:
    """Check committed second-reviewer evidence.

    Always checks genuineness: the stored packet stays blinded, the recorded
    judgments and comparisons are internally consistent, and the usefulness
    threshold passes. With ``current=True`` (the release gate) it additionally
    checks currency: the packet and digests match the current evaluation
    results, manifest, and reviewer inputs.
    """
    errors: list[str] = []
    packet = read_json(packet_path, "reviewer packet")
    packet_output = packet_path.read_text(encoding="utf-8")
    errors.extend(packet_genuineness_errors(packet))
    results = read_json(review_path, "reviewer results")
    if results.get("schema_version") != REVIEW_SCHEMA_VERSION:
        errors.append("reviewer result schema is stale")
    reviewer = results.get("reviewer")
    execution = reviewer.get("execution", {}) if isinstance(reviewer, dict) else {}
    trace = reviewer.get("trace") if isinstance(reviewer, dict) else None
    identity = (
        reviewer.get("input_identity") if isinstance(reviewer, dict) else None
    )
    if current:
        identity_ok = identity == reviewer_input_identity()
    else:
        identity_ok = (
            isinstance(identity, dict)
            and set(identity)
            == {"evaluator_sha256", "prompt_sha256", "response_schema_sha256"}
            and all(is_sha256_hex(value) for value in identity.values())
        )
    recorded_limits = (
        execution.get("trace_limits") if isinstance(execution, dict) else None
    )
    if current:
        limits_ok = recorded_limits == TRACE_LIMITS
    else:
        # Genuineness validates the recorded limits' shape only; the exact
        # values are the evaluator's to demand at the release gate, so an
        # evaluator constant edit does not invalidate lagging evidence.
        limits_ok = (
            isinstance(recorded_limits, dict)
            and set(recorded_limits) == set(TRACE_LIMITS)
            and all(
                isinstance(value, int)
                and not isinstance(value, bool)
                and 0 < value <= TRACE_LIMIT_CEILINGS[key]
                for key, value in recorded_limits.items()
            )
        )
    if not limits_ok:
        recorded_limits = None
    bounds = recorded_limits or {
        "commands": 0,
        "stored_command_characters": 0,
        "stored_output_characters": 0,
    }
    if (
        not isinstance(reviewer, dict)
        or reviewer.get("kind") != "codex-exec"
        or reviewer.get("blinded_to_primary_labels") is not True
        or not isinstance(reviewer.get("codex_version"), str)
        or not identity_ok
        or not limits_ok
        or not isinstance(execution, dict)
        or {
            key: value
            for key, value in execution.items()
            if key != "trace_limits"
        }
        != {
            "ephemeral": True,
            "sandbox": "read-only",
            "approval_policy": "never",
            "repository_available": False,
        }
    ):
        errors.append("reviewer identity or blinding metadata is malformed")
    if (
        not isinstance(trace, list)
        or not trace
        or len(trace) > bounds["commands"]
    ):
        errors.append("second-reviewer trace is missing or unbounded")
    else:
        for command in trace:
            command_text = (
                command.get("command") if isinstance(command, dict) else None
            )
            if (
                not isinstance(command, dict)
                or not isinstance(command_text, str)
                or not is_packet_only_command(command_text)
                or command.get("cwd") not in (None, "<REVIEW_WORKSPACE>")
                or len(command_text)
                > bounds["stored_command_characters"] + 1
                or len(str(command.get("output_preview", "")))
                > bounds["stored_output_characters"] + 1
                or command.get("status") != "completed"
                or command.get("exit_code") != 0
                or not _trace_output_matches_packet(
                    packet,
                    packet_output,
                    command.get("output_characters"),
                    command.get("output_sha256"),
                    reviewed_packets,
                )
            ):
                errors.append("second-reviewer trace is missing or unbounded")
                break
    if not is_sha256_hex(results.get("evaluation_results_sha256")):
        errors.append("reviewer evidence digests are malformed")
    response = {"judgments": results.get("judgments")}
    try:
        rebuilt = _review_results(
            packet,
            response,
            _stored_primary_labels(results),
            evaluation_results_sha256=results.get("evaluation_results_sha256"),
            reviewer=reviewer if isinstance(reviewer, dict) else {},
        )
    except (ReviewerEvaluationError, KeyError, TypeError) as exc:
        errors.append(str(exc) or "reviewer results are malformed")
    else:
        if results != rebuilt:
            errors.append("reviewer comparisons or input digests are stale")
        if rebuilt["comparison"]["secondary_usefulness_passed"] is not True:
            errors.append("second-reviewer usefulness threshold does not pass")

    if current:
        try:
            expected = expected_packet(manifest_path, evaluation_path)
        except ReviewerEvaluationError as exc:
            errors.append(str(exc))
            expected = None
        if expected is not None:
            if packet != expected:
                errors.append(
                    "reviewer packet is stale or contains non-blinded fields"
                )
            manifest = read_json(manifest_path, "evaluation manifest")
            try:
                rebuilt_current = build_review_results(
                    expected,
                    response,
                    manifest,
                    evaluation_results_sha256=file_sha256(evaluation_path),
                    reviewer=reviewer if isinstance(reviewer, dict) else {},
                )
            except ReviewerEvaluationError as exc:
                errors.append(str(exc))
            else:
                if results != rebuilt_current:
                    errors.append(
                        "reviewer comparisons or input digests are stale"
                    )
    return errors
