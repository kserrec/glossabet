"""Command-line entry point.

Exit statuses (contract, PLAN.md Phase 1): 0 success, 1 user error (bad
usage, missing input, not-yet-implemented command), 2 internal defect.
"""

from __future__ import annotations

import argparse
import sys
import traceback

from glossarize import __version__

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_DEFECT = 2


class _Parser(argparse.ArgumentParser):
    # argparse exits with status 2 on usage errors; 2 is reserved for
    # internal defects here, so usage problems exit 1 instead.
    def error(self, message: str) -> "argparse.NoReturn":  # type: ignore[name-defined]
        self.print_usage(sys.stderr)
        self.exit(EXIT_USER_ERROR, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="glossarize",
        description=(
            "Build and maintain a shared vocabulary for a codebase. "
            "Deterministic machinery gathers evidence; the /glossarize "
            "agent skill brainstorms names; the human decides."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"glossarize {__version__}"
    )
    sub = parser.add_subparsers(dest="command")

    scan = sub.add_parser("scan", help="build or refresh repository evidence")
    scan.add_argument("path", nargs="?", default=".", help="repository root")

    analyze = sub.add_parser(
        "analyze",
        help="scan plus a terminology report (register, overlaps, overloads)",
    )
    analyze.add_argument("path", nargs="?", default=".", help="repository root")

    show = sub.add_parser("show", help="display the current glossary")
    show.add_argument("path", nargs="?", default=".", help="repository root")

    return parser


def _run(argv: list[str] | None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_USER_ERROR

    if args.command == "scan":
        from glossarize.evidence import scan_command

        return scan_command(args.path)

    if args.command == "analyze":
        from glossarize.evidence import analyze_command

        return analyze_command(args.path)

    if args.command == "show":
        from glossarize.glossary import show_command

        return show_command(args.path)

    parser.error(f"unknown command {args.command!r}")
    return EXIT_DEFECT  # unreachable; error() exits


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(argv)
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        print(
            "glossarize: internal error — this is a defect in glossarize, "
            "not a usage mistake.",
            file=sys.stderr,
        )
        return EXIT_DEFECT
