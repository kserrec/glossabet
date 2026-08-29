"""Construction and integrity rules for blinded reviewer packets."""

from __future__ import annotations

import hashlib
from pathlib import Path

from evaluation.deterministic.results import (
    read_results as read_engine_results,
)
from evaluation.deterministic.results import (
    verify_results as verify_engine_results,
)
from evaluation.harness.io import file_sha256, is_sha256_hex
from evaluation.reviewer.contract import (
    DEFAULT_MANIFEST,
    DEFAULT_RESULTS,
    PACKET_SCHEMA_VERSION,
    ReviewerEvaluationError,
    json_bytes,
)


def contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(contains_key(item, key) for item in value)
    return False


def build_packet(
    evaluation_results: dict,
    *,
    manifest_sha256: str,
) -> dict:
    findings = []
    sources = []
    seen: set[str] = set()
    for case in evaluation_results.get("cases", []):
        if not isinstance(case, dict):
            raise ReviewerEvaluationError("evaluation case is malformed")
        source_id = case.get("id")
        sources.append({"id": source_id, **case.get("source", {})})
        for item in case.get("review_items", []):
            if not isinstance(item, dict):
                raise ReviewerEvaluationError(
                    f"{source_id}: review item is malformed"
                )
            key = item.get("review_key")
            if not isinstance(key, str) or not key or key in seen:
                raise ReviewerEvaluationError(
                    "review keys must be unique non-empty strings"
                )
            seen.add(key)
            if contains_key(item, "useful"):
                raise ReviewerEvaluationError(
                    "review packet input contains a usefulness label"
                )
            findings.append(item)
    if not findings:
        raise ReviewerEvaluationError(
            "review packet needs at least one emitted finding"
        )
    return {
        "schema_version": PACKET_SCHEMA_VERSION,
        "evaluation_manifest_sha256": manifest_sha256,
        "engine": evaluation_results.get("engine"),
        "question": (
            "Would showing this finding to a regular maintainer help a focused "
            "vocabulary review? Correct-but-actionless noise is not useful."
        ),
        "sources": sources,
        "findings": findings,
    }


def expected_packet(
    manifest_path: Path = DEFAULT_MANIFEST,
    evaluation_path: Path = DEFAULT_RESULTS,
) -> dict:
    try:
        engine_errors = verify_engine_results(
            evaluation_path, manifest_path, current=True
        )
        evaluation_results = read_engine_results(evaluation_path)
    except ValueError as exc:
        raise ReviewerEvaluationError(str(exc)) from exc
    if engine_errors:
        raise ReviewerEvaluationError(
            "cannot build reviewer packet from stale evaluation results: "
            + "; ".join(engine_errors)
        )
    return build_packet(
        evaluation_results,
        manifest_sha256=file_sha256(manifest_path),
    )


def write_packet(
    path: Path,
    manifest_path: Path = DEFAULT_MANIFEST,
    evaluation_path: Path = DEFAULT_RESULTS,
) -> dict:
    packet = expected_packet(manifest_path, evaluation_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(packet))
    return packet


def packet_output_identity(output: str) -> tuple[int, str]:
    return len(output), hashlib.sha256(output.encode()).hexdigest()


def same_review_payload(left: dict, right: dict) -> bool:
    """Compare the packet fields that the retained judgments evaluate."""
    keys = ("question", "sources", "findings")
    return all(
        key in left and key in right and left[key] == right[key]
        for key in keys
    )


def packet_genuineness_errors(packet: dict) -> list[str]:
    errors: list[str] = []
    if packet.get("schema_version") != PACKET_SCHEMA_VERSION:
        errors.append("reviewer packet schema is stale")
    if not is_sha256_hex(packet.get("evaluation_manifest_sha256")):
        errors.append("reviewer packet manifest digest is malformed")
    findings = packet.get("findings")
    well_formed = isinstance(findings, list) and bool(findings)
    seen: set[str] = set()
    for item in findings if well_formed else []:
        key = item.get("review_key") if isinstance(item, dict) else None
        if not isinstance(key, str) or not key or key in seen:
            well_formed = False
            break
        seen.add(key)
        if contains_key(item, "useful"):
            errors.append("reviewer packet contains a usefulness label")
            break
    if not well_formed:
        errors.append("reviewer packet findings are missing or malformed")
    return errors
