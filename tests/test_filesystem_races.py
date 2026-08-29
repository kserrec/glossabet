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
import shutil
from types import SimpleNamespace

import pytest

from glossabet.agent import managed_context
from glossabet.agent.managed_context import ContextSyncError, read_regular_target
from glossabet.corpus import cache as cache_module
from glossabet.corpus import path_policy
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


# --- exact entry names: lookup and listing must describe one state --------


@pytest.mark.parametrize("with_casefold_sibling", [False, True])
def test_host_file_vanishing_during_exact_name_confirmation_is_uncertain(
    tmp_path,
    monkeypatch,
    with_casefold_sibling,
    case_distinct_names_supported,
):
    """A successful path lookup followed by a listing with no target is a
    concurrent disappearance, even when a casefold-equivalent sibling remains."""
    if with_casefold_sibling and not case_distinct_names_supported:
        pytest.skip("requires two case-distinct entries in one directory")

    target = tmp_path / "AGENTS.md"
    target.write_text("human text\n", encoding="utf-8")
    sibling = tmp_path / "agents.md"
    if with_casefold_sibling:
        sibling.write_text("different file\n", encoding="utf-8")
    real_scandir = os.scandir

    def vanish_then_scan(directory):
        if os.fspath(directory) == os.fspath(tmp_path) and target.exists():
            target.unlink()
        return real_scandir(directory)

    monkeypatch.setattr(path_policy.os, "scandir", vanish_then_scan)

    with pytest.raises(ContextSyncError) as raised:
        read_regular_target(target)

    assert "exact name could not be confirmed" in str(raised.value)
    assert "different spelling" not in str(raised.value)
    assert not target.exists()
    assert sibling.exists() is with_casefold_sibling


def test_host_file_vanishing_before_exact_name_lookup_is_a_detected_change(
    tmp_path, monkeypatch
):
    """A file seen by the managed caller but absent at the helper's first
    observation changed concurrently; it is not a differently spelled file."""
    target = tmp_path / "AGENTS.md"
    target.write_text("human text\n", encoding="utf-8")
    real_entry_named_exactly = managed_context.entry_named_exactly

    def vanish_before_lookup(root, name):
        if target.exists():
            target.unlink()
        return real_entry_named_exactly(root, name)

    monkeypatch.setattr(
        managed_context,
        "entry_named_exactly",
        vanish_before_lookup,
    )

    with pytest.raises(ContextSyncError) as raised:
        read_regular_target(target)

    assert "changed while being inspected" in str(raised.value)
    assert "different spelling" not in str(raised.value)
    assert not target.exists()


@POSIX_ONLY
def test_host_file_restored_after_missing_exact_name_lookup_is_a_detected_change(
    tmp_path, monkeypatch
):
    """Restoring the same inode after the helper observed absence does not
    turn that disagreement into proof of a stable alternate spelling."""
    target = tmp_path / "AGENTS.md"
    target.write_text("human text\n", encoding="utf-8")
    held_link = tmp_path / ".held-agents"
    os.link(target, held_link)
    real_entry_named_exactly = managed_context.entry_named_exactly
    raced_once = False

    def vanish_then_restore(root, name):
        nonlocal raced_once
        if not raced_once:
            raced_once = True
            target.unlink()
            answer = real_entry_named_exactly(root, name)
            os.link(held_link, target)
            return answer
        return real_entry_named_exactly(root, name)

    monkeypatch.setattr(
        managed_context,
        "entry_named_exactly",
        vanish_then_restore,
    )

    with pytest.raises(ContextSyncError) as raised:
        read_regular_target(target)

    assert "changed while being inspected" in str(raised.value)
    assert "different spelling" not in str(raised.value)
    assert target.samefile(held_link)


def test_stable_different_spelling_remains_a_definite_mismatch(
    tmp_path, monkeypatch
):
    """Emulate a case-insensitive lookup whose directory entry preserves a
    different spelling; this is a known mismatch, not lookup uncertainty."""
    requested = tmp_path / "AGENTS.md"
    actual = tmp_path / "agents.md"
    actual.write_text("human text\n", encoding="utf-8")
    real_lstat = os.lstat

    def case_insensitive_lstat(path, *args, **kwargs):
        if os.fspath(path) == os.fspath(requested):
            return real_lstat(actual, *args, **kwargs)
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(path_policy.os, "lstat", case_insensitive_lstat)

    assert path_policy.entry_named_exactly(tmp_path, requested.name) is False


def test_different_spelling_without_file_identity_is_uncertain(
    tmp_path, monkeypatch
):
    """A listed alternate spelling cannot be bound to the requested lookup
    when the filesystem reports zero instead of portable file identity."""
    requested = tmp_path / "AGENTS.md"
    actual = tmp_path / "agents.md"
    actual.write_text("human text\n", encoding="utf-8")
    real_lstat = os.lstat

    def case_insensitive_lstat_without_identity(path, *args, **kwargs):
        looked_up = actual if os.fspath(path) == os.fspath(requested) else path
        info = real_lstat(looked_up, *args, **kwargs)
        return SimpleNamespace(
            st_mode=info.st_mode,
            st_dev=info.st_dev,
            st_ino=0,
        )

    monkeypatch.setattr(
        path_policy.os,
        "lstat",
        case_insensitive_lstat_without_identity,
    )

    assert path_policy.entry_named_exactly(tmp_path, requested.name) is None


@POSIX_ONLY
def test_stale_exact_directory_entry_after_rename_is_uncertain(
    tmp_path, monkeypatch
):
    """A DirEntry keeps the spelling it had when enumerated. If that entry is
    renamed before being yielded, its stale name is not current exact proof."""
    requested = tmp_path / "AGENTS.md"
    alternate = tmp_path / "agents.md"
    requested.write_text("human text\n", encoding="utf-8")
    real_scandir = os.scandir

    class RenameBeforeYield:
        def __enter__(self):
            self.entries = real_scandir(tmp_path)
            iterator = self.entries.__enter__()
            stale = next(iterator)
            requested.rename(alternate)
            return iter([stale])

        def __exit__(self, exc_type, exc_value, traceback):
            return self.entries.__exit__(exc_type, exc_value, traceback)

    monkeypatch.setattr(path_policy.os, "scandir", lambda _root: RenameBeforeYield())

    assert path_policy.entry_named_exactly(tmp_path, requested.name) is None
    names = set(os.listdir(tmp_path))
    assert requested.name not in names
    assert alternate.name in names


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


@pytest.mark.parametrize("replace_target", [False, True])
def test_host_file_identity_must_be_available_across_the_open(
    tmp_path, monkeypatch, replace_target
):
    """A zero inode means identity is unavailable, not that every observed
    file is the same file. Both a stable read and a replacement fail closed."""
    target = tmp_path / "AGENTS.md"
    target.write_text("human text\n", encoding="utf-8")
    replacement = tmp_path / "replacement.md"
    replacement.write_text("replacement text\n", encoding="utf-8")
    real_path_lstat = pathlib.Path.lstat
    real_fstat = os.fstat
    real_named_exactly = managed_context.entry_named_exactly

    def without_identity(info):
        return SimpleNamespace(
            st_mode=info.st_mode,
            st_size=info.st_size,
            st_dev=info.st_dev,
            st_ino=0,
        )

    def lstat_without_identity(path):
        return without_identity(real_path_lstat(path))

    def fstat_without_identity(descriptor):
        return without_identity(real_fstat(descriptor))

    def optionally_replace_then_confirm(root, name):
        answer = real_named_exactly(root, name)
        if replace_target:
            os.replace(replacement, target)
        return answer

    monkeypatch.setattr(pathlib.Path, "lstat", lstat_without_identity)
    monkeypatch.setattr(managed_context.os, "fstat", fstat_without_identity)
    monkeypatch.setattr(
        managed_context,
        "entry_named_exactly",
        optionally_replace_then_confirm,
    )

    with pytest.raises(ContextSyncError, match="filesystem identity is unavailable"):
        read_regular_target(target)


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
    real_unlink = cache_module.os.unlink
    swapped = False

    def swap_then_unlink(path, *args, **kwargs):
        nonlocal swapped
        target = pathlib.Path(path)
        if not swapped and target.name == cache_module.CACHE_FILE:
            swapped = True
            real_unlink(path, *args, **kwargs)
            os.symlink(canary, path)
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(cache_module.os, "unlink", swap_then_unlink)

    report = clear_cache()

    assert canary.read_text(encoding="utf-8") == "CANARY"
    assert swapped is True
    assert not (entry / cache_module.CACHE_FILE).exists()
    assert report["removed_entries"] == 1


def test_cache_capture_uses_portable_path_identity(tmp_path, monkeypatch):
    """Windows may expose different identity fields through directory
    enumeration and a path stat for the same unchanged directory."""
    root = tmp_path / "cache"
    _entry(root, "f")
    monkeypatch.setenv(cache_module.CACHE_ROOT_ENV, str(root))
    real_scandir = cache_module.os.scandir

    class DivergentEnumerationEntry:
        def __init__(self, entry):
            self._entry = entry
            self.name = entry.name
            self.path = entry.path

        def stat(self, *, follow_symlinks=True):
            info = self._entry.stat(follow_symlinks=follow_symlinks)
            return SimpleNamespace(
                st_mode=info.st_mode,
                st_dev=info.st_dev,
                st_ino=info.st_ino + 1,
            )

    def divergent_root_scandir(path):
        if pathlib.Path(path) == root:
            with real_scandir(path) as entries:
                return [DivergentEnumerationEntry(entry) for entry in entries]
        return real_scandir(path)

    monkeypatch.setattr(cache_module.os, "scandir", divergent_root_scandir)

    report = clear_cache()

    assert report["removed_entries"] == 1
    assert report["root_removed"] is True
    assert not root.exists()


def test_cache_entry_replaced_by_a_real_directory_is_preserved(
    tmp_path, monkeypatch
):
    root = tmp_path / "cache"
    entry = _entry(root, "b")
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    (replacement / "KEEP.txt").write_text("KEEP", encoding="utf-8")
    saved_original = tmp_path / "saved-original"
    monkeypatch.setenv(cache_module.CACHE_ROOT_ENV, str(root))
    real_rename = cache_module.os.rename
    swapped = False

    def swap_then_capture(source, destination):
        nonlocal swapped
        source_path = pathlib.Path(source)
        if not swapped and source_path.name == entry.name:
            swapped = True
            real_rename(source, saved_original)
            real_rename(replacement, source)
        return real_rename(source, destination)

    monkeypatch.setattr(cache_module.os, "rename", swap_then_capture)

    report = clear_cache()

    assert swapped is True
    assert (entry / "KEEP.txt").read_text(encoding="utf-8") == "KEEP"
    assert report["removed_entries"] == 0
    assert report["unrecognized_left_in_place"] == [entry.name]
    assert report["root_refusal"] == "a cache entry changed while being captured"


def test_cache_entry_swapped_before_listing_is_not_followed(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    entry = _entry(root, "c")
    canary_dir = tmp_path / "precious"
    canary_dir.mkdir()
    canary = canary_dir / cache_module.CACHE_FILE
    canary.write_text("KEEP", encoding="utf-8")
    monkeypatch.setenv(cache_module.CACHE_ROOT_ENV, str(root))
    real_scandir = cache_module.os.scandir
    swapped = False

    def swap_then_list(path):
        nonlocal swapped
        if not swapped and not isinstance(path, int) and pathlib.Path(path) == entry:
            swapped = True
            shutil.rmtree(entry)
            os.symlink(canary_dir, entry, target_is_directory=True)
        return real_scandir(path)

    monkeypatch.setattr(cache_module.os, "scandir", swap_then_list)

    report = clear_cache()

    assert swapped is True
    assert canary.read_text(encoding="utf-8") == "KEEP"
    assert report["removed_entries"] == 0
    assert report["root_refusal"] == "a cache entry changed while being captured"


def test_cache_root_swapped_before_listing_is_refused(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    _entry(root, "d")
    canary_root = tmp_path / "precious"
    canary_entry = canary_root / ("d" * 64)
    canary_entry.mkdir(parents=True)
    canary = canary_entry / cache_module.CACHE_FILE
    canary.write_text("KEEP", encoding="utf-8")
    monkeypatch.setenv(cache_module.CACHE_ROOT_ENV, str(root))
    real_scandir = cache_module.os.scandir
    swapped = False

    def swap_then_list(path):
        nonlocal swapped
        if not swapped and not isinstance(path, int) and pathlib.Path(path) == root:
            swapped = True
            shutil.rmtree(root)
            os.symlink(canary_root, root, target_is_directory=True)
        return real_scandir(path)

    monkeypatch.setattr(cache_module.os, "scandir", swap_then_list)

    report = clear_cache()

    assert swapped is True
    assert canary.read_text(encoding="utf-8") == "KEEP"
    assert report["root_refusal"] == "the cache path changed while being captured"
    assert report["removed_entries"] == 0


def test_cache_root_replaced_by_a_real_directory_is_preserved(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "cache"
    _entry(root, "e")
    replacement = tmp_path / "replacement-root"
    replacement.mkdir()
    canary = replacement / "KEEP.txt"
    canary.write_text("KEEP", encoding="utf-8")
    saved_original = tmp_path / "saved-root"
    monkeypatch.setenv(cache_module.CACHE_ROOT_ENV, str(root))
    real_rename = cache_module.os.rename
    swapped = False

    def swap_then_capture(source, destination):
        nonlocal swapped
        if not swapped and pathlib.Path(source) == root:
            swapped = True
            real_rename(root, saved_original)
            real_rename(replacement, root)
        return real_rename(source, destination)

    monkeypatch.setattr(cache_module.os, "rename", swap_then_capture)

    report = clear_cache()

    assert swapped is True
    assert (root / "KEEP.txt").read_text(encoding="utf-8") == "KEEP"
    assert report["removed_entries"] == 0
    assert report["root_refusal"] == "the cache path changed while being captured"


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
