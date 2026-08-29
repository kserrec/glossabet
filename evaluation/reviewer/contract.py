"""Paths, formats, limits, and shared primitives for the reviewer lane."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import NoReturn

from evaluation.harness.identity import lane_source_identity
from evaluation.harness.io import file_sha256, read_json_object
from glossabet.runtime.artifacts import MAX_JSON_BYTES

ROOT = Path(__file__).resolve().parents[2]

PACKET_SCHEMA_VERSION = 1
REVIEW_SCHEMA_VERSION = 2
DEFAULT_MANIFEST = ROOT / "evaluation" / "corpus.json"
DEFAULT_RESULTS = ROOT / "evaluation" / "results.json"
DEFAULT_PACKET = ROOT / "evaluation" / "reviewer-packet.json"
DEFAULT_REVIEWED_PACKETS = ROOT / "evaluation" / "reviewer-reviewed-packets"
DEFAULT_REVIEW_RESULTS = ROOT / "evaluation" / "reviewer-results.json"
PROMPT_PATH = ROOT / "evaluation" / "reviewer-prompt.md"
RESPONSE_SCHEMA_PATH = ROOT / "evaluation" / "reviewer-response-schema.json"

SECONDARY_USEFULNESS_THRESHOLD = 0.8
# Generous absolute ceilings behind any recorded trace limits: genuine
# verification accepts lagging limit values, never unbounded ones.
TRACE_LIMIT_CEILINGS = {
    "jsonl_bytes": 100_000_000,
    "events": 10_000,
    "commands": 100,
    "stored_command_characters": 100_000,
    "stored_output_characters": 100_000,
}
TRACE_LIMITS = {
    "jsonl_bytes": 4_000_000,
    "events": 100,
    "commands": 3,
    "stored_command_characters": 1000,
    "stored_output_characters": 1000,
}


class ReviewerEvaluationError(ValueError):
    """The blinded review input, run, or retained result broke its contract."""


def fail(message: str) -> NoReturn:
    raise ReviewerEvaluationError(message)


def read_json(path: Path, label: str) -> dict:
    return read_json_object(path, label, max_bytes=MAX_JSON_BYTES, fail=fail)


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def json_sha256(value: dict) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def reviewer_input_identity() -> dict:
    return {
        "evaluator_sha256": lane_source_identity("reviewer"),
        "prompt_sha256": file_sha256(PROMPT_PATH),
        "response_schema_sha256": file_sha256(RESPONSE_SCHEMA_PATH),
    }
