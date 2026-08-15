"""Canonical skill installation is packaged, explicit, and overwrite-safe."""

import os
from pathlib import Path

import pytest

from glossabet.cli import EXIT_OK, EXIT_USER_ERROR, main
from glossabet.installer import (
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
    assert target.read_text() == "user-owned skill\n"
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
    assert neighbor.read_text() == "keep\n"
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
