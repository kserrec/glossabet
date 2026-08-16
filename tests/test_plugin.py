"""The Codex plugin bundles one canonical skill and one matching CLI wheel."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path

from glossabet import __version__

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "glossabet"
SKILL = ROOT / "skill" / "SKILL.md"
PLUGIN_SKILL = PLUGIN / "skills" / "glossabet" / "SKILL.md"
RUNNER = PLUGIN / "skills" / "glossabet" / "scripts" / "run_glossabet.py"
ASSETS = PLUGIN / "skills" / "glossabet" / "assets"


def _manifest(plugin: Path = PLUGIN) -> dict:
    return json.loads(
        (plugin / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )


def _wheel() -> Path:
    wheels = sorted(ASSETS.glob("glossabet-*.whl"))
    assert [wheel.name for wheel in wheels] == [
        f"glossabet-{__version__}-py3-none-any.whl"
    ]
    return wheels[0]


def test_plugin_manifest_and_sources_are_version_coupled():
    manifest = _manifest()
    assert manifest["name"] == "glossabet"
    assert manifest["version"] == __version__
    assert manifest["skills"] == "./skills/"
    assert manifest["license"] == "Apache-2.0"
    assert manifest["author"]["name"] == "Kyle Serrecchia"
    assert PLUGIN_SKILL.read_bytes() == SKILL.read_bytes()

    skill_text = SKILL.read_text(encoding="utf-8")
    assert f"matching Glossabet {__version__} engine" in skill_text
    assert f"`glossabet {__version__}`" in skill_text
    runner_text = RUNNER.read_text(encoding="utf-8")
    assert re.search(
        rf'^EXPECTED_VERSION = "{re.escape(__version__)}"$',
        runner_text,
        re.MULTILINE,
    )


def test_plugin_wheel_matches_package_version_entry_point_and_skill():
    wheel = _wheel()
    with zipfile.ZipFile(wheel) as archive:
        assert "glossabet/brief.py" in archive.namelist()
        metadata_path = f"glossabet-{__version__}.dist-info/METADATA"
        metadata = BytesParser(policy=policy.default).parsebytes(
            archive.read(metadata_path)
        )
        assert metadata["Name"] == "glossabet"
        assert metadata["Version"] == __version__
        assert metadata.get_all("Requires-Dist", []) == []
        assert archive.read("glossabet/_skill/SKILL.md") == SKILL.read_bytes()
        entry_points = archive.read(
            f"glossabet-{__version__}.dist-info/entry_points.txt"
        ).decode("utf-8")
        assert "glossabet = glossabet.cli:main" in entry_points


def test_plugin_runner_executes_bundled_cli():
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--version"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout == f"glossabet {__version__}\n"
    assert result.stderr == ""


def test_plugin_runner_executes_bundled_brief(tmp_path):
    glossary = {
        "schema_version": 1,
        "concepts": [
            {
                "id": "payment-service",
                "term": "Payment Service",
                "definition": "The boundary that owns payment attempts.",
                "status": "canonical",
            }
        ],
    }
    saved = subprocess.run(
        [sys.executable, str(RUNNER), "save", str(tmp_path)],
        cwd=ROOT,
        input=json.dumps(glossary),
        text=True,
        capture_output=True,
        check=True,
    )
    result = subprocess.run(
        [sys.executable, str(RUNNER), "brief", str(tmp_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "saved glossary" in saved.stdout
    assert "Glossabet vocabulary brief v1" in result.stdout
    assert "Payment Service — The boundary that owns payment attempts." in result.stdout
    assert result.stderr == ""


def test_plugin_runner_rejects_a_manifest_version_mismatch(tmp_path):
    copy = tmp_path / "glossabet"
    shutil.copytree(PLUGIN, copy)
    manifest_path = copy / ".codex-plugin" / "plugin.json"
    manifest = _manifest(copy)
    manifest["version"] = "9.9.9"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(copy / "skills" / "glossabet" / "scripts" / "run_glossabet.py"),
            "--version",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 2
    assert "manifest version '9.9.9' does not match" in result.stderr
