#!/usr/bin/env python3
"""Assemble the local Codex plugin from one verified Glossabet wheel."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "glossabet"
HOOK_PATH = "./hooks/hooks.json"
SESSION_START_COMMAND = (
    'python3 -B "$PLUGIN_ROOT/skills/glossabet/scripts/run_glossabet.py" brief .'
)
SESSION_START_COMMAND_WINDOWS = (
    'py -3 -B "%PLUGIN_ROOT%\\skills\\glossabet\\scripts\\run_glossabet.py" brief .'
)


def _fail(message: str) -> None:
    raise SystemExit(f"plugin build failed: {message}")


def _source_version() -> str:
    text = (ROOT / "glossabet" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', text, re.MULTILINE)
    if match is None:
        _fail("could not read glossabet/__init__.py version")
    return match.group(1)


def _one_wheel(dist: Path) -> Path:
    wheels = sorted(dist.resolve().glob("glossabet-*.whl"))
    if len(wheels) != 1:
        _fail(f"expected one Glossabet wheel, found {len(wheels)}")
    return wheels[0]


def _check_wheel(wheel: Path, version: str, skill: bytes) -> None:
    expected_dist_info = f"glossabet-{version}.dist-info"
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        metadata_name = f"{expected_dist_info}/METADATA"
        skill_name = "glossabet/_skill/SKILL.md"
        if metadata_name not in names or skill_name not in names:
            _fail("wheel lacks its metadata or canonical skill")
        metadata = BytesParser(policy=policy.default).parsebytes(
            archive.read(metadata_name)
        )
        if metadata["Name"] != "glossabet" or metadata["Version"] != version:
            _fail("wheel name/version does not match the source package")
        if archive.read(skill_name) != skill:
            _fail("wheel skill differs from canonical skill/SKILL.md")


def _check_sources(version: str) -> tuple[Path, Path, bytes]:
    manifest_path = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("name") != "glossabet" or manifest.get("version") != version:
        _fail("plugin manifest name/version does not match the source package")
    if manifest.get("hooks") != HOOK_PATH:
        _fail("plugin manifest does not expose the session-start hook")

    hook_path = PLUGIN_ROOT / "hooks" / "hooks.json"
    hooks = json.loads(hook_path.read_text(encoding="utf-8"))
    expected_hooks = {
        "description": "Load the repository's settled vocabulary into each Codex session.",
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "^(startup|resume|clear|compact)$",
                    "hooks": [
                        {
                            "type": "command",
                            "command": SESSION_START_COMMAND,
                            "commandWindows": SESSION_START_COMMAND_WINDOWS,
                            "timeout": 30,
                            "statusMessage": "Loading settled repository vocabulary",
                            "additionalContextLimit": 0,
                        }
                    ],
                }
            ]
        },
    }
    if hooks != expected_hooks:
        _fail("plugin session-start hook does not match its bounded brief contract")

    runner = (
        PLUGIN_ROOT / "skills" / "glossabet" / "scripts" / "run_glossabet.py"
    )
    runner_text = runner.read_text(encoding="utf-8")
    if f'EXPECTED_VERSION = "{version}"' not in runner_text:
        _fail("plugin runner version does not match the source package")

    skill_path = ROOT / "skill" / "SKILL.md"
    skill = skill_path.read_bytes()
    if f"matching Glossabet {version} engine".encode() not in skill:
        _fail("canonical skill does not declare the source package version")
    return skill_path, runner, skill


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", type=Path)
    args = parser.parse_args()

    version = _source_version()
    wheel = _one_wheel(args.dist_dir)
    skill_path, _runner, skill = _check_sources(version)
    _check_wheel(wheel, version, skill)

    skill_root = PLUGIN_ROOT / "skills" / "glossabet"
    plugin_skill = skill_root / "SKILL.md"
    assets = skill_root / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    plugin_skill.write_bytes(skill_path.read_bytes())

    expected_name = f"glossabet-{version}-py3-none-any.whl"
    for old_wheel in assets.glob("glossabet-*.whl"):
        if old_wheel.name != expected_name:
            old_wheel.unlink()
    shutil.copyfile(wheel, assets / expected_name)

    print(f"assembled Glossabet plugin {version}: {PLUGIN_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
