"""The Codex plugin bundles one canonical skill and one matching CLI wheel."""

from __future__ import annotations

import json
import os
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
HOOKS = PLUGIN / "hooks" / "hooks.json"


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
    assert manifest["hooks"] == "./hooks/hooks.json"
    assert manifest["license"] == "Apache-2.0"
    assert manifest["author"]["name"] == "Kyle Serrecchia"
    # The marketplace UI links these; they must track the renamed repo.
    assert manifest["homepage"] == "https://github.com/kserrec/glossabet"
    assert manifest["repository"] == "https://github.com/kserrec/glossabet"
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


def _session_start_handler() -> dict:
    config = json.loads(HOOKS.read_text(encoding="utf-8"))
    assert set(config) == {"description", "hooks"}
    assert set(config["hooks"]) == {"SessionStart"}
    groups = config["hooks"]["SessionStart"]
    assert len(groups) == 1
    assert groups[0]["matcher"] == "^(startup|resume|clear|compact)$"
    assert len(groups[0]["hooks"]) == 1
    return groups[0]["hooks"][0]


def test_plugin_session_start_hook_is_bounded_and_version_coupled():
    handler = _session_start_handler()

    assert handler == {
        "type": "command",
        "command": (
            'python3 -B "$PLUGIN_ROOT/skills/glossabet/scripts/'
            'run_glossabet.py" brief .'
        ),
        "commandWindows": (
            'py -3 -B "%PLUGIN_ROOT%\\skills\\glossabet\\scripts\\'
            'run_glossabet.py" brief .'
        ),
        "timeout": 30,
        "statusMessage": "Loading settled repository vocabulary",
        "additionalContextLimit": 0,
    }


def _run_session_start_hook(repository: Path) -> subprocess.CompletedProcess[str]:
    handler = _session_start_handler()
    command = handler["commandWindows" if os.name == "nt" else "command"]
    return subprocess.run(
        command,
        cwd=repository,
        env={**os.environ, "PLUGIN_ROOT": str(PLUGIN)},
        text=True,
        capture_output=True,
        shell=True,
    )


def _repository_files(root: Path) -> dict[Path, bytes]:
    files: dict[Path, bytes] = {}
    for current, directories, names in os.walk(root):
        directories[:] = [
            name
            for name in directories
            if name != ".env"
            and not name.endswith(".env")
            and not name.startswith(".env.")
            and ".env." not in name
        ]
        for name in names:
            if (
                name == ".env"
                or name.endswith(".env")
                or name.startswith(".env.")
                or ".env." in name
            ):
                continue
            path = Path(current) / name
            files[path.relative_to(root)] = path.read_bytes()
    return files


def test_plugin_session_start_hook_emits_fresh_brief_without_writing(tmp_path):
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
    subprocess.run(
        [sys.executable, str(RUNNER), "save", str(tmp_path)],
        cwd=ROOT,
        input=json.dumps(glossary),
        text=True,
        capture_output=True,
        check=True,
    )
    before = _repository_files(tmp_path)

    result = _run_session_start_hook(tmp_path)

    after = _repository_files(tmp_path)
    assert result.returncode == 0
    assert result.stderr == ""
    assert "Glossabet vocabulary brief v1" in result.stdout
    assert "Payment Service — The boundary that owns payment attempts." in result.stdout
    assert after == before


def test_plugin_session_start_hook_without_glossary_contributes_nothing(tmp_path):
    before = list(tmp_path.iterdir())

    result = _run_session_start_hook(tmp_path)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == before


def test_plugin_wheel_matches_package_version_entry_point_and_skill():
    wheel = _wheel()
    with zipfile.ZipFile(wheel) as archive:
        assert "glossabet/brief.py" in archive.namelist()
        assert "glossabet/context_sync.py" in archive.namelist()
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
