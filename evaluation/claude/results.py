"""Offline verification of recorded Claude evidence.

Genuineness (the default) judges the committed result and attempt history
as untampered, bounded, and consistent with their own retained event
traces, without consulting the current tree, the installed plugin, or
Claude's login state. Currency (``current=True``) additionally compares the
recorded input identity to the current evaluator and installed plugin.

This module never imports the live host.
"""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.claude.contract import (
    CANONICAL_DEFINITION,
    CANONICAL_SKILL,
    CANONICAL_TERM,
    DEFAULT_INSTALLED_PLUGIN,
    DEFAULT_RESULTS,
    EXPECTED_CLAUDE_VERSION,
    HISTORY_PATH,
    HISTORY_SCHEMA_VERSION,
    PROPOSED_TERM,
    RESPONSE_SCHEMA_PATH,
    RESULT_SCHEMA_VERSION,
    ROOT,
    RUNS_PATH,
    SCENARIO_IDS,
    SCENARIOS_PATH,
    SOURCE_CANARY,
    ClaudeEvaluationError,
    load_manifest,
    read_json,
    sha256_text,
    tree_sha256,
)
from evaluation.claude.events import (
    api_retries,
    hook_event_seen,
    response_shape_errors,
    structured_output,
    tool_calls,
)
from evaluation.claude.history import attempt_from_result, history_summary
from evaluation.harness.identity import lane_source_identity
from evaluation.harness.io import file_sha256, is_sha256_hex
from glossabet import __version__


def input_identity(installed_plugin: Path) -> dict:
    return {
        "evaluator_sha256": lane_source_identity("claude"),
        "scenario_manifest_sha256": file_sha256(SCENARIOS_PATH),
        "response_schema_sha256": file_sha256(RESPONSE_SCHEMA_PATH),
        "canonical_skill_sha256": file_sha256(CANONICAL_SKILL),
        "installed_plugin_sha256": tree_sha256(installed_plugin),
        "engine_version": __version__,
    }


def input_shape_errors(value: object) -> list[str]:
    keys = {
        "evaluator_sha256",
        "scenario_manifest_sha256",
        "response_schema_sha256",
        "canonical_skill_sha256",
        "installed_plugin_sha256",
        "engine_version",
    }
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or not isinstance(value.get("engine_version"), str)
        or not value.get("engine_version")
        or any(not is_sha256_hex(value[key]) for key in keys - {"engine_version"})
    ):
        return ["Claude result input identity is malformed"]
    return []


def verify_history(path: Path | None = None) -> list[str]:
    path = HISTORY_PATH if path is None else path
    errors: list[str] = []
    try:
        history = read_json(path, "Claude attempt history")
    except ClaudeEvaluationError as exc:
        return [str(exc)]
    attempts = history.get("attempts")
    if history.get("schema_version") != HISTORY_SCHEMA_VERSION or not isinstance(attempts, list):
        return ["Claude attempt history is malformed"]
    ids = [item.get("id") for item in attempts if isinstance(item, dict)]
    if len(ids) != len(attempts) or len(ids) != len(set(ids)):
        errors.append("Claude attempt history ids are malformed or duplicated")
    for index, attempt in enumerate(attempts):
        if not isinstance(attempt, dict):
            errors.append(f"Claude attempt {index} is malformed")
            continue
        outcome = attempt.get("outcome")
        raw = attempt.get("raw_result")
        if outcome == "completed" and not isinstance(raw, dict):
            errors.append(f"Claude attempt {attempt.get('id')} lacks raw evidence")
            continue
        if outcome == "aborted" and raw is not None:
            errors.append(f"Claude aborted attempt {attempt.get('id')} claims raw evidence")
            continue
        if isinstance(raw, dict):
            raw_path = ROOT / str(raw.get("path", ""))
            try:
                if raw_path.resolve().parent != RUNS_PATH.resolve():
                    raise ValueError
            except (OSError, ValueError):
                errors.append(f"Claude attempt {attempt.get('id')} raw path escapes")
                continue
            if (
                raw_path.is_symlink()
                or not raw_path.is_file()
                or not is_sha256_hex(raw.get("sha256"))
                or file_sha256(raw_path) != raw.get("sha256")
            ):
                errors.append(f"Claude attempt {attempt.get('id')} raw digest is stale")
                continue
            try:
                raw_result = read_json(raw_path, "Claude raw result")
                expected_attempt = attempt_from_result(
                    str(attempt.get("id")),
                    raw_result,
                    raw_path,
                )
                expected_attempt["recorded_on"] = attempt.get("recorded_on")
            except (ClaudeEvaluationError, KeyError, IndexError, TypeError) as exc:
                errors.append(
                    f"Claude attempt {attempt.get('id')} raw result is malformed: {exc}"
                )
            else:
                if attempt != expected_attempt:
                    errors.append(
                        f"Claude attempt {attempt.get('id')} contradicts its raw result"
                    )
        checks = attempt.get("safety_checks")
        if not isinstance(checks, dict) or attempt.get("safety_pass") is not all(
            value is True for value in checks.values()
        ):
            errors.append(f"Claude attempt {attempt.get('id')} safety summary contradicts checks")
    if history.get("summary") != history_summary(
        [item for item in attempts if isinstance(item, dict)]
    ):
        errors.append("Claude attempt history summary is stale")
    return errors


def result_scenario_errors(item: object, scenario: dict, limits: dict) -> list[str]:
    expected_id = scenario["id"]
    if not isinstance(item, dict) or item.get("id") != expected_id:
        return [f"{expected_id}: result is missing or out of order"]
    errors: list[str] = []
    failures = item.get("failures")
    if not isinstance(failures, list) or item.get("passed") is not (not failures):
        errors.append(f"{expected_id}: passed flag contradicts failures")
    if (
        item.get("prompt") != scenario["prompt"]
        or item.get("prompt_sha256") != sha256_text(scenario["prompt"])
    ):
        errors.append(f"{expected_id}: prompt or prompt digest is stale")

    response = item.get("response")
    errors.extend(
        f"{expected_id}: {error}" for error in response_shape_errors(response)
    )
    response = response if isinstance(response, dict) else {}
    if expected_id == "ambient-present":
        if response.get("status") != "supplied":
            errors.append(f"{expected_id}: supplied status is missing")
        if response.get("term") != CANONICAL_TERM:
            errors.append(f"{expected_id}: canonical term is missing or altered")
        if response.get("definition") != CANONICAL_DEFINITION:
            errors.append(f"{expected_id}: canonical definition is missing or altered")
        if response.get("protocol") is not None:
            errors.append(f"{expected_id}: unexpected skill protocol was retained")
    elif expected_id == "ambient-absent":
        if response.get("status") != "not-supplied":
            errors.append(f"{expected_id}: not-supplied status is missing")
        if any(response.get(key) is not None for key in ("term", "definition", "protocol")):
            errors.append(f"{expected_id}: vocabulary or a protocol was retained")
    elif expected_id == "skill-root":
        protocol = response.get("protocol")
        normalized = protocol.casefold() if isinstance(protocol, str) else ""
        if response.get("status") != "skill-loaded":
            errors.append(f"{expected_id}: skill-loaded status is missing")
        if response.get("term") is not None or response.get("definition") is not None:
            errors.append(f"{expected_id}: ambient vocabulary fields were retained")
        if not all(item in normalized for item in ("step 0", "version", "inspect")):
            errors.append(f"{expected_id}: Step 0 version/inspect boundary is missing")
        if not any(item in normalized for item in ("tool", "disabled", "unavailable", "cannot")):
            errors.append(f"{expected_id}: unavailable-tools boundary is missing")

    events = item.get("events")
    events_valid = (
        isinstance(events, list)
        and len(events) <= limits["events_per_call"]
        and all(isinstance(event, dict) for event in events)
    )
    if not events_valid:
        errors.append(f"{expected_id}: event trace is missing, malformed, or unbounded")
        events = []
    event_response, event_usage = structured_output(events)
    if event_response != item.get("response"):
        errors.append(f"{expected_id}: response contradicts the retained event trace")
    if event_usage != item.get("usage"):
        errors.append(f"{expected_id}: usage contradicts the retained event trace")

    serialized = json.dumps(
        {"response": item.get("response"), "events": events},
        ensure_ascii=False,
    )
    recomputed_observations = {
        "hook_event_seen": hook_event_seen(events),
        "tool_calls": tool_calls(events),
        "api_retries": api_retries(events),
        "canonical_term_seen": CANONICAL_TERM in serialized,
        "canonical_definition_seen": CANONICAL_DEFINITION in serialized,
        "proposed_term_absent": PROPOSED_TERM not in serialized,
        "source_canary_absent": SOURCE_CANARY not in serialized,
    }
    observed = item.get("observed")
    if not isinstance(observed, dict):
        errors.append(f"{expected_id}: observations are missing")
    else:
        expected_observation_keys = {
            *recomputed_observations,
            "unexpected_writes",
            "direct_brief_sha256",
        }
        if set(observed) != expected_observation_keys:
            errors.append(f"{expected_id}: observation fields are stale")
        for key, recomputed in recomputed_observations.items():
            if observed.get(key) != recomputed:
                errors.append(f"{expected_id}: {key} contradicts the event trace")
        if observed.get("hook_event_seen") is not True:
            errors.append(f"{expected_id}: SessionStart hook was not observed")
        if observed.get("tool_calls") != []:
            errors.append(f"{expected_id}: model tools were recorded")
        if observed.get("api_retries") != 0:
            errors.append(f"{expected_id}: API retries were recorded")
        if observed.get("unexpected_writes") != []:
            errors.append(f"{expected_id}: fixture writes were recorded")
        if observed.get("proposed_term_absent") is not True:
            errors.append(f"{expected_id}: proposed vocabulary leaked")
        if observed.get("source_canary_absent") is not True:
            errors.append(f"{expected_id}: source canary leaked")
        if not is_sha256_hex(observed.get("direct_brief_sha256")):
            errors.append(f"{expected_id}: direct brief digest is malformed")
        if (
            expected_id == "ambient-absent"
            and observed.get("direct_brief_sha256") != sha256_text("")
        ):
            errors.append(f"{expected_id}: no-glossary direct brief was not empty")
    if item.get("returncode") != 0:
        errors.append(f"{expected_id}: Claude return code was not zero")
    stderr = item.get("stderr")
    if (
        not isinstance(stderr, str)
        or len(stderr) > limits["stored_string_characters"] + 1
        or item.get("stderr_sanitized_sha256") != sha256_text(stderr)
    ):
        errors.append(f"{expected_id}: sanitized stderr or its digest is stale")
    if not is_sha256_hex(item.get("stdout_sha256")) or not is_sha256_hex(item.get("stderr_sha256")):
        errors.append(f"{expected_id}: stream digests are malformed")
    return errors


def verify_results(
    path: Path | None = None,
    *,
    current: bool = False,
    installed_plugin: Path | None = None,
) -> list[str]:
    path = DEFAULT_RESULTS if path is None else path
    installed_plugin = (
        DEFAULT_INSTALLED_PLUGIN if installed_plugin is None else installed_plugin
    )
    errors: list[str] = []
    try:
        result = read_json(path, "Claude evaluation result")
        manifest = load_manifest()
    except ClaudeEvaluationError as exc:
        return [str(exc)]
    if result.get("schema_version") != RESULT_SCHEMA_VERSION:
        errors.append("Claude result schema is stale")
    if current:
        try:
            if result.get("inputs") != input_identity(installed_plugin):
                errors.append("Claude result inputs do not match the current evaluator/plugin")
        except (ClaudeEvaluationError, OSError) as exc:
            errors.append(f"current Claude inputs are unreadable: {exc}")
    else:
        errors.extend(input_shape_errors(result.get("inputs")))
    if result.get("auth") != {
        "logged_in": True,
        "auth_method": "claude.ai",
        "api_provider": "firstParty",
        "subscription_type": "max",
    }:
        errors.append("Claude result auth method is missing or unsafe")
    method = result.get("method")
    expected_method = {
        "host_calls": 3,
        "retries": 0,
        "normal_profile_authentication": True,
        "authentication_commands_allowed": False,
        "setting_sources": ["user"],
        "tools": [],
        "strict_empty_mcp": True,
        "session_persistence": False,
        "chrome": False,
        "max_turns_per_call": 1,
        "model": manifest["model"],
        "max_usd_per_call": manifest["budget"]["max_usd_per_call"],
        "trace_limits": manifest["trace_limits"],
    }
    if method != expected_method:
        errors.append("Claude result method is weakened or stale")
    environment = result.get("environment")
    if not isinstance(environment, dict) or environment.get("claude_version") != EXPECTED_CLAUDE_VERSION:
        errors.append("Claude result does not identify the required host version")
    plugin = result.get("plugin")
    if (
        not isinstance(plugin, dict)
        or plugin.get("path") != "<HOME>/.claude/skills/glossabet"
        or not is_sha256_hex(plugin.get("tree_sha256"))
        or not is_sha256_hex(plugin.get("skill_sha256"))
        or not is_sha256_hex(plugin.get("manifest_sha256"))
        or not is_sha256_hex(plugin.get("hook_sha256"))
        or not isinstance(plugin.get("enabled_plugins"), list)
    ):
        errors.append("Claude installed-plugin evidence is missing or malformed")
    scenarios = result.get("scenarios")
    if not isinstance(scenarios, list):
        scenarios = []
        errors.append("Claude scenario results are missing")
    for index, scenario in enumerate(manifest["scenarios"]):
        item = scenarios[index] if index < len(scenarios) else None
        errors.extend(
            result_scenario_errors(item, scenario, manifest["trace_limits"])
        )
    if len(scenarios) != len(SCENARIO_IDS):
        errors.append("Claude scenario result count is stale")
    passed = sum(
        isinstance(item, dict) and item.get("passed") is True for item in scenarios
    )
    expected_summary = {
        "required": 3,
        "passed": passed,
        "failed": 3 - passed,
        "all_passed": passed == 3,
    }
    if result.get("summary") != expected_summary:
        errors.append("Claude scenario summary is inconsistent")
    if not expected_summary["all_passed"]:
        errors.append("Claude evaluation scenarios did not all pass")
    if result.get("cleanup_verified") is not True:
        errors.append("Claude evaluator scratch cleanup is not verified")
    errors.extend(verify_history())
    try:
        result_digest = file_sha256(path)
        history = read_json(HISTORY_PATH, "Claude attempt history")
        retained = [
            item.get("raw_result", {}).get("sha256")
            for item in history.get("attempts", [])
            if isinstance(item, dict) and isinstance(item.get("raw_result"), dict)
        ]
        if result_digest not in retained:
            errors.append("Claude result is not retained by the attempt history")
    except (ClaudeEvaluationError, OSError) as exc:
        errors.append(f"Claude result retention is unreadable: {exc}")
    return errors
