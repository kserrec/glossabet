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
import secrets
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
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


_SCRATCH_PREFIX = "glossabet-claude-eval-"
_SCRATCH_MARKER = ".glossabet-evaluator-owned"


@dataclass(frozen=True)
class OwnedScratch:
    """One exact evaluator-created directory beneath one exact parent."""

    path: Path
    parent: Path
    identity: tuple[int, int]
    parent_identity: tuple[int, int]
    token: str


def _entry_identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _is_link_or_junction(info: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(
        reparse_flag and file_attributes & reparse_flag
    )


def _entry_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def owned_scratch(parent: Path) -> OwnedScratch:
    try:
        requested_info = parent.lstat()
    except OSError:
        fail(f"scratch parent is missing or uninspectable: {parent}")
    if _is_link_or_junction(requested_info) or not stat.S_ISDIR(
        requested_info.st_mode
    ):
        fail(f"scratch parent is missing, symlinked, or junctioned: {parent}")
    resolved_parent = parent.resolve()
    parent_info = resolved_parent.lstat()
    root = Path(
        tempfile.mkdtemp(prefix=_SCRATCH_PREFIX, dir=resolved_parent)
    )
    token = secrets.token_hex(32)
    with (root / _SCRATCH_MARKER).open("x", encoding="utf-8") as marker:
        marker.write(token)
    root_info = root.lstat()
    return OwnedScratch(
        path=root,
        parent=resolved_parent,
        identity=_entry_identity(root_info),
        parent_identity=_entry_identity(parent_info),
        token=token,
    )


def remove_owned_scratch(scratch: OwnedScratch) -> bool:
    """Remove only the same immediate child created by ``owned_scratch``.

    Python 3.10's cross-version ``onerror`` hook accepts a confined entry that
    vanished during deletion and retries a failed unlink/rmdir after clearing
    a Windows read-only bit. Symlinks and junctions are never
    permission-corrected, so a swapped entry cannot turn that retry into an
    operation on its target.
    """
    root = scratch.path
    parent = scratch.parent
    if root.parent != parent or not root.name.startswith(_SCRATCH_PREFIX):
        fail(f"refusing to remove scratch outside its owned parent: {root}")
    try:
        parent_info = parent.lstat()
    except OSError:
        fail(f"refusing cleanup after scratch parent changed: {parent}")
    if (
        _is_link_or_junction(parent_info)
        or not stat.S_ISDIR(parent_info.st_mode)
        or _entry_identity(parent_info) != scratch.parent_identity
    ):
        fail(f"refusing cleanup after scratch parent changed: {parent}")
    try:
        root_info = root.lstat()
    except FileNotFoundError:
        return True
    if (
        _is_link_or_junction(root_info)
        or not stat.S_ISDIR(root_info.st_mode)
        or _entry_identity(root_info) != scratch.identity
    ):
        fail(f"refusing to remove replaced evaluator scratch: {root}")
    marker = root / _SCRATCH_MARKER
    try:
        marker_info = marker.lstat()
    except OSError:
        fail(f"refusing to remove replaced evaluator scratch: {root}")
    if (
        _is_link_or_junction(marker_info)
        or not stat.S_ISREG(marker_info.st_mode)
        or marker_info.st_size != len(scratch.token)
    ):
        fail(f"refusing to remove replaced evaluator scratch: {root}")
    try:
        marker_value = marker.read_text(encoding="utf-8")
    except OSError:
        fail(f"refusing to remove replaced evaluator scratch: {root}")
    if marker_value != scratch.token:
        fail(f"refusing to remove replaced evaluator scratch: {root}")

    def retry_readonly_delete(
        function: Callable[..., object],
        path: str,
        exc_info: tuple[type[BaseException], BaseException, object],
    ) -> None:
        error = exc_info[1]
        if function not in {
            os.remove,
            os.rmdir,
            os.unlink,
        }:
            raise error
        candidate = Path(path)
        try:
            candidate.relative_to(root)
        except ValueError:
            raise error from None
        if isinstance(error, FileNotFoundError):
            return
        if not isinstance(error, PermissionError):
            raise error
        try:
            candidate_info = candidate.lstat()
        except OSError:
            raise error from None
        if _is_link_or_junction(candidate_info):
            raise error
        os.chmod(candidate, candidate_info.st_mode | stat.S_IWRITE)
        function(path)

    shutil.rmtree(root, onerror=retry_readonly_delete)
    return not _entry_exists(root)
