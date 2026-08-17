"""Command-line entry point.

Exit statuses (contract, PLAN.md Phase 1): 0 success, 1 user error (bad
usage, missing input, not-yet-implemented command), 2 internal defect.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from typing import NoReturn as _NoReturn

from glossabet import __version__
from glossabet.display import (
    escape_terminal_text,
    print_error,
    safe_terminal_streams,
)

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_DEFECT = 2


class _Parser(argparse.ArgumentParser):
    # argparse exits with status 2 on usage errors; 2 is reserved for
    # internal defects here, so usage problems exit 1 instead.
    def error(self, message: str) -> _NoReturn:
        self.print_usage(sys.stderr)
        safe_message = escape_terminal_text(message)
        self.exit(EXIT_USER_ERROR, f"{self.prog}: error: {safe_message}\n")


def _add_repository_path(command: argparse.ArgumentParser) -> None:
    command.add_argument("path", nargs="?", default=".", help="repository root")


def _add_graphify_toggle(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--no-graphify", action="store_true",
        help="ignore graphify-out/graph.json even if present",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="glossabet",
        description=(
            "Build and maintain a shared vocabulary for a codebase. "
            "Deterministic machinery gathers evidence; the /glossabet "
            "agent skill brainstorms names; the human decides."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"glossabet {__version__}"
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

    inspect = sub.add_parser(
        "inspect",
        help="emit a fresh, bounded JSON context for the agent skill",
    )
    _add_repository_path(inspect)
    _add_graphify_toggle(inspect)
    inspect.add_argument(
        "--full",
        action="store_true",
        help="emit the detailed pre-lean agent projection",
    )

    brief = sub.add_parser(
        "brief",
        help="emit a bounded read-only digest of canonical vocabulary",
    )
    _add_repository_path(brief)

    sync_context = sub.add_parser(
        "sync-context",
        help="explicitly sync canonical vocabulary into a host instruction file",
        description=(
            "Explicitly sync one managed canonical-vocabulary block into the "
            "selected repository-root host instruction file."
        ),
    )
    _add_repository_path(sync_context)
    sync_context.add_argument(
        "--agent",
        choices=("codex", "claude"),
        default="codex",
        help="host file to update: AGENTS.md for Codex (default), CLAUDE.md for Claude",
    )
    sync_context.add_argument(
        "--force",
        action="store_true",
        help="replace edited content in a structurally valid managed block",
    )

    show = sub.add_parser("show", help="display the current glossary")
    _add_repository_path(show)

    save = sub.add_parser(
        "save",
        help="validate and save glossary JSON received on standard input",
    )
    _add_repository_path(save)

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
        description=(
            "Install the canonical agent skill (Codex by default). "
            "With --agent claude the skill folder also becomes a Claude Code "
            "skills-directory plugin whose session-start hook runs "
            "`glossabet brief .` in every session; nothing outside that "
            "folder is written."
        ),
    )
    install.add_argument(
        "--agent",
        choices=("codex", "claude"),
        default="codex",
        help="agent host whose personal skill location should be used (default: codex)",
    )
    install.add_argument(
        "--skill-only",
        action="store_true",
        help=(
            "with --agent claude, install only SKILL.md and no session-start "
            "hook (no ambient glossary loading)"
        ),
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
        from glossabet.evidence import scan_command

        return scan_command(args.path, graphify=not args.no_graphify)

    if args.command == "analyze":
        from glossabet.evidence import analyze_command

        return analyze_command(args.path, graphify=not args.no_graphify)

    if args.command == "inspect":
        from glossabet.agent_context import inspect_command

        return inspect_command(
            args.path,
            graphify=not args.no_graphify,
            full=args.full,
        )

    if args.command == "brief":
        from glossabet.brief import brief_command

        return brief_command(args.path)

    if args.command == "sync-context":
        from glossabet.context_sync import sync_context_command

        return sync_context_command(args.path, args.agent, force=args.force)

    if args.command == "show":
        from glossabet.glossary import show_command

        return show_command(args.path)

    if args.command == "save":
        from glossabet.glossary import save_command

        return save_command(args.path)

    if args.command == "drift":
        from glossabet.drift import drift_command

        return drift_command(args.path)

    if args.command == "validate":
        from glossabet.reconcile import validate_command

        return validate_command(args.path)

    if args.command == "install":
        from glossabet.installer import install_command

        return install_command(
            args.agent,
            args.destination,
            force=args.force,
            skill_only=args.skill_only,
        )

    parser.error(f"unknown command {args.command!r}")
    return EXIT_DEFECT  # unreachable; error() exits


def _main(argv: list[str] | None = None) -> int:
    try:
        return _run(argv)
    except SystemExit:
        raise
    except Exception as exc:
        # Imported lazily to keep CLI startup small and avoid pulling command
        # modules into argparse-only paths.
        from glossabet.artifacts import ArtifactError

        if isinstance(exc, ArtifactError):
            print_error(exc)
            return EXIT_USER_ERROR
        print(escape_terminal_text(traceback.format_exc()), file=sys.stderr)
        print(
            "glossabet: internal error — this is a defect in glossabet, "
            "not a usage mistake.",
            file=sys.stderr,
        )
        return EXIT_DEFECT


def main(argv: list[str] | None = None) -> int:
    """Run one CLI invocation with terminal-safe standard streams."""
    with safe_terminal_streams():
        return _main(argv)
