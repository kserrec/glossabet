"""Installed Codex boundary evidence is current, bounded, and fail-closed."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

import scripts.agent_eval as agent_eval
from scripts.agent_eval import (
    AgentEvaluationError,
    HOOK_DEFINITION,
    HOOK_PROMPT,
    HOOK_PROPOSED_TERM,
    HOOK_SOURCE_CANARY,
    HOOK_TERM,
    _append_attempt,
    _artifact_errors,
    _artifact_snapshot,
    _attempt_from_error,
    _attempt_from_probe_error,
    _codex_exec_command,
    _competing_standalone_skill_paths,
    _disabled_skills_config,
    _evaluate_scenario,
    _evaluate_session_hook,
    _history_errors,
    _history_summary,
    _installed_version_command,
    _make_scenario,
    _promote_current_result,
    _raw_result_record,
    _result_input_errors,
    _run_missing_cli_scenario,
    _snapshot,
    _tree_sha256,
    _usage_totals,
    _validated_run_output,
    verify_results,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evaluation" / "agent-scenarios.json"
PROMPT = ROOT / "evaluation" / "agent-prompt.md"
RESULTS = ROOT / "evaluation" / "agent-results.json"
HISTORY = ROOT / "evaluation" / "agent-history.json"


def test_agent_manifest_covers_every_phase_22_boundary():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert [scenario["id"] for scenario in manifest["scenarios"]] == [
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
    ]
    sensitive = manifest["scenarios"][-3]
    assert sensitive["accepted_statuses"] == [
        "grounded",
        "grounded-with-warning",
    ]
    hook = manifest["scenarios"][-2]
    assert hook["delivery"] == "plugin-hook"
    assert hook["expected_status"] == "grounded"


def test_session_hook_prompt_does_not_supply_the_answer_or_product_name():
    normalized = " ".join(HOOK_PROMPT.split())

    assert "glossabet" not in normalized.casefold()
    assert HOOK_TERM not in normalized
    assert HOOK_DEFINITION not in normalized
    assert HOOK_PROPOSED_TERM not in normalized
    assert "Do not run commands, call tools, inspect files" in normalized


def test_session_hook_scenario_requires_ambient_context_without_commands(tmp_path):
    root = tmp_path / "session-hook"
    _make_scenario(root, "session-hook")
    before = _snapshot(root)
    scenario = {
        "id": "session-hook",
        "delivery": "plugin-hook",
        "expected_status": "grounded",
    }

    result = _evaluate_session_hook(
        scenario,
        root=root,
        commands=[],
        response={
            "id": "session-hook",
            "status": "grounded",
            "facts": [f"{HOOK_TERM} — {HOOK_DEFINITION}"],
            "next_action": "Use the settled term in future work.",
        },
        before=before,
        workspace=tmp_path,
        limits={
            "stored_command_characters": 1200,
            "stored_output_characters": 600,
        },
    )

    assert result["passed"] is True
    assert result["unexpected_writes"] == []
    assert result["observed"] == {
        "agent_command_count": 0,
        "canonical_term_seen": True,
        "canonical_definition_seen": True,
        "proposed_term_absent": True,
        "source_text_absent": True,
        "user_prompt_mentions_glossabet": False,
        "user_prompt_sha256": hashlib.sha256(HOOK_PROMPT.encode()).hexdigest(),
    }
    assert HOOK_SOURCE_CANARY not in json.dumps(result)


def test_current_result_identity_must_match_every_bound_input(
    monkeypatch,
):
    current = {"plugin_sha256": "1" * 64, "engine_version": "0.1.0"}
    monkeypatch.setattr(agent_eval, "_input_identity", lambda: current)
    stale = deepcopy(current)
    stale["plugin_sha256"] = "0" * 64

    assert _result_input_errors({"inputs": current}) == []
    assert _result_input_errors({"inputs": stale}) == [
        "agent result input identity is stale"
    ]


def test_committed_installed_agent_evidence_is_current_safe_and_complete():
    assert verify_results(RESULTS) == []
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    assert results["summary"] == {
        "required": 12,
        "passed": 12,
        "failed": 0,
        "all_passed": True,
    }
    assert history["summary"] == {
        "attempts": 11,
        "missing_cli_boundary": {
            "attempted": 10,
            "failed": 2,
            "passed": 8,
        },
        "plugin_preflight": {
            "attempted": 8,
            "failed": 1,
            "passed": 7,
        },
        "plugin_scenarios": {
            "attempted": 7,
            "failed": 0,
            "passed": 7,
        },
        "procedural": {"failed": 3, "passed": 8},
        "raw_results_retained": 6,
        "safety": {"failed": 0, "passed": 11},
    }
    assert history["current_artifact"] == _artifact_snapshot()
    assert _artifact_errors(history["current_artifact"]) == []
    assert results["delivery"]["installed_plugin_skill_read"] is True
    assert results["delivery"]["session_start_hook_context_seen"] is True
    assert results["delivery"]["temporary_plugin_state_removed"] is True
    hook = next(
        item for item in results["scenarios"] if item["id"] == "session-hook"
    )
    assert hook["passed"] is True
    assert hook["trace"] == []
    assert hook["unexpected_writes"] == []
    assert hook["observed"] == {
        "agent_command_count": 0,
        "canonical_definition_seen": True,
        "canonical_term_seen": True,
        "proposed_term_absent": True,
        "source_text_absent": True,
        "user_prompt_mentions_glossabet": False,
        "user_prompt_sha256": hashlib.sha256(HOOK_PROMPT.encode()).hexdigest(),
    }
    missing_cli = next(
        item for item in results["scenarios"] if item["id"] == "missing-cli"
    )
    assert missing_cli["passed"] is True
    assert missing_cli["unexpected_writes"] == []
    assert all("inspect" not in item["command"] for item in missing_cli["trace"])
    sensitive = next(
        item for item in results["scenarios"] if item["id"] == "sensitive-file"
    )
    assert sensitive["observed"]["sensitive_paths"] == [
        ".env",
        "api-secret.txt",
    ]
    assert sensitive["unexpected_writes"] == []
    latest_raw = ROOT / history["attempts"][-1]["raw_result"]["path"]
    assert RESULTS.read_bytes() == latest_raw.read_bytes()


def test_attempt_history_retains_failures_without_turning_them_into_the_gate():
    history = json.loads(HISTORY.read_text(encoding="utf-8"))

    assert _history_errors(result_path=RESULTS) == []
    assert [
        attempt["id"]
        for attempt in history["attempts"]
        if not attempt["procedural_pass"]
    ] == [
        "20260816-full-metadata-rebuild",
        "20260816-full-current-artifact-preflight",
        "20260816T192615Z-full-e73a0e21",
    ]
    assert [
        attempt["evidence_basis"] for attempt in history["attempts"]
    ].count("retained-raw-result") == 6


def test_current_result_must_match_retained_raw_bytes(tmp_path):
    unretained_copy = tmp_path / "unretained-copy.json"
    unretained_copy.write_bytes(RESULTS.read_bytes())

    assert any(
        "not retained by the attempt history" in error
        for error in _history_errors(result_path=unretained_copy)
    )


def test_promote_current_result_preserves_exact_raw_bytes(monkeypatch, tmp_path):
    raw = tmp_path / "raw.json"
    raw.write_bytes(b'{"raw": true}\n')
    current = tmp_path / "current.json"
    current.write_bytes(b'{"old": true}\n')
    monkeypatch.setattr(agent_eval, "DEFAULT_RESULTS", current)

    _promote_current_result(raw)

    assert current.read_bytes() == raw.read_bytes()


def test_attempt_history_rejects_stale_artifact_or_safety_claim(tmp_path):
    original = json.loads(HISTORY.read_text(encoding="utf-8"))

    stale_artifact = deepcopy(original)
    stale_artifact["current_artifact"]["wheel_sha256"] = "0" * 64
    stale_path = tmp_path / "stale-artifact.json"
    stale_path.write_text(json.dumps(stale_artifact), encoding="utf-8")
    assert "current deterministic plugin artifact identity is stale" in (
        _history_errors(stale_path)
    )

    unsafe = deepcopy(original)
    unsafe["attempts"][0]["safety_pass"] = False
    unsafe["summary"] = _history_summary(unsafe["attempts"])
    unsafe_path = tmp_path / "unsafe.json"
    unsafe_path.write_text(json.dumps(unsafe), encoding="utf-8")
    assert any(
        "records a safety failure" in error
        for error in _history_errors(unsafe_path)
    )


def test_attempt_history_rejects_rewritten_raw_evidence(tmp_path):
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    retained = next(
        attempt for attempt in history["attempts"] if attempt["raw_result"]
    )
    retained["raw_result"]["sha256"] = "0" * 64
    path = tmp_path / "rewritten-raw.json"
    path.write_text(json.dumps(history), encoding="utf-8")

    assert any(
        "raw result digest is stale" in error
        for error in _history_errors(path)
    )


def test_append_attempt_preserves_every_prior_record(monkeypatch, tmp_path):
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    path = tmp_path / "agent-history.json"
    path.write_text(json.dumps(history), encoding="utf-8")
    monkeypatch.setattr(agent_eval, "HISTORY_PATH", path)
    before = deepcopy(history["attempts"])
    appended = deepcopy(before[-1])
    appended["id"] = "later-distinct-attempt"

    _append_attempt(appended)

    updated = json.loads(path.read_text(encoding="utf-8"))
    assert updated["attempts"][:-1] == before
    assert updated["attempts"][-1] == appended
    assert updated["summary"] == _history_summary(updated["attempts"])


def test_agent_run_output_is_unique_and_repository_retained(tmp_path):
    accepted = ROOT / "evaluation" / "agent-runs" / "new-run.json"
    assert _validated_run_output(accepted) == accepted

    with pytest.raises(AgentEvaluationError, match="evaluation/agent-runs"):
        _validated_run_output(tmp_path / "escaped.json")

    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    with pytest.raises(AgentEvaluationError, match="outside the repository"):
        _raw_result_record(outside)


def test_missing_usage_is_recorded_as_unknown_not_zero():
    assert _usage_totals([]) is None


def test_pre_lifecycle_abort_records_no_cleanup_debt():
    attempt = _attempt_from_error(
        "pre-lifecycle-abort", AgentEvaluationError("codex is not installed")
    )

    assert attempt["cleanup_verified"] is True
    assert attempt["safety_checks"]["temporary_state_removed"] is True
    assert attempt["safety_pass"] is True
    assert attempt["usage"] is None

    cleanup_failure = AgentEvaluationError("plugin cleanup failed")
    cleanup_failure.cleanup_verified = False
    unsafe = _attempt_from_error("cleanup-failure", cleanup_failure)
    assert unsafe["cleanup_verified"] is False
    assert unsafe["safety_pass"] is False


def test_focused_probe_abort_stays_in_the_focused_reliability_series():
    attempt = _attempt_from_probe_error(
        "focused-abort", AgentEvaluationError("agent response was malformed")
    )

    assert attempt["kind"] == "missing-cli-only"
    assert attempt["inputs"]["plugin_sha256"] is None
    assert attempt["checks"] == {
        "plugin_preflight": "not_run",
        "plugin_scenarios": "not_run",
        "missing_cli_boundary": "failed",
    }
    assert attempt["procedural_pass"] is False


def test_plugin_identity_ignores_interpreter_bytecode_cache(tmp_path):
    plugin = tmp_path / "plugin"
    source = plugin / "skills" / "glossabet" / "scripts" / "run_glossabet.py"
    source.parent.mkdir(parents=True)
    source.write_text("print('glossabet')\n", encoding="utf-8")
    clean_identity = _tree_sha256(plugin)

    cache = source.parent / "__pycache__" / "run_glossabet.cpython-312.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"generated interpreter cache")

    assert _tree_sha256(plugin) == clean_identity


def test_plugin_identity_uses_platform_independent_path_order(tmp_path):
    plugin = tmp_path / "plugin"
    contents = {
        "skills/glossabet/SKILL.md": b"skill",
        "skills/glossabet/assets/engine.whl": b"wheel",
        "skills/glossabet/scripts/run_glossabet.py": b"runner",
    }
    for relative, content in contents.items():
        path = plugin / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    expected = hashlib.sha256()
    for relative, content in sorted(contents.items()):
        encoded = relative.encode()
        expected.update(len(encoded).to_bytes(8, "big"))
        expected.update(encoded)
        expected.update(len(content).to_bytes(8, "big"))
        expected.update(content)

    assert _tree_sha256(plugin) == expected.hexdigest()


def test_agent_prompt_requires_complete_untransformed_inspect_stdout():
    normalized = " ".join(PROMPT.read_text(encoding="utf-8").split())

    assert (
        "Run each `inspect` as a direct command whose only arguments after the "
        "resolved engine invocation are `inspect` and the scenario's absolute path."
        in normalized
    )
    assert (
        "Do not pipe, redirect, filter, summarize, reserialize, or otherwise "
        "transform its stdout; the JSONL trace must capture the complete engine "
        "output unchanged."
        in normalized
    )


def test_agent_eval_disables_default_standalone_skill_without_modifying_it(
    tmp_path,
):
    skill = tmp_path / ".agents" / "skills" / "glossabet" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("stale user-owned skill\n", encoding="utf-8")

    paths = _competing_standalone_skill_paths(home=tmp_path)

    assert paths == (skill,)
    assert _disabled_skills_config(paths) == (
        f"skills.config=[{{path={json.dumps(str(skill))},enabled=false}}]"
    )
    assert skill.read_text(encoding="utf-8") == "stale user-owned skill\n"


def test_agent_eval_adds_no_skill_override_when_standalone_skill_is_absent(
    tmp_path,
):
    paths = _competing_standalone_skill_paths(home=tmp_path)

    assert paths == ()
    assert _disabled_skills_config(paths) is None


def test_agent_eval_passes_the_skill_override_to_codex_exec(tmp_path):
    skill = tmp_path / ".agents" / "skills" / "glossabet" / "SKILL.md"

    command = _codex_exec_command(
        "/usr/bin/codex",
        workspace=tmp_path,
        prompt="$glossabet",
        final_path=tmp_path / "agent-final.json",
        disabled_skills=(skill,),
    )

    override = _disabled_skills_config((skill,))
    assert override is not None
    assert command[command.index(override) - 1] == "-c"
    assert not any("experimental_use_profile" in item for item in command)
    assert not any("allow_login_shell" in item for item in command)
    assert "--dangerously-bypass-hook-trust" not in command
    assert command[-1] == "$glossabet"


def test_agent_eval_can_bypass_hook_trust_for_digest_bound_plugin_probe(tmp_path):
    command = _codex_exec_command(
        "/usr/bin/codex",
        workspace=tmp_path,
        prompt=HOOK_PROMPT,
        final_path=tmp_path / "agent-final.json",
        bypass_hook_trust=True,
    )

    assert command.count("--dangerously-bypass-hook-trust") == 1
    assert command[-1] == HOOK_PROMPT


def test_agent_eval_can_disable_profile_and_login_shell_for_one_codex_exec(
    tmp_path,
):
    command = _codex_exec_command(
        "/usr/bin/codex",
        workspace=tmp_path,
        prompt="$glossabet",
        final_path=tmp_path / "agent-final.json",
        use_shell_profile=False,
        allow_login_shell=False,
    )

    profile_override = "shell_environment_policy.experimental_use_profile=false"
    login_override = "allow_login_shell=false"
    assert command[command.index(profile_override) - 1] == "-c"
    assert command[command.index(login_override) - 1] == "-c"
    assert command[-1] == "$glossabet"


def test_missing_cli_host_run_disables_profile_and_login_shell(
    monkeypatch,
    tmp_path,
):
    observed: dict[str, object] = {}

    def install_skill(destination):
        destination.mkdir(parents=True)
        (destination / "SKILL.md").write_text("test skill\n", encoding="utf-8")

    def run_codex(*args, **kwargs):
        observed.update(kwargs)
        return {"scenarios": [{"id": "missing-cli"}]}, [], {"input_tokens": 0}

    monkeypatch.setattr(agent_eval, "_install_standalone_skill", install_skill)
    monkeypatch.setattr(agent_eval, "_run_codex", run_codex)
    monkeypatch.setattr(
        agent_eval,
        "_evaluate_scenario",
        lambda *args, **kwargs: {"id": "missing-cli", "passed": True},
    )

    result, usage = _run_missing_cli_scenario(
        "/usr/bin/codex",
        {
            "id": "missing-cli",
            "description": "The engine command is absent.",
            "delivery": "standalone-skill",
            "expected_status": "stopped",
        },
        {},
        tmp_path,
    )

    assert result == {"id": "missing-cli", "passed": True}
    assert usage == {"input_tokens": 0}
    assert observed["use_shell_profile"] is False
    assert observed["allow_login_shell"] is False


def test_agent_eval_reports_a_competing_standalone_version_command(tmp_path):
    installed = tmp_path / "plugins" / "glossabet" / "0.1.0"
    commands = [
        {
            "command": "/venv/bin/glossabet --version",
            "cwd": None,
            "output": "glossabet 0.1.0\n",
            "exit_code": 0,
            "status": "completed",
        }
    ]
    limits = {"stored_command_characters": 1200}

    with pytest.raises(AgentEvaluationError) as raised:
        _installed_version_command(
            commands,
            installed_path=installed,
            workspace=tmp_path,
            limits=limits,
        )

    message = str(raised.value)
    assert "count was 0, expected 1" in message
    assert "/venv/bin/glossabet --version" in message


def test_missing_cli_accepts_the_exact_skill_boundary_without_a_shell_read(
    tmp_path,
):
    root = tmp_path / "scenarios" / "missing-cli"
    skill = root / ".agents" / "skills" / "glossabet" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("installed by the scenario\n", encoding="utf-8")
    before = _snapshot(root)
    runner = skill.parent / "scripts" / "run_glossabet.py"
    commands = [
        {
            "command": (
                f"if [[ -f '{runner.as_posix()}' ]]; then "
                f"python3 '{runner.as_posix()}' --version; "
                "else glossabet --version; fi"
            ),
            "cwd": None,
            "output": "zsh: command not found: glossabet\n",
            "exit_code": 127,
            "status": "failed",
        }
    ]

    result = _evaluate_scenario(
        {
            "id": "missing-cli",
            "delivery": "standalone-skill",
            "expected_status": "stopped",
        },
        root=root,
        commands=commands,
        response={
            "id": "missing-cli",
            "status": "stopped",
            "facts": ["The standalone engine command is missing."],
            "next_action": "Install the matching engine before inspection.",
        },
        before=before,
        workspace=tmp_path,
        limits={
            "commands_per_scenario": 12,
            "stored_command_characters": 1200,
            "stored_output_characters": 600,
        },
    )

    assert result["passed"] is True
    assert result["failures"] == []
    assert result["observed"] == {
        "standalone_skill_boundary_observed": True,
        "engine_missing": True,
    }


def test_agent_verifier_rejects_unretained_weakened_or_unsafe_evidence(
    tmp_path,
):
    original = json.loads(RESULTS.read_text(encoding="utf-8"))

    copied = tmp_path / "unretained-copy.json"
    copied.write_text(json.dumps(original), encoding="utf-8")
    assert "agent result is not retained by the attempt history" in (
        verify_results(copied)
    )

    mutations = []

    weakened = deepcopy(original)
    weakened["method"]["host_runs"] = 1
    mutations.append((weakened, "method is weakened or stale"))

    delivery_missing = deepcopy(original)
    delivery_missing["delivery"]["installed_plugin_skill_read"] = False
    mutations.append((delivery_missing, "delivery evidence is missing or stale"))

    unsafe = deepcopy(original)
    unsafe["scenarios"][0]["unexpected_writes"] = ["README.md"]
    mutations.append((unsafe, "unexpected writes are recorded"))

    inconsistent = deepcopy(original)
    inconsistent["summary"]["passed"] = 11
    mutations.append((inconsistent, "scenario summary is inconsistent"))

    contradictory = deepcopy(original)
    contradictory["delivery"]["standalone_skill_boundary_observed"] = False
    mutations.append(
        (contradictory, "standalone delivery summary contradicts its scenario")
    )

    for index, (value, expected) in enumerate(mutations):
        path = tmp_path / f"agent-results-{index}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        assert any(expected in error for error in verify_results(path))
