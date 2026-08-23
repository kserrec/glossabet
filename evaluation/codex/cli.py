"""Terminal-facing behavior of the Codex evaluation lane."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from evaluation.codex.contract import RUNS_PATH, AgentEvaluationError, fail
from evaluation.codex.history import (
    append_attempt,
    attempt_from_probe,
    attempt_from_result,
    new_attempt_id,
    promote_current_result,
    refresh_artifact_record,
    validated_run_output,
)
from evaluation.codex.results import verify_results
from evaluation.codex.runner import run_recorded_evaluation, run_recorded_probe

DESCRIPTION = (
    "Run and verify bounded installed-skill scenarios through real Codex exec."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent_eval.py", description=DESCRIPTION)
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
            result = run_recorded_evaluation(output, attempt_id)
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
            probe = run_recorded_probe(attempt_id)
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
