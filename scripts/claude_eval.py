#!/usr/bin/env python3
"""Run and verify bounded Claude Code session-start scenarios.

Thin entry point: the lane lives in ``evaluation.claude``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.claude.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
