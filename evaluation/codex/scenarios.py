"""Codex scenario contract and judgments.

``validate_manifest`` pins the scenario manifest's shape. The evaluation
functions judge one scenario from what the host observed — the agent's
structured response, the relevant command trace, and the fixture snapshot
before and after — and return a typed result with every failure named.
Nothing here runs Codex or touches a plugin; fixtures are built in
``evaluation.codex.fixtures``.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from evaluation.codex.contract import (
    HOOK_DEFINITION,
    HOOK_PROMPT,
    HOOK_PROPOSED_TERM,
    HOOK_SOURCE_CANARY,
    HOOK_TERM,
    MARKDOWN_GLOSSARY_CANARY,
    MARKDOWN_GLOSSARY_TEXT,
    REQUIRED_SCENARIO_IDS,
    SENSITIVE_CANARY,
    STATUS_VOCABULARY,
    fail,
    mapping,
)
from evaluation.codex.fixtures import snapshot, unexpected_writes
from evaluation.codex.trace import extract_context, scenario_commands, trace_summary
from evaluation.harness.io import changed_paths
from glossabet import __version__
from glossabet.agent.agent_context_protocol import AGENT_CONTEXT_SCHEMA_VERSION


def validate_manifest(manifest: dict) -> tuple[list[dict], dict]:
    if manifest.get("schema_version") != 1:
        fail("unsupported agent scenario manifest")
    scenarios = manifest.get("scenarios")
    limits = manifest.get("trace_limits")
    if not isinstance(scenarios, list) or not isinstance(limits, dict):
        fail("agent scenario manifest is malformed")
    expected_ids = list(REQUIRED_SCENARIO_IDS)
    if [item.get("id") for item in scenarios if isinstance(item, dict)] != expected_ids:
        fail("agent scenario ids/order do not match the current contract")
    status_vocabulary = STATUS_VOCABULARY
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            fail("agent scenario is malformed")
        expected = scenario.get("expected_status")
        accepted = scenario.get("accepted_statuses", [expected])
        description = scenario.get("description")
        if not isinstance(description, str) or not description.strip():
            fail(f"agent scenario {scenario.get('id')} has no description")
        if (
            expected not in status_vocabulary
            or not isinstance(accepted, list)
            or not accepted
            or expected not in accepted
            or any(status not in status_vocabulary for status in accepted)
        ):
            fail(f"agent scenario {scenario.get('id')} has invalid statuses")
        expected_delivery = (
            "plugin-hook"
            if scenario.get("id") == "session-hook"
            else "standalone-skill"
            if scenario.get("id") == "missing-cli"
            else "plugin"
        )
        if scenario.get("delivery") != expected_delivery:
            fail(f"agent scenario {scenario.get('id')} has invalid delivery")
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
        fail("agent trace limits are malformed")
    return scenarios, limits


def response_by_id(response: dict, expected_ids: list[str]) -> dict[str, dict]:
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


def expected_error(scenario_id: str, output: str) -> bool:
    lowered = output.casefold()
    required = {
        "malformed": ("glossary", "unreadable"),
        "oversized": ("glossary", "larger than"),
        "symlinked": ("glossary", "symlink"),
    }[scenario_id]
    return all(part in lowered for part in required)


def check_context(scenario_id: str, context: dict) -> tuple[list[str], dict]:
    failures = []
    coverage = mapping(context.get("coverage"))
    projection_ledger = mapping(coverage.get("context"))
    record_fields = (
        "intentional_exclusions",
        "source_omissions",
        "truncations",
    )
    records: dict[str, list[dict]] = {}
    for field in record_fields:
        value = projection_ledger.get(field)
        if not isinstance(value, list):
            failures.append(f"context {field} was not a list")
            value = []
        valid_records: list[dict] = []
        malformed = False
        for item in value:
            if (
                not isinstance(item, dict)
                or set(item) != {"path", "kind", "amount"}
                or not isinstance(item.get("path"), str)
                or not item["path"]
                or not isinstance(item.get("kind"), str)
                or not item["kind"]
                or not isinstance(item.get("amount"), int)
                or isinstance(item["amount"], bool)
                or item["amount"] <= 0
            ):
                malformed = True
                continue
            valid_records.append(item)
        if malformed:
            failures.append(f"context {field} contained malformed records")
        pairs = [(item["path"], item["kind"]) for item in valid_records]
        if len(pairs) != len(set(pairs)):
            failures.append(f"context {field} contained duplicate records")
        records[field] = valid_records
    observed: dict[str, object] = {
        "context_schema_version": context.get("context_schema_version"),
        "generator": context.get("generator"),
        "freshness": mapping(context.get("freshness")).get("status"),
        "corpus_complete": mapping(coverage.get("corpus")).get("complete"),
        "projection_complete": projection_ledger.get("projection_complete"),
        "source_complete": projection_ledger.get("source_complete"),
        "context_projection": projection_ledger.get("projection"),
        "intentional_exclusions": len(records["intentional_exclusions"]),
        "source_omissions": len(records["source_omissions"]),
        "truncations": len(records["truncations"]),
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
    if observed["source_complete"] is not True:
        failures.append("scenario unexpectedly had incomplete projection sources")
    expected_projection_complete = scenario_id != "partial"
    if observed["projection_complete"] is not expected_projection_complete:
        failures.append(
            "projection completeness did not match the scenario's applied limits"
        )

    intentional_pairs = {
        (item.get("path"), item.get("kind"))
        for item in records["intentional_exclusions"]
        if isinstance(item, dict)
    }
    truncation_pairs = {
        (item.get("path"), item.get("kind"))
        for item in records["truncations"]
        if isinstance(item, dict)
    }
    required_lean_exclusions = {
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
    if not required_lean_exclusions <= intentional_pairs:
        failures.append(
            "lean projection did not account for its intentional exclusions"
        )
    allowed_lean_exclusions = required_lean_exclusions | {
        (
            "vocabulary.doc_terms.items.*.locations",
            "file_locations_rolled_up",
        ),
    }
    if any(
        (item["path"], item["kind"]) not in allowed_lean_exclusions
        for item in records["intentional_exclusions"]
    ):
        failures.append(
            "context intentional_exclusions contained unexpected records"
        )
    if any(
        item["path"] == "imports"
        and item["kind"] == "section_excluded"
        and item["amount"] != 1
        for item in records["intentional_exclusions"]
    ):
        failures.append("context imports exclusion amount was not 1")

    structural = mapping(context.get("structural_groups"))
    glossary = mapping(context.get("glossary"))
    if scenario_id == "fresh":
        observed["graph_freshness"] = mapping(structural.get("freshness")).get("status")
        observed["graph_usable"] = structural.get("usable")
        if observed["graph_freshness"] != "current" or observed[
            "graph_usable"
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
        ) not in truncation_pairs:
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
        if records["truncations"] or records["source_omissions"]:
            failures.append(
                "scenario unexpectedly exceeded the standard lean projection"
            )
    return failures, observed


def accepted_statuses(scenario: dict) -> list:
    return scenario.get("accepted_statuses", [scenario["expected_status"]])


def status_failures(scenario: dict, response: dict) -> list[str]:
    accepted = accepted_statuses(scenario)
    if response.get("status") not in accepted:
        return [
            f"agent status {response.get('status')!r} did not match "
            f"one of {accepted!r}"
        ]
    return []


def evaluate_scenario(
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
        else scenario_commands(commands, root)
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
            if not expected_error(scenario_id, command["output"]):
                failures.append("inspect error did not identify the direct-input cause")
            observed["inspect_exit_code"] = command.get("exit_code")
            observed["error_sha256"] = hashlib.sha256(
                command["output"].encode()
            ).hexdigest()
        else:
            command = inspect_commands[0]
            if command.get("exit_code") != 0:
                failures.append("valid scenario inspect failed")
            context = extract_context(command["output"])
            if context is None:
                failures.append("valid scenario produced no parseable context JSON")
            else:
                context_failures, observed = check_context(scenario_id, context)
                failures.extend(context_failures)

    failures.extend(status_failures(scenario, response))
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

    after = snapshot(root)
    writes = unexpected_writes(before, after)
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
            trace_summary(command, workspace, limits, trace_aliases)
            for command in relevant
        ],
    }


def evaluate_session_hook(
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

    failures.extend(status_failures(scenario, response))
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

    after = snapshot(root)
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
            trace_summary(command, workspace, limits) for command in commands
        ],
    }
