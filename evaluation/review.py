#!/usr/bin/env python3
"""Build and verify the blinded second-reviewer evaluation lane."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.run import (  # noqa: E402
    DEFAULT_MANIFEST,
    DEFAULT_RESULTS,
    EvaluationError,
    verify_results as verify_engine_results,
)

PACKET_SCHEMA_VERSION = 1
REVIEW_SCHEMA_VERSION = 2
DEFAULT_PACKET = PROJECT_ROOT / "evaluation" / "reviewer-packet.json"
DEFAULT_REVIEW_RESULTS = PROJECT_ROOT / "evaluation" / "reviewer-results.json"
PROMPT_PATH = PROJECT_ROOT / "evaluation" / "reviewer-prompt.md"
RESPONSE_SCHEMA_PATH = PROJECT_ROOT / "evaluation" / "reviewer-response-schema.json"
SECONDARY_USEFULNESS_THRESHOLD = 0.8
TRACE_LIMITS = {
    "jsonl_bytes": 4_000_000,
    "events": 100,
    "commands": 3,
    "stored_command_characters": 1000,
    "stored_output_characters": 1000,
}


def _read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError, RecursionError) as exc:
        raise EvaluationError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise EvaluationError(f"{label} must be a JSON object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_sha256(value: dict) -> str:
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    return hashlib.sha256(encoded).hexdigest()


def _hex_digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _reviewer_input_identity() -> dict:
    return {
        "evaluator_sha256": _sha256(Path(__file__).resolve()),
        "prompt_sha256": _sha256(PROMPT_PATH),
        "response_schema_sha256": _sha256(RESPONSE_SCHEMA_PATH),
    }


def _codex_version(codex: str) -> str:
    result = subprocess.run(
        [codex, "--version"],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if result.returncode:
        raise EvaluationError(result.stderr.strip() or "could not run codex --version")
    match = re.search(r"codex-cli\s+([^\s]+)", result.stdout)
    if match is None:
        raise EvaluationError(f"unrecognized Codex version output: {result.stdout!r}")
    return match.group(1)


def _bounded_text(text: str, workspace: Path, limit: int) -> str:
    normalized = text.replace(str(workspace), "<REVIEW_WORKSPACE>")
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "…"


def _parse_reviewer_trace(raw: str, workspace: Path) -> tuple[list[dict], dict]:
    if len(raw.encode("utf-8")) > TRACE_LIMITS["jsonl_bytes"]:
        raise EvaluationError("second-reviewer JSONL exceeded its byte bound")
    events = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (ValueError, RecursionError) as exc:
            raise EvaluationError(f"second reviewer emitted non-JSON stdout: {exc}")
        if not isinstance(event, dict):
            raise EvaluationError("second-reviewer JSONL event was not an object")
        events.append(event)
    if len(events) > TRACE_LIMITS["events"]:
        raise EvaluationError("second-reviewer JSONL exceeded its event bound")

    commands = []
    disallowed_items = []
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in {"file_change", "mcp_tool_call", "web_search"}:
            disallowed_items.append(item_type)
        if item_type != "command_execution":
            continue
        command = item.get("command")
        output = item.get("aggregated_output", "")
        if not isinstance(command, str) or not isinstance(output, str):
            raise EvaluationError("second-reviewer command trace is malformed")
        lowered = command.casefold()
        if (
            "reviewer-packet.json" not in lowered
            or ".." in command
            or any(
                token in lowered
                for token in (
                    "evaluation/results",
                    "evaluation/corpus",
                    "reviewer-results",
                    "internet",
                    "curl ",
                    "wget ",
                )
            )
        ):
            raise EvaluationError(
                "second reviewer issued a command outside the blinded packet"
            )
        commands.append({
            "command": _bounded_text(
                command, workspace, TRACE_LIMITS["stored_command_characters"]
            ),
            "cwd": (
                _bounded_text(
                    item["cwd"],
                    workspace,
                    TRACE_LIMITS["stored_command_characters"],
                )
                if isinstance(item.get("cwd"), str) else None
            ),
            "exit_code": item.get("exit_code"),
            "status": item.get("status"),
            "output_characters": len(output),
            "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
            "output_preview": _bounded_text(
                output, workspace, TRACE_LIMITS["stored_output_characters"]
            ),
        })
    if disallowed_items:
        raise EvaluationError(
            f"second reviewer used disallowed tools: {sorted(set(disallowed_items))}"
        )
    if not commands or len(commands) > TRACE_LIMITS["commands"]:
        raise EvaluationError("second reviewer did not use a bounded packet-only trace")
    if any(command.get("exit_code") != 0 for command in commands):
        raise EvaluationError("second-reviewer packet read failed")

    usage = next(
        (
            event.get("usage", {})
            for event in reversed(events)
            if event.get("type") == "turn.completed"
        ),
        {},
    )
    return commands, usage


def _contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def build_packet(
    evaluation_results: dict,
    *,
    manifest_sha256: str,
) -> dict:
    findings = []
    sources = []
    seen: set[str] = set()
    for case in evaluation_results.get("cases", []):
        if not isinstance(case, dict):
            raise EvaluationError("evaluation case is malformed")
        source_id = case.get("id")
        sources.append({"id": source_id, **case.get("source", {})})
        for item in case.get("review_items", []):
            if not isinstance(item, dict):
                raise EvaluationError(f"{source_id}: review item is malformed")
            key = item.get("review_key")
            if not isinstance(key, str) or not key or key in seen:
                raise EvaluationError("review keys must be unique non-empty strings")
            seen.add(key)
            if _contains_key(item, "useful"):
                raise EvaluationError("review packet input contains a usefulness label")
            findings.append(item)
    if not findings:
        raise EvaluationError("review packet needs at least one emitted finding")
    return {
        "schema_version": PACKET_SCHEMA_VERSION,
        "evaluation_manifest_sha256": manifest_sha256,
        "engine": evaluation_results.get("engine"),
        "question": (
            "Would showing this finding to a regular maintainer help a focused "
            "vocabulary review? Correct-but-actionless noise is not useful."
        ),
        "sources": sources,
        "findings": findings,
    }


def expected_packet(
    manifest_path: Path = DEFAULT_MANIFEST,
    evaluation_path: Path = DEFAULT_RESULTS,
) -> dict:
    engine_errors = verify_engine_results(
        evaluation_path, manifest_path, current=True
    )
    if engine_errors:
        raise EvaluationError(
            "cannot build reviewer packet from stale evaluation results: "
            + "; ".join(engine_errors)
        )
    evaluation_results = _read_json(evaluation_path, "evaluation results")
    return build_packet(
        evaluation_results,
        manifest_sha256=_sha256(manifest_path),
    )


def write_packet(
    path: Path,
    manifest_path: Path = DEFAULT_MANIFEST,
    evaluation_path: Path = DEFAULT_RESULTS,
) -> dict:
    packet = expected_packet(manifest_path, evaluation_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(packet, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return packet


def _primary_labels(manifest: dict) -> dict[str, bool]:
    labels: dict[str, bool] = {}
    for source in manifest["sources"]:
        source_id = source["id"]
        for surface in ("terminology", "drift", "structural"):
            expectation = source.get("expectations", {}).get(surface)
            if not isinstance(expectation, dict):
                continue
            for item in expectation.get("correct", []):
                key = f"{source_id}|{surface}|{item['key']}"
                if key in labels:
                    raise EvaluationError(f"duplicate primary review key: {key}")
                labels[key] = item["useful"]
    return labels


def _normalized_judgments(response: dict, expected_keys: list[str]) -> list[dict]:
    raw = response.get("judgments")
    if not isinstance(raw, list):
        raise EvaluationError("review response needs a judgments list")
    judgments: dict[str, dict] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise EvaluationError("each reviewer judgment must be an object")
        key = item.get("review_key")
        useful = item.get("useful")
        reason = item.get("reason")
        if (
            not isinstance(key, str)
            or key in judgments
            or not isinstance(useful, bool)
            or not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > 1000
        ):
            raise EvaluationError(f"malformed or duplicate reviewer judgment: {key!r}")
        judgments[key] = {
            "review_key": key,
            "useful": useful,
            "reason": reason.strip(),
        }
    if set(judgments) != set(expected_keys):
        missing = sorted(set(expected_keys) - set(judgments))
        extra = sorted(set(judgments) - set(expected_keys))
        raise EvaluationError(
            f"review judgments do not match packet (missing={missing}, extra={extra})"
        )
    return [judgments[key] for key in expected_keys]


def build_review_results(
    packet: dict,
    response: dict,
    manifest: dict,
    *,
    evaluation_results_sha256: str,
    reviewer: dict,
) -> dict:
    return _review_results(
        packet,
        response,
        _primary_labels(manifest),
        evaluation_results_sha256=evaluation_results_sha256,
        reviewer=reviewer,
    )


def _review_results(
    packet: dict,
    response: dict,
    primary: dict[str, bool],
    *,
    evaluation_results_sha256: str,
    reviewer: dict,
) -> dict:
    expected_keys = [item["review_key"] for item in packet["findings"]]
    judgments = _normalized_judgments(response, expected_keys)
    if not judgments:
        raise EvaluationError("review results need at least one judgment")
    comparisons = []
    disagreements = []
    secondary_useful = 0
    agreement_count = 0
    for judgment in judgments:
        key = judgment["review_key"]
        primary_useful = primary.get(key, False)
        agrees = primary_useful == judgment["useful"]
        secondary_useful += judgment["useful"]
        agreement_count += agrees
        comparison = {
            "review_key": key,
            "primary_useful": primary_useful,
            "secondary_useful": judgment["useful"],
            "agrees": agrees,
        }
        comparisons.append(comparison)
        if not agrees:
            disagreements.append({
                **comparison,
                "secondary_reason": judgment["reason"],
            })
    count = len(judgments)
    usefulness_rate = round(secondary_useful / count, 4)
    agreement_rate = round(agreement_count / count, 4)
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "packet_sha256": _json_sha256(packet),
        "evaluation_results_sha256": evaluation_results_sha256,
        "reviewer": reviewer,
        "judgments": judgments,
        "comparison": {
            "findings_reviewed": count,
            "secondary_useful": secondary_useful,
            "secondary_usefulness_rate": usefulness_rate,
            "secondary_usefulness_threshold": SECONDARY_USEFULNESS_THRESHOLD,
            "secondary_usefulness_passed": (
                usefulness_rate >= SECONDARY_USEFULNESS_THRESHOLD
            ),
            "agreement_count": agreement_count,
            "agreement_rate": agreement_rate,
            "comparisons": comparisons,
            "disagreements": disagreements,
        },
    }


def run_reviewer(
    output_path: Path = DEFAULT_REVIEW_RESULTS,
    packet_path: Path = DEFAULT_PACKET,
    manifest_path: Path = DEFAULT_MANIFEST,
    evaluation_path: Path = DEFAULT_RESULTS,
) -> dict:
    packet = write_packet(packet_path, manifest_path, evaluation_path)
    codex = shutil.which("codex")
    if codex is None:
        raise EvaluationError("codex is not installed")
    codex = str(Path(codex).resolve())
    codex_version = _codex_version(codex)

    with tempfile.TemporaryDirectory(prefix="glossabet-second-reviewer-") as raw:
        workspace = Path(raw)
        isolated_packet = workspace / "reviewer-packet.json"
        isolated_schema = workspace / "reviewer-response-schema.json"
        final_path = workspace / "reviewer-response.json"
        shutil.copy2(packet_path, isolated_packet)
        shutil.copy2(RESPONSE_SCHEMA_PATH, isolated_schema)
        expected_files = {
            isolated_packet.name: _sha256(isolated_packet),
            isolated_schema.name: _sha256(isolated_schema),
        }
        command = [
            codex,
            "exec",
            "--json",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "-c",
            'approval_policy="never"',
            "--output-schema",
            str(isolated_schema),
            "--output-last-message",
            str(final_path),
            "--cd",
            str(workspace),
            PROMPT_PATH.read_text(encoding="utf-8"),
        ]
        print(
            "$ codex exec --json --ephemeral --sandbox read-only ...",
            flush=True,
        )
        process = subprocess.run(
            command,
            cwd=workspace,
            text=True,
            capture_output=True,
            timeout=900,
        )
        if process.stderr:
            print(process.stderr[-4000:], end="", file=sys.stderr, flush=True)
        if process.returncode:
            detail = process.stderr[-2000:] or process.stdout[-2000:]
            raise EvaluationError(
                f"second-reviewer Codex run exited {process.returncode}: {detail}"
            )
        trace, usage = _parse_reviewer_trace(process.stdout, workspace)
        response = _read_json(final_path, "second-reviewer response")
        final_path.unlink()
        observed_files = {
            path.name: _sha256(path)
            for path in workspace.iterdir()
            if path.is_file()
        }
        if observed_files != expected_files:
            raise EvaluationError("second reviewer changed its isolated workspace")

    manifest = _read_json(manifest_path, "evaluation manifest")
    result = build_review_results(
        packet,
        response,
        manifest,
        evaluation_results_sha256=_sha256(evaluation_path),
        reviewer={
            "kind": "codex-exec",
            "codex_version": codex_version,
            "model": "configured default; Codex CLI JSONL did not report it",
            "blinded_to_primary_labels": True,
            "independence": (
                "separate ephemeral Codex session in an isolated temporary "
                "working directory, explicitly supplied only the review prompt, "
                "response schema, and blinded packet"
            ),
            "input_identity": _reviewer_input_identity(),
            "execution": {
                "ephemeral": True,
                "sandbox": "read-only",
                "approval_policy": "never",
                "repository_available": False,
                "trace_limits": TRACE_LIMITS,
            },
            "trace": trace,
            "usage": usage,
        },
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _packet_genuineness_errors(packet: dict) -> list[str]:
    errors: list[str] = []
    if packet.get("schema_version") != PACKET_SCHEMA_VERSION:
        errors.append("reviewer packet schema is stale")
    if not _hex_digest(packet.get("evaluation_manifest_sha256")):
        errors.append("reviewer packet manifest digest is malformed")
    findings = packet.get("findings")
    well_formed = isinstance(findings, list) and bool(findings)
    seen: set[str] = set()
    for item in findings if well_formed else []:
        key = item.get("review_key") if isinstance(item, dict) else None
        if not isinstance(key, str) or not key or key in seen:
            well_formed = False
            break
        seen.add(key)
        if _contains_key(item, "useful"):
            errors.append("reviewer packet contains a usefulness label")
            break
    if not well_formed:
        errors.append("reviewer packet findings are missing or malformed")
    return errors


def _stored_primary_labels(results: dict) -> dict[str, bool]:
    comparison = results.get("comparison")
    comparisons = (
        comparison.get("comparisons") if isinstance(comparison, dict) else None
    )
    if not isinstance(comparisons, list):
        raise EvaluationError(
            "reviewer comparison records are missing or malformed"
        )
    labels: dict[str, bool] = {}
    for item in comparisons:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("review_key"), str)
            or not isinstance(item.get("primary_useful"), bool)
            or item["review_key"] in labels
        ):
            raise EvaluationError(
                "reviewer comparison records are missing or malformed"
            )
        labels[item["review_key"]] = item["primary_useful"]
    return labels


def verify_results(
    review_path: Path = DEFAULT_REVIEW_RESULTS,
    packet_path: Path = DEFAULT_PACKET,
    manifest_path: Path = DEFAULT_MANIFEST,
    evaluation_path: Path = DEFAULT_RESULTS,
    *,
    current: bool = False,
) -> list[str]:
    """Check committed second-reviewer evidence.

    Always checks genuineness: the stored packet stays blinded, the recorded
    judgments and comparisons are internally consistent, and the usefulness
    threshold passes. With ``current=True`` (the release gate) it additionally
    checks currency: the packet and digests match the current evaluation
    results, manifest, and reviewer inputs.
    """
    errors: list[str] = []
    packet = _read_json(packet_path, "reviewer packet")
    errors.extend(_packet_genuineness_errors(packet))
    results = _read_json(review_path, "reviewer results")
    if results.get("schema_version") != REVIEW_SCHEMA_VERSION:
        errors.append("reviewer result schema is stale")
    reviewer = results.get("reviewer")
    execution = reviewer.get("execution", {}) if isinstance(reviewer, dict) else {}
    trace = reviewer.get("trace") if isinstance(reviewer, dict) else None
    identity = (
        reviewer.get("input_identity") if isinstance(reviewer, dict) else None
    )
    if current:
        identity_ok = identity == _reviewer_input_identity()
    else:
        identity_ok = (
            isinstance(identity, dict)
            and set(identity)
            == {"evaluator_sha256", "prompt_sha256", "response_schema_sha256"}
            and all(_hex_digest(value) for value in identity.values())
        )
    recorded_limits = (
        execution.get("trace_limits") if isinstance(execution, dict) else None
    )
    if current:
        limits_ok = recorded_limits == TRACE_LIMITS
    else:
        # Genuineness validates the recorded limits' shape only; the exact
        # values are the evaluator's to demand at the release gate, so an
        # evaluator constant edit does not invalidate lagging evidence.
        limits_ok = (
            isinstance(recorded_limits, dict)
            and set(recorded_limits) == set(TRACE_LIMITS)
            and all(
                isinstance(value, int)
                and not isinstance(value, bool)
                and value > 0
                for value in recorded_limits.values()
            )
        )
    if not limits_ok:
        recorded_limits = None
    bounds = recorded_limits or {
        "commands": 0,
        "stored_command_characters": 0,
        "stored_output_characters": 0,
    }
    if (
        not isinstance(reviewer, dict)
        or reviewer.get("kind") != "codex-exec"
        or reviewer.get("blinded_to_primary_labels") is not True
        or not isinstance(reviewer.get("codex_version"), str)
        or not identity_ok
        or not limits_ok
        or not isinstance(execution, dict)
        or {
            key: value
            for key, value in execution.items()
            if key != "trace_limits"
        }
        != {
            "ephemeral": True,
            "sandbox": "read-only",
            "approval_policy": "never",
            "repository_available": False,
        }
    ):
        errors.append("reviewer identity or blinding metadata is malformed")
    if (
        not isinstance(trace, list)
        or not trace
        or len(trace) > bounds["commands"]
    ):
        errors.append("second-reviewer trace is missing or unbounded")
    else:
        for command in trace:
            if (
                not isinstance(command, dict)
                or "reviewer-packet.json" not in str(
                    command.get("command", "")
                ).casefold()
                or len(str(command.get("command", "")))
                > bounds["stored_command_characters"] + 1
                or len(str(command.get("output_preview", "")))
                > bounds["stored_output_characters"] + 1
                or command.get("exit_code") != 0
            ):
                errors.append("second-reviewer trace is missing or unbounded")
                break
    if not _hex_digest(results.get("evaluation_results_sha256")):
        errors.append("reviewer evidence digests are malformed")
    response = {"judgments": results.get("judgments")}
    try:
        rebuilt = _review_results(
            packet,
            response,
            _stored_primary_labels(results),
            evaluation_results_sha256=results.get("evaluation_results_sha256"),
            reviewer=reviewer if isinstance(reviewer, dict) else {},
        )
    except (EvaluationError, KeyError, TypeError) as exc:
        errors.append(str(exc) or "reviewer results are malformed")
    else:
        if results != rebuilt:
            errors.append("reviewer comparisons or input digests are stale")
        if rebuilt["comparison"]["secondary_usefulness_passed"] is not True:
            errors.append("second-reviewer usefulness threshold does not pass")

    if current:
        try:
            expected = expected_packet(manifest_path, evaluation_path)
        except EvaluationError as exc:
            errors.append(str(exc))
            expected = None
        if expected is not None:
            if packet != expected:
                errors.append(
                    "reviewer packet is stale or contains non-blinded fields"
                )
            manifest = _read_json(manifest_path, "evaluation manifest")
            try:
                rebuilt_current = build_review_results(
                    expected,
                    response,
                    manifest,
                    evaluation_results_sha256=_sha256(evaluation_path),
                    reviewer=reviewer if isinstance(reviewer, dict) else {},
                )
            except EvaluationError as exc:
                errors.append(str(exc))
            else:
                if results != rebuilt_current:
                    errors.append(
                        "reviewer comparisons or input digests are stale"
                    )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--evaluation", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--packet", type=Path, default=DEFAULT_PACKET)
    parser.add_argument("--output", type=Path, default=DEFAULT_REVIEW_RESULTS)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--build-packet", action="store_true")
    action.add_argument("--run-reviewer", action="store_true")
    action.add_argument("--verify-results", type=Path)
    parser.add_argument(
        "--current",
        action="store_true",
        help=(
            "with --verify-results, additionally require the evidence to "
            "match the current evaluation results and reviewer inputs "
            "(the release gate)"
        ),
    )
    args = parser.parse_args(argv)
    if args.current and args.verify_results is None:
        parser.error("--current requires --verify-results")

    try:
        if args.build_packet:
            packet = write_packet(args.packet, args.manifest, args.evaluation)
            print(
                f"wrote blinded reviewer packet with {len(packet['findings'])} "
                f"finding(s): {args.packet}"
            )
            return 0
        if args.verify_results is not None:
            errors = verify_results(
                args.verify_results,
                args.packet,
                args.manifest,
                args.evaluation,
                current=args.current,
            )
            if errors:
                for error in errors:
                    print(f"review verification: {error}", file=sys.stderr)
                return 1
            if args.current:
                print("second-reviewer evidence matches the blinded packet")
            else:
                print(
                    "second-reviewer evidence is genuine, blinded, and "
                    "internally consistent"
                )
            return 0
        result = run_reviewer(
            args.output,
            args.packet,
            args.manifest,
            args.evaluation,
        )
        print(
            f"recorded {result['comparison']['findings_reviewed']} second-reviewer "
            f"judgment(s): {args.output}"
        )
        return 0
    except (EvaluationError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"review evaluation: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
