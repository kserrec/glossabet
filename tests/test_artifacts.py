"""Artifact writes are confined, atomic, and cleanup-safe."""

import os

import pytest

from glossabet.runtime.artifacts import ArtifactError, write_artifact


def test_atomic_write_replaces_complete_document_without_temp_files(tmp_path):
    path = write_artifact(tmp_path, "evidence.json", {"state": "first"})
    write_artifact(tmp_path, "evidence.json", {"state": "second"})

    assert path.read_text(encoding="utf-8") == '{\n  "state": "second"\n}\n'
    assert not list(path.parent.glob(".evidence.json.*.tmp"))


def test_failed_atomic_commit_preserves_existing_document(
    tmp_path, monkeypatch
):
    path = write_artifact(tmp_path, "evidence.json", {"state": "existing"})

    def fail_replace(source, destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr("glossabet.runtime.artifacts.os.replace", fail_replace)
    with pytest.raises(ArtifactError, match="simulated replace failure"):
        write_artifact(tmp_path, "evidence.json", {"state": "new"})

    assert path.read_text(encoding="utf-8") == '{\n  "state": "existing"\n}\n'
    assert not list(path.parent.glob(".evidence.json.*.tmp"))


# --- the one bounded-read discipline --------------------------------------


def test_read_bounded_json_outcomes_are_named_and_bound_is_judged_from_bytes(
    tmp_path, monkeypatch
):
    from glossabet.runtime.artifacts import (
        READ_ABSENT,
        READ_MALFORMED,
        READ_OK,
        READ_OVERSIZED,
        READ_UNREADABLE,
        read_bounded_bytes,
        read_bounded_json,
    )
    exact = tmp_path / "exact.json"
    exact.write_bytes(b'{"k":1}')  # 7 bytes
    assert read_bounded_json(exact, 7).status == READ_OK
    assert read_bounded_json(exact, 7).value == {"k": 1}
    over = read_bounded_json(exact, 6)
    assert over.status == READ_OVERSIZED and over.size == 7 and over.value is None

    assert read_bounded_json(tmp_path / "missing.json", 10).status == READ_ABSENT
    assert read_bounded_json(tmp_path, 10).status == READ_ABSENT  # a directory

    recursive = tmp_path / "recursive.json"
    recursive.write_bytes(b"[]")

    def fail_recursive_parse(_document):
        raise RecursionError("simulated parser recursion limit")

    with monkeypatch.context() as recursion_patch:
        recursion_patch.setattr(
            "glossabet.runtime.artifacts.json.loads", fail_recursive_parse
        )
        malformed = read_bounded_json(recursive, 10 ** 9)
    assert malformed.status == READ_MALFORMED
    assert malformed.payload == b"[]"
    assert malformed.error == "simulated parser recursion limit"

    bad = tmp_path / "bad.json"
    bad.write_bytes(b"\xff\xfe{}")
    assert read_bounded_json(bad, 100).status == READ_MALFORMED  # UTF-8 only, no BOM sniffing

    raw = read_bounded_bytes(exact, 100)
    assert raw.status == READ_OK and raw.payload == b'{"k":1}' and raw.value is None

    # The bound is enforced by how much is *read*, not by trusting a size
    # probe: an over-cap file costs at most cap + 1 bytes of memory, so a
    # repository-controlled multi-gigabyte glossary or config cannot make
    # the engine inflate it before refusing.
    class CountingReader:
        def __init__(self, handle):
            self.handle, self.requested = handle, []

        def read(self, size=-1):
            self.requested.append(size)
            return self.handle.read(size)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return self.handle.__exit__(*exc)

    import builtins

    opened = []
    real_open = builtins.open

    def spying_open(path_, mode="r", *args, **kwargs):
        handle = real_open(path_, mode, *args, **kwargs)
        if "b" in mode and str(path_) == str(exact):
            reader = CountingReader(handle)
            opened.append(reader)
            return reader
        return handle

    monkeypatch_open = pytest.MonkeyPatch()
    monkeypatch_open.setattr(builtins, "open", spying_open)
    try:
        assert read_bounded_bytes(exact, 3).status == READ_OVERSIZED
    finally:
        monkeypatch_open.undo()
    assert opened and opened[-1].requested == [4]  # cap + 1, never the whole file

    if hasattr(os, "geteuid") and os.geteuid() != 0:
        locked = tmp_path / "locked.json"
        locked.write_text("{}")
        locked.chmod(0)
        try:
            assert read_bounded_json(locked, 100).status == READ_UNREADABLE
        finally:
            locked.chmod(0o600)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_written_artifacts_get_the_modes_a_plain_open_would(tmp_path):
    """Artifacts are written through a private temp file (mkstemp: 0o600),
    then given 0o666 minus the caller's umask like any file the user's own
    tools create — so another uid on a shared checkout or a later CI step
    can read glossary.json/evidence.json. Two umasks, both must apply."""
    import stat

    original = os.umask(0o022)
    try:
        for umask, expected in ((0o022, 0o644), (0o002, 0o664), (0o077, 0o600)):
            os.umask(umask)
            path = write_artifact(tmp_path, f"artifact-{umask:o}.json", {"k": 1})
            assert stat.S_IMODE(path.stat().st_mode) == expected, oct(umask)
    finally:
        os.umask(original)


def test_bounded_read_memory_follows_content_not_cap(tmp_path):
    """A small file under a large cap must not allocate the cap: the reader
    takes bounded chunks, so peak heap tracks the bytes actually read."""
    import tracemalloc

    from glossabet.runtime.artifacts import (
        READ_CHUNK_BYTES,
        READ_FIRST_CHUNK_BYTES,
        READ_OK,
        READ_OVERSIZED,
        read_bounded_bytes,
    )

    small = tmp_path / "small.json"
    small.write_bytes(b"{}")
    cap = 64_000_000
    tracemalloc.start()
    read = read_bounded_bytes(small, cap)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert read.status == READ_OK and read.payload == b"{}"
    assert peak < 4 * READ_FIRST_CHUNK_BYTES

    # The bound is still judged from bytes read across chunk boundaries.
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (READ_CHUNK_BYTES + 5))
    assert read_bounded_bytes(big, READ_CHUNK_BYTES + 5).payload == b"x" * (READ_CHUNK_BYTES + 5)
    assert read_bounded_bytes(big, READ_CHUNK_BYTES + 4).status == READ_OVERSIZED
