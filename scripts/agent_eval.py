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
SCENARIOS_PATH = ROOT / "evaluation" / "agent-scenarios.json"
PROMPT_PATH = ROOT / "evaluation" / "agent-prompt.md"
RESPONSE_SCHEMA_PATH = ROOT / "evaluation" / "agent-response-schema.json"
DEFAULT_RESULTS = ROOT / "evaluation" / "agent-results.json"
PLUGIN = ROOT / "plugins" / "glossabet"
CANONICAL_SKILL = ROOT / "skill" / "SKILL.md"
RESULT_SCHEMA_VERSION = 2
SENSITIVE_CANARY = "GLOSSABET_SENSITIVE_CANARY_MUST_NOT_APPEAR"

sys.path.insert(0, str(ROOT))

from glossabet import __version__  # noqa: E402
from glossabet.artifacts import MAX_JSON_BYTES  # noqa: E402
from glossabet.scanner import is_sensitive  # noqa: E402


class AgentEvaluationError(RuntimeError):
    """The host run or its captured evidence violated the scenario contract."""


def _fail(message: str) -> None:
    raise AgentEvaluationError(message)


def _dotenv_part(name: str) -> bool:
    return (
        name == ".env"
        or name.endswith(".env")
        or name.startswith(".env.")
        or ".env." in name
    )


def _read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError, RecursionError) as exc:
        _fail(f"{label} is unreadable: {exc}")
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    files: list[Path] = []
    for current, directories, names in os.walk(root):
        directories[:] = sorted(
            name for name in directories if not _dotenv_part(name)
        )
        for name in sorted(names):
            if not _dotenv_part(name):
                files.append(Path(current) / name)
    for path in sorted(files):
        relative = path.relative_to(root).as_posix().encode()
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _input_identity() -> dict:
    return {
        "evaluator_sha256": _sha256(Path(__file__).resolve()),
        "scenario_manifest_sha256": _sha256(SCENARIOS_PATH),
        "prompt_sha256": _sha256(PROMPT_PATH),
        "response_schema_sha256": _sha256(RESPONSE_SCHEMA_PATH),
        "canonical_skill_sha256": _sha256(CANONICAL_SKILL),
        "plugin_sha256": _tree_sha256(PLUGIN),
        "engine_version": __version__,
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


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
        _fail(f"command exited {result.returncode}: {shown}: {detail}")
    if not parse_json:
        return result.stdout
    try:
        value = json.loads(result.stdout)
    except (ValueError, RecursionError) as exc:
        _fail(f"command returned malformed JSON: {shown}: {exc}")
    if not isinstance(value, dict):
        _fail(f"command JSON was not an object: {shown}")
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
        _fail(result.stderr.strip() or result.stdout.strip() or "git failed")
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
    _write_json(
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
    _ordinary_repo(root)
    if scenario_id == "malformed":
        _glossary_path(root).write_text("{not-json", encoding="utf-8")
    elif scenario_id == "oversized":
        with _glossary_path(root).open("wb") as handle:
            handle.truncate(MAX_JSON_BYTES + 1)
    elif scenario_id == "symlinked":
        target = root / "outside-glossary.json"
        _write_json(target, {"schema_version": 1, "concepts": []})
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
        _write_json(
            root / "package.json",
            {"private": True, "workspaces": ["packages/*"]},
        )
        for name in ("alpha", "beta", "gamma"):
            package = root / "packages" / name
            package.mkdir(parents=True)
            _write_json(package / "package.json", {"name": name})
            (package / "index.js").write_text(
                f"export const {name}Service = true;\n", encoding="utf-8"
            )
    elif scenario_id == "resumed-glossary":
        _write_json(
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
    elif scenario_id == "sensitive-file":
        dotenv = root / ".env"
        dotenv.touch()
        dotenv.chmod(0)
        sensitive = root / "api-secret.txt"
        sensitive.write_text(SENSITIVE_CANARY, encoding="utf-8")
        sensitive.chmod(0)
    elif scenario_id not in {"absent", "missing-cli"}:
        _fail(f"unknown scenario fixture: {scenario_id}")


def _snapshot(root: Path) -> dict[str, tuple]:
    snapshot: dict[str, tuple] = {}
    for current, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(
            name
            for name in directories
            if name != ".git" and not _dotenv_part(name)
        )
        for name in sorted(names):
            if _dotenv_part(name):
                continue
            path = Path(current) / name
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            if path.is_symlink():
                snapshot[relative] = ("symlink", os.readlink(path))
            elif is_sensitive(name):
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
    changed = sorted(
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )
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
        _fail(result.stderr.strip() or "could not run codex --version")
    match = re.search(r"codex-cli\s+([^\s]+)", result.stdout)
    if match is None:
        _fail(f"unrecognized Codex version output: {result.stdout!r}")
    return match.group(1)


def _parse_events(raw: str, limits: dict) -> list[dict]:
    encoded = raw.encode("utf-8")
    if len(encoded) > limits["jsonl_bytes"]:
        _fail(
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
            _fail(f"Codex emitted non-JSON stdout: {line[:200]!r}: {exc}")
        if not isinstance(event, dict):
            _fail("Codex JSONL event was not an object")
        events.append(event)
    if len(events) > limits["events"]:
        _fail(
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
            _fail("Codex command trace is malformed")
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


def _extract_context(output: str) -> dict | None:
    stripped = output.strip()
    if not stripped.startswith("{"):
        return None
    try:
        value = json.loads(stripped)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _run_codex(
    codex: str,
    *,
    workspace: Path,
    prompt: str,
    environment: dict[str, str],
    limits: dict,
) -> tuple[dict, list[dict], dict]:
    final_path = workspace / "agent-final.json"
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
        "--output-schema",
        str(RESPONSE_SCHEMA_PATH),
        "--output-last-message",
        str(final_path),
        "--cd",
        str(workspace),
        prompt,
    ]
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
        _fail("sensitive canary appeared in the Codex trace")
    events = _parse_events(result.stdout, limits)
    if result.returncode:
        _fail(
            f"codex exec exited {result.returncode}: "
            f"{result.stderr[-2000:] or result.stdout[-2000:]}"
        )
    response = _read_json(final_path, "Codex final response")
    if SENSITIVE_CANARY in json.dumps(response):
        _fail("sensitive canary appeared in the Codex final response")
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
        _fail("Codex response has no scenarios list")
    by_id: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            _fail("Codex returned a malformed scenario response")
        if item["id"] in by_id:
            _fail(f"Codex returned duplicate scenario {item['id']}")
        by_id[item["id"]] = item
    if list(by_id) != expected_ids:
        _fail(
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
    observed: dict[str, object] = {
        "context_schema_version": context.get("context_schema_version"),
        "generator": context.get("generator"),
        "freshness": context.get("freshness", {}).get("status"),
        "corpus_complete": context.get("coverage", {}).get("corpus", {}).get(
            "complete"
        ),
        "context_complete": context.get("coverage", {}).get("context", {}).get(
            "complete"
        ),
    }
    if context.get("context_schema_version") != 1:
        failures.append("context schema was not 1")
    if context.get("generator") != {"name": "glossabet", "version": __version__}:
        failures.append("context generator did not match the installed engine")
    if observed["freshness"] != "current":
        failures.append("inspect did not return invocation-current context")
    if observed["corpus_complete"] is not True:
        failures.append("scenario unexpectedly had partial scanner coverage")

    structural = context.get("structural_groups", {})
    glossary = context.get("glossary", {})
    if scenario_id == "fresh":
        observed["graph_freshness"] = structural.get("freshness", {}).get("status")
        observed["graph_available"] = structural.get("available")
        if observed["graph_freshness"] != "current" or observed[
            "graph_available"
        ] is not True:
            failures.append("fresh Graphify input was not reported current/available")
    elif scenario_id == "stale":
        observed["graph_freshness"] = structural.get("freshness", {}).get("status")
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
        omissions = context.get("coverage", {}).get("context", {}).get(
            "omissions", []
        )
        observed["context_omissions"] = len(omissions)
        if observed["context_complete"] is not False or not omissions:
            failures.append("partial projection did not expose bounded omissions")
    elif scenario_id == "monorepo":
        observed["monorepo"] = context.get("monorepo")
        if context.get("monorepo", {}).get("detected") is not True:
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
    elif scenario_id == "sensitive-file":
        skipped = context.get("skipped", {}).get("sensitive", [])
        observed["sensitive_paths"] = skipped
        if set(skipped) != {".env", "api-secret.txt"}:
            failures.append("sensitive paths were not both excluded and reported")
        if SENSITIVE_CANARY in json.dumps(context):
            failures.append("sensitive canary entered the agent context")

    if scenario_id != "partial" and observed["context_complete"] is not True:
        failures.append("scenario unexpectedly had partial agent projection")
    return failures, observed


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
        if not any(
            ".agents/skills/glossabet/SKILL.md" in command["command"]
            for command in relevant
        ):
            failures.append("Codex did not load the installed canonical skill")
        version_commands = [
            command for command in relevant if "--version" in command["command"]
        ]
        if (
            len(version_commands) != 1
            or version_commands[0].get("exit_code") in {0, None}
            or "glossabet" not in version_commands[0]["output"].casefold()
        ):
            failures.append("missing CLI was not observed as an engine failure")
        observed["engine_missing"] = not failures
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
        elif inspect_commands:
            command = inspect_commands[0]
            if command.get("exit_code") != 0:
                failures.append("valid scenario inspect failed")
            context = _extract_context(command["output"])
            if context is None:
                failures.append("valid scenario produced no parseable context JSON")
            else:
                context_failures, observed = _check_context(scenario_id, context)
                failures.extend(context_failures)

    accepted_statuses = scenario.get(
        "accepted_statuses", [scenario["expected_status"]]
    )
    if response.get("status") not in accepted_statuses:
        failures.append(
            f"agent status {response.get('status')!r} did not match "
            f"one of {accepted_statuses!r}"
        )
    if not isinstance(response.get("facts"), list) or not response["facts"]:
        failures.append("agent returned no scenario facts")
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


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if _dotenv_part(name)}


def _prepare_marketplace(root: Path, name: str) -> None:
    shutil.copytree(
        PLUGIN,
        root / "plugins" / "glossabet",
        ignore=_copy_ignore,
    )
    _write_json(
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
        isinstance(item, dict) and item.get("name") == "glossabet"
        for item in installed
    ):
        _fail("a Glossabet plugin is already installed; refusing to replace it")


def _install_plugin(
    codex: str,
    marketplace: Path,
    marketplace_name: str,
) -> tuple[str, Path, Path]:
    plugin_id = f"glossabet@{marketplace_name}"
    added = _run(
        [codex, "plugin", "marketplace", "add", str(marketplace), "--json"],
        cwd=ROOT,
        parse_json=True,
    )
    assert isinstance(added, dict)
    if added.get("marketplaceName") != marketplace_name:
        _fail("Codex registered the temporary marketplace under another name")
    installed = _run(
        [codex, "plugin", "add", plugin_id, "--json"],
        cwd=ROOT,
        parse_json=True,
    )
    assert isinstance(installed, dict)
    path = Path(str(installed.get("installedPath", "")))
    expected_cache = Path.home() / ".codex" / "plugins" / "cache"
    expected_parent = expected_cache / marketplace_name
    if (
        installed.get("version") != __version__
        or not path.is_absolute()
        or path.name != __version__
        or path.parent.name != "glossabet"
        or path.parents[1] != expected_parent
    ):
        _fail(f"Codex returned an unexpected plugin installation: {installed}")
    runner = path / "skills" / "glossabet" / "scripts" / "run_glossabet.py"
    if not runner.is_file():
        _fail("installed plugin has no skill-local runner")
    return plugin_id, path, expected_parent


def _cleanup_plugin(
    codex: str,
    plugin_id: str,
    marketplace_name: str,
    cache_parent: Path | None,
) -> None:
    errors = []
    try:
        _run(
            [codex, "plugin", "remove", plugin_id, "--json"],
            cwd=ROOT,
            parse_json=True,
        )
    except Exception as exc:  # preserve all narrowly scoped cleanup failures
        errors.append(str(exc))
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
            isinstance(item, dict) and item.get("pluginId") == plugin_id
            for item in plugin_data.get("installed", [])
        ):
            errors.append("temporary plugin remains installed")
        if any(
            isinstance(item, dict) and item.get("name") == marketplace_name
            for item in marketplace_data.get("marketplaces", [])
        ):
            errors.append("temporary marketplace remains configured")
    except Exception as exc:
        errors.append(str(exc))
    if errors:
        _fail("; ".join(errors))


def _prompt_for(scenarios: list[dict], roots: dict[str, Path]) -> str:
    supplied = [
        {
            "id": scenario["id"],
            "path": str(roots[scenario["id"]]),
            "description": scenario["description"],
            "allowed_statuses": scenario.get(
                "accepted_statuses", [scenario["expected_status"]]
            ),
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
        _fail("standalone installed skill differs from canonical source")
    if (destination / "scripts" / "run_glossabet.py").exists():
        _fail("standalone missing-CLI scenario unexpectedly has a plugin runner")


def _validate_manifest(manifest: dict) -> tuple[list[dict], dict]:
    if manifest.get("schema_version") != 1:
        _fail("unsupported agent scenario manifest")
    scenarios = manifest.get("scenarios")
    limits = manifest.get("trace_limits")
    if not isinstance(scenarios, list) or not isinstance(limits, dict):
        _fail("agent scenario manifest is malformed")
    expected_ids = [
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
    if [item.get("id") for item in scenarios if isinstance(item, dict)] != expected_ids:
        _fail("agent scenario ids/order do not match the Phase 22 contract")
    status_vocabulary = {
        "grounded",
        "grounded-with-warning",
        "grounded-partial",
        "choice-required",
        "resumed",
        "stopped",
    }
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            _fail("agent scenario is malformed")
        expected = scenario.get("expected_status")
        accepted = scenario.get("accepted_statuses", [expected])
        if (
            expected not in status_vocabulary
            or not isinstance(accepted, list)
            or not accepted
            or expected not in accepted
            or any(status not in status_vocabulary for status in accepted)
        ):
            _fail(f"agent scenario {scenario.get('id')} has invalid statuses")
    required_limits = {
        "jsonl_bytes",
        "events",
        "commands_per_scenario",
        "stored_command_characters",
        "stored_output_characters",
    }
    if set(limits) != required_limits or not all(
        isinstance(value, int) and not isinstance(value, bool) and value > 0
        for value in limits.values()
    ):
        _fail("agent trace limits are malformed")
    return scenarios, limits


def _run_missing_cli_scenario(
    codex: str,
    scenario: dict,
    limits: dict,
    work: Path,
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
    manifest = _read_json(SCENARIOS_PATH, "agent scenario manifest")
    scenarios, limits = _validate_manifest(manifest)
    scenario = next(item for item in scenarios if item["id"] == "missing-cli")
    codex = shutil.which("codex")
    if codex is None:
        _fail("codex is not installed")
    codex = str(Path(codex).resolve())
    with tempfile.TemporaryDirectory(prefix="glossabet-missing-cli-probe-") as raw:
        result, usage = _run_missing_cli_scenario(
            codex, scenario, limits, Path(raw)
        )
    return {
        "codex_version": _codex_version(codex),
        "scenario": result,
        "usage": usage,
    }


def run_evaluation(output: Path = DEFAULT_RESULTS) -> dict:
    manifest = _read_json(SCENARIOS_PATH, "agent scenario manifest")
    scenarios, limits = _validate_manifest(manifest)
    codex = shutil.which("codex")
    if codex is None:
        _fail("codex is not installed")
    codex = str(Path(codex).resolve())
    codex_version = _codex_version(codex)
    _ensure_no_installed_glossabet(codex)

    plugin_scenarios = [
        scenario for scenario in scenarios if scenario["delivery"] == "plugin"
    ]
    missing_scenario = next(
        scenario for scenario in scenarios if scenario["id"] == "missing-cli"
    )
    results: list[dict] = []
    usages: list[dict] = []
    delivery_trace: list[dict] = []

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

        primary_error: Exception | None = None
        try:
            plugin_id, installed_path, cache_parent = _install_plugin(
                codex, marketplace, marketplace_name
            )
            response, commands, usage = _run_codex(
                codex,
                workspace=batch,
                prompt=_prompt_for(plugin_scenarios, roots),
                environment=environment,
                limits=limits,
            )
            usages.append(usage)
            version_commands = [
                command
                for command in commands
                if str(installed_path) in command["command"]
                and "--version" in command["command"]
            ]
            if len(version_commands) != 1 or version_commands[0][
                "output"
            ].strip() != f"glossabet {__version__}":
                _fail("installed plugin engine was not version-checked exactly once")
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
                _fail("Codex did not read the temporarily installed plugin skill")
            if any(
                str(installed_skill) not in command["command"]
                for command in glossabet_skill_reads
            ):
                _fail("Codex read a different Glossabet skill during the plugin run")
            trace_aliases = ((str(installed_path), "<INSTALLED_PLUGIN>"),)
            delivery_trace = [
                _trace_summary(command, batch, limits, trace_aliases)
                for command in commands
                if command in glossabet_skill_reads or command in version_commands
            ]
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
        except Exception as exc:
            primary_error = exc
        finally:
            try:
                _cleanup_plugin(
                    codex,
                    plugin_id,
                    marketplace_name,
                    cache_parent,
                )
            except Exception as cleanup_exc:
                if primary_error is None:
                    primary_error = cleanup_exc
                else:
                    primary_error = AgentEvaluationError(
                        f"{primary_error}; cleanup also failed: {cleanup_exc}"
                    )
        if primary_error is not None:
            raise primary_error

        missing_result, missing_usage = _run_missing_cli_scenario(
            codex, missing_scenario, limits, work
        )
        usages.append(missing_usage)
        results.append(missing_result)

    ordered = {result["id"]: result for result in results}
    results = [ordered[scenario["id"]] for scenario in scenarios]
    passed = sum(result["passed"] for result in results)
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "inputs": _input_identity(),
        "environment": {
            "codex_version": codex_version,
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "method": {
            "host_runs": 2,
            "codex_exec_ephemeral": True,
            "sandbox": "workspace-write",
            "approval_policy": "never",
            "plugin_lifecycle": "temporary install and complete removal",
            "trace_limits": limits,
            "model": "configured default; Codex CLI JSONL did not report it",
        },
        "delivery": {
            "installed_plugin_skill_read": True,
            "installed_plugin_engine_version_checked": True,
            "standalone_skill_read": True,
            "temporary_plugin_state_removed": True,
            "trace": delivery_trace,
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


def verify_results(path: Path = DEFAULT_RESULTS) -> list[str]:
    errors: list[str] = []
    manifest = _read_json(SCENARIOS_PATH, "agent scenario manifest")
    scenarios, limits = _validate_manifest(manifest)
    result = _read_json(path, "agent evaluation results")
    if result.get("schema_version") != RESULT_SCHEMA_VERSION:
        errors.append("agent result schema is stale")
    if result.get("inputs") != _input_identity():
        errors.append("agent evaluation inputs are stale")
    method = result.get("method", {})
    if (
        method.get("host_runs") != 2
        or method.get("codex_exec_ephemeral") is not True
        or method.get("sandbox") != "workspace-write"
        or method.get("approval_policy") != "never"
        or method.get("trace_limits") != limits
    ):
        errors.append("agent evaluation method is weakened or stale")
    delivery = result.get("delivery", {})
    delivery_trace = delivery.get("trace") if isinstance(delivery, dict) else None
    if (
        not isinstance(delivery, dict)
        or delivery.get("installed_plugin_skill_read") is not True
        or delivery.get("installed_plugin_engine_version_checked") is not True
        or delivery.get("standalone_skill_read") is not True
        or delivery.get("temporary_plugin_state_removed") is not True
        or not isinstance(delivery_trace, list)
        or len(delivery_trace) > limits["commands_per_scenario"]
        or not any(
            "<INSTALLED_PLUGIN>/skills/glossabet/SKILL.md"
            in str(command.get("command", ""))
            for command in delivery_trace
            if isinstance(command, dict)
        )
        or not any(
            "<INSTALLED_PLUGIN>/skills/glossabet/scripts/run_glossabet.py"
            in str(command.get("command", ""))
            and "--version" in str(command.get("command", ""))
            for command in delivery_trace
            if isinstance(command, dict)
        )
    ):
        errors.append("installed-skill delivery evidence is missing or stale")
    items = result.get("scenarios")
    if not isinstance(items, list):
        errors.append("agent scenario results are missing")
        items = []
    expected_ids = [scenario["id"] for scenario in scenarios]
    if [item.get("id") for item in items if isinstance(item, dict)] != expected_ids:
        errors.append("agent scenario result ids/order are stale")
    for item in items:
        if not isinstance(item, dict):
            errors.append("agent scenario result is malformed")
            continue
        scenario_id = item.get("id", "<unknown>")
        if item.get("passed") is not True or item.get("failures") != []:
            errors.append(f"{scenario_id}: installed-agent scenario does not pass")
        if item.get("unexpected_writes") != []:
            errors.append(f"{scenario_id}: unexpected writes are recorded")
        trace = item.get("trace")
        if not isinstance(trace, list) or len(trace) > limits[
            "commands_per_scenario"
        ]:
            errors.append(f"{scenario_id}: trace is missing or unbounded")
            continue
        for command in trace:
            if (
                not isinstance(command, dict)
                or len(str(command.get("command", "")))
                > limits["stored_command_characters"] + 1
                or len(str(command.get("output_preview", "")))
                > limits["stored_output_characters"] + 1
            ):
                errors.append(f"{scenario_id}: stored trace exceeds its bound")
                break
    summary = result.get("summary", {})
    if summary != {
        "required": len(scenarios),
        "passed": len(scenarios),
        "failed": 0,
        "all_passed": True,
    }:
        errors.append("agent scenario summary does not record a complete pass")
    environment = result.get("environment", {})
    if not isinstance(environment.get("codex_version"), str):
        errors.append("agent results do not identify the Codex CLI version")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--run", action="store_true")
    action.add_argument("--probe-missing-cli", action="store_true")
    action.add_argument("--verify-results", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args(argv)
    try:
        if args.run:
            result = run_evaluation(args.output)
            summary = result["summary"]
            print(
                f"installed-agent evaluation: {summary['passed']}/"
                f"{summary['required']} scenarios passed"
            )
            return 0 if summary["all_passed"] else 1
        if args.probe_missing_cli:
            probe = probe_missing_cli()
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
        errors = verify_results(args.verify_results)
        if errors:
            for error in errors:
                print(f"agent evaluation verification: {error}", file=sys.stderr)
            return 1
        print("installed-agent evidence matches the current scenarios and bundle")
        return 0
    except (AgentEvaluationError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"agent evaluation: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
