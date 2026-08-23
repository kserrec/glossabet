#!/usr/bin/env python3
"""Build and verify bounded Claude Code live-host evidence.

Everything except ``--run`` is offline. A live run requires a conspicuous
confirmation phrase, reuses the already signed-in normal Claude profile, and
never invokes an authentication command. The three model calls have no tools,
no MCP servers, no saved sessions, and no evaluator retry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, NoReturn

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_PATH = ROOT / "evaluation" / "claude-scenarios.json"
RESPONSE_SCHEMA_PATH = ROOT / "evaluation" / "claude-response-schema.json"
HISTORY_PATH = ROOT / "evaluation" / "claude-history.json"
DEFAULT_RESULTS = ROOT / "evaluation" / "claude-results.json"
RUNS_PATH = ROOT / "evaluation" / "agent-runs"
CANONICAL_SKILL = ROOT / "skill" / "SKILL.md"
DEFAULT_INSTALLED_PLUGIN = Path.home() / ".claude" / "skills" / "glossabet"

RESULT_SCHEMA_VERSION = 1
HISTORY_SCHEMA_VERSION = 1
EXPECTED_CLAUDE_VERSION = "2.1.235"
LIVE_CONFIRMATION = "run-three-normal-profile-claude-calls-no-retry"
SCENARIO_IDS = ("ambient-present", "ambient-absent", "skill-root")

CANONICAL_TERM = "Copper Finch"
CANONICAL_DEFINITION = (
    "A frozen collection request carrying the order key and amount in cents."
)
PROPOSED_TERM = "Silver Heron"
SOURCE_CANARY = "SOURCE_ONLY_MARIGOLD_71C2"

MAX_JSON_BYTES = 16_000_000
_RUN_NAME = re.compile(
    r"\d{8}T\d{6}Z-claude-[a-z0-9-]+-[0-9a-f]{8}\.json"
)
_HOOK_COMMAND = re.compile(r'^"([^"\n]+)" brief \.$')
_PROVIDER_ENV_KEYS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_FOUNDRY",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CONFIG_DIR",
    }
)
_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)

sys.path.insert(0, str(ROOT))

from evaluation.harness.identity import lane_source_identity  # noqa: E402
from evaluation.harness.io import (  # noqa: E402
    changed_paths,
    dotenv_part,
    file_sha256,
    framed_digest,
    is_sha256_hex,
    read_json_object,
)
from glossabet import __version__  # noqa: E402
from glossabet.install.claude_plugin import (  # noqa: E402
    CLAUDE_HOOKS_RELATIVE,
    CLAUDE_MANIFEST_RELATIVE,
    claude_hooks,
    claude_plugin_manifest,
)


class ClaudeEvaluationError(RuntimeError):
    """The bounded host run or its retained evidence broke its contract."""


def _fail(message: str) -> NoReturn:
    raise ClaudeEvaluationError(message)



def _read_json(path: Path, label: str) -> dict:
    return read_json_object(
        path,
        label,
        max_bytes=MAX_JSON_BYTES,
        fail=_fail,
        reject_symlink=True,
        overflow_suffix="",
    )



def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _replace_json(path: Path, value: object) -> None:
    if path.is_symlink():
        _fail(f"refusing to replace symlinked JSON: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(_json_bytes(value))
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_new_json(path: Path, value: object) -> None:
    if path.exists() or path.is_symlink():
        _fail(f"refusing to overwrite evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(_json_bytes(value))
        try:
            os.link(temporary, path)
        except FileExistsError:
            _fail(f"refusing to overwrite evidence: {path}")
    finally:
        if temporary.exists():
            temporary.unlink()


def _tree_sha256(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        _fail(f"tree is missing or symlinked: {root}")
    files: list[Path] = []
    for current, directories, names in os.walk(root, followlinks=False):
        kept = []
        for name in sorted(directories):
            path = Path(current) / name
            if dotenv_part(name) or name == "__pycache__":
                continue
            if path.is_symlink():
                _fail(f"tree contains a symlinked directory: {path}")
            kept.append(name)
        directories[:] = kept
        for name in sorted(names):
            if dotenv_part(name) or name.endswith(".pyc"):
                continue
            path = Path(current) / name
            if path.is_symlink():
                _fail(f"tree contains a symlinked file: {path}")
            files.append(path)
    ordered = sorted(files, key=lambda item: item.relative_to(root).as_posix())
    return framed_digest(
        (path.relative_to(root).as_posix(), path.read_bytes()) for path in ordered
    )


def _snapshot(root: Path) -> dict[str, tuple]:
    """Hash a fixture without descending into Git or any dotenv path."""
    snapshot: dict[str, tuple] = {}
    for current, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(
            name
            for name in directories
            if name not in {".git", "__pycache__"} and not dotenv_part(name)
        )
        for name in sorted(names):
            if dotenv_part(name) or name.endswith(".pyc"):
                continue
            path = Path(current) / name
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            if path.is_symlink():
                snapshot[relative] = ("symlink", os.readlink(path))
            else:
                snapshot[relative] = (
                    "file",
                    info.st_size,
                    stat.S_IMODE(info.st_mode),
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
    return snapshot



def _manifest() -> dict:
    value = _read_json(SCENARIOS_PATH, "Claude scenario manifest")
    if value.get("schema_version") != 1:
        _fail("Claude scenario manifest schema is stale")
    host = value.get("host")
    budget = value.get("budget")
    limits = value.get("trace_limits")
    scenarios = value.get("scenarios")
    if host != {
        "name": "Claude Code",
        "version": EXPECTED_CLAUDE_VERSION,
        "platform": "Linux",
    }:
        _fail("Claude scenario host contract is stale")
    if not isinstance(budget, dict) or budget != {
        "calls": 3,
        "retries": 0,
        "estimated_total_input_tokens": 200000,
        "estimated_total_output_tokens": 6000,
        "max_usd_per_call": 0.25,
    }:
        _fail("Claude scenario budget contract is stale")
    if (
        not isinstance(limits, dict)
        or set(limits)
        != {
            "jsonl_bytes_per_call",
            "events_per_call",
            "stored_string_characters",
        }
        or any(not isinstance(item, int) or item <= 0 for item in limits.values())
        or limits["jsonl_bytes_per_call"] > 5_000_000
        or limits["events_per_call"] > 2_000
        or limits["stored_string_characters"] > 20_000
    ):
        _fail("Claude scenario trace limits are malformed or unbounded")
    if not isinstance(scenarios, list) or [
        item.get("id") for item in scenarios if isinstance(item, dict)
    ] != list(SCENARIO_IDS):
        _fail("Claude scenario ids/order are stale")
    for scenario in scenarios:
        if not isinstance(scenario, dict) or set(scenario) != {
            "id",
            "fixture",
            "expected_status",
            "disable_skills",
            "prompt",
        }:
            _fail("Claude scenario shape is malformed")
        if not isinstance(scenario["prompt"], str) or not scenario["prompt"]:
            _fail(f"{scenario['id']}: prompt is missing")
    if value.get("model") != "sonnet":
        _fail("Claude scenario model is stale")
    return value


def _response_schema() -> dict:
    schema = _read_json(RESPONSE_SCHEMA_PATH, "Claude response schema")
    required = schema.get("required")
    properties = schema.get("properties")
    if (
        schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or required != ["status", "term", "definition", "protocol"]
        or not isinstance(properties, dict)
        or set(properties) != set(required)
    ):
        _fail("Claude response schema contract is stale")
    return schema


def _provider_environment_name(name: str) -> bool:
    return name in _PROVIDER_ENV_KEYS or name.startswith("ANTHROPIC_")


def _normal_profile_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    environment = dict(os.environ)
    for name in tuple(environment):
        if _provider_environment_name(name):
            environment.pop(name)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["NO_COLOR"] = "1"
    if extra:
        environment.update(
            {
                name: value
                for name, value in extra.items()
                if not _provider_environment_name(name)
            }
        )
    return environment


def _safe_text(value: str, *roots: tuple[Path, str], limit: int = 2000) -> str:
    sanitized = value
    for path, replacement in roots:
        sanitized = sanitized.replace(str(path), replacement)
    sanitized = sanitized.replace(str(ROOT), "<REPO>")
    sanitized = sanitized.replace(str(Path.home()), "<HOME>")
    return sanitized if len(sanitized) <= limit else sanitized[:limit] + "…"


def _command(
    arguments: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            arguments,
            cwd=cwd,
            env=environment,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _fail(f"could not run {Path(arguments[0]).name}: {type(exc).__name__}")


def _require_success(
    result: subprocess.CompletedProcess[str], label: str, *, roots=()
) -> str:
    if result.returncode:
        detail = _safe_text(result.stderr or result.stdout, *roots)
        _fail(f"{label} exited {result.returncode}: {detail}")
    return result.stdout


def _claude_version(
    claude: Path, *, environment: dict[str, str]
) -> str:
    result = _command([str(claude), "--version"], cwd=ROOT, environment=environment)
    output = _require_success(result, "claude --version").strip()
    match = re.fullmatch(r"([^\s]+) \(Claude Code\)", output)
    if match is None:
        _fail("Claude Code returned an unrecognized version string")
    version = match.group(1)
    if version != EXPECTED_CLAUDE_VERSION:
        _fail(
            f"Claude Code version is {version}; this evaluator requires "
            f"{EXPECTED_CLAUDE_VERSION}"
        )
    return version


def _auth_status(
    claude: Path, *, environment: dict[str, str]
) -> dict:
    result = _command(
        [
            str(claude),
            "--setting-sources",
            "user",
            "auth",
            "status",
            "--json",
        ],
        cwd=ROOT,
        environment=environment,
    )
    if result.returncode:
        _fail("normal-profile Claude authentication preflight failed")
    try:
        value = json.loads(result.stdout)
    except (ValueError, RecursionError):
        _fail("normal-profile Claude authentication preflight was malformed")
    if not isinstance(value, dict):
        _fail("normal-profile Claude authentication preflight was malformed")
    safe = {
        "logged_in": value.get("loggedIn"),
        "auth_method": value.get("authMethod"),
        "api_provider": value.get("apiProvider"),
        "subscription_type": value.get("subscriptionType"),
    }
    if safe != {
        "logged_in": True,
        "auth_method": "claude.ai",
        "api_provider": "firstParty",
        "subscription_type": "max",
    }:
        _fail(
            "normal-profile Claude authentication is not the expected "
            "signed-in first-party Max subscription; refusing to open login"
        )
    return safe


def _installed_plugin(
    plugin: Path, *, environment: dict[str, str]
) -> tuple[dict, Path]:
    plugin = plugin.expanduser().absolute()
    if plugin.is_symlink() or not plugin.is_dir():
        _fail(f"installed Claude plugin is missing or symlinked: {plugin}")
    skill = plugin / "SKILL.md"
    manifest_path = plugin / CLAUDE_MANIFEST_RELATIVE
    hook_path = plugin / CLAUDE_HOOKS_RELATIVE
    for label, path in (
        ("installed skill", skill),
        ("installed manifest", manifest_path),
        ("installed hook", hook_path),
    ):
        if path.is_symlink() or not path.is_file():
            _fail(f"{label} is missing or symlinked")
    if skill.read_bytes() != CANONICAL_SKILL.read_bytes():
        _fail("installed Claude skill differs from the canonical skill")
    manifest = _read_json(manifest_path, "installed Claude manifest")
    if manifest != claude_plugin_manifest():
        _fail("installed Claude manifest differs from the current contract")
    hook = _read_json(hook_path, "installed Claude hook")
    try:
        command = hook["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    except (KeyError, IndexError, TypeError):
        _fail("installed Claude hook shape is malformed")
    match = _HOOK_COMMAND.fullmatch(command) if isinstance(command, str) else None
    if match is None:
        _fail("installed Claude hook command is malformed")
    executable = Path(match.group(1))
    if not executable.is_absolute() or not executable.is_file():
        _fail("installed Claude hook executable is missing or unsafe")
    if hook != claude_hooks(executable):
        _fail("installed Claude hook differs from the current contract")
    version = _command(
        [str(executable), "--version"], cwd=ROOT, environment=environment
    )
    if version.returncode or version.stdout.strip() != f"glossabet {__version__}":
        _fail("installed Claude hook executable has the wrong Glossabet version")
    return (
        {
            "path": "<HOME>/.claude/skills/glossabet",
            "tree_sha256": _tree_sha256(plugin),
            "skill_sha256": file_sha256(skill),
            "manifest_sha256": file_sha256(manifest_path),
            "hook_sha256": file_sha256(hook_path),
            "hook_executable": "<HOME>/.local/bin/glossabet",
        },
        executable,
    )


def _plugin_inventory(
    claude: Path,
    plugin: Path,
    *,
    environment: dict[str, str],
) -> list[dict]:
    validation = _command(
        [str(claude), "plugin", "validate", str(plugin)],
        cwd=ROOT,
        environment=environment,
    )
    _require_success(
        validation,
        "claude plugin validate",
        roots=((plugin, "<INSTALLED_PLUGIN>"),),
    )
    listing = _command(
        [
            str(claude),
            "--setting-sources",
            "user",
            "plugin",
            "list",
            "--json",
        ],
        cwd=ROOT,
        environment=environment,
    )
    output = _require_success(listing, "claude plugin list")
    try:
        records = json.loads(output)
    except (ValueError, RecursionError):
        _fail("Claude plugin inventory was malformed")
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        _fail("Claude plugin inventory was malformed")
    enabled = [item for item in records if item.get("enabled") is True]
    matches = [item for item in enabled if item.get("id") == "glossabet@skills-dir"]
    if len(matches) != 1:
        _fail("Claude plugin inventory does not contain one enabled glossabet@skills-dir")
    install_path = matches[0].get("installPath")
    if not isinstance(install_path, str) or Path(install_path).resolve() != plugin.resolve():
        _fail("Claude plugin inventory points Glossabet at another folder")
    safe_inventory: list[dict] = []
    for item in enabled:
        plugin_id = item.get("id")
        if not isinstance(plugin_id, str) or not plugin_id:
            _fail("Claude plugin inventory contains an unnamed enabled plugin")
        details = _command(
            [
                str(claude),
                "--setting-sources",
                "user",
                "plugin",
                "details",
                plugin_id,
            ],
            cwd=ROOT,
            environment=environment,
        )
        text = _require_success(details, f"claude plugin details {plugin_id}")
        hook_match = re.search(r"Hooks \((\d+)\)(?:\s+([^\n]+))?", text)
        if hook_match is None:
            _fail(f"Claude plugin details did not report hook count for {plugin_id}")
        hooks = int(hook_match.group(1))
        hook_names = (hook_match.group(2) or "").strip()
        if plugin_id == "glossabet@skills-dir":
            if hooks != 1 or "SessionStart" not in hook_names:
                _fail("Glossabet plugin does not expose exactly one SessionStart hook")
        elif hooks:
            _fail(f"enabled plugin {plugin_id} has hooks that could contaminate the run")
        safe_inventory.append(
            {
                "id": plugin_id,
                "version": item.get("version") if isinstance(item.get("version"), str) else None,
                "scope": item.get("scope") if isinstance(item.get("scope"), str) else None,
                "hooks": hooks,
            }
        )
    return safe_inventory


def preflight(
    claude: Path,
    installed_plugin: Path,
    *,
    environment: dict[str, str] | None = None,
) -> tuple[dict, Path]:
    environment = _normal_profile_environment(environment)
    if platform.system() != "Linux":
        _fail("this evidence plan is scoped to Linux")
    if not claude.is_file():
        _fail(f"Claude executable is missing: {claude}")
    version = _claude_version(claude, environment=environment)
    auth = _auth_status(claude, environment=environment)
    plugin_record, hook_executable = _installed_plugin(
        installed_plugin, environment=environment
    )
    inventory = _plugin_inventory(
        claude, installed_plugin, environment=environment
    )
    return (
        {
            "claude_version": version,
            "platform": platform.platform(),
            "auth": auth,
            "plugin": plugin_record,
            "enabled_plugins": inventory,
        },
        hook_executable,
    )


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.fsmonitor=",
            "-c",
            "core.hooksPath=/dev/null",
            *arguments,
        ],
        cwd=root,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        },
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        _fail(result.stderr.strip() or result.stdout.strip() or "git failed")
    return result.stdout.strip()


def _create_fixture(root: Path, kind: str) -> None:
    root.mkdir(parents=True)
    (root / "payment.py").write_text(
        "from dataclasses import dataclass\n\n"
        "@dataclass(frozen=True)\n"
        "class ChargeIntent:\n"
        "    order_key: str\n"
        "    amount_cents: int\n\n"
        f'SOURCE_NOTE = "{SOURCE_CANARY}"\n',
        encoding="utf-8",
    )
    if kind == "managed-glossary":
        glossary = root / "glossabet-out" / "glossary.json"
        _write_json(
            glossary,
            {
                "schema_version": 1,
                "concepts": [
                    {
                        "id": "copper-finch",
                        "term": CANONICAL_TERM,
                        "definition": CANONICAL_DEFINITION,
                        "status": "canonical",
                    },
                    {
                        "id": "silver-heron",
                        "term": PROPOSED_TERM,
                        "definition": "An unsettled alternate name.",
                        "status": "proposed",
                    },
                ],
            },
        )
    elif kind != "no-glossary":
        _fail(f"unknown Claude fixture kind: {kind}")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(
        root,
        "-c",
        "user.email=claude-eval@example.invalid",
        "-c",
        "user.name=Claude Eval",
        "commit",
        "-qm",
        "fixture",
    )


def _input_identity(installed_plugin: Path) -> dict:
    return {
        "evaluator_sha256": lane_source_identity("claude"),
        "scenario_manifest_sha256": file_sha256(SCENARIOS_PATH),
        "response_schema_sha256": file_sha256(RESPONSE_SCHEMA_PATH),
        "canonical_skill_sha256": file_sha256(CANONICAL_SKILL),
        "installed_plugin_sha256": _tree_sha256(installed_plugin),
        "engine_version": __version__,
    }


def _claude_command(
    claude: Path,
    scenario: dict,
    manifest: dict,
    schema: dict,
) -> list[str]:
    command = [
        str(claude),
        "--setting-sources",
        "user",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--no-chrome",
        "--no-session-persistence",
        "--permission-mode",
        "dontAsk",
        "--tools",
        "",
        "--model",
        manifest["model"],
        "--effort",
        "low",
        "--max-budget-usd",
        str(manifest["budget"]["max_usd_per_call"]),
        "--max-turns",
        "1",
        "--output-format",
        "stream-json",
        "--include-hook-events",
        "--verbose",
        "--json-schema",
        json.dumps(schema, separators=(",", ":"), ensure_ascii=False),
    ]
    if scenario["disable_skills"] is True:
        command.append("--disable-slash-commands")
    command.extend(["-p", scenario["prompt"]])
    return command


def _parse_events(raw: str, limits: dict) -> list[dict]:
    size = len(raw.encode())
    if size > limits["jsonl_bytes_per_call"]:
        _fail(
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
            _fail(f"Claude emitted non-JSON stdout: {line[:160]!r}: {exc}")
        if not isinstance(event, dict):
            _fail("Claude JSONL event was not an object")
        events.append(event)
    if len(events) > limits["events_per_call"]:
        _fail(
            f"Claude trace exceeded {limits['events_per_call']} events "
            f"({len(events)} observed)"
        )
    return events


def _walk_values(value: object) -> Iterable[object]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_values(child)


def _hook_event_seen(events: list[dict]) -> bool:
    return any(
        "hook" in text.casefold()
        and "sessionstart" in re.sub(r"[^a-z]", "", text.casefold())
        for event in events
        for text in [json.dumps(event, ensure_ascii=False)]
    )


def _tool_calls(events: list[dict]) -> list[str]:
    calls: list[str] = []
    for event in events:
        for value in _walk_values(event):
            if not isinstance(value, dict) or value.get("type") != "tool_use":
                continue
            name = value.get("name")
            calls.append(name if isinstance(name, str) else "<unnamed>")
    return calls


def _api_retries(events: list[dict]) -> int:
    return sum(
        event.get("type") == "system" and event.get("subtype") == "api_retry"
        for event in events
    )


def _structured_output(events: list[dict]) -> tuple[dict | None, dict]:
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


def _sanitize_value(
    value: object,
    *,
    workspace: Path,
    limit: int,
    key: str | None = None,
) -> object:
    if key == "session_id":
        return "<SESSION>"
    if key == "transcript_path":
        return "<TRANSCRIPT>"
    if isinstance(value, str):
        return _safe_text(
            value,
            (workspace, "<WORKSPACE>"),
            limit=limit,
        )
    if isinstance(value, list):
        return [
            _sanitize_value(item, workspace=workspace, limit=limit)
            for item in value
        ]
    if isinstance(value, dict):
        return {
            str(child_key): _sanitize_value(
                child,
                workspace=workspace,
                limit=limit,
                key=str(child_key),
            )
            for child_key, child in value.items()
        }
    return value


def _response_shape_errors(response: object) -> list[str]:
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


def _scenario_errors(
    scenario: dict,
    *,
    response: dict | None,
    events: list[dict],
    direct_brief: str,
    unexpected_writes: list[str],
    returncode: int,
) -> tuple[list[str], dict]:
    failures = _response_shape_errors(response)
    tools = _tool_calls(events)
    hook_seen = _hook_event_seen(events)
    retries = _api_retries(events)
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
        "direct_brief_sha256": _sha256_text(direct_brief),
        "canonical_term_seen": CANONICAL_TERM in serialized,
        "canonical_definition_seen": CANONICAL_DEFINITION in serialized,
        "proposed_term_absent": PROPOSED_TERM not in serialized,
        "source_canary_absent": SOURCE_CANARY not in serialized,
    }
    return list(dict.fromkeys(failures)), observed


def _direct_brief(
    executable: Path,
    root: Path,
    *,
    environment: dict[str, str],
) -> str:
    result = _command(
        [str(executable), "brief", "."],
        cwd=root,
        environment=environment,
    )
    return _require_success(
        result,
        "installed Glossabet brief",
        roots=((root, "<WORKSPACE>"),),
    )


def _run_scenario(
    claude: Path,
    hook_executable: Path,
    root: Path,
    scenario: dict,
    manifest: dict,
    schema: dict,
    *,
    environment: dict[str, str],
) -> tuple[dict, dict]:
    limits = manifest["trace_limits"]
    before = _snapshot(root)
    direct_brief = _direct_brief(hook_executable, root, environment=environment)
    after_brief = _snapshot(root)
    brief_writes = changed_paths(before, after_brief)
    command = _claude_command(claude, scenario, manifest, schema)
    result = _command(
        command,
        cwd=root,
        environment=environment,
        timeout=600,
    )
    after = _snapshot(root)
    unexpected_writes = sorted(set(brief_writes + changed_paths(after_brief, after)))
    parse_failure: str | None = None
    try:
        events = _parse_events(result.stdout, limits)
    except ClaudeEvaluationError as exc:
        events = []
        parse_failure = str(exc)
    response, usage = _structured_output(events)
    failures, observed = _scenario_errors(
        scenario,
        response=response,
        events=events,
        direct_brief=direct_brief,
        unexpected_writes=unexpected_writes,
        returncode=result.returncode,
    )
    if parse_failure:
        failures.insert(0, parse_failure)
    sanitized_events = [
        _sanitize_value(
            event,
            workspace=root,
            limit=limits["stored_string_characters"],
        )
        for event in events
    ]
    stderr = _safe_text(
        result.stderr,
        (root, "<WORKSPACE>"),
        limit=limits["stored_string_characters"],
    )
    record = {
        "id": scenario["id"],
        "passed": not failures,
        "failures": failures,
        "prompt": scenario["prompt"],
        "prompt_sha256": _sha256_text(scenario["prompt"]),
        "response": response,
        "observed": observed,
        "returncode": result.returncode,
        "stdout_sha256": _sha256_text(result.stdout),
        "stderr": stderr,
        "stderr_sha256": _sha256_text(result.stderr),
        "stderr_sanitized_sha256": _sha256_text(stderr),
        "events": sanitized_events,
        "usage": usage,
    }
    return record, usage


def _usage_totals(records: list[dict]) -> dict:
    totals = {
        key: sum(
            item.get(key, 0)
            for item in records
            if isinstance(item.get(key, 0), (int, float))
        )
        for key in _USAGE_KEYS
    }
    costs = [
        item.get("total_cost_usd")
        for item in records
        if isinstance(item.get("total_cost_usd"), (int, float))
    ]
    totals["total_cost_usd"] = sum(costs) if costs else None
    return totals


def _owned_scratch(parent: Path) -> Path:
    parent = parent.resolve()
    if parent.is_symlink() or not parent.is_dir():
        _fail(f"scratch parent is missing or symlinked: {parent}")
    return Path(tempfile.mkdtemp(prefix="glossabet-claude-eval-", dir=parent))


def _remove_owned_scratch(root: Path, parent: Path) -> bool:
    resolved_parent = parent.resolve()
    resolved_root = root.resolve()
    if (
        root.is_symlink()
        or resolved_root.parent != resolved_parent
        or not resolved_root.name.startswith("glossabet-claude-eval-")
    ):
        _fail(f"refusing to remove unowned scratch path: {root}")
    shutil.rmtree(resolved_root)
    return not resolved_root.exists()


def _validated_output(path: Path) -> Path:
    candidate = path if path.is_absolute() else ROOT / path
    if RUNS_PATH.is_symlink() or candidate.suffix != ".json":
        _fail("Claude run output must be a JSON file in evaluation/agent-runs")
    resolved = candidate.resolve()
    if resolved.parent != RUNS_PATH.resolve() or not _RUN_NAME.fullmatch(resolved.name):
        _fail("Claude run output name/path does not match the immutable-run contract")
    if candidate.exists() or candidate.is_symlink():
        _fail(f"refusing to overwrite Claude run evidence: {candidate}")
    return candidate


def _new_attempt_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-claude-full-{uuid.uuid4().hex[:8]}"


def run_evaluation(
    output: Path,
    *,
    claude: Path,
    installed_plugin: Path = DEFAULT_INSTALLED_PLUGIN,
    scratch_parent: Path = Path("/tmp"),
    environment: dict[str, str] | None = None,
) -> dict:
    manifest = _manifest()
    schema = _response_schema()
    environment = _normal_profile_environment(environment)
    preflight_record, hook_executable = preflight(
        claude,
        installed_plugin,
        environment=environment,
    )
    work = _owned_scratch(scratch_parent)
    results: list[dict] = []
    usages: list[dict] = []
    cleanup_verified = False
    try:
        for scenario in manifest["scenarios"]:
            root = work / scenario["id"]
            _create_fixture(root, scenario["fixture"])
            scenario_environment = {
                **environment,
                "GLOSSABET_CACHE_DIR": str(work / ".glossabet-cache"),
            }
            result, usage = _run_scenario(
                claude,
                hook_executable,
                root,
                scenario,
                manifest,
                schema,
                environment=scenario_environment,
            )
            results.append(result)
            usages.append(usage)
    finally:
        try:
            cleanup_verified = _remove_owned_scratch(work, scratch_parent)
        except BaseException as exc:
            failure = ClaudeEvaluationError(
                "evaluator scratch cleanup failed: "
                f"{type(exc).__name__}: {str(exc) or 'no detail'}"
            )
            failure.cleanup_verified = False
            raise failure from exc
    passed = sum(item["passed"] is True for item in results)
    summary = {
        "required": len(SCENARIO_IDS),
        "passed": passed,
        "failed": len(SCENARIO_IDS) - passed,
        "all_passed": passed == len(SCENARIO_IDS),
    }
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": _input_identity(installed_plugin),
        "environment": {
            "claude_version": preflight_record["claude_version"],
            "platform": preflight_record["platform"],
            "python": platform.python_version(),
        },
        "auth": preflight_record["auth"],
        "plugin": {
            **preflight_record["plugin"],
            "enabled_plugins": preflight_record["enabled_plugins"],
        },
        "method": {
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
        },
        "scenarios": results,
        "usage": _usage_totals(usages),
        "cleanup_verified": cleanup_verified,
        "summary": summary,
    }
    _write_new_json(output, result)
    return result


def _history_summary(attempts: list[dict]) -> dict:
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


def _raw_result_record(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        _fail("Claude raw result is missing or symlinked")
    try:
        relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        _fail("Claude raw result is outside the repository")
    return {"path": relative, "sha256": file_sha256(path)}


def _attempt_from_result(attempt_id: str, result: dict, path: Path) -> dict:
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
        "raw_result": _raw_result_record(path),
    }


def _attempt_from_error(attempt_id: str, exc: BaseException) -> dict:
    message = str(exc) or type(exc).__name__
    cleanup = getattr(exc, "cleanup_verified", True) is True
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
        "failures": [message],
        "usage": None,
        "scenario_summary": None,
        "raw_result": None,
    }


def _append_attempt(attempt: dict) -> None:
    history = _read_json(HISTORY_PATH, "Claude attempt history")
    attempts = history.get("attempts")
    if history.get("schema_version") != HISTORY_SCHEMA_VERSION or not isinstance(attempts, list):
        _fail("Claude attempt history is malformed")
    if any(isinstance(item, dict) and item.get("id") == attempt.get("id") for item in attempts):
        _fail(f"Claude attempt id already exists: {attempt.get('id')}")
    attempts.append(attempt)
    history["summary"] = _history_summary(attempts)
    _replace_json(HISTORY_PATH, history)


def _promote_current_result(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        _fail("Claude raw result is missing or symlinked")
    if DEFAULT_RESULTS.is_symlink():
        _fail("Claude current result is symlinked")
    temporary = DEFAULT_RESULTS.with_name(
        f".{DEFAULT_RESULTS.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        temporary.write_bytes(path.read_bytes())
        if file_sha256(temporary) != file_sha256(path):
            _fail("Claude current-result mirror differs from the raw result")
        os.replace(temporary, DEFAULT_RESULTS)
    finally:
        if temporary.exists():
            temporary.unlink()



def _input_shape_errors(value: object) -> list[str]:
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
        history = _read_json(path, "Claude attempt history")
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
                raw_result = _read_json(raw_path, "Claude raw result")
                expected_attempt = _attempt_from_result(
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
    if history.get("summary") != _history_summary(
        [item for item in attempts if isinstance(item, dict)]
    ):
        errors.append("Claude attempt history summary is stale")
    return errors


def _result_scenario_errors(item: object, scenario: dict, limits: dict) -> list[str]:
    expected_id = scenario["id"]
    if not isinstance(item, dict) or item.get("id") != expected_id:
        return [f"{expected_id}: result is missing or out of order"]
    errors: list[str] = []
    failures = item.get("failures")
    if not isinstance(failures, list) or item.get("passed") is not (not failures):
        errors.append(f"{expected_id}: passed flag contradicts failures")
    if (
        item.get("prompt") != scenario["prompt"]
        or item.get("prompt_sha256") != _sha256_text(scenario["prompt"])
    ):
        errors.append(f"{expected_id}: prompt or prompt digest is stale")

    response = item.get("response")
    errors.extend(
        f"{expected_id}: {error}" for error in _response_shape_errors(response)
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
    event_response, event_usage = _structured_output(events)
    if event_response != item.get("response"):
        errors.append(f"{expected_id}: response contradicts the retained event trace")
    if event_usage != item.get("usage"):
        errors.append(f"{expected_id}: usage contradicts the retained event trace")

    serialized = json.dumps(
        {"response": item.get("response"), "events": events},
        ensure_ascii=False,
    )
    recomputed_observations = {
        "hook_event_seen": _hook_event_seen(events),
        "tool_calls": _tool_calls(events),
        "api_retries": _api_retries(events),
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
            and observed.get("direct_brief_sha256") != _sha256_text("")
        ):
            errors.append(f"{expected_id}: no-glossary direct brief was not empty")
    if item.get("returncode") != 0:
        errors.append(f"{expected_id}: Claude return code was not zero")
    stderr = item.get("stderr")
    if (
        not isinstance(stderr, str)
        or len(stderr) > limits["stored_string_characters"] + 1
        or item.get("stderr_sanitized_sha256") != _sha256_text(stderr)
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
        result = _read_json(path, "Claude evaluation result")
        manifest = _manifest()
    except ClaudeEvaluationError as exc:
        return [str(exc)]
    if result.get("schema_version") != RESULT_SCHEMA_VERSION:
        errors.append("Claude result schema is stale")
    if current:
        try:
            if result.get("inputs") != _input_identity(installed_plugin):
                errors.append("Claude result inputs do not match the current evaluator/plugin")
        except (ClaudeEvaluationError, OSError) as exc:
            errors.append(f"current Claude inputs are unreadable: {exc}")
    else:
        errors.extend(_input_shape_errors(result.get("inputs")))
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
            _result_scenario_errors(item, scenario, manifest["trace_limits"])
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
        history = _read_json(HISTORY_PATH, "Claude attempt history")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--run", action="store_true")
    action.add_argument("--verify-history", action="store_true")
    action.add_argument("--verify-results", type=Path)
    parser.add_argument("--current", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--confirm-live-batch")
    parser.add_argument("--claude", type=Path)
    parser.add_argument("--installed-plugin", type=Path, default=DEFAULT_INSTALLED_PLUGIN)
    parser.add_argument("--scratch-parent", type=Path, default=Path("/tmp"))
    args = parser.parse_args(argv)
    try:
        if args.output is not None and not args.run:
            _fail("--output can be used only with --run")
        if args.current and args.verify_results is None:
            _fail("--current can be used only with --verify-results")
        if args.run:
            if args.confirm_live_batch != LIVE_CONFIRMATION:
                _fail(
                    "live Claude evaluation requires --confirm-live-batch "
                    f"{LIVE_CONFIRMATION} after fresh user authorization"
                )
            claude = args.claude or (
                Path(found) if (found := shutil.which("claude")) else None
            )
            if claude is None:
                _fail("claude is not on PATH; refusing to open a login flow")
            attempt_id = _new_attempt_id()
            output = _validated_output(
                args.output or RUNS_PATH / f"{attempt_id}.json"
            )
            try:
                result = run_evaluation(
                    output,
                    claude=claude,
                    installed_plugin=args.installed_plugin,
                    scratch_parent=args.scratch_parent,
                )
            except BaseException as exc:
                try:
                    _append_attempt(_attempt_from_error(attempt_id, exc))
                except Exception as append_exc:
                    print(
                        "Claude evaluation: failed to retain aborted attempt: "
                        f"{append_exc}",
                        file=sys.stderr,
                    )
                raise
            _append_attempt(_attempt_from_result(attempt_id, result, output))
            _promote_current_result(output)
            summary = result["summary"]
            print(
                f"Claude evaluation: {summary['passed']}/{summary['required']} "
                "scenarios passed"
            )
            return 0 if summary["all_passed"] else 1
        if args.verify_history:
            errors = verify_history()
        else:
            errors = verify_results(
                args.verify_results,
                current=args.current,
                installed_plugin=args.installed_plugin,
            )
        if errors:
            for error in errors:
                print(f"Claude evaluation verification: {error}", file=sys.stderr)
            return 1
        if args.verify_history:
            attempts = _read_json(HISTORY_PATH, "Claude attempt history")["attempts"]
            message = (
                "Claude attempt history is genuine and empty"
                if not attempts
                else "Claude attempt history is genuine; "
                f"{len(attempts)} attempt{'s' if len(attempts) != 1 else ''} retained"
            )
        else:
            message = "Claude evaluation evidence is genuine and internally consistent"
        print(message)
        return 0
    except (ClaudeEvaluationError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"Claude evaluation: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
