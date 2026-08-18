"""The filtered Git state of a repository root: HEAD plus a dirty flag.

This is the one place the engine runs ``git`` against an untrusted checkout.
It owns three things that must never drift apart: the hardened invocation
(a hostile ``.git/config`` must not achieve code execution — see
``SAFE_CONFIG`` and ``_filter_driver_overrides``), the freshness pathspec
that hides only Glossabet-owned output from the dirty check
(``FRESHNESS_STATUS_ARGS``), and the stamp shape ``{"head", "dirty"}`` that
evidence, brief, the Graphify adapter, and the cache all consume. Callers
never spell any of it themselves; tests substitute ``repository_git_stamp``
here to control freshness.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from glossabet.runtime.artifacts import OUT_DIR, REPORT_FILE


# Config keys that let a repository's own .git/config name a program git will
# execute (core.fsmonitor runs on `git status`, hooks on many operations). We
# only read HEAD and dirty state from an untrusted repo, so we override these
# to empty on every call: a hostile .git/config must not achieve code
# execution. Command-line -c beats repo-local config. Content filter drivers
# (filter.<name>.clean/smudge/process) are a third such surface — `git status`
# runs them during content conversion — but their names are attacker-chosen,
# so they are enumerated from the repository's effective config (with
# include.path/includeIf directives resolved, exactly as `git status` sees
# them) and cleared per-name in _filter_driver_overrides.
SAFE_CONFIG = ("-c", "core.fsmonitor=", "-c", "core.hooksPath=/dev/null")


def _resolve_git() -> str:
    """Absolute git path so a repo-shipped git.exe on the cwd search path
    (Windows resolves the current directory before PATH) cannot be run."""
    return shutil.which("git") or "git"


# Freshness describes repository inputs, not Glossabet's own output. Keep the
# pathspec here literal and documented in ARCHITECTURE.md/README: the whole
# top-level output directory and the root GLOSSABET.md vocabulary-health
# report are Glossabet-owned derived output, whether tracked or untracked, so
# regenerating them never makes the inputs they were generated from look
# stale. GLOSSARY.md is deliberately NOT excluded: it is human-governed
# vocabulary, and a change to it is meaningful repository state. Only the
# scan root's GLOSSABET.md is excluded; a nested subproject's report is that
# subproject's output, not this scan's, and stays visible like any other
# path. The pathspec is relative to `git -C root`, not Git's top level,
# because a supported per-subproject scan may start inside a larger worktree.
# --no-renames ensures a move across that ownership boundary still exposes the
# changed non-output path. Git-ignored paths retain Git's ordinary status
# semantics and every other tracked or untracked path remains visible.
FRESHNESS_STATUS_ARGS = (
    "status",
    "--porcelain=v1",
    "--untracked-files=all",
    "--no-renames",
    "--",
    ".",
    f":(exclude){OUT_DIR}",
    f":(exclude){OUT_DIR}/**",
    f":(exclude){REPORT_FILE}",
)


def _filter_driver_overrides(git_exe: str, root: Path) -> tuple[str, ...]:
    """`-c filter.<name>.<op>=` for every content-filter driver the repository
    defines, so `git status` cannot execute an attacker-named clean/smudge/
    process command during content conversion. Reading config runs no filter.
    """
    try:
        # Enumerate the way `git status` will resolve config: WITHOUT --local,
        # so `include.path`/`includeIf` directives are followed. A hostile repo
        # can define its filter driver in an included file that --local never
        # reads, then trip it during status content conversion. Reading config
        # runs no filter. Clearing the user's own global/system filter names as
        # a side effect is harmless: this probe never wants any filter to run.
        proc = subprocess.run(
            [git_exe, *SAFE_CONFIG, "-C", str(root),
             "config", "--name-only", "--get-regexp", r"^filter\."],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    if proc.returncode not in (0, 1):  # 1 == no matching keys
        return ()
    overrides: list[str] = []
    for key in proc.stdout.split():
        if key.startswith("filter.") and key.count(".") >= 2:
            overrides.extend(("-c", f"{key}="))
    return tuple(overrides)


def repository_git_stamp(root: Path) -> dict:
    git_exe = _resolve_git()
    filter_overrides = _filter_driver_overrides(git_exe, root)

    def git(*args: str) -> str | None:
        try:
            proc = subprocess.run(
                [git_exe, *SAFE_CONFIG, *filter_overrides,
                 "-C", str(root), *args],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return proc.stdout if proc.returncode == 0 else None

    head = git("rev-parse", "HEAD")
    if head is None:
        return {"head": None, "dirty": None}
    status = git(*FRESHNESS_STATUS_ARGS)
    return {
        "head": head.strip(),
        "dirty": bool(status.strip()) if status is not None else None,
    }
