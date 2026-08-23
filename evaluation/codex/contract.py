"""The Codex evaluation lane's contract: repository paths, schema versions,
scenario generations, canaries, hook wording, and the lane's error type.

Every Codex module imports from here; nothing here imports a lane module.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NoReturn

from evaluation.harness.io import read_json_object
from glossabet.runtime.artifacts import MAX_JSON_BYTES

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_PATH = ROOT / "evaluation" / "agent-scenarios.json"
PROMPT_PATH = ROOT / "evaluation" / "agent-prompt.md"
RESPONSE_SCHEMA_PATH = ROOT / "evaluation" / "agent-response-schema.json"
DEFAULT_RESULTS = ROOT / "evaluation" / "agent-results.json"
HISTORY_PATH = ROOT / "evaluation" / "agent-history.json"
RUNS_PATH = ROOT / "evaluation" / "agent-runs"
PLUGIN = ROOT / "plugins" / "glossabet"
PLUGIN_HOOK = PLUGIN / "hooks" / "hooks.json"
CANONICAL_SKILL = ROOT / "skill" / "SKILL.md"
RESULT_SCHEMA_VERSION = 5
# The scenario sets the evaluator's per-scenario assertions understand.
# Genuineness verification never reads the current scenario manifest (the
# evidence may honestly lag it); it accepts a recorded run whose scenario
# ids match one of these known generations exactly — never a subset, so no
# recorded scenario can be dropped without detection. Currency (the release
# gate) demands the current manifest's set.
PHASE_22_SCENARIO_IDS = (
    "fresh",
    "stale",
    "absent",
    "malformed",
    "oversized",
    "symlinked",
    "partial",
    "monorepo",
    "resumed-glossary",
    "sensitive-file",
    "session-hook",
    "missing-cli",
)
PHASE_31_SCENARIO_IDS = (
    "fresh",
    "stale",
    "absent",
    "malformed",
    "oversized",
    "symlinked",
    "partial",
    "monorepo",
    "resumed-glossary",
    "markdown-glossary",
    "both-glossaries",
    "sensitive-file",
    "session-hook",
    "missing-cli",
)
SCENARIO_ID_GENERATIONS = (PHASE_22_SCENARIO_IDS, PHASE_31_SCENARIO_IDS)
REQUIRED_SCENARIO_IDS = PHASE_31_SCENARIO_IDS
STATUS_VOCABULARY = frozenset(
    {
        "grounded",
        "grounded-with-warning",
        "grounded-partial",
        "choice-required",
        "resumed",
        "adoption",
        "stopped",
    }
)
# Generous absolute ceilings behind any recorded trace limits: genuine
# verification accepts lagging limit values, never unbounded ones.
TRACE_LIMIT_CEILINGS = {
    "commands_per_scenario": 100,
    "events": 10_000,
    "jsonl_bytes": 100_000_000,
    "stored_command_characters": 100_000,
    "stored_output_characters": 100_000,
}
TRACE_LIMIT_KEYS = frozenset(TRACE_LIMIT_CEILINGS)
HISTORY_SCHEMA_VERSION = 1
SENSITIVE_CANARY = "GLOSSABET_SENSITIVE_CANARY_MUST_NOT_APPEAR"
HOOK_SOURCE_CANARY = "AMBIENT_SOURCE_TEXT_MUST_NOT_REACH_SESSION_CONTEXT"
HOOK_TERM = "Payment Service"
HOOK_DEFINITION = "The boundary that owns payment attempts."
HOOK_PROPOSED_TERM = "Gateway Route"
# A repository's own hand-maintained GLOSSARY.md. Its words must reach the
# agent context only as metadata (presence, size, digest) — never as content
# or vocabulary evidence — so this canary must not appear in any context.
MARKDOWN_GLOSSARY_CANARY = "REPOSITORY_GLOSSARY_TEXT_MUST_NOT_ENTER_CONTEXT"
MARKDOWN_GLOSSARY_TEXT = (
    "# Glossary\n\n"
    "**Payment Service** — the boundary that owns payment attempts.\n\n"
    f"{MARKDOWN_GLOSSARY_CANARY}\n"
)
SESSION_START_COMMAND = (
    'python3 -I -B "$PLUGIN_ROOT/skills/glossabet/scripts/run_glossabet.py" brief .'
)
SESSION_START_COMMAND_WINDOWS = (
    'py -3 -I -B "%PLUGIN_ROOT%\\skills\\glossabet\\scripts\\run_glossabet.py" brief .'
)
HOOK_PROMPT = """This is a bounded fresh-session context evaluation.
Do not run commands, call tools, inspect files, or use outside knowledge. From
developer context already supplied before this request, copy the repository's
one settled term and its definition verbatim into `facts`. Return exactly one
scenario with id `session-hook`. Use status `grounded` when that context exists
and `stopped` when it does not. `next_action` must say only how to use the
settled term; do not perform any action.
"""


class AgentEvaluationError(RuntimeError):
    """The host run or its captured evidence violated the scenario contract."""


def fail(message: str) -> NoReturn:
    raise AgentEvaluationError(message)


def expected_hook_config() -> dict:
    return {
        "description": "Load the repository's settled vocabulary into each Codex session.",
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "^(startup|resume|clear|compact)$",
                    "hooks": [
                        {
                            "type": "command",
                            "command": SESSION_START_COMMAND,
                            "commandWindows": SESSION_START_COMMAND_WINDOWS,
                            "timeout": 30,
                            "statusMessage": "Loading settled repository vocabulary",
                            "additionalContextLimit": 0,
                        }
                    ],
                }
            ]
        },
    }


def read_json(path: Path, label: str) -> dict:
    return read_json_object(path, label, max_bytes=MAX_JSON_BYTES, fail=fail)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def mapping(value: object) -> dict:
    """Agent-relayed output controls these shapes; never crash on them."""
    return value if isinstance(value, dict) else {}


INPUT_IDENTITY_KEYS = frozenset({
    "canonical_skill_sha256",
    "engine_version",
    "evaluator_sha256",
    "plugin_sha256",
    "prompt_sha256",
    "response_schema_sha256",
    "scenario_manifest_sha256",
})


ARTIFACT_IDENTITY_KEYS = frozenset({
    "canonical_skill_sha256",
    "engine_version",
    "hook_sha256",
    "plugin_sha256",
    "pyproject_sha256",
    "readme_sha256",
    "runner_sha256",
    "source_package_sha256",
    "wheel_sha256",
})


USAGE_KEYS = (
    "cache_write_input_tokens",
    "cached_input_tokens",
    "input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
