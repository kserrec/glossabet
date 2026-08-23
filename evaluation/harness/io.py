"""Bounded JSON reading, framed hashing, deterministic tree walks, and
atomic replacement shared by the evaluation lanes.

Every lane keeps its own error type and wording; these helpers take the
lane's ``fail`` callable rather than choosing a message for it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import NoReturn

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def dotenv_part(name: str) -> bool:
    """A path component naming a dotenv variant, which no lane ever reads."""
    return (
        name == ".env"
        or name.endswith(".env")
        or name.startswith(".env.")
        or ".env." in name
    )


def is_sha256_hex(value: object) -> bool:
    return isinstance(value, str) and _SHA256_HEX.fullmatch(value) is not None


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def framed_digest(records: Iterable[tuple[str, bytes]]) -> str:
    """SHA-256 over length-prefixed (name, content) records.

    The 8-byte big-endian length before each field makes the encoding
    collision-safe: no split of one byte stream into different names and
    contents can produce the same digest. Callers supply records already in
    their canonical order.
    """
    digest = hashlib.sha256()
    for name, content in records:
        encoded = name.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def walk_paths(
    root: Path, *, excluded_directory: str, skip_dotenv: bool = True
) -> list[Path]:
    """Deterministic file walk skipping one directory name.

    Dotenv names are skipped by default so identity digests never touch
    them; a write-diff snapshot may opt back in to track sensitive files by
    stat only.
    """
    files: list[Path] = []
    for current, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(
            name
            for name in directories
            if name != excluded_directory and not dotenv_part(name)
        )
        for name in sorted(names):
            if not skip_dotenv or not dotenv_part(name):
                files.append(Path(current) / name)
    return files


def tree_sha256(root: Path) -> str:
    """Framed digest of every regular file under ``root`` except
    ``__pycache__`` and dotenv names, in repository-relative sorted order."""
    files = walk_paths(root, excluded_directory="__pycache__")
    ordered = sorted(files, key=lambda item: item.relative_to(root).as_posix())
    return framed_digest(
        (path.relative_to(root).as_posix(), path.read_bytes()) for path in ordered
    )


def read_json_object(
    path: Path,
    label: str,
    *,
    max_bytes: int,
    fail: Callable[[str], NoReturn],
    reject_symlink: bool = False,
    overflow_suffix: str = " — refusing to load",
) -> dict:
    """Load a bounded JSON object, reporting every failure through ``fail``."""
    try:
        if reject_symlink and path.is_symlink():
            fail(f"{label} is symlinked")
        if path.stat().st_size > max_bytes:
            fail(f"{label} exceeds {max_bytes} bytes{overflow_suffix}")
        value = json.loads(path.read_bytes())
    except (OSError, ValueError, RecursionError) as exc:
        fail(f"{label} is unreadable: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} must be a JSON object")
    return value


def replace_via_temporary(
    target: Path, write_payload: Callable[[Path], None]
) -> None:
    """Populate a unique same-directory temporary, then replace ``target``."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        write_payload(temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def changed_paths(before: dict[str, tuple], after: dict[str, tuple]) -> list[str]:
    return sorted(
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )
