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
import secrets
import stat
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict, TypeGuard

from glossabet import __version__
from glossabet.runtime.artifacts import read_bounded_json, write_json_atomic

# Every change to what an entry means bumps the version, because a stale
# entry is reused silently otherwise: version 4 invalidated doc entries made
# before the managed block was stripped from host documents (a reused
# AGENTS.md/CLAUDE.md entry would echo a synchronized glossary block into
# evidence even though the current extractor removes that block).
CACHE_VERSION = 5
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
    if not _inside(path.resolve(strict=False), root):
        return path
    raise CacheLocationError(
        "the selected Glossabet cache directory is inside the scanned "
        "repository"
    )


def _inside(candidate: Path, root: Path) -> bool:
    """Whether ``candidate`` lies under ``root`` — by identity, not spelling:
    on a case-insensitive filesystem ``…/Repo/.cache`` and ``…/repo`` are one
    tree though their strings differ."""
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        pass
    try:
        root_stat = root.stat()
    except OSError:
        return False
    for ancestor in (candidate, *candidate.parents):
        try:
            if os.path.samestat(ancestor.stat(), root_stat):
                return True
        except OSError:
            continue  # not created yet: keep walking up
    return False


def load_cache(root: Path) -> dict[str, object] | None:
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


class CodeEntry(TypedDict):
    """One extracted code file as cached and folded into evidence."""

    kind: str
    language: str
    identifiers: dict[str, int]
    imports: list[str]
    content_sha256: str
    size: int


class DocEntry(TypedDict):
    """One extracted documentation file as cached and folded into evidence."""

    kind: str
    words: dict[str, int]
    word_total: int
    content_sha256: str
    size: int


def _count(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _counter_shape(value: object) -> TypeGuard[dict[str, int]]:
    return isinstance(value, dict) and all(
        isinstance(key, str) and _count(count) for key, count in value.items()
    )


def _string_list(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _cached_entry(
    cached: Mapping[str, object] | None,
    rel: str,
    kind: str,
    content_sha256: str,
) -> Mapping[str, object] | None:
    """The cache's entry for ``rel`` when it is of ``kind`` and describes
    exactly the content now on disk; its fields are still unvalidated."""
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
    ):
        return entry
    return None


def cached_code_entry(
    cached: Mapping[str, object] | None, rel: str, content_sha256: str
) -> CodeEntry | None:
    """A validated cached code entry for ``rel``, or ``None`` to re-extract."""
    entry = _cached_entry(cached, rel, "code", content_sha256)
    if entry is None:
        return None
    size = entry.get("size")
    language = entry.get("language")
    identifiers = entry.get("identifiers")
    imports = entry.get("imports")
    if (
        not _count(size)
        or not isinstance(language, str)
        or not _counter_shape(identifiers)
        or not _string_list(imports)
    ):
        return None
    return {
        "kind": "code",
        "language": language,
        "identifiers": identifiers,
        "imports": imports,
        "content_sha256": content_sha256,
        "size": size,
    }


def cached_doc_entry(
    cached: Mapping[str, object] | None, rel: str, content_sha256: str
) -> DocEntry | None:
    """A validated cached doc entry for ``rel``, or ``None`` to re-extract."""
    entry = _cached_entry(cached, rel, "doc", content_sha256)
    if entry is None:
        return None
    size = entry.get("size")
    words = entry.get("words")
    total = entry.get("word_total")
    if not _count(size) or not _counter_shape(words) or not _count(total):
        return None
    return {
        "kind": "doc",
        "words": words,
        "word_total": total,
        "content_sha256": content_sha256,
        "size": size,
    }


def save_cache(
    root: Path, files: Mapping[str, object], git_stamp: Mapping[str, object]
) -> bool:
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


class CacheClearReport(TypedDict):
    """What ``clear_cache`` did, in the order it is reported."""

    cache_root: str
    existed: bool
    root_refusal: str | None
    removed_entries: int
    unrecognized_left_in_place: list[str]
    root_removed: bool


def _is_link_or_junction(info: os.stat_result) -> bool:
    """Whether an entry can redirect traversal to another directory tree."""
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(
        reparse_flag and file_attributes & reparse_flag
    )


def _cache_file_owned(name: str, info: os.stat_result) -> bool:
    return (
        not _is_link_or_junction(info)
        and stat.S_ISREG(info.st_mode)
        and (name == CACHE_FILE or name.startswith(CACHE_FILE + "."))
    )


def _capture_sibling(parent: Path) -> Path:
    for _attempt in range(100):
        candidate = parent / f".glossabet-clear-{secrets.token_hex(16)}"
        if not os.path.lexists(candidate):
            return candidate
    raise OSError("could not allocate a cache-clear capture path")


def _restore_capture(captured: Path, original: Path) -> bool:
    if os.path.lexists(original):
        return False
    try:
        os.rename(captured, original)
    except OSError:
        return False
    return True


def clear_cache() -> CacheClearReport:
    """Remove Glossabet's own incremental-extraction cache and report it.

    Only a root containing exactly the layout Glossabet writes is removed:
    ``<root>/<64-hex>/cache.json`` entries plus ``cache.json.*`` temporaries.
    A fully recognized root and each expected child are atomically captured
    and identity-checked before only the known regular files are unlinked.
    Directory links are never followed; any foreign or unreadable entry leaves
    the whole root in place and is reported, so a misconfigured
    ``GLOSSABET_CACHE_DIR`` (say, a home directory) can never be partly cleared.
    """
    root = _platform_cache_root().absolute()
    report: CacheClearReport = {
        "cache_root": str(root),
        "existed": False,
        "root_refusal": None,
        "removed_entries": 0,
        "unrecognized_left_in_place": [],
        "root_removed": False,
    }
    try:
        root_info = root.lstat()
    except FileNotFoundError:
        return report
    except OSError:
        report["root_refusal"] = "the cache path is uninspectable"
        return report
    report["existed"] = True
    if _is_link_or_junction(root_info):
        report["root_refusal"] = "the cache path is symlinked or junctioned"
        return report
    if not stat.S_ISDIR(root_info.st_mode):
        report["root_refusal"] = "the cache path is not a directory"
        return report
    try:
        children = sorted(os.scandir(root), key=lambda entry: entry.name)
    except OSError:
        report["root_refusal"] = "the cache directory could not be listed"
        return report
    recognized_entries: dict[str, tuple[int, int]] = {}
    for child in children:
        try:
            child_info = child.stat(follow_symlinks=False)
        except OSError:
            report["unrecognized_left_in_place"].append(child.name)
            continue
        if (
            _is_link_or_junction(child_info)
            or not stat.S_ISDIR(child_info.st_mode)
            or len(child.name) != 64
            or any(c not in "0123456789abcdef" for c in child.name)
        ):
            report["unrecognized_left_in_place"].append(child.name)
            continue
        entry_dir = Path(child.path)
        try:
            items = list(os.scandir(entry_dir))
        except OSError:
            # Unlistable: left in place and reported, like anything else
            # this command does not understand.
            report["unrecognized_left_in_place"].append(child.name)
            continue
        recognized = True
        for item in items:
            try:
                item_info = item.stat(follow_symlinks=False)
            except OSError:
                recognized = False
                continue
            if not _cache_file_owned(item.name, item_info):
                recognized = False
        if not recognized:
            report["unrecognized_left_in_place"].append(child.name)
            continue
        recognized_entries[child.name] = (child_info.st_dev, child_info.st_ino)
    if report["unrecognized_left_in_place"]:
        # Mixed or unreadable roots stay wholly untouched.
        return report
    try:
        captured_root = _capture_sibling(root.parent)
    except OSError:
        report["root_refusal"] = "a cache capture path could not be allocated"
        return report
    root_captured = False
    try:
        os.rename(root, captured_root)
        root_captured = True
        captured_root_info = captured_root.lstat()
    except OSError:
        if root_captured:
            _restore_capture(captured_root, root)
        report["root_refusal"] = "the cache path changed while being captured"
        return report
    if (
        _is_link_or_junction(captured_root_info)
        or not stat.S_ISDIR(captured_root_info.st_mode)
        or not os.path.samestat(root_info, captured_root_info)
    ):
        restored = _restore_capture(captured_root, root)
        report["root_refusal"] = (
            "the cache path changed while being captured"
            if restored
            else "the changed cache entry was preserved beside its original path"
        )
        return report

    def refuse_captured_root(reason: str) -> CacheClearReport:
        restored = _restore_capture(captured_root, root)
        report["root_refusal"] = (
            reason
            if restored
            else f"{reason}; preserved the captured cache beside its original path"
        )
        return report

    for name, expected_identity in sorted(recognized_entries.items()):
        entry = captured_root / name
        try:
            captured_entry = _capture_sibling(captured_root)
        except OSError:
            report["unrecognized_left_in_place"].append(name)
            return refuse_captured_root(
                "a cache-entry capture path could not be allocated"
            )
        entry_captured = False
        try:
            os.rename(entry, captured_entry)
            entry_captured = True
            captured_info = captured_entry.lstat()
        except OSError:
            if entry_captured:
                _restore_capture(captured_entry, entry)
            report["unrecognized_left_in_place"].append(name)
            return refuse_captured_root(
                "a cache entry changed while being captured"
            )
        if (
            _is_link_or_junction(captured_info)
            or not stat.S_ISDIR(captured_info.st_mode)
            or (captured_info.st_dev, captured_info.st_ino) != expected_identity
        ):
            _restore_capture(captured_entry, entry)
            report["unrecognized_left_in_place"].append(name)
            return refuse_captured_root(
                "a cache entry changed while being captured"
            )
        try:
            items = sorted(os.scandir(captured_entry), key=lambda item: item.name)
        except OSError:
            _restore_capture(captured_entry, entry)
            report["unrecognized_left_in_place"].append(name)
            return refuse_captured_root(
                "a captured cache entry could not be listed"
            )
        try:
            captured_layout_valid = all(
                _cache_file_owned(
                    item.name,
                    item.stat(follow_symlinks=False),
                )
                for item in items
            )
        except OSError:
            captured_layout_valid = False
        if not captured_layout_valid:
            _restore_capture(captured_entry, entry)
            report["unrecognized_left_in_place"].append(name)
            return refuse_captured_root(
                "a captured cache entry no longer matched Glossabet's layout"
            )
        try:
            for item in items:
                latest_info = item.stat(follow_symlinks=False)
                if not _cache_file_owned(item.name, latest_info):
                    raise OSError("cache entry changed before deletion")
                os.unlink(item.path)
            captured_entry.rmdir()
        except OSError:
            _restore_capture(captured_entry, entry)
            report["unrecognized_left_in_place"].append(name)
            return refuse_captured_root(
                "a captured cache entry could not be removed safely"
            )
        report["removed_entries"] += 1
    try:
        captured_root.rmdir()
    except OSError:
        return refuse_captured_root(
            "the captured cache directory could not be removed safely"
        )
    report["root_removed"] = not os.path.lexists(root)
    return report


def cache_clear_command() -> int:
    """CLI: remove Glossabet's user cache and print exactly what happened."""
    from glossabet.runtime.display import escape_terminal_text

    report = clear_cache()
    root = escape_terminal_text(report["cache_root"])
    if report["root_refusal"] is not None:
        entries = report["removed_entries"]
        if entries:
            noun = "repository entry" if entries == 1 else "repository entries"
            # Deletions cannot be rolled back after an operating-system error;
            # keep the failure report truthful about any completed work.
            print(
                f"glossabet cache: removed {entries} {noun} under {root} "
                "before refusal",
                file=sys.stderr,
            )
        print(
            f"glossabet cache: refusing {root}: {report['root_refusal']}",
            file=sys.stderr,
        )
        return 1
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
