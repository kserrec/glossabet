"""Per-file extraction cache: .glossarize/cache.json in the scanned repo.

Invalidation is uniform per-file mtime_ns + size (robust across tracked,
untracked, and dirty states; nanosecond resolution avoids same-tick rewrite
staleness). The whole cache invalidates when the generator version changes,
because a tokenizer change alters extraction. A cache is an optimization
only — any doubt reads as a miss, never as stale data.
"""

from __future__ import annotations

import json
from pathlib import Path

from glossarize import __version__

CACHE_VERSION = 1
CACHE_DIR = ".glossarize"
CACHE_FILE = "cache.json"


def cache_path(root: Path) -> Path:
    return root / CACHE_DIR / CACHE_FILE


def load_cache(root: Path) -> dict | None:
    path = cache_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None  # corrupt cache is a miss, never an error
    if data.get("cache_version") != CACHE_VERSION:
        return None
    if data.get("generator_version") != __version__:
        return None
    if not isinstance(data.get("files"), dict):
        return None
    return data


def entry_if_valid(cached: dict | None, rel: str, kind: str,
                   mtime_ns: int, size: int) -> dict | None:
    if cached is None:
        return None
    entry = cached["files"].get(rel)
    if (
        isinstance(entry, dict)
        and entry.get("kind") == kind
        and entry.get("mtime_ns") == mtime_ns
        and entry.get("size") == size
    ):
        return entry
    return None


def save_cache(root: Path, files: dict, git_stamp: dict) -> None:
    out = root / CACHE_DIR
    out.mkdir(exist_ok=True)
    payload = {
        "cache_version": CACHE_VERSION,
        "generator_version": __version__,
        "git": git_stamp,
        "files": files,
    }
    cache_path(root).write_text(
        json.dumps(payload, indent=1, sort_keys=True) + "\n"
    )
