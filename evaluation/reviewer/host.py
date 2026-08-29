"""Live Codex host invocation for the blinded reviewer lane."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from evaluation.harness.io import file_sha256
from evaluation.reviewer.contract import (
    DEFAULT_MANIFEST,
    DEFAULT_PACKET,
    DEFAULT_RESULTS,
    DEFAULT_REVIEW_RESULTS,
    DEFAULT_REVIEWED_PACKETS,
    PROMPT_PATH,
    RESPONSE_SCHEMA_PATH,
    TRACE_LIMITS,
    ReviewerEvaluationError,
    json_bytes,
    read_json,
    reviewer_input_identity,
)
from evaluation.reviewer.packet import write_packet
from evaluation.reviewer.results import (
    build_review_results,
    publish_review_artifacts,
)
from evaluation.reviewer.trace import parse_reviewer_trace


def _codex_version(codex: str) -> str:
    result = subprocess.run(
        [codex, "--version"],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if result.returncode:
        raise ReviewerEvaluationError(
            result.stderr.strip() or "could not run codex --version"
        )
    match = re.search(r"codex-cli\s+([^\s]+)", result.stdout)
    if match is None:
        raise ReviewerEvaluationError(
            f"unrecognized Codex version output: {result.stdout!r}"
        )
    return match.group(1)


def run_reviewer(
    output_path: Path = DEFAULT_REVIEW_RESULTS,
    packet_path: Path = DEFAULT_PACKET,
    manifest_path: Path = DEFAULT_MANIFEST,
    evaluation_path: Path = DEFAULT_RESULTS,
    reviewed_packets: Path = DEFAULT_REVIEWED_PACKETS,
) -> dict:
    packet = write_packet(packet_path, manifest_path, evaluation_path)
    # Bind the run to the deterministic packet object, not to a path another
    # process could replace while the model host is running.
    packet_bytes = json_bytes(packet)
    codex = shutil.which("codex")
    if codex is None:
        raise ReviewerEvaluationError("codex is not installed")
    codex = str(Path(codex).resolve())
    codex_version = _codex_version(codex)

    with tempfile.TemporaryDirectory(
        prefix="glossabet-second-reviewer-"
    ) as raw:
        workspace = Path(raw)
        isolated_packet = workspace / "reviewer-packet.json"
        isolated_schema = workspace / "reviewer-response-schema.json"
        final_path = workspace / "reviewer-response.json"
        isolated_packet.write_bytes(packet_bytes)
        shutil.copy2(RESPONSE_SCHEMA_PATH, isolated_schema)
        expected_files = {
            isolated_packet.name: file_sha256(isolated_packet),
            isolated_schema.name: file_sha256(isolated_schema),
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
            raise ReviewerEvaluationError(
                f"second-reviewer Codex run exited {process.returncode}: {detail}"
            )
        trace, usage = parse_reviewer_trace(process.stdout, workspace)
        response = read_json(final_path, "second-reviewer response")
        final_path.unlink()
        observed_files = {
            path.name: file_sha256(path)
            for path in workspace.iterdir()
            if path.is_file()
        }
        if observed_files != expected_files:
            raise ReviewerEvaluationError(
                "second reviewer changed its isolated workspace"
            )

    manifest = read_json(manifest_path, "evaluation manifest")
    result = build_review_results(
        packet,
        response,
        manifest,
        evaluation_results_sha256=file_sha256(evaluation_path),
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
            "input_identity": reviewer_input_identity(),
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
    publish_review_artifacts(
        result,
        output_path,
        packet_bytes,
        reviewed_packets,
    )
    return result
