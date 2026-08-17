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
import sys
import tempfile
from pathlib import Path

from glossabet.display import escape_terminal_text

OUT_DIR = "glossabet-out"

# Directly-read repository JSON (graph.json and glossary.json) is bounded like
# every walked file (scanner.MAX_FILE_BYTES): an untrusted repo must not be
# able to OOM the process with a giant artifact before json.loads runs. The
# user-owned extraction cache uses the same bound as a corruption safeguard.
MAX_JSON_BYTES = 64_000_000


class ArtifactError(ValueError):
    """A repository artifact path or write is unsafe or unusable."""


def oversized(path: Path, cap: int | None = None) -> bool:
    """True if the file exists and exceeds the byte cap (caller decides how
    to degrade). A stat failure is not oversized — the reader handles it."""
    cap = MAX_JSON_BYTES if cap is None else cap
    try:
        return path.stat().st_size > cap
    except OSError:
        return False


def repo_root(path_arg: str) -> Path | None:
    """Resolved repository root, or None after reporting the user error."""
    root = Path(path_arg)
    if not root.is_dir():
        print(
            "glossabet: not a directory: " + escape_terminal_text(path_arg),
            file=sys.stderr,
        )
        return None
    return root.resolve()


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
