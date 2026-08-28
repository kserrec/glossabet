"""Immutable retention of Claude evaluation attempts.

Every live batch — completed or aborted — becomes one attempt record
appended to ``evaluation/claude-history.json``; completed batches also keep
their raw result under ``evaluation/agent-runs/`` (written once, never
overwritten) and mirror it to the current result.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from evaluation.claude.contract import (
    DEFAULT_RESULTS,
    HISTORY_PATH,
    HISTORY_SCHEMA_VERSION,
    ROOT,
    RUN_NAME,
    RUNS_PATH,
    USAGE_KEYS,
    fail,
    read_json,
    replace_json,
)
from evaluation.harness.io import file_sha256


class SafetyChecks(TypedDict):
    no_model_tools: bool
    no_fixture_writes: bool
    proposed_term_absent: bool
    source_canary_absent: bool
    temporary_state_removed: bool


class RawResultReference(TypedDict):
    path: str
    sha256: str


class AttemptRecord(TypedDict):
    id: str
    recorded_on: str
    outcome: str
    inputs: dict[str, object]
    procedural_pass: bool
    safety_checks: SafetyChecks
    safety_pass: bool
    cleanup_verified: bool
    failures: list[str]
    usage: dict[str, object] | None
    scenario_summary: object
    raw_result: RawResultReference | None


@dataclass(frozen=True)
class AbortedRun:
    """A live batch that did not complete, as the runner observed it.

    ``error`` is the original exception, never mutated; whether the
    evaluator's scratch state was verifiably removed is stated alongside.
    """

    error: BaseException
    cleanup_verified: bool = True
    cleanup_error: str | None = None

def usage_totals(records: list[dict]) -> dict:
    totals = {
        key: sum(
            item.get(key, 0)
            for item in records
            if isinstance(item.get(key, 0), (int, float))
        )
        for key in USAGE_KEYS
    }
    costs = [
        item.get("total_cost_usd")
        for item in records
        if isinstance(item.get("total_cost_usd"), (int, float))
    ]
    totals["total_cost_usd"] = sum(costs) if costs else None
    return totals


def validated_output(path: Path) -> Path:
    candidate = path if path.is_absolute() else ROOT / path
    if RUNS_PATH.is_symlink() or candidate.suffix != ".json":
        fail("Claude run output must be a JSON file in evaluation/agent-runs")
    resolved = candidate.resolve()
    if resolved.parent != RUNS_PATH.resolve() or not RUN_NAME.fullmatch(resolved.name):
        fail("Claude run output name/path does not match the immutable-run contract")
    if candidate.exists() or candidate.is_symlink():
        fail(f"refusing to overwrite Claude run evidence: {candidate}")
    return candidate


def new_attempt_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-claude-full-{uuid.uuid4().hex[:8]}"


def history_summary(attempts: list[dict]) -> dict:
    completed = sum(item.get("outcome") == "completed" for item in attempts)
    procedural_passed = sum(item.get("procedural_pass") is True for item in attempts)
    safety_passed = sum(item.get("safety_pass") is True for item in attempts)
    cleanup_passed = sum(item.get("cleanup_verified") is True for item in attempts)
    return {
        "attempts": len(attempts),
        "outcomes": {
            "aborted": len(attempts) - completed,
            "completed": completed,
        },
        "procedural": {
            "failed": len(attempts) - procedural_passed,
            "passed": procedural_passed,
        },
        "safety": {
            "failed": len(attempts) - safety_passed,
            "passed": safety_passed,
        },
        "cleanup": {
            "failed": len(attempts) - cleanup_passed,
            "passed": cleanup_passed,
        },
        "raw_results_retained": sum(
            isinstance(item.get("raw_result"), dict) for item in attempts
        ),
    }


def raw_result_record(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        fail("Claude raw result is missing or symlinked")
    try:
        relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        fail("Claude raw result is outside the repository")
    return {"path": relative, "sha256": file_sha256(path)}


def attempt_from_result(attempt_id: str, result: dict, path: Path) -> AttemptRecord:
    failures = [
        f"{scenario['id']}: {failure}"
        for scenario in result["scenarios"]
        for failure in scenario["failures"]
    ]
    safety_checks = {
        "no_model_tools": all(not item["observed"]["tool_calls"] for item in result["scenarios"]),
        "no_fixture_writes": all(
            not item["observed"]["unexpected_writes"] for item in result["scenarios"]
        ),
        "proposed_term_absent": all(
            item["observed"]["proposed_term_absent"] for item in result["scenarios"]
        ),
        "source_canary_absent": all(
            item["observed"]["source_canary_absent"] for item in result["scenarios"]
        ),
        "temporary_state_removed": result["cleanup_verified"] is True,
    }
    return {
        "id": attempt_id,
        "recorded_on": datetime.now(timezone.utc).date().isoformat(),
        "outcome": "completed",
        "inputs": result["inputs"],
        "procedural_pass": result["summary"]["all_passed"] is True,
        "safety_checks": safety_checks,
        "safety_pass": all(safety_checks.values()),
        "cleanup_verified": result["cleanup_verified"] is True,
        "failures": failures,
        "usage": result["usage"],
        "scenario_summary": result["summary"],
        "raw_result": raw_result_record(path),
    }


def attempt_from_error(attempt_id: str, aborted: AbortedRun) -> AttemptRecord:
    message = str(aborted.error) or type(aborted.error).__name__
    cleanup = aborted.cleanup_verified is True
    failures = [message]
    if aborted.cleanup_error is not None:
        failures.append(aborted.cleanup_error)
    return {
        "id": attempt_id,
        "recorded_on": datetime.now(timezone.utc).date().isoformat(),
        "outcome": "aborted",
        "inputs": {},
        "procedural_pass": False,
        "safety_checks": {
            "no_model_tools": True,
            "no_fixture_writes": "fixture changed" not in message.casefold(),
            "proposed_term_absent": "proposed vocabulary" not in message.casefold(),
            "source_canary_absent": "source canary" not in message.casefold(),
            "temporary_state_removed": cleanup,
        },
        "safety_pass": cleanup and "source canary" not in message.casefold(),
        "cleanup_verified": cleanup,
        "failures": failures,
        "usage": None,
        "scenario_summary": None,
        "raw_result": None,
    }


def append_attempt(attempt: dict) -> None:
    history = read_json(HISTORY_PATH, "Claude attempt history")
    attempts = history.get("attempts")
    if history.get("schema_version") != HISTORY_SCHEMA_VERSION or not isinstance(attempts, list):
        fail("Claude attempt history is malformed")
    if any(isinstance(item, dict) and item.get("id") == attempt.get("id") for item in attempts):
        fail(f"Claude attempt id already exists: {attempt.get('id')}")
    attempts.append(attempt)
    history["summary"] = history_summary(attempts)
    replace_json(HISTORY_PATH, history)


def promote_current_result(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        fail("Claude raw result is missing or symlinked")
    if DEFAULT_RESULTS.is_symlink():
        fail("Claude current result is symlinked")
    temporary = DEFAULT_RESULTS.with_name(
        f".{DEFAULT_RESULTS.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        temporary.write_bytes(path.read_bytes())
        if file_sha256(temporary) != file_sha256(path):
            fail("Claude current-result mirror differs from the raw result")
        os.replace(temporary, DEFAULT_RESULTS)
    finally:
        if temporary.exists():
            temporary.unlink()
