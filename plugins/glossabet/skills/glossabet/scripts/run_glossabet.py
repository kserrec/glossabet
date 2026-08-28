#!/usr/bin/env python3
"""Run the exact Glossabet wheel bundled with the Codex plugin."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

EXPECTED_VERSION = "0.1.0"
# SHA-256 of the exact wheel this runner is authorized to execute. It lives
# here in scripts/ — a different directory than the assets/ wheel it guards —
# so a write primitive scoped to assets/ (e.g. a marketplace updater) cannot
# swap in a tampered wheel and matching hash together. build_plugin.py keeps
# this in sync with the bundled wheel.
EXPECTED_WHEEL_SHA256 = (
    "04b02b62744448079effaf40bef7dd6803e73602525a8acbaa336660e4476821"
)


def _fail(message: str) -> int:
    # Under ``-I`` a user's PYTHONUTF8/PYTHONIOENCODING is ignored; a message
    # naming a non-ASCII path must not itself raise on a narrow stderr.
    stream = sys.stderr
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (ValueError, OSError):
            pass
    print(f"glossabet plugin runner: {message}", file=stream)
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
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if digest != EXPECTED_WHEEL_SHA256:
        raise RuntimeError(
            "bundled wheel failed its integrity check; refusing to execute it"
        )
    return wheel


def _insert_before_site_packages(entry: str) -> None:
    for index, path in enumerate(sys.path):
        lowered = path.replace("\\", "/").lower()
        if "site-packages" in lowered or "dist-packages" in lowered:
            sys.path.insert(index, entry)
            return
    sys.path.append(entry)


def run() -> int:
    if sys.version_info < (3, 10):
        return _fail("Python 3.10 or newer is required")
    try:
        wheel = _load_wheel()
        # After the standard library, before any site-packages: the
        # integrity-checked bundle must never outrank the stdlib (a wheel that
        # somehow carried a top-level module name such as subprocess.py cannot
        # shadow it), but it must outrank a stale or squatted `glossabet`
        # installed elsewhere — otherwise the digest guards a wheel that is
        # not the one executed. The hook also starts this interpreter with
        # ``-I`` (isolated: no PYTHONPATH, no user site, no script directory).
        _insert_before_site_packages(str(wheel))
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
