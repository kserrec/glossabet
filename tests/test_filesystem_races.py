"""The check/use races the filesystem primitives are documented to resist.

``SECURITY.md`` ("Threat model and concurrency assumptions") supports a
hostile repository that is not mutated during a command and *detects* an
ordinary concurrent change at the sites listed there; an adversarial local
process racing path components is out of scope. These tests pin the
detections and fail-closed behaviours that are still claimed, by performing
the swap deterministically in the window between the check and the use.
"""

from __future__ import annotations

import os
import pathlib

import pytest

from glossabet.agent import managed_context
from glossabet.agent.managed_context import ContextSyncError, read_regular_target
from glossabet.corpus import cache as cache_module
from glossabet.corpus.cache import clear_cache
from glossabet.runtime import artifacts
from glossabet.runtime.artifacts import (
    READ_OVERSIZED,
    read_bounded_bytes,
    replace_file_atomic,
)

POSIX_ONLY = pytest.mark.skipif(
    os.name == "nt",
    reason="relies on POSIX rename/inode semantics; Windows is covered by the "
    "platform-neutral tests in this module and by the documented limits",
)


# --- bounded reads: the bound is judged from the bytes read, not a stat ----


def test_bounded_read_stays_bounded_when_the_file_grows_after_the_check(
    tmp_path, monkeypatch
):
    """A file replaced by a larger one between the regular-file check and
    the open is still refused by size: nothing beyond ``cap + 1`` bytes is
    read and nothing is decoded. (Ordinary concurrent change — detected.)"""
    path = tmp_path / "glossary.json"
    path.write_bytes(b"{}")
    cap = 16
    real_isfile = os.path.isfile

    def grow_then_answer(candidate):
        answer = real_isfile(candidate)
        if os.fspath(candidate) == str(path):
            path.write_bytes(b"[" + b"1," * cap + b"1]")
        return answer

    monkeypatch.setattr(artifacts.os.path, "isfile", grow_then_answer)

    read = read_bounded_bytes(path, cap)

    assert read.status == READ_OVERSIZED
    assert read.value is None and read.payload is None
    assert read.size is not None and read.size > cap  # best-effort hint


# --- managed host-context read: identity is compared across the open ------


def test_host_file_swapped_for_a_symlink_after_the_check_is_never_read(
    tmp_path, monkeypatch
):
    """Between ``lstat`` and ``open`` the host file becomes a symlink to a
    canary. On POSIX ``O_NOFOLLOW`` refuses the open; on Windows the open
    follows the link and the (device, inode) comparison between the
    pre-open ``lstat``, the descriptor, and the post-open ``lstat`` fails.
    Either way the canary's bytes are never returned."""
    target = tmp_path / "AGENTS.md"
    target.write_text("human text\n", encoding="utf-8")
    canary = tmp_path / "secret.md"
    canary.write_text("CANARY\n", encoding="utf-8")
    real_named_exactly = managed_context.entry_named_exactly

    def swap_then_confirm(root, name):
        answer = real_named_exactly(root, name)
        target.unlink()
        os.symlink(canary, target)
        return answer

    monkeypatch.setattr(managed_context, "entry_named_exactly", swap_then_confirm)

    with pytest.raises(ContextSyncError) as raised:
        read_regular_target(target)

    assert "CANARY" not in str(raised.value)
    assert canary.read_text(encoding="utf-8") == "CANARY\n"


@POSIX_ONLY
def test_host_file_replaced_by_another_regular_file_after_the_check_is_refused(
    tmp_path, monkeypatch
):
    """A different regular file (new inode) moved over the target between
    the check and the open fails the identity comparison, so stale bytes
    cannot be combined with a mode or size judged on the old file."""
    target = tmp_path / "AGENTS.md"
    target.write_text("human text\n", encoding="utf-8")
    replacement = tmp_path / "replacement.md"
    replacement.write_text("replacement text\n", encoding="utf-8")
    real_named_exactly = managed_context.entry_named_exactly

    def replace_then_confirm(root, name):
        answer = real_named_exactly(root, name)
        os.replace(replacement, target)
        return answer

    monkeypatch.setattr(managed_context, "entry_named_exactly", replace_then_confirm)

    with pytest.raises(ContextSyncError, match="changed while being inspected"):
        read_regular_target(target)


def test_host_file_read_is_bounded_even_if_it_grows_after_the_size_check(
    tmp_path, monkeypatch
):
    """The ``st_size`` check is advisory; the read itself takes at most one
    byte past the cap and refuses on that evidence."""
    target = tmp_path / "AGENTS.md"
    target.write_text("small\n", encoding="utf-8")
    limit = managed_context.MAX_HOST_FILE_BYTES
    real_named_exactly = managed_context.entry_named_exactly

    def grow_in_place_then_confirm(root, name):
        answer = real_named_exactly(root, name)
        # Same inode, more bytes: an append, not a replacement.
        with open(target, "ab") as handle:
            handle.write(b"x" * limit)
        return answer

    monkeypatch.setattr(managed_context, "entry_named_exactly", grow_in_place_then_confirm)

    with pytest.raises(ContextSyncError, match="larger than"):
        read_regular_target(target)


# --- atomic replace: the final path component is replaced, never followed --


@POSIX_ONLY
def test_atomic_replace_onto_a_symlink_replaces_the_link_not_its_target(tmp_path):
    """If the final component became a symlink after the caller's check,
    ``os.replace`` swaps the directory entry itself: the link is gone and
    its target is untouched. (A *parent directory* swapped for a symlink is
    the documented out-of-scope race.)"""
    canary = tmp_path / "canary.json"
    canary.write_bytes(b"CANARY")
    path = tmp_path / "evidence.json"
    os.symlink(canary, path)

    replace_file_atomic(path, b"{}\n")

    assert not path.is_symlink()
    assert path.read_bytes() == b"{}\n"
    assert canary.read_bytes() == b"CANARY"
    assert list(tmp_path.glob(".evidence.json.*.tmp")) == []


def test_atomic_replace_aborts_when_the_pre_replace_check_fails(tmp_path):
    """``before_replace`` runs after the temporary is durable and before the
    swap; raising there leaves the original bytes and no temporary."""
    path = tmp_path / "evidence.json"
    path.write_bytes(b"original")

    def refuse() -> None:
        raise RuntimeError("target changed")

    with pytest.raises(RuntimeError):
        replace_file_atomic(path, b"replacement", before_replace=refuse)

    assert path.read_bytes() == b"original"
    assert list(tmp_path.glob(".evidence.json.*.tmp")) == []


# --- cache clearing: unlink/rmdir never follow a link swapped in late ------


def _entry(root: pathlib.Path, letter: str) -> pathlib.Path:
    entry = root / (letter * 64)
    entry.mkdir(parents=True)
    (entry / cache_module.CACHE_FILE).write_text("{}", encoding="utf-8")
    return entry


def test_cache_file_swapped_for_a_symlink_after_the_check_loses_only_the_link(
    tmp_path, monkeypatch
):
    root = tmp_path / "cache"
    entry = _entry(root, "a")
    canary = tmp_path / "precious.json"
    canary.write_text("CANARY", encoding="utf-8")
    monkeypatch.setenv(cache_module.CACHE_ROOT_ENV, str(root))
    real_unlink = os.unlink

    def swap_then_unlink(path, *args, **kwargs):
        target = pathlib.Path(path)
        if target.name == cache_module.CACHE_FILE and not target.is_symlink():
            real_unlink(target)
            os.symlink(canary, target)
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(cache_module.os, "unlink", swap_then_unlink)

    report = clear_cache()

    assert canary.read_text(encoding="utf-8") == "CANARY"
    assert not (entry / cache_module.CACHE_FILE).exists()
    assert report["removed_entries"] == 1


def test_cache_entry_swapped_for_a_directory_symlink_is_not_followed(
    tmp_path, monkeypatch
):
    """The directory link itself may remain or be removed depending on the
    platform's ``rmdir`` behavior; its external target is never traversed,
    and the report must describe whichever safe outcome occurred."""
    root = tmp_path / "cache"
    entry = _entry(root, "b")
    canary_dir = tmp_path / "precious"
    canary_dir.mkdir()
    (canary_dir / "keep.txt").write_text("KEEP", encoding="utf-8")
    monkeypatch.setenv(cache_module.CACHE_ROOT_ENV, str(root))
    real_rmdir = pathlib.Path.rmdir

    def swap_then_rmdir(self):
        if self == entry and not self.is_symlink():
            (self / cache_module.CACHE_FILE).unlink(missing_ok=True)
            real_rmdir(self)
            os.symlink(canary_dir, self, target_is_directory=True)
        return real_rmdir(self)

    monkeypatch.setattr(pathlib.Path, "rmdir", swap_then_rmdir)

    report = clear_cache()

    assert (canary_dir / "keep.txt").read_text(encoding="utf-8") == "KEEP"
    assert canary_dir.is_dir()
    assert report["removed_entries"] == 1
    entry_remains = os.path.lexists(entry)
    assert report["unrecognized_left_in_place"] == (
        [entry.name] if entry_remains else []
    )
    assert report["root_removed"] is not entry_remains


# --- source reads: the walk-time size is the charged size -----------------


def test_walk_time_size_is_what_the_ledger_charges(tmp_path):
    """The corpus ledger charges the size seen at walk time and reclassifies
    exactly those bytes if the read later fails; it does not re-stat. This
    is the documented assumption-1 behaviour (a file that grows between
    walk and read is read whole — see SECURITY.md)."""
    from glossabet.corpus.walk_budget import CorpusBudget

    budget = CorpusBudget()
    budget.include_source("a.py", 10)
    budget.reclassify_unread("a.py", "unreadable", production=True)

    assert budget.source_files == 0 and budget.source_bytes == 0
    assert budget.skipped_source_files == 1 and budget.skipped_source_bytes == 10
    assert budget.skipped_sample[0]["reason"] == "unreadable"
