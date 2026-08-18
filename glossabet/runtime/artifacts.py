"""Shared artifact plumbing: safe paths, deterministic writes, and repo roots.

Every artifact is written the same way — sorted keys, stable indentation,
trailing newline — so identical content is identical bytes (determinism,
PLAN.md principle 6). Repository-owned artifact paths reject symlink
components so a hostile checkout cannot redirect either a direct read or a
write. Writes use a same-directory temporary file plus ``os.replace`` so an
interrupted command cannot leave a partially-written JSON document.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


OUT_DIR = "glossabet-out"
# The human-readable vocabulary-health report the /glossabet skill writes at
# the scan root (next to GLOSSARY.md, so a repository browser finds it). It is
# derived Glossabet output: never machine state, never lexical evidence, never
# a freshness input. The engine does not read or write it; the name lives here
# so the scanner exclusion and the freshness pathspec spell it identically.
REPORT_FILE = "GLOSSABET.md"

# Directly-read repository JSON (graph.json and glossary.json) is bounded like
# every walked file (scanner.MAX_FILE_BYTES): an untrusted repo must not be
# able to OOM the process with a giant artifact before json.loads runs. The
# user-owned extraction cache uses the same bound as a corruption safeguard.
MAX_JSON_BYTES = 64_000_000


class ArtifactError(ValueError):
    """A repository artifact path or write is unsafe or unusable."""


# One read discipline for every directly-read file whose size an untrusted
# repository controls. The bound is judged from the bytes actually read (the
# reader takes ``cap + 1`` bytes), never from a stat that a concurrent writer
# could make stale. Callers get a named outcome and decide how to degrade —
# raise, warn, or treat as a miss — without re-deriving the read, the
# encoding, the bound, or the exception set.
READ_ABSENT = "absent"        # no regular file at the path
READ_OK = "read"              # value/payload is usable
READ_OVERSIZED = "oversized"  # more than ``cap`` bytes; nothing was decoded
READ_UNREADABLE = "unreadable"  # the OS refused the read
READ_MALFORMED = "malformed"  # bytes read, but not valid UTF-8 JSON


@dataclass(frozen=True)
class BoundedRead:
    status: str
    cap: int
    # ``payload`` is the exact bytes read (READ_OK from read_bounded_bytes,
    # and READ_OK/READ_MALFORMED from the JSON reader); ``value`` is the
    # decoded JSON document (READ_OK from the JSON readers only).
    payload: bytes | None = None
    value: object = None
    # Best-effort size hint for READ_OVERSIZED (``None`` when even a stat
    # failed); the reason text for READ_UNREADABLE / READ_MALFORMED.
    size: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == READ_OK


def read_bounded_bytes(path: Path | str, cap: int) -> BoundedRead:
    """Read a regular file of at most ``cap`` bytes; ``cap + 1`` bytes are
    requested so the bound is decided by what was read."""
    if not os.path.isfile(path):
        return BoundedRead(READ_ABSENT, cap)
    try:
        with open(path, "rb") as handle:
            payload = handle.read(cap + 1)
    except OSError as exc:
        return BoundedRead(READ_UNREADABLE, cap, error=str(exc))
    if len(payload) > cap:
        try:
            size: int | None = os.path.getsize(path)
        except OSError:
            size = None
        return BoundedRead(READ_OVERSIZED, cap, size=size)
    return BoundedRead(READ_OK, cap, payload=payload)


def parse_bounded_json(raw: bytes | str, cap: int) -> BoundedRead:
    """Decode an already-read document under the same bound and error set:
    UTF-8 only, ``RecursionError`` from hostile nesting caught (json raises
    it outside the ValueError hierarchy)."""
    payload = raw.encode("utf-8") if isinstance(raw, str) else raw
    if len(payload) > cap:
        return BoundedRead(READ_OVERSIZED, cap, size=len(payload))
    try:
        value = json.loads(payload.decode("utf-8"))
    except (ValueError, RecursionError) as exc:
        return BoundedRead(READ_MALFORMED, cap, payload=payload, error=str(exc))
    return BoundedRead(READ_OK, cap, payload=payload, value=value)


def read_bounded_json(path: Path | str, cap: int | None = None) -> BoundedRead:
    """``read_bounded_bytes`` then ``parse_bounded_json``; the default cap is
    the shared repository-JSON bound."""
    cap = MAX_JSON_BYTES if cap is None else cap
    read = read_bounded_bytes(path, cap)
    if not read.ok:
        return read
    return parse_bounded_json(read.payload, cap)


def confined_artifact_path(root: Path, relative: str) -> Path:
    """Return a repository-relative artifact path with no symlink component.

    Direct artifacts are a separate trust surface from walked source files.
    Following even an in-repository symlink here could make a generated write
    replace an unrelated user file, so artifact paths deliberately use the
    stricter rule: no symlink component at all.
    """
    root = root.resolve()
    rel = Path(relative)
    if rel.is_absolute() or not rel.parts or ".." in rel.parts:
        raise ArtifactError(f"unsafe artifact path: {relative}")

    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise ArtifactError(
                f"{relative}: symlinked artifact paths are not trusted"
            )
    try:
        current.resolve(strict=False).relative_to(root)
    except (OSError, ValueError) as exc:
        raise ArtifactError(
            f"{relative}: artifact path resolves outside the repository"
        ) from exc
    return current


def replace_file_atomic(
    path: Path,
    payload: bytes,
    *,
    mode: int | None = None,
    before_replace=None,
) -> None:
    """Write ``payload`` to a same-directory temporary, then replace ``path``.

    The temporary is flushed and fsynced before the swap so an interrupted
    command cannot leave a partial file, and it is unlinked on any failure.
    ``mode`` is applied to the temporary when given; without it the file
    keeps mkstemp's owner-only permissions. ``before_replace``, when given,
    runs after the temporary is durable and immediately before the swap —
    the caller's last chance to abort the replacement.
    """
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        if before_replace is not None:
            before_replace()
        os.replace(temporary, path)
    except BaseException:
        try:
            Path(temporary).unlink()
        except OSError:
            pass
        raise


def write_json_atomic(path: Path, payload: dict, *, indent: int = 2) -> None:
    """Write deterministic JSON atomically, replacing ``path`` at commit."""
    # allow_nan=False fails closed: a NaN would otherwise serialize as the
    # bare non-JSON token ``NaN`` and every strict consumer would reject
    # the artifact.
    serialized = json.dumps(
        payload, indent=indent, sort_keys=True, allow_nan=False
    ) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    replace_file_atomic(path, serialized.encode("utf-8"))


def write_artifact(root: Path, filename: str, payload: dict) -> Path:
    root = root.resolve()
    out = confined_artifact_path(root, OUT_DIR)
    if out.exists() and not out.is_dir():
        raise ArtifactError(f"{OUT_DIR}: artifact output path is not a directory")
    try:
        out.mkdir(exist_ok=True)
        path = confined_artifact_path(root, f"{OUT_DIR}/{filename}")
        write_json_atomic(path, payload)
    except ArtifactError:
        raise
    except OSError as exc:
        raise ArtifactError(f"cannot write {OUT_DIR}/{filename}: {exc}") from exc
    return path
