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


def write_json_atomic(path: Path, payload: dict, *, indent: int = 2) -> None:
    """Write deterministic JSON atomically, replacing ``path`` at commit."""
    serialized = json.dumps(payload, indent=indent, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            Path(temporary).unlink()
        except OSError:
            pass
        raise


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
