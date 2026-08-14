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
