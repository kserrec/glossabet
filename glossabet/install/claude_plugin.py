"""The Claude Code skills-directory plugin that ``install --agent claude`` writes.

Claude Code loads any folder under ``~/.claude/skills/`` that carries a
``.claude-plugin/plugin.json`` as the plugin ``<name>@skills-dir`` on the next
session, so the folder can bundle a ``hooks/hooks.json``. Glossabet uses that
to run ``brief .`` at session start, resume, clear, and compaction — the
ambient-consumption route the Codex plugin already provides (PLAN Phase 33).

This module only describes the files (pure data out); ``installer`` writes
them, and nothing outside the skill folder is ever written.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from glossabet import __version__
from glossabet.runtime.executables import which_on_path

# Fields shared with the checked-in Codex plugin manifest; a test pins them
# to plugins/glossabet/.codex-plugin/plugin.json so the two hosts cannot drift.
PLUGIN_DESCRIPTION = (
    "Build and maintain a shared codebase vocabulary with a bundled local CLI."
)
PLUGIN_AUTHOR = {"name": "Kyle Serrecchia", "url": "https://github.com/kserrec"}
PLUGIN_HOMEPAGE = "https://github.com/kserrec/glossabet"
PLUGIN_LICENSE = "Apache-2.0"
PLUGIN_KEYWORDS = ["code-quality", "glossary", "terminology"]
SESSION_START_MATCHER = "^(startup|resume|clear|compact)$"
SESSION_START_STATUS = "Loading settled repository vocabulary"
SESSION_START_TIMEOUT_SECONDS = 30
CLAUDE_MANIFEST_RELATIVE = Path(".claude-plugin") / "plugin.json"
CLAUDE_HOOKS_RELATIVE = Path("hooks") / "hooks.json"
MANIFEST_LABEL = "Claude Code plugin manifest"
HOOK_LABEL = "session-start hook"

_EXECUTABLE_NAMES = frozenset({"glossabet", "glossabet.exe"})
# Characters that would change meaning inside the double-quoted hook command.
_UNSAFE_COMMAND_CHARACTERS = frozenset('"$`') | frozenset(chr(c) for c in range(32))


class ClaudePluginError(ValueError):
    """The Claude Code plugin cannot be described safely."""


def claude_plugin_manifest() -> dict:
    """The ``.claude-plugin/plugin.json`` that makes the skill folder a plugin.

    ``"skills": ["./"]`` keeps the folder's own root ``SKILL.md`` a skill (the
    shape ``claude plugin init`` scaffolds). No ``hooks`` field: Claude Code
    discovers ``hooks/hooks.json`` by default, and naming it as well would
    register the hook twice.
    """
    return {
        "name": "glossabet",
        "version": __version__,
        "description": PLUGIN_DESCRIPTION,
        "author": dict(PLUGIN_AUTHOR),
        "homepage": PLUGIN_HOMEPAGE,
        "repository": PLUGIN_HOMEPAGE,
        "license": PLUGIN_LICENSE,
        "keywords": list(PLUGIN_KEYWORDS),
        "skills": ["./"],
    }


def hook_command(executable: Path) -> str:
    """The shell-form hook command: the exact executable, then ``brief .``."""
    text = str(executable)
    if any(character in _UNSAFE_COMMAND_CHARACTERS for character in text):
        raise ClaudePluginError(
            "refusing to write a session-start hook: the glossabet executable "
            f"path contains characters unsafe in a hook command: {text}"
        )
    return f'"{text}" brief .'


def claude_hooks(executable: Path) -> dict:
    """The ``hooks/hooks.json`` SessionStart contract for Claude Code.

    Plain stdout of a SessionStart command hook becomes session context on
    exit 0; ``brief`` prints the bounded canonical vocabulary and nothing at
    all when the repository has no glossary. ``fork`` is excluded on purpose:
    a fork inherits its parent's context, which already holds the brief.
    """
    return {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": SESSION_START_MATCHER,
                    "hooks": [
                        {
                            "type": "command",
                            "command": hook_command(executable),
                            "timeout": SESSION_START_TIMEOUT_SECONDS,
                            "statusMessage": SESSION_START_STATUS,
                        }
                    ],
                }
            ]
        }
    }


def _json_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def claude_plugin_files(executable: Path) -> list[tuple[str, Path, bytes]]:
    """The files written beside ``SKILL.md``: ``(label, relative path, bytes)``."""
    return [
        (MANIFEST_LABEL, CLAUDE_MANIFEST_RELATIVE, _json_bytes(claude_plugin_manifest())),
        (HOOK_LABEL, CLAUDE_HOOKS_RELATIVE, _json_bytes(claude_hooks(executable))),
    ]


def _candidate_executables() -> list[Path]:
    """The executable that ran this command (an explicit user choice), then
    the first ``glossabet`` on ``PATH`` — looked up without ever resolving
    into the current directory: the hook this path lands in runs in every
    future session, so a repository-local ``glossabet.bat`` picked up from
    a cwd-first search must never be the candidate."""
    candidates: list[Path] = []
    argv0 = sys.argv[0] if sys.argv else ""
    if argv0 and Path(argv0).name.lower() in _EXECUTABLE_NAMES:
        candidates.append(Path(argv0))
    found = which_on_path("glossabet")
    if found is not None:
        candidates.append(found)
    return candidates


def executable_location_warnings(path: Path) -> list[str]:
    """Why persisting ``path`` into a session-start hook is fragile: it lives
    inside the current directory or a project virtual environment, which the
    project's own tooling rewrites or deletes."""
    warnings = []
    resolved = path.resolve()
    try:
        resolved.relative_to(Path.cwd().resolve())
        warnings.append(
            f"{path} is inside the current directory; the hook will run this "
            "exact file from every project's sessions"
        )
    except ValueError:
        pass
    if any(part in (".venv", "venv") for part in resolved.parts):
        warnings.append(
            f"{path} is inside a virtual environment that its project's "
            "tooling may rewrite or delete; prefer a tool install "
            "(`uv tool install glossabet`) and rerun with --force"
        )
    return warnings


def resolve_cli_executable() -> Path:
    """Return the absolute ``glossabet`` executable a hook may name.

    Prefers the executable that ran this command (``sys.argv[0]``), then the
    first ``glossabet`` on ``PATH``. The candidate must exist as a file and
    ``<path> --version`` must report this package version, so the hook can
    never name a shell alias, a stale install, or nothing at all.
    """
    reasons: list[str] = []
    for candidate in _candidate_executables():
        path = candidate.expanduser().absolute()
        if not path.is_file():
            reasons.append(f"{path}: not a file")
            continue
        try:
            result = subprocess.run(
                [str(path), "--version"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            reasons.append(f"{path}: cannot run --version ({exc})")
            continue
        expected = f"glossabet {__version__}"
        if result.returncode != 0 or result.stdout.strip() != expected:
            reasons.append(f"{path}: --version did not report {expected!r}")
            continue
        return path
    detail = "; ".join(reasons) if reasons else "no glossabet executable found"
    raise ClaudePluginError(
        "cannot resolve the glossabet executable for the session-start hook "
        f"({detail}); install the CLI (for example `uv tool install glossabet`) "
        "and rerun, or pass --skill-only"
    )
