"""The live Claude Code host: a sanitized normal-profile environment,
version and authentication preflight, installed-plugin inspection, the
exact zero-tool ``claude`` command, output sanitization, and ownership of
the evaluator's scratch directory.

Authentication is reused, never created: no login command exists here.
Offline verification never imports this module.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from evaluation.claude.contract import (
    CANONICAL_SKILL,
    EXPECTED_CLAUDE_VERSION,
    HOOK_COMMAND,
    PROVIDER_ENV_KEYS,
    ROOT,
    fail,
    read_json,
    tree_sha256,
)
from evaluation.harness.io import file_sha256
from glossabet import __version__
from glossabet.install.claude_plugin import (
    CLAUDE_HOOKS_RELATIVE,
    CLAUDE_MANIFEST_RELATIVE,
    claude_hooks,
    claude_plugin_manifest,
)


def provider_environment_name(name: str) -> bool:
    return name in PROVIDER_ENV_KEYS or name.startswith("ANTHROPIC_")


def normal_profile_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    environment = dict(os.environ)
    for name in tuple(environment):
        if provider_environment_name(name):
            environment.pop(name)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["NO_COLOR"] = "1"
    if extra:
        environment.update(
            {
                name: value
                for name, value in extra.items()
                if not provider_environment_name(name)
            }
        )
    return environment


def safe_text(value: str, *roots: tuple[Path, str], limit: int = 2000) -> str:
    sanitized = value
    for path, replacement in roots:
        sanitized = sanitized.replace(str(path), replacement)
    sanitized = sanitized.replace(str(ROOT), "<REPO>")
    sanitized = sanitized.replace(str(Path.home()), "<HOME>")
    return sanitized if len(sanitized) <= limit else sanitized[:limit] + "…"


def run_command(
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


def require_success(
    result: subprocess.CompletedProcess[str], label: str, *, roots=()
) -> str:
    if result.returncode:
        detail = safe_text(result.stderr or result.stdout, *roots)
        fail(f"{label} exited {result.returncode}: {detail}")
    return result.stdout


def claude_version(
    claude: Path, *, environment: dict[str, str]
) -> str:
    result = run_command([str(claude), "--version"], cwd=ROOT, environment=environment)
    output = require_success(result, "claude --version").strip()
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


def auth_status(
    claude: Path, *, environment: dict[str, str]
) -> dict:
    result = run_command(
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


def inspect_installed_plugin(
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
    version = run_command(
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


def plugin_inventory(
    claude: Path,
    plugin: Path,
    *,
    environment: dict[str, str],
) -> list[dict]:
    validation = run_command(
        [str(claude), "plugin", "validate", str(plugin)],
        cwd=ROOT,
        environment=environment,
    )
    require_success(
        validation,
        "claude plugin validate",
        roots=((plugin, "<INSTALLED_PLUGIN>"),),
    )
    listing = run_command(
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
    output = require_success(listing, "claude plugin list")
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
        details = run_command(
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
        text = require_success(details, f"claude plugin details {plugin_id}")
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
    environment = normal_profile_environment(environment)
    if platform.system() != "Linux":
        fail("this evidence plan is scoped to Linux")
    if not claude.is_file():
        fail(f"Claude executable is missing: {claude}")
    version = claude_version(claude, environment=environment)
    auth = auth_status(claude, environment=environment)
    plugin_record, hook_executable = inspect_installed_plugin(
        installed_plugin, environment=environment
    )
    inventory = plugin_inventory(
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


def claude_command(
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


def sanitize_value(
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
        return safe_text(
            value,
            (workspace, "<WORKSPACE>"),
            limit=limit,
        )
    if isinstance(value, list):
        return [
            sanitize_value(item, workspace=workspace, limit=limit)
            for item in value
        ]
    if isinstance(value, dict):
        return {
            str(child_key): sanitize_value(
                child,
                workspace=workspace,
                limit=limit,
                key=str(child_key),
            )
            for child_key, child in value.items()
        }
    return value


def direct_brief(
    executable: Path,
    root: Path,
    *,
    environment: dict[str, str],
) -> str:
    result = run_command(
        [str(executable), "brief", "."],
        cwd=root,
        environment=environment,
    )
    return require_success(
        result,
        "installed Glossabet brief",
        roots=((root, "<WORKSPACE>"),),
    )


def owned_scratch(parent: Path) -> Path:
    parent = parent.resolve()
    if parent.is_symlink() or not parent.is_dir():
        fail(f"scratch parent is missing or symlinked: {parent}")
    return Path(tempfile.mkdtemp(prefix="glossabet-claude-eval-", dir=parent))


def remove_owned_scratch(root: Path, parent: Path) -> bool:
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
