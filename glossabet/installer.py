"""Install the canonical agent skill from the Glossabet distribution.

The repository copy at ``skill/SKILL.md`` is the source of truth. Hatch maps
that file into the wheel as ``glossabet/_skill/SKILL.md``; source checkouts
fall back to the repository path so ``uv run glossabet install`` behaves the
same before and after packaging.

Installation writes only inside one user-selected skill directory outside
the analyzed repository. It is idempotent, refuses symlinked destinations,
and never replaces a different existing file unless the user explicitly
supplies ``--force``.

For Claude Code the same directory also becomes a *skills-directory plugin*:
Claude Code loads any folder under ``~/.claude/skills/`` that carries a
``.claude-plugin/plugin.json`` as the plugin ``<name>@skills-dir`` on the next
session, so the folder can bundle a ``hooks/hooks.json``. Glossabet uses that
to run ``brief .`` at session start, resume, clear, and compaction — the
ambient-consumption route the Codex plugin already provides (PLAN Phase 33).
Nothing outside the skill directory is ever written; ``~/.claude/settings.json``
is never touched.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

from glossabet import __version__
from glossabet.artifacts import replace_file_atomic
from glossabet.display import escape_terminal_text, print_error

_DESTINATIONS = {
    "codex": Path(".agents") / "skills" / "glossabet",
    "claude": Path(".claude") / "skills" / "glossabet",
}


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
# Characters that would change meaning inside the double-quoted hook command.
_UNSAFE_COMMAND_CHARACTERS = frozenset('"$`') | frozenset(chr(c) for c in range(32))


class InstallError(ValueError):
    """The requested skill installation is unsafe or cannot be completed."""


def default_skill_directory(agent: str, *, home: Path | None = None) -> Path:
    """Return the documented personal skill directory for ``agent``."""
    if agent not in _DESTINATIONS:
        raise InstallError(f"unsupported agent: {agent}")
    return (Path.home() if home is None else home) / _DESTINATIONS[agent]


def canonical_skill_text() -> str:
    """Read the canonical skill from package data or a source checkout."""
    packaged = resources.files("glossabet").joinpath("_skill", "SKILL.md")
    try:
        return packaged.read_text(encoding="utf-8")
    except FileNotFoundError:
        source = Path(__file__).resolve().parents[1] / "skill" / "SKILL.md"
        try:
            return source.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise RuntimeError(
                "the canonical skill is missing from this Glossabet installation"
            ) from exc


def _reject_symlink_components(path: Path) -> None:
    """Reject any existing symlink component in an installation path."""
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise InstallError(
                f"refusing symlinked skill destination component: {current}"
            )


def _install_file(
    destination: Path,
    relative: Path,
    payload: bytes,
    *,
    label: str,
    force: bool,
) -> tuple[Path, str]:
    """Write one owned file inside ``destination``; return ``(path, outcome)``.

    ``outcome`` is ``installed``, ``current``, or ``replaced``. A different
    existing file is never replaced without ``force``; symlinked components
    are refused; the write is atomic.
    """
    target = destination / relative
    _reject_symlink_components(target)

    if destination.exists() and not destination.is_dir():
        raise InstallError(
            f"skill destination exists but is not a directory: {destination}"
        )
    if target.exists() and not target.is_file():
        raise InstallError(f"{label} target exists but is not a file: {target}")

    if target.exists():
        try:
            existing = target.read_bytes()
        except OSError as exc:
            raise InstallError(
                f"cannot read existing {label} at {target}: {exc}"
            ) from exc
        if existing == payload:
            return target, "current"
        if not force:
            raise InstallError(
                f"a different {label} already exists at {target}; "
                "rerun with --force only if replacing that file is intended"
            )

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        _reject_symlink_components(target)
        outcome = "replaced" if target.exists() else "installed"
        replace_file_atomic(target, payload, mode=0o644)
    except InstallError:
        raise
    except OSError as exc:
        raise InstallError(f"cannot install {label} at {target}: {exc}") from exc
    return target, outcome


def install_skill(destination: Path, *, force: bool = False) -> tuple[Path, str]:
    """Install the canonical skill and return ``(path, outcome)``.

    ``outcome`` is ``installed``, ``current``, or ``replaced``.
    """
    destination = destination.expanduser().absolute()
    return _install_file(
        destination,
        Path("SKILL.md"),
        canonical_skill_text().encode("utf-8"),
        label="skill",
        force=force,
    )


def _json_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


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
        raise InstallError(
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


def _candidate_executables() -> list[Path]:
    candidates: list[Path] = []
    argv0 = sys.argv[0] if sys.argv else ""
    if argv0:
        path = Path(argv0)
        stem = path.name.lower()
        if stem == "glossabet" or stem == "glossabet.exe":
            candidates.append(path)
    found = shutil.which("glossabet")
    if found:
        candidates.append(Path(found))
    return candidates


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
    raise InstallError(
        "cannot resolve the glossabet executable for the session-start hook "
        f"({detail}); install the CLI (for example `uv tool install glossabet`) "
        "and rerun, or pass --skill-only"
    )


def install_claude_plugin(
    destination: Path,
    executable: Path,
    *,
    force: bool = False,
) -> list[tuple[str, Path, str]]:
    """Write the manifest and hook beside SKILL.md; return ``(label, path, outcome)``."""
    destination = destination.expanduser().absolute()
    results = []
    manifest_path, outcome = _install_file(
        destination,
        CLAUDE_MANIFEST_RELATIVE,
        _json_bytes(claude_plugin_manifest()),
        label="Claude Code plugin manifest",
        force=force,
    )
    results.append(("Claude Code plugin manifest", manifest_path, outcome))
    hooks_path, outcome = _install_file(
        destination,
        CLAUDE_HOOKS_RELATIVE,
        _json_bytes(claude_hooks(executable)),
        label="session-start hook",
        force=force,
    )
    results.append(("session-start hook", hooks_path, outcome))
    return results


_VERBS = {
    "installed": "Installed",
    "current": "Already current",
    "replaced": "Replaced",
}


def install_command(
    agent: str,
    destination_arg: str | None,
    *,
    force: bool = False,
    skill_only: bool = False,
    executable: Path | None = None,
) -> int:
    destination = (
        Path(destination_arg)
        if destination_arg is not None
        else default_skill_directory(agent)
    )
    try:
        path, outcome = install_skill(destination, force=force)
    except InstallError as exc:
        print_error(exc)
        return 1

    safe_agent = escape_terminal_text(agent)
    safe_path = escape_terminal_text(str(path))
    print(f"{_VERBS[outcome]} Glossabet skill for {safe_agent}: {safe_path}")
    if agent != "claude" or skill_only:
        return 0

    # Claude Code: the same folder becomes a skills-directory plugin whose
    # SessionStart hook runs `brief .` in every session. The skill above is
    # already in place; a hook failure is reported and exits non-zero so the
    # caller cannot mistake it for a complete ambient install.
    try:
        if executable is None:
            executable = resolve_cli_executable()
        results = install_claude_plugin(destination, executable, force=force)
    except InstallError as exc:
        print_error(exc)
        print_error(
            "the skill is installed, but Claude Code sessions will not load "
            "the glossary automatically until this is fixed"
        )
        return 1

    for label, written, file_outcome in results:
        print(
            f"{_VERBS[file_outcome]} {label}: "
            f"{escape_terminal_text(str(written))}"
        )
    folder = escape_terminal_text(str(path.parent))
    command = escape_terminal_text(hook_command(executable))
    print(
        "Every Claude Code session will run "
        f"{command} at startup, resume, clear, and compaction "
        "(loaded as plugin glossabet@skills-dir from the next session); "
        "with no glossary it adds nothing."
    )
    print(
        f"To remove ambient loading, delete {folder} or run "
        "`claude plugin disable glossabet@skills-dir`."
    )
    return 0
