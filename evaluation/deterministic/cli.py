"""Terminal-facing behavior of the deterministic evaluation lane."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from evaluation.deterministic.contract import (
    DEFAULT_MANIFEST,
    DEFAULT_RESULTS,
    EvaluationError,
)
from evaluation.deterministic.results import verify_results
from evaluation.deterministic.runner import run_evaluation

DESCRIPTION = """Reproduce Glossabet's pinned deterministic lexical evaluation.

External source is checked out only into a caller-provided directory or a
temporary directory. Nothing is imported or executed from a target project."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run.py", description=DESCRIPTION)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--fetch", action="store_true")
    source.add_argument("--repositories-root", type=Path)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--verify-results",
        type=Path,
        help="verify committed results are genuine and internally consistent",
    )
    parser.add_argument(
        "--current",
        action="store_true",
        help=(
            "with --verify-results, additionally require the evidence to "
            "describe the current engine source, manifest, and corpora "
            "(the release gate)"
        ),
    )
    args = parser.parse_args(argv)
    if args.current and args.verify_results is None:
        parser.error("--current requires --verify-results")
    if args.case and args.check:
        parser.error(
            "--check gates release thresholds, which a partial --case run "
            "never computes; drop --case or --check"
        )
    if args.case and args.output.resolve() == DEFAULT_RESULTS.resolve():
        parser.error(
            "--case writes a partial document; pass an explicit --output "
            "so the committed release evidence is not overwritten"
        )
    if args.verify_results is not None:
        try:
            errors = verify_results(
                args.verify_results, args.manifest, current=args.current
            )
        except (EvaluationError, OSError, subprocess.TimeoutExpired) as exc:
            print(f"evaluation verification: {exc}", file=sys.stderr)
            return 1
        if errors:
            for error in errors:
                print(f"evaluation verification: {error}", file=sys.stderr)
            return 1
        if args.current:
            print("evaluation results match the current engine and corpus")
        else:
            print("evaluation results are genuine and internally consistent")
        return 0
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    try:
        if args.fetch:
            with tempfile.TemporaryDirectory(prefix="glossabet-eval-repos-") as raw:
                result = run_evaluation(
                    args.manifest,
                    args.output,
                    Path(raw),
                    True,
                    args.runs,
                    set(args.case),
                )
        else:
            result = run_evaluation(
                args.manifest,
                args.output,
                args.repositories_root,
                False,
                args.runs,
                set(args.case),
            )
    except (EvaluationError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"evaluation: {exc}", file=sys.stderr)
        return 1

    aggregate = result["aggregate"]
    print(
        f"evaluated {aggregate['cases']} case(s), "
        f"{aggregate['source_files']} source file(s): "
        f"precision {aggregate['quality']['overall_precision']}, "
        f"false alarms {aggregate['quality']['false_alarms']}"
    )
    thresholds = result["release_thresholds"]
    if thresholds["configured"]:
        print("release thresholds: " + ("pass" if thresholds["passed"] else "FAIL"))
    return 1 if args.check and thresholds.get("passed") is not True else 0
