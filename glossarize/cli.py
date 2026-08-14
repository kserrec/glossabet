"""Command-line entry point.

Exit statuses (contract, PLAN.md Phase 1): 0 success, 1 user error (bad
usage, missing input, not-yet-implemented command), 2 internal defect.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from typing import NoReturn as _NoReturn

from glossarize import __version__

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_DEFECT = 2


class _Parser(argparse.ArgumentParser):
    # argparse exits with status 2 on usage errors; 2 is reserved for
    # internal defects here, so usage problems exit 1 instead.
    def error(self, message: str) -> _NoReturn:
        self.print_usage(sys.stderr)
        self.exit(EXIT_USER_ERROR, f"{self.prog}: error: {message}\n")


def _add_repository_path(command: argparse.ArgumentParser) -> None:
    command.add_argument("path", nargs="?", default=".", help="repository root")


def _add_graphify_toggle(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--no-graphify", action="store_true",
        help="ignore graphify-out/graph.json even if present",
    )


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
    _add_repository_path(scan)
    _add_graphify_toggle(scan)

    analyze = sub.add_parser(
        "analyze",
        help="scan plus a terminology report (register, overlaps, overloads)",
    )
    _add_repository_path(analyze)
    _add_graphify_toggle(analyze)

    show = sub.add_parser("show", help="display the current glossary")
    _add_repository_path(show)

    drift = sub.add_parser(
        "drift", help="check live vocabulary against the canonical glossary"
    )
    _add_repository_path(drift)

    validate = sub.add_parser(
        "validate",
        help="reconcile the glossary against evidence and the graphify graph",
    )
    _add_repository_path(validate)

    install = sub.add_parser(
        "install",
        help="install the canonical agent skill (Codex by default)",
        description="Install the canonical agent skill (Codex by default).",
    )
    install.add_argument(
        "--agent",
        choices=("codex", "claude"),
        default="codex",
        help="agent host whose personal skill location should be used (default: codex)",
    )
    install.add_argument(
        "--destination",
        metavar="DIR",
        help="override the skill directory; SKILL.md is written inside DIR",
    )
    install.add_argument(
        "--force",
        action="store_true",
        help="replace a different existing SKILL.md at the destination",
    )

    return parser


def _run(argv: list[str] | None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_USER_ERROR

    if args.command == "scan":
        from glossarize.evidence import scan_command

        return scan_command(args.path, graphify=not args.no_graphify)

    if args.command == "analyze":
        from glossarize.evidence import analyze_command

        return analyze_command(args.path, graphify=not args.no_graphify)

    if args.command == "show":
        from glossarize.glossary import show_command

        return show_command(args.path)

    if args.command == "drift":
        from glossarize.drift import drift_command

        return drift_command(args.path)

    if args.command == "validate":
        from glossarize.reconcile import validate_command

        return validate_command(args.path)

    if args.command == "install":
        from glossarize.installer import install_command

        return install_command(
            args.agent, args.destination, force=args.force
        )

    parser.error(f"unknown command {args.command!r}")
    return EXIT_DEFECT  # unreachable; error() exits


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(argv)
    except SystemExit:
        raise
    except Exception as exc:
        # Imported lazily to keep CLI startup small and avoid pulling command
        # modules into argparse-only paths.
        from glossarize.artifacts import ArtifactError

        if isinstance(exc, ArtifactError):
            print(f"glossarize: {exc}", file=sys.stderr)
            return EXIT_USER_ERROR
        traceback.print_exc()
        print(
            "glossarize: internal error — this is a defect in glossarize, "
            "not a usage mistake.",
            file=sys.stderr,
        )
        return EXIT_DEFECT
