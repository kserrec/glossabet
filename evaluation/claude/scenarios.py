"""Per-scenario judgment for the Claude lane: the model's structured
response, its retained events, the direct brief, and the fixture diff in;
every named failure plus the recorded observations out. Pure.
"""

from __future__ import annotations

import json

from evaluation.claude.contract import (
    CANONICAL_DEFINITION,
    CANONICAL_TERM,
    PROPOSED_TERM,
    SOURCE_CANARY,
    sha256_text,
)
from evaluation.claude.events import (
    api_retries,
    hook_event_seen,
    response_shape_errors,
    tool_calls,
)


def scenario_errors(
    scenario: dict,
    *,
    response: dict | None,
    events: list[dict],
    direct_brief: str,
    unexpected_writes: list[str],
    returncode: int,
) -> tuple[list[str], dict]:
    failures = response_shape_errors(response)
    tools = tool_calls(events)
    hook_seen = hook_event_seen(events)
    retries = api_retries(events)
    if returncode:
        failures.append(f"Claude exited {returncode}")
    if tools:
        failures.append(f"model used tools despite the zero-tool command: {tools}")
    if not hook_seen:
        failures.append("SessionStart hook lifecycle event was not observed")
    if retries:
        failures.append(f"Claude performed {retries} API retries")
    if unexpected_writes:
        failures.append(f"fixture changed: {unexpected_writes}")
    serialized = json.dumps({"response": response, "events": events}, ensure_ascii=False)
    if PROPOSED_TERM in serialized:
        failures.append("proposed vocabulary reached the model trace")
    if SOURCE_CANARY in serialized:
        failures.append("repository source canary reached the model trace")
    scenario_id = scenario["id"]
    response = response or {}
    if scenario_id == "ambient-present":
        if response.get("status") != "supplied":
            failures.append("ambient-present did not report supplied vocabulary")
        if response.get("term") != CANONICAL_TERM:
            failures.append("ambient-present lost the canonical term")
        if response.get("definition") != CANONICAL_DEFINITION:
            failures.append("ambient-present lost the canonical definition")
        if response.get("protocol") is not None:
            failures.append("ambient-present returned a skill protocol")
        if CANONICAL_TERM not in direct_brief or CANONICAL_DEFINITION not in direct_brief:
            failures.append("direct brief lacks the canonical vocabulary")
    elif scenario_id == "ambient-absent":
        if response.get("status") != "not-supplied":
            failures.append("ambient-absent claimed vocabulary was supplied")
        if any(response.get(key) is not None for key in ("term", "definition", "protocol")):
            failures.append("ambient-absent returned vocabulary or a protocol")
        if direct_brief != "":
            failures.append("no-glossary direct brief was not empty")
        if CANONICAL_TERM in serialized or CANONICAL_DEFINITION in serialized:
            failures.append("no-glossary trace contains the canonical fixture vocabulary")
    elif scenario_id == "skill-root":
        protocol = response.get("protocol")
        normalized = protocol.casefold() if isinstance(protocol, str) else ""
        if response.get("status") != "skill-loaded":
            failures.append("root /glossabet skill was not reported as loaded")
        if response.get("term") is not None or response.get("definition") is not None:
            failures.append("skill-root returned ambient vocabulary fields")
        if not all(item in normalized for item in ("step 0", "version", "inspect")):
            failures.append("skill-root response lacks the Step 0 version/inspect boundary")
        if not any(item in normalized for item in ("tool", "disabled", "unavailable", "cannot")):
            failures.append("skill-root did not stop at the unavailable-tools boundary")
    else:
        failures.append(f"unknown scenario result: {scenario_id}")
    observed = {
        "hook_event_seen": hook_seen,
        "tool_calls": tools,
        "api_retries": retries,
        "unexpected_writes": unexpected_writes,
        "direct_brief_sha256": sha256_text(direct_brief),
        "canonical_term_seen": CANONICAL_TERM in serialized,
        "canonical_definition_seen": CANONICAL_DEFINITION in serialized,
        "proposed_term_absent": PROPOSED_TERM not in serialized,
        "source_canary_absent": SOURCE_CANARY not in serialized,
    }
    return list(dict.fromkeys(failures)), observed
