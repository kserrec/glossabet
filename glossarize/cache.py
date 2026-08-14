"""User-owned, content-validated per-file extraction cache.

The scanned repository is hostile input, so it cannot supply extraction
results that Glossarize later trusts. Cache files therefore live in the
current user's platform cache directory, in a repository-keyed subdirectory.
Each reusable entry is matched to the SHA-256 digest of the current file
bytes. A cache is an optimization only: any location, size, JSON, schema, or
entry-shape problem becomes a miss and never changes scan correctness.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

from glossarize import __version__
from glossarize.artifacts import oversized, write_json_atomic

CACHE_VERSION = 2
CACHE_FILE = "cache.json"
CACHE_ROOT_ENV = "GLOSSARIZE_CACHE_DIR"


class CacheLocationError(ValueError):
    """The selected user cache would sit inside the scanned repository."""


def _platform_cache_root() -> Path:
    override = os.environ.get(CACHE_ROOT_ENV)
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        xdg = os.environ.get("XDG_CACHE_HOME")
        candidate = Path(xdg).expanduser() if xdg else None
        base = candidate if candidate and candidate.is_absolute() else Path.home() / ".cache"
    return base / "glossarize"


def _repository_identity(root: Path) -> str:
    return os.path.normcase(str(root.resolve()))


def cache_path(root: Path) -> Path:
    root = root.resolve()
    identity = _repository_identity(root)
    key = hashlib.sha256(os.fsencode(identity)).hexdigest()
    path = _platform_cache_root() / key / CACHE_FILE
    try:
        path.resolve(strict=False).relative_to(root)
    except ValueError:
        return path
    raise CacheLocationError(
        "the selected Glossarize cache directory is inside the scanned "
        "repository"
    )


def load_cache(root: Path) -> dict | None:
    try:
        path = cache_path(root)
    except CacheLocationError:
        return None
    if path.is_symlink() or not path.is_file():
        return None
    if oversized(path):
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("cache_version") != CACHE_VERSION:
        return None
    if data.get("generator_version") != __version__:
        return None
    if data.get("repository") != _repository_identity(root):
        return None
    if not isinstance(data.get("files"), dict):
        return None
    return data


def _counter_shape(value: object) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str)
        and isinstance(count, int)
        and not isinstance(count, bool)
        and count >= 0
        for key, count in value.items()
    )


def _entry_shape(entry: dict, kind: str) -> bool:
    size = entry.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        return False
    if kind == "code":
        return (
            isinstance(entry.get("language"), str)
            and _counter_shape(entry.get("identifiers"))
            and isinstance(entry.get("imports"), list)
            and all(isinstance(item, str) for item in entry["imports"])
        )
    if kind == "doc":
        total = entry.get("word_total")
        return (
            _counter_shape(entry.get("words"))
            and isinstance(total, int)
            and not isinstance(total, bool)
            and total >= 0
        )
    return False


def entry_if_valid(
    cached: dict | None,
    rel: str,
    kind: str,
    content_sha256: str,
) -> dict | None:
    if not isinstance(cached, dict):
        return None
    files = cached.get("files")
    if not isinstance(files, dict):
        return None
    entry = files.get(rel)
    if (
        isinstance(entry, dict)
        and entry.get("kind") == kind
        and entry.get("content_sha256") == content_sha256
        and _entry_shape(entry, kind)
    ):
        return entry
    return None


def save_cache(root: Path, files: dict, git_stamp: dict) -> bool:
    payload = {
        "cache_version": CACHE_VERSION,
        "generator_version": __version__,
        "repository": _repository_identity(root),
        "git": git_stamp,
        "files": files,
    }
    try:
        write_json_atomic(cache_path(root), payload, indent=1)
    except (CacheLocationError, OSError):
        return False
    return True
