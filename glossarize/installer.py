"""Install the canonical agent skill from the Glossarize distribution.

The repository copy at ``skill/SKILL.md`` is the source of truth. Hatch maps
that file into the wheel as ``glossarize/_skill/SKILL.md``; source checkouts
fall back to the repository path so ``uv run glossarize install`` behaves the
same before and after packaging.

Installation writes one user-selected file outside the analyzed repository.
It is idempotent, refuses symlinked destinations, and never replaces a
different existing skill unless the user explicitly supplies ``--force``.
"""

from __future__ import annotations

import os
import sys
import tempfile
from importlib import resources
from pathlib import Path

from glossarize.cli import EXIT_OK, EXIT_USER_ERROR

AGENTS = ("codex", "claude")
_DESTINATIONS = {
    "codex": Path(".agents") / "skills" / "glossarize",
    "claude": Path(".claude") / "skills" / "glossarize",
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
    packaged = resources.files("glossarize").joinpath("_skill", "SKILL.md")
    try:
        return packaged.read_text(encoding="utf-8")
    except FileNotFoundError:
        source = Path(__file__).resolve().parents[1] / "skill" / "SKILL.md"
        try:
            return source.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise RuntimeError(
                "the canonical skill is missing from this Glossarize installation"
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


def _write_text_atomic(path: Path, text: str) -> None:
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        try:
            Path(temporary).unlink()
        except OSError:
            pass
        raise


def install_skill(destination: Path, *, force: bool = False) -> tuple[Path, str]:
    """Install the canonical skill and return ``(path, outcome)``.

    ``outcome`` is ``installed``, ``current``, or ``replaced``.
    """
    destination = destination.expanduser().absolute()
    target = destination / "SKILL.md"
    _reject_symlink_components(target)

    if destination.exists() and not destination.is_dir():
        raise InstallError(
            f"skill destination exists but is not a directory: {destination}"
        )
    if target.exists() and not target.is_file():
        raise InstallError(f"skill target exists but is not a file: {target}")

    text = canonical_skill_text()
    if target.exists():
        try:
            existing = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise InstallError(f"cannot read existing skill at {target}: {exc}") from exc
        if existing == text:
            return target, "current"
        if not force:
            raise InstallError(
                f"a different skill already exists at {target}; "
                "rerun with --force only if replacing that file is intended"
            )

    try:
        destination.mkdir(parents=True, exist_ok=True)
        _reject_symlink_components(target)
        outcome = "replaced" if target.exists() else "installed"
        _write_text_atomic(target, text)
    except InstallError:
        raise
    except OSError as exc:
        raise InstallError(f"cannot install skill at {target}: {exc}") from exc
    return target, outcome


def install_command(
    agent: str,
    destination_arg: str | None,
    *,
    force: bool = False,
) -> int:
    destination = (
        Path(destination_arg)
        if destination_arg is not None
        else default_skill_directory(agent)
    )
    try:
        path, outcome = install_skill(destination, force=force)
    except InstallError as exc:
        print(f"glossarize: {exc}", file=sys.stderr)
        return EXIT_USER_ERROR

    verbs = {
        "installed": "Installed",
        "current": "Already current",
        "replaced": "Replaced",
    }
    print(f"{verbs[outcome]} Glossarize skill for {agent}: {path}")
    return EXIT_OK
