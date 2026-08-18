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
            'python3 -I -B "$PLUGIN_ROOT/skills/glossabet/scripts/'
            'run_glossabet.py" brief .'
        ),
        "commandWindows": (
            'py -3 -I -B "%PLUGIN_ROOT%\\skills\\glossabet\\scripts\\'
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
        assert "glossabet/agent/brief.py" in archive.namelist()
        assert "glossabet/agent/context_sync.py" in archive.namelist()
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


def test_plugin_runner_rejects_a_tampered_wheel(tmp_path):
    import shutil
    import subprocess
    import sys

    staged = tmp_path / "glossabet"
    shutil.copytree(PLUGIN, staged)
    wheel = next((staged / "skills" / "glossabet" / "assets").glob("*.whl"))
    wheel.write_bytes(wheel.read_bytes() + b"\x00tampered")
    runner = staged / "skills" / "glossabet" / "scripts" / "run_glossabet.py"

    result = subprocess.run(
        [sys.executable, "-B", str(runner), "--version"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "integrity check" in result.stderr


def test_plugin_runner_bundled_wheel_outranks_an_installed_glossabet(tmp_path):
    """The digest guards the wheel that is *executed*: an importable
    `glossabet` on any site-packages/dist-packages segment of sys.path — a
    stale install, a squat — must lose to the bundled wheel, or the runner
    would verify one artifact and run another. Under the real hook the
    interpreter is `-I`, so a PYTHONPATH segment named site-packages is the
    test's stand-in for a site directory; the executed version is what the
    child prints. Sitting after the stdlib is the other half of the same
    ordering; the version output proves only the site-packages half."""
    site = tmp_path / "site-packages"
    (site / "glossabet").mkdir(parents=True)
    (site / "glossabet" / "__init__.py").write_text(
        '__version__ = "0.0.0-squat"\n', encoding="utf-8"
    )
    (site / "glossabet" / "cli.py").write_text(
        'def main(argv=None):\n    print("SQUATTED"); return 0\n', encoding="utf-8"
    )
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--version"],
        cwd=ROOT, text=True, capture_output=True,
        env={**os.environ, "PYTHONPATH": str(site)},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"glossabet {__version__}\n"
    assert "SQUATTED" not in proc.stdout + proc.stderr


def test_plugin_runner_pins_the_bundled_wheel_digest():
    import hashlib
    import re

    runner = (PLUGIN / "skills" / "glossabet" / "scripts"
              / "run_glossabet.py").read_text(encoding="utf-8")
    match = re.search(r'EXPECTED_WHEEL_SHA256 = \(\s*"([0-9a-f]{64})"', runner)
    assert match is not None
    wheel = next((PLUGIN / "skills" / "glossabet" / "assets").glob("*.whl"))
    assert match.group(1) == hashlib.sha256(wheel.read_bytes()).hexdigest()


def test_hook_interpreter_is_isolated_from_a_hostile_working_directory(tmp_path):
    """The SessionStart hook starts the runner with `-I`: a repository whose
    root ships `encodings.py` (or any stdlib-named module) plus a shell rc
    that leaves an empty PYTHONPATH entry (= cwd) must not get that module
    executed before the runner's first line."""
    import json
    import os
    import subprocess

    import shlex

    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())
    command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    # Execute the hook's own command line (interpreter substituted, the
    # plugin root expanded), so dropping `-I` from hooks.json — not merely
    # from this test — is what makes the hostile module run.
    argv = shlex.split(command.replace("$PLUGIN_ROOT", str(PLUGIN)))
    assert argv[0] == "python3"
    argv[0] = sys.executable
    (tmp_path / "encodings.py").write_text(
        'print("PWNED via encodings.py")\nraise SystemExit(99)\n'
    )
    (tmp_path / "a.py").write_text("x = 1\n")
    proc = subprocess.run(
        argv, cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": ":/opt/nothing"},
    )
    assert "PWNED" not in proc.stdout + proc.stderr
    assert proc.returncode == 0, proc.stderr
    # And the same command with the isolation flag removed is what would
    # have executed the repository's module: the flag is doing the work.
    naive = [arg for arg in argv if arg != "-I"]
    proc = subprocess.run(
        naive, cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": ":/opt/nothing"},
    )
    # The hostile module runs before stdout exists, so its traceback (not
    # its print) is the evidence; the exit is a Python startup failure.
    assert proc.returncode != 0
    assert str(tmp_path / "encodings.py") in proc.stderr
