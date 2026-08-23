"""Codex scenario manifest validation.

Per-scenario fixtures and judgments join this module in a later pass; for
now it owns the manifest contract that both the live runner and the
release-gate verifier consult.
"""

from __future__ import annotations

from evaluation.codex.contract import REQUIRED_SCENARIO_IDS, STATUS_VOCABULARY, fail


def validate_manifest(manifest: dict) -> tuple[list[dict], dict]:
    if manifest.get("schema_version") != 1:
        fail("unsupported agent scenario manifest")
    scenarios = manifest.get("scenarios")
    limits = manifest.get("trace_limits")
    if not isinstance(scenarios, list) or not isinstance(limits, dict):
        fail("agent scenario manifest is malformed")
    expected_ids = list(REQUIRED_SCENARIO_IDS)
    if [item.get("id") for item in scenarios if isinstance(item, dict)] != expected_ids:
        fail("agent scenario ids/order do not match the current contract")
    status_vocabulary = STATUS_VOCABULARY
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            fail("agent scenario is malformed")
        expected = scenario.get("expected_status")
        accepted = scenario.get("accepted_statuses", [expected])
        description = scenario.get("description")
        if not isinstance(description, str) or not description.strip():
            fail(f"agent scenario {scenario.get('id')} has no description")
        if (
            expected not in status_vocabulary
            or not isinstance(accepted, list)
            or not accepted
            or expected not in accepted
            or any(status not in status_vocabulary for status in accepted)
        ):
            fail(f"agent scenario {scenario.get('id')} has invalid statuses")
        expected_delivery = (
            "plugin-hook"
            if scenario.get("id") == "session-hook"
            else "standalone-skill"
            if scenario.get("id") == "missing-cli"
            else "plugin"
        )
        if scenario.get("delivery") != expected_delivery:
            fail(f"agent scenario {scenario.get('id')} has invalid delivery")
    required_limits = {
        "jsonl_bytes",
        "events",
        "commands_per_scenario",
        "stored_command_characters",
        "stored_output_characters",
    }
    if set(limits) != required_limits or not all(
        isinstance(value, int) and not isinstance(value, bool) and value > 0
        for value in limits.values()
    ):
        fail("agent trace limits are malformed")
    return scenarios, limits
