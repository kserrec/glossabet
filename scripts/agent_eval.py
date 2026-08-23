#!/usr/bin/env python3
"""Run and verify bounded installed-skill scenarios through real Codex exec."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.codex.contract import (  # noqa: E402
    CANONICAL_SKILL,
    DEFAULT_RESULTS,
    HOOK_PROMPT,
    PLUGIN,
    PLUGIN_HOOK,
    PROMPT_PATH,
    RESPONSE_SCHEMA_PATH,
    RESULT_SCHEMA_VERSION,
    RUNS_PATH,
    SCENARIOS_PATH,
    SENSITIVE_CANARY,
    AgentEvaluationError,
    fail,
    read_json,
    write_json,
)
from evaluation.codex.fixtures import make_scenario, snapshot  # noqa: E402
from evaluation.codex.history import (  # noqa: E402
    append_attempt,
    attempt_from_error,
    attempt_from_probe,
    attempt_from_probe_error,
    attempt_from_result,
    new_attempt_id,
    promote_current_result,
    refresh_artifact_record,
    validated_run_output,
)
from evaluation.codex.results import input_identity, verify_results  # noqa: E402
from evaluation.codex.scenarios import (  # noqa: E402
    accepted_statuses,
    evaluate_scenario,
    evaluate_session_hook,
    response_by_id,
    validate_manifest,
)
from evaluation.codex.trace import (  # noqa: E402
    command_items,
    installed_version_command,
    parse_events,
    trace_summary,
)
from evaluation.harness.io import (  # noqa: E402
    dotenv_part,
    file_sha256,
)
from glossabet import __version__  # noqa: E402
from glossabet.install.installer import default_skill_directory  # noqa: E402


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


def _codex_version(codex: str) -> str:
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


def _prepare_marketplace(root: Path, name: str) -> None:
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
        fail("a Glossabet plugin is already installed; refusing to replace it")


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
            fail("Codex registered the temporary marketplace under another name")
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
        fail("; ".join(errors))


def _prompt_for(scenarios: list[dict], roots: dict[str, Path]) -> str:
    supplied = [
        {
            "id": scenario["id"],
            "path": str(roots[scenario["id"]]),
            "description": scenario["description"],
            "allowed_statuses": accepted_statuses(scenario),
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
        fail("standalone installed skill differs from canonical source")
    if (destination / "scripts" / "run_glossabet.py").exists():
        fail("standalone missing-CLI scenario unexpectedly has a plugin runner")


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
    make_scenario(missing_root, "missing-cli")
    _install_standalone_skill(
        missing_root / ".agents" / "skills" / "glossabet"
    )
    missing_before = snapshot(missing_root)
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
    response_items = response_by_id(response, ["missing-cli"])
    result = evaluate_scenario(
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
    manifest = read_json(SCENARIOS_PATH, "agent scenario manifest")
    scenarios, limits = validate_manifest(manifest)
    scenario = next(item for item in scenarios if item["id"] == "missing-cli")
    codex = shutil.which("codex")
    if codex is None:
        fail("codex is not installed")
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
    manifest = read_json(SCENARIOS_PATH, "agent scenario manifest")
    scenarios, limits = validate_manifest(manifest)
    codex = shutil.which("codex")
    if codex is None:
        fail("codex is not installed")
    codex = str(Path(codex).resolve())
    codex_version = _codex_version(codex)
    # The identity must describe the bytes this run consumes; computing it
    # after the host runs would bind the evidence to whatever the tree
    # contains by then.
    inputs = input_identity()
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
            make_scenario(root, scenario["id"])
            before[scenario["id"]] = snapshot(root)
        environment = {
            **os.environ,
            "GLOSSABET_CACHE_DIR": str(batch / ".engine-cache"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        hook_root = work / "session-hook-run"
        make_scenario(hook_root, "session-hook")
        hook_before = snapshot(hook_root)
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
            hook_response_items = response_by_id(
                hook_response, ["session-hook"]
            )
            hook_result = evaluate_session_hook(
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
            version_command = installed_version_command(
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
                fail("Codex did not read the temporarily installed plugin skill")
            if any(
                str(installed_skill) not in command["command"]
                for command in glossabet_skill_reads
            ):
                fail("Codex read a different Glossabet skill during the plugin run")
            trace_aliases = ((str(installed_path), "<INSTALLED_PLUGIN>"),)
            skill_read_summaries = [
                trace_summary(command, batch, limits, trace_aliases)
                for command in commands
                if command in glossabet_skill_reads
                and command is not version_command
            ]
            allowed_reads = max(0, limits["commands_per_scenario"] - 1)
            delivery_trace = [
                trace_summary(version_command, batch, limits, trace_aliases)
            ] + skill_read_summaries[:allowed_reads]
            delivery_trace_truncated = len(skill_read_summaries) > allowed_reads
            response_items = response_by_id(
                response, [scenario["id"] for scenario in plugin_scenarios]
            )
            for scenario in plugin_scenarios:
                scenario_id = scenario["id"]
                results.append(evaluate_scenario(
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
            primary_error.cleanup_verified = cleanup_verified
            primary_error.attempt_usage = usages
            primary_error.failed_stage = stage
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
            exc.cleanup_verified = cleanup_verified
            exc.attempt_usage = usages
            exc.failed_stage = stage
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
            "installed_plugin_hook_sha256": file_sha256(PLUGIN_HOOK),
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
            fail("--output can be used only with --run")
        if args.current and args.verify_results is None:
            fail("--current can be used only with --verify-results")
        if args.run:
            attempt_id = new_attempt_id("full")
            output = validated_run_output(
                args.output or RUNS_PATH / f"{attempt_id}.json"
            )
            try:
                result = run_evaluation(output)
            except BaseException as exc:
                try:
                    append_attempt(attempt_from_error(attempt_id, exc))
                except Exception as append_exc:
                    print(
                        "agent evaluation: failed to record the aborted "
                        f"attempt: {append_exc}",
                        file=sys.stderr,
                    )
                raise
            append_attempt(attempt_from_result(attempt_id, result, output))
            promote_current_result(output)
            summary = result["summary"]
            print(
                f"installed-agent evaluation: {summary['passed']}/"
                f"{summary['required']} scenarios passed"
            )
            return 0 if summary["all_passed"] else 1
        if args.probe_missing_cli:
            attempt_id = new_attempt_id("missing-cli")
            try:
                probe = probe_missing_cli()
            except Exception as exc:
                append_attempt(attempt_from_probe_error(attempt_id, exc))
                raise
            append_attempt(attempt_from_probe(attempt_id, probe))
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
            artifact = refresh_artifact_record()
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
