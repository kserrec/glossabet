#!/usr/bin/env python3
"""Run and verify bounded installed-skill scenarios through real Codex exec."""

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
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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
_TRACE_LIMIT_CEILINGS = {
    "commands_per_scenario": 100,
    "events": 10_000,
    "jsonl_bytes": 100_000_000,
    "stored_command_characters": 100_000,
    "stored_output_characters": 100_000,
}
_TRACE_LIMIT_KEYS = frozenset(_TRACE_LIMIT_CEILINGS)
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
    'python3 -B "$PLUGIN_ROOT/skills/glossabet/scripts/run_glossabet.py" brief .'
)
SESSION_START_COMMAND_WINDOWS = (
    'py -3 -B "%PLUGIN_ROOT%\\skills\\glossabet\\scripts\\run_glossabet.py" brief .'
)
HOOK_PROMPT = """This is a bounded fresh-session context evaluation.
Do not run commands, call tools, inspect files, or use outside knowledge. From
developer context already supplied before this request, copy the repository's
one settled term and its definition verbatim into `facts`. Return exactly one
scenario with id `session-hook`. Use status `grounded` when that context exists
and `stopped` when it does not. `next_action` must say only how to use the
settled term; do not perform any action.
"""

sys.path.insert(0, str(ROOT))

from glossabet import __version__  # noqa: E402
from glossabet.agent_context import AGENT_CONTEXT_SCHEMA_VERSION  # noqa: E402
from glossabet.artifacts import MAX_JSON_BYTES  # noqa: E402
from glossabet.installer import default_skill_directory  # noqa: E402
from glossabet.scanner import is_sensitive  # noqa: E402


class AgentEvaluationError(RuntimeError):
    """The host run or its captured evidence violated the scenario contract."""


def _fail(message: str) -> None:
    raise AgentEvaluationError(message)


def _expected_hook_config() -> dict:
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


def _dotenv_part(name: str) -> bool:
    return (
        name == ".env"
        or name.endswith(".env")
        or name.startswith(".env.")
        or ".env." in name
    )


def _read_json(path: Path, label: str) -> dict:
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            _fail(f"{label} exceeds {MAX_JSON_BYTES} bytes — refusing to load")
        value = json.loads(path.read_bytes())
    except (OSError, ValueError, RecursionError) as exc:
        _fail(f"{label} is unreadable: {exc}")
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _walk_paths(
    root: Path, *, excluded_directory: str, skip_dotenv: bool = True
) -> list[Path]:
    """Deterministic file walk skipping one directory name.

    Dotenv names are skipped by default so identity digests never touch
    them; the write-diff snapshot opts back in, tracking sensitive files
    by stat only.
    """
    files: list[Path] = []
    for current, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(
            name
            for name in directories
            if name != excluded_directory and not _dotenv_part(name)
        )
        for name in sorted(names):
            if not skip_dotenv or not _dotenv_part(name):
                files.append(Path(current) / name)
    return files


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    files = _walk_paths(root, excluded_directory="__pycache__")
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode()
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


_INPUT_IDENTITY_KEYS = frozenset({
    "canonical_skill_sha256",
    "engine_version",
    "evaluator_sha256",
    "plugin_sha256",
    "prompt_sha256",
    "response_schema_sha256",
    "scenario_manifest_sha256",
})
_ARTIFACT_IDENTITY_KEYS = frozenset({
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
_USAGE_KEYS = (
    "cache_write_input_tokens",
    "cached_input_tokens",
    "input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)


def _input_identity() -> dict:
    return {
        "evaluator_sha256": _sha256(Path(__file__).resolve()),
        "scenario_manifest_sha256": _sha256(SCENARIOS_PATH),
        "prompt_sha256": _sha256(PROMPT_PATH),
        "response_schema_sha256": _sha256(RESPONSE_SCHEMA_PATH),
        "canonical_skill_sha256": _sha256(CANONICAL_SKILL),
        "plugin_sha256": _tree_sha256(PLUGIN),
        "engine_version": __version__,
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _replace_via_temporary(target: Path, write_payload) -> None:
    """Populate a unique same-directory temporary, then replace ``target``."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        write_payload(temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_history(value: dict) -> None:
    _replace_via_temporary(
        HISTORY_PATH, lambda temporary: _write_json(temporary, value)
    )


def _promote_current_result(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        _fail("completed agent result is missing or symlinked")
    if DEFAULT_RESULTS.is_symlink():
        _fail("current agent result is symlinked")

    def write_mirror(temporary: Path) -> None:
        temporary.write_bytes(path.read_bytes())
        if _sha256(temporary) != _sha256(path):
            _fail("current agent result mirror differs from retained raw result")

    _replace_via_temporary(DEFAULT_RESULTS, write_mirror)


def _plugin_wheel() -> Path:
    wheels = sorted(
        (PLUGIN / "skills" / "glossabet" / "assets").glob("glossabet-*.whl")
    )
    if len(wheels) != 1:
        _fail(f"expected one checked-in plugin wheel, found {len(wheels)}")
    return wheels[0]


def _artifact_snapshot() -> dict:
    runner = (
        PLUGIN / "skills" / "glossabet" / "scripts" / "run_glossabet.py"
    )
    wheel = _plugin_wheel()
    return {
        "canonical_skill_sha256": _sha256(CANONICAL_SKILL),
        "engine_version": __version__,
        "hook_sha256": _sha256(PLUGIN_HOOK),
        "plugin_sha256": _tree_sha256(PLUGIN),
        "pyproject_sha256": _sha256(ROOT / "pyproject.toml"),
        "readme_sha256": _sha256(ROOT / "README.md"),
        "runner_sha256": _sha256(runner),
        "source_package_sha256": _tree_sha256(ROOT / "glossabet"),
        "wheel_sha256": _sha256(wheel),
    }


def _source_python_files() -> dict[str, bytes]:
    package = ROOT / "glossabet"
    return {
        path.relative_to(ROOT).as_posix(): path.read_bytes()
        for path in _walk_paths(package, excluded_directory="__pycache__")
        if path.name.endswith(".py")
    }


def _artifact_errors(recorded: object) -> list[str]:
    """Verify current delivery deterministically, without an agent or network."""
    errors: list[str] = []
    plugin_skill = PLUGIN / "skills" / "glossabet" / "SKILL.md"
    runner = (
        PLUGIN / "skills" / "glossabet" / "scripts" / "run_glossabet.py"
    )
    guessed_root_runner = PLUGIN / "scripts" / "run_glossabet.py"
    try:
        wheel = _plugin_wheel()
        snapshot = _artifact_snapshot()
    except (AgentEvaluationError, OSError) as exc:
        return [f"current plugin artifact is unreadable: {exc}"]

    if recorded != snapshot:
        errors.append("current deterministic plugin artifact identity is stale")
    try:
        if (
            plugin_skill.is_symlink()
            or plugin_skill.read_bytes() != CANONICAL_SKILL.read_bytes()
        ):
            errors.append("checked-in plugin skill differs from the canonical skill")
        if runner.is_symlink() or not runner.is_file():
            errors.append("checked-in skill-local runner is missing or symlinked")
        if guessed_root_runner.exists() or guessed_root_runner.is_symlink():
            errors.append("an ambiguous plugin-root runner exists")
        manifest = _read_json(
            PLUGIN / ".codex-plugin" / "plugin.json",
            "checked-in plugin manifest",
        )
        if (
            manifest.get("name") != "glossabet"
            or manifest.get("version") != __version__
        ):
            errors.append("checked-in plugin manifest name/version is stale")
        if manifest.get("hooks") != "./hooks/hooks.json":
            errors.append("checked-in plugin manifest does not expose its hook")
        if PLUGIN_HOOK.is_symlink() or not PLUGIN_HOOK.is_file():
            errors.append("checked-in plugin hook is missing or symlinked")
        elif _read_json(PLUGIN_HOOK, "checked-in plugin hook") != (
            _expected_hook_config()
        ):
            errors.append("checked-in plugin hook contract is stale")
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
            source_files = _source_python_files()
            wheel_python = {
                name
                for name in names
                if name.startswith("glossabet/") and name.endswith(".py")
            }
            if wheel_python != set(source_files) or any(
                archive.read(name) != content
                for name, content in source_files.items()
                if name in names
            ):
                errors.append("checked-in plugin wheel differs from package source")
            if "glossabet/brief.py" not in names:
                errors.append("checked-in plugin wheel lacks the brief implementation")
            if (
                "glossabet/_skill/SKILL.md" not in names
                or archive.read("glossabet/_skill/SKILL.md")
                != CANONICAL_SKILL.read_bytes()
            ):
                errors.append("checked-in plugin wheel embeds a different skill")
            metadata_names = [
                name for name in names if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_names) != 1:
                errors.append("checked-in plugin wheel has ambiguous metadata")
            else:
                _headers, separator, description = archive.read(
                    metadata_names[0]
                ).partition(b"\n\n")
                if not separator or description != (ROOT / "README.md").read_bytes():
                    errors.append(
                        "checked-in plugin wheel embeds stale README metadata"
                    )
    except (AgentEvaluationError, OSError, KeyError, zipfile.BadZipFile) as exc:
        errors.append(f"current plugin structure check failed: {exc}")

    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        version = subprocess.run(
            [sys.executable, str(runner), "--version"],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
        )
        if (
            version.returncode != 0
            or version.stdout != f"glossabet {__version__}\n"
            or version.stderr != ""
        ):
            errors.append(
                "checked-in skill-local runner failed its exact version check"
            )
        brief = subprocess.run(
            [
                sys.executable,
                str(runner),
                "brief",
                str(ROOT / "examples" / "payment-service"),
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
        )
        if (
            brief.returncode != 0
            or brief.stderr != ""
            or not brief.stdout.startswith("Glossabet vocabulary brief v1 (emitted by ")
            or "coverage: complete=true" not in brief.stdout
            or len(brief.stdout.encode("utf-8")) > 4_096
        ):
            errors.append(
                "checked-in plugin wheel failed the bounded brief smoke check"
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        errors.append(f"current plugin execution check failed: {exc}")
    return errors


def _history_summary(attempts: list[dict]) -> dict:
    def check_summary(name: str) -> dict:
        values = [
            attempt.get("checks", {}).get(name)
            for attempt in attempts
            if attempt.get("checks", {}).get(name) in {"passed", "failed"}
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


def _new_attempt_id(kind: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{kind}-{uuid.uuid4().hex[:8]}"


def _usage_totals(value: object) -> dict | None:
    candidates = value if isinstance(value, list) else [value]
    records = [record for record in candidates if isinstance(record, dict)]
    keys = _USAGE_KEYS
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


def _append_attempt(attempt: dict) -> None:
    if HISTORY_PATH.is_symlink():
        _fail("agent attempt history is symlinked")
    if HISTORY_PATH.exists():
        history = _read_json(HISTORY_PATH, "agent attempt history")
    else:
        history = {
            "schema_version": HISTORY_SCHEMA_VERSION,
            "current_artifact": {},
            "attempts": [],
            "summary": _history_summary([]),
        }
    attempts = history.get("attempts")
    if history.get("schema_version") != HISTORY_SCHEMA_VERSION or not isinstance(
        attempts, list
    ):
        _fail("agent attempt history is malformed")
    if any(
        item.get("id") == attempt.get("id")
        for item in attempts
        if isinstance(item, dict)
    ):
        _fail(f"agent attempt id already exists: {attempt.get('id')}")
    attempts.append(attempt)
    history["summary"] = _history_summary(attempts)
    _write_history(history)


def _refresh_artifact_record() -> dict:
    if HISTORY_PATH.is_symlink():
        _fail("agent attempt history is symlinked")
    history = _read_json(HISTORY_PATH, "agent attempt history")
    attempts = history.get("attempts")
    if history.get("schema_version") != HISTORY_SCHEMA_VERSION or not isinstance(
        attempts, list
    ):
        _fail("agent attempt history is malformed")
    history["current_artifact"] = _artifact_snapshot()
    history["summary"] = _history_summary(attempts)
    _write_history(history)
    return history["current_artifact"]


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    parse_json: bool = False,
    timeout: int = 120,
) -> str | dict:
    shown = " ".join(command[:4])
    print(f"$ {shown}{' ...' if len(command) > 4 else ''}", flush=True)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr, flush=True)
    if result.returncode:
        detail = result.stdout[-2000:] or result.stderr[-2000:]
        _fail(f"command exited {result.returncode}: {shown}: {detail}")
    if not parse_json:
        return result.stdout
    try:
        value = json.loads(result.stdout)
    except (ValueError, RecursionError) as exc:
        _fail(f"command returned malformed JSON: {shown}: {exc}")
    if not isinstance(value, dict):
        _fail(f"command JSON was not an object: {shown}")
    return value


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c", "core.fsmonitor=",
            "-c", "core.hooksPath=/dev/null",
            *args,
        ],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=30,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        },
    )
    if result.returncode:
        _fail(result.stderr.strip() or result.stdout.strip() or "git failed")
    return result.stdout.strip()


def _ordinary_repo(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "service.py").write_text(
        "class PaymentService:\n    pass\n\npayment_record = PaymentService()\n",
        encoding="utf-8",
    )


def _git_graph_repo(root: Path, *, stale: bool) -> None:
    _ordinary_repo(root)
    (root / ".gitignore").write_text(
        "graphify-out/\nglossabet-out/\n", encoding="utf-8"
    )
    _git(root, "init", "-q")
    _git(root, "add", ".gitignore", "service.py")
    _git(
        root,
        "-c", "user.name=Glossabet Evaluation",
        "-c", "user.email=evaluation@example.invalid",
        "commit", "-q", "-m", "fixture",
    )
    head = _git(root, "rev-parse", "HEAD")
    _write_json(
        root / "graphify-out" / "graph.json",
        {
            "built_at_commit": "0" * 40 if stale else head,
            "nodes": [
                {
                    "id": "payment",
                    "label": "PaymentService",
                    "community": 0,
                    "source_file": "service.py",
                }
            ],
            "links": [],
        },
    )


def _glossary_path(root: Path) -> Path:
    path = root / "glossabet-out" / "glossary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _make_scenario(root: Path, scenario_id: str) -> None:
    if scenario_id == "fresh":
        _git_graph_repo(root, stale=False)
        return
    if scenario_id == "stale":
        _git_graph_repo(root, stale=True)
        return
    if scenario_id == "session-hook":
        root.mkdir(parents=True)
        (root / "module.py").write_text(
            f'ambient_source_canary = "{HOOK_SOURCE_CANARY}"\n',
            encoding="utf-8",
        )
        _write_json(
            _glossary_path(root),
            {
                "schema_version": 1,
                "concepts": [
                    {
                        "id": "payment-service",
                        "term": HOOK_TERM,
                        "definition": HOOK_DEFINITION,
                        "status": "canonical",
                    },
                    {
                        "id": "gateway-route",
                        "term": HOOK_PROPOSED_TERM,
                        "definition": "A term that has not been settled.",
                        "status": "proposed",
                    },
                ],
            },
        )
        return
    _ordinary_repo(root)
    if scenario_id == "malformed":
        _glossary_path(root).write_text("{not-json", encoding="utf-8")
    elif scenario_id == "oversized":
        with _glossary_path(root).open("wb") as handle:
            handle.truncate(MAX_JSON_BYTES + 1)
    elif scenario_id == "symlinked":
        target = root / "outside-glossary.json"
        _write_json(target, {"schema_version": 1, "concepts": []})
        _glossary_path(root).symlink_to(target)
    elif scenario_id == "partial":
        (root / "service.py").write_text(
            "".join(
                f"distinctIdentifier{index} = {index}\n"
                for index in range(360)
            ),
            encoding="utf-8",
        )
    elif scenario_id == "monorepo":
        _write_json(
            root / "package.json",
            {"private": True, "workspaces": ["packages/*"]},
        )
        for name in ("alpha", "beta", "gamma"):
            package = root / "packages" / name
            package.mkdir(parents=True)
            _write_json(package / "package.json", {"name": name})
            (package / "index.js").write_text(
                f"export const {name}Service = true;\n", encoding="utf-8"
            )
    elif scenario_id == "resumed-glossary":
        _write_json(
            _glossary_path(root),
            {
                "schema_version": 1,
                "concepts": [
                    {
                        "id": "payment-service",
                        "term": "Payment Service",
                        "definition": "The boundary that owns payment attempts.",
                        "status": "canonical",
                    },
                    {
                        "id": "gateway-route",
                        "term": "Gateway Route",
                        "definition": "The still-open provider routing concept.",
                        "status": "proposed",
                    },
                ],
            },
        )
    elif scenario_id == "markdown-glossary":
        # Bytes, not text: the checker compares the engine's SHA-256 with the
        # digest of these exact bytes, and text mode would write CRLF on
        # Windows.
        (root / "GLOSSARY.md").write_bytes(MARKDOWN_GLOSSARY_TEXT.encode("utf-8"))
    elif scenario_id == "both-glossaries":
        (root / "GLOSSARY.md").write_bytes(MARKDOWN_GLOSSARY_TEXT.encode("utf-8"))
        _write_json(
            _glossary_path(root),
            {
                "schema_version": 1,
                "concepts": [
                    {
                        "id": "payment-service",
                        "term": "Payment Service",
                        "definition": "The boundary that owns payment attempts.",
                        "status": "canonical",
                    }
                ],
            },
        )
    elif scenario_id == "sensitive-file":
        dotenv = root / ".env"
        dotenv.touch()
        dotenv.chmod(0)
        sensitive = root / "api-secret.txt"
        sensitive.write_text(SENSITIVE_CANARY, encoding="utf-8")
        sensitive.chmod(0)
    elif scenario_id not in {"absent", "missing-cli"}:
        _fail(f"unknown scenario fixture: {scenario_id}")


def _snapshot(root: Path) -> dict[str, tuple]:
    snapshot: dict[str, tuple] = {}
    for path in _walk_paths(
        root, excluded_directory=".git", skip_dotenv=False
    ):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if path.is_symlink():
            snapshot[relative] = ("symlink", os.readlink(path))
        elif is_sensitive(path.name):
            snapshot[relative] = (
                "sensitive-stat",
                info.st_size,
                stat.S_IMODE(info.st_mode),
                info.st_mtime_ns,
            )
        else:
            snapshot[relative] = (
                "file",
                info.st_size,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
    return snapshot


def _unexpected_writes(
    before: dict[str, tuple], after: dict[str, tuple]
) -> list[str]:
    changed = _changed_paths(before, after)
    return [
        path for path in changed if path != "glossabet-out/evidence.json"
    ]


def _changed_paths(
    before: dict[str, tuple], after: dict[str, tuple]
) -> list[str]:
    return sorted(
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )


def _codex_version(codex: str) -> str:
    result = subprocess.run(
        [codex, "--version"],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if result.returncode:
        _fail(result.stderr.strip() or "could not run codex --version")
    match = re.search(r"codex-cli\s+([^\s]+)", result.stdout)
    if match is None:
        _fail(f"unrecognized Codex version output: {result.stdout!r}")
    return match.group(1)


def _competing_standalone_skill_paths(
    *, home: Path | None = None
) -> tuple[Path, ...]:
    """Return Glossabet's default standalone skill when it can shadow a plugin."""
    skill = default_skill_directory("codex", home=home) / "SKILL.md"
    return (skill.absolute(),) if skill.is_file() else ()


def _disabled_skills_config(paths: tuple[Path, ...]) -> str | None:
    """Build a per-run Codex override without changing user-owned config."""
    normalized = sorted({str(path.absolute()) for path in paths})
    if not normalized:
        return None
    entries = ",".join(
        f"{{path={json.dumps(path)},enabled=false}}" for path in normalized
    )
    return f"skills.config=[{entries}]"


def _parse_events(raw: str, limits: dict) -> list[dict]:
    encoded = raw.encode("utf-8")
    if len(encoded) > limits["jsonl_bytes"]:
        _fail(
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
            _fail(f"Codex emitted non-JSON stdout: {line[:200]!r}: {exc}")
        if not isinstance(event, dict):
            _fail("Codex JSONL event was not an object")
        events.append(event)
    if len(events) > limits["events"]:
        _fail(
            f"Codex trace exceeded {limits['events']} events "
            f"({len(events)} observed)"
        )
    return events


def _command_items(events: list[dict]) -> list[dict]:
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
            _fail("Codex command trace is malformed")
        commands.append({
            "command": command,
            "cwd": item.get("cwd") if isinstance(item.get("cwd"), str) else None,
            "output": output,
            "exit_code": item.get("exit_code"),
            "status": item.get("status"),
        })
    return commands


def _normalize_text(
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


def _trace_summary(
    command: dict,
    workspace: Path,
    limits: dict,
    aliases: tuple[tuple[str, str], ...] = (),
) -> dict:
    output = command["output"]
    return {
        "command": _normalize_text(
            command["command"],
            workspace,
            limits["stored_command_characters"],
            aliases,
        ),
        "cwd": (
            _normalize_text(
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
        "output_preview": _normalize_text(
            output,
            workspace,
            limits["stored_output_characters"],
            aliases,
        ),
    }


def _installed_version_command(
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
        _normalize_text(
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
        _fail(
            "installed plugin engine version-check count was "
            f"{len(matching)}, expected 1; observed --version commands: {observed}"
        )
    command = matching[0]
    expected = f"glossabet {__version__}"
    if command["output"].strip() != expected:
        output = command["output"]
        _fail(
            "installed plugin engine version output did not match "
            f"{expected!r}; output characters={len(output)}, "
            f"sha256={hashlib.sha256(output.encode()).hexdigest()}"
        )
    return command


def _extract_context(output: str) -> dict | None:
    stripped = output.strip()
    if not stripped.startswith("{"):
        return None
    try:
        value = json.loads(stripped)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _codex_exec_command(
    codex: str,
    *,
    workspace: Path,
    prompt: str,
    final_path: Path,
    disabled_skills: tuple[Path, ...] = (),
    use_shell_profile: bool | None = None,
    allow_login_shell: bool | None = None,
    bypass_hook_trust: bool = False,
) -> list[str]:
    command = [
        codex,
        "exec",
        "--json",
        "--ephemeral",
        "--sandbox",
        "workspace-write",
        "--skip-git-repo-check",
        "-c",
        'approval_policy="never"',
    ]
    if bypass_hook_trust:
        command.append("--dangerously-bypass-hook-trust")
    skills_config = _disabled_skills_config(disabled_skills)
    if skills_config is not None:
        command.extend(["-c", skills_config])
    if use_shell_profile is not None:
        command.extend([
            "-c",
            "shell_environment_policy.experimental_use_profile="
            + json.dumps(use_shell_profile),
        ])
    if allow_login_shell is not None:
        command.extend([
            "-c",
            "allow_login_shell=" + json.dumps(allow_login_shell),
        ])
    command.extend([
        "--output-schema",
        str(RESPONSE_SCHEMA_PATH),
        "--output-last-message",
        str(final_path),
        "--cd",
        str(workspace),
        prompt,
    ])
    return command


def _run_codex(
    codex: str,
    *,
    workspace: Path,
    prompt: str,
    environment: dict[str, str],
    limits: dict,
    disabled_skills: tuple[Path, ...] = (),
    use_shell_profile: bool | None = None,
    allow_login_shell: bool | None = None,
    bypass_hook_trust: bool = False,
) -> tuple[dict, list[dict], dict]:
    final_path = workspace / "agent-final.json"
    command = _codex_exec_command(
        codex,
        workspace=workspace,
        prompt=prompt,
        final_path=final_path,
        disabled_skills=disabled_skills,
        use_shell_profile=use_shell_profile,
        allow_login_shell=allow_login_shell,
        bypass_hook_trust=bypass_hook_trust,
    )
    print("$ codex exec --json --ephemeral --sandbox workspace-write ...", flush=True)
    result = subprocess.run(
        command,
        cwd=workspace,
        env=environment,
        text=True,
        capture_output=True,
        timeout=900,
    )
    if result.stderr:
        print(result.stderr[-4000:], end="", file=sys.stderr, flush=True)
    if SENSITIVE_CANARY in result.stdout or SENSITIVE_CANARY in result.stderr:
        _fail("sensitive canary appeared in the Codex trace")
    if result.returncode:
        _fail(
            f"codex exec exited {result.returncode}: "
            f"{result.stderr[-2000:] or result.stdout[-2000:]}"
        )
    events = _parse_events(result.stdout, limits)
    response = _read_json(final_path, "Codex final response")
    if SENSITIVE_CANARY in json.dumps(response):
        _fail("sensitive canary appeared in the Codex final response")
    final_path.unlink()
    usage = next(
        (
            event.get("usage", {})
            for event in reversed(events)
            if event.get("type") == "turn.completed"
        ),
        {},
    )
    return response, _command_items(events), usage


def _response_by_id(response: dict, expected_ids: list[str]) -> dict[str, dict]:
    items = response.get("scenarios")
    if not isinstance(items, list):
        _fail("Codex response has no scenarios list")
    by_id: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            _fail("Codex returned a malformed scenario response")
        if item["id"] in by_id:
            _fail(f"Codex returned duplicate scenario {item['id']}")
        by_id[item["id"]] = item
    if list(by_id) != expected_ids:
        _fail(
            f"Codex scenario order/ids differ from the manifest: "
            f"{list(by_id)} != {expected_ids}"
        )
    return by_id


def _scenario_commands(commands: list[dict], root: Path) -> list[dict]:
    needle = str(root)
    return [
        command
        for command in commands
        if needle in command["command"] or needle == command.get("cwd")
    ]


def _expected_error(scenario_id: str, output: str) -> bool:
    lowered = output.casefold()
    required = {
        "malformed": ("glossary", "unreadable"),
        "oversized": ("glossary", "larger than"),
        "symlinked": ("glossary", "symlink"),
    }[scenario_id]
    return all(part in lowered for part in required)


def _mapping(value: object) -> dict:
    """Agent-relayed output controls these shapes; never crash on them."""
    return value if isinstance(value, dict) else {}


def _check_context(scenario_id: str, context: dict) -> tuple[list[str], dict]:
    failures = []
    coverage = _mapping(context.get("coverage"))
    projection_ledger = _mapping(coverage.get("context"))
    omissions = projection_ledger.get("omissions")
    if not isinstance(omissions, list):
        omissions = []
    observed: dict[str, object] = {
        "context_schema_version": context.get("context_schema_version"),
        "generator": context.get("generator"),
        "freshness": _mapping(context.get("freshness")).get("status"),
        "corpus_complete": _mapping(coverage.get("corpus")).get("complete"),
        "context_complete": projection_ledger.get("complete"),
        "context_projection": projection_ledger.get("projection"),
        "context_omissions": len(omissions),
    }
    if context.get("context_schema_version") != AGENT_CONTEXT_SCHEMA_VERSION:
        failures.append(
            f"context schema was not {AGENT_CONTEXT_SCHEMA_VERSION}"
        )
    if context.get("generator") != {"name": "glossabet", "version": __version__}:
        failures.append("context generator did not match the installed engine")
    if observed["freshness"] != "current":
        failures.append("inspect did not return invocation-current context")
    if observed["corpus_complete"] is not True:
        failures.append("scenario unexpectedly had partial scanner coverage")
    if observed["context_projection"] != "lean":
        failures.append("inspect did not return the routine lean projection")
    if observed["context_complete"] is not False:
        failures.append("lean projection did not disclose its standard omissions")

    omission_pairs = {
        (item.get("path"), item.get("kind"))
        for item in omissions
        if isinstance(item, dict)
    }
    required_lean_omissions = {
        ("imports", "section_excluded"),
        (
            "vocabulary.tokens.items.*.locations",
            "file_locations_rolled_up",
        ),
        (
            "vocabulary.identifiers.items.*.locations",
            "file_locations_rolled_up",
        ),
    }
    if not required_lean_omissions <= omission_pairs:
        failures.append("lean projection did not account for standard omissions")

    structural = _mapping(context.get("structural_groups"))
    glossary = _mapping(context.get("glossary"))
    if scenario_id == "fresh":
        observed["graph_freshness"] = _mapping(structural.get("freshness")).get("status")
        observed["graph_available"] = structural.get("available")
        if observed["graph_freshness"] != "current" or observed[
            "graph_available"
        ] is not True:
            failures.append("fresh Graphify input was not reported current/available")
    elif scenario_id == "stale":
        observed["graph_freshness"] = _mapping(structural.get("freshness")).get("status")
        if observed["graph_freshness"] != "stale":
            failures.append("stale Graphify input was not reported stale")
    elif scenario_id == "absent":
        observed["graph_present"] = structural.get("present")
        observed["glossary_present"] = glossary.get("present")
        if observed["graph_present"] is not False:
            failures.append("absent Graphify input was not reported absent")
        if observed["glossary_present"] is not False:
            failures.append("absent glossary was not reported absent")
    elif scenario_id == "partial":
        if (
            "vocabulary.identifiers.items",
            "list_items",
        ) not in omission_pairs:
            failures.append(
                "partial projection did not expose its identifier sample cap"
            )
    elif scenario_id == "monorepo":
        observed["monorepo"] = context.get("monorepo")
        if _mapping(context.get("monorepo")).get("detected") is not True:
            failures.append("workspace manifest did not trigger monorepo detection")
    elif scenario_id == "resumed-glossary":
        concepts = glossary.get("concepts", [])
        observed["glossary_present"] = glossary.get("present")
        observed["concept_statuses"] = {
            item.get("term"): item.get("status")
            for item in concepts if isinstance(item, dict)
        }
        if observed["glossary_present"] is not True:
            failures.append("valid existing glossary was not returned")
        if observed["concept_statuses"] != {
            "Gateway Route": "proposed",
            "Payment Service": "canonical",
        }:
            failures.append("resumed glossary statuses were not preserved")
    elif scenario_id in {"markdown-glossary", "both-glossaries"}:
        repository_glossary = _mapping(context.get("repository_glossary"))
        observed["glossary_present"] = glossary.get("present")
        observed["repository_glossary"] = {
            key: repository_glossary.get(key)
            for key in ("present", "readable", "sha256", "nested_ignored")
        }
        expected_structured = scenario_id == "both-glossaries"
        if observed["glossary_present"] is not expected_structured:
            failures.append(
                "structured glossary presence did not match the scenario"
            )
        expected_digest = hashlib.sha256(
            MARKDOWN_GLOSSARY_TEXT.encode("utf-8")
        ).hexdigest()
        if (
            repository_glossary.get("present") is not True
            or repository_glossary.get("readable") is not True
            or repository_glossary.get("sha256") != expected_digest
            or repository_glossary.get("nested_ignored") != []
        ):
            failures.append(
                "repository GLOSSARY.md was not reported present, readable, "
                "and exactly identified"
            )
        if MARKDOWN_GLOSSARY_CANARY in json.dumps(context):
            failures.append("repository GLOSSARY.md content entered the agent context")
    elif scenario_id == "sensitive-file":
        skipped = context.get("skipped", {}).get("sensitive", [])
        observed["sensitive_paths"] = skipped
        if set(skipped) != {".env", "api-secret.txt"}:
            failures.append("sensitive paths were not both excluded and reported")
        if SENSITIVE_CANARY in json.dumps(context):
            failures.append("sensitive canary entered the agent context")

    if scenario_id != "partial":
        unexpected = [
            item
            for item in omissions
            if isinstance(item, dict)
            and not (
                item.get("kind") == "section_excluded"
                and item.get("path") == "imports"
            )
            and not (
                item.get("kind") == "file_locations_rolled_up"
                and item.get("path", "").startswith("vocabulary.")
                and item.get("path", "").endswith(".locations")
            )
        ]
        if unexpected:
            failures.append(
                "scenario unexpectedly exceeded the standard lean projection"
            )
    return failures, observed


def _accepted_statuses(scenario: dict) -> list:
    return scenario.get("accepted_statuses", [scenario["expected_status"]])


def _status_failures(scenario: dict, response: dict) -> list[str]:
    accepted_statuses = _accepted_statuses(scenario)
    if response.get("status") not in accepted_statuses:
        return [
            f"agent status {response.get('status')!r} did not match "
            f"one of {accepted_statuses!r}"
        ]
    return []


def _evaluate_scenario(
    scenario: dict,
    *,
    root: Path,
    commands: list[dict],
    response: dict,
    before: dict[str, tuple],
    workspace: Path,
    limits: dict,
    trace_aliases: tuple[tuple[str, str], ...] = (),
) -> dict:
    scenario_id = scenario["id"]
    failures: list[str] = []
    relevant = (
        commands if scenario_id == "missing-cli"
        else _scenario_commands(commands, root)
    )
    if len(relevant) > limits["commands_per_scenario"]:
        failures.append("scenario command trace exceeded its bound")
    forbidden = (".env", "api-secret", "glossabet-out", "graphify-out", "glossary.json")
    for command in relevant:
        lowered = command["command"].casefold()
        if any(token in lowered for token in forbidden):
            failures.append("agent command directly named an excluded/artifact path")
        installed_skill_read = (
            scenario_id == "missing-cli"
            and ".agents/skills/glossabet/skill.md" in lowered
            and re.search(r"\b(cat|sed)\b", lowered) is not None
        )
        bundled_runner_probe = (
            scenario_id == "missing-cli"
            and ".agents/skills/glossabet/scripts/run_glossabet.py" in lowered
            and re.search(r"\btest\s+-f\b|\[\s+-f\b", lowered) is not None
        )
        if (
            "inspect" not in lowered
            and "--version" not in lowered
            and not installed_skill_read
            and not bundled_runner_probe
        ):
            failures.append("agent used a non-engine command inside the scenario")

    observed: dict[str, object] = {}
    if scenario_id == "missing-cli":
        if any("inspect" in command["command"] for command in relevant):
            failures.append("missing engine scenario attempted inspect")
        skill_boundary_observed = any(
            ".agents/skills/glossabet/skill.md" in command["command"].casefold()
            or ".agents/skills/glossabet/scripts/run_glossabet.py"
            in command["command"].casefold()
            for command in relevant
        )
        if not skill_boundary_observed:
            failures.append("Codex did not use the installed standalone skill boundary")
        version_commands = [
            command for command in relevant if "--version" in command["command"]
        ]
        engine_failure_observed = (
            len(version_commands) == 1
            and version_commands[0].get("exit_code") not in {0, None}
            and "glossabet" in version_commands[0]["output"].casefold()
        )
        if not engine_failure_observed:
            failures.append("missing CLI was not observed as an engine failure")
        observed["standalone_skill_boundary_observed"] = skill_boundary_observed
        # The observation records the engine-failure evidence itself, not
        # whether unrelated checks had already failed.
        observed["engine_missing"] = engine_failure_observed
    else:
        inspect_commands = [
            command for command in relevant if "inspect" in command["command"]
        ]
        if len(inspect_commands) != 1:
            failures.append(
                f"expected one attributable inspect command, found {len(inspect_commands)}"
            )
        elif scenario_id in {"malformed", "oversized", "symlinked"}:
            command = inspect_commands[0]
            if command.get("exit_code") == 0:
                failures.append("invalid direct input did not stop inspect")
            if not _expected_error(scenario_id, command["output"]):
                failures.append("inspect error did not identify the direct-input cause")
            observed["inspect_exit_code"] = command.get("exit_code")
            observed["error_sha256"] = hashlib.sha256(
                command["output"].encode()
            ).hexdigest()
        else:
            command = inspect_commands[0]
            if command.get("exit_code") != 0:
                failures.append("valid scenario inspect failed")
            context = _extract_context(command["output"])
            if context is None:
                failures.append("valid scenario produced no parseable context JSON")
            else:
                context_failures, observed = _check_context(scenario_id, context)
                failures.extend(context_failures)

    failures.extend(_status_failures(scenario, response))
    if not isinstance(response.get("facts"), list) or not response["facts"]:
        failures.append("agent returned no scenario facts")
    elif scenario_id in {"markdown-glossary", "both-glossaries"}:
        facts_text = "\n".join(
            item for item in response["facts"] if isinstance(item, str)
        )
        if "GLOSSARY.md" not in facts_text:
            failures.append(
                "agent facts did not acknowledge the repository GLOSSARY.md"
            )
        if MARKDOWN_GLOSSARY_CANARY in facts_text:
            failures.append(
                "agent read the repository GLOSSARY.md during Step 0"
            )
    if not isinstance(response.get("next_action"), str) or not response[
        "next_action"
    ].strip():
        failures.append("agent returned no next action")

    after = _snapshot(root)
    writes = _unexpected_writes(before, after)
    if writes:
        failures.append(f"unexpected repository writes: {writes}")

    return {
        "id": scenario_id,
        "delivery": scenario["delivery"],
        "passed": not failures,
        "failures": failures,
        "observed": observed,
        "agent_response": response,
        "unexpected_writes": writes,
        "trace": [
            _trace_summary(command, workspace, limits, trace_aliases)
            for command in relevant
        ],
    }


def _evaluate_session_hook(
    scenario: dict,
    *,
    root: Path,
    commands: list[dict],
    response: dict,
    before: dict[str, tuple],
    workspace: Path,
    limits: dict,
) -> dict:
    failures: list[str] = []
    if "glossabet" in HOOK_PROMPT.casefold():
        failures.append("session-hook user prompt named Glossabet")
    if commands:
        failures.append("session-hook agent ran a command or tool")

    failures.extend(_status_failures(scenario, response))
    facts = response.get("facts")
    facts_text = "\n".join(facts) if isinstance(facts, list) and all(
        isinstance(item, str) for item in facts
    ) else ""
    if not facts_text:
        failures.append("session-hook agent returned no facts")
    if HOOK_TERM not in facts_text:
        failures.append("session-hook context lost the canonical term")
    if HOOK_DEFINITION not in facts_text:
        failures.append("session-hook context lost the canonical definition")
    response_text = json.dumps(response, ensure_ascii=False)
    if HOOK_PROPOSED_TERM in response_text:
        failures.append("session-hook exposed a proposed term as settled context")
    if HOOK_SOURCE_CANARY in response_text:
        failures.append("session-hook exposed repository source text")
    if not isinstance(response.get("next_action"), str) or not response[
        "next_action"
    ].strip():
        failures.append("session-hook agent returned no next action")

    after = _snapshot(root)
    writes = _changed_paths(before, after)
    if writes:
        failures.append(f"session-hook wrote repository paths: {writes}")

    return {
        "id": scenario["id"],
        "delivery": scenario["delivery"],
        "passed": not failures,
        "failures": failures,
        "observed": {
            "agent_command_count": len(commands),
            "canonical_term_seen": HOOK_TERM in facts_text,
            "canonical_definition_seen": HOOK_DEFINITION in facts_text,
            "proposed_term_absent": HOOK_PROPOSED_TERM not in response_text,
            "source_text_absent": HOOK_SOURCE_CANARY not in response_text,
            "user_prompt_mentions_glossabet": (
                "glossabet" in HOOK_PROMPT.casefold()
            ),
            "user_prompt_sha256": hashlib.sha256(HOOK_PROMPT.encode()).hexdigest(),
        },
        "agent_response": response,
        "unexpected_writes": writes,
        "trace": [
            _trace_summary(command, workspace, limits) for command in commands
        ],
    }


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    # Mirror _tree_sha256's exclusions so the installed bytes never exceed
    # what the digest-bound artifact claim covered.
    return {
        name for name in names if _dotenv_part(name) or name == "__pycache__"
    }


def _prepare_marketplace(root: Path, name: str) -> None:
    shutil.copytree(
        PLUGIN,
        root / "plugins" / "glossabet",
        ignore=_copy_ignore,
    )
    _write_json(
        root / ".agents" / "plugins" / "marketplace.json",
        {
            "name": name,
            "interface": {"displayName": "Glossabet agent evaluation"},
            "plugins": [
                {
                    "name": "glossabet",
                    "source": {
                        "source": "local",
                        "path": "./plugins/glossabet",
                    },
                    "policy": {
                        "installation": "AVAILABLE",
                        "authentication": "ON_INSTALL",
                    },
                    "category": "Productivity",
                }
            ],
        },
    )


def _ensure_no_installed_glossabet(codex: str) -> None:
    data = _run(
        [codex, "plugin", "list", "--json"],
        cwd=ROOT,
        parse_json=True,
    )
    assert isinstance(data, dict)
    installed = data.get("installed", [])
    if any(
        isinstance(item, dict)
        and (
            item.get("name") == "glossabet"
            or str(item.get("pluginId", "")).startswith("glossabet@")
        )
        for item in installed
    ):
        _fail("a Glossabet plugin is already installed; refusing to replace it")


def _install_plugin(
    codex: str,
    marketplace: Path,
    marketplace_name: str,
) -> tuple[str, Path, Path]:
    plugin_id = f"glossabet@{marketplace_name}"
    # Progress is attached to any failure so cleanup removes exactly the
    # state that was created, including the cache directory Codex leaves
    # behind once `plugin add` has run.
    progress = {
        "marketplace_added": False,
        "plugin_added": False,
        "cache_parent": None,
    }
    try:
        added = _run(
            [codex, "plugin", "marketplace", "add", str(marketplace), "--json"],
            cwd=ROOT,
            parse_json=True,
        )
        progress["marketplace_added"] = True
        assert isinstance(added, dict)
        if added.get("marketplaceName") != marketplace_name:
            _fail("Codex registered the temporary marketplace under another name")
        installed = _run(
            [codex, "plugin", "add", plugin_id, "--json"],
            cwd=ROOT,
            parse_json=True,
        )
        progress["plugin_added"] = True
        expected_cache = Path.home() / ".codex" / "plugins" / "cache"
        expected_parent = expected_cache / marketplace_name
        progress["cache_parent"] = expected_parent
        assert isinstance(installed, dict)
        path = Path(str(installed.get("installedPath", "")))
        if (
            installed.get("version") != __version__
            or not path.is_absolute()
            or path.name != __version__
            or path.parent.name != "glossabet"
            or path.parents[1] != expected_parent
        ):
            _fail(f"Codex returned an unexpected plugin installation: {installed}")
        runner = path / "skills" / "glossabet" / "scripts" / "run_glossabet.py"
        if not runner.is_file():
            _fail("installed plugin has no skill-local runner")
        installed_hook = path / "hooks" / "hooks.json"
        if (
            installed_hook.is_symlink()
            or not installed_hook.is_file()
            or installed_hook.read_bytes() != PLUGIN_HOOK.read_bytes()
        ):
            _fail("installed plugin has no exact session-start hook")
    except BaseException as exc:
        for key, value in progress.items():
            setattr(exc, key, value)
        raise
    return plugin_id, path, expected_parent


def _cleanup_plugin(
    codex: str,
    plugin_id: str,
    marketplace_name: str,
    cache_parent: Path | None,
    *,
    plugin_added: bool = True,
    marketplace_added: bool = True,
) -> None:
    errors = []
    if plugin_added:
        try:
            _run(
                [codex, "plugin", "remove", plugin_id, "--json"],
                cwd=ROOT,
                parse_json=True,
            )
        except Exception as exc:  # preserve all narrowly scoped cleanup failures
            errors.append(str(exc))
    if marketplace_added:
        try:
            _run(
                [
                    codex,
                    "plugin",
                    "marketplace",
                    "remove",
                    marketplace_name,
                    "--json",
                ],
                cwd=ROOT,
                parse_json=True,
            )
        except Exception as exc:
            errors.append(str(exc))
    if cache_parent is not None and cache_parent.exists():
        expected = Path.home() / ".codex" / "plugins" / "cache" / marketplace_name
        if cache_parent != expected:
            errors.append(f"refusing unexpected cache cleanup path: {cache_parent}")
        else:
            try:
                cache_parent.rmdir()
            except OSError as exc:
                errors.append(f"temporary plugin cache was not empty: {exc}")

    try:
        plugin_data = _run(
            [codex, "plugin", "list", "--json"],
            cwd=ROOT,
            parse_json=True,
        )
        marketplace_data = _run(
            [codex, "plugin", "marketplace", "list", "--json"],
            cwd=ROOT,
            parse_json=True,
        )
        assert isinstance(plugin_data, dict)
        assert isinstance(marketplace_data, dict)
        if any(
            isinstance(item, dict)
            and (
                item.get("pluginId") == plugin_id
                or item.get("name") == "glossabet"
            )
            for item in plugin_data.get("installed", [])
        ):
            errors.append("temporary plugin remains installed")
        if any(
            isinstance(item, dict)
            and (
                item.get("name") == marketplace_name
                or item.get("marketplaceName") == marketplace_name
            )
            for item in marketplace_data.get("marketplaces", [])
        ):
            errors.append("temporary marketplace remains configured")
    except Exception as exc:
        errors.append(str(exc))
    if errors:
        _fail("; ".join(errors))


def _prompt_for(scenarios: list[dict], roots: dict[str, Path]) -> str:
    supplied = [
        {
            "id": scenario["id"],
            "path": str(roots[scenario["id"]]),
            "description": scenario["description"],
            "allowed_statuses": _accepted_statuses(scenario),
        }
        for scenario in scenarios
    ]
    return (
        PROMPT_PATH.read_text(encoding="utf-8")
        + "\n\nScenario list:\n"
        + json.dumps(supplied, indent=2)
    )


def _install_standalone_skill(destination: Path) -> None:
    _run(
        [
            sys.executable,
            "-m",
            "glossabet",
            "install",
            "--agent",
            "codex",
            "--destination",
            str(destination),
        ],
        cwd=ROOT,
    )
    installed = destination / "SKILL.md"
    if installed.read_bytes() != CANONICAL_SKILL.read_bytes():
        _fail("standalone installed skill differs from canonical source")
    if (destination / "scripts" / "run_glossabet.py").exists():
        _fail("standalone missing-CLI scenario unexpectedly has a plugin runner")


def _validate_manifest(manifest: dict) -> tuple[list[dict], dict]:
    if manifest.get("schema_version") != 1:
        _fail("unsupported agent scenario manifest")
    scenarios = manifest.get("scenarios")
    limits = manifest.get("trace_limits")
    if not isinstance(scenarios, list) or not isinstance(limits, dict):
        _fail("agent scenario manifest is malformed")
    expected_ids = list(REQUIRED_SCENARIO_IDS)
    if [item.get("id") for item in scenarios if isinstance(item, dict)] != expected_ids:
        _fail("agent scenario ids/order do not match the current contract")
    status_vocabulary = STATUS_VOCABULARY
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            _fail("agent scenario is malformed")
        expected = scenario.get("expected_status")
        accepted = scenario.get("accepted_statuses", [expected])
        description = scenario.get("description")
        if not isinstance(description, str) or not description.strip():
            _fail(f"agent scenario {scenario.get('id')} has no description")
        if (
            expected not in status_vocabulary
            or not isinstance(accepted, list)
            or not accepted
            or expected not in accepted
            or any(status not in status_vocabulary for status in accepted)
        ):
            _fail(f"agent scenario {scenario.get('id')} has invalid statuses")
        expected_delivery = (
            "plugin-hook"
            if scenario.get("id") == "session-hook"
            else "standalone-skill"
            if scenario.get("id") == "missing-cli"
            else "plugin"
        )
        if scenario.get("delivery") != expected_delivery:
            _fail(f"agent scenario {scenario.get('id')} has invalid delivery")
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
        _fail("agent trace limits are malformed")
    return scenarios, limits


def _run_missing_cli_scenario(
    codex: str,
    scenario: dict,
    limits: dict,
    work: Path,
    *,
    disabled_skills: tuple[Path, ...] = (),
) -> tuple[dict, dict]:
    missing_workspace = work / "missing-cli-run"
    missing_root = missing_workspace / "scenarios" / "missing-cli"
    _make_scenario(missing_root, "missing-cli")
    _install_standalone_skill(
        missing_root / ".agents" / "skills" / "glossabet"
    )
    missing_before = _snapshot(missing_root)
    restricted_path = os.pathsep.join(
        [str(Path(codex).parent), "/usr/bin", "/bin"]
    )
    missing_environment = {
        **os.environ,
        "PATH": restricted_path,
        "GLOSSABET_CACHE_DIR": str(missing_workspace / ".engine-cache"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    response, commands, usage = _run_codex(
        codex,
        workspace=missing_root,
        prompt=_prompt_for([scenario], {"missing-cli": missing_root}),
        environment=missing_environment,
        limits=limits,
        disabled_skills=disabled_skills,
        use_shell_profile=False,
        allow_login_shell=False,
    )
    response_items = _response_by_id(response, ["missing-cli"])
    result = _evaluate_scenario(
        scenario,
        root=missing_root,
        commands=commands,
        response=response_items["missing-cli"],
        before=missing_before,
        workspace=missing_workspace,
        limits=limits,
    )
    return result, usage


def probe_missing_cli() -> dict:
    manifest = _read_json(SCENARIOS_PATH, "agent scenario manifest")
    scenarios, limits = _validate_manifest(manifest)
    scenario = next(item for item in scenarios if item["id"] == "missing-cli")
    codex = shutil.which("codex")
    if codex is None:
        _fail("codex is not installed")
    codex = str(Path(codex).resolve())
    disabled_skills = _competing_standalone_skill_paths()
    with tempfile.TemporaryDirectory(prefix="glossabet-missing-cli-probe-") as raw:
        result, usage = _run_missing_cli_scenario(
            codex,
            scenario,
            limits,
            Path(raw),
            disabled_skills=disabled_skills,
        )
    return {
        "codex_version": _codex_version(codex),
        "scenario": result,
        "usage": usage,
    }


def run_evaluation(output: Path = DEFAULT_RESULTS) -> dict:
    manifest = _read_json(SCENARIOS_PATH, "agent scenario manifest")
    scenarios, limits = _validate_manifest(manifest)
    codex = shutil.which("codex")
    if codex is None:
        _fail("codex is not installed")
    codex = str(Path(codex).resolve())
    codex_version = _codex_version(codex)
    # The identity must describe the bytes this run consumes; computing it
    # after the host runs would bind the evidence to whatever the tree
    # contains by then.
    inputs = _input_identity()
    disabled_skills = _competing_standalone_skill_paths()
    _ensure_no_installed_glossabet(codex)

    plugin_scenarios = [
        scenario for scenario in scenarios if scenario["delivery"] == "plugin"
    ]
    hook_scenario = next(
        scenario for scenario in scenarios if scenario["id"] == "session-hook"
    )
    missing_scenario = next(
        scenario for scenario in scenarios if scenario["id"] == "missing-cli"
    )
    results: list[dict] = []
    usages: list[dict] = []
    delivery_trace: list[dict] = []
    delivery_trace_truncated = False

    with tempfile.TemporaryDirectory(prefix="glossabet-agent-eval-") as raw:
        work = Path(raw)
        marketplace_name = f"glossabet-agent-eval-{uuid.uuid4().hex[:12]}"
        marketplace = work / "marketplace"
        _prepare_marketplace(marketplace, marketplace_name)
        plugin_id = f"glossabet@{marketplace_name}"
        installed_path: Path | None = None
        cache_parent: Path | None = None

        batch = work / "plugin-run"
        roots = {
            scenario["id"]: batch / "scenarios" / scenario["id"]
            for scenario in plugin_scenarios
        }
        before = {}
        for scenario in plugin_scenarios:
            root = roots[scenario["id"]]
            _make_scenario(root, scenario["id"])
            before[scenario["id"]] = _snapshot(root)
        environment = {
            **os.environ,
            "GLOSSABET_CACHE_DIR": str(batch / ".engine-cache"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        hook_root = work / "session-hook-run"
        _make_scenario(hook_root, "session-hook")
        hook_before = _snapshot(hook_root)
        hook_environment = {
            **os.environ,
            "GLOSSABET_CACHE_DIR": str(work / ".hook-engine-cache"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        hook_result: dict | None = None

        primary_error: BaseException | None = None
        cleanup_verified = False
        stage = "plugin-preflight"
        marketplace_added = False
        plugin_added = False
        try:
            plugin_id, installed_path, cache_parent = _install_plugin(
                codex, marketplace, marketplace_name
            )
            marketplace_added = True
            plugin_added = True
            stage = "plugin-scenarios"
            hook_response, hook_commands, hook_usage = _run_codex(
                codex,
                workspace=hook_root,
                prompt=HOOK_PROMPT,
                environment=hook_environment,
                limits=limits,
                disabled_skills=disabled_skills,
                bypass_hook_trust=True,
            )
            usages.append(hook_usage)
            hook_response_items = _response_by_id(
                hook_response, ["session-hook"]
            )
            hook_result = _evaluate_session_hook(
                hook_scenario,
                root=hook_root,
                commands=hook_commands,
                response=hook_response_items["session-hook"],
                before=hook_before,
                workspace=hook_root,
                limits=limits,
            )
            results.append(hook_result)
            response, commands, usage = _run_codex(
                codex,
                workspace=batch,
                prompt=_prompt_for(plugin_scenarios, roots),
                environment=environment,
                limits=limits,
                disabled_skills=disabled_skills,
                bypass_hook_trust=True,
            )
            usages.append(usage)
            version_command = _installed_version_command(
                commands,
                installed_path=installed_path,
                workspace=batch,
                limits=limits,
            )
            installed_skill = installed_path / "skills" / "glossabet" / "SKILL.md"
            glossabet_skill_reads = [
                command
                for command in commands
                if "skill.md" in command["command"].casefold()
                and (
                    "glossabet" in command["command"].casefold()
                    or "glossarize" in command["command"].casefold()
                )
            ]
            if not any(
                str(installed_skill) in command["command"]
                for command in glossabet_skill_reads
            ):
                _fail("Codex did not read the temporarily installed plugin skill")
            if any(
                str(installed_skill) not in command["command"]
                for command in glossabet_skill_reads
            ):
                _fail("Codex read a different Glossabet skill during the plugin run")
            trace_aliases = ((str(installed_path), "<INSTALLED_PLUGIN>"),)
            skill_read_summaries = [
                _trace_summary(command, batch, limits, trace_aliases)
                for command in commands
                if command in glossabet_skill_reads
                and command is not version_command
            ]
            allowed_reads = max(0, limits["commands_per_scenario"] - 1)
            delivery_trace = [
                _trace_summary(version_command, batch, limits, trace_aliases)
            ] + skill_read_summaries[:allowed_reads]
            delivery_trace_truncated = len(skill_read_summaries) > allowed_reads
            response_items = _response_by_id(
                response, [scenario["id"] for scenario in plugin_scenarios]
            )
            for scenario in plugin_scenarios:
                scenario_id = scenario["id"]
                results.append(_evaluate_scenario(
                    scenario,
                    root=roots[scenario_id],
                    commands=commands,
                    response=response_items[scenario_id],
                    before=before[scenario_id],
                    workspace=batch,
                    limits=limits,
                    trace_aliases=trace_aliases,
                ))
        except BaseException as exc:
            # BaseException so an operator interrupt still records its
            # cleanup outcome and attempt instead of vanishing.
            primary_error = exc
            marketplace_added = getattr(
                exc, "marketplace_added", marketplace_added
            )
            plugin_added = getattr(exc, "plugin_added", plugin_added)
            cache_parent = getattr(exc, "cache_parent", cache_parent)
        finally:
            try:
                _cleanup_plugin(
                    codex,
                    plugin_id,
                    marketplace_name,
                    cache_parent,
                    plugin_added=plugin_added,
                    marketplace_added=marketplace_added,
                )
                cleanup_verified = True
            except Exception as cleanup_exc:
                if primary_error is None:
                    primary_error = cleanup_exc
                elif isinstance(primary_error, Exception):
                    primary_error = AgentEvaluationError(
                        f"{primary_error}; cleanup also failed: {cleanup_exc}"
                    )
                else:
                    # Never replace an interrupt with the cleanup failure;
                    # report it alongside instead.
                    print(
                        "agent evaluation: cleanup failed during interrupt: "
                        f"{cleanup_exc}",
                        file=sys.stderr,
                        flush=True,
                    )
        if primary_error is not None:
            setattr(primary_error, "cleanup_verified", cleanup_verified)
            setattr(primary_error, "attempt_usage", usages)
            setattr(primary_error, "failed_stage", stage)
            raise primary_error

        stage = "missing-cli"
        try:
            missing_result, missing_usage = _run_missing_cli_scenario(
                codex,
                missing_scenario,
                limits,
                work,
                disabled_skills=disabled_skills,
            )
        except BaseException as exc:
            setattr(exc, "cleanup_verified", cleanup_verified)
            setattr(exc, "attempt_usage", usages)
            setattr(exc, "failed_stage", stage)
            raise
        usages.append(missing_usage)
        results.append(missing_result)

    ordered = {result["id"]: result for result in results}
    results = [ordered[scenario["id"]] for scenario in scenarios]
    passed = sum(result["passed"] for result in results)
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "inputs": inputs,
        "environment": {
            "codex_version": codex_version,
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "method": {
            "host_runs": 3,
            "codex_exec_ephemeral": True,
            "sandbox": "workspace-write",
            "approval_policy": "never",
            "plugin_lifecycle": "temporary install and complete removal",
            "same_name_skill_policy": (
                "disable Glossabet's default standalone skill for each host run"
            ),
            "missing_cli_shell_profile_disabled": True,
            "missing_cli_login_shell_disabled": True,
            "plugin_hook_trust": (
                "one-off bypass for the digest-bound temporary plugin artifact"
            ),
            "trace_limits": limits,
            "model": "configured default; Codex CLI JSONL did not report it",
        },
        "delivery": {
            "installed_plugin_skill_read": True,
            "installed_plugin_engine_version_checked": True,
            "installed_plugin_hook_sha256": _sha256(PLUGIN_HOOK),
            "session_start_hook_context_seen": (
                hook_result is not None
                and hook_result.get("observed", {}).get("canonical_term_seen")
                is True
                and hook_result.get("observed", {}).get(
                    "canonical_definition_seen"
                )
                is True
            ),
            "session_start_user_prompt_mentions_glossabet": False,
            "standalone_skill_boundary_observed": missing_result.get(
                "observed", {}
            ).get("standalone_skill_boundary_observed")
            is True,
            "temporary_plugin_state_removed": True,
            "trace": delivery_trace,
            "trace_truncated": delivery_trace_truncated,
        },
        "usage": usages,
        "scenarios": results,
        "summary": {
            "required": len(scenarios),
            "passed": passed,
            "failed": len(scenarios) - passed,
            "all_passed": passed == len(scenarios),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _result_safety_checks(result: dict) -> dict:
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
        and not _trace_ran_inspect(missing_trace),
        "temporary_state_removed": delivery.get(
            "temporary_plugin_state_removed"
        )
        is True,
    }


def _trace_ran_inspect(trace) -> bool:
    return any(
        "inspect" in str(command.get("command", "")).casefold()
        for command in trace
        if isinstance(command, dict)
    )


def _result_safety_errors(result: dict) -> list[str]:
    errors: list[str] = []
    checks = _result_safety_checks(result)
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
        if scenario_id == "missing-cli" and _trace_ran_inspect(trace):
            errors.append("missing-cli: inspect ran after the engine failure")
    sensitive = next(
        (
            scenario
            for scenario in scenarios
            if isinstance(scenario, dict) and scenario.get("id") == "sensitive-file"
        ),
        None,
    )
    if sensitive is None or sensitive.get("observed", {}).get(
        "sensitive_paths"
    ) != [".env", "api-secret.txt"]:
        errors.append("sensitive-file exclusions are missing or stale")
    return errors


def _raw_result_record(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        _fail("completed agent result is missing or symlinked")
    try:
        relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        _fail("completed agent result is outside the repository")
    return {"path": relative, "sha256": _sha256(path)}


def _attempt_from_result(attempt_id: str, result: dict, path: Path) -> dict:
    missing = next(
        (
            scenario
            for scenario in result.get("scenarios", [])
            if isinstance(scenario, dict) and scenario.get("id") == "missing-cli"
        ),
        {},
    )
    plugin_scenarios = [
        scenario
        for scenario in result.get("scenarios", [])
        if isinstance(scenario, dict) and scenario.get("id") != "missing-cli"
    ]
    safety_checks = _result_safety_checks(result)
    safety_errors = _result_safety_errors(result)
    failures = [
        f"{scenario.get('id', '<unknown>')}: {failure}"
        for scenario in result.get("scenarios", [])
        if isinstance(scenario, dict)
        for failure in scenario.get("failures", [])
        if isinstance(failure, str)
    ]
    return {
        "id": attempt_id,
        "recorded_on": datetime.now(timezone.utc).date().isoformat(),
        "kind": "full",
        "inputs": result.get("inputs", {}),
        "outcome": "completed",
        "evidence_basis": "retained-raw-result",
        "checks": {
            "plugin_preflight": "passed",
            "plugin_scenarios": (
                "passed"
                if plugin_scenarios
                and all(scenario.get("passed") is True for scenario in plugin_scenarios)
                else "failed"
            ),
            "missing_cli_boundary": (
                "passed" if missing.get("passed") is True else "failed"
            ),
        },
        "procedural_pass": result.get("summary", {}).get("all_passed") is True,
        "safety_checks": safety_checks,
        "safety_pass": all(safety_checks.values()) and not safety_errors,
        "cleanup_verified": result.get("delivery", {}).get(
            "temporary_plugin_state_removed"
        )
        is True,
        "failures": failures + safety_errors,
        "evidence": ["bounded full result retained at the recorded path"],
        "usage": _usage_totals(result.get("usage", [])),
        "scenario_summary": result.get("summary"),
        "raw_result": _raw_result_record(path),
    }


def _attempt_from_probe(attempt_id: str, probe: dict) -> dict:
    scenario = probe["scenario"]
    trace = scenario.get("trace", [])
    safety_errors: list[str] = []
    if scenario.get("unexpected_writes") != []:
        safety_errors.append("missing-cli probe recorded unexpected writes")
    if _trace_ran_inspect(trace):
        safety_errors.append("missing-cli probe invoked inspect")
    safety_checks = {
        "sensitive_canary_absent": SENSITIVE_CANARY not in json.dumps(probe),
        "unexpected_repository_writes_absent": scenario.get(
            "unexpected_writes"
        )
        == [],
        "missing_cli_inspect_absent": not _trace_ran_inspect(trace),
        "temporary_state_removed": True,
    }
    inputs = _input_identity()
    inputs["plugin_sha256"] = None
    return {
        "id": attempt_id,
        "recorded_on": datetime.now(timezone.utc).date().isoformat(),
        "kind": "missing-cli-only",
        "inputs": inputs,
        "outcome": "completed",
        "evidence_basis": "session-record",
        "checks": {
            "plugin_preflight": "not_run",
            "plugin_scenarios": "not_run",
            "missing_cli_boundary": (
                "passed" if scenario.get("passed") is True else "failed"
            ),
        },
        "procedural_pass": scenario.get("passed") is True,
        "safety_checks": safety_checks,
        "safety_pass": all(safety_checks.values()) and not safety_errors,
        "cleanup_verified": True,
        "failures": list(scenario.get("failures", [])) + safety_errors,
        "evidence": [
            "bounded missing-CLI trace returned by the isolated probe",
            *[
                str(command.get("command", ""))
                for command in trace
                if isinstance(command, dict)
            ],
        ],
        "usage": _usage_totals(probe.get("usage", {})),
        "scenario_summary": None,
        "raw_result": None,
    }


def _attempt_from_error(attempt_id: str, exc: BaseException) -> dict:
    message = str(exc) or type(exc).__name__
    # Errors raised before the managed plugin lifecycle create no test-owned
    # state. Once that lifecycle begins, run_evaluation attaches the observed
    # cleanup outcome explicitly.
    cleanup_verified = getattr(exc, "cleanup_verified", True) is True
    unsafe = any(
        marker in message.casefold()
        for marker in ("sensitive canary", "unexpected write", "cleanup also failed")
    )
    safety_checks = {
        "sensitive_canary_absent": "sensitive canary" not in message.casefold(),
        "unexpected_repository_writes_absent": (
            "unexpected write" not in message.casefold()
        ),
        "missing_cli_inspect_absent": True,
        "temporary_state_removed": cleanup_verified,
    }
    stage_checks = {
        "plugin-preflight": {
            "plugin_preflight": "failed",
            "plugin_scenarios": "not_run",
            "missing_cli_boundary": "not_run",
        },
        "plugin-scenarios": {
            "plugin_preflight": "passed",
            "plugin_scenarios": "failed",
            "missing_cli_boundary": "not_run",
        },
        "missing-cli": {
            "plugin_preflight": "passed",
            "plugin_scenarios": "passed",
            "missing_cli_boundary": "failed",
        },
    }
    checks = stage_checks.get(
        getattr(exc, "failed_stage", "plugin-preflight"),
        stage_checks["plugin-preflight"],
    )
    return {
        "id": attempt_id,
        "recorded_on": datetime.now(timezone.utc).date().isoformat(),
        "kind": "full",
        "inputs": _input_identity(),
        "outcome": "aborted",
        "evidence_basis": "session-record",
        "checks": checks,
        "procedural_pass": False,
        "safety_checks": safety_checks,
        "safety_pass": all(safety_checks.values()) and not unsafe,
        "cleanup_verified": cleanup_verified,
        "failures": [message],
        "evidence": [message],
        "usage": _usage_totals(getattr(exc, "attempt_usage", [])),
        "scenario_summary": None,
        "raw_result": None,
    }


def _attempt_from_probe_error(attempt_id: str, exc: Exception) -> dict:
    attempt = _attempt_from_error(attempt_id, exc)
    attempt["kind"] = "missing-cli-only"
    attempt["inputs"]["plugin_sha256"] = None
    attempt["checks"] = {
        "plugin_preflight": "not_run",
        "plugin_scenarios": "not_run",
        "missing_cli_boundary": "failed",
    }
    return attempt


def _digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _validated_run_output(path: Path) -> Path:
    candidate = path if path.is_absolute() else ROOT / path
    if RUNS_PATH.is_symlink() or candidate.suffix != ".json":
        _fail("agent run output must be a JSON file under evaluation/agent-runs")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(RUNS_PATH.resolve())
    except ValueError:
        _fail("agent run output must stay under evaluation/agent-runs")
    if candidate.exists() or candidate.is_symlink():
        _fail(f"refusing to overwrite existing agent result: {candidate}")
    return candidate


def _artifact_shape_errors(recorded: object) -> list[str]:
    """Check the recorded artifact identity is well-formed without comparing
    it to the current tree; the release gate performs that comparison."""
    keys = _ARTIFACT_IDENTITY_KEYS
    if (
        not isinstance(recorded, dict)
        or set(recorded) != keys
        or not isinstance(recorded.get("engine_version"), str)
        or not recorded.get("engine_version")
        or any(not _digest(recorded[key]) for key in keys - {"engine_version"})
    ):
        return ["recorded plugin artifact identity is malformed"]
    return []


def _history_errors(
    path: Path = HISTORY_PATH,
    *,
    result_path: Path | None = None,
    current: bool = False,
) -> list[str]:
    errors: list[str] = []
    try:
        history = _read_json(path, "agent attempt history")
    except AgentEvaluationError as exc:
        return [str(exc)]
    if history.get("schema_version") != HISTORY_SCHEMA_VERSION:
        errors.append("agent attempt history schema is stale")
    if path.is_symlink():
        errors.append("agent attempt history is symlinked")
    if current:
        errors.extend(_artifact_errors(history.get("current_artifact")))
    else:
        errors.extend(_artifact_shape_errors(history.get("current_artifact")))
    attempts = history.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        return errors + ["agent attempt history is empty or malformed"]
    seen: set[str] = set()
    full_input_keys = _INPUT_IDENTITY_KEYS
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
        if not isinstance(inputs, dict) or set(inputs) != full_input_keys:
            errors.append(f"{label} input identity is malformed")
        else:
            for key, value in inputs.items():
                if key == "engine_version":
                    if not isinstance(value, str) or not value:
                        errors.append(f"{label} engine version is malformed")
                elif key == "plugin_sha256" and value is None:
                    if attempt.get("kind") != "missing-cli-only":
                        errors.append(f"{label} lacks its plugin identity")
                elif not _digest(value):
                    errors.append(f"{label} {key} is not a SHA-256 digest")
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
        expected_usage_keys = set(_USAGE_KEYS)
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
        raw = attempt.get("raw_result")
        if raw is not None:
            if not isinstance(raw, dict) or set(raw) != {"path", "sha256"}:
                errors.append(f"{label} raw result reference is malformed")
                continue
            try:
                raw_candidate = ROOT / raw["path"]
                if raw_candidate.is_symlink():
                    raise ValueError("raw result is symlinked")
                raw_path = raw_candidate.resolve()
                # Confined to the immutable runs directory, mirroring
                # _validated_run_output on the write path: retention must
                # not be satisfiable by a file vouching for itself.
                raw_path.relative_to(RUNS_PATH.resolve())
            except (KeyError, TypeError, ValueError):
                errors.append(
                    f"{label} raw result escapes evaluation/agent-runs"
                )
                continue
            if not raw_path.is_file():
                errors.append(f"{label} raw result is missing or symlinked")
                continue
            if not _digest(raw.get("sha256")) or _sha256(raw_path) != raw["sha256"]:
                errors.append(f"{label} raw result digest is stale")
                continue
            retained_results.add(raw_path)
            retained_result_digests.add(raw["sha256"])
            try:
                raw_result = _read_json(raw_path, f"{label} raw result")
            except AgentEvaluationError as exc:
                errors.append(str(exc))
                continue
            if raw_result.get("inputs") != inputs:
                errors.append(f"{label} raw result input identity differs")
            if raw_result.get("summary") != attempt.get("scenario_summary"):
                errors.append(f"{label} raw result summary differs")
            errors.extend(
                f"{label}: {error}" for error in _result_safety_errors(raw_result)
            )
            if attempt.get("evidence_basis") != "retained-raw-result":
                errors.append(f"{label} raw result has the wrong evidence basis")
        elif attempt.get("evidence_basis") == "retained-raw-result":
            errors.append(f"{label} claims a retained raw result but has none")
    if history.get("summary") != _history_summary(
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
                    _sha256(result_path) in retained_result_digests
                )
        if not result_is_retained:
            errors.append("agent result is not retained by the attempt history")
    return errors


def _result_input_errors(result: dict) -> list[str]:
    if result.get("inputs") != _input_identity():
        return ["agent result input identity is stale"]
    return []


def _input_shape_errors(inputs: object) -> list[str]:
    """Check the recorded input identity is well-formed without comparing it
    to the current tree; the release gate performs that comparison."""
    keys = _INPUT_IDENTITY_KEYS
    if (
        not isinstance(inputs, dict)
        or set(inputs) != keys
        or not isinstance(inputs.get("engine_version"), str)
        or not inputs.get("engine_version")
        or any(not _digest(inputs[key]) for key in keys - {"engine_version"})
    ):
        return ["agent result input identity is malformed"]
    return []


def _recorded_scenario_generation(result: dict) -> list[str]:
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
    result = _read_json(path, "agent evaluation results")
    if current:
        errors.extend(_result_input_errors(result))
    else:
        errors.extend(_input_shape_errors(result.get("inputs")))
    method = result.get("method")
    recorded_limits = (
        method.get("trace_limits") if isinstance(method, dict) else None
    )
    if current:
        # The release gate demands the recorded run used the current
        # scenario manifest exactly.
        manifest = _read_json(SCENARIOS_PATH, "agent scenario manifest")
        scenarios, manifest_limits = _validate_manifest(manifest)
        expected_ids = [scenario["id"] for scenario in scenarios]
        limits_ok = recorded_limits == manifest_limits
    else:
        # Genuineness never reads the current manifest: the evidence may
        # honestly lag it. The scenario set and limit shape are pinned by
        # the evaluator itself.
        expected_ids = _recorded_scenario_generation(result)
        limits_ok = (
            isinstance(recorded_limits, dict)
            and set(recorded_limits) == _TRACE_LIMIT_KEYS
            and all(
                isinstance(value, int)
                and not isinstance(value, bool)
                and 0 < value <= _TRACE_LIMIT_CEILINGS[key]
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
        delivery_hook_sha == _sha256(PLUGIN_HOOK)
        if current
        else _digest(delivery_hook_sha)
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
        expected_boundary = missing_cli.get("observed", {}).get(
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
        hook_observed = hook.get("observed", {})
        hook_prompt_sha = hook_observed.get("user_prompt_sha256")
        hook_prompt_sha_ok = (
            hook_prompt_sha == hashlib.sha256(HOOK_PROMPT.encode()).hexdigest()
            if current
            else _digest(hook_prompt_sha)
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
    errors.extend(_result_safety_errors(result))
    errors.extend(_history_errors(result_path=path, current=current))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--run", action="store_true")
    action.add_argument("--probe-missing-cli", action="store_true")
    action.add_argument("--refresh-artifact", action="store_true")
    action.add_argument("--verify-results", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--current",
        action="store_true",
        help=(
            "with --verify-results, additionally require the evidence to "
            "match the current plugin artifact and inputs (the release gate)"
        ),
    )
    args = parser.parse_args(argv)
    try:
        if args.output is not None and not args.run:
            _fail("--output can be used only with --run")
        if args.current and args.verify_results is None:
            _fail("--current can be used only with --verify-results")
        if args.run:
            attempt_id = _new_attempt_id("full")
            output = _validated_run_output(
                args.output or RUNS_PATH / f"{attempt_id}.json"
            )
            try:
                result = run_evaluation(output)
            except BaseException as exc:
                try:
                    _append_attempt(_attempt_from_error(attempt_id, exc))
                except Exception as append_exc:
                    print(
                        "agent evaluation: failed to record the aborted "
                        f"attempt: {append_exc}",
                        file=sys.stderr,
                    )
                raise
            _append_attempt(_attempt_from_result(attempt_id, result, output))
            _promote_current_result(output)
            summary = result["summary"]
            print(
                f"installed-agent evaluation: {summary['passed']}/"
                f"{summary['required']} scenarios passed"
            )
            return 0 if summary["all_passed"] else 1
        if args.probe_missing_cli:
            attempt_id = _new_attempt_id("missing-cli")
            try:
                probe = probe_missing_cli()
            except Exception as exc:
                _append_attempt(_attempt_from_probe_error(attempt_id, exc))
                raise
            _append_attempt(_attempt_from_probe(attempt_id, probe))
            scenario = probe["scenario"]
            print(json.dumps({
                "codex_version": probe["codex_version"],
                "passed": scenario["passed"],
                "failures": scenario["failures"],
                "observed": scenario["observed"],
                "trace": scenario["trace"],
                "usage": probe["usage"],
            }, indent=2, sort_keys=True))
            return 0 if scenario["passed"] else 1
        if args.refresh_artifact:
            artifact = _refresh_artifact_record()
            print(json.dumps(artifact, indent=2, sort_keys=True))
            return 0
        errors = verify_results(args.verify_results, current=args.current)
        if errors:
            for error in errors:
                print(f"agent evaluation verification: {error}", file=sys.stderr)
            return 1
        if args.current:
            print(
                "installed-agent evidence matches the current plugin artifact "
                "and inputs; procedural reliability history retained"
            )
        else:
            print(
                "installed-agent evidence is genuine, bounded, and "
                "safety-complete; procedural reliability history retained"
            )
        return 0
    except (AgentEvaluationError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"agent evaluation: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
