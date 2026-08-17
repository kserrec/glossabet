"""Artifact writes are confined, atomic, and cleanup-safe."""

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
