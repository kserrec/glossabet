"""Bounded parsing and normalization of Codex execution traces.

Raw JSONL from ``codex exec`` is parsed under the manifest's byte and event
limits, reduced to the command executions Glossabet judges, and summarized
with workspace, repository, and home paths redacted so a committed trace
never names the maintainer's machine. Everything here is pure: input text
and limits in, bounded records or a lane failure out.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation.codex.contract import ROOT, fail
from glossabet import __version__


def parse_events(raw: str, limits: dict) -> list[dict]:
    encoded = raw.encode("utf-8")
    if len(encoded) > limits["jsonl_bytes"]:
        fail(
            f"Codex JSONL exceeded {limits['jsonl_bytes']} bytes "
            f"({len(encoded)} observed)"
        )
    events = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (ValueError, RecursionError) as exc:
            fail(f"Codex emitted non-JSON stdout: {line[:200]!r}: {exc}")
        if not isinstance(event, dict):
            fail("Codex JSONL event was not an object")
        events.append(event)
    if len(events) > limits["events"]:
        fail(
            f"Codex trace exceeded {limits['events']} events "
            f"({len(events)} observed)"
        )
    return events


def command_items(events: list[dict]) -> list[dict]:
    commands = []
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "command_execution":
            continue
        command = item.get("command")
        output = item.get("aggregated_output", "")
        if not isinstance(command, str) or not isinstance(output, str):
            fail("Codex command trace is malformed")
        commands.append({
            "command": command,
            "cwd": item.get("cwd") if isinstance(item.get("cwd"), str) else None,
            "output": output,
            "exit_code": item.get("exit_code"),
            "status": item.get("status"),
        })
    return commands


def normalize_text(
    text: str,
    workspace: Path,
    limit: int,
    aliases: tuple[tuple[str, str], ...] = (),
) -> str:
    normalized = text
    for source, replacement in aliases:
        normalized = normalized.replace(source, replacement)
    normalized = normalized.replace(str(workspace), "<WORKSPACE>")
    # The agent may invoke absolute interpreter/shell paths the aliases above
    # never anticipated; redacting the repo root and home directory keeps a
    # committed, public trace from leaking the maintainer's username and
    # local layout. Repo root first (more specific than home).
    normalized = normalized.replace(str(ROOT), "<REPO>")
    normalized = normalized.replace(str(Path.home()), "<HOME>")
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "…"


def trace_summary(
    command: dict,
    workspace: Path,
    limits: dict,
    aliases: tuple[tuple[str, str], ...] = (),
) -> dict:
    output = command["output"]
    return {
        "command": normalize_text(
            command["command"],
            workspace,
            limits["stored_command_characters"],
            aliases,
        ),
        "cwd": (
            normalize_text(
                command["cwd"],
                workspace,
                limits["stored_command_characters"],
                aliases,
            )
            if command["cwd"] is not None else None
        ),
        "exit_code": command["exit_code"],
        "status": command["status"],
        "output_characters": len(output),
        "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
        "output_preview": normalize_text(
            output,
            workspace,
            limits["stored_output_characters"],
            aliases,
        ),
    }


def extract_context(output: str) -> dict | None:
    stripped = output.strip()
    if not stripped.startswith("{"):
        return None
    try:
        value = json.loads(stripped)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def scenario_commands(commands: list[dict], root: Path) -> list[dict]:
    needle = str(root)
    return [
        command
        for command in commands
        if needle in command["command"] or needle == command.get("cwd")
    ]


def installed_version_command(
    commands: list[dict],
    *,
    installed_path: Path,
    workspace: Path,
    limits: dict,
) -> dict:
    """Require one successful version check through the installed plugin path."""
    matching = [
        command
        for command in commands
        if str(installed_path) in command["command"]
        and "--version" in command["command"]
    ]
    aliases = ((str(installed_path), "<INSTALLED_PLUGIN>"),)
    version_commands = [
        normalize_text(
            command["command"],
            workspace,
            limits["stored_command_characters"],
            aliases,
        )
        for command in commands
        if "--version" in command["command"]
    ][:8]
    if len(matching) != 1:
        observed = json.dumps(version_commands) if version_commands else "none"
        fail(
            "installed plugin engine version-check count was "
            f"{len(matching)}, expected 1; observed --version commands: {observed}"
        )
    command = matching[0]
    expected = f"glossabet {__version__}"
    if command["output"].strip() != expected:
        output = command["output"]
        fail(
            "installed plugin engine version output did not match "
            f"{expected!r}; output characters={len(output)}, "
            f"sha256={hashlib.sha256(output.encode()).hexdigest()}"
        )
    return command
