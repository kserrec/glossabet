#!/usr/bin/env python3
"""Run and verify bounded installed-skill scenarios through real Codex exec."""

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
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.codex.contract import (  # noqa: E402
    CANONICAL_SKILL,
    DEFAULT_RESULTS,
    HOOK_DEFINITION,
    HOOK_PROMPT,
    HOOK_PROPOSED_TERM,
    HOOK_SOURCE_CANARY,
    HOOK_TERM,
    MARKDOWN_GLOSSARY_CANARY,
    MARKDOWN_GLOSSARY_TEXT,
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
    mapping,
    read_json,
    write_json,
)
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
from evaluation.codex.scenarios import validate_manifest  # noqa: E402
from evaluation.harness.io import (  # noqa: E402
    changed_paths,
    dotenv_part,
    file_sha256,
    walk_paths,
)
from glossabet import __version__  # noqa: E402
from glossabet.agent.agent_context import AGENT_CONTEXT_SCHEMA_VERSION  # noqa: E402
from glossabet.corpus.scanner import is_sensitive  # noqa: E402
from glossabet.install.installer import default_skill_directory  # noqa: E402
from glossabet.runtime.artifacts import MAX_JSON_BYTES  # noqa: E402


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


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c", "core.fsmonitor=",
            "-c", "core.hooksPath=/dev/null",
            *args,
        ],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=30,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        },
    )
    if result.returncode:
        fail(result.stderr.strip() or result.stdout.strip() or "git failed")
    return result.stdout.strip()


def _ordinary_repo(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "service.py").write_text(
        "class PaymentService:\n    pass\n\npayment_record = PaymentService()\n",
        encoding="utf-8",
    )


def _git_graph_repo(root: Path, *, stale: bool) -> None:
    _ordinary_repo(root)
    (root / ".gitignore").write_text(
        "graphify-out/\nglossabet-out/\n", encoding="utf-8"
    )
    _git(root, "init", "-q")
    _git(root, "add", ".gitignore", "service.py")
    _git(
        root,
        "-c", "user.name=Glossabet Evaluation",
        "-c", "user.email=evaluation@example.invalid",
        "commit", "-q", "-m", "fixture",
    )
    head = _git(root, "rev-parse", "HEAD")
    write_json(
        root / "graphify-out" / "graph.json",
        {
            "built_at_commit": "0" * 40 if stale else head,
            "nodes": [
                {
                    "id": "payment",
                    "label": "PaymentService",
                    "community": 0,
                    "source_file": "service.py",
                }
            ],
            "links": [],
        },
    )


def _glossary_path(root: Path) -> Path:
    path = root / "glossabet-out" / "glossary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _make_scenario(root: Path, scenario_id: str) -> None:
    if scenario_id == "fresh":
        _git_graph_repo(root, stale=False)
        return
    if scenario_id == "stale":
        _git_graph_repo(root, stale=True)
        return
    if scenario_id == "session-hook":
        root.mkdir(parents=True)
        (root / "module.py").write_text(
            f'ambient_source_canary = "{HOOK_SOURCE_CANARY}"\n',
            encoding="utf-8",
        )
        write_json(
            _glossary_path(root),
            {
                "schema_version": 1,
                "concepts": [
                    {
                        "id": "payment-service",
                        "term": HOOK_TERM,
                        "definition": HOOK_DEFINITION,
                        "status": "canonical",
                    },
                    {
                        "id": "gateway-route",
                        "term": HOOK_PROPOSED_TERM,
                        "definition": "A term that has not been settled.",
                        "status": "proposed",
                    },
                ],
            },
        )
        return
    _ordinary_repo(root)
    if scenario_id == "malformed":
        _glossary_path(root).write_text("{not-json", encoding="utf-8")
    elif scenario_id == "oversized":
        with _glossary_path(root).open("wb") as handle:
            handle.truncate(MAX_JSON_BYTES + 1)
    elif scenario_id == "symlinked":
        target = root / "outside-glossary.json"
        write_json(target, {"schema_version": 1, "concepts": []})
        _glossary_path(root).symlink_to(target)
    elif scenario_id == "partial":
        (root / "service.py").write_text(
            "".join(
                f"distinctIdentifier{index} = {index}\n"
                for index in range(360)
            ),
            encoding="utf-8",
        )
    elif scenario_id == "monorepo":
        write_json(
            root / "package.json",
            {"private": True, "workspaces": ["packages/*"]},
        )
        for name in ("alpha", "beta", "gamma"):
            package = root / "packages" / name
            package.mkdir(parents=True)
            write_json(package / "package.json", {"name": name})
            (package / "index.js").write_text(
                f"export const {name}Service = true;\n", encoding="utf-8"
            )
    elif scenario_id == "resumed-glossary":
        write_json(
            _glossary_path(root),
            {
                "schema_version": 1,
                "concepts": [
                    {
                        "id": "payment-service",
                        "term": "Payment Service",
                        "definition": "The boundary that owns payment attempts.",
                        "status": "canonical",
                    },
                    {
                        "id": "gateway-route",
                        "term": "Gateway Route",
                        "definition": "The still-open provider routing concept.",
                        "status": "proposed",
                    },
                ],
            },
        )
    elif scenario_id == "markdown-glossary":
        # Bytes, not text: the checker compares the engine's SHA-256 with the
        # digest of these exact bytes, and text mode would write CRLF on
        # Windows.
        (root / "GLOSSARY.md").write_bytes(MARKDOWN_GLOSSARY_TEXT.encode("utf-8"))
    elif scenario_id == "both-glossaries":
        (root / "GLOSSARY.md").write_bytes(MARKDOWN_GLOSSARY_TEXT.encode("utf-8"))
        write_json(
            _glossary_path(root),
            {
                "schema_version": 1,
                "concepts": [
                    {
                        "id": "payment-service",
                        "term": "Payment Service",
                        "definition": "The boundary that owns payment attempts.",
                        "status": "canonical",
                    }
                ],
            },
        )
    elif scenario_id == "sensitive-file":
        dotenv = root / ".env"
        dotenv.touch()
        dotenv.chmod(0)
        sensitive = root / "api-secret.txt"
        sensitive.write_text(SENSITIVE_CANARY, encoding="utf-8")
        sensitive.chmod(0)
    elif scenario_id not in {"absent", "missing-cli"}:
        fail(f"unknown scenario fixture: {scenario_id}")


def _snapshot(root: Path) -> dict[str, tuple]:
    snapshot: dict[str, tuple] = {}
    for path in walk_paths(
        root, excluded_directory=".git", skip_dotenv=False
    ):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if path.is_symlink():
            snapshot[relative] = ("symlink", os.readlink(path))
        elif is_sensitive(path.name):
            snapshot[relative] = (
                "sensitive-stat",
                info.st_size,
                stat.S_IMODE(info.st_mode),
                info.st_mtime_ns,
            )
        else:
            snapshot[relative] = (
                "file",
                info.st_size,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
    return snapshot


def _unexpected_writes(
    before: dict[str, tuple], after: dict[str, tuple]
) -> list[str]:
    changed = changed_paths(before, after)
    return [
        path for path in changed if path != "glossabet-out/evidence.json"
    ]


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


def _parse_events(raw: str, limits: dict) -> list[dict]:
    encoded = raw.encode("utf-8")
    if len(encoded) > limits["jsonl_bytes"]:
        fail(
            f"Codex JSONL exceeded {limits['jsonl_bytes']} bytes "
            f"({len(encoded)} observed)"
        )
    events = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (ValueError, RecursionError) as exc:
            fail(f"Codex emitted non-JSON stdout: {line[:200]!r}: {exc}")
        if not isinstance(event, dict):
            fail("Codex JSONL event was not an object")
        events.append(event)
    if len(events) > limits["events"]:
        fail(
            f"Codex trace exceeded {limits['events']} events "
            f"({len(events)} observed)"
        )
    return events


def _command_items(events: list[dict]) -> list[dict]:
    commands = []
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "command_execution":
            continue
        command = item.get("command")
        output = item.get("aggregated_output", "")
        if not isinstance(command, str) or not isinstance(output, str):
            fail("Codex command trace is malformed")
        commands.append({
            "command": command,
            "cwd": item.get("cwd") if isinstance(item.get("cwd"), str) else None,
            "output": output,
            "exit_code": item.get("exit_code"),
            "status": item.get("status"),
        })
    return commands


def _normalize_text(
    text: str,
    workspace: Path,
    limit: int,
    aliases: tuple[tuple[str, str], ...] = (),
) -> str:
    normalized = text
    for source, replacement in aliases:
        normalized = normalized.replace(source, replacement)
    normalized = normalized.replace(str(workspace), "<WORKSPACE>")
    # The agent may invoke absolute interpreter/shell paths the aliases above
    # never anticipated; redacting the repo root and home directory keeps a
    # committed, public trace from leaking the maintainer's username and
    # local layout. Repo root first (more specific than home).
    normalized = normalized.replace(str(ROOT), "<REPO>")
    normalized = normalized.replace(str(Path.home()), "<HOME>")
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "…"


def _trace_summary(
    command: dict,
    workspace: Path,
    limits: dict,
    aliases: tuple[tuple[str, str], ...] = (),
) -> dict:
    output = command["output"]
    return {
        "command": _normalize_text(
            command["command"],
            workspace,
            limits["stored_command_characters"],
            aliases,
        ),
        "cwd": (
            _normalize_text(
                command["cwd"],
                workspace,
                limits["stored_command_characters"],
                aliases,
            )
            if command["cwd"] is not None else None
        ),
        "exit_code": command["exit_code"],
        "status": command["status"],
        "output_characters": len(output),
        "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
        "output_preview": _normalize_text(
            output,
            workspace,
            limits["stored_output_characters"],
            aliases,
        ),
    }


def _installed_version_command(
    commands: list[dict],
    *,
    installed_path: Path,
    workspace: Path,
    limits: dict,
) -> dict:
    """Require one successful version check through the installed plugin path."""
    matching = [
        command
        for command in commands
        if str(installed_path) in command["command"]
        and "--version" in command["command"]
    ]
    aliases = ((str(installed_path), "<INSTALLED_PLUGIN>"),)
    version_commands = [
        _normalize_text(
            command["command"],
            workspace,
            limits["stored_command_characters"],
            aliases,
        )
        for command in commands
        if "--version" in command["command"]
    ][:8]
    if len(matching) != 1:
        observed = json.dumps(version_commands) if version_commands else "none"
        fail(
            "installed plugin engine version-check count was "
            f"{len(matching)}, expected 1; observed --version commands: {observed}"
        )
    command = matching[0]
    expected = f"glossabet {__version__}"
    if command["output"].strip() != expected:
        output = command["output"]
        fail(
            "installed plugin engine version output did not match "
            f"{expected!r}; output characters={len(output)}, "
            f"sha256={hashlib.sha256(output.encode()).hexdigest()}"
        )
    return command


def _extract_context(output: str) -> dict | None:
    stripped = output.strip()
    if not stripped.startswith("{"):
        return None
    try:
        value = json.loads(stripped)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


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
    events = _parse_events(result.stdout, limits)
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
    return response, _command_items(events), usage


def _response_by_id(response: dict, expected_ids: list[str]) -> dict[str, dict]:
    items = response.get("scenarios")
    if not isinstance(items, list):
        fail("Codex response has no scenarios list")
    by_id: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            fail("Codex returned a malformed scenario response")
        if item["id"] in by_id:
            fail(f"Codex returned duplicate scenario {item['id']}")
        by_id[item["id"]] = item
    if list(by_id) != expected_ids:
        fail(
            f"Codex scenario order/ids differ from the manifest: "
            f"{list(by_id)} != {expected_ids}"
        )
    return by_id


def _scenario_commands(commands: list[dict], root: Path) -> list[dict]:
    needle = str(root)
    return [
        command
        for command in commands
        if needle in command["command"] or needle == command.get("cwd")
    ]


def _expected_error(scenario_id: str, output: str) -> bool:
    lowered = output.casefold()
    required = {
        "malformed": ("glossary", "unreadable"),
        "oversized": ("glossary", "larger than"),
        "symlinked": ("glossary", "symlink"),
    }[scenario_id]
    return all(part in lowered for part in required)


def _check_context(scenario_id: str, context: dict) -> tuple[list[str], dict]:
    failures = []
    coverage = mapping(context.get("coverage"))
    projection_ledger = mapping(coverage.get("context"))
    omissions = projection_ledger.get("omissions")
    if not isinstance(omissions, list):
        omissions = []
    observed: dict[str, object] = {
        "context_schema_version": context.get("context_schema_version"),
        "generator": context.get("generator"),
        "freshness": mapping(context.get("freshness")).get("status"),
        "corpus_complete": mapping(coverage.get("corpus")).get("complete"),
        "context_complete": projection_ledger.get("complete"),
        "context_projection": projection_ledger.get("projection"),
        "context_omissions": len(omissions),
    }
    if context.get("context_schema_version") != AGENT_CONTEXT_SCHEMA_VERSION:
        failures.append(
            f"context schema was not {AGENT_CONTEXT_SCHEMA_VERSION}"
        )
    if context.get("generator") != {"name": "glossabet", "version": __version__}:
        failures.append("context generator did not match the installed engine")
    if observed["freshness"] != "current":
        failures.append("inspect did not return invocation-current context")
    if observed["corpus_complete"] is not True:
        failures.append("scenario unexpectedly had partial scanner coverage")
    if observed["context_projection"] != "lean":
        failures.append("inspect did not return the routine lean projection")
    if observed["context_complete"] is not False:
        failures.append("lean projection did not disclose its standard omissions")

    omission_pairs = {
        (item.get("path"), item.get("kind"))
        for item in omissions
        if isinstance(item, dict)
    }
    required_lean_omissions = {
        ("imports", "section_excluded"),
        (
            "vocabulary.tokens.items.*.locations",
            "file_locations_rolled_up",
        ),
        (
            "vocabulary.identifiers.items.*.locations",
            "file_locations_rolled_up",
        ),
    }
    if not required_lean_omissions <= omission_pairs:
        failures.append("lean projection did not account for standard omissions")

    structural = mapping(context.get("structural_groups"))
    glossary = mapping(context.get("glossary"))
    if scenario_id == "fresh":
        observed["graph_freshness"] = mapping(structural.get("freshness")).get("status")
        observed["graph_available"] = structural.get("available")
        if observed["graph_freshness"] != "current" or observed[
            "graph_available"
        ] is not True:
            failures.append("fresh Graphify input was not reported current/available")
    elif scenario_id == "stale":
        observed["graph_freshness"] = mapping(structural.get("freshness")).get("status")
        if observed["graph_freshness"] != "stale":
            failures.append("stale Graphify input was not reported stale")
    elif scenario_id == "absent":
        observed["graph_present"] = structural.get("present")
        observed["glossary_present"] = glossary.get("present")
        if observed["graph_present"] is not False:
            failures.append("absent Graphify input was not reported absent")
        if observed["glossary_present"] is not False:
            failures.append("absent glossary was not reported absent")
    elif scenario_id == "partial":
        if (
            "vocabulary.identifiers.items",
            "list_items",
        ) not in omission_pairs:
            failures.append(
                "partial projection did not expose its identifier sample cap"
            )
    elif scenario_id == "monorepo":
        observed["monorepo"] = context.get("monorepo")
        if mapping(context.get("monorepo")).get("detected") is not True:
            failures.append("workspace manifest did not trigger monorepo detection")
    elif scenario_id == "resumed-glossary":
        concepts = glossary.get("concepts", [])
        observed["glossary_present"] = glossary.get("present")
        observed["concept_statuses"] = {
            item.get("term"): item.get("status")
            for item in concepts if isinstance(item, dict)
        }
        if observed["glossary_present"] is not True:
            failures.append("valid existing glossary was not returned")
        if observed["concept_statuses"] != {
            "Gateway Route": "proposed",
            "Payment Service": "canonical",
        }:
            failures.append("resumed glossary statuses were not preserved")
    elif scenario_id in {"markdown-glossary", "both-glossaries"}:
        repository_glossary = mapping(context.get("repository_glossary"))
        observed["glossary_present"] = glossary.get("present")
        observed["repository_glossary"] = {
            key: repository_glossary.get(key)
            for key in ("present", "readable", "sha256", "nested_ignored")
        }
        expected_structured = scenario_id == "both-glossaries"
        if observed["glossary_present"] is not expected_structured:
            failures.append(
                "structured glossary presence did not match the scenario"
            )
        expected_digest = hashlib.sha256(
            MARKDOWN_GLOSSARY_TEXT.encode("utf-8")
        ).hexdigest()
        if (
            repository_glossary.get("present") is not True
            or repository_glossary.get("readable") is not True
            or repository_glossary.get("sha256") != expected_digest
            or repository_glossary.get("nested_ignored") != []
        ):
            failures.append(
                "repository GLOSSARY.md was not reported present, readable, "
                "and exactly identified"
            )
        if MARKDOWN_GLOSSARY_CANARY in json.dumps(context):
            failures.append("repository GLOSSARY.md content entered the agent context")
    elif scenario_id == "sensitive-file":
        skipped = mapping(context.get("skipped")).get("sensitive", [])
        observed["sensitive_paths"] = skipped
        if set(skipped) != {".env", "api-secret.txt"}:
            failures.append("sensitive paths were not both excluded and reported")
        if SENSITIVE_CANARY in json.dumps(context):
            failures.append("sensitive canary entered the agent context")

    if scenario_id != "partial":
        unexpected = [
            item
            for item in omissions
            if isinstance(item, dict)
            and not (
                item.get("kind") == "section_excluded"
                and item.get("path") == "imports"
            )
            and not (
                item.get("kind") == "file_locations_rolled_up"
                and str(item.get("path") or "").startswith("vocabulary.")
                and str(item.get("path") or "").endswith(".locations")
            )
        ]
        if unexpected:
            failures.append(
                "scenario unexpectedly exceeded the standard lean projection"
            )
    return failures, observed


def _accepted_statuses(scenario: dict) -> list:
    return scenario.get("accepted_statuses", [scenario["expected_status"]])


def _status_failures(scenario: dict, response: dict) -> list[str]:
    accepted_statuses = _accepted_statuses(scenario)
    if response.get("status") not in accepted_statuses:
        return [
            f"agent status {response.get('status')!r} did not match "
            f"one of {accepted_statuses!r}"
        ]
    return []


def _evaluate_scenario(
    scenario: dict,
    *,
    root: Path,
    commands: list[dict],
    response: dict,
    before: dict[str, tuple],
    workspace: Path,
    limits: dict,
    trace_aliases: tuple[tuple[str, str], ...] = (),
) -> dict:
    scenario_id = scenario["id"]
    failures: list[str] = []
    relevant = (
        commands if scenario_id == "missing-cli"
        else _scenario_commands(commands, root)
    )
    if len(relevant) > limits["commands_per_scenario"]:
        failures.append("scenario command trace exceeded its bound")
    forbidden = (".env", "api-secret", "glossabet-out", "graphify-out", "glossary.json")
    for command in relevant:
        lowered = command["command"].casefold()
        if any(token in lowered for token in forbidden):
            failures.append("agent command directly named an excluded/artifact path")
        installed_skill_read = (
            scenario_id == "missing-cli"
            and ".agents/skills/glossabet/skill.md" in lowered
            and re.search(r"\b(cat|sed)\b", lowered) is not None
        )
        bundled_runner_probe = (
            scenario_id == "missing-cli"
            and ".agents/skills/glossabet/scripts/run_glossabet.py" in lowered
            and re.search(r"\btest\s+-f\b|\[\s+-f\b", lowered) is not None
        )
        if (
            "inspect" not in lowered
            and "--version" not in lowered
            and not installed_skill_read
            and not bundled_runner_probe
        ):
            failures.append("agent used a non-engine command inside the scenario")

    observed: dict[str, object] = {}
    if scenario_id == "missing-cli":
        if any("inspect" in command["command"] for command in relevant):
            failures.append("missing engine scenario attempted inspect")
        skill_boundary_observed = any(
            ".agents/skills/glossabet/skill.md" in command["command"].casefold()
            or ".agents/skills/glossabet/scripts/run_glossabet.py"
            in command["command"].casefold()
            for command in relevant
        )
        if not skill_boundary_observed:
            failures.append("Codex did not use the installed standalone skill boundary")
        version_commands = [
            command for command in relevant if "--version" in command["command"]
        ]
        engine_failure_observed = (
            len(version_commands) == 1
            and version_commands[0].get("exit_code") not in {0, None}
            and "glossabet" in version_commands[0]["output"].casefold()
        )
        if not engine_failure_observed:
            failures.append("missing CLI was not observed as an engine failure")
        observed["standalone_skill_boundary_observed"] = skill_boundary_observed
        # The observation records the engine-failure evidence itself, not
        # whether unrelated checks had already failed.
        observed["engine_missing"] = engine_failure_observed
    else:
        inspect_commands = [
            command for command in relevant if "inspect" in command["command"]
        ]
        if len(inspect_commands) != 1:
            failures.append(
                f"expected one attributable inspect command, found {len(inspect_commands)}"
            )
        elif scenario_id in {"malformed", "oversized", "symlinked"}:
            command = inspect_commands[0]
            if command.get("exit_code") == 0:
                failures.append("invalid direct input did not stop inspect")
            if not _expected_error(scenario_id, command["output"]):
                failures.append("inspect error did not identify the direct-input cause")
            observed["inspect_exit_code"] = command.get("exit_code")
            observed["error_sha256"] = hashlib.sha256(
                command["output"].encode()
            ).hexdigest()
        else:
            command = inspect_commands[0]
            if command.get("exit_code") != 0:
                failures.append("valid scenario inspect failed")
            context = _extract_context(command["output"])
            if context is None:
                failures.append("valid scenario produced no parseable context JSON")
            else:
                context_failures, observed = _check_context(scenario_id, context)
                failures.extend(context_failures)

    failures.extend(_status_failures(scenario, response))
    if not isinstance(response.get("facts"), list) or not response["facts"]:
        failures.append("agent returned no scenario facts")
    elif scenario_id in {"markdown-glossary", "both-glossaries"}:
        facts_text = "\n".join(
            item for item in response["facts"] if isinstance(item, str)
        )
        if "GLOSSARY.md" not in facts_text:
            failures.append(
                "agent facts did not acknowledge the repository GLOSSARY.md"
            )
        if MARKDOWN_GLOSSARY_CANARY in facts_text:
            failures.append(
                "agent read the repository GLOSSARY.md during Step 0"
            )
    if not isinstance(response.get("next_action"), str) or not response[
        "next_action"
    ].strip():
        failures.append("agent returned no next action")

    after = _snapshot(root)
    writes = _unexpected_writes(before, after)
    if writes:
        failures.append(f"unexpected repository writes: {writes}")

    return {
        "id": scenario_id,
        "delivery": scenario["delivery"],
        "passed": not failures,
        "failures": failures,
        "observed": observed,
        "agent_response": response,
        "unexpected_writes": writes,
        "trace": [
            _trace_summary(command, workspace, limits, trace_aliases)
            for command in relevant
        ],
    }


def _evaluate_session_hook(
    scenario: dict,
    *,
    root: Path,
    commands: list[dict],
    response: dict,
    before: dict[str, tuple],
    workspace: Path,
    limits: dict,
) -> dict:
    failures: list[str] = []
    if "glossabet" in HOOK_PROMPT.casefold():
        failures.append("session-hook user prompt named Glossabet")
    if commands:
        failures.append("session-hook agent ran a command or tool")

    failures.extend(_status_failures(scenario, response))
    facts = response.get("facts")
    facts_text = "\n".join(facts) if isinstance(facts, list) and all(
        isinstance(item, str) for item in facts
    ) else ""
    if not facts_text:
        failures.append("session-hook agent returned no facts")
    if HOOK_TERM not in facts_text:
        failures.append("session-hook context lost the canonical term")
    if HOOK_DEFINITION not in facts_text:
        failures.append("session-hook context lost the canonical definition")
    response_text = json.dumps(response, ensure_ascii=False)
    if HOOK_PROPOSED_TERM in response_text:
        failures.append("session-hook exposed a proposed term as settled context")
    if HOOK_SOURCE_CANARY in response_text:
        failures.append("session-hook exposed repository source text")
    if not isinstance(response.get("next_action"), str) or not response[
        "next_action"
    ].strip():
        failures.append("session-hook agent returned no next action")

    after = _snapshot(root)
    writes = changed_paths(before, after)
    if writes:
        failures.append(f"session-hook wrote repository paths: {writes}")

    return {
        "id": scenario["id"],
        "delivery": scenario["delivery"],
        "passed": not failures,
        "failures": failures,
        "observed": {
            "agent_command_count": len(commands),
            "canonical_term_seen": HOOK_TERM in facts_text,
            "canonical_definition_seen": HOOK_DEFINITION in facts_text,
            "proposed_term_absent": HOOK_PROPOSED_TERM not in response_text,
            "source_text_absent": HOOK_SOURCE_CANARY not in response_text,
            "user_prompt_mentions_glossabet": (
                "glossabet" in HOOK_PROMPT.casefold()
            ),
            "user_prompt_sha256": hashlib.sha256(HOOK_PROMPT.encode()).hexdigest(),
        },
        "agent_response": response,
        "unexpected_writes": writes,
        "trace": [
            _trace_summary(command, workspace, limits) for command in commands
        ],
    }


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
            "allowed_statuses": _accepted_statuses(scenario),
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
    _make_scenario(missing_root, "missing-cli")
    _install_standalone_skill(
        missing_root / ".agents" / "skills" / "glossabet"
    )
    missing_before = _snapshot(missing_root)
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
    response_items = _response_by_id(response, ["missing-cli"])
    result = _evaluate_scenario(
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
            _make_scenario(root, scenario["id"])
            before[scenario["id"]] = _snapshot(root)
        environment = {
            **os.environ,
            "GLOSSABET_CACHE_DIR": str(batch / ".engine-cache"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        hook_root = work / "session-hook-run"
        _make_scenario(hook_root, "session-hook")
        hook_before = _snapshot(hook_root)
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
            hook_response_items = _response_by_id(
                hook_response, ["session-hook"]
            )
            hook_result = _evaluate_session_hook(
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
            version_command = _installed_version_command(
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
                _trace_summary(command, batch, limits, trace_aliases)
                for command in commands
                if command in glossabet_skill_reads
                and command is not version_command
            ]
            allowed_reads = max(0, limits["commands_per_scenario"] - 1)
            delivery_trace = [
                _trace_summary(version_command, batch, limits, trace_aliases)
            ] + skill_read_summaries[:allowed_reads]
            delivery_trace_truncated = len(skill_read_summaries) > allowed_reads
            response_items = _response_by_id(
                response, [scenario["id"] for scenario in plugin_scenarios]
            )
            for scenario in plugin_scenarios:
                scenario_id = scenario["id"]
                results.append(_evaluate_scenario(
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
