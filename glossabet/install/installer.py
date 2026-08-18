"""Install the canonical agent skill from the Glossabet distribution.

The repository copy at ``skill/SKILL.md`` is the source of truth. Hatch maps
that file into the wheel as ``glossabet/_skill/SKILL.md``; source checkouts
fall back to the repository path so ``uv run glossabet install`` behaves the
same before and after packaging.

Installation writes only inside one user-selected skill directory outside
the analyzed repository. It is idempotent, refuses symlinked destinations,
and never replaces a different existing file unless the user explicitly
supplies ``--force``.

For Claude Code the same directory also becomes a skills-directory plugin
whose session-start hook runs ``brief .``; ``claude_plugin`` describes those
files and this module writes them. Nothing outside the skill directory is
ever written; ``~/.claude/settings.json`` is never touched.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from glossabet.runtime.artifacts import replace_file_atomic
from glossabet.install.claude_plugin import (
    ClaudePluginError,
    claude_plugin_files,
    hook_command,
    resolve_cli_executable,
)
from glossabet.runtime.display import escape_terminal_text, print_error

_DESTINATIONS = {
    "codex": Path(".agents") / "skills" / "glossabet",
    "claude": Path(".claude") / "skills" / "glossabet",
}


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
        source = Path(__file__).resolve().parents[2] / "skill" / "SKILL.md"
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


def install_claude_plugin(
    destination: Path,
    executable: Path,
    *,
    force: bool = False,
) -> list[tuple[str, Path, str]]:
    """Write the manifest and hook beside SKILL.md; return ``(label, path, outcome)``."""
    destination = destination.expanduser().absolute()
    written = []
    for label, relative, payload in claude_plugin_files(executable):
        path, outcome = _install_file(
            destination, relative, payload, label=label, force=force
        )
        written.append((label, path, outcome))
    return written


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
    except (InstallError, ClaudePluginError) as exc:
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
