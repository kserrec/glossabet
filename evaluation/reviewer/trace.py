"""Pure parsing and validation of the reviewer host's bounded trace."""

from __future__ import annotations

import hashlib
import json
import shlex
from pathlib import Path

from evaluation.reviewer.contract import ROOT, TRACE_LIMITS, ReviewerEvaluationError

_PACKET_READERS = frozenset({"cat", "/bin/cat", "/usr/bin/cat"})
_PACKET_SHELLS = frozenset({
    "sh", "bash", "zsh",
    "/bin/sh", "/bin/bash", "/bin/zsh",
    "/usr/bin/sh", "/usr/bin/bash", "/usr/bin/zsh",
})


def bounded_text(text: str, workspace: Path, limit: int) -> str:
    normalized = text.replace(str(workspace), "<REVIEW_WORKSPACE>")
    # The reviewer may echo an absolute interpreter or shell path that the
    # workspace replacement never anticipated. Scrub the repository root and
    # home directory too so retained public evidence cannot leak the
    # maintainer's username or layout. Repository root first: it is more
    # specific than home.
    normalized = normalized.replace(str(ROOT), "<REPO>")
    normalized = normalized.replace(str(Path.home()), "<HOME>")
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "…"


def is_packet_only_command(command: str) -> bool:
    """Accept only the exact blinded-packet read used by the reviewer lane."""
    try:
        arguments = shlex.split(command)
    except ValueError:
        return False
    if (
        len(arguments) == 2
        and arguments[0] in _PACKET_READERS
        and arguments[1] == "reviewer-packet.json"
    ):
        return True
    if (
        len(arguments) != 3
        or arguments[0] not in _PACKET_SHELLS
        or arguments[1] not in {"-c", "-lc"}
    ):
        return False
    try:
        inner = shlex.split(arguments[2])
    except ValueError:
        return False
    return (
        len(inner) == 2
        and inner[0] in _PACKET_READERS
        and inner[1] == "reviewer-packet.json"
    )


def parse_reviewer_trace(raw: str, workspace: Path) -> tuple[list[dict], dict]:
    if len(raw.encode("utf-8")) > TRACE_LIMITS["jsonl_bytes"]:
        raise ReviewerEvaluationError(
            "second-reviewer JSONL exceeded its byte bound"
        )
    events = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (ValueError, RecursionError) as exc:
            raise ReviewerEvaluationError(
                f"second reviewer emitted non-JSON stdout: {exc}"
            ) from exc
        if not isinstance(event, dict):
            raise ReviewerEvaluationError(
                "second-reviewer JSONL event was not an object"
            )
        events.append(event)
    if len(events) > TRACE_LIMITS["events"]:
        raise ReviewerEvaluationError(
            "second-reviewer JSONL exceeded its event bound"
        )
    try:
        resolved_workspace = workspace.resolve()
        packet_output = (workspace / "reviewer-packet.json").read_text(
            encoding="utf-8"
        )
    except (OSError, UnicodeError) as exc:
        raise ReviewerEvaluationError(
            "second-reviewer blinded packet could not be verified"
        ) from exc

    commands = []
    disallowed_items = []
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in {"file_change", "mcp_tool_call", "web_search"}:
            disallowed_items.append(item_type)
        if item_type != "command_execution":
            continue
        command = item.get("command")
        output = item.get("aggregated_output", "")
        if not isinstance(command, str) or not isinstance(output, str):
            raise ReviewerEvaluationError(
                "second-reviewer command trace is malformed"
            )
        if not is_packet_only_command(command):
            raise ReviewerEvaluationError(
                "second reviewer issued a command outside the blinded packet"
            )
        cwd = item.get("cwd")
        try:
            cwd_matches = (
                cwd is None
                or isinstance(cwd, str)
                and Path(cwd).resolve() == resolved_workspace
            )
        except (OSError, RuntimeError):
            cwd_matches = False
        if not cwd_matches:
            raise ReviewerEvaluationError(
                "second reviewer issued a command outside the isolated workspace"
            )
        if output != packet_output:
            raise ReviewerEvaluationError(
                "second-reviewer command output did not match the blinded packet"
            )
        commands.append({
            "command": bounded_text(
                command, workspace, TRACE_LIMITS["stored_command_characters"]
            ),
            "cwd": (
                bounded_text(
                    cwd,
                    workspace,
                    TRACE_LIMITS["stored_command_characters"],
                )
                if isinstance(cwd, str) else None
            ),
            "exit_code": item.get("exit_code"),
            "status": item.get("status"),
            "output_characters": len(output),
            "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
            "output_preview": bounded_text(
                output, workspace, TRACE_LIMITS["stored_output_characters"]
            ),
        })
    if disallowed_items:
        raise ReviewerEvaluationError(
            f"second reviewer used disallowed tools: {sorted(set(disallowed_items))}"
        )
    if not commands or len(commands) > TRACE_LIMITS["commands"]:
        raise ReviewerEvaluationError(
            "second reviewer did not use a bounded packet-only trace"
        )
    if any(
        command.get("status") != "completed"
        or command.get("exit_code") != 0
        for command in commands
    ):
        raise ReviewerEvaluationError(
            "second-reviewer packet read did not complete"
        )

    usage = next(
        (
            event.get("usage", {})
            for event in reversed(events)
            if event.get("type") == "turn.completed"
        ),
        {},
    )
    return commands, usage
