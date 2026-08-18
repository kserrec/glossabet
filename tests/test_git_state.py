"""glossabet.git_state: the hardened repository stamp and its freshness
pathspec — hides only Glossabet-owned output, never executes a hostile
.git/config, and never claims clean state it cannot prove."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from glossabet.cli import main
from glossabet.runtime.git_state import repository_git_stamp


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
    _git(root, "config", "user.name", "Glossabet Test")

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
        (tmp_path / "glossabet-out" / "evidence.json").read_text(encoding="utf-8")
    )
    assert _is_fresh(evidence["repository"]["git"], repository_git_stamp(tmp_path))
    assert not (tmp_path / ".gitignore").exists()


def test_first_scan_of_nested_repository_scope_is_immediately_fresh(tmp_path):
    relative = "packages/service/main.py"
    _init_repo(tmp_path, extra_tracked={relative: "service_name = 1\n"})
    service = tmp_path / "packages" / "service"

    assert main(["scan", str(service)]) == 0

    evidence = json.loads(
        (service / "glossabet-out" / "evidence.json").read_text(encoding="utf-8")
    )
    assert _is_fresh(evidence["repository"]["git"], repository_git_stamp(service))


def test_user_change_after_scan_makes_evidence_stale(tmp_path):
    _init_repo(tmp_path)
    assert main(["scan", str(tmp_path)]) == 0
    stamped = json.loads(
        (tmp_path / "glossabet-out" / "evidence.json").read_text(encoding="utf-8")
    )["repository"]["git"]

    (tmp_path / "main.py").write_text("changed_after_scan = 1\n")

    assert not _is_fresh(stamped, repository_git_stamp(tmp_path))


def test_tracked_and_untracked_generated_output_do_not_dirty_freshness(tmp_path):
    _init_repo(
        tmp_path,
        extra_tracked={"glossabet-out/evidence.json": "{}\n"},
    )
    output = tmp_path / "glossabet-out"
    (output / "evidence.json").write_text('{"refreshed": true}\n')
    (output / "drift.json").write_text("{}\n")
    (output / "validation.json").write_text("{}\n")

    assert repository_git_stamp(tmp_path)["dirty"] is False


def test_move_into_generated_output_keeps_source_deletion_visible(tmp_path):
    _init_repo(tmp_path)
    output = tmp_path / "glossabet-out"
    output.mkdir()
    (tmp_path / "main.py").rename(output / "main.py")

    assert repository_git_stamp(tmp_path)["dirty"] is True


def test_move_out_of_generated_output_keeps_destination_visible(tmp_path):
    _init_repo(
        tmp_path,
        extra_tracked={"glossabet-out/evidence.json": "{}\n"},
    )
    (tmp_path / "glossabet-out" / "evidence.json").rename(
        tmp_path / "recovered.json"
    )

    assert repository_git_stamp(tmp_path)["dirty"] is True


@pytest.mark.parametrize(
    ("relative", "content"),
    [
        ("main.py", "changed_name = 1\n"),
        ("notes.md", "untracked user note\n"),
        ("GLOSSARY.md", "human-readable glossary\n"),
        ("graphify-out/graph.json", "{}\n"),
        (".glossabet/cache.json", "{}\n"),
        ("src/glossabet-out/user.txt", "not top-level tool output\n"),
    ],
)
def test_user_and_non_owned_paths_remain_dirty(tmp_path, relative, content):
    _init_repo(tmp_path)
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)

    assert repository_git_stamp(tmp_path)["dirty"] is True


def test_git_ignored_changes_follow_git_status_semantics(tmp_path):
    _init_repo(tmp_path, ignore="scratch.local\n")
    (tmp_path / "scratch.local").write_text("ignored local state\n")

    assert repository_git_stamp(tmp_path)["dirty"] is False


def test_non_git_repository_has_unverified_freshness(tmp_path):
    (tmp_path / "main.py").write_text("ordinary_name = 1\n")

    assert repository_git_stamp(tmp_path) == {"head": None, "dirty": None}


def test_hostile_git_config_does_not_execute_code(tmp_path, monkeypatch):
    # A repo whose .git/config sets core.fsmonitor must not run that command
    # when glossabet reads the git stamp (core.fsmonitor fires on git status).
    import subprocess as sp
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_SYSTEM": "/dev/null"}
    sp.run(["git", "init", "-q"], cwd=repo, env=env, check=True)
    sp.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "main.py").write_text("x = 1\n")
    sp.run(["git", "add", "main.py"], cwd=repo, check=True)
    sp.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm", "i"],
           cwd=repo, check=True)
    marker = tmp_path / "PWNED"
    sp.run(["git", "config", "core.fsmonitor", f"touch {marker}; false"],
           cwd=repo, check=True)
    stamp = repository_git_stamp(repo)
    assert stamp["head"] is not None  # git still works
    assert not marker.exists(), "core.fsmonitor command was executed"


def test_hostile_git_filter_driver_does_not_execute_code(tmp_path):
    # A repo whose .git/config defines a content filter driver plus a
    # .gitattributes binding it must not run that command when glossabet
    # reads the git stamp (git status runs clean filters during content
    # conversion of a racily-modified tracked file).
    import subprocess as sp
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_SYSTEM": "/dev/null"}
    sp.run(["git", "init", "-q"], cwd=repo, env=env, check=True)
    sp.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "main.py").write_text("x = 1\n")
    (repo / ".gitattributes").write_text("* filter=evil\n")
    sp.run(["git", "add", "-A"], cwd=repo, check=True)
    sp.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm", "i"],
           cwd=repo, check=True)
    marker = tmp_path / "PWNED"
    sp.run(["git", "config", "filter.evil.clean",
            f"sh -c 'touch {marker}; cat'"], cwd=repo, check=True)
    os.utime(repo / "main.py", (0, 0))  # racy-old forces the re-hash path

    stamp = repository_git_stamp(repo)
    assert stamp["head"] is not None  # git still works
    assert not marker.exists(), "filter driver command was executed"


def test_hostile_git_filter_driver_via_config_include_does_not_execute(tmp_path):
    # The filter driver is defined in a file pulled in by `include.path`, not
    # directly in .git/config. `git config --local` never resolves includes, so
    # an enumeration that used --local missed it while `git status` (which does
    # resolve includes) still ran it — an RCE bypass. The override enumeration
    # must follow includes exactly as git does.
    import subprocess as sp
    from glossabet.runtime.git_state import _filter_driver_overrides, _resolve_git
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_SYSTEM": "/dev/null"}
    sp.run(["git", "init", "-q"], cwd=repo, env=env, check=True)
    sp.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    marker = tmp_path / "PWNED_INCLUDE"
    # Commit BEFORE the filter driver exists, so `git add` itself never runs
    # the attacker command (which assumes a POSIX `sh`/`touch` and would fail
    # the staging on Windows). Only our freshness probe should encounter it.
    (repo / "main.py").write_text("x = 1\n")
    (repo / ".gitattributes").write_text("* filter=evil\n")
    sp.run(["git", "add", "-A"], cwd=repo, check=True)
    sp.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm", "i"],
           cwd=repo, check=True)
    # Now define the driver via include.path (not directly in .git/config).
    include_file = repo / ".git" / "evil-include"
    # Forward-slash the marker: it is embedded in a git-config value inside
    # the include file, and git's config parser treats backslash as an escape,
    # so a Windows-native path here would make git reject the whole include.
    marker_posix = marker.as_posix()
    include_file.write_text(
        "[filter \"evil\"]\n"
        f"\tclean = sh -c 'touch {marker_posix}; cat'\n"
        f"\tsmudge = sh -c 'touch {marker_posix}; cat'\n"
    )
    # Forward-slash path: git config treats backslash as an escape, so a
    # Windows-native path here would not resolve the include.
    sp.run(["git", "config", "include.path", include_file.as_posix()],
           cwd=repo, check=True)
    os.utime(repo / "main.py", (0, 0))  # racy-old forces the re-hash path

    # The include-defined driver must be enumerated for clearing...
    overrides = _filter_driver_overrides(_resolve_git(), repo)
    assert "-c" in overrides and any(
        o.startswith("filter.evil.") for o in overrides
    ), overrides
    # ...and never executed.
    stamp = repository_git_stamp(repo)
    assert stamp["head"] is not None
    assert not marker.exists(), "include-defined filter driver was executed"


def test_stamp_ignores_a_callers_git_dir_and_work_tree(tmp_path, monkeypatch):
    """``-C root`` names the stamped repository; an exported GIT_DIR (some CI
    wrappers and hook scripts set one) must not redirect the stamp to another
    repository or, when relative, to nowhere."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    _init_repo(a)
    _init_repo(b)
    (b / "main.py").write_text("different = 2\n")
    _git(b, "commit", "-qam", "b diverges")
    head_a = repository_git_stamp(a)["head"]
    head_b = repository_git_stamp(b)["head"]
    assert head_a and head_b and head_a != head_b

    monkeypatch.setenv("GIT_DIR", str(a / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(a))
    assert repository_git_stamp(b) == {"head": head_b, "dirty": False}
    monkeypatch.setenv("GIT_DIR", ".git")  # relative, as a hook at a's top sees
    (a / "sub").mkdir()
    (a / "sub" / "x.py").write_text("y = 1\n")
    assert repository_git_stamp(a / "sub")["head"] == head_a
