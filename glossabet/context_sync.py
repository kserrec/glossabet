"""Explicit, bounded synchronization into agent host instruction files.

Only ``sync_context_command`` writes a project-owned host file. Inspection is
read-only and never follows a target symlink. One exact managed block may be
appended to or replaced inside root ``AGENTS.md`` or ``CLAUDE.md`` while every
surrounding byte remains untouched.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from glossabet.artifacts import repo_root
from glossabet.brief import build_managed_brief, glossary_sha256
from glossabet.display import escape_terminal_text, print_error
from glossabet.glossary import require_glossary


MANAGED_CONTEXT_SCHEMA_VERSION = 1
MANAGED_BLOCK_FORMAT_VERSION = 1
MAX_HOST_FILE_BYTES = 2_000_000

AGENT_TARGETS = {
    "codex": "AGENTS.md",
    "claude": "CLAUDE.md",
}

START_MARKER = "<!-- glossabet:managed-context:start -->"
END_MARKER = "<!-- glossabet:managed-context:end -->"
_MARKER_PREFIX = "<!-- glossabet:managed-context"
_METADATA_RE = re.compile(
    r"<!-- glossabet:managed-context "
    r"format=(?P<format>[0-9]{1,9}) "
    r"glossary-sha256=(?P<glossary>[0-9a-f]{64}) "
    r"content-sha256=(?P<content>[0-9a-f]{64}) -->"
)
_BLOCK_RE = re.compile(
    rf"(?m)^{re.escape(START_MARKER)}\r?\n"
    rf"(?P<metadata>{_METADATA_RE.pattern})\r?\n"
    rf"(?P<body>.*?)"
    rf"^{re.escape(END_MARKER)}(?=\r?$)",
    re.DOTALL,
)


class ContextSyncError(ValueError):
    """A host-context target is unsafe, ambiguous, or cannot be updated."""


@dataclass(frozen=True)
class _Analysis:
    status: str
    detail: str
    start: int | None = None
    end: int | None = None


def _normalized_newlines(text: str) -> str:
    return text.replace("\r\n", "\n")


def _content_sha256(text: str) -> str:
    return hashlib.sha256(_normalized_newlines(text).encode("utf-8")).hexdigest()


def _render_block(glossary: dict, *, newline: str = "\n") -> str:
    body = build_managed_brief(glossary)
    if any(marker in body for marker in (START_MARKER, END_MARKER, _MARKER_PREFIX)):
        raise ContextSyncError(
            "the glossary renders reserved managed-context marker text"
        )
    metadata = (
        "<!-- glossabet:managed-context "
        f"format={MANAGED_BLOCK_FORMAT_VERSION} "
        f"glossary-sha256={glossary_sha256(glossary)} "
        f"content-sha256={_content_sha256(body)} -->"
    )
    block = START_MARKER + "\n" + metadata + "\n" + body + END_MARKER
    return block if newline == "\n" else block.replace("\n", newline)


def _analyze_managed_block(text: str, glossary: dict) -> _Analysis:
    if _MARKER_PREFIX not in text:
        return _Analysis("absent", "no Glossabet managed context block")
    if text.count(START_MARKER) != 1 or text.count(END_MARKER) != 1:
        return _Analysis(
            "edited",
            "managed-context markers are unmatched, duplicated, or changed",
        )
    match = _BLOCK_RE.search(text)
    if match is None or text.count(_MARKER_PREFIX) != 3:
        return _Analysis(
            "edited",
            "managed-context markers or metadata are malformed",
        )

    metadata = _METADATA_RE.fullmatch(match.group("metadata"))
    if metadata is None:  # Kept explicit even though _BLOCK_RE embeds the pattern.
        return _Analysis("edited", "managed-context metadata is malformed")

    body = _normalized_newlines(match.group("body"))
    declared_content = metadata.group("content")
    if _content_sha256(body) != declared_content:
        return _Analysis(
            "edited",
            "managed-context content no longer matches its content stamp",
            match.start(),
            match.end(),
        )

    current_glossary = glossary_sha256(glossary)
    declared_glossary = metadata.group("glossary")
    declared_format = int(metadata.group("format"))
    if declared_format > MANAGED_BLOCK_FORMAT_VERSION:
        return _Analysis(
            "edited",
            "managed-context block uses a newer unsupported format",
            match.start(),
            match.end(),
        )
    if (
        declared_format != MANAGED_BLOCK_FORMAT_VERSION
        or declared_glossary != current_glossary
    ):
        return _Analysis(
            "stale",
            "managed-context block does not render the current glossary format/state",
            match.start(),
            match.end(),
        )

    try:
        expected = _render_block(glossary)
    except ContextSyncError as exc:
        return _Analysis("edited", str(exc), match.start(), match.end())
    actual = _normalized_newlines(match.group(0))
    if actual != expected:
        return _Analysis(
            "edited",
            "managed-context content differs from the current deterministic projection",
            match.start(),
            match.end(),
        )
    return _Analysis(
        "current",
        "managed-context block matches the current glossary",
        match.start(),
        match.end(),
    )


def _detect_newline(text: str) -> str:
    crlf = text.count("\r\n")
    bare_lf = text.count("\n") - crlf
    return "\r\n" if crlf and not bare_lf else "\n"


def _read_regular_target(path: Path) -> tuple[bytes | None, int]:
    """Return existing bytes and the mode to preserve; reject unsafe targets."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None, 0o644
    except OSError as exc:
        raise ContextSyncError(f"cannot inspect {path.name}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode):
        raise ContextSyncError(f"refusing symlinked host-context target: {path.name}")
    if not stat.S_ISREG(info.st_mode):
        raise ContextSyncError(f"host-context target is not a regular file: {path.name}")
    if info.st_size > MAX_HOST_FILE_BYTES:
        raise ContextSyncError(
            f"{path.name} is larger than {MAX_HOST_FILE_BYTES} bytes"
        )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        current = path.lstat()
        identities = {
            (info.st_dev, info.st_ino),
            (opened.st_dev, opened.st_ino),
            (current.st_dev, current.st_ino),
        }
        if (
            len(identities) != 1
            or not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(current.st_mode)
        ):
            raise ContextSyncError(
                f"host-context target changed while being inspected: {path.name}"
            )
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            payload = handle.read(MAX_HOST_FILE_BYTES + 1)
    except ContextSyncError:
        raise
    except OSError as exc:
        raise ContextSyncError(f"cannot read {path.name}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(payload) > MAX_HOST_FILE_BYTES:
        raise ContextSyncError(
            f"{path.name} is larger than {MAX_HOST_FILE_BYTES} bytes"
        )
    return payload, stat.S_IMODE(opened.st_mode)


def _write_bytes_atomic(
    path: Path,
    payload: bytes,
    mode: int,
    *,
    expected: bytes | None,
) -> None:
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        current, current_mode = _read_regular_target(path)
        if current != expected or (
            expected is not None and current_mode != mode
        ):
            raise ContextSyncError(
                f"{path.name} changed during synchronization; no update was made"
            )
        os.replace(temporary, path)
    except BaseException:
        try:
            Path(temporary).unlink()
        except OSError:
            pass
        raise


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
    existing_bytes, mode = _read_regular_target(target)
    if existing_bytes is None:
        existing = ""
    else:
        try:
            existing = existing_bytes.decode("utf-8")
        except UnicodeError as exc:
            raise ContextSyncError(f"{filename} is not valid UTF-8") from exc

    analysis = _analyze_managed_block(existing, glossary)
    newline = _detect_newline(existing)
    block = _render_block(glossary, newline=newline)

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


def _inspect_target(path: Path, glossary: dict) -> dict:
    try:
        existing, _mode = _read_regular_target(path)
    except ContextSyncError as exc:
        return {"path": path.name, "status": "uninspectable", "detail": str(exc)}
    if existing is None:
        analysis = _Analysis("absent", "no host-context file")
    else:
        try:
            text = existing.decode("utf-8")
        except UnicodeError:
            analysis = _Analysis("uninspectable", "host-context file is not valid UTF-8")
        else:
            analysis = _analyze_managed_block(text, glossary)
    return {"path": path.name, "status": analysis.status, "detail": analysis.detail}


def inspect_managed_context(root: Path, glossary: dict) -> dict:
    """Inspect both supported root host files without writing or following links."""
    targets = [
        _inspect_target(root / filename, glossary)
        for filename in sorted(AGENT_TARGETS.values())
    ]
    issue_statuses = {"stale", "edited", "uninspectable"}
    return {
        "schema_version": MANAGED_CONTEXT_SCHEMA_VERSION,
        "checked": True,
        "targets": targets,
        "issue_count": sum(target["status"] in issue_statuses for target in targets),
    }


def unchecked_managed_context() -> dict:
    """Explicit state for pure builders whose caller supplied no repository."""
    return {
        "schema_version": MANAGED_CONTEXT_SCHEMA_VERSION,
        "targets": [],
        "issue_count": 0,
        "checked": False,
    }


def print_managed_context_issues(report: dict) -> None:
    for target in report.get("targets", []):
        if target.get("status") not in {"stale", "edited", "uninspectable"}:
            continue
        path = escape_terminal_text(str(target.get("path", "host context")))
        status = escape_terminal_text(str(target.get("status", "issue")))
        detail = escape_terminal_text(str(target.get("detail", "")))
        print(f"managed context {path}: {status} — {detail}", file=sys.stderr)


def strip_managed_context_for_evidence(relative: str, text: str) -> str:
    """Remove one exactly bounded managed block from root host-file evidence.

    The surrounding hand-written instructions remain lexical evidence. Even a
    body whose stamp was edited is removed when its two exact outer markers
    still define one unambiguous region; malformed marker layouts are left
    untouched and separately flagged by drift/validate.
    """
    if relative not in AGENT_TARGETS.values():
        return text
    if text.count(START_MARKER) != 1 or text.count(END_MARKER) != 1:
        return text
    start = text.find(START_MARKER)
    end = text.find(END_MARKER, start + len(START_MARKER))
    if start < 0 or end < 0:
        return text
    end += len(END_MARKER)
    return text[:start] + text[end:]


def sync_context_command(path_arg: str, agent: str, *, force: bool = False) -> int:
    root = repo_root(path_arg)
    if root is None:
        return 1
    glossary = require_glossary(root, "no glossary to synchronize")
    if glossary is None:
        return 1
    try:
        path, outcome = sync_context(root, glossary, agent, force=force)
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
