"""The managed host-context block as an *inspected* thing: render the
block one glossary deserves, read a root host file safely (no symlinks, no
oversize, no swap-under-us), classify the block a file carries (absent /
current / stale / edited / uninspectable), and report the classification.

`context_sync` (the command that writes the block) sits above this module
and uses the same renderer, reader, and analysis; `drift` and `reconcile`
sit beside it and only inspect — they must never depend on the command.
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from glossabet.agent.brief import build_managed_brief
from glossabet.agent.managed_block import (
    AGENT_TARGETS,
    BLOCK_RE,
    END_MARKER,
    MANAGED_BLOCK_FORMAT_VERSION,
    MARKER_PREFIX,
    METADATA_RE,
    START_MARKER,
)
from glossabet.corpus.scanner import entry_named_exactly
from glossabet.glossary.store import glossary_sha256
from glossabet.runtime.display import escape_terminal_text

MANAGED_CONTEXT_SCHEMA_VERSION = 1
MAX_HOST_FILE_BYTES = 2_000_000


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


def render_block(glossary: dict, *, newline: str = "\n") -> str:
    body = build_managed_brief(glossary)
    if any(marker in body for marker in (START_MARKER, END_MARKER, MARKER_PREFIX)):
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


def analyze_managed_block(text: str, glossary: dict) -> _Analysis:
    if MARKER_PREFIX not in text:
        return _Analysis("absent", "no Glossabet managed context block")
    if text.count(START_MARKER) != 1 or text.count(END_MARKER) != 1:
        return _Analysis(
            "edited",
            "managed-context markers are unmatched, duplicated, or changed",
        )
    match = BLOCK_RE.search(text)
    if match is None or text.count(MARKER_PREFIX) != 3:
        return _Analysis(
            "edited",
            "managed-context markers or metadata are malformed",
        )
    # The regex tolerates a leading BOM before a block at byte 0; the block
    # itself (what is compared, and what a resync replaces) starts after it.
    block_start = match.start() + (1 if match.group(0).startswith("\ufeff") else 0)
    block_text = text[block_start:match.end()]

    metadata = METADATA_RE.fullmatch(match.group("metadata"))
    if metadata is None:  # Kept explicit even though BLOCK_RE embeds the pattern.
        return _Analysis("edited", "managed-context metadata is malformed")

    body = _normalized_newlines(match.group("body"))
    declared_content = metadata.group("content")
    if _content_sha256(body) != declared_content:
        return _Analysis(
            "edited",
            "managed-context content no longer matches its content stamp",
            block_start,
            match.end(),
        )

    current_glossary = glossary_sha256(glossary)
    declared_glossary = metadata.group("glossary")
    declared_format = int(metadata.group("format"))
    if declared_format > MANAGED_BLOCK_FORMAT_VERSION:
        return _Analysis(
            "edited",
            "managed-context block uses a newer unsupported format",
            block_start,
            match.end(),
        )
    if (
        declared_format != MANAGED_BLOCK_FORMAT_VERSION
        or declared_glossary != current_glossary
    ):
        return _Analysis(
            "stale",
            "managed-context block does not render the current glossary format/state",
            block_start,
            match.end(),
        )

    try:
        expected = render_block(glossary)
    except ContextSyncError as exc:
        return _Analysis("edited", str(exc), block_start, match.end())
    actual = _normalized_newlines(block_text)
    if actual != expected:
        return _Analysis(
            "edited",
            "managed-context content differs from the current deterministic projection",
            block_start,
            match.end(),
        )
    return _Analysis(
        "current",
        "managed-context block matches the current glossary",
        block_start,
        match.end(),
    )


def read_regular_target(path: Path) -> tuple[bytes | None, int]:
    """Return existing bytes and the mode to preserve; reject unsafe targets."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None, 0o644
    except OSError as exc:
        raise ContextSyncError(f"cannot inspect {path.name}: {exc}") from exc
    if entry_named_exactly(path.parent, path.name) is False:
        # On a case-insensitive filesystem the lookup found ``agents.md``
        # while the exact ``AGENTS.md`` does not exist. Writing "a new
        # AGENTS.md" would silently replace that other file's contents.
        raise ContextSyncError(
            f"a host-context file exists at {path.name} under a different "
            "spelling of its name; rename it to exactly that name first"
        )
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


def _inspect_target(path: Path, glossary: dict) -> dict:
    try:
        existing, _mode = read_regular_target(path)
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
            analysis = analyze_managed_block(text, glossary)
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
