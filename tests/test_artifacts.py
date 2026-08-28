"""Artifact writes are confined, atomic, and cleanup-safe."""

import builtins
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


class _RecordingReader:
    def __init__(self, handle):
        self.handle = handle
        self.requested_sizes = []
        self.returned_sizes = []

    def read(self, size=-1):
        payload = self.handle.read(size)
        self.requested_sizes.append(size)
        self.returned_sizes.append(len(payload))
        return payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self.handle.__exit__(*exc)


def _record_bounded_read(monkeypatch, path, cap):
    from glossabet.runtime.artifacts import read_bounded_bytes

    readers = []
    real_open = builtins.open

    def recording_open(candidate, mode="r", *args, **kwargs):
        handle = real_open(candidate, mode, *args, **kwargs)
        if "b" in mode and os.fspath(candidate) == os.fspath(path):
            reader = _RecordingReader(handle)
            readers.append(reader)
            return reader
        return handle

    with monkeypatch.context() as recording:
        recording.setattr(builtins, "open", recording_open)
        result = read_bounded_bytes(path, cap)
    assert len(readers) == 1
    return result, readers[0]


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
    bounded, reader = _record_bounded_read(monkeypatch, exact, 3)
    assert bounded.status == READ_OVERSIZED
    assert reader.requested_sizes == [4]
    assert reader.returned_sizes == [4]

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


def test_bounded_read_requests_follow_content_and_bound(tmp_path, monkeypatch):
    """Requested chunks stay bounded independently of the configured cap,
    while returned bytes decide exact-boundary and oversized outcomes."""
    from glossabet.runtime.artifacts import (
        READ_CHUNK_BYTES,
        READ_FIRST_CHUNK_BYTES,
        READ_OK,
        READ_OVERSIZED,
    )

    small = tmp_path / "small.json"
    small.write_bytes(b"{}")
    cap = 64_000_000
    read, small_reader = _record_bounded_read(monkeypatch, small, cap)
    assert read.status == READ_OK and read.payload == b"{}"
    assert small_reader.requested_sizes[0] == READ_FIRST_CHUNK_BYTES
    assert all(
        0 < size <= READ_CHUNK_BYTES
        for size in small_reader.requested_sizes
    )
    assert max(small_reader.requested_sizes) < cap + 1
    assert sum(small_reader.returned_sizes) == len(b"{}")
    assert small_reader.returned_sizes[-1] == 0

    # The bound is still judged from bytes read across chunk boundaries.
    big = tmp_path / "big.bin"
    payload = b"x" * (READ_CHUNK_BYTES + 5)
    big.write_bytes(payload)

    exact, exact_reader = _record_bounded_read(monkeypatch, big, len(payload))
    assert exact.status == READ_OK and exact.payload == payload
    assert all(
        0 < size <= READ_CHUNK_BYTES
        for size in exact_reader.requested_sizes
    )
    assert sum(exact_reader.returned_sizes) == len(payload)
    assert exact_reader.returned_sizes[-1] == 0

    over_cap = len(payload) - 1
    oversized, oversized_reader = _record_bounded_read(
        monkeypatch, big, over_cap
    )
    assert oversized.status == READ_OVERSIZED
    assert oversized.payload is None and oversized.size == len(payload)
    assert all(
        0 < size <= READ_CHUNK_BYTES
        for size in oversized_reader.requested_sizes
    )
    assert sum(oversized_reader.returned_sizes) == over_cap + 1
    assert oversized_reader.returned_sizes[-1] > 0
