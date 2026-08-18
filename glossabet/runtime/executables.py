"""Locating executables the engine runs (``git``) or persists (``glossabet``
in a session-start hook) without ever resolving into the current directory.

``shutil.which`` on Windows searches the current directory *first* (unless
``NoDefaultCurrentDirectoryInExePath`` is set), and ``CreateProcess`` does the
same for a bare program name — so with the current directory being the
repository under analysis, a hostile checkout shipping ``git.exe`` or
``glossabet.bat`` would be run, or worse, written into a hook that every
future session executes. This lookup walks ``PATH`` itself, skips empty and
relative entries (which mean "here"), and refuses any hit that lives inside
the current directory. It never returns a bare name.
"""

from __future__ import annotations

import os
from pathlib import Path


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def which_on_path(name: str) -> Path | None:
    """The first ``name`` on ``PATH`` — absolute directories only, never the
    current directory or anything beneath it — or ``None``."""
    cwd = Path.cwd().resolve()
    if os.name == "nt":
        extensions = [
            ext.lower() for ext in os.environ.get("PATHEXT", ".EXE;.BAT;.CMD").split(";")
            if ext
        ]
        names = [name] if any(name.lower().endswith(e) for e in extensions) else [
            name + ext for ext in extensions
        ]
    else:
        names = [name]
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry or entry in (".", os.curdir):
            continue
        directory = Path(entry)
        if not directory.is_absolute():
            continue
        try:
            resolved = directory.resolve()
        except OSError:
            continue
        if resolved == cwd or _inside(resolved, cwd):
            continue
        for candidate_name in names:
            candidate = directory / candidate_name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate.absolute()
    return None
