"""Composition of one live Claude evaluation: preflight, three bounded
host calls in an owned scratch directory, judgment, guaranteed scratch
removal, and one write-once result document.

An abort at any point becomes a typed ``AbortedRun`` built in this scope;
the original exception — including an operator interrupt — is re-raised
unmodified after the attempt has been retained.
"""

from __future__ import annotations

import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from evaluation.claude.contract import (
    DEFAULT_INSTALLED_PLUGIN,
    RESULT_SCHEMA_VERSION,
    SCENARIO_IDS,
    ClaudeEvaluationError,
    ScratchCleanupFailed,
    load_manifest,
    load_response_schema,
    sha256_text,
    write_new_json,
)
from evaluation.claude.events import parse_events, structured_output
from evaluation.claude.fixtures import create_fixture, snapshot
from evaluation.claude.history import (
    AbortedRun,
    append_attempt,
    attempt_from_error,
    usage_totals,
)
from evaluation.claude.host import (
    claude_command,
    direct_brief,
    normal_profile_environment,
    owned_scratch,
    preflight,
    remove_owned_scratch,
    run_command,
    safe_text,
    sanitize_value,
)
from evaluation.claude.results import input_identity
from evaluation.claude.scenarios import scenario_errors
from evaluation.harness.io import changed_paths


def run_scenario(
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
    before = snapshot(root)
    brief_text = direct_brief(hook_executable, root, environment=environment)
    after_brief = snapshot(root)
    brief_writes = changed_paths(before, after_brief)
    command = claude_command(claude, scenario, manifest, schema)
    result = run_command(
        command,
        cwd=root,
        environment=environment,
        timeout=600,
    )
    after = snapshot(root)
    unexpected_writes = sorted(set(brief_writes + changed_paths(after_brief, after)))
    parse_failure: str | None = None
    try:
        events = parse_events(result.stdout, limits)
    except ClaudeEvaluationError as exc:
        events = []
        parse_failure = str(exc)
    response, usage = structured_output(events)
    failures, observed = scenario_errors(
        scenario,
        response=response,
        events=events,
        direct_brief=brief_text,
        unexpected_writes=unexpected_writes,
        returncode=result.returncode,
    )
    if parse_failure:
        failures.insert(0, parse_failure)
    sanitized_events = [
        sanitize_value(
            event,
            workspace=root,
            limit=limits["stored_string_characters"],
        )
        for event in events
    ]
    stderr = safe_text(
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


class _Aborted(BaseException):
    """Carry explicit lifecycle state without altering the primary error."""

    def __init__(self, aborted: AbortedRun) -> None:
        super().__init__(str(aborted.error))
        self.aborted = aborted


def _cleanup_failure(exc: BaseException) -> ScratchCleanupFailed:
    return ScratchCleanupFailed(
        "evaluator scratch cleanup failed: "
        f"{type(exc).__name__}: {str(exc) or 'no detail'}"
    )


def _report_secondary_cleanup(aborted: AbortedRun) -> None:
    if aborted.cleanup_error is not None:
        print(f"Claude evaluation: {aborted.cleanup_error}", file=sys.stderr)


def _execute_evaluation(
    output: Path,
    *,
    claude: Path,
    installed_plugin: Path = DEFAULT_INSTALLED_PLUGIN,
    scratch_parent: Path = Path("/tmp"),
    environment: dict[str, str] | None = None,
) -> dict:
    manifest = load_manifest()
    schema = load_response_schema()
    environment = normal_profile_environment(environment)
    preflight_record, hook_executable = preflight(
        claude,
        installed_plugin,
        environment=environment,
    )
    scratch = owned_scratch(scratch_parent)
    work = scratch.path
    results: list[dict] = []
    usages: list[dict] = []
    cleanup_verified = False
    primary_error: BaseException | None = None
    cleanup_error: str | None = None
    try:
        for scenario in manifest["scenarios"]:
            root = work / scenario["id"]
            create_fixture(root, scenario["fixture"])
            scenario_environment = {
                **environment,
                "GLOSSABET_CACHE_DIR": str(work / ".glossabet-cache"),
            }
            result, usage = run_scenario(
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
    except BaseException as exc:
        primary_error = exc
    try:
        cleanup_verified = remove_owned_scratch(scratch)
        if not cleanup_verified:
            raise OSError("owned evaluator scratch path remains")
    except BaseException as exc:
        cleanup_verified = False
        if primary_error is None:
            primary_error = (
                exc
                if isinstance(exc, KeyboardInterrupt)
                else _cleanup_failure(exc)
            )
        else:
            cleanup_error = (
                "secondary cleanup failure: "
                f"{type(exc).__name__}: {str(exc) or 'no detail'}"
            )
    if primary_error is not None:
        raise _Aborted(
            AbortedRun(
                primary_error,
                cleanup_verified=cleanup_verified,
                cleanup_error=cleanup_error,
            )
        )
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


def run_evaluation(
    output: Path,
    *,
    claude: Path,
    installed_plugin: Path = DEFAULT_INSTALLED_PLUGIN,
    scratch_parent: Path = Path("/tmp"),
    environment: dict[str, str] | None = None,
) -> dict:
    try:
        return _execute_evaluation(
            output,
            claude=claude,
            installed_plugin=installed_plugin,
            scratch_parent=scratch_parent,
            environment=environment,
        )
    except _Aborted as carrier:
        aborted = carrier.aborted
        _report_secondary_cleanup(aborted)
        raise aborted.error from None


def run_recorded_evaluation(
    output: Path,
    attempt_id: str,
    *,
    claude: Path,
    installed_plugin: Path,
    scratch_parent: Path,
) -> dict:
    """Run the batch and retain the attempt whether or not it completes.

    On abort the typed record is appended first; the original exception is
    then re-raised unmodified.
    """
    try:
        return _execute_evaluation(
            output,
            claude=claude,
            installed_plugin=installed_plugin,
            scratch_parent=scratch_parent,
        )
    except _Aborted as carrier:
        aborted = carrier.aborted
    except BaseException as exc:
        aborted = AbortedRun(exc)
    _report_secondary_cleanup(aborted)
    try:
        append_attempt(attempt_from_error(attempt_id, aborted))
    except Exception as append_exc:
        print(
            "Claude evaluation: failed to retain aborted attempt: "
            f"{append_exc}",
            file=sys.stderr,
        )
    raise aborted.error from None
