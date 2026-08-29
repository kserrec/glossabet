#!/usr/bin/env python3
"""Build and verify the blinded second-reviewer evaluation lane.

Thin entry point: the lane lives in ``evaluation.reviewer``.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.reviewer.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
