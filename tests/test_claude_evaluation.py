"""Claude Code evidence is bounded, subscription-safe, and fail-closed."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

import scripts.claude_eval as claude_eval
from glossabet import __version__
from glossabet.install.claude_plugin import claude_hooks, claude_plugin_manifest
from scripts.claude_eval import (
    CANONICAL_DEFINITION,
    CANONICAL_TERM,
    LIVE_CONFIRMATION,
    PROPOSED_TERM,
    SCENARIO_IDS,
    SOURCE_CANARY,
    ClaudeEvaluationError,
    _append_attempt,
    _attempt_from_error,
    _attempt_from_result,
    _claude_command,
    _history_summary,
    _manifest,
    _normal_profile_environment,
    _promote_current_result,
    _remove_owned_scratch,
    _response_schema,
    _tree_sha256,
    _validated_output,
    main,
    preflight,
    run_evaluation,
    verify_history,
    verify_results,
)


def _make_executable(path: Path, source: str) -> Path:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)
    return path


def _fake_host(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str]]:
    real_glossabet = _make_executable(
        tmp_path / "fake-glossabet-real",
        f"""#!/usr/bin/env python3
import sys
from pathlib import Path

if sys.argv[1:] == ["--version"]:
    print("glossabet {__version__}")
    raise SystemExit(0)
if sys.argv[1:] == ["brief", "."]:
    if Path.cwd().name != "ambient-absent":
        print({(CANONICAL_TERM + ' — ' + CANONICAL_DEFINITION)!r})
    raise SystemExit(0)
raise SystemExit(2)
""",
    )
    glossabet = tmp_path / "glossabet"
    glossabet.symlink_to(real_glossabet)

    plugin = tmp_path / "installed-glossabet"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / "hooks").mkdir()
    (plugin / "SKILL.md").write_bytes(claude_eval.CANONICAL_SKILL.read_bytes())
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(claude_plugin_manifest(), indent=2) + "\n",
        encoding="utf-8",
    )
    (plugin / "hooks" / "hooks.json").write_text(
        json.dumps(claude_hooks(glossabet), indent=2) + "\n",
        encoding="utf-8",
    )

    log = tmp_path / "fake-claude-calls.jsonl"
    claude = _make_executable(
        tmp_path / "claude",
        f"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
mode = os.environ.get("FAKE_CLAUDE_MODE", "pass")
plugin = os.environ["FAKE_PLUGIN_PATH"]
log = Path(os.environ["FAKE_CLAUDE_LOG"])

if args == ["--version"]:
    print("2.1.235 (Claude Code)")
    raise SystemExit(0)

if "auth" in args and "status" in args:
    logged_in = mode != "logged-out"
    print(json.dumps({{
        "loggedIn": logged_in,
        "authMethod": "claude.ai" if logged_in else "none",
        "apiProvider": "firstParty" if logged_in else "none",
        "subscriptionType": "max" if logged_in else None,
        "email": "must-not-be-retained@example.invalid",
        "orgId": "must-not-be-retained",
    }}))
    raise SystemExit(0)

if "plugin" in args:
    index = args.index("plugin")
    operation = args[index + 1]
    if operation == "validate":
        print("Validation passed")
        raise SystemExit(0)
    if operation == "list":
        print(json.dumps([
            {{
                "id": "frontend-design@claude-plugins-official",
                "version": "unknown",
                "scope": "user",
                "enabled": True,
                "installPath": "/irrelevant/frontend",
            }},
            {{
                "id": "glossabet@skills-dir",
                "version": "0.1.0",
                "scope": "user",
                "enabled": True,
                "installPath": plugin,
            }},
        ]))
        raise SystemExit(0)
    if operation == "details":
        plugin_id = args[index + 2]
        if plugin_id == "glossabet@skills-dir":
            print("glossabet 0.1.0\\n  Hooks (1)  SessionStart")
        elif mode == "other-hook":
            print("frontend-design\\n  Hooks (1)  SessionStart")
        else:
            print("frontend-design\\n  Hooks (0)")
        raise SystemExit(0)

if "-p" not in args:
    raise SystemExit(2)

with log.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({{"cwd": str(Path.cwd()), "args": args}}) + "\\n")

scenario = Path.cwd().name
if mode == "write":
    (Path.cwd() / "unexpected.txt").write_text("changed", encoding="utf-8")

events = [{{
    "type": "system",
    "subtype": "hook_started",
    "hook_event_name": "SessionStart",
    "plugin": "glossabet@skills-dir",
}}]
if mode == "missing-hook":
    events = []
if scenario == "ambient-present":
    response = {{
        "status": "supplied",
        "term": {CANONICAL_TERM!r},
        "definition": {CANONICAL_DEFINITION!r},
        "protocol": None,
    }}
    if events:
        events[0]["output"] = {CANONICAL_TERM!r} + " — " + {CANONICAL_DEFINITION!r}
elif scenario == "ambient-absent":
    response = {{
        "status": "not-supplied",
        "term": None,
        "definition": None,
        "protocol": None,
    }}
    if mode == "bad-absent":
        response = {{
            "status": "supplied",
            "term": {CANONICAL_TERM!r},
            "definition": {CANONICAL_DEFINITION!r},
            "protocol": None,
        }}
else:
    response = {{
        "status": "skill-loaded",
        "term": None,
        "definition": None,
        "protocol": "Step 0 checks the version and runs inspect, but tools are unavailable.",
    }}

if mode == "tool":
    events.append({{
        "type": "assistant",
        "message": {{"content": [{{"type": "tool_use", "name": "Read"}}]}},
    }})
if mode == "api-retry":
    events.append({{"type": "system", "subtype": "api_retry"}})
if mode == "leak-proposed":
    events.append({{"type": "system", "note": {PROPOSED_TERM!r}}})
if mode == "leak-source":
    events.append({{"type": "system", "note": {SOURCE_CANARY!r}}})

events.append({{
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "session_id": "private-session-id",
    "structured_output": response,
    "usage": {{"input_tokens": 100, "output_tokens": 20}},
    "total_cost_usd": 0.01,
}})
for event in events:
    print(json.dumps(event))
""",
    )
    environment = {
        "FAKE_PLUGIN_PATH": str(plugin),
        "FAKE_CLAUDE_LOG": str(log),
    }
    return claude, glossabet, plugin, environment


@pytest.fixture
def evidence_area(monkeypatch, tmp_path):
    root = tmp_path / "evidence-repository"
    runs = root / "evaluation" / "agent-runs"
    runs.mkdir(parents=True)
    history = root / "evaluation" / "claude-history.json"
    results = root / "evaluation" / "claude-results.json"
    history.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "attempts": [],
                "summary": _history_summary([]),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(claude_eval, "ROOT", root)
    monkeypatch.setattr(claude_eval, "RUNS_PATH", runs)
    monkeypatch.setattr(claude_eval, "HISTORY_PATH", history)
    monkeypatch.setattr(claude_eval, "DEFAULT_RESULTS", results)
    monkeypatch.setattr(claude_eval.platform, "system", lambda: "Linux")
    return {"root": root, "runs": runs, "history": history, "results": results}


def _run_fake(
    tmp_path: Path,
    evidence_area: dict,
    *,
    mode: str = "pass",
) -> tuple[dict, Path, Path, Path, dict[str, str]]:
    claude, _, plugin, environment = _fake_host(tmp_path)
    environment["FAKE_CLAUDE_MODE"] = mode
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    output = (
        evidence_area["runs"]
        / "20260818T120000Z-claude-full-deadbeef.json"
    )
    result = run_evaluation(
        output,
        claude=claude,
        installed_plugin=plugin,
        scratch_parent=scratch,
        environment=environment,
    )
    return result, output, plugin, scratch, environment


def test_manifest_has_exact_bounded_calls_and_unprimed_prompts():
    manifest = _manifest()
    scenarios = manifest["scenarios"]

    assert tuple(item["id"] for item in scenarios) == SCENARIO_IDS
    assert manifest["budget"] == {
        "calls": 3,
        "retries": 0,
        "estimated_total_input_tokens": 200000,
        "estimated_total_output_tokens": 6000,
        "max_usd_per_call": 0.25,
    }
    assert scenarios[0]["prompt"] == scenarios[1]["prompt"]
    for scenario in scenarios[:2]:
        prompt = scenario["prompt"].casefold()
        assert "glossabet" not in prompt
        assert CANONICAL_TERM.casefold() not in prompt
        assert CANONICAL_DEFINITION.casefold() not in prompt
        assert PROPOSED_TERM.casefold() not in prompt
        assert SOURCE_CANARY.casefold() not in prompt
        assert scenario["disable_skills"] is True
    assert scenarios[2]["prompt"] == "/glossabet"
    assert scenarios[2]["disable_skills"] is False
    assert _response_schema()["required"] == [
        "status",
        "term",
        "definition",
        "protocol",
    ]
    assert "$schema" not in _response_schema()


def test_claude_command_disables_tools_mcp_persistence_and_retries():
    manifest = _manifest()
    schema = _response_schema()

    for scenario in manifest["scenarios"]:
        command = _claude_command(Path("/usr/bin/claude"), scenario, manifest, schema)
        assert command.count("-p") == 1
        assert command[-1] == scenario["prompt"]
        assert command[command.index("--tools") + 1] == ""
        assert command[command.index("--setting-sources") + 1] == "user"
        assert command[command.index("--max-turns") + 1] == "1"
        assert command[command.index("--max-budget-usd") + 1] == "0.25"
        assert command[command.index("--mcp-config") + 1] == '{"mcpServers":{}}'
        assert "--strict-mcp-config" in command
        assert "--no-session-persistence" in command
        assert "--include-hook-events" in command
        assert "login" not in command
        assert "logout" not in command
        assert "setup-token" not in command
    assert "--disable-slash-commands" in _claude_command(
        Path("claude"), manifest["scenarios"][0], manifest, schema
    )
    assert "--disable-slash-commands" not in _claude_command(
        Path("claude"), manifest["scenarios"][2], manifest, schema
    )


def test_normal_profile_environment_strips_every_provider_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-survive")
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", "must-not-survive")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/tmp/not-normal")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "must-not-survive")

    environment = _normal_profile_environment(
        {
            "ANTHROPIC_API_KEY": "cannot-be-reintroduced",
            "FAKE_MARKER": "retained",
        }
    )

    assert not any(name.startswith("ANTHROPIC_") for name in environment)
    assert "CLAUDE_CONFIG_DIR" not in environment
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in environment
    assert environment["FAKE_MARKER"] == "retained"


def test_tree_identity_never_reads_dotenv_contents(monkeypatch, tmp_path):
    (tmp_path / "ordinary.txt").write_text("ordinary", encoding="utf-8")
    (tmp_path / ".env").write_text("synthetic", encoding="utf-8")
    (tmp_path / "service.env.local").write_text("synthetic", encoding="utf-8")
    (tmp_path / ".env.production").mkdir()
    (tmp_path / ".env.production" / "nested.txt").write_text(
        "synthetic", encoding="utf-8"
    )
    original = Path.read_bytes

    def guarded_read(path):
        assert not claude_eval._dotenv_part(path.name)
        assert not any(claude_eval._dotenv_part(part) for part in path.parts)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    first = _tree_sha256(tmp_path)
    (tmp_path / "ordinary.txt").write_text("changed", encoding="utf-8")
    second = _tree_sha256(tmp_path)

    assert first != second


def test_preflight_uses_normal_max_auth_and_sanitizes_identity(monkeypatch, tmp_path):
    claude, _, plugin, environment = _fake_host(tmp_path)
    monkeypatch.setattr(claude_eval.platform, "system", lambda: "Linux")

    record, executable = preflight(
        claude,
        plugin,
        environment=environment,
    )

    assert executable.is_file()
    assert record["auth"] == {
        "logged_in": True,
        "auth_method": "claude.ai",
        "api_provider": "firstParty",
        "subscription_type": "max",
    }
    assert "email" not in record["auth"]
    assert "org" not in json.dumps(record).casefold()
    assert record["plugin"]["path"] == "<HOME>/.claude/skills/glossabet"
    assert record["plugin"]["hook_executable"] == "<HOME>/.local/bin/glossabet"
    assert record["enabled_plugins"] == [
        {
            "id": "frontend-design@claude-plugins-official",
            "version": "unknown",
            "scope": "user",
            "hooks": 0,
        },
        {
            "id": "glossabet@skills-dir",
            "version": "0.1.0",
            "scope": "user",
            "hooks": 1,
        },
    ]


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("logged-out", "refusing to open login"),
        ("other-hook", "could contaminate the run"),
    ],
)
def test_preflight_fails_before_model_calls(monkeypatch, tmp_path, mode, message):
    claude, _, plugin, environment = _fake_host(tmp_path)
    environment["FAKE_CLAUDE_MODE"] = mode
    monkeypatch.setattr(claude_eval.platform, "system", lambda: "Linux")

    with pytest.raises(ClaudeEvaluationError, match=message):
        preflight(claude, plugin, environment=environment)

    log = Path(environment["FAKE_CLAUDE_LOG"])
    assert not log.exists()


def test_fake_host_full_run_makes_exactly_three_calls_and_cleans_scratch(
    tmp_path,
    evidence_area,
):
    result, output, _, scratch, environment = _run_fake(tmp_path, evidence_area)

    assert output.is_file()
    assert result["summary"] == {
        "required": 3,
        "passed": 3,
        "failed": 0,
        "all_passed": True,
    }
    assert result["cleanup_verified"] is True
    assert not list(scratch.glob("glossabet-claude-eval-*"))
    assert result["auth"] == {
        "logged_in": True,
        "auth_method": "claude.ai",
        "api_provider": "firstParty",
        "subscription_type": "max",
    }
    assert result["usage"] == {
        "input_tokens": 300,
        "output_tokens": 60,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "total_cost_usd": pytest.approx(0.03),
    }
    calls = [
        json.loads(line)
        for line in Path(environment["FAKE_CLAUDE_LOG"]).read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert [Path(item["cwd"]).name for item in calls] == list(SCENARIO_IDS)
    assert all(item["args"][item["args"].index("--tools") + 1] == "" for item in calls)
    assert all("--no-session-persistence" in item["args"] for item in calls)
    assert result["scenarios"][0]["response"]["term"] == CANONICAL_TERM
    assert result["scenarios"][1]["response"]["term"] is None
    assert "<SESSION>" in json.dumps(result)
    assert "private-session-id" not in json.dumps(result)


@pytest.mark.parametrize(
    ("mode", "failure"),
    [
        ("tool", "model used tools"),
        ("missing-hook", "hook lifecycle event was not observed"),
        ("write", "fixture changed"),
        ("leak-proposed", "proposed vocabulary reached"),
        ("leak-source", "source canary reached"),
        ("api-retry", "API retries"),
        ("bad-absent", "ambient-absent claimed vocabulary"),
    ],
)
def test_fake_host_records_each_safety_and_semantic_miss(
    tmp_path,
    evidence_area,
    mode,
    failure,
):
    result, _, _, scratch, _ = _run_fake(
        tmp_path,
        evidence_area,
        mode=mode,
    )

    assert result["summary"]["all_passed"] is False
    assert any(
        failure.casefold() in item.casefold()
        for scenario in result["scenarios"]
        for item in scenario["failures"]
    )
    assert not list(scratch.glob("glossabet-claude-eval-*"))


def test_cleanup_failure_is_never_reported_as_safe(
    monkeypatch,
    tmp_path,
    evidence_area,
):
    claude, _, plugin, environment = _fake_host(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    output = (
        evidence_area["runs"]
        / "20260818T120000Z-claude-full-deadbeef.json"
    )

    def fail_cleanup(_root, _parent):
        raise OSError("synthetic cleanup refusal")

    monkeypatch.setattr(claude_eval, "_remove_owned_scratch", fail_cleanup)
    with pytest.raises(ClaudeEvaluationError, match="scratch cleanup failed") as caught:
        run_evaluation(
            output,
            claude=claude,
            installed_plugin=plugin,
            scratch_parent=scratch,
            environment=environment,
        )

    assert caught.value.cleanup_verified is False
    attempt = _attempt_from_error("synthetic-cleanup-failure", caught.value)
    assert attempt["cleanup_verified"] is False
    assert attempt["safety_checks"]["temporary_state_removed"] is False
    assert attempt["safety_pass"] is False
    assert not output.exists()


def test_history_result_mirror_and_current_verification_are_digest_bound(
    tmp_path,
    evidence_area,
):
    result, output, plugin, _, _ = _run_fake(tmp_path, evidence_area)
    attempt = _attempt_from_result(
        "20260818T120000Z-claude-full-deadbeef",
        result,
        output,
    )

    _append_attempt(attempt)
    _promote_current_result(output)

    assert verify_history() == []
    assert verify_results(evidence_area["results"]) == []
    assert verify_results(
        evidence_area["results"], current=True, installed_plugin=plugin
    ) == []
    assert evidence_area["results"].read_bytes() == output.read_bytes()

    original_history = json.loads(evidence_area["history"].read_text())
    altered_history = deepcopy(original_history)
    altered_history["attempts"][0]["failures"] = ["fabricated ledger claim"]
    evidence_area["history"].write_text(
        json.dumps(altered_history, indent=2) + "\n",
        encoding="utf-8",
    )
    assert any("contradicts its raw result" in error for error in verify_history())
    evidence_area["history"].write_text(
        json.dumps(original_history, indent=2) + "\n",
        encoding="utf-8",
    )

    output.write_text("{}\n", encoding="utf-8")
    assert any("raw digest is stale" in error for error in verify_history())


def test_history_verifier_reports_the_retained_attempt_count(
    capsys,
    evidence_area,
):
    assert main(["--verify-history"]) == 0
    assert capsys.readouterr().out.strip() == (
        "Claude attempt history is genuine and empty"
    )

    _append_attempt(
        _attempt_from_error(
            "20260818T120000Z-claude-full-deadbeef",
            ClaudeEvaluationError("synthetic preflight refusal"),
        )
    )

    assert main(["--verify-history"]) == 0
    assert capsys.readouterr().out.strip() == (
        "Claude attempt history is genuine; 1 attempt retained"
    )


def test_result_verifier_rejects_weakened_method_and_claimed_success(
    tmp_path,
    evidence_area,
):
    result, _, _, _, _ = _run_fake(tmp_path, evidence_area)
    weakened = deepcopy(result)
    weakened["method"]["tools"] = ["Read"]
    weakened["scenarios"][0]["response"]["term"] = "Invented"
    weakened["scenarios"][0]["failures"] = []
    weakened["scenarios"][0]["passed"] = True
    weakened["scenarios"][0]["stderr"] = "altered"
    path = evidence_area["root"] / "weakened.json"
    path.write_text(json.dumps(weakened), encoding="utf-8")

    errors = verify_results(path)

    assert "Claude result method is weakened or stale" in errors
    assert any("canonical term" in error for error in errors)
    assert any("sanitized stderr" in error for error in errors)


def test_output_and_cleanup_are_confined(evidence_area, tmp_path):
    good = evidence_area["runs"] / "20260818T120000Z-claude-full-deadbeef.json"
    assert _validated_output(good) == good

    for bad in (
        evidence_area["root"] / "outside.json",
        evidence_area["runs"] / "arbitrary.json",
    ):
        with pytest.raises(ClaudeEvaluationError):
            _validated_output(bad)
    good.write_text("reserved", encoding="utf-8")
    with pytest.raises(ClaudeEvaluationError, match="overwrite"):
        _validated_output(good)

    parent = tmp_path / "scratch-parent"
    parent.mkdir()
    owned = parent / "glossabet-claude-eval-owned"
    owned.mkdir()
    assert _remove_owned_scratch(owned, parent) is True
    foreign = parent / "foreign"
    foreign.mkdir()
    with pytest.raises(ClaudeEvaluationError, match="unowned"):
        _remove_owned_scratch(foreign, parent)
    assert foreign.is_dir()


def test_main_refuses_live_run_without_confirmation_before_any_host_call(
    monkeypatch,
    tmp_path,
    evidence_area,
):
    claude = _make_executable(tmp_path / "unused-claude", "#!/bin/sh\nexit 99\n")

    def unexpected(*_args, **_kwargs):
        raise AssertionError("live host must not run without the confirmation phrase")

    monkeypatch.setattr(claude_eval, "run_evaluation", unexpected)

    assert main(["--run", "--claude", str(claude)]) == 1
    assert json.loads(evidence_area["history"].read_text())["attempts"] == []
    assert not evidence_area["results"].exists()
    assert LIVE_CONFIRMATION not in "--run"
