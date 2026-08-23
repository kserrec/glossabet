#!/usr/bin/env python3
"""Reproduce Glossabet's pinned deterministic lexical evaluation.

Thin entry point: the lane lives in ``evaluation.deterministic``.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.deterministic.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
