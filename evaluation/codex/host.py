"""The live Codex host: command execution, version probing, the temporary
marketplace, plugin installation and removal, and the standalone-skill
shadow used for the missing-CLI scenario.

Everything here mutates real state — the user's Codex plugin registry, a
temporary marketplace, a cache directory under ``~/.codex`` — so the
progress of that mutation is tracked explicitly in ``PluginLifecycle`` and
cleanup removes exactly what was created. Offline verification never
imports this module.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from evaluation.codex.contract import (
    CANONICAL_SKILL,
    PLUGIN,
    PLUGIN_HOOK,
    RESPONSE_SCHEMA_PATH,
    ROOT,
    SENSITIVE_CANARY,
    fail,
    read_json,
    write_json,
)
from evaluation.codex.trace import command_items, parse_events
from evaluation.harness.io import dotenv_part
from glossabet import __version__
from glossabet.install.installer import default_skill_directory


@dataclass
class PluginLifecycle:
    """What the temporary plugin installation has created so far.

    Mutated in place as ``install_plugin`` progresses so that a failure at
    any point — including an operator interrupt — leaves the caller holding
    an exact record of what ``cleanup_plugin`` must remove. Exceptions are
    never annotated with this state.
    """

    marketplace_added: bool = False
    plugin_added: bool = False
    cache_parent: Path | None = None


def run_command(
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
        fail(f"command exited {result.returncode}: {shown}: {detail}")
    if not parse_json:
        return result.stdout
    try:
        value = json.loads(result.stdout)
    except (ValueError, RecursionError) as exc:
        fail(f"command returned malformed JSON: {shown}: {exc}")
    if not isinstance(value, dict):
        fail(f"command JSON was not an object: {shown}")
    return value


def codex_version(codex: str) -> str:
    result = subprocess.run(
        [codex, "--version"],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if result.returncode:
        fail(result.stderr.strip() or "could not run codex --version")
    match = re.search(r"codex-cli\s+([^\s]+)", result.stdout)
    if match is None:
        fail(f"unrecognized Codex version output: {result.stdout!r}")
    return match.group(1)


def competing_standalone_skill_paths(
    *, home: Path | None = None
) -> tuple[Path, ...]:
    """Return Glossabet's default standalone skill when it can shadow a plugin."""
    skill = default_skill_directory("codex", home=home) / "SKILL.md"
    return (skill.absolute(),) if skill.is_file() else ()


def disabled_skills_config(paths: tuple[Path, ...]) -> str | None:
    """Build a per-run Codex override without changing user-owned config."""
    normalized = sorted({str(path.absolute()) for path in paths})
    if not normalized:
        return None
    entries = ",".join(
        f"{{path={json.dumps(path)},enabled=false}}" for path in normalized
    )
    return f"skills.config=[{entries}]"


def codex_exec_command(
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
    skills_config = disabled_skills_config(disabled_skills)
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


def run_codex(
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
    command = codex_exec_command(
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
        fail("sensitive canary appeared in the Codex trace")
    if result.returncode:
        fail(
            f"codex exec exited {result.returncode}: "
            f"{result.stderr[-2000:] or result.stdout[-2000:]}"
        )
    events = parse_events(result.stdout, limits)
    response = read_json(final_path, "Codex final response")
    if SENSITIVE_CANARY in json.dumps(response):
        fail("sensitive canary appeared in the Codex final response")
    final_path.unlink()
    usage = next(
        (
            event.get("usage", {})
            for event in reversed(events)
            if event.get("type") == "turn.completed"
        ),
        {},
    )
    return response, command_items(events), usage


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    # Mirror _tree_sha256's exclusions so the installed bytes never exceed
    # what the digest-bound artifact claim covered.
    return {
        name for name in names if dotenv_part(name) or name == "__pycache__"
    }


def prepare_marketplace(root: Path, name: str) -> None:
    shutil.copytree(
        PLUGIN,
        root / "plugins" / "glossabet",
        ignore=_copy_ignore,
    )
    write_json(
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


def ensure_no_installed_glossabet(codex: str) -> None:
    data = run_command(
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
        fail("a Glossabet plugin is already installed; refusing to replace it")


def install_standalone_skill(destination: Path) -> None:
    run_command(
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
        fail("standalone installed skill differs from canonical source")
    if (destination / "scripts" / "run_glossabet.py").exists():
        fail("standalone missing-CLI scenario unexpectedly has a plugin runner")


def install_plugin(
    codex: str,
    marketplace: Path,
    marketplace_name: str,
    lifecycle: PluginLifecycle,
) -> tuple[str, Path]:
    """Register the temporary marketplace and install the plugin from it.

    Returns the plugin id and its installed path. ``lifecycle`` is advanced
    step by step so a failure part-way leaves it describing exactly the
    state that now exists, including the cache directory Codex leaves
    behind once ``plugin add`` has run.
    """
    plugin_id = f"glossabet@{marketplace_name}"
    added = run_command(
        [codex, "plugin", "marketplace", "add", str(marketplace), "--json"],
        cwd=ROOT,
        parse_json=True,
    )
    lifecycle.marketplace_added = True
    assert isinstance(added, dict)
    if added.get("marketplaceName") != marketplace_name:
        fail("Codex registered the temporary marketplace under another name")
    installed = run_command(
        [codex, "plugin", "add", plugin_id, "--json"],
        cwd=ROOT,
        parse_json=True,
    )
    lifecycle.plugin_added = True
    expected_cache = Path.home() / ".codex" / "plugins" / "cache"
    expected_parent = expected_cache / marketplace_name
    lifecycle.cache_parent = expected_parent
    assert isinstance(installed, dict)
    path = Path(str(installed.get("installedPath", "")))
    if (
        installed.get("version") != __version__
        or not path.is_absolute()
        or path.name != __version__
        or path.parent.name != "glossabet"
        or path.parents[1] != expected_parent
    ):
        fail(f"Codex returned an unexpected plugin installation: {installed}")
    runner = path / "skills" / "glossabet" / "scripts" / "run_glossabet.py"
    if not runner.is_file():
        fail("installed plugin has no skill-local runner")
    installed_hook = path / "hooks" / "hooks.json"
    if (
        installed_hook.is_symlink()
        or not installed_hook.is_file()
        or installed_hook.read_bytes() != PLUGIN_HOOK.read_bytes()
    ):
        fail("installed plugin has no exact session-start hook")
    return plugin_id, path


def cleanup_plugin(
    codex: str,
    plugin_id: str,
    marketplace_name: str,
    lifecycle: PluginLifecycle,
) -> None:
    """Remove exactly the state ``lifecycle`` records, then prove the plugin
    and marketplace are gone. Every narrowly scoped failure is kept and
    reported together."""
    errors = []
    if lifecycle.plugin_added:
        try:
            run_command(
                [codex, "plugin", "remove", plugin_id, "--json"],
                cwd=ROOT,
                parse_json=True,
            )
        except Exception as exc:  # preserve all narrowly scoped cleanup failures
            errors.append(str(exc))
    if lifecycle.marketplace_added:
        try:
            run_command(
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
    cache_parent = lifecycle.cache_parent
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
        plugin_data = run_command(
            [codex, "plugin", "list", "--json"],
            cwd=ROOT,
            parse_json=True,
        )
        marketplace_data = run_command(
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
        fail("; ".join(errors))
