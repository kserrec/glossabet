"""Pure readers over Claude Code's retained JSONL event stream.

Used both live (to judge a fresh run) and offline (to prove a recorded
result still agrees with its own retained events). Nothing here spawns a
process or touches the filesystem.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from evaluation.claude.contract import fail


def parse_events(raw: str, limits: dict) -> list[dict]:
    size = len(raw.encode())
    if size > limits["jsonl_bytes_per_call"]:
        fail(
            f"Claude JSONL exceeded {limits['jsonl_bytes_per_call']} bytes "
            f"({size} observed)"
        )
    events: list[dict] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (ValueError, RecursionError) as exc:
            fail(f"Claude emitted non-JSON stdout: {line[:160]!r}: {exc}")
        if not isinstance(event, dict):
            fail("Claude JSONL event was not an object")
        events.append(event)
    if len(events) > limits["events_per_call"]:
        fail(
            f"Claude trace exceeded {limits['events_per_call']} events "
            f"({len(events)} observed)"
        )
    return events


def walk_values(value: object) -> Iterable[object]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_values(child)


def hook_event_seen(events: list[dict]) -> bool:
    return any(
        "hook" in text.casefold()
        and "sessionstart" in re.sub(r"[^a-z]", "", text.casefold())
        for event in events
        for text in [json.dumps(event, ensure_ascii=False)]
    )


def tool_calls(events: list[dict]) -> list[str]:
    calls: list[str] = []
    for event in events:
        for value in walk_values(event):
            if not isinstance(value, dict) or value.get("type") != "tool_use":
                continue
            name = value.get("name")
            calls.append(name if isinstance(name, str) else "<unnamed>")
    return calls


def api_retries(events: list[dict]) -> int:
    return sum(
        event.get("type") == "system" and event.get("subtype") == "api_retry"
        for event in events
    )


def structured_output(events: list[dict]) -> tuple[dict | None, dict]:
    results = [event for event in events if event.get("type") == "result"]
    if not results:
        return None, {}
    event = results[-1]
    value = event.get("structured_output")
    if value is None and isinstance(event.get("result"), str):
        try:
            value = json.loads(event["result"])
        except (ValueError, RecursionError):
            value = None
    usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
    usage = {
        key: item
        for key, item in usage.items()
        if isinstance(key, str) and isinstance(item, (int, float))
    }
    if isinstance(event.get("total_cost_usd"), (int, float)):
        usage["total_cost_usd"] = event["total_cost_usd"]
    return value if isinstance(value, dict) else None, usage


def response_shape_errors(response: object) -> list[str]:
    if not isinstance(response, dict):
        return ["Claude returned no structured response"]
    if set(response) != {"status", "term", "definition", "protocol"}:
        return ["Claude response keys differ from the response schema"]
    if response.get("status") not in {
        "supplied",
        "not-supplied",
        "skill-loaded",
        "skill-unavailable",
    }:
        return ["Claude response status is invalid"]
    errors = []
    for key, maximum in (("term", 200), ("definition", 500), ("protocol", 1000)):
        value = response.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > maximum):
            errors.append(f"Claude response {key} is malformed")
    return errors
