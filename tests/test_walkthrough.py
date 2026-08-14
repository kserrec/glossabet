"""The checked-in walkthrough is a runnable end-to-end product example."""

import subprocess
import sys
from pathlib import Path


def test_walkthrough_completes_from_an_isolated_copy():
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(root / "scripts" / "run_walkthrough.py")],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Walkthrough passed" in completed.stdout
    assert "0 finding(s)" in completed.stdout
