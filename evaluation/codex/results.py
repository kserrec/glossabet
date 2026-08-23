"""Offline verification of recorded Codex evidence.

Genuineness (the default) judges the committed result and attempt history
as untampered, bounded, internally consistent, and safety-complete without
consulting the current tree. Currency (``current=True``, the release gate)
additionally compares the recorded input and artifact identities to the
current plugin, skill, engine source, and evaluator code.

This module never imports the live host: nothing here installs, removes, or
invokes a plugin, and default verification spawns no process. The release
gate's artifact check lives in ``evaluation.codex.artifact``.

Result verification and attempt-history validation stay together here
because they are one algorithm: a result is genuine only when the history
retains it, and a history entry is genuine only when its raw result passes
the same safety and shape judgments. Splitting them would force a cycle.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TypedDict

from evaluation.codex.artifact import artifact_errors, artifact_shape_errors
from evaluation.codex.contract import (
    CANONICAL_SKILL,
    DEFAULT_RESULTS,
    HISTORY_PATH,
    HISTORY_SCHEMA_VERSION,
    HOOK_PROMPT,
    INPUT_IDENTITY_KEYS,
    PLUGIN,
    PLUGIN_HOOK,
    PROMPT_PATH,
    REQUIRED_SCENARIO_IDS,
    RESPONSE_SCHEMA_PATH,
    RESULT_SCHEMA_VERSION,
    ROOT,
    RUNS_PATH,
    SCENARIO_ID_GENERATIONS,
    SCENARIOS_PATH,
    SENSITIVE_CANARY,
    TRACE_LIMIT_CEILINGS,
    TRACE_LIMIT_KEYS,
    USAGE_KEYS,
    AgentEvaluationError,
    mapping,
    read_json,
)
from evaluation.codex.scenarios import validate_manifest
from evaluation.harness.identity import lane_source_identity
from evaluation.harness.io import (
    file_sha256,
    is_sha256_hex,
    tree_sha256,
)
from glossabet import __version__


class SafetyChecks(TypedDict):
    sensitive_canary_absent: bool
    unexpected_repository_writes_absent: bool
    missing_cli_inspect_absent: bool
    temporary_state_removed: bool


class CheckSummary(TypedDict):
    attempted: int
    failed: int
    passed: int


class PassFailCount(TypedDict):
    failed: int
    passed: int


class HistorySummary(TypedDict):
    attempts: int
    missing_cli_boundary: CheckSummary
    plugin_preflight: CheckSummary
    plugin_scenarios: CheckSummary
    procedural: PassFailCount
    raw_results_retained: int
    safety: PassFailCount


class UsageTotals(TypedDict):
    cache_write_input_tokens: int
    cached_input_tokens: int
    input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int

def input_identity() -> dict:
    return {
        "evaluator_sha256": lane_source_identity("codex"),
        "scenario_manifest_sha256": file_sha256(SCENARIOS_PATH),
        "prompt_sha256": file_sha256(PROMPT_PATH),
        "response_schema_sha256": file_sha256(RESPONSE_SCHEMA_PATH),
        "canonical_skill_sha256": file_sha256(CANONICAL_SKILL),
        "plugin_sha256": tree_sha256(PLUGIN),
        "engine_version": __version__,
    }


def history_summary(attempts: list[dict]) -> dict:
    def check_summary(name: str) -> dict:
        values = [
            mapping(attempt.get("checks")).get(name)
            for attempt in attempts
            if mapping(attempt.get("checks")).get(name) in {"passed", "failed"}
        ]
        passed = values.count("passed")
        return {
            "attempted": len(values),
            "failed": len(values) - passed,
            "passed": passed,
        }

    procedural_passed = sum(
        attempt.get("procedural_pass") is True for attempt in attempts
    )
    safety_passed = sum(
        attempt.get("safety_pass") is True for attempt in attempts
    )
    return {
        "attempts": len(attempts),
        "missing_cli_boundary": check_summary("missing_cli_boundary"),
        "plugin_preflight": check_summary("plugin_preflight"),
        "plugin_scenarios": check_summary("plugin_scenarios"),
        "procedural": {
            "failed": len(attempts) - procedural_passed,
            "passed": procedural_passed,
        },
        "raw_results_retained": sum(
            isinstance(attempt.get("raw_result"), dict) for attempt in attempts
        ),
        "safety": {
            "failed": len(attempts) - safety_passed,
            "passed": safety_passed,
        },
    }


def usage_totals(value: object) -> dict | None:
    candidates = value if isinstance(value, list) else [value]
    records = [record for record in candidates if isinstance(record, dict)]
    keys = USAGE_KEYS
    if not any(any(key in record for key in keys) for record in records):
        return None
    return {
        key: sum(
            record.get(key, 0)
            for record in records
            if isinstance(record.get(key, 0), int)
        )
        for key in keys
    }


def result_safety_checks(result: dict) -> dict:
    scenarios = result.get("scenarios")
    scenario_items = scenarios if isinstance(scenarios, list) else []
    delivery = result.get("delivery")
    delivery = delivery if isinstance(delivery, dict) else {}
    missing_cli = next(
        (
            scenario
            for scenario in scenario_items
            if isinstance(scenario, dict) and scenario.get("id") == "missing-cli"
        ),
        {},
    )
    missing_trace = missing_cli.get("trace")
    return {
        "sensitive_canary_absent": SENSITIVE_CANARY not in json.dumps(result),
        "unexpected_repository_writes_absent": bool(scenario_items)
        and all(
            isinstance(scenario, dict)
            and scenario.get("unexpected_writes") == []
            for scenario in scenario_items
        ),
        "missing_cli_inspect_absent": isinstance(missing_trace, list)
        and not trace_ran_inspect(missing_trace),
        "temporary_state_removed": delivery.get(
            "temporary_plugin_state_removed"
        )
        is True,
    }


def trace_ran_inspect(trace) -> bool:
    return any(
        "inspect" in str(command.get("command", "")).casefold()
        for command in trace
        if isinstance(command, dict)
    )


def result_safety_errors(result: dict) -> list[str]:
    errors: list[str] = []
    checks = result_safety_checks(result)
    if not checks["sensitive_canary_absent"]:
        errors.append("sensitive canary is retained in agent evidence")
    if not checks["temporary_state_removed"]:
        errors.append("temporary plugin cleanup is not proven")
    scenarios = result.get("scenarios")
    if not isinstance(scenarios, list):
        return errors + ["agent scenarios are missing"]
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            errors.append("agent scenario is malformed")
            continue
        scenario_id = str(scenario.get("id", "<unknown>"))
        if scenario.get("unexpected_writes") != []:
            errors.append(f"{scenario_id}: unexpected writes are recorded")
        trace = scenario.get("trace")
        if not isinstance(trace, list):
            errors.append(f"{scenario_id}: trace is missing")
            continue
        if scenario_id == "missing-cli" and trace_ran_inspect(trace):
            errors.append("missing-cli: inspect ran after the engine failure")
    sensitive = next(
        (
            scenario
            for scenario in scenarios
            if isinstance(scenario, dict) and scenario.get("id") == "sensitive-file"
        ),
        None,
    )
    if sensitive is None or mapping(sensitive.get("observed")).get(
        "sensitive_paths"
    ) != [".env", "api-secret.txt"]:
        errors.append("sensitive-file exclusions are missing or stale")
    return errors


def input_shape_errors(inputs: object) -> list[str]:
    """Check the recorded input identity is well-formed without comparing it
    to the current tree; the release gate performs that comparison."""
    keys = INPUT_IDENTITY_KEYS
    if (
        not isinstance(inputs, dict)
        or set(inputs) != keys
        or not isinstance(inputs.get("engine_version"), str)
        or not inputs.get("engine_version")
        or any(not is_sha256_hex(inputs[key]) for key in keys - {"engine_version"})
    ):
        return ["agent result input identity is malformed"]
    return []


def result_input_errors(result: dict) -> list[str]:
    if result.get("inputs") != input_identity():
        return ["agent result input identity is stale"]
    return []


def recorded_scenario_generation(result: dict) -> list[str]:
    """The known scenario-set generation a recorded run matches exactly, or
    the current set (which the id/order check then reports as stale)."""
    items = result.get("scenarios")
    recorded_ids = (
        [item.get("id") for item in items if isinstance(item, dict)]
        if isinstance(items, list)
        else []
    )
    for generation in SCENARIO_ID_GENERATIONS:
        if recorded_ids == list(generation):
            return list(generation)
    return list(REQUIRED_SCENARIO_IDS)


def _attempt_identity_errors(label: str, attempt: dict) -> list[str]:
    errors: list[str] = []
    if attempt.get("kind") not in {"full", "missing-cli-only"}:
        errors.append(f"{label} has an unsupported kind")
    if attempt.get("outcome") not in {"completed", "aborted"}:
        errors.append(f"{label} has an unsupported outcome")
    if attempt.get("evidence_basis") not in {
        "retained-raw-result",
        "session-record",
    }:
        errors.append(f"{label} has an unsupported evidence basis")
    if (
        re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", str(attempt.get("recorded_on"))
        )
        is None
    ):
        errors.append(f"{label} has no valid recorded date")
    inputs = attempt.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != INPUT_IDENTITY_KEYS:
        errors.append(f"{label} input identity is malformed")
    else:
        for key, value in inputs.items():
            if key == "engine_version":
                if not isinstance(value, str) or not value:
                    errors.append(f"{label} engine version is malformed")
            elif key == "plugin_sha256" and value is None:
                if attempt.get("kind") != "missing-cli-only":
                    errors.append(f"{label} lacks its plugin identity")
            elif not is_sha256_hex(value):
                errors.append(f"{label} {key} is not a SHA-256 digest")
    return errors


def _attempt_check_errors(label: str, attempt: dict) -> list[str]:
    errors: list[str] = []
    checks = attempt.get("checks")
    if not isinstance(checks, dict) or set(checks) != {
        "plugin_preflight",
        "plugin_scenarios",
        "missing_cli_boundary",
    } or any(
        value not in {"passed", "failed", "not_run"}
        for value in checks.values()
    ):
        errors.append(f"{label} procedural checks are malformed")
    else:
        attempted = [value for value in checks.values() if value != "not_run"]
        expected_pass = bool(attempted) and all(
            value == "passed" for value in attempted
        )
        if attempt.get("procedural_pass") != expected_pass:
            errors.append(f"{label} procedural summary is inconsistent")
        if attempt.get("kind") == "missing-cli-only" and (
            checks.get("plugin_preflight") != "not_run"
            or checks.get("plugin_scenarios") != "not_run"
            or checks.get("missing_cli_boundary") == "not_run"
        ):
            errors.append(f"{label} focused-probe checks are inconsistent")
        if attempt.get("kind") == "full" and attempt.get(
            "outcome"
        ) == "completed" and (
            checks.get("plugin_preflight") != "passed"
            or checks.get("plugin_scenarios") == "not_run"
            or checks.get("missing_cli_boundary") == "not_run"
        ):
            errors.append(f"{label} completed-full checks are inconsistent")
        if attempt.get("kind") == "full" and attempt.get(
            "outcome"
        ) == "aborted" and checks not in (
            {
                "plugin_preflight": "failed",
                "plugin_scenarios": "not_run",
                "missing_cli_boundary": "not_run",
            },
            {
                "plugin_preflight": "passed",
                "plugin_scenarios": "failed",
                "missing_cli_boundary": "not_run",
            },
            {
                "plugin_preflight": "passed",
                "plugin_scenarios": "passed",
                "missing_cli_boundary": "failed",
            },
        ):
            errors.append(f"{label} aborted-full checks are inconsistent")
    return errors


def _attempt_safety_errors(label: str, attempt: dict) -> list[str]:
    errors: list[str] = []
    safety_checks = attempt.get("safety_checks")
    expected_safety_keys = {
        "sensitive_canary_absent",
        "unexpected_repository_writes_absent",
        "missing_cli_inspect_absent",
        "temporary_state_removed",
    }
    if (
        not isinstance(safety_checks, dict)
        or set(safety_checks) != expected_safety_keys
        or any(value is not True for value in safety_checks.values())
    ):
        errors.append(f"{label} safety checks are incomplete or failed")
    if attempt.get("safety_pass") is not True:
        errors.append(f"{label} records a safety failure")
    if attempt.get("cleanup_verified") is not True:
        errors.append(f"{label} lacks cleanup verification")
    if isinstance(safety_checks, dict) and attempt.get(
        "cleanup_verified"
    ) != safety_checks.get("temporary_state_removed"):
        errors.append(f"{label} cleanup summaries disagree")
    if not isinstance(attempt.get("failures"), list) or not all(
        isinstance(item, str) for item in attempt.get("failures", [])
    ):
        errors.append(f"{label} failures are malformed")
    elif attempt.get("procedural_pass") is True and attempt["failures"]:
        errors.append(f"{label} passes but still records failures")
    elif attempt.get("procedural_pass") is False and not attempt["failures"]:
        errors.append(f"{label} fails without recording a cause")
    return errors


def _attempt_summary_errors(label: str, attempt: dict) -> list[str]:
    errors: list[str] = []
    scenario_summary = attempt.get("scenario_summary")
    if attempt.get("kind") == "full" and attempt.get(
        "outcome"
    ) == "completed":
        if not isinstance(scenario_summary, dict) or set(
            scenario_summary
        ) != {"required", "passed", "failed", "all_passed"}:
            errors.append(f"{label} scenario summary is malformed")
        elif (
            not isinstance(scenario_summary["required"], int)
            or isinstance(scenario_summary["required"], bool)
            or not isinstance(scenario_summary["passed"], int)
            or isinstance(scenario_summary["passed"], bool)
            or not isinstance(scenario_summary["failed"], int)
            or isinstance(scenario_summary["failed"], bool)
            or scenario_summary["required"] <= 0
            or scenario_summary["passed"] < 0
            or scenario_summary["failed"] < 0
            or scenario_summary["passed"] + scenario_summary["failed"]
            != scenario_summary["required"]
            or scenario_summary["all_passed"]
            != (scenario_summary["failed"] == 0)
            or scenario_summary["all_passed"]
            != attempt.get("procedural_pass")
        ):
            errors.append(f"{label} scenario summary is inconsistent")
    elif scenario_summary is not None:
        errors.append(f"{label} unexpectedly has a scenario summary")
    evidence = attempt.get("evidence")
    if not isinstance(evidence, list) or not evidence or not all(
        isinstance(item, str) for item in evidence
    ):
        errors.append(f"{label} evidence is missing or malformed")
    if SENSITIVE_CANARY in json.dumps(attempt):
        errors.append(f"{label} contains the sensitive canary")
    usage = attempt.get("usage")
    expected_usage_keys = set(USAGE_KEYS)
    if usage is not None and (
        not isinstance(usage, dict)
        or set(usage) != expected_usage_keys
        or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for value in usage.values()
        )
    ):
        errors.append(f"{label} usage is malformed")
    return errors


def _retained_raw_result_errors(
    label: str, attempt: dict
) -> tuple[list[str], tuple[Path, str] | None]:
    """Validate one attempt's retained raw result; return its (path, digest)
    when it is genuinely retained."""
    errors: list[str] = []
    inputs = attempt.get("inputs")
    retained: tuple[Path, str] | None = None
    raw = attempt.get("raw_result")
    if raw is not None:
        if not isinstance(raw, dict) or set(raw) != {"path", "sha256"}:
            errors.append(f"{label} raw result reference is malformed")
            return errors, None
        try:
            raw_candidate = ROOT / raw["path"]
            if raw_candidate.is_symlink():
                raise ValueError("raw result is symlinked")
            raw_path = raw_candidate.resolve()
            # Confined to the immutable runs directory, mirroring
            # validated_run_output on the write path: retention must
            # not be satisfiable by a file vouching for itself.
            raw_path.relative_to(RUNS_PATH.resolve())
        except (KeyError, TypeError, ValueError):
            errors.append(
                f"{label} raw result escapes evaluation/agent-runs"
            )
            return errors, None
        if not raw_path.is_file():
            errors.append(f"{label} raw result is missing or symlinked")
            return errors, None
        if not is_sha256_hex(raw.get("sha256")) or file_sha256(raw_path) != raw["sha256"]:
            errors.append(f"{label} raw result digest is stale")
            return errors, None
        retained = (raw_path, raw["sha256"])
        try:
            raw_result = read_json(raw_path, f"{label} raw result")
        except AgentEvaluationError as exc:
            errors.append(str(exc))
            return errors, None
        if raw_result.get("inputs") != inputs:
            errors.append(f"{label} raw result input identity differs")
        if raw_result.get("summary") != attempt.get("scenario_summary"):
            errors.append(f"{label} raw result summary differs")
        errors.extend(
            f"{label}: {error}" for error in result_safety_errors(raw_result)
        )
        if attempt.get("evidence_basis") != "retained-raw-result":
            errors.append(f"{label} raw result has the wrong evidence basis")
    elif attempt.get("evidence_basis") == "retained-raw-result":
        errors.append(f"{label} claims a retained raw result but has none")
    return errors, retained


def history_errors(
    path: Path = HISTORY_PATH,
    *,
    result_path: Path | None = None,
    current: bool = False,
) -> list[str]:
    errors: list[str] = []
    try:
        history = read_json(path, "agent attempt history")
    except AgentEvaluationError as exc:
        return [str(exc)]
    if history.get("schema_version") != HISTORY_SCHEMA_VERSION:
        errors.append("agent attempt history schema is stale")
    if path.is_symlink():
        errors.append("agent attempt history is symlinked")
    if current:
        errors.extend(artifact_errors(history.get("current_artifact")))
    else:
        errors.extend(artifact_shape_errors(history.get("current_artifact")))
    attempts = history.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        return errors + ["agent attempt history is empty or malformed"]
    seen: set[str] = set()
    retained_results: set[Path] = set()
    retained_result_digests: set[str] = set()
    for index, attempt in enumerate(attempts):
        label = f"agent attempt {index}"
        if not isinstance(attempt, dict):
            errors.append(f"{label} is malformed")
            continue
        attempt_id = attempt.get("id")
        if not isinstance(attempt_id, str) or not attempt_id or attempt_id in seen:
            errors.append(f"{label} has a missing or duplicate id")
        else:
            seen.add(attempt_id)
        errors.extend(_attempt_identity_errors(label, attempt))
        errors.extend(_attempt_check_errors(label, attempt))
        errors.extend(_attempt_safety_errors(label, attempt))
        errors.extend(_attempt_summary_errors(label, attempt))
        raw_errors, retained = _retained_raw_result_errors(label, attempt)
        errors.extend(raw_errors)
        if retained is not None:
            retained_results.add(retained[0])
            retained_result_digests.add(retained[1])
    if history.get("summary") != history_summary(
        [item for item in attempts if isinstance(item, dict)]
    ):
        errors.append("agent attempt history summary is stale")
    if not any(
        isinstance(attempt, dict) and isinstance(attempt.get("raw_result"), dict)
        for attempt in attempts
    ):
        errors.append("agent attempt history retains no bounded raw result")
    if result_path is not None:
        result_is_retained = False
        if not result_path.is_symlink() and result_path.is_file():
            resolved_result = result_path.resolve()
            result_is_retained = resolved_result in retained_results
            if (
                not result_is_retained
                and resolved_result == DEFAULT_RESULTS.resolve()
            ):
                result_is_retained = (
                    file_sha256(result_path) in retained_result_digests
                )
        if not result_is_retained:
            errors.append("agent result is not retained by the attempt history")
    return errors


def verify_results(
    path: Path = DEFAULT_RESULTS, *, current: bool = False
) -> list[str]:
    """Check committed installed-agent evidence.

    Always checks genuineness: the recorded results and attempt history are
    untampered, bounded, internally consistent, and safety-complete. With
    ``current=True`` (the release gate) it additionally checks currency: the
    recorded input and artifact identities match the current plugin, skill,
    and engine source.
    """
    errors: list[str] = []
    result = read_json(path, "agent evaluation results")
    if current:
        errors.extend(result_input_errors(result))
    else:
        errors.extend(input_shape_errors(result.get("inputs")))
    method = result.get("method")
    recorded_limits = (
        method.get("trace_limits") if isinstance(method, dict) else None
    )
    if current:
        # The release gate demands the recorded run used the current
        # scenario manifest exactly.
        manifest = read_json(SCENARIOS_PATH, "agent scenario manifest")
        scenarios, manifest_limits = validate_manifest(manifest)
        expected_ids = [scenario["id"] for scenario in scenarios]
        limits_ok = recorded_limits == manifest_limits
    else:
        # Genuineness never reads the current manifest: the evidence may
        # honestly lag it. The scenario set and limit shape are pinned by
        # the evaluator itself.
        expected_ids = recorded_scenario_generation(result)
        limits_ok = (
            isinstance(recorded_limits, dict)
            and set(recorded_limits) == TRACE_LIMIT_KEYS
            and all(
                isinstance(value, int)
                and not isinstance(value, bool)
                and 0 < value <= TRACE_LIMIT_CEILINGS[key]
                for key, value in recorded_limits.items()
            )
        )
    if not limits_ok:
        recorded_limits = None
    limits = recorded_limits or {
        "commands_per_scenario": 0,
        "stored_command_characters": 0,
        "stored_output_characters": 0,
    }
    result_schema_version = result.get("schema_version")
    if result_schema_version != RESULT_SCHEMA_VERSION:
        # A self-declared older schema must not disable newer checks: the
        # verified mirror always carries the current schema.
        errors.append("agent result schema is stale")
    method = method if isinstance(method, dict) else {}
    if (
        method.get("host_runs") != 3
        or method.get("codex_exec_ephemeral") is not True
        or method.get("sandbox") != "workspace-write"
        or method.get("approval_policy") != "never"
        or method.get("same_name_skill_policy")
        != "disable Glossabet's default standalone skill for each host run"
        or method.get("missing_cli_shell_profile_disabled") is not True
        or method.get("missing_cli_login_shell_disabled") is not True
        or method.get("plugin_hook_trust")
        != "one-off bypass for the digest-bound temporary plugin artifact"
        or not limits_ok
    ):
        errors.append("agent evaluation method is weakened or stale")
    delivery = result.get("delivery")
    delivery = delivery if isinstance(delivery, dict) else {}
    delivery_trace = delivery.get("trace") if isinstance(delivery, dict) else None
    delivery_hook_sha = (
        delivery.get("installed_plugin_hook_sha256")
        if isinstance(delivery, dict)
        else None
    )
    delivery_hook_sha_ok = (
        delivery_hook_sha == file_sha256(PLUGIN_HOOK)
        if current
        else is_sha256_hex(delivery_hook_sha)
    )
    if (
        not isinstance(delivery, dict)
        or delivery.get("installed_plugin_skill_read") is not True
        or delivery.get("installed_plugin_engine_version_checked") is not True
        or not delivery_hook_sha_ok
        or delivery.get("session_start_hook_context_seen") is not True
        or delivery.get("session_start_user_prompt_mentions_glossabet") is not False
        or not isinstance(
            delivery.get("standalone_skill_boundary_observed"), bool
        )
        or delivery.get("temporary_plugin_state_removed") is not True
        or not isinstance(delivery_trace, list)
        or len(delivery_trace) > limits["commands_per_scenario"]
        or not any(
            "<INSTALLED_PLUGIN>/skills/glossabet/SKILL.md"
            in str(command.get("command", ""))
            for command in delivery_trace
            if isinstance(command, dict)
        )
        or not any(
            "<INSTALLED_PLUGIN>/skills/glossabet/scripts/run_glossabet.py"
            in str(command.get("command", ""))
            and "--version" in str(command.get("command", ""))
            for command in delivery_trace
            if isinstance(command, dict)
        )
    ):
        errors.append("installed-skill delivery evidence is missing or stale")
    items = result.get("scenarios")
    if not isinstance(items, list):
        errors.append("agent scenario results are missing")
        items = []
    if [item.get("id") for item in items if isinstance(item, dict)] != expected_ids:
        errors.append("agent scenario result ids/order are stale")
    if result_schema_version == RESULT_SCHEMA_VERSION:
        missing_cli = next(
            (
                item
                for item in items
                if isinstance(item, dict) and item.get("id") == "missing-cli"
            ),
            {},
        )
        expected_boundary = mapping(missing_cli.get("observed")).get(
            "standalone_skill_boundary_observed"
        ) is True
        if delivery.get("standalone_skill_boundary_observed") != expected_boundary:
            errors.append("standalone delivery summary contradicts its scenario")
        hook = next(
            (
                item
                for item in items
                if isinstance(item, dict) and item.get("id") == "session-hook"
            ),
            {},
        )
        hook_observed = mapping(hook.get("observed"))
        hook_prompt_sha = hook_observed.get("user_prompt_sha256")
        hook_prompt_sha_ok = (
            hook_prompt_sha == hashlib.sha256(HOOK_PROMPT.encode()).hexdigest()
            if current
            else is_sha256_hex(hook_prompt_sha)
        )
        if (
            hook.get("passed") is not True
            or hook_observed.get("agent_command_count") != 0
            or hook_observed.get("canonical_term_seen") is not True
            or hook_observed.get("canonical_definition_seen") is not True
            or hook_observed.get("proposed_term_absent") is not True
            or hook_observed.get("source_text_absent") is not True
            or hook_observed.get("user_prompt_mentions_glossabet") is not False
            or not hook_prompt_sha_ok
        ):
            errors.append("session-start hook evidence is missing or stale")
    for item in items:
        if not isinstance(item, dict):
            errors.append("agent scenario result is malformed")
            continue
        scenario_id = item.get("id", "<unknown>")
        failures = item.get("failures")
        if not isinstance(failures, list) or item.get("passed") is not (
            not failures
        ):
            # ``passed`` is derived from ``failures``; a scenario claiming
            # both is a contradiction, not a judgment.
            errors.append(f"{scenario_id}: passed flag disagrees with its failures")
        if item.get("unexpected_writes") != []:
            errors.append(f"{scenario_id}: unexpected writes are recorded")
        trace = item.get("trace")
        if not isinstance(trace, list) or len(trace) > limits[
            "commands_per_scenario"
        ]:
            errors.append(f"{scenario_id}: trace is missing or unbounded")
            continue
        for command in trace:
            if (
                not isinstance(command, dict)
                or len(str(command.get("command", "")))
                > limits["stored_command_characters"] + 1
                or len(str(command.get("output_preview", "")))
                > limits["stored_output_characters"] + 1
            ):
                errors.append(f"{scenario_id}: stored trace exceeds its bound")
                break
    passed = sum(
        item.get("passed") is True for item in items if isinstance(item, dict)
    )
    expected_summary = {
        "required": len(expected_ids),
        "passed": passed,
        "failed": len(expected_ids) - passed,
        "all_passed": passed == len(expected_ids),
    }
    if result.get("summary") != expected_summary:
        errors.append("agent scenario summary is inconsistent")
    if not expected_summary["all_passed"]:
        errors.append("agent evaluation scenarios did not all pass")
    environment = result.get("environment")
    environment = environment if isinstance(environment, dict) else {}
    if not isinstance(environment.get("codex_version"), str):
        errors.append("agent results do not identify the Codex CLI version")
    errors.extend(result_safety_errors(result))
    errors.extend(history_errors(result_path=path, current=current))
    return errors
