#!/usr/bin/env python3
"""Run the exact Glossabet wheel bundled with the Codex plugin."""

from __future__ import annotations

import json
import sys
from pathlib import Path

EXPECTED_VERSION = "0.1.0"


def _fail(message: str) -> int:
    print(f"glossabet plugin runner: {message}", file=sys.stderr)
    return 2


def _bundle_paths() -> tuple[Path, Path]:
    skill_root = Path(__file__).resolve().parents[1]
    plugin_root = skill_root.parents[1]
    return plugin_root / ".codex-plugin" / "plugin.json", skill_root / "assets"


def _load_wheel() -> Path:
    manifest_path, assets = _bundle_paths()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        raise RuntimeError(f"cannot read plugin manifest: {exc}") from exc
    if manifest.get("name") != "glossabet":
        raise RuntimeError("plugin manifest name is not 'glossabet'")
    if manifest.get("version") != EXPECTED_VERSION:
        raise RuntimeError(
            "plugin manifest version "
            f"{manifest.get('version')!r} does not match {EXPECTED_VERSION}"
        )

    expected_name = f"glossabet-{EXPECTED_VERSION}-py3-none-any.whl"
    wheel = assets / expected_name
    candidates = sorted(
        path.name
        for path in assets.iterdir()
        if path.is_file() and path.name.startswith("glossabet-")
        and path.suffix == ".whl"
    )
    if candidates != [expected_name] or not wheel.is_file():
        raise RuntimeError(
            f"expected only {expected_name!r} in bundled assets; found {candidates!r}"
        )
    return wheel


def run() -> int:
    if sys.version_info < (3, 10):
        return _fail("Python 3.10 or newer is required")
    try:
        wheel = _load_wheel()
        sys.path.insert(0, str(wheel))
        from glossabet import __version__
        from glossabet.cli import main
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        return _fail(str(exc))
    if __version__ != EXPECTED_VERSION:
        return _fail(
            f"bundled engine version {__version__!r} does not match "
            f"{EXPECTED_VERSION}"
        )
    return main()


if __name__ == "__main__":
    raise SystemExit(run())
