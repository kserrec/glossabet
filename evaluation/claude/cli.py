"""Terminal-facing behavior of the Claude evaluation lane."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from evaluation.claude.contract import (
    DEFAULT_INSTALLED_PLUGIN,
    HISTORY_PATH,
    LIVE_CONFIRMATION,
    RUNS_PATH,
    ClaudeEvaluationError,
    fail,
    read_json,
)
from evaluation.claude.history import (
    append_attempt,
    attempt_from_result,
    new_attempt_id,
    promote_current_result,
    validated_output,
)
from evaluation.claude.results import verify_history, verify_results
from evaluation.claude.runner import run_recorded_evaluation

DESCRIPTION = """Build and verify bounded Claude Code live-host evidence.

Everything except ``--run`` is offline. A live run requires a conspicuous
confirmation phrase, reuses the already signed-in normal Claude profile, and
never invokes an authentication command. The three model calls have no tools,
no MCP servers, no saved sessions, and no evaluator retry."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claude_eval.py", description=DESCRIPTION)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--run", action="store_true")
    action.add_argument("--verify-history", action="store_true")
    action.add_argument("--verify-results", type=Path)
    parser.add_argument("--current", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--confirm-live-batch")
    parser.add_argument("--claude", type=Path)
    parser.add_argument("--installed-plugin", type=Path, default=DEFAULT_INSTALLED_PLUGIN)
    parser.add_argument("--scratch-parent", type=Path, default=Path("/tmp"))
    args = parser.parse_args(argv)
    try:
        if args.output is not None and not args.run:
            fail("--output can be used only with --run")
        if args.current and args.verify_results is None:
            fail("--current can be used only with --verify-results")
        if args.run:
            if args.confirm_live_batch != LIVE_CONFIRMATION:
                fail(
                    "live Claude evaluation requires --confirm-live-batch "
                    f"{LIVE_CONFIRMATION} after fresh user authorization"
                )
            claude = args.claude or (
                Path(found) if (found := shutil.which("claude")) else None
            )
            if claude is None:
                fail("claude is not on PATH; refusing to open a login flow")
            attempt_id = new_attempt_id()
            output = validated_output(
                args.output or RUNS_PATH / f"{attempt_id}.json"
            )
            result = run_recorded_evaluation(
                output,
                attempt_id,
                claude=claude,
                installed_plugin=args.installed_plugin,
                scratch_parent=args.scratch_parent,
            )
            append_attempt(attempt_from_result(attempt_id, result, output))
            promote_current_result(output)
            summary = result["summary"]
            print(
                f"Claude evaluation: {summary['passed']}/{summary['required']} "
                "scenarios passed"
            )
            return 0 if summary["all_passed"] else 1
        if args.verify_history:
            errors = verify_history()
        else:
            errors = verify_results(
                args.verify_results,
                current=args.current,
                installed_plugin=args.installed_plugin,
            )
        if errors:
            for error in errors:
                print(f"Claude evaluation verification: {error}", file=sys.stderr)
            return 1
        if args.verify_history:
            attempts = read_json(HISTORY_PATH, "Claude attempt history")["attempts"]
            message = (
                "Claude attempt history is genuine and empty"
                if not attempts
                else "Claude attempt history is genuine; "
                f"{len(attempts)} attempt{'s' if len(attempts) != 1 else ''} retained"
            )
        else:
            message = "Claude evaluation evidence is genuine and internally consistent"
        print(message)
        return 0
    except (ClaudeEvaluationError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"Claude evaluation: {exc}", file=sys.stderr)
        return 1
