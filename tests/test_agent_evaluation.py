"""Installed Codex boundary evidence is current, bounded, and fail-closed."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

import scripts.agent_eval as agent_eval
from scripts.agent_eval import (
    AgentEvaluationError,
    _codex_exec_command,
    _competing_standalone_skill_paths,
    _disabled_skills_config,
    _evaluate_scenario,
    _installed_version_command,
    _run_missing_cli_scenario,
    _snapshot,
    _tree_sha256,
    verify_results,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evaluation" / "agent-scenarios.json"
PROMPT = ROOT / "evaluation" / "agent-prompt.md"
RESULTS = ROOT / "evaluation" / "agent-results.json"


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
        "missing-cli",
    ]
    sensitive = manifest["scenarios"][-2]
    assert sensitive["accepted_statuses"] == [
        "grounded",
        "grounded-with-warning",
    ]


def test_committed_installed_agent_evidence_is_current_and_complete():
    assert verify_results(RESULTS) == []
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert results["summary"] == {
        "required": 11,
        "passed": 11,
        "failed": 0,
        "all_passed": True,
    }
    assert results["delivery"]["installed_plugin_skill_read"] is True
    assert results["delivery"]["temporary_plugin_state_removed"] is True
    sensitive = next(
        item for item in results["scenarios"] if item["id"] == "sensitive-file"
    )
    assert sensitive["observed"]["sensitive_paths"] == [
        ".env",
        "api-secret.txt",
    ]
    assert sensitive["unexpected_writes"] == []


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
    assert command[-1] == "$glossabet"


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


def test_agent_verifier_rejects_stale_weakened_or_failing_evidence(tmp_path):
    original = json.loads(RESULTS.read_text(encoding="utf-8"))

    mutations = []

    stale = deepcopy(original)
    stale["inputs"]["evaluator_sha256"] = "0" * 64
    mutations.append((stale, "inputs are stale"))

    weakened = deepcopy(original)
    weakened["method"]["host_runs"] = 1
    mutations.append((weakened, "method is weakened or stale"))

    delivery_missing = deepcopy(original)
    delivery_missing["delivery"]["installed_plugin_skill_read"] = False
    mutations.append((delivery_missing, "delivery evidence is missing or stale"))

    scenario_failed = deepcopy(original)
    scenario_failed["scenarios"][0]["passed"] = False
    mutations.append((scenario_failed, "scenario does not pass"))

    for index, (value, expected) in enumerate(mutations):
        path = tmp_path / f"agent-results-{index}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        assert any(expected in error for error in verify_results(path))
