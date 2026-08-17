"""Artifact writes are confined, atomic, and cleanup-safe."""

import os
import pytest

from glossabet.artifacts import ArtifactError, write_artifact


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

    monkeypatch.setattr("glossabet.artifacts.os.replace", fail_replace)
    with pytest.raises(ArtifactError, match="simulated replace failure"):
        write_artifact(tmp_path, "evidence.json", {"state": "new"})

    assert path.read_text(encoding="utf-8") == '{\n  "state": "existing"\n}\n'
    assert not list(path.parent.glob(".evidence.json.*.tmp"))


# --- the one bounded read discipline (Phase 35.2) ---------------------------


def test_read_bounded_json_outcomes_are_named_and_bound_is_judged_from_bytes(tmp_path):
    from glossabet.artifacts import (
        READ_ABSENT, READ_MALFORMED, READ_OK, READ_OVERSIZED, READ_UNREADABLE,
        read_bounded_bytes, read_bounded_json,
    )
    exact = tmp_path / "exact.json"
    exact.write_bytes(b'{"k":1}')  # 7 bytes
    assert read_bounded_json(exact, 7).status == READ_OK
    assert read_bounded_json(exact, 7).value == {"k": 1}
    over = read_bounded_json(exact, 6)
    assert over.status == READ_OVERSIZED and over.size == 7 and over.value is None

    assert read_bounded_json(tmp_path / "missing.json", 10).status == READ_ABSENT
    assert read_bounded_json(tmp_path, 10).status == READ_ABSENT  # a directory

    deep = tmp_path / "deep.json"
    depth = 60_000
    deep.write_bytes(b"[" * depth + b"]" * depth)
    assert read_bounded_json(deep, 10 ** 9).status == READ_MALFORMED  # RecursionError caught

    bad = tmp_path / "bad.json"
    bad.write_bytes(b"\xff\xfe{}")
    assert read_bounded_json(bad, 100).status == READ_MALFORMED  # UTF-8 only, no BOM sniffing

    raw = read_bounded_bytes(exact, 100)
    assert raw.status == READ_OK and raw.payload == b'{"k":1}' and raw.value is None

    if hasattr(os, "geteuid") and os.geteuid() != 0:
        locked = tmp_path / "locked.json"
        locked.write_text("{}")
        locked.chmod(0)
        try:
            assert read_bounded_json(locked, 100).status == READ_UNREADABLE
        finally:
            locked.chmod(0o600)
