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
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.claude.contract import (  # noqa: E402
    CANONICAL_DEFINITION,
    CANONICAL_SKILL,
    CANONICAL_TERM,
    DEFAULT_INSTALLED_PLUGIN,
    EXPECTED_CLAUDE_VERSION,
    HISTORY_PATH,
    HOOK_COMMAND,
    LIVE_CONFIRMATION,
    PROPOSED_TERM,
    PROVIDER_ENV_KEYS,
    RESULT_SCHEMA_VERSION,
    RUNS_PATH,
    SCENARIO_IDS,
    SOURCE_CANARY,
    ClaudeEvaluationError,
    ScratchCleanupFailed,
    fail,
    load_manifest,
    load_response_schema,
    read_json,
    sha256_text,
    tree_sha256,
    write_json,
    write_new_json,
)
from evaluation.claude.events import (  # noqa: E402
    api_retries,
    hook_event_seen,
    parse_events,
    response_shape_errors,
    structured_output,
    tool_calls,
)
from evaluation.claude.history import (  # noqa: E402
    AbortedRun,
    append_attempt,
    attempt_from_error,
    attempt_from_result,
    new_attempt_id,
    promote_current_result,
    usage_totals,
    validated_output,
)
from evaluation.claude.results import (  # noqa: E402
    input_identity,
    verify_history,
    verify_results,
)
from evaluation.harness.io import changed_paths, dotenv_part, file_sha256  # noqa: E402
from glossabet import __version__  # noqa: E402
from glossabet.install.claude_plugin import (  # noqa: E402
    CLAUDE_HOOKS_RELATIVE,
    CLAUDE_MANIFEST_RELATIVE,
    claude_hooks,
    claude_plugin_manifest,
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


def _provider_environment_name(name: str) -> bool:
    return name in PROVIDER_ENV_KEYS or name.startswith("ANTHROPIC_")


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
        fail(f"could not run {Path(arguments[0]).name}: {type(exc).__name__}")


def _require_success(
    result: subprocess.CompletedProcess[str], label: str, *, roots=()
) -> str:
    if result.returncode:
        detail = _safe_text(result.stderr or result.stdout, *roots)
        fail(f"{label} exited {result.returncode}: {detail}")
    return result.stdout


def _claude_version(
    claude: Path, *, environment: dict[str, str]
) -> str:
    result = _command([str(claude), "--version"], cwd=ROOT, environment=environment)
    output = _require_success(result, "claude --version").strip()
    match = re.fullmatch(r"([^\s]+) \(Claude Code\)", output)
    if match is None:
        fail("Claude Code returned an unrecognized version string")
    version = match.group(1)
    if version != EXPECTED_CLAUDE_VERSION:
        fail(
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
        fail("normal-profile Claude authentication preflight failed")
    try:
        value = json.loads(result.stdout)
    except (ValueError, RecursionError):
        fail("normal-profile Claude authentication preflight was malformed")
    if not isinstance(value, dict):
        fail("normal-profile Claude authentication preflight was malformed")
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
        fail(
            "normal-profile Claude authentication is not the expected "
            "signed-in first-party Max subscription; refusing to open login"
        )
    return safe


def _installed_plugin(
    plugin: Path, *, environment: dict[str, str]
) -> tuple[dict, Path]:
    plugin = plugin.expanduser().absolute()
    if plugin.is_symlink() or not plugin.is_dir():
        fail(f"installed Claude plugin is missing or symlinked: {plugin}")
    skill = plugin / "SKILL.md"
    manifest_path = plugin / CLAUDE_MANIFEST_RELATIVE
    hook_path = plugin / CLAUDE_HOOKS_RELATIVE
    for label, path in (
        ("installed skill", skill),
        ("installed manifest", manifest_path),
        ("installed hook", hook_path),
    ):
        if path.is_symlink() or not path.is_file():
            fail(f"{label} is missing or symlinked")
    if skill.read_bytes() != CANONICAL_SKILL.read_bytes():
        fail("installed Claude skill differs from the canonical skill")
    manifest = read_json(manifest_path, "installed Claude manifest")
    if manifest != claude_plugin_manifest():
        fail("installed Claude manifest differs from the current contract")
    hook = read_json(hook_path, "installed Claude hook")
    try:
        command = hook["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    except (KeyError, IndexError, TypeError):
        fail("installed Claude hook shape is malformed")
    match = HOOK_COMMAND.fullmatch(command) if isinstance(command, str) else None
    if match is None:
        fail("installed Claude hook command is malformed")
    executable = Path(match.group(1))
    if not executable.is_absolute() or not executable.is_file():
        fail("installed Claude hook executable is missing or unsafe")
    if hook != claude_hooks(executable):
        fail("installed Claude hook differs from the current contract")
    version = _command(
        [str(executable), "--version"], cwd=ROOT, environment=environment
    )
    if version.returncode or version.stdout.strip() != f"glossabet {__version__}":
        fail("installed Claude hook executable has the wrong Glossabet version")
    return (
        {
            "path": "<HOME>/.claude/skills/glossabet",
            "tree_sha256": tree_sha256(plugin),
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
        fail("Claude plugin inventory was malformed")
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        fail("Claude plugin inventory was malformed")
    enabled = [item for item in records if item.get("enabled") is True]
    matches = [item for item in enabled if item.get("id") == "glossabet@skills-dir"]
    if len(matches) != 1:
        fail("Claude plugin inventory does not contain one enabled glossabet@skills-dir")
    install_path = matches[0].get("installPath")
    if not isinstance(install_path, str) or Path(install_path).resolve() != plugin.resolve():
        fail("Claude plugin inventory points Glossabet at another folder")
    safe_inventory: list[dict] = []
    for item in enabled:
        plugin_id = item.get("id")
        if not isinstance(plugin_id, str) or not plugin_id:
            fail("Claude plugin inventory contains an unnamed enabled plugin")
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
            fail(f"Claude plugin details did not report hook count for {plugin_id}")
        hooks = int(hook_match.group(1))
        hook_names = (hook_match.group(2) or "").strip()
        if plugin_id == "glossabet@skills-dir":
            if hooks != 1 or "SessionStart" not in hook_names:
                fail("Glossabet plugin does not expose exactly one SessionStart hook")
        elif hooks:
            fail(f"enabled plugin {plugin_id} has hooks that could contaminate the run")
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
        fail("this evidence plan is scoped to Linux")
    if not claude.is_file():
        fail(f"Claude executable is missing: {claude}")
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
        fail(result.stderr.strip() or result.stdout.strip() or "git failed")
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
        write_json(
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
        fail(f"unknown Claude fixture kind: {kind}")
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


def _scenario_errors(
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
        events = parse_events(result.stdout, limits)
    except ClaudeEvaluationError as exc:
        events = []
        parse_failure = str(exc)
    response, usage = structured_output(events)
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
        "prompt_sha256": sha256_text(scenario["prompt"]),
        "response": response,
        "observed": observed,
        "returncode": result.returncode,
        "stdout_sha256": sha256_text(result.stdout),
        "stderr": stderr,
        "stderr_sha256": sha256_text(result.stderr),
        "stderr_sanitized_sha256": sha256_text(stderr),
        "events": sanitized_events,
        "usage": usage,
    }
    return record, usage


def _owned_scratch(parent: Path) -> Path:
    parent = parent.resolve()
    if parent.is_symlink() or not parent.is_dir():
        fail(f"scratch parent is missing or symlinked: {parent}")
    return Path(tempfile.mkdtemp(prefix="glossabet-claude-eval-", dir=parent))


def _remove_owned_scratch(root: Path, parent: Path) -> bool:
    resolved_parent = parent.resolve()
    resolved_root = root.resolve()
    if (
        root.is_symlink()
        or resolved_root.parent != resolved_parent
        or not resolved_root.name.startswith("glossabet-claude-eval-")
    ):
        fail(f"refusing to remove unowned scratch path: {root}")
    shutil.rmtree(resolved_root)
    return not resolved_root.exists()


def run_evaluation(
    output: Path,
    *,
    claude: Path,
    installed_plugin: Path = DEFAULT_INSTALLED_PLUGIN,
    scratch_parent: Path = Path("/tmp"),
    environment: dict[str, str] | None = None,
) -> dict:
    manifest = load_manifest()
    schema = load_response_schema()
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
            raise ScratchCleanupFailed(
                "evaluator scratch cleanup failed: "
                f"{type(exc).__name__}: {str(exc) or 'no detail'}"
            ) from exc
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
        "inputs": input_identity(installed_plugin),
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
        "usage": usage_totals(usages),
        "cleanup_verified": cleanup_verified,
        "summary": summary,
    }
    write_new_json(output, result)
    return result


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
            fail("--output can be used only with --run")
        if args.current and args.verify_results is None:
            fail("--current can be used only with --verify-results")
        if args.run:
            if args.confirm_live_batch != LIVE_CONFIRMATION:
                fail(
                    "live Claude evaluation requires --confirm-live-batch "
                    f"{LIVE_CONFIRMATION} after fresh user authorization"
                )
            claude = args.claude or (
                Path(found) if (found := shutil.which("claude")) else None
            )
            if claude is None:
                fail("claude is not on PATH; refusing to open a login flow")
            attempt_id = new_attempt_id()
            output = validated_output(
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
                aborted = AbortedRun(
                    exc, cleanup_verified=not isinstance(exc, ScratchCleanupFailed)
                )
                try:
                    append_attempt(attempt_from_error(attempt_id, aborted))
                except Exception as append_exc:
                    print(
                        "Claude evaluation: failed to retain aborted attempt: "
                        f"{append_exc}",
                        file=sys.stderr,
                    )
                raise
            append_attempt(attempt_from_result(attempt_id, result, output))
            promote_current_result(output)
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
            attempts = read_json(HISTORY_PATH, "Claude attempt history")["attempts"]
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
