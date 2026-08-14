"""Shared glossarize-out plumbing: where artifacts live, how they are
written, and how artifact-producing commands resolve their repo root.

Every artifact is written the same way — sorted keys, stable indentation,
trailing newline — so identical content is identical bytes (determinism,
PLAN.md principle 6).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUT_DIR = "glossarize-out"

# Directly-read JSON (graph.json, glossary.json, cache.json) is bounded like
# every walked file (scanner.MAX_FILE_BYTES): an untrusted repo must not be
# able to OOM the process with a giant artifact before json.loads runs.
MAX_JSON_BYTES = 64_000_000


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
        print(f"glossarize: not a directory: {path_arg}", file=sys.stderr)
        return None
    return root.resolve()


def write_artifact(root: Path, filename: str, payload: dict) -> Path:
    out = root / OUT_DIR
    out.mkdir(exist_ok=True)
    path = out / filename
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path
