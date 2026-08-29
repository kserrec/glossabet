"""The managed host-context block as an *inspected* thing: render the
block one glossary deserves, read a root host file safely (no symlinks, no
oversize, a swap between check and open detected by identity), classify the block a file carries (absent /
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
from typing import Literal, TypedDict

from glossabet.agent.brief import build_managed_brief
from glossabet.corpus.scanner import entry_named_exactly
from glossabet.glossary.model import GlossaryDocument
from glossabet.glossary.store import glossary_sha256
from glossabet.managed_block import (
    AGENT_TARGETS,
    BLOCK_RE,
    END_MARKER,
    MANAGED_BLOCK_FORMAT_VERSION,
    MARKER_PREFIX,
    METADATA_RE,
    START_MARKER,
)
from glossabet.runtime.display import escape_terminal_text

MANAGED_CONTEXT_SCHEMA_VERSION = 1
MAX_HOST_FILE_BYTES = 2_000_000


class ContextSyncError(ValueError):
    """A host-context target is unsafe, ambiguous, or cannot be updated."""


ManagedBlockStatus = Literal["absent", "current", "stale", "edited", "uninspectable"]
ISSUE_STATUSES: frozenset[ManagedBlockStatus] = frozenset(
    {"stale", "edited", "uninspectable"}
)


class ManagedTargetReport(TypedDict):
    """One root host file's managed block, classified."""

    path: str
    status: ManagedBlockStatus
    detail: str


class ManagedContextReport(TypedDict):
    """The persisted ``managed_context`` section of drift and validation.
    ``checked`` is false for the pure builders' placeholder."""

    schema_version: int
    checked: bool
    targets: list[ManagedTargetReport]
    issue_count: int


@dataclass(frozen=True)
class _Analysis:
    status: ManagedBlockStatus
    detail: str
    start: int | None = None
    end: int | None = None


def _normalized_newlines(text: str) -> str:
    return text.replace("\r\n", "\n")


def _content_sha256(text: str) -> str:
    return hashlib.sha256(_normalized_newlines(text).encode("utf-8")).hexdigest()


def render_block(glossary: GlossaryDocument, *, newline: str = "\n") -> str:
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


def analyze_managed_block(text: str, glossary: GlossaryDocument) -> _Analysis:
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


def _confirm_unchanged_identity(path: Path, expected: os.stat_result) -> None:
    """Require ``path`` to remain the same file as an earlier observation."""
    try:
        current = path.lstat()
    except FileNotFoundError as exc:
        raise ContextSyncError(
            f"host-context target changed while being inspected: {path.name}"
        ) from exc
    except OSError as exc:
        raise ContextSyncError(f"cannot inspect {path.name}: {exc}") from exc
    if expected.st_ino == 0 or current.st_ino == 0:
        raise ContextSyncError(
            f"cannot inspect {path.name}: filesystem identity is unavailable"
        )
    if (expected.st_dev, expected.st_ino) != (current.st_dev, current.st_ino):
        raise ContextSyncError(
            f"host-context target changed while being inspected: {path.name}"
        )


def read_regular_target(
    path: Path,
) -> tuple[bytes | None, int, tuple[int, int] | None]:
    """Return bytes, mode, and stable identity; reject unsafe targets.

    An absent target has no identity. For an existing target the device/inode
    pair is the one proven equal before, during, and after the bounded read;
    callers that may write can bind a later recheck to this exact file.
    """
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None, 0o644, None
    except OSError as exc:
        raise ContextSyncError(f"cannot inspect {path.name}: {exc}") from exc
    exact_name = entry_named_exactly(path.parent, path.name)
    if exact_name is False:
        # False is also the helper's truthful answer when the path is absent
        # at its first observation. Because this caller already found the
        # path, bind a repeated spelling decision to that earlier file before
        # diagnosing a stable case-only mismatch.
        _confirm_unchanged_identity(path, info)
        repeated_name = entry_named_exactly(path.parent, path.name)
        if repeated_name is True:
            raise ContextSyncError(
                f"host-context target changed while being inspected: {path.name}"
            )
        if repeated_name is None:
            raise ContextSyncError(
                f"cannot inspect {path.name}: its exact name could not be confirmed"
            )
        _confirm_unchanged_identity(path, info)
        # On a case-insensitive filesystem the lookup found ``agents.md``
        # while the exact ``AGENTS.md`` does not exist. Writing "a new
        # AGENTS.md" would silently replace that other file's contents.
        raise ContextSyncError(
            f"a host-context file exists at {path.name} under a different "
            "spelling of its name; rename it to exactly that name first"
        )
    if exact_name is None:
        # A bounded or failed directory listing cannot prove which entry a
        # case-insensitive path lookup opened. Uncertainty never authorizes a
        # write into a project-owned host file.
        raise ContextSyncError(
            f"cannot inspect {path.name}: its exact name could not be confirmed"
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
        if any(observed.st_ino == 0 for observed in (info, opened, current)):
            # Some supported filesystems report zero when portable file
            # identity is unavailable. Three unknown identities comparing
            # equal cannot prove that the target stayed the same file.
            raise ContextSyncError(
                f"cannot inspect {path.name}: filesystem identity is unavailable"
            )
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
    return (
        payload,
        stat.S_IMODE(opened.st_mode),
        (opened.st_dev, opened.st_ino),
    )


def _inspect_target(path: Path, glossary: GlossaryDocument) -> ManagedTargetReport:
    try:
        existing, _mode, _identity = read_regular_target(path)
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


def inspect_managed_context(
    root: Path, glossary: GlossaryDocument
) -> ManagedContextReport:
    """Inspect both supported root host files without writing or following links."""
    targets = [
        _inspect_target(root / filename, glossary)
        for filename in sorted(AGENT_TARGETS.values())
    ]
    return {
        "schema_version": MANAGED_CONTEXT_SCHEMA_VERSION,
        "checked": True,
        "targets": targets,
        "issue_count": sum(target["status"] in ISSUE_STATUSES for target in targets),
    }


def unchecked_managed_context() -> ManagedContextReport:
    """Explicit state for pure builders whose caller supplied no repository."""
    return {
        "schema_version": MANAGED_CONTEXT_SCHEMA_VERSION,
        "targets": [],
        "issue_count": 0,
        "checked": False,
    }


def print_managed_context_issues(report: ManagedContextReport) -> None:
    for target in report["targets"]:
        if target["status"] not in ISSUE_STATUSES:
            continue
        path = escape_terminal_text(target["path"])
        status = escape_terminal_text(target["status"])
        detail = escape_terminal_text(target["detail"])
        print(f"managed context {path}: {status} — {detail}", file=sys.stderr)
