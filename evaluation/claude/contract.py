"""The Claude Code evaluation lane's contract: repository paths, the pinned
host/budget/limit expectations, canaries, the lane's error types, and its
exact JSON encoding (``ensure_ascii=False``, unlike the Codex lane).

Every Claude module imports from here; nothing here imports a lane module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from pathlib import Path
from typing import NoReturn

from evaluation.harness.io import dotenv_part, framed_digest, read_json_object

ROOT = Path(__file__).resolve().parents[2]
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
RUN_NAME = re.compile(
    r"\d{8}T\d{6}Z-claude-[a-z0-9-]+-[0-9a-f]{8}\.json"
)
HOOK_COMMAND = re.compile(r'^"([^"\n]+)" brief \.$')
PROVIDER_ENV_KEYS = frozenset(
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
USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


class ClaudeEvaluationError(RuntimeError):
    """The bounded host run or its retained evidence broke its contract."""


def fail(message: str) -> NoReturn:
    raise ClaudeEvaluationError(message)


def read_json(path: Path, label: str) -> dict:
    return read_json_object(
        path,
        label,
        max_bytes=MAX_JSON_BYTES,
        fail=fail,
        reject_symlink=True,
        overflow_suffix="",
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value))


def replace_json(path: Path, value: object) -> None:
    if path.is_symlink():
        fail(f"refusing to replace symlinked JSON: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(json_bytes(value))
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_new_json(path: Path, value: object) -> None:
    if path.exists() or path.is_symlink():
        fail(f"refusing to overwrite evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(json_bytes(value))
        try:
            os.link(temporary, path)
        except FileExistsError:
            fail(f"refusing to overwrite evidence: {path}")
    finally:
        if temporary.exists():
            temporary.unlink()


def tree_sha256(root: Path) -> str:
    try:
        root_info = root.lstat()
    except OSError:
        fail(f"tree is missing or unreadable: {root}")
    if not stat.S_ISDIR(root_info.st_mode):
        fail(f"tree is missing or symlinked: {root}")
    files: list[Path] = []
    for current, directories, names in os.walk(root, followlinks=False):
        kept = []
        for name in sorted(directories):
            path = Path(current) / name
            if dotenv_part(name) or name == "__pycache__":
                continue
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode):
                fail(f"tree contains a symlinked directory: {path}")
            kept.append(name)
        directories[:] = kept
        for name in sorted(names):
            if dotenv_part(name) or name.endswith(".pyc"):
                continue
            path = Path(current) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                fail(f"tree contains a symlinked file: {path}")
            if not stat.S_ISREG(info.st_mode):
                fail(f"tree contains a non-regular file: {path}")
            files.append(path)
    ordered = sorted(files, key=lambda item: item.relative_to(root).as_posix())
    return framed_digest(
        (path.relative_to(root).as_posix(), path.read_bytes()) for path in ordered
    )


def load_manifest() -> dict:
    value = read_json(SCENARIOS_PATH, "Claude scenario manifest")
    if value.get("schema_version") != 1:
        fail("Claude scenario manifest schema is stale")
    host = value.get("host")
    budget = value.get("budget")
    limits = value.get("trace_limits")
    scenarios = value.get("scenarios")
    if host != {
        "name": "Claude Code",
        "version": EXPECTED_CLAUDE_VERSION,
        "platform": "Linux",
    }:
        fail("Claude scenario host contract is stale")
    if not isinstance(budget, dict) or budget != {
        "calls": 3,
        "retries": 0,
        "estimated_total_input_tokens": 200000,
        "estimated_total_output_tokens": 6000,
        "max_usd_per_call": 0.25,
    }:
        fail("Claude scenario budget contract is stale")
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
        fail("Claude scenario trace limits are malformed or unbounded")
    if not isinstance(scenarios, list) or [
        item.get("id") for item in scenarios if isinstance(item, dict)
    ] != list(SCENARIO_IDS):
        fail("Claude scenario ids/order are stale")
    for scenario in scenarios:
        if not isinstance(scenario, dict) or set(scenario) != {
            "id",
            "fixture",
            "expected_status",
            "disable_skills",
            "prompt",
        }:
            fail("Claude scenario shape is malformed")
        if not isinstance(scenario["prompt"], str) or not scenario["prompt"]:
            fail(f"{scenario['id']}: prompt is missing")
    if value.get("model") != "sonnet":
        fail("Claude scenario model is stale")
    return value


def load_response_schema() -> dict:
    schema = read_json(RESPONSE_SCHEMA_PATH, "Claude response schema")
    required = schema.get("required")
    properties = schema.get("properties")
    if (
        schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or required != ["status", "term", "definition", "protocol"]
        or not isinstance(properties, dict)
        or set(properties) != set(required)
    ):
        fail("Claude response schema contract is stale")
    return schema


class ScratchCleanupFailed(ClaudeEvaluationError):
    """The evaluator's own scratch directory could not be verifiably removed.

    A distinct type, so the aborted-attempt record can state that temporary
    state may remain without any attribute being attached to the exception.
    """
