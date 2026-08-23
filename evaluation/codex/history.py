"""Immutable retention of Codex evaluation attempts.

Every live run or probe — completed or aborted — becomes one attempt record
appended to ``evaluation/agent-history.json``; completed full runs also keep
their raw result under ``evaluation/agent-runs/`` and mirror it to the
current result. Records are only ever appended, never rewritten.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict

from evaluation.codex.artifact import artifact_snapshot
from evaluation.codex.contract import (
    DEFAULT_RESULTS,
    HISTORY_PATH,
    HISTORY_SCHEMA_VERSION,
    ROOT,
    RUNS_PATH,
    SENSITIVE_CANARY,
    fail,
    read_json,
    write_json,
)
from evaluation.codex.results import (
    SafetyChecks,
    UsageTotals,
    history_summary,
    input_identity,
    result_safety_checks,
    result_safety_errors,
    trace_ran_inspect,
    usage_totals,
)
from evaluation.harness.io import file_sha256, replace_via_temporary

CheckOutcome = Literal["passed", "failed", "not_run"]


class ProceduralChecks(TypedDict):
    plugin_preflight: CheckOutcome
    plugin_scenarios: CheckOutcome
    missing_cli_boundary: CheckOutcome


class RawResultReference(TypedDict):
    path: str
    sha256: str


class AttemptRecord(TypedDict):
    id: str
    recorded_on: str
    kind: str
    inputs: dict[str, object]
    outcome: str
    evidence_basis: str
    checks: ProceduralChecks
    procedural_pass: bool
    safety_checks: SafetyChecks
    safety_pass: bool
    cleanup_verified: bool
    failures: list[str]
    evidence: list[str]
    usage: UsageTotals | None
    scenario_summary: object
    raw_result: RawResultReference | None

def write_history(value: dict) -> None:
    replace_via_temporary(
        HISTORY_PATH, lambda temporary: write_json(temporary, value)
    )


def promote_current_result(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        fail("completed agent result is missing or symlinked")
    if DEFAULT_RESULTS.is_symlink():
        fail("current agent result is symlinked")

    def write_mirror(temporary: Path) -> None:
        temporary.write_bytes(path.read_bytes())
        if file_sha256(temporary) != file_sha256(path):
            fail("current agent result mirror differs from retained raw result")

    replace_via_temporary(DEFAULT_RESULTS, write_mirror)


def new_attempt_id(kind: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{kind}-{uuid.uuid4().hex[:8]}"


def validated_run_output(path: Path) -> Path:
    candidate = path if path.is_absolute() else ROOT / path
    if RUNS_PATH.is_symlink() or candidate.suffix != ".json":
        fail("agent run output must be a JSON file under evaluation/agent-runs")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(RUNS_PATH.resolve())
    except ValueError:
        fail("agent run output must stay under evaluation/agent-runs")
    if candidate.exists() or candidate.is_symlink():
        fail(f"refusing to overwrite existing agent result: {candidate}")
    return candidate


def raw_result_record(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        fail("completed agent result is missing or symlinked")
    try:
        relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        fail("completed agent result is outside the repository")
    return {"path": relative, "sha256": file_sha256(path)}


def append_attempt(attempt: dict) -> None:
    if HISTORY_PATH.is_symlink():
        fail("agent attempt history is symlinked")
    if HISTORY_PATH.exists():
        history = read_json(HISTORY_PATH, "agent attempt history")
    else:
        history = {
            "schema_version": HISTORY_SCHEMA_VERSION,
            "current_artifact": {},
            "attempts": [],
            "summary": history_summary([]),
        }
    attempts = history.get("attempts")
    if history.get("schema_version") != HISTORY_SCHEMA_VERSION or not isinstance(
        attempts, list
    ):
        fail("agent attempt history is malformed")
    if any(
        item.get("id") == attempt.get("id")
        for item in attempts
        if isinstance(item, dict)
    ):
        fail(f"agent attempt id already exists: {attempt.get('id')}")
    attempts.append(attempt)
    history["summary"] = history_summary(attempts)
    write_history(history)


def refresh_artifact_record() -> dict:
    if HISTORY_PATH.is_symlink():
        fail("agent attempt history is symlinked")
    history = read_json(HISTORY_PATH, "agent attempt history")
    attempts = history.get("attempts")
    if history.get("schema_version") != HISTORY_SCHEMA_VERSION or not isinstance(
        attempts, list
    ):
        fail("agent attempt history is malformed")
    history["current_artifact"] = artifact_snapshot()
    history["summary"] = history_summary(attempts)
    write_history(history)
    return history["current_artifact"]


def attempt_from_result(attempt_id: str, result: dict, path: Path) -> dict:
    missing = next(
        (
            scenario
            for scenario in result.get("scenarios", [])
            if isinstance(scenario, dict) and scenario.get("id") == "missing-cli"
        ),
        {},
    )
    plugin_scenarios = [
        scenario
        for scenario in result.get("scenarios", [])
        if isinstance(scenario, dict) and scenario.get("id") != "missing-cli"
    ]
    safety_checks = result_safety_checks(result)
    safety_errors = result_safety_errors(result)
    failures = [
        f"{scenario.get('id', '<unknown>')}: {failure}"
        for scenario in result.get("scenarios", [])
        if isinstance(scenario, dict)
        for failure in scenario.get("failures", [])
        if isinstance(failure, str)
    ]
    return {
        "id": attempt_id,
        "recorded_on": datetime.now(timezone.utc).date().isoformat(),
        "kind": "full",
        "inputs": result.get("inputs", {}),
        "outcome": "completed",
        "evidence_basis": "retained-raw-result",
        "checks": {
            "plugin_preflight": "passed",
            "plugin_scenarios": (
                "passed"
                if plugin_scenarios
                and all(scenario.get("passed") is True for scenario in plugin_scenarios)
                else "failed"
            ),
            "missing_cli_boundary": (
                "passed" if missing.get("passed") is True else "failed"
            ),
        },
        "procedural_pass": result.get("summary", {}).get("all_passed") is True,
        "safety_checks": safety_checks,
        "safety_pass": all(safety_checks.values()) and not safety_errors,
        "cleanup_verified": result.get("delivery", {}).get(
            "temporary_plugin_state_removed"
        )
        is True,
        "failures": failures + safety_errors,
        "evidence": ["bounded full result retained at the recorded path"],
        "usage": usage_totals(result.get("usage", [])),
        "scenario_summary": result.get("summary"),
        "raw_result": raw_result_record(path),
    }


def attempt_from_probe(attempt_id: str, probe: dict) -> dict:
    scenario = probe["scenario"]
    trace = scenario.get("trace", [])
    safety_errors: list[str] = []
    if scenario.get("unexpected_writes") != []:
        safety_errors.append("missing-cli probe recorded unexpected writes")
    if trace_ran_inspect(trace):
        safety_errors.append("missing-cli probe invoked inspect")
    safety_checks = {
        "sensitive_canary_absent": SENSITIVE_CANARY not in json.dumps(probe),
        "unexpected_repository_writes_absent": scenario.get(
            "unexpected_writes"
        )
        == [],
        "missing_cli_inspect_absent": not trace_ran_inspect(trace),
        "temporary_state_removed": True,
    }
    inputs = input_identity()
    inputs["plugin_sha256"] = None
    return {
        "id": attempt_id,
        "recorded_on": datetime.now(timezone.utc).date().isoformat(),
        "kind": "missing-cli-only",
        "inputs": inputs,
        "outcome": "completed",
        "evidence_basis": "session-record",
        "checks": {
            "plugin_preflight": "not_run",
            "plugin_scenarios": "not_run",
            "missing_cli_boundary": (
                "passed" if scenario.get("passed") is True else "failed"
            ),
        },
        "procedural_pass": scenario.get("passed") is True,
        "safety_checks": safety_checks,
        "safety_pass": all(safety_checks.values()) and not safety_errors,
        "cleanup_verified": True,
        "failures": list(scenario.get("failures", [])) + safety_errors,
        "evidence": [
            "bounded missing-CLI trace returned by the isolated probe",
            *[
                str(command.get("command", ""))
                for command in trace
                if isinstance(command, dict)
            ],
        ],
        "usage": usage_totals(probe.get("usage", {})),
        "scenario_summary": None,
        "raw_result": None,
    }


def attempt_from_error(attempt_id: str, exc: BaseException) -> dict:
    message = str(exc) or type(exc).__name__
    # Errors raised before the managed plugin lifecycle create no test-owned
    # state. Once that lifecycle begins, run_evaluation attaches the observed
    # cleanup outcome explicitly.
    cleanup_verified = getattr(exc, "cleanup_verified", True) is True
    unsafe = any(
        marker in message.casefold()
        for marker in ("sensitive canary", "unexpected write", "cleanup also failed")
    )
    safety_checks = {
        "sensitive_canary_absent": "sensitive canary" not in message.casefold(),
        "unexpected_repository_writes_absent": (
            "unexpected write" not in message.casefold()
        ),
        "missing_cli_inspect_absent": True,
        "temporary_state_removed": cleanup_verified,
    }
    stage_checks = {
        "plugin-preflight": {
            "plugin_preflight": "failed",
            "plugin_scenarios": "not_run",
            "missing_cli_boundary": "not_run",
        },
        "plugin-scenarios": {
            "plugin_preflight": "passed",
            "plugin_scenarios": "failed",
            "missing_cli_boundary": "not_run",
        },
        "missing-cli": {
            "plugin_preflight": "passed",
            "plugin_scenarios": "passed",
            "missing_cli_boundary": "failed",
        },
    }
    checks = stage_checks.get(
        getattr(exc, "failed_stage", "plugin-preflight"),
        stage_checks["plugin-preflight"],
    )
    return {
        "id": attempt_id,
        "recorded_on": datetime.now(timezone.utc).date().isoformat(),
        "kind": "full",
        "inputs": input_identity(),
        "outcome": "aborted",
        "evidence_basis": "session-record",
        "checks": checks,
        "procedural_pass": False,
        "safety_checks": safety_checks,
        "safety_pass": all(safety_checks.values()) and not unsafe,
        "cleanup_verified": cleanup_verified,
        "failures": [message],
        "evidence": [message],
        "usage": usage_totals(getattr(exc, "attempt_usage", [])),
        "scenario_summary": None,
        "raw_result": None,
    }


def attempt_from_probe_error(attempt_id: str, exc: Exception) -> dict:
    attempt = attempt_from_error(attempt_id, exc)
    attempt["kind"] = "missing-cli-only"
    attempt["inputs"]["plugin_sha256"] = None
    attempt["checks"] = {
        "plugin_preflight": "not_run",
        "plugin_scenarios": "not_run",
        "missing_cli_boundary": "failed",
    }
    return attempt
