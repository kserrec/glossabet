"""Command-line entry point.

Exit statuses (contract, PLAN.md Phase 1): 0 success, 1 user error (bad
usage, missing input, not-yet-implemented command), 2 internal defect.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from typing import NoReturn as _NoReturn

from glossabet import __version__
from glossabet.runtime.display import (
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


_SCOPE_NOTE = (
    "Analysis scope: production files drive vocabulary; test, fixture, "
    "generated, and vendored paths are classified by built-in defaults. An "
    "optional root glossabet.json (ignore_paths, path_roles) adjusts them; "
    "every effective role and exclusion is reported."
)


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

    scan = sub.add_parser(
        "scan",
        help="build or refresh repository evidence",
        description="Build or refresh repository evidence. " + _SCOPE_NOTE,
    )
    _add_repository_path(scan)
    _add_graphify_toggle(scan)

    analyze = sub.add_parser(
        "analyze",
        help="scan plus a terminology report (register, overlaps, overloads)",
        description=(
            "Scan plus a terminology report (register, overlaps, overloads). "
            + _SCOPE_NOTE
        ),
    )
    _add_repository_path(analyze)
    _add_graphify_toggle(analyze)

    inspect = sub.add_parser(
        "inspect",
        help="emit a fresh, bounded JSON context for the agent skill",
        description=(
            "Emit a fresh, bounded JSON context for the agent skill. "
            + _SCOPE_NOTE
        ),
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

    sub.add_parser(
        "cache-clear",
        help="remove Glossabet's user cache directory (never the repository)",
        description=(
            "Remove the incremental extraction cache Glossabet keeps in the "
            "current user's platform cache directory (or GLOSSABET_CACHE_DIR). "
            "Only Glossabet's own cache layout is deleted; the repository and "
            "glossabet-out/ are never touched, and anything unrecognized under "
            "the cache root is left in place and reported."
        ),
    )

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
        help=(
            "replace a different existing SKILL.md at the destination "
            "(with --agent claude, also a different plugin manifest or "
            "session-start hook)"
        ),
    )

    return parser


class _Arguments(argparse.Namespace):
    """The parsed command line, named so dispatch reads typed attributes.
    Each subcommand sets only the attributes its parser defines."""

    command: str | None
    path: str
    no_graphify: bool
    full: bool
    agent: str
    force: bool
    skill_only: bool
    destination: str | None


def _run(argv: list[str] | None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv, namespace=_Arguments())

    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_USER_ERROR

    if args.command == "scan":
        from glossabet.analysis.evidence_report import scan_command

        return scan_command(args.path, graphify=not args.no_graphify)

    if args.command == "analyze":
        from glossabet.analysis.evidence_report import analyze_command

        return analyze_command(args.path, graphify=not args.no_graphify)

    if args.command == "inspect":
        from glossabet.agent.agent_context import inspect_command

        return inspect_command(
            args.path,
            graphify=not args.no_graphify,
            full=args.full,
        )

    if args.command == "brief":
        from glossabet.agent.brief import brief_command

        return brief_command(args.path)

    if args.command == "sync-context":
        from glossabet.agent.context_sync import sync_context_command

        return sync_context_command(args.path, args.agent, force=args.force)

    if args.command == "show":
        from glossabet.glossary.glossary_commands import show_command

        return show_command(args.path)

    if args.command == "save":
        from glossabet.glossary.glossary_commands import save_command

        return save_command(args.path)

    if args.command == "drift":
        from glossabet.glossary.drift import drift_command

        return drift_command(args.path)

    if args.command == "validate":
        from glossabet.glossary.reconcile import validate_command

        return validate_command(args.path)

    if args.command == "cache-clear":
        from glossabet.corpus.cache import cache_clear_command

        return cache_clear_command()

    if args.command == "install":
        from glossabet.install.installer import install_command

        return install_command(
            args.agent,
            args.destination,
            force=args.force,
            skill_only=args.skill_only,
        )

    parser.error(f"unknown command {args.command!r}")
    return EXIT_DEFECT  # unreachable; error() exits


def _abandon_stdout() -> None:
    """Point fd 1 at the null device so the interpreter's exit-time flush of
    an unwritable stdout stays quiet (no "Exception ignored" noise, no exit
    status 120 overriding the one already chosen)."""
    try:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    except (OSError, ValueError):
        pass


def _main(argv: list[str] | None = None) -> int:
    try:
        code = _run(argv)
        sys.stdout.flush()  # a full disk or closed pipe is reported here
        return code
    except SystemExit as exc:
        # argparse's --version/--help/usage-error paths: still flush inside
        # the guarded region so a closed pipe stays quiet, and a successful
        # exit whose output could not be written is not reported as success.
        try:
            sys.stdout.flush()
        except OSError:
            _abandon_stdout()
            if not exc.code:
                return EXIT_USER_ERROR
        raise
    except BrokenPipeError:
        # The reader went away (a pager closed, a hook host stopped
        # listening): there is nobody to print to and nothing is wrong with
        # glossabet.
        _abandon_stdout()
        return EXIT_USER_ERROR
    except OSError as exc:
        # Permission denied, unreadable directory, disk full: the user's
        # environment, not a glossabet defect. pathlib's ``exists()`` /
        # ``is_dir()`` / ``is_symlink()`` raise on EACCES, so these surface
        # from any command that touches a path.
        detail = exc.strerror or str(exc)
        if exc.filename:
            detail = f"{detail}: {exc.filename}"
        print_error(detail)
        try:
            sys.stdout.flush()
        except OSError:  # the failure was stdout itself (disk full)
            _abandon_stdout()
        return EXIT_USER_ERROR
    except Exception as exc:
        # Imported lazily to keep CLI startup small and avoid pulling command
        # modules into argparse-only paths.
        from glossabet.runtime.artifacts import ArtifactError

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
