"""Git freshness must ignore only Glossarize-owned repository output."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from glossarize.cli import main
from glossarize.evidence import _git_stamp


def _git(root: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    subprocess.run(
        ["git", *args],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(
    root: Path,
    *,
    extra_tracked: dict[str, str] | None = None,
    ignore: str | None = None,
) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Glossarize Test")

    tracked = ["main.py"]
    (root / "main.py").write_text("original_name = 1\n")
    for relative, content in (extra_tracked or {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        tracked.append(relative)
    if ignore is not None:
        (root / ".gitignore").write_text(ignore)
        tracked.append(".gitignore")

    _git(root, "add", "--", *tracked)
    _git(
        root,
        "-c",
        "commit.gpgsign=false",
        "-c",
        "core.hooksPath=/dev/null",
        "commit",
        "-qm",
        "initial",
    )


def _is_fresh(stamped: dict, live: dict) -> bool:
    return (
        isinstance(stamped.get("head"), str)
        and stamped["head"] == live.get("head")
        and stamped.get("dirty") is False
        and live.get("dirty") is False
    )


def test_first_scan_of_clean_repo_is_immediately_fresh_without_gitignore_edit(
    tmp_path,
):
    _init_repo(tmp_path)
    assert not (tmp_path / ".gitignore").exists()

    assert main(["scan", str(tmp_path)]) == 0

    evidence = json.loads(
        (tmp_path / "glossarize-out" / "evidence.json").read_text()
    )
    assert _is_fresh(evidence["repository"]["git"], _git_stamp(tmp_path))
    assert not (tmp_path / ".gitignore").exists()


def test_first_scan_of_nested_repository_scope_is_immediately_fresh(tmp_path):
    relative = "packages/service/main.py"
    _init_repo(tmp_path, extra_tracked={relative: "service_name = 1\n"})
    service = tmp_path / "packages" / "service"

    assert main(["scan", str(service)]) == 0

    evidence = json.loads(
        (service / "glossarize-out" / "evidence.json").read_text()
    )
    assert _is_fresh(evidence["repository"]["git"], _git_stamp(service))


def test_user_change_after_scan_makes_evidence_stale(tmp_path):
    _init_repo(tmp_path)
    assert main(["scan", str(tmp_path)]) == 0
    stamped = json.loads(
        (tmp_path / "glossarize-out" / "evidence.json").read_text()
    )["repository"]["git"]

    (tmp_path / "main.py").write_text("changed_after_scan = 1\n")

    assert not _is_fresh(stamped, _git_stamp(tmp_path))


def test_tracked_and_untracked_generated_output_do_not_dirty_freshness(tmp_path):
    _init_repo(
        tmp_path,
        extra_tracked={"glossarize-out/evidence.json": "{}\n"},
    )
    output = tmp_path / "glossarize-out"
    (output / "evidence.json").write_text('{"refreshed": true}\n')
    (output / "drift.json").write_text("{}\n")
    (output / "validation.json").write_text("{}\n")

    assert _git_stamp(tmp_path)["dirty"] is False


def test_move_into_generated_output_keeps_source_deletion_visible(tmp_path):
    _init_repo(tmp_path)
    output = tmp_path / "glossarize-out"
    output.mkdir()
    (tmp_path / "main.py").rename(output / "main.py")

    assert _git_stamp(tmp_path)["dirty"] is True


def test_move_out_of_generated_output_keeps_destination_visible(tmp_path):
    _init_repo(
        tmp_path,
        extra_tracked={"glossarize-out/evidence.json": "{}\n"},
    )
    (tmp_path / "glossarize-out" / "evidence.json").rename(
        tmp_path / "recovered.json"
    )

    assert _git_stamp(tmp_path)["dirty"] is True


@pytest.mark.parametrize(
    ("relative", "content"),
    [
        ("main.py", "changed_name = 1\n"),
        ("notes.md", "untracked user note\n"),
        ("GLOSSARY.md", "human-readable glossary\n"),
        ("graphify-out/graph.json", "{}\n"),
        (".glossarize/cache.json", "{}\n"),
        ("src/glossarize-out/user.txt", "not top-level tool output\n"),
    ],
)
def test_user_and_non_owned_paths_remain_dirty(tmp_path, relative, content):
    _init_repo(tmp_path)
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)

    assert _git_stamp(tmp_path)["dirty"] is True


def test_git_ignored_changes_follow_git_status_semantics(tmp_path):
    _init_repo(tmp_path, ignore="scratch.local\n")
    (tmp_path / "scratch.local").write_text("ignored local state\n")

    assert _git_stamp(tmp_path)["dirty"] is False


def test_non_git_repository_has_unverified_freshness(tmp_path):
    (tmp_path / "main.py").write_text("ordinary_name = 1\n")

    assert _git_stamp(tmp_path) == {"head": None, "dirty": None}
