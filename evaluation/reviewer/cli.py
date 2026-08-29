"""Terminal-facing behavior of the blinded reviewer lane."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from evaluation.reviewer.contract import (
    DEFAULT_MANIFEST,
    DEFAULT_PACKET,
    DEFAULT_RESULTS,
    DEFAULT_REVIEW_RESULTS,
    DEFAULT_REVIEWED_PACKETS,
    ReviewerEvaluationError,
)
from evaluation.reviewer.packet import write_packet
from evaluation.reviewer.results import verify_results

DESCRIPTION = "Build and verify the blinded second-reviewer evaluation lane."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--evaluation", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--packet", type=Path, default=DEFAULT_PACKET)
    parser.add_argument(
        "--reviewed-packets",
        type=Path,
        default=DEFAULT_REVIEWED_PACKETS,
        help="directory of exact blinded packets retained by content digest",
    )
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
                reviewed_packets=args.reviewed_packets,
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

        # Keep the authenticated host module outside the offline import path.
        from evaluation.reviewer.host import run_reviewer

        result = run_reviewer(
            args.output,
            args.packet,
            args.manifest,
            args.evaluation,
            args.reviewed_packets,
        )
        print(
            f"recorded {result['comparison']['findings_reviewed']} second-reviewer "
            f"judgment(s): {args.output}"
        )
        return 0
    except (ReviewerEvaluationError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"review evaluation: {exc}", file=sys.stderr)
        return 1
