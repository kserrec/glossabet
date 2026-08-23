#!/usr/bin/env python3
"""Run and verify bounded installed-skill scenarios through real Codex exec.

Thin entry point: the lane lives in ``evaluation.codex``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.codex.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
