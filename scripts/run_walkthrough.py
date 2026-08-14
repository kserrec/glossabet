#!/usr/bin/env python3
"""Run the documented sample lifecycle without mutating the checked-in copy."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples" / "payment-service"


def _run(command: list[str], *, env: dict[str, str]) -> None:
    print(f"\n$ {' '.join(command)}", flush=True)
    subprocess.run(command, check=True, env=env)


def main() -> int:
    if not SAMPLE.is_dir():
        print(f"walkthrough: sample repository is missing: {SAMPLE}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="glossarize-walkthrough-") as raw:
        work = Path(raw)
        repository = work / "payment-service"
        shutil.copytree(SAMPLE, repository)

        env = os.environ.copy()
        env["GLOSSARIZE_CACHE_DIR"] = str(work / "cache")
        command = [sys.executable, "-m", "glossarize"]
        _run([*command, "analyze", str(repository)], env=env)
        _run([*command, "show", str(repository)], env=env)
        _run([*command, "drift", str(repository)], env=env)
        _run([*command, "validate", str(repository)], env=env)

        out = repository / "glossarize-out"
        drift = json.loads((out / "drift.json").read_text(encoding="utf-8"))
        validation = json.loads(
            (out / "validation.json").read_text(encoding="utf-8")
        )
        if drift["total_findings"] != 0:
            raise RuntimeError(
                f"sample drifted unexpectedly: {drift['total_findings']} findings"
            )
        if validation["total_findings"] != 0:
            raise RuntimeError(
                "sample validation unexpectedly found "
                f"{validation['total_findings']} findings"
            )

    print(
        "\nWalkthrough passed: evidence built, settled glossary displayed, "
        "zero drift found, lexical validation clean, and temporary data removed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
