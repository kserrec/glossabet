"""Incremental cache: warm results must be byte-identical to cold scans,
only changed files may be re-extracted, and every doubt (version change,
corruption) must read as a miss, never as stale data."""

import json
import os

from glossarize import __version__
from glossarize.cache import cache_path, load_cache
from glossarize.evidence import build_evidence


def make_repo(tmp_path):
    (tmp_path / "a.py").write_text("payment_service = 1\ncharge_total = 2\n")
    (tmp_path / "b.py").write_text("billing_worker = 1\n")
    (tmp_path / "README.md").write_text("The billing subsystem charges.\n")
    return tmp_path


def as_bytes(evidence):
    return json.dumps(evidence, sort_keys=True)


def test_warm_scan_is_byte_identical_after_change(tmp_path):
    root = make_repo(tmp_path)
    build_evidence(root, cache=True)  # populate
    (root / "b.py").write_text("billing_worker = 1\nrefund_worker = 2\n")
    warm = build_evidence(root, cache=True)
    cold = build_evidence(root, cache=False)
    assert as_bytes(warm) == as_bytes(cold)


def test_unchanged_files_are_reused_not_reextracted(tmp_path):
    root = make_repo(tmp_path)
    stats: dict = {}
    build_evidence(root, cache=True, stats=stats)
    assert stats == {"reused": 0, "extracted": 3}
    (root / "b.py").write_text("billing_worker = 1\nrefund_worker = 2\n")
    stats = {}
    build_evidence(root, cache=True, stats=stats)
    assert stats == {"reused": 2, "extracted": 1}


def test_fully_warm_scan_extracts_nothing(tmp_path):
    root = make_repo(tmp_path)
    build_evidence(root, cache=True)
    stats: dict = {}
    warm = build_evidence(root, cache=True, stats=stats)
    assert stats == {"reused": 3, "extracted": 0}
    assert as_bytes(warm) == as_bytes(build_evidence(root, cache=False))


def test_generator_version_change_invalidates_everything(tmp_path):
    root = make_repo(tmp_path)
    build_evidence(root, cache=True)
    cached = json.loads(cache_path(root).read_text())
    cached["generator_version"] = "0.0.0-older"
    cache_path(root).write_text(json.dumps(cached))
    assert load_cache(root) is None  # a version mismatch is a full miss
    stats: dict = {}
    build_evidence(root, cache=True, stats=stats)
    assert stats["extracted"] == 3 and stats["reused"] == 0


def test_ascii_tokenizer_cache_version_is_invalidated(tmp_path):
    root = make_repo(tmp_path)
    build_evidence(root, cache=True)
    cached = json.loads(cache_path(root).read_text())
    cached["cache_version"] = 2
    cache_path(root).write_text(json.dumps(cached))

    assert load_cache(root) is None
    stats: dict = {}
    build_evidence(root, cache=True, stats=stats)
    assert stats == {"reused": 0, "extracted": 3}


def test_corrupt_cache_is_a_miss_not_an_error(tmp_path):
    root = make_repo(tmp_path)
    build_evidence(root, cache=True)
    cache_path(root).write_text("{broken json")
    stats: dict = {}
    warm = build_evidence(root, cache=True, stats=stats)
    assert stats["extracted"] == 3
    assert as_bytes(warm) == as_bytes(build_evidence(root, cache=False))


def test_touched_but_identical_content_still_correct(tmp_path):
    root = make_repo(tmp_path)
    build_evidence(root, cache=True)
    content = (root / "a.py").read_text()
    (root / "a.py").write_text(content)  # new mtime, same bytes
    stats = {}
    warm = build_evidence(root, cache=True, stats=stats)
    assert stats == {"reused": 3, "extracted": 0}
    assert as_bytes(warm) == as_bytes(build_evidence(root, cache=False))


def test_cache_lives_outside_repo_and_never_enters_evidence(tmp_path):
    root = make_repo(tmp_path)
    build_evidence(root, cache=True)
    evidence = build_evidence(root, cache=True)
    blob = json.dumps(evidence)
    assert ".glossarize" not in blob
    assert cache_path(root).is_file()
    assert not cache_path(root).resolve().is_relative_to(root.resolve())
    assert load_cache(root)["generator_version"] == __version__


def test_deeply_nested_cache_json_is_a_miss(tmp_path):
    path = cache_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("[" * 60000 + "]" * 60000)
    assert load_cache(tmp_path) is None  # miss, not a crash


def test_oversized_cache_is_a_miss(tmp_path, monkeypatch):
    # Security boundary (SECURITY.md): an untrusted repo shipping a giant
    # cache.json must be a miss, never read into memory and OOM the process.
    monkeypatch.setattr("glossarize.artifacts.MAX_JSON_BYTES", 50)
    root = make_repo(tmp_path)
    path = cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"cache_version": 1, "generator_version": __version__,
         "git": {}, "files": {"x": "y" * 200}}
    ))
    assert load_cache(root) is None


def test_wrong_top_level_cache_json_is_a_miss(tmp_path):
    path = cache_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("[]")
    assert load_cache(tmp_path) is None


def test_same_size_same_mtime_rewrite_invalidates_by_content(tmp_path):
    root = make_repo(tmp_path)
    build_evidence(root, cache=True)
    changed = root / "b.py"
    before = changed.stat()
    changed.write_text("forgery_worker = 1\n")  # same bytes as billing_worker
    assert changed.stat().st_size == before.st_size
    os.utime(changed, ns=(before.st_atime_ns, before.st_mtime_ns))

    stats = {}
    warm = build_evidence(root, cache=True, stats=stats)
    assert stats == {"reused": 2, "extracted": 1}
    blob = json.dumps(warm)
    assert "forgery_worker" in blob and "billing_worker" not in blob


def test_repository_supplied_legacy_cache_is_never_trusted(tmp_path):
    root = make_repo(tmp_path)
    legacy = root / ".glossarize"
    legacy.mkdir()
    (legacy / "cache.json").write_text(json.dumps({
        "cache_version": 2,
        "generator_version": __version__,
        "repository": str(root.resolve()),
        "files": {
            "a.py": {
                "kind": "code",
                "language": "python",
                "identifiers": {"fabricated_identifier": 999},
                "imports": [],
                "content_sha256": "0" * 64,
                "size": 1,
            }
        },
    }))

    blob = json.dumps(build_evidence(root, cache=True))
    assert "fabricated_identifier" not in blob
    assert "payment_service" in blob


def test_cache_is_disabled_if_configured_inside_scanned_repo(
    tmp_path, monkeypatch
):
    root = make_repo(tmp_path)
    unsafe = root / ".user-cache"
    monkeypatch.setenv("GLOSSARIZE_CACHE_DIR", str(unsafe))

    build_evidence(root, cache=True)
    stats = {}
    build_evidence(root, cache=True, stats=stats)

    assert stats == {"reused": 0, "extracted": 3}
    assert not unsafe.exists()
