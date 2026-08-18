"""Incremental cache: warm results must be byte-identical to cold scans,
only changed files may be re-extracted, and every doubt (version change,
corruption) must read as a miss, never as stale data."""

import hashlib
import json
import os

import pytest

from glossabet import __version__
from glossabet.corpus.cache import CACHE_VERSION, cache_path, clear_cache, load_cache
from glossabet.analysis.evidence import build_evidence


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
    cached = json.loads(cache_path(root).read_text(encoding="utf-8"))
    cached["generator_version"] = "0.0.0-older"
    cache_path(root).write_text(json.dumps(cached))
    assert load_cache(root) is None  # a version mismatch is a full miss
    stats: dict = {}
    build_evidence(root, cache=True, stats=stats)
    assert stats["extracted"] == 3 and stats["reused"] == 0


def test_ascii_tokenizer_cache_version_is_invalidated(tmp_path):
    root = make_repo(tmp_path)
    build_evidence(root, cache=True)
    cached = json.loads(cache_path(root).read_text(encoding="utf-8"))
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
    content = (root / "a.py").read_text(encoding="utf-8")
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
    assert ".glossabet" not in blob
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
    monkeypatch.setattr("glossabet.runtime.artifacts.MAX_JSON_BYTES", 50)
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
    legacy = root / ".glossabet"
    legacy.mkdir()
    # Every field is deliberately valid for the CURRENT cache schema —
    # correct version, identity, digest, and size — so the only thing
    # standing between the fabricated identifier and the evidence is that
    # the engine must never read a repository-supplied cache location.
    content = (root / "a.py").read_bytes()
    (legacy / "cache.json").write_text(json.dumps({
        "cache_version": CACHE_VERSION,
        "generator_version": __version__,
        "repository": os.path.normcase(str(root.resolve())),
        "files": {
            "a.py": {
                "kind": "code",
                "language": "python",
                "identifiers": {"fabricated_identifier": 999},
                "imports": [],
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
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
    monkeypatch.setenv("GLOSSABET_CACHE_DIR", str(unsafe))

    build_evidence(root, cache=True)
    stats = {}
    build_evidence(root, cache=True, stats=stats)

    assert stats == {"reused": 0, "extracted": 3}
    assert not unsafe.exists()


def test_cache_clear_removes_only_glossabet_layout(tmp_path, capsys):
    from glossabet.cli import main

    (tmp_path / "repo").mkdir()
    repo = make_repo(tmp_path / "repo")
    build_evidence(repo, cache=True)
    path = cache_path(repo)
    assert path.is_file()
    root = path.parent.parent

    # Foreign content under the same root must survive: a stray file, a
    # non-hex directory, and a symlinked directory pointing at user data.
    (root / "notes.txt").write_text("mine")
    (root / "other-tool").mkdir()
    (root / "other-tool" / "data").write_text("x")
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep").write_text("keep")
    os.symlink(victim, root / ("a" * 64), target_is_directory=True)

    assert main(["cache-clear"]) == 0
    out = capsys.readouterr().out
    assert "removed 1 repository entry" in out
    assert not path.exists()
    assert not path.parent.exists()
    assert (root / "notes.txt").read_text() == "mine"
    assert (root / "other-tool" / "data").read_text() == "x"
    assert (victim / "keep").read_text() == "keep"
    assert (root / ("a" * 64)).is_symlink()
    assert "left in place" in out
    assert root.is_dir()


def test_cache_clear_removes_empty_root_and_reports_absence(tmp_path, capsys):
    from glossabet.cli import main

    (tmp_path / "repo").mkdir()
    repo = make_repo(tmp_path / "repo")
    build_evidence(repo, cache=True)
    root = cache_path(repo).parent.parent

    assert main(["cache-clear"]) == 0
    assert "cache directory removed" in capsys.readouterr().out
    assert not root.exists()

    assert main(["cache-clear"]) == 0
    assert "nothing to remove" in capsys.readouterr().out


def test_cache_clear_reports_an_unlistable_entry_instead_of_crashing(tmp_path, monkeypatch):
    """An entry directory that cannot be listed is left in place and named in
    the report, after the removable entries were still removed."""
    root = tmp_path / "cache"
    good = root / ("a" * 64)
    good.mkdir(parents=True)
    (good / "cache.json").write_text("{}")
    locked = root / ("c" * 64)
    locked.mkdir()
    (locked / "cache.json").write_text("{}")
    locked.chmod(0)
    monkeypatch.setenv("GLOSSABET_CACHE_DIR", str(root))
    try:
        if os.access(locked, os.R_OK):
            pytest.skip("running as root: every directory is listable")
        report = clear_cache()
    finally:
        locked.chmod(0o755)
    assert report["removed_entries"] == 1
    assert report["unrecognized_left_in_place"] == ["c" * 64]
    assert report["root_removed"] is False


def test_malformed_cache_entries_are_misses_never_crashes_or_stale_evidence(tmp_path):
    """A cache whose envelope is valid but whose per-file entries are the
    wrong shape (a hand edit, a crash mid-write, a future format) must read
    as a miss for those files: the warm scan re-extracts them and stays
    byte-identical to a cold scan. Without the entry-shape check every scan
    would crash on the first malformed entry (probed by the audit)."""
    root = make_repo(tmp_path)
    build_evidence(root, cache=True)
    path = cache_path(root)
    good = json.loads(path.read_text(encoding="utf-8"))
    cold = as_bytes(build_evidence(root, cache=False))
    assert set(good["files"]) == {"a.py", "b.py", "README.md"}

    def corrupt(mutate):
        data = json.loads(json.dumps(good))
        mutate(data["files"])
        path.write_text(json.dumps(data), encoding="utf-8")
        stats: dict = {}
        warm = build_evidence(root, cache=True, stats=stats)
        assert as_bytes(warm) == cold
        return stats["extracted"]

    # Every corruption family: wrong container, wrong field types, negative
    # counts, booleans where ints belong, missing fields, wrong kind.
    assert corrupt(lambda f: f.__setitem__("a.py", "not-a-dict")) == 1
    assert corrupt(lambda f: f["a.py"].__setitem__("identifiers", ["x"])) == 1
    assert corrupt(lambda f: f["a.py"]["identifiers"].__setitem__("payment", -1)) == 1
    assert corrupt(lambda f: f["a.py"]["identifiers"].__setitem__("payment", True)) == 1
    assert corrupt(lambda f: f["a.py"].__setitem__("imports", "os")) == 1
    assert corrupt(lambda f: f["a.py"].__setitem__("size", "12")) == 1
    assert corrupt(lambda f: f["a.py"].__setitem__("size", True)) == 1
    assert corrupt(lambda f: f["a.py"].__setitem__("imports", [7])) == 1
    assert corrupt(lambda f: f["a.py"].pop("language")) == 1
    assert corrupt(lambda f: f["a.py"].__setitem__("kind", "doc")) == 1
    assert corrupt(lambda f: f["README.md"].__setitem__("words", [["billing", 1]])) == 1
    assert corrupt(lambda f: f["README.md"].__setitem__("word_total", -3)) == 1
    assert corrupt(lambda f: f["README.md"].pop("word_total")) == 1
    # Two entries broken at once: only those two are re-extracted.
    def two(f):
        f["a.py"]["identifiers"] = None
        f["b.py"]["language"] = 7
    assert corrupt(two) == 2
    # And an intact cache re-extracts nothing.
    assert corrupt(lambda f: None) == 0
