"""Composition of one live Codex evaluation.

``run_evaluation`` builds the fixtures, installs the plugin through the
host, runs the three bounded ``codex exec`` sessions, judges every
scenario, removes the temporary plugin state, and writes one result
document. Lifecycle state lives in this scope: an abort at any stage
becomes a typed ``AbortedRun`` record after cleanup, and the original
exception — including an operator interrupt — is re-raised unmodified.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from evaluation.codex.contract import (
    HOOK_PROMPT,
    PLUGIN_HOOK,
    PROMPT_PATH,
    RESULT_SCHEMA_VERSION,
    SCENARIOS_PATH,
    fail,
    read_json,
)
from evaluation.codex.fixtures import make_scenario, snapshot
from evaluation.codex.history import (
    AbortedRun,
    FailedStage,
    append_attempt,
    attempt_from_error,
    attempt_from_probe_error,
)
from evaluation.codex.host import (
    PluginLifecycle,
    cleanup_plugin,
    codex_version,
    competing_standalone_skill_paths,
    ensure_no_installed_glossabet,
    install_plugin,
    install_standalone_skill,
    prepare_marketplace,
    run_codex,
)
from evaluation.codex.results import input_identity
from evaluation.codex.scenarios import (
    accepted_statuses,
    evaluate_scenario,
    evaluate_session_hook,
    response_by_id,
    validate_manifest,
)
from evaluation.codex.trace import installed_version_command, trace_summary
from evaluation.harness.io import file_sha256


def _locate_codex() -> str:
    codex = shutil.which("codex")
    if codex is None:
        fail("codex is not installed")
    return str(Path(codex).resolve())


def prompt_for(scenarios: list[dict], roots: dict[str, Path]) -> str:
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


def run_missing_cli_scenario(
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
    install_standalone_skill(
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
    response, commands, usage = run_codex(
        codex,
        workspace=missing_root,
        prompt=prompt_for([scenario], {"missing-cli": missing_root}),
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
    codex = _locate_codex()
    disabled_skills = competing_standalone_skill_paths()
    with tempfile.TemporaryDirectory(prefix="glossabet-missing-cli-probe-") as raw:
        result, usage = run_missing_cli_scenario(
            codex,
            scenario,
            limits,
            Path(raw),
            disabled_skills=disabled_skills,
        )
    return {
        "codex_version": codex_version(codex),
        "scenario": result,
        "usage": usage,
    }


def run_recorded_probe(attempt_id: str) -> dict:
    """Run the focused missing-CLI probe and retain its attempt either way."""
    try:
        probe = probe_missing_cli()
    except Exception as exc:
        append_attempt(attempt_from_probe_error(attempt_id, AbortedRun(exc)))
        raise
    return probe


@dataclass
class _PluginBatch:
    """Everything the plugin-delivered host sessions produce."""

    results: list[dict] = field(default_factory=list)
    usages: list[dict] = field(default_factory=list)
    hook_result: dict | None = None
    delivery_trace: list[dict] = field(default_factory=list)
    delivery_trace_truncated: bool = False


def _run_hook_session(
    codex: str,
    hook_scenario: dict,
    work: Path,
    limits: dict,
    disabled_skills: tuple[Path, ...],
    batch: _PluginBatch,
) -> None:
    hook_root = work / "session-hook-run"
    make_scenario(hook_root, "session-hook")
    hook_before = snapshot(hook_root)
    hook_environment = {
        **os.environ,
        "GLOSSABET_CACHE_DIR": str(work / ".hook-engine-cache"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    hook_response, hook_commands, hook_usage = run_codex(
        codex,
        workspace=hook_root,
        prompt=HOOK_PROMPT,
        environment=hook_environment,
        limits=limits,
        disabled_skills=disabled_skills,
        bypass_hook_trust=True,
    )
    batch.usages.append(hook_usage)
    hook_response_items = response_by_id(hook_response, ["session-hook"])
    batch.hook_result = evaluate_session_hook(
        hook_scenario,
        root=hook_root,
        commands=hook_commands,
        response=hook_response_items["session-hook"],
        before=hook_before,
        workspace=hook_root,
        limits=limits,
    )
    batch.results.append(batch.hook_result)


def _run_plugin_session(
    codex: str,
    plugin_scenarios: list[dict],
    work: Path,
    installed_path: Path,
    limits: dict,
    disabled_skills: tuple[Path, ...],
    batch: _PluginBatch,
) -> None:
    workspace = work / "plugin-run"
    roots = {
        scenario["id"]: workspace / "scenarios" / scenario["id"]
        for scenario in plugin_scenarios
    }
    before = {}
    for scenario in plugin_scenarios:
        root = roots[scenario["id"]]
        make_scenario(root, scenario["id"])
        before[scenario["id"]] = snapshot(root)
    environment = {
        **os.environ,
        "GLOSSABET_CACHE_DIR": str(workspace / ".engine-cache"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    response, commands, usage = run_codex(
        codex,
        workspace=workspace,
        prompt=prompt_for(plugin_scenarios, roots),
        environment=environment,
        limits=limits,
        disabled_skills=disabled_skills,
        bypass_hook_trust=True,
    )
    batch.usages.append(usage)
    version_command = installed_version_command(
        commands,
        installed_path=installed_path,
        workspace=workspace,
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
        trace_summary(command, workspace, limits, trace_aliases)
        for command in commands
        if command in glossabet_skill_reads
        and command is not version_command
    ]
    allowed_reads = max(0, limits["commands_per_scenario"] - 1)
    batch.delivery_trace = [
        trace_summary(version_command, workspace, limits, trace_aliases)
    ] + skill_read_summaries[:allowed_reads]
    batch.delivery_trace_truncated = len(skill_read_summaries) > allowed_reads
    response_items = response_by_id(
        response, [scenario["id"] for scenario in plugin_scenarios]
    )
    for scenario in plugin_scenarios:
        scenario_id = scenario["id"]
        batch.results.append(evaluate_scenario(
            scenario,
            root=roots[scenario_id],
            commands=commands,
            response=response_items[scenario_id],
            before=before[scenario_id],
            workspace=workspace,
            limits=limits,
            trace_aliases=trace_aliases,
        ))


def _run_plugin_batch(
    codex: str,
    scenarios: list[dict],
    work: Path,
    limits: dict,
    disabled_skills: tuple[Path, ...],
) -> tuple[_PluginBatch, BaseException | None, FailedStage, bool, str | None]:
    """Install the temporary plugin, run the hook and plugin sessions, and
    always clean up. Returns the batch, the primary error if any, the stage
    it failed at, whether cleanup was verified, and any secondary cleanup
    diagnostic that must not replace the primary failure."""
    plugin_scenarios = [
        scenario for scenario in scenarios if scenario["delivery"] == "plugin"
    ]
    hook_scenario = next(
        scenario for scenario in scenarios if scenario["id"] == "session-hook"
    )
    marketplace_name = f"glossabet-agent-eval-{uuid.uuid4().hex[:12]}"
    marketplace = work / "marketplace"
    prepare_marketplace(marketplace, marketplace_name)
    plugin_id = f"glossabet@{marketplace_name}"
    lifecycle = PluginLifecycle()
    batch = _PluginBatch()
    primary_error: BaseException | None = None
    cleanup_verified = False
    cleanup_error: str | None = None
    stage: FailedStage = "plugin-preflight"
    try:
        plugin_id, installed_path = install_plugin(
            codex, marketplace, marketplace_name, lifecycle
        )
        stage = "plugin-scenarios"
        _run_hook_session(
            codex, hook_scenario, work, limits, disabled_skills, batch
        )
        _run_plugin_session(
            codex,
            plugin_scenarios,
            work,
            installed_path,
            limits,
            disabled_skills,
            batch,
        )
    except BaseException as exc:
        # BaseException so an operator interrupt still records its
        # cleanup outcome and attempt instead of vanishing.
        primary_error = exc
    finally:
        try:
            cleanup_plugin(codex, plugin_id, marketplace_name, lifecycle)
            cleanup_verified = True
        except Exception as cleanup_exc:
            if primary_error is None:
                primary_error = cleanup_exc
            else:
                cleanup_error = (
                    "secondary cleanup failure: "
                    f"{type(cleanup_exc).__name__}: "
                    f"{str(cleanup_exc) or 'no detail'}"
                )
    return batch, primary_error, stage, cleanup_verified, cleanup_error


def _assemble_result(
    *,
    inputs: dict,
    version: str,
    limits: dict,
    scenarios: list[dict],
    batch: _PluginBatch,
    missing_result: dict,
) -> dict:
    ordered = {result["id"]: result for result in batch.results}
    results = [ordered[scenario["id"]] for scenario in scenarios]
    passed = sum(result["passed"] for result in results)
    hook_observed = (
        batch.hook_result.get("observed", {})
        if batch.hook_result is not None
        else {}
    )
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "inputs": inputs,
        "environment": {
            "codex_version": version,
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
                batch.hook_result is not None
                and hook_observed.get("canonical_term_seen") is True
                and hook_observed.get("canonical_definition_seen") is True
            ),
            "session_start_user_prompt_mentions_glossabet": False,
            "standalone_skill_boundary_observed": missing_result.get(
                "observed", {}
            ).get("standalone_skill_boundary_observed")
            is True,
            "temporary_plugin_state_removed": True,
            "trace": batch.delivery_trace,
            "trace_truncated": batch.delivery_trace_truncated,
        },
        "usage": batch.usages,
        "scenarios": results,
        "summary": {
            "required": len(scenarios),
            "passed": passed,
            "failed": len(scenarios) - passed,
            "all_passed": passed == len(scenarios),
        },
    }


def _execute_evaluation(output: Path) -> dict:
    manifest = read_json(SCENARIOS_PATH, "agent scenario manifest")
    scenarios, limits = validate_manifest(manifest)
    codex = _locate_codex()
    version = codex_version(codex)
    # The identity must describe the bytes this run consumes; computing it
    # after the host runs would bind the evidence to whatever the tree
    # contains by then.
    inputs = input_identity()
    disabled_skills = competing_standalone_skill_paths()
    ensure_no_installed_glossabet(codex)
    missing_scenario = next(
        scenario for scenario in scenarios if scenario["id"] == "missing-cli"
    )

    with tempfile.TemporaryDirectory(prefix="glossabet-agent-eval-") as raw:
        work = Path(raw)
        (
            batch,
            primary_error,
            stage,
            cleanup_verified,
            cleanup_error,
        ) = _run_plugin_batch(codex, scenarios, work, limits, disabled_skills)
        if primary_error is not None:
            raise _Aborted(
                AbortedRun(
                    primary_error,
                    failed_stage=stage,
                    cleanup_verified=cleanup_verified,
                    usage=batch.usages,
                    cleanup_error=cleanup_error,
                )
            )
        try:
            missing_result, missing_usage = run_missing_cli_scenario(
                codex,
                missing_scenario,
                limits,
                work,
                disabled_skills=disabled_skills,
            )
        except BaseException as exc:
            raise _Aborted(
                AbortedRun(exc, "missing-cli", cleanup_verified, batch.usages)
            ) from exc
        batch.usages.append(missing_usage)
        batch.results.append(missing_result)

    result = _assemble_result(
        inputs=inputs,
        version=version,
        limits=limits,
        scenarios=scenarios,
        batch=batch,
        missing_result=missing_result,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


class _Aborted(BaseException):
    """Internal carrier from the run scope to the recording scope.

    A ``BaseException`` so an interrupt's record is not swallowed by an
    ``except Exception``; the public runner boundaries re-raise the original
    error.
    """

    def __init__(self, aborted: AbortedRun) -> None:
        super().__init__(str(aborted.error))
        self.aborted = aborted


def _report_secondary_cleanup(aborted: AbortedRun) -> None:
    if aborted.cleanup_error is not None:
        print(f"agent evaluation: {aborted.cleanup_error}", file=sys.stderr)


def run_evaluation(output: Path) -> dict:
    """Run the full installed-plugin evaluation and write ``output``.

    Raises the original first failure after the temporary plugin state has
    been removed; use ``run_recorded_evaluation`` to also retain the attempt.
    """
    try:
        return _execute_evaluation(output)
    except _Aborted as carrier:
        aborted = carrier.aborted
        _report_secondary_cleanup(aborted)
        raise aborted.error from None


def run_recorded_evaluation(output: Path, attempt_id: str) -> dict:
    """Run the evaluation and retain the attempt whether or not it completes.

    On abort, the typed record is appended first and the original exception
    is then re-raised unmodified. Errors raised before the host lifecycle
    begins are recorded with the same defaults as before.
    """
    try:
        return _execute_evaluation(output)
    except _Aborted as carrier:
        aborted = carrier.aborted
    except BaseException as exc:
        aborted = AbortedRun(exc)
    _report_secondary_cleanup(aborted)
    try:
        append_attempt(attempt_from_error(attempt_id, aborted))
    except Exception as append_exc:
        print(
            "agent evaluation: failed to record the aborted "
            f"attempt: {append_exc}",
            file=sys.stderr,
        )
    raise aborted.error from None
