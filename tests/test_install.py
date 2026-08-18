"""Canonical skill installation is packaged, explicit, and overwrite-safe."""

import os
from pathlib import Path

import pytest

from glossabet.cli import EXIT_OK, EXIT_USER_ERROR, main
from glossabet.install.installer import (
    canonical_skill_text,
    default_skill_directory,
)

CANONICAL_SKILL = Path(__file__).resolve().parents[1] / "skill" / "SKILL.md"


def test_default_agent_destinations_are_the_documented_personal_locations(tmp_path):
    assert default_skill_directory("codex", home=tmp_path) == (
        tmp_path / ".agents" / "skills" / "glossabet"
    )
    assert default_skill_directory("claude", home=tmp_path) == (
        tmp_path / ".claude" / "skills" / "glossabet"
    )


def test_packaged_or_source_skill_matches_the_canonical_file():
    assert canonical_skill_text() == CANONICAL_SKILL.read_text(encoding="utf-8")


def test_install_writes_canonical_skill_and_is_idempotent(tmp_path, capsys):
    destination = tmp_path / "agent" / "glossabet"

    assert main(["install", "--destination", str(destination)]) == EXIT_OK
    target = destination / "SKILL.md"
    assert target.read_text(encoding="utf-8") == CANONICAL_SKILL.read_text(
        encoding="utf-8"
    )
    assert "Installed" in capsys.readouterr().out

    assert main(["install", "--destination", str(destination)]) == EXIT_OK
    assert "Already current" in capsys.readouterr().out


def test_install_refuses_different_existing_skill_without_force(tmp_path, capsys):
    destination = tmp_path / "glossabet"
    destination.mkdir()
    target = destination / "SKILL.md"
    target.write_text("user-owned skill\n")

    assert main(["install", "--destination", str(destination)]) == EXIT_USER_ERROR
    assert target.read_text(encoding="utf-8") == "user-owned skill\n"
    assert "--force" in capsys.readouterr().err


def test_force_replaces_only_the_skill_file_and_leaves_no_temporary_file(
    tmp_path, capsys
):
    destination = tmp_path / "glossabet"
    destination.mkdir()
    target = destination / "SKILL.md"
    target.write_text("old\n")
    neighbor = destination / "notes.md"
    neighbor.write_text("keep\n")

    assert main([
        "install", "--destination", str(destination), "--force"
    ]) == EXIT_OK
    assert target.read_text(encoding="utf-8") == CANONICAL_SKILL.read_text(
        encoding="utf-8"
    )
    assert neighbor.read_text(encoding="utf-8") == "keep\n"
    assert not list(destination.glob(".SKILL.md.*.tmp"))
    assert "Replaced" in capsys.readouterr().out


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges")
def test_install_refuses_symlinked_destination_components(tmp_path, capsys):
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)

    assert main([
        "install", "--destination", str(linked / "glossabet")
    ]) == EXIT_USER_ERROR
    assert not (outside / "glossabet" / "SKILL.md").exists()
    assert "symlinked" in capsys.readouterr().err


# --- Claude Code: the skill folder becomes a skills-directory plugin -------

import json
import shutil
import subprocess
import sys

from glossabet import __version__
from glossabet.install import claude_plugin
from glossabet.install.claude_plugin import (
    CLAUDE_HOOKS_RELATIVE,
    CLAUDE_MANIFEST_RELATIVE,
    ClaudePluginError,
    claude_hooks,
    claude_plugin_manifest,
    hook_command,
    resolve_cli_executable,
)
from glossabet.install.installer import install_command

ROOT = Path(__file__).resolve().parents[1]
CODEX_PLUGIN = ROOT / "plugins" / "glossabet"
FAKE_EXECUTABLE = Path("/opt/tools/bin/glossabet")


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _wrapper_executable(directory: Path, *, version: str = __version__) -> Path:
    """A real ``glossabet`` executable: a shell wrapper around this interpreter."""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "glossabet"
    if version == __version__:
        body = f'#!/bin/sh\nexec "{sys.executable}" -m glossabet "$@"\n'
    else:
        body = f'#!/bin/sh\necho "glossabet {version}"\n'
    script.write_text(body, encoding="utf-8")
    script.chmod(0o755)
    return script


def _claude_install(home: Path, *args: str, executable: Path | None = FAKE_EXECUTABLE):
    destination = home / ".claude" / "skills" / "glossabet"
    code = install_command(
        "claude",
        str(destination),
        force="--force" in args,
        skill_only="--skill-only" in args,
        executable=executable,
    )
    return code, destination


def test_claude_install_writes_manifest_and_hook_and_nothing_else(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    (home / "unrelated.txt").write_bytes(b"keep")
    before = _tree(home)

    code, destination = _claude_install(home)

    assert code == EXIT_OK
    written = {
        key: value for key, value in _tree(home).items() if key not in before
    }
    assert set(written) == {
        str(Path(".claude/skills/glossabet/SKILL.md")),
        str(Path(".claude/skills/glossabet") / CLAUDE_MANIFEST_RELATIVE),
        str(Path(".claude/skills/glossabet") / CLAUDE_HOOKS_RELATIVE),
    }
    assert {k: v for k, v in _tree(home).items() if k in before} == before

    manifest = json.loads((destination / CLAUDE_MANIFEST_RELATIVE).read_text("utf-8"))
    assert manifest == claude_plugin_manifest()
    assert manifest["name"] == "glossabet"
    assert manifest["version"] == __version__
    assert manifest["skills"] == ["./"]
    assert "hooks" not in manifest  # default hooks/hooks.json discovery, once

    hooks = json.loads((destination / CLAUDE_HOOKS_RELATIVE).read_text("utf-8"))
    assert hooks == claude_hooks(FAKE_EXECUTABLE)
    (entry,) = hooks["hooks"]["SessionStart"]
    assert entry["matcher"] == "^(startup|resume|clear|compact)$"
    (handler,) = entry["hooks"]
    assert handler == {
        "type": "command",
        "command": '"/opt/tools/bin/glossabet" brief .',
        "timeout": 30,
        "statusMessage": "Loading settled repository vocabulary",
    }
    assert set(hooks) == {"hooks"}

    out = capsys.readouterr().out
    assert "Installed Glossabet skill for claude:" in out
    assert "Installed Claude Code plugin manifest:" in out
    assert "Installed session-start hook:" in out
    assert '"/opt/tools/bin/glossabet" brief .' in out
    assert "glossabet@skills-dir" in out


def test_claude_install_is_idempotent(tmp_path, capsys):
    home = tmp_path / "home"
    _claude_install(home)
    snapshot = _tree(home)
    capsys.readouterr()

    code, _ = _claude_install(home)

    assert code == EXIT_OK
    assert _tree(home) == snapshot
    out = capsys.readouterr().out
    assert out.count("Already current") == 3
    assert "Installed" not in out.replace("Already current", "")


def test_claude_install_never_replaces_a_different_hook_without_force(tmp_path, capsys):
    home = tmp_path / "home"
    _claude_install(home)
    hooks = home / ".claude" / "skills" / "glossabet" / CLAUDE_HOOKS_RELATIVE
    hooks.write_text('{"hooks": {"user": "edited"}}\n', encoding="utf-8")
    capsys.readouterr()

    code, _ = _claude_install(home)

    assert code == EXIT_USER_ERROR
    assert hooks.read_text(encoding="utf-8") == '{"hooks": {"user": "edited"}}\n'
    err = capsys.readouterr().err
    assert "different session-start hook" in err
    assert "--force" in err
    assert "will not load the glossary automatically" in err

    code, _ = _claude_install(home, "--force")

    assert code == EXIT_OK
    assert json.loads(hooks.read_text("utf-8")) == claude_hooks(FAKE_EXECUTABLE)
    assert "Replaced session-start hook" in capsys.readouterr().out
    assert not list(hooks.parent.glob(".hooks.json.*.tmp"))


def test_claude_install_never_replaces_a_different_manifest_without_force(tmp_path, capsys):
    home = tmp_path / "home"
    destination = home / ".claude" / "skills" / "glossabet"
    manifest = destination / CLAUDE_MANIFEST_RELATIVE
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name": "someone-elses"}\n', encoding="utf-8")

    code, _ = _claude_install(home)

    assert code == EXIT_USER_ERROR
    assert manifest.read_text(encoding="utf-8") == '{"name": "someone-elses"}\n'
    assert (destination / "SKILL.md").exists()  # the skill itself is in place
    assert not (destination / CLAUDE_HOOKS_RELATIVE).exists()
    assert "different Claude Code plugin manifest" in capsys.readouterr().err


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges")
def test_claude_install_refuses_symlinked_hook_directory(tmp_path, capsys):
    home = tmp_path / "home"
    destination = home / ".claude" / "skills" / "glossabet"
    destination.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (destination / "hooks").symlink_to(outside, target_is_directory=True)

    code, _ = _claude_install(home)

    assert code == EXIT_USER_ERROR
    assert not (outside / "hooks.json").exists()
    assert "symlinked" in capsys.readouterr().err


def test_skill_only_writes_only_the_skill(tmp_path, capsys):
    home = tmp_path / "home"

    code, destination = _claude_install(home, "--skill-only", executable=None)

    assert code == EXIT_OK
    assert list(_tree(home)) == [str(Path(".claude/skills/glossabet/SKILL.md"))]
    out = capsys.readouterr().out
    assert out.strip().count("\n") == 0
    assert "hook" not in out


def test_codex_install_is_unchanged_by_the_claude_route(tmp_path, capsys):
    destination = tmp_path / ".agents" / "skills" / "glossabet"

    assert main(["install", "--destination", str(destination)]) == EXIT_OK

    assert list(_tree(tmp_path)) == [str(Path(".agents/skills/glossabet/SKILL.md"))]
    out = capsys.readouterr().out
    assert out == f"Installed Glossabet skill for codex: {destination / 'SKILL.md'}\n"


def test_unresolvable_executable_still_installs_the_skill_but_fails_loudly(
    tmp_path, capsys, monkeypatch
):
    home = tmp_path / "home"
    monkeypatch.setattr(claude_plugin, "_candidate_executables", lambda: [])

    code, destination = _claude_install(home, executable=None)

    assert code == EXIT_USER_ERROR
    assert list(_tree(home)) == [str(Path(".claude/skills/glossabet/SKILL.md"))]
    err = capsys.readouterr().err
    assert "cannot resolve the glossabet executable" in err
    assert "--skill-only" in err
    assert "will not load the glossary automatically" in err


def test_hook_command_refuses_shell_significant_paths():
    for bad in ('/tmp/a"b/glossabet', "/tmp/$HOME/glossabet", "/tmp/`x`/glossabet",
                "/tmp/a\nb/glossabet"):
        with pytest.raises(ClaudePluginError):
            hook_command(Path(bad))
    assert hook_command(Path("/tmp/with space/glossabet")) == (
        '"/tmp/with space/glossabet" brief .'
    )


def test_manifest_and_hook_metadata_match_the_codex_plugin():
    codex_manifest = json.loads(
        (CODEX_PLUGIN / ".codex-plugin" / "plugin.json").read_text("utf-8")
    )
    claude_manifest = claude_plugin_manifest()
    for field in ("name", "version", "description", "author", "homepage",
                  "repository", "license", "keywords"):
        assert claude_manifest[field] == codex_manifest[field], field

    codex_hooks = json.loads((CODEX_PLUGIN / "hooks" / "hooks.json").read_text("utf-8"))
    (codex_entry,) = codex_hooks["hooks"]["SessionStart"]
    (claude_entry,) = claude_hooks(FAKE_EXECUTABLE)["hooks"]["SessionStart"]
    assert claude_entry["matcher"] == codex_entry["matcher"]
    (codex_handler,) = codex_entry["hooks"]
    (claude_handler,) = claude_entry["hooks"]
    assert claude_handler["statusMessage"] == codex_handler["statusMessage"]
    assert claude_handler["timeout"] == codex_handler["timeout"]
    assert claude_handler["command"].endswith(" brief .")
    assert codex_handler["command"].endswith(" brief .")


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell wrapper")
def test_resolve_cli_executable_verifies_the_version(tmp_path, monkeypatch):
    good = _wrapper_executable(tmp_path / "good")
    stale = _wrapper_executable(tmp_path / "stale", version="0.0.1")

    monkeypatch.setattr(sys, "argv", ["pytest"])
    monkeypatch.setenv("PATH", str(stale.parent))
    with pytest.raises(ClaudePluginError, match="did not report"):
        resolve_cli_executable()

    monkeypatch.setenv("PATH", str(good.parent))
    assert resolve_cli_executable() == good.absolute()

    # The executable that ran the command wins over PATH.
    monkeypatch.setattr(sys, "argv", [str(good), "install"])
    monkeypatch.setenv("PATH", str(stale.parent))
    assert resolve_cli_executable() == good.absolute()


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell wrapper")
def test_written_hook_prints_the_brief_and_writes_nothing(tmp_path, capsys):
    executable = _wrapper_executable(tmp_path / "bin")
    home = tmp_path / "home"
    code, destination = _claude_install(home, executable=executable)
    assert code == EXIT_OK
    hooks = json.loads((destination / CLAUDE_HOOKS_RELATIVE).read_text("utf-8"))
    command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]

    repository = tmp_path / "repo"
    repository.mkdir()
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "payment-service",
            "term": "Payment Service",
            "definition": "The boundary that owns payment attempts.",
            "status": "canonical",
        }],
    }
    subprocess.run(
        [sys.executable, "-m", "glossabet", "save", str(repository)],
        cwd=ROOT, input=json.dumps(glossary), text=True,
        capture_output=True, check=True,
    )
    before = _tree(repository)

    result = subprocess.run(
        command, cwd=repository, shell=True, text=True, capture_output=True
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "Glossabet vocabulary brief v1" in result.stdout
    assert "Payment Service — The boundary that owns payment attempts." in result.stdout
    assert len(result.stdout.encode("utf-8")) <= 4_096
    assert _tree(repository) == before

    empty = tmp_path / "empty"
    empty.mkdir()
    result = subprocess.run(
        command, cwd=empty, shell=True, text=True, capture_output=True
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert list(empty.iterdir()) == []


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not on PATH")
def test_claude_cli_validates_the_installed_plugin_folder(tmp_path):
    home = tmp_path / "home"
    code, destination = _claude_install(home)
    assert code == EXIT_OK

    result = subprocess.run(
        ["claude", "plugin", "validate", str(destination)],
        text=True, capture_output=True, timeout=120,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Validation passed" in result.stdout
