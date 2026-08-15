"""Evidence builder: the concrete threats — ingested secrets, contaminated
evidence, nondeterminism, silent truncation, missed monorepo shape."""

import json
import os

from glossabet.cli import main
from glossabet.evidence import Limits, build_evidence, scan_command, write_evidence


def make_repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "payment_service.py").write_text(
        "class PaymentService:\n"
        "    def charge_payment(self, payment_request):\n"
        "        return payment_request\n"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text(
        "The payment gateway is the boundary to the processor.\n"
    )
    # Must never enter evidence:
    (tmp_path / ".env").write_text("API_TOKEN=SECRETTOKENVALUE\n")
    (tmp_path / "secrets.yaml").write_text("password: HUSHEDVALUE\n")
    (tmp_path / "cert.pem").write_text("PEMSECRETBODY\n")
    (tmp_path / "GLOSSARY.md").write_text("zanzibar is our canonical term\n")
    gout = tmp_path / "glossabet-out"
    gout.mkdir()
    (gout / "old.json").write_text('{"term": "contaminantword"}\n')
    nm = tmp_path / "node_modules"
    nm.mkdir()
    (nm / "junk.js").write_text("var noisetokenword = 1;\n")
    return tmp_path


def test_sensitive_files_never_enter_evidence(tmp_path):
    evidence = build_evidence(make_repo(tmp_path))
    blob = json.dumps(evidence)
    assert "SECRETTOKENVALUE" not in blob and "secrettokenvalue" not in blob
    assert "HUSHEDVALUE" not in blob.upper()
    assert "PEMSECRETBODY" not in blob.upper()
    assert sorted(evidence["skipped"]["sensitive"]) == [
        ".env", "cert.pem", "secrets.yaml",
    ]


def test_own_outputs_and_noise_dirs_excluded(tmp_path):
    blob = json.dumps(build_evidence(make_repo(tmp_path)))
    assert "zanzibar" not in blob  # GLOSSARY.md (contamination rule)
    assert "contaminantword" not in blob  # glossabet-out/
    assert "noisetokenword" not in blob  # node_modules/


def test_pre_rename_output_and_cache_directories_stay_excluded(tmp_path):
    root = make_repo(tmp_path)
    old_output = root / "glossarize-out"
    old_output.mkdir()
    (old_output / "old.json").write_text('{"term": "legacycontaminant"}\n')
    old_cache = root / ".glossarize"
    old_cache.mkdir()
    (old_cache / "cache.json").write_text(
        '{"term": "legacycachecontaminant"}\n'
    )

    blob = json.dumps(build_evidence(root))

    assert "legacycontaminant" not in blob
    assert "legacycachecontaminant" not in blob


def test_vocabulary_normalizes_across_conventions(tmp_path):
    evidence = build_evidence(make_repo(tmp_path))
    tokens = {t["term"]: t for t in evidence["vocabulary"]["tokens"]["items"]}
    # PaymentService + charge_payment + payment_request all feed "payment".
    assert tokens["payment"]["count"] == 4
    assert tokens["payment"]["locations"][0]["path"] == "src/payment_service.py"


def test_scan_is_deterministic_including_own_output(tmp_path):
    root = make_repo(tmp_path)
    first = build_evidence(root)
    write_evidence(root, first)  # second walk sees glossabet-out/ and must ignore it
    second = build_evidence(root)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_first_output_directory_does_not_change_walk_budget(tmp_path):
    (tmp_path / "service.py").write_text("payment_service = 1\n")
    first = build_evidence(tmp_path)

    write_evidence(tmp_path, first)
    second = build_evidence(tmp_path)

    assert first["skipped"]["corpus_budget"] == second["skipped"]["corpus_budget"]
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_truncation_is_capped_marked_and_counted(tmp_path):
    (tmp_path / "a.py").write_text("alpha_word\nbeta_word\nbeta_word\n")
    (tmp_path / "b.py").write_text("beta_word\ngamma_word\ndelta_word\n")
    limits = Limits(tokens=2, identifiers=2, doc_terms=2, locations_per_term=1)
    evidence = build_evidence(tmp_path, limits)
    tokens = evidence["vocabulary"]["tokens"]
    assert len(tokens["items"]) == 2
    trunc = tokens["truncated"]
    assert trunc is not None and trunc["dropped_terms"] > 0
    assert trunc["dropped_occurrences"] > 0
    beta = next(t for t in tokens["items"] if t["term"] == "beta")
    assert beta["files"] == 2  # true breadth survives the location cap
    assert len(beta["locations"]) == 1 and beta["locations_truncated"] is True


def test_corpus_file_budget_is_deterministic_and_reported(tmp_path, monkeypatch):
    monkeypatch.setattr("glossabet.scanner.MAX_SOURCE_FILES", 2)
    for name in ("c.py", "a.py", "b.py"):
        (tmp_path / name).write_text(f"{name[0]}_identifier = 1\n")

    evidence = build_evidence(tmp_path)
    budget = evidence["skipped"]["corpus_budget"]

    assert [item["path"] for item in evidence["files"]["code"]] == [
        "a.py", "b.py",
    ]
    assert evidence["totals"]["source_files"] == 2
    assert budget["complete"] is False
    assert budget["production_complete"] is False
    assert budget["used"]["source_files"] == 2
    assert budget["skipped"]["source_files"] == 1
    assert budget["skipped"]["sample"] == [
        {"path": "c.py", "reason": "source-file-limit"}
    ]


def test_oversized_production_source_marks_corpus_incomplete(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("glossabet.scanner.MAX_FILE_BYTES", 40)
    (tmp_path / "small.py").write_text("ordinary = 1\n")
    (tmp_path / "large.py").write_text(
        "hidden_canonical_term = 1\n" + "# padding\n" * 10
    )

    evidence = build_evidence(tmp_path)
    budget = evidence["skipped"]["corpus_budget"]

    assert evidence["skipped"]["oversized"] == ["large.py"]
    assert budget["complete"] is False
    assert budget["production_complete"] is False
    assert budget["skipped"]["source_files"] == 1
    assert budget["skipped"]["sample"] == [
        {"path": "large.py", "reason": "file-size-limit"}
    ]


def test_skipped_nonproduction_source_keeps_production_corpus_complete(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("glossabet.scanner.MAX_SOURCE_FILES", 1)
    (tmp_path / "a.py").write_text("production_name = 1\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "z.py").write_text("test_only_name = 1\n")

    budget = build_evidence(tmp_path)["skipped"]["corpus_budget"]

    assert budget["complete"] is False
    assert budget["production_complete"] is True
    assert budget["skipped"]["production_source_files"] == 0


def test_corpus_byte_budget_reports_skips_and_can_use_later_space(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("glossabet.scanner.MAX_SOURCE_BYTES", 35)
    (tmp_path / "a.py").write_text("alpha_identifier = 1\n")
    (tmp_path / "b.py").write_text("bravo_identifier = 2\n")
    (tmp_path / "c.py").write_text("c = 3\n")

    evidence = build_evidence(tmp_path)
    budget = evidence["skipped"]["corpus_budget"]

    assert [item["path"] for item in evidence["files"]["code"]] == [
        "a.py", "c.py",
    ]
    assert budget["used"]["source_bytes"] <= 35
    assert budget["skipped"]["sample"] == [
        {"path": "b.py", "reason": "source-byte-limit"}
    ]


def test_walk_work_budget_marks_unknown_remainder(tmp_path, monkeypatch):
    monkeypatch.setattr("glossabet.scanner.MAX_WALK_ENTRIES", 2)
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / name).write_text(f"{name[0]}_identifier = 1\n")

    evidence = build_evidence(tmp_path)
    budget = evidence["skipped"]["corpus_budget"]

    assert budget["complete"] is False
    assert budget["used"]["walk_entries"] == 2
    assert budget["walk_remainder"] == {
        "truncated": True,
        "minimum_entries_omitted": 1,
        "exact": False,
        "sample": [{"path": ".", "reason": "walk-entry-limit"}],
        "sample_truncated": False,
    }
    assert [item["path"] for item in evidence["files"]["code"]] == [
        "a.py", "b.py",
    ]


def test_corpus_budget_skip_sample_is_itself_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr("glossabet.scanner.MAX_SOURCE_FILES", 1)
    monkeypatch.setattr("glossabet.scanner.BUDGET_PATH_SAMPLE", 1)
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / name).write_text(f"{name[0]}_identifier = 1\n")

    budget = build_evidence(tmp_path)["skipped"]["corpus_budget"]

    assert budget["skipped"]["source_files"] == 2
    assert len(budget["skipped"]["sample"]) == 1
    assert budget["skipped"]["sample_truncated"] is True


def test_overfull_directory_is_skipped_whole_to_preserve_determinism(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("glossabet.scanner.MAX_DIRECTORY_ENTRIES", 2)
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / name).write_text(f"{name[0]}_identifier = 1\n")

    evidence = build_evidence(tmp_path)
    budget = evidence["skipped"]["corpus_budget"]

    assert evidence["files"]["code"] == []
    assert budget["walk_remainder"]["minimum_entries_omitted"] == 3
    assert budget["walk_remainder"]["sample"] == [
        {"path": ".", "reason": "directory-entry-limit"}
    ]


def test_monorepo_detected_by_sub_roots(tmp_path):
    for name in ("a", "b", "c"):
        d = tmp_path / "packages" / name
        d.mkdir(parents=True)
        (d / "package.json").write_text("{}")
        (d / "index.js").write_text("var x = 1;\n")
    mono = build_evidence(tmp_path)["monorepo"]
    assert mono["detected"] is True
    assert len(mono["sub_roots"]) == 3
    assert any("sub-projects" in r for r in mono["reasons"])


def test_monorepo_detected_by_workspace_manifest(tmp_path):
    (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - 'packages/*'\n")
    (tmp_path / "index.js").write_text("var x = 1;\n")
    mono = build_evidence(tmp_path)["monorepo"]
    assert mono["detected"] is True
    assert any("pnpm-workspace.yaml" in r for r in mono["reasons"])


def test_small_single_project_is_not_flagged(tmp_path):
    evidence = build_evidence(make_repo(tmp_path))
    assert evidence["monorepo"]["detected"] is False
    assert evidence["repository"]["git"] == {"head": None, "dirty": None}


def test_scan_command_end_to_end(tmp_path, capsys):
    root = make_repo(tmp_path)
    assert main(["scan", str(root)]) == 0
    assert (root / "glossabet-out" / "evidence.json").is_file()
    out = capsys.readouterr()
    assert "code files" in out.out
    assert "sensitive" in out.err  # exclusion is reported, not silent


def test_scan_on_missing_path_is_user_error(tmp_path):
    assert scan_command(str(tmp_path / "nope")) == 1


def test_nested_glossary_md_excluded(tmp_path):
    # Contamination rule holds at any depth, not just the repo root.
    (tmp_path / "main.py").write_text("widget = 1\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "GLOSSARY.md").write_text("nestedglossaryword is canonical\n")
    assert "nestedglossaryword" not in json.dumps(build_evidence(tmp_path))


def test_sensitive_directories_pruned_and_reported(tmp_path):
    # An innocuously named file inside a sensitive-named directory must
    # never enter evidence, and the exclusion is reported, not silent.
    (tmp_path / "main.py").write_text("x = 1\n")
    sec = tmp_path / "secrets"
    sec.mkdir()
    (sec / "notes.txt").write_text("the master password is huntertwovalue\n")
    nested = tmp_path / "config" / "credentials"
    nested.mkdir(parents=True)
    (nested / "db.txt").write_text("dbleakword access phrase\n")
    evidence = build_evidence(tmp_path)
    blob = json.dumps(evidence).lower()
    assert "huntertwovalue" not in blob and "dbleakword" not in blob
    assert "secrets" in evidence["skipped"]["sensitive"]
    assert "config/credentials" in evidence["skipped"]["sensitive"]


def test_code_bytes_counts_bytes_not_characters(tmp_path):
    path = tmp_path / "unicode.py"
    path.write_text("# café résumé naïveté\nx = 1\n", encoding="utf-8")
    evidence = build_evidence(tmp_path)
    assert evidence["totals"]["code_bytes"] == path.stat().st_size
    assert evidence["totals"]["source_bytes"] == path.stat().st_size


def test_unicode_and_language_forms_round_trip_through_evidence(tmp_path):
    (tmp_path / "unicode.py").write_text(
        "ÜberHTTP2Server = 1\n支付Service = 2\nданные_очереди = 3\n",
        encoding="utf-8",
    )
    (tmp_path / "queue.clj").write_text("(def pending-work 1)\n")

    evidence = build_evidence(tmp_path)
    tokens = {
        entry["term"] for entry in evidence["vocabulary"]["tokens"]["items"]
    }
    identifiers = {
        entry["name"]: entry["tokens"]
        for entry in evidence["vocabulary"]["identifiers"]["items"]
    }

    assert {"über", "http2", "支付", "данные", "очереди"} <= tokens
    assert identifiers["ÜberHTTP2Server"] == ["über", "http2", "server"]
    assert identifiers["pending-work"] == ["pending", "work"]
    assert evidence["vocabulary"]["normalization"]["parser_backed"] is False


def test_scan_reports_partial_corpus_budget(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("glossabet.scanner.MAX_SOURCE_FILES", 1)
    (tmp_path / "a.py").write_text("alpha_identifier = 1\n")
    (tmp_path / "b.py").write_text("bravo_identifier = 2\n")

    assert main(["scan", str(tmp_path)]) == 0

    captured = capsys.readouterr()
    assert "corpus budget" in captured.err
    assert "evidence is partial" in captured.err


def test_symlink_escaping_repo_is_not_ingested(tmp_path):
    # A hostile repo cannot read host files from outside itself via a
    # symlink: os.walk's followlinks=False guards directories, not files.
    outside = tmp_path / "outside_host_file.py"
    outside.write_text("stolenhostsecret = 1\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("x = 1\n")
    os.symlink(outside, repo / "leaked.py")
    evidence = build_evidence(repo)
    assert "stolenhostsecret" not in json.dumps(evidence)
    assert "leaked.py" in evidence["skipped"]["symlinks_escaping_repo"]
    assert "leaked.py" not in [f["path"] for f in evidence["files"]["code"]]


def test_symlink_inside_repo_still_scanned(tmp_path):
    # An in-repo symlink target is legitimate content and is not skipped as
    # an escape (its identifiers still reach evidence).
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "real.py").write_text("insideridentifier = 1\n")
    os.symlink(repo / "real.py", repo / "link.py")
    assert "insideridentifier" in json.dumps(build_evidence(repo))


def test_hostile_git_config_does_not_execute_code(tmp_path, monkeypatch):
    # A repo whose .git/config sets core.fsmonitor must not run that command
    # when glossabet reads the git stamp (core.fsmonitor fires on git status).
    import subprocess as sp
    from glossabet.evidence import _git_stamp
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
    stamp = _git_stamp(repo)
    assert stamp["head"] is not None  # git still works
    assert not marker.exists(), "core.fsmonitor command was executed"


def test_deeply_nested_graph_json_does_not_crash(tmp_path):
    (tmp_path / "main.py").write_text("x = 1\n")
    gout = tmp_path / "graphify-out"
    gout.mkdir()
    depth = 60000
    (gout / "graph.json").write_text("[" * depth + "]" * depth)
    evidence = build_evidence(tmp_path)  # must not raise RecursionError
    assert evidence["structural_groups"]["available"] is False


def test_evidence_symlink_cannot_overwrite_outside_file(tmp_path, capsys):
    outside = tmp_path / "outside.json"
    outside.write_text("sentinel\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("ordinary_identifier = 1\n")
    out = repo / "glossabet-out"
    out.mkdir()
    os.symlink(outside, out / "evidence.json")

    assert main(["scan", str(repo)]) == 1
    assert outside.read_text() == "sentinel\n"
    assert "symlinked artifact" in capsys.readouterr().err


def test_output_directory_symlink_cannot_redirect_writes(tmp_path, capsys):
    outside = tmp_path / "outside-output"
    outside.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("ordinary_identifier = 1\n")
    os.symlink(outside, repo / "glossabet-out")

    assert main(["scan", str(repo)]) == 1
    assert not (outside / "evidence.json").exists()
    assert "symlinked artifact" in capsys.readouterr().err


def test_oversized_root_workspace_manifest_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr("glossabet.scanner.MAX_FILE_BYTES", 50)
    (tmp_path / "main.py").write_text("ordinary_identifier = 1\n")
    (tmp_path / "package.json").write_text(
        json.dumps({"workspaces": ["packages/*"], "padding": "x" * 100})
    )

    evidence = build_evidence(tmp_path)
    assert evidence["monorepo"]["detected"] is False
    assert "package.json" in evidence["skipped"]["oversized"]


def test_escaping_root_workspace_manifest_symlink_is_not_read(tmp_path):
    outside = tmp_path / "outside-Cargo.toml"
    outside.write_text("[workspace]\nmembers = ['packages/*']\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("ordinary_identifier = 1\n")
    os.symlink(outside, repo / "Cargo.toml")

    evidence = build_evidence(repo)
    assert evidence["monorepo"]["detected"] is False
    assert "Cargo.toml" in evidence["skipped"]["symlinks_escaping_repo"]
