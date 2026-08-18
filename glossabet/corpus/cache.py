"""User-owned, content-validated per-file extraction cache.

The scanned repository is hostile input, so it cannot supply extraction
results that Glossabet later trusts. Cache files therefore live in the
current user's platform cache directory, in a repository-keyed subdirectory.
Each reusable entry is matched to the SHA-256 digest of the current file
bytes. A cache is an optimization only: any location, size, JSON, schema, or
entry-shape problem becomes a miss and never changes scan correctness.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from glossabet import __version__
from glossabet.runtime.artifacts import read_bounded_json, write_json_atomic

# Version 4 invalidates doc extraction from before Phase 28.3. Reusing a
# version-3 entry for AGENTS.md/CLAUDE.md could echo a synchronized glossary
# block into evidence even though the current extractor removes that block.
CACHE_VERSION = 4
CACHE_FILE = "cache.json"
CACHE_ROOT_ENV = "GLOSSABET_CACHE_DIR"


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
    return base / "glossabet"


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
        "the selected Glossabet cache directory is inside the scanned "
        "repository"
    )


def load_cache(root: Path) -> dict | None:
    try:
        path = cache_path(root)
    except CacheLocationError:
        return None
    if path.is_symlink() or not path.is_file():
        return None
    read = read_bounded_json(path)
    if not read.ok:
        return None
    data = read.value
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


def clear_cache() -> dict:
    """Remove Glossabet's own incremental-extraction cache and report it.

    Only the layout Glossabet writes is removed: ``<root>/<64-hex>/cache.json``
    entries (plus any ``cache.json.*`` temporaries left by an interrupted
    atomic write) and the per-repository directories once empty, then the
    cache root itself once empty. Directory symlinks are never followed and
    nothing else under the root is deleted; anything unrecognized is left in
    place and reported so a misconfigured ``GLOSSABET_CACHE_DIR`` (say, a home
    directory) can never be wiped by this command.
    """
    root = _platform_cache_root()
    report = {
        "cache_root": str(root),
        "existed": False,
        "removed_entries": 0,
        "unrecognized_left_in_place": [],
        "root_removed": False,
    }
    if root.is_symlink() or not root.is_dir():
        return report
    report["existed"] = True
    try:
        children = sorted(os.scandir(root), key=lambda entry: entry.name)
    except OSError:
        return report
    for child in children:
        if (
            child.is_symlink()
            or not child.is_dir(follow_symlinks=False)
            or len(child.name) != 64
            or any(c not in "0123456789abcdef" for c in child.name)
        ):
            report["unrecognized_left_in_place"].append(child.name)
            continue
        entry_dir = Path(child.path)
        removed_here = False
        leftovers = False
        for item in os.scandir(entry_dir):
            is_cache_file = (
                not item.is_symlink()
                and item.is_file(follow_symlinks=False)
                and (item.name == CACHE_FILE or item.name.startswith(CACHE_FILE + "."))
            )
            if is_cache_file:
                try:
                    os.unlink(item.path)
                    removed_here = True
                except OSError:
                    leftovers = True
            else:
                leftovers = True
        if removed_here:
            report["removed_entries"] += 1
        if leftovers:
            report["unrecognized_left_in_place"].append(child.name)
            continue
        try:
            entry_dir.rmdir()
        except OSError:
            report["unrecognized_left_in_place"].append(child.name)
    if not report["unrecognized_left_in_place"]:
        try:
            root.rmdir()
            report["root_removed"] = True
        except OSError:
            pass
    return report


def cache_clear_command() -> int:
    """CLI: remove Glossabet's user cache and print exactly what happened."""
    from glossabet.runtime.display import escape_terminal_text

    report = clear_cache()
    root = escape_terminal_text(report["cache_root"])
    if not report["existed"]:
        print(f"glossabet cache: nothing to remove ({root} does not exist)")
        return 0
    entries = report["removed_entries"]
    noun = "repository entry" if entries == 1 else "repository entries"
    print(f"glossabet cache: removed {entries} {noun} under {root}")
    if report["root_removed"]:
        print("glossabet cache: cache directory removed")
    for name in report["unrecognized_left_in_place"]:
        print(
            "glossabet cache: left in place (not Glossabet's layout): "
            + escape_terminal_text(name)
        )
    return 0
