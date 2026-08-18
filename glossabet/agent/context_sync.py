"""Explicit, bounded synchronization into agent host instruction files.

Only ``sync_context_command`` writes a project-owned host file. Inspection is
read-only and never follows a target symlink. One exact managed block may be
appended to or replaced inside root ``AGENTS.md`` or ``CLAUDE.md`` while every
surrounding byte remains untouched.
"""

from __future__ import annotations

from pathlib import Path

from glossabet.runtime.artifacts import replace_file_atomic
from glossabet.runtime.display import escape_terminal_text, print_error
from glossabet.runtime.engine_run import GLOSSARY_REQUIRED, open_run
from glossabet.agent.managed_block import AGENT_TARGETS
from glossabet.agent.managed_context import (
    ContextSyncError,
    analyze_managed_block,
    read_regular_target,
    render_block,
)


def _detect_newline(text: str) -> str:
    crlf = text.count("\r\n")
    bare_lf = text.count("\n") - crlf
    return "\r\n" if crlf and not bare_lf else "\n"


def _write_bytes_atomic(
    path: Path,
    payload: bytes,
    mode: int,
    *,
    expected: bytes | None,
) -> None:
    def _require_unchanged_target() -> None:
        current, current_mode = read_regular_target(path)
        if current != expected or (
            expected is not None and current_mode != mode
        ):
            raise ContextSyncError(
                f"{path.name} changed during synchronization; no update was made"
            )

    replace_file_atomic(
        path, payload, mode=mode, before_replace=_require_unchanged_target
    )


def _append_block(text: str, block: str, newline: str) -> str:
    if not text:
        return block + newline
    if text.endswith(newline + newline):
        separator = ""
    elif text.endswith(newline):
        separator = newline
    else:
        separator = newline + newline
    return text + separator + block + newline


def sync_context(
    root: Path,
    glossary: dict,
    agent: str,
    *,
    force: bool = False,
) -> tuple[Path, str]:
    """Synchronize one explicitly selected host file.

    Returns ``(path, outcome)`` where outcome is ``created``, ``appended``,
    ``updated``, ``repaired``, or ``current``. ``force`` repairs only a
    structurally valid block whose exact outer markers and metadata still
    provide an unambiguous replacement range; malformed markers or metadata
    are never overwritten.
    """
    try:
        filename = AGENT_TARGETS[agent]
    except KeyError as exc:
        raise ContextSyncError(f"unsupported agent: {agent}") from exc
    root = root.resolve()
    target = root / filename
    existing_bytes, mode = read_regular_target(target)
    if existing_bytes is None:
        existing = ""
    else:
        try:
            existing = existing_bytes.decode("utf-8")
        except UnicodeError as exc:
            raise ContextSyncError(f"{filename} is not valid UTF-8") from exc

    analysis = analyze_managed_block(existing, glossary)
    newline = _detect_newline(existing)
    block = render_block(glossary, newline=newline)

    if analysis.status == "current":
        return target, "current"
    if analysis.status == "edited":
        if analysis.start is None or analysis.end is None:
            raise ContextSyncError(
                f"refusing ambiguous managed-context collision in {filename}: "
                + analysis.detail
            )
        if not force:
            raise ContextSyncError(
                f"managed context in {filename} was edited; rerun with --force "
                "only if replacing that managed block is intended"
            )

    if analysis.status == "absent":
        updated = _append_block(existing, block, newline)
        outcome = "created" if existing_bytes is None else "appended"
    else:
        assert analysis.start is not None and analysis.end is not None
        updated = existing[:analysis.start] + block + existing[analysis.end:]
        outcome = "repaired" if analysis.status == "edited" else "updated"

    payload = updated.encode("utf-8")
    try:
        _write_bytes_atomic(
            target,
            payload,
            mode,
            expected=existing_bytes,
        )
    except OSError as exc:
        raise ContextSyncError(f"cannot update {filename}: {exc}") from exc
    return target, outcome


def sync_context_command(path_arg: str, agent: str, *, force: bool = False) -> int:
    run = open_run(
        path_arg, glossary=GLOSSARY_REQUIRED,
        missing="no glossary to synchronize",
    )
    try:
        path, outcome = sync_context(
            run.root, run.glossary, agent, force=force
        )
    except ContextSyncError as exc:
        print_error(exc)
        return 1
    verbs = {
        "created": "Created",
        "appended": "Appended",
        "updated": "Updated",
        "repaired": "Repaired",
        "current": "Already current",
    }
    safe_path = escape_terminal_text(str(path))
    print(f"{verbs[outcome]} managed vocabulary context: {safe_path}")
    return 0
