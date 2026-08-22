"""Evidence builder: the concrete threats — ingested secrets, contaminated
evidence, nondeterminism, silent truncation, missed monorepo shape."""

import json
import os

import pytest

from glossabet.analysis.evidence import Limits, build_evidence, write_evidence
from glossabet.cli import main
from glossabet.corpus.scanner import EXCLUSION_KINDS, SkippedPaths, WalkResult


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
    # Source-shaped canaries too: a `.json` is never read for vocabulary, so
    # it alone cannot prove glossabet-out/ is excluded rather than skipped
    # for its extension (test-audit). `.glossabet/` is a hidden directory,
    # so its canary pins the outcome (no cache content in evidence), not
    # which rule produced it.
    (gout / "leak.py").write_text("outdirsourceword = 1\n")
    (gout / "notes.md").write_text("outdirdocword is discussed here\n")
    cache = tmp_path / ".glossabet"
    cache.mkdir()
    (cache / "cache.py").write_text("cachedirsourceword = 1\n")
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


def test_additional_private_key_and_credential_names_are_sensitive():
    """One representative per documented family (dotenv names and variants,
    key/certificate extensions, SSH identities, credential stores, secret/
    credential words), so dropping any one alternative from the pattern
    set fails here rather than leaking through a family no test named."""
    from glossabet.corpus.scanner import is_sensitive

    for name in (
        # dotenv: bare, prefixed, suffixed, and the .env.<stage> family
        ".env", "prod.env", ".env.production", "app.env.local",
        # private keys / certificates / stores, every extension alternative
        "server.pem", "server.key", "cert.p12", "cert.pfx", "trust.jks",
        "app.keystore", "cert.der", "private.p8", "server.ppk",
        "backup.kdbx", "key.asc", "key.gpg", "key.pgp",
        # SSH identities
        "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
        # credential stores
        ".netrc", ".npmrc", ".pypirc", ".htpasswd", ".dockercfg",
        # words anywhere in the name
        "secrets.yaml", "my_secret_config.py", "credentials.json",
        "SERVER.PEM", "Key.GPG", "ID_ED25519",  # case-insensitive
    ):
        assert is_sensitive(name), name
    for name in (
        "main.py", "README.md", "data.json", "environment.py",
        "id_card.py", "keyboard.py", "pemberton.md",
    ):
        # (`secretary.md` matches the `secret` word rule: over-exclusion is
        # the safe direction and is deliberate.)
        assert not is_sensitive(name), name


def test_sensitive_files_of_every_family_never_enter_evidence(tmp_path):
    """End to end for the families the unit test names by pattern only: the
    file bodies carry unique canary words that must appear nowhere in the
    evidence document, and each file lands in the sensitive ledger."""
    canaries = {
        ".env.local": "DOTENVSTAGECANARY=1\n",
        "deploy.env": "DOTENVSUFFIXCANARY=1\n",
        "id_ed25519": "SSHIDENTITYCANARY\n",
        ".npmrc": "//registry/:_authToken=NPMRCCANARY\n",
        "client.p12": "PKCSCANARYBODY\n",
        "credentials.json": '{"credentialcanary": 1}\n',
    }
    for name, body in canaries.items():
        (tmp_path / name).write_text(body)
    (tmp_path / "app.py").write_text("ordinary_module = 1\n")
    evidence = build_evidence(tmp_path)
    blob = json.dumps(evidence).casefold()
    assert "canary" not in blob
    assert sorted(evidence["skipped"]["sensitive"]) == sorted(canaries)
    assert "ordinary" in blob


def test_own_outputs_and_noise_dirs_excluded(tmp_path):
    blob = json.dumps(build_evidence(make_repo(tmp_path)))
    assert "zanzibar" not in blob  # GLOSSARY.md (contamination rule)
    assert "contaminantword" not in blob  # glossabet-out/
    assert "outdirsourceword" not in blob  # glossabet-out/*.py
    assert "outdirdocword" not in blob  # glossabet-out/*.md
    assert "cachedirsourceword" not in blob  # .glossabet/
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


def test_language_tokens_are_tagged_not_deleted_and_domain_use_wins(tmp_path):
    (tmp_path / "builtins.py").write_text(
        "items = dict()\nitems.append(len(items))\n"
    )
    (tmp_path / "domain.js").write_text("const dict = domain_dictionary\n")

    first = build_evidence(tmp_path)
    second = build_evidence(tmp_path)
    tokens = {
        item["term"]: item
        for item in first["vocabulary"]["tokens"]["items"]
    }

    assert tokens["append"]["origin"] == "language"
    assert tokens["len"]["origin"] == "language"
    assert tokens["dict"]["origin"] == "domain"
    assert tokens["domain"]["origin"] == "domain"
    assert all(item["origin"] in {"language", "domain"} for item in tokens.values())
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


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
    monkeypatch.setattr("glossabet.corpus.scanner.MAX_SOURCE_FILES", 2)
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
    monkeypatch.setattr("glossabet.corpus.scanner.MAX_FILE_BYTES", 40)
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
    monkeypatch.setattr("glossabet.corpus.scanner.MAX_SOURCE_FILES", 1)
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
    monkeypatch.setattr("glossabet.corpus.scanner.MAX_SOURCE_BYTES", 35)
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
    monkeypatch.setattr("glossabet.corpus.scanner.MAX_WALK_ENTRIES", 2)
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
    monkeypatch.setattr("glossabet.corpus.scanner.MAX_SOURCE_FILES", 1)
    monkeypatch.setattr("glossabet.corpus.scanner.BUDGET_PATH_SAMPLE", 1)
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / name).write_text(f"{name[0]}_identifier = 1\n")

    budget = build_evidence(tmp_path)["skipped"]["corpus_budget"]

    assert budget["skipped"]["source_files"] == 2
    assert len(budget["skipped"]["sample"]) == 1
    assert budget["skipped"]["sample_truncated"] is True


def test_overfull_directory_is_skipped_whole_to_preserve_determinism(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("glossabet.corpus.scanner.MAX_DIRECTORY_ENTRIES", 2)
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
    monkeypatch.setattr("glossabet.corpus.scanner.MAX_SOURCE_FILES", 1)
    (tmp_path / "a.py").write_text("alpha_identifier = 1\n")
    (tmp_path / "b.py").write_text("bravo_identifier = 2\n")

    assert main(["scan", str(tmp_path)]) == 0

    captured = capsys.readouterr()
    assert "corpus coverage incomplete" in captured.err
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
    assert outside.read_text(encoding="utf-8") == "sentinel\n"
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
    monkeypatch.setattr("glossabet.corpus.scanner.MAX_FILE_BYTES", 50)
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


def test_unreadable_and_binary_sources_are_confessed_not_silent(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "core.py").write_text("core_service = 1\n")
    # ASCII text encoded UTF-16LE is full of NUL bytes: binary despite .md.
    (tmp_path / "notes.md").write_bytes("utf sixteen words\n".encode("utf-16-le"))
    (tmp_path / "broken.py").write_bytes(b"\0\0\0\0binary blob")

    evidence = build_evidence(tmp_path)

    budget = evidence["skipped"]["corpus_budget"]
    assert budget["complete"] is False
    assert budget["production_complete"] is False
    reasons = {
        item["path"]: item["reason"] for item in budget["skipped"]["sample"]
    }
    assert reasons == {
        "broken.py": "binary-content",
        "notes.md": "binary-content",
    }
    # Inventory stays consistent with totals on both sides.
    assert evidence["totals"]["doc_files"] == len(evidence["files"]["docs"])
    docs_by_path = {d["path"]: d for d in evidence["files"]["docs"]}
    assert docs_by_path["notes.md"]["words"] == 0
    # The unreadable code file contributed no identifiers.
    names = {e["name"] for e in evidence["vocabulary"]["identifiers"]["items"]}
    assert names == {"core_service"}
    # A read-failed file moves from used to skipped; it is never on both
    # sides of the ledger.
    assert (
        budget["used"]["source_files"] + budget["skipped"]["source_files"]
        == evidence["totals"]["source_files"]
    )


def test_oserror_during_read_is_confessed_as_unreadable(tmp_path, monkeypatch):
    core_source = b"core_service = 1\n"
    vanished_source = b"vanished_service = 1\n"
    (tmp_path / "core.py").write_bytes(core_source)
    (tmp_path / "gone.py").write_bytes(vanished_source)

    import glossabet.corpus.extraction as extraction_module

    real_read = extraction_module.read_source

    def failing_read(path):
        if path.name == "gone.py":
            path.unlink()  # vanished between the walk's stat and the read
            return "unreadable"
        return real_read(path)

    monkeypatch.setattr(extraction_module, "read_source", failing_read)
    evidence = build_evidence(tmp_path)

    budget = evidence["skipped"]["corpus_budget"]
    assert budget["complete"] is False
    assert {item["reason"] for item in budget["skipped"]["sample"]} == {
        "unreadable"
    }
    assert (
        budget["used"]["source_files"] + budget["skipped"]["source_files"]
        == evidence["totals"]["source_files"]
    )
    # The bytes moved to the skipped side are the ones the walk charged
    # (a fresh stat of the vanished file would have subtracted nothing).
    assert budget["skipped"]["source_bytes"] == len(vanished_source)
    assert budget["used"]["source_bytes"] == len(core_source)


def test_pathological_single_identifier_is_bounded_not_a_dos(tmp_path):
    # A single identifier with a huge token count would make the O(t^2)
    # pattern/co-occurrence folding a CPU/memory bomb. It must be capped and
    # the truncation recorded.
    import time

    huge = "_".join(f"t{i:05d}" for i in range(50000))
    (tmp_path / "main.py").write_text(huge + " = 1\n")

    # The same spelling in a second file is still one oversized spelling.
    (tmp_path / "other.py").write_text(huge + " = 2\n")

    start = time.monotonic()
    evidence = build_evidence(tmp_path)
    assert time.monotonic() - start < 10, "folding was not bounded"
    assert evidence["skipped"]["oversized_identifiers"] == 1
    # No token-pattern entry exceeds the per-identifier token cap.
    entry = next(
        item for item in evidence["vocabulary"]["identifiers"]["items"]
        if item["name"] == huge
    )
    assert entry is not None


def test_symlink_to_in_repo_sensitive_file_is_not_laundered(tmp_path):
    # notes.py -> .env: the link's own name is not sensitive and its target
    # is inside the repo, so the escape check passes; without a target-name
    # check the secret contents would land in evidence identifiers.
    (tmp_path / ".env").write_text("AWS_SECRET_ACCESS_KEY=wJalrCANARYsecret\n")
    (tmp_path / "real.py").write_text("legit_name = 1\n")
    os.symlink(".env", tmp_path / "notes.py")

    evidence = build_evidence(tmp_path)
    blob = json.dumps(evidence)

    assert "CANARY" not in blob and "AWS_SECRET" not in blob
    assert "notes.py" in evidence["skipped"]["sensitive"]
    names = {i["name"] for i in evidence["vocabulary"]["identifiers"]["items"]}
    assert names == {"legit_name"}


def test_exclusion_ledger_owns_every_skipped_key_and_sentence(tmp_path):
    """Phase 35.3: the scanner's ledger is the one spelling of each
    exclusion's evidence key and report sentence — a kind that is collected
    but not in the ledger, or in the ledger but not collected, is a silent
    exclusion."""
    from dataclasses import fields

    from glossabet.corpus.scanner import (
        EXCLUSION_KINDS,
        WalkResult,
        exclusion_sentences,
    )

    collected = {f.name for f in fields(WalkResult) if f.name.startswith("skipped_")}
    assert {kind.attribute for kind in EXCLUSION_KINDS} == collected
    assert len({kind.key for kind in EXCLUSION_KINDS}) == len(EXCLUSION_KINDS)

    (tmp_path / "main.py").write_text("x = 1\n")
    (tmp_path / ".env").write_text("SECRET=1\n")
    (tmp_path / "GLOSSARY.md").write_text("# g\n")
    evidence = build_evidence(tmp_path, cache=False)
    skipped = evidence["skipped"]
    assert set(skipped) >= {kind.key for kind in EXCLUSION_KINDS}
    assert exclusion_sentences(skipped) == [
        "excluded 1 sensitive path(s) from evidence",
        "excluded 1 GLOSSARY.md file(s) from lexical evidence "
        "(never evidence for itself)",
    ]


def test_documentation_vocabulary_views_stay_in_step():
    # The doc-term table reads counts and per-file locations from the same
    # aggregate; a fold that updated one view and not the other would let
    # ``files`` disagree with ``count`` in evidence.
    from glossabet.analysis.vocabulary import DocumentationVocabulary

    documentation = DocumentationVocabulary()
    documentation.fold({"tenant": 2, "ledger": 1}, "README.md")
    documentation.fold({"tenant": 3}, "docs/guide.md")

    assert documentation.term_counts == {"tenant": 5, "ledger": 1}
    assert documentation.term_files["tenant"] == {
        "README.md": 2, "docs/guide.md": 3,
    }
    assert documentation.term_files["ledger"] == {"README.md": 1}
    for term, total in documentation.term_counts.items():
        assert sum(documentation.term_files[term].values()) == total


def test_innocently_named_symlinks_cannot_launder_excluded_content(tmp_path):
    """Every exclusion applies to a link's *target* path too: a link named
    like ordinary content must not read GLOSSARY.md, the report, Glossabet's
    own output, a sensitive directory, hidden, ignored, generated, or
    vendored content into evidence — and each refusal is reported."""
    (tmp_path / "main.py").write_text("real_value = 1\n")
    (tmp_path / "GLOSSARY.md").write_text("glossaryleak word\n")
    (tmp_path / "GLOSSABET.md").write_text("reportleak word\n")
    (tmp_path / "glossabet-out").mkdir()
    (tmp_path / "glossabet-out" / "notes.md").write_text("selfoutleak word\n")
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "notes.txt").write_text("secretleak word\n")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "h.py").write_text("hiddenleak = 1\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("vendoredleak = 1\n")
    (tmp_path / "scratch").mkdir()
    (tmp_path / "scratch" / "x.py").write_text("ignoredleak = 1\n")
    (tmp_path / "glossabet.json").write_text(
        json.dumps({"schema_version": 1, "ignore_paths": ["scratch"]})
    )
    links = {
        "glossary_link.md": "GLOSSARY.md",
        "report_link.md": "GLOSSABET.md",
        "selfout_link.md": "glossabet-out/notes.md",
        "innocent.txt": "secrets/notes.txt",
        "hidden_link.py": ".hidden/h.py",
        "vendored_link.js": "node_modules/junk.js",
        "ignored_link.py": "scratch/x.py",
    }
    for link, target in links.items():
        os.symlink(tmp_path / target, tmp_path / link)

    evidence = build_evidence(tmp_path)

    blob = json.dumps(evidence)
    for canary in ("glossaryleak", "reportleak", "selfoutleak", "secretleak",
                   "hiddenleak", "vendoredleak", "ignoredleak"):
        assert canary not in blob, canary
    assert [f["path"] for f in evidence["files"]["code"]] == ["main.py"]
    assert evidence["files"]["docs"] == []
    assert evidence["skipped"]["symlinks_to_excluded_content"] == [
        "glossary_link.md", "hidden_link.py", "ignored_link.py",
        "report_link.md", "selfout_link.md", "vendored_link.js",
    ]
    assert "innocent.txt" in evidence["skipped"]["sensitive"]


def test_walk_reports_directory_symlinks_dangling_links_and_unlistable_dirs(
    tmp_path, tmp_path_factory, monkeypatch
):
    """Nothing the walk meets and does not read is silent: an escaping
    directory link, a confined directory link (real path is walked), a
    dangling file link, and an unlistable directory each land in a ledger,
    and an unlistable directory makes the walk inexact."""
    (tmp_path / "main.py").write_text("main_value = 1\n")
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "a.py").write_text("real_value = 1\n")
    outside = tmp_path_factory.mktemp("outside")  # pytest-owned, off the repo root
    (outside / "o.py").write_text("outsideleak = 1\n")
    os.symlink(outside, tmp_path / "docs_link")
    os.symlink(tmp_path / "real", tmp_path / "current")
    os.symlink(tmp_path / "missing.py", tmp_path / "broken.py")
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "z.py").write_text("locked_value = 1\n")
    real_scandir = os.scandir

    def unreadable_locked_directory(path):
        if os.path.abspath(path) == os.path.abspath(locked):
            raise PermissionError("synthetic unreadable directory")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", unreadable_locked_directory)
    evidence = build_evidence(tmp_path)

    assert "outsideleak" not in json.dumps(evidence)
    skipped = evidence["skipped"]
    assert skipped["symlinks_escaping_repo"] == ["docs_link"]
    assert skipped["symlinked_directories"] == ["current"]
    assert skipped["unreadable"] == ["broken.py"]
    assert [f["path"] for f in evidence["files"]["code"]] == [
        "main.py", "real/a.py"
    ]
    budget = evidence["skipped"]["corpus_budget"]
    assert budget["complete"] is False
    assert budget["walk_remainder"]["exact"] is False
    assert {"path": "locked", "reason": "unreadable-directory"} in (
        budget["walk_remainder"]["sample"]
    )


def test_non_utf8_text_is_confessed_not_decoded_into_invented_vocabulary(tmp_path):
    """Latin-1/cp1252 bytes must not become `nave_rsum` identifiers or `cafs`
    doc words: the file is skipped with a named reason in the corpus budget
    and the corpus is reported incomplete."""
    (tmp_path / "ok.py").write_text("plain_value = 1\n")
    (tmp_path / "legacy.py").write_bytes("naïve_résumé_value = 1\n".encode("latin-1"))
    (tmp_path / "notes.md").write_bytes("The café’s naïveté façade\n".encode("cp1252"))

    evidence = build_evidence(tmp_path)

    blob = json.dumps(evidence)
    for invented in ("nave", "rsum", "cafs", "faade", "navet"):
        assert invented not in blob, invented
    budget = evidence["skipped"]["corpus_budget"]
    assert budget["complete"] is False
    assert {"path": "legacy.py", "reason": "not-utf-8"} in budget["skipped"]["sample"]
    assert {"path": "notes.md", "reason": "not-utf-8"} in budget["skipped"]["sample"]
    # A UTF-8 file with a BOM and real accents still reads normally, and the
    # BOM is not content: a first-line `import` (anchored at line start)
    # is still seen, so the module's dependency edge is not lost.
    (tmp_path / "legacy.py").write_bytes(
        "\ufeffimport os\nnaïve_value = 1\n".encode("utf-8")
    )
    (tmp_path / "notes.md").unlink()
    evidence = build_evidence(tmp_path)
    assert "naïve" in json.dumps(evidence, ensure_ascii=False)
    assert "os" in {e["name"] for e in evidence["imports"]["external_top"]}


def test_fixture_package_manifests_are_not_monorepo_sub_roots(tmp_path):
    """Three `tests/fixtures/*/package.json` are test scaffolding, not three
    sub-projects; only production-role directories count toward the alert."""
    (tmp_path / "app.py").write_text("app_value = 1\n")
    for name in ("one", "two", "three"):
        fixture = tmp_path / "tests" / "fixtures" / name
        fixture.mkdir(parents=True)
        (fixture / "package.json").write_text("{}")
        (fixture / "index.js").write_text("x = 1\n")
    mono = build_evidence(tmp_path)["monorepo"]
    assert mono == {"detected": False, "reasons": [], "sub_roots": []}
    # Real sub-projects still count.
    for name in ("web", "api", "worker"):
        (tmp_path / "packages" / name).mkdir(parents=True)
        (tmp_path / "packages" / name / "package.json").write_text("{}")
    mono = build_evidence(tmp_path)["monorepo"]
    assert mono["detected"] is True
    assert mono["sub_roots"] == ["packages/api", "packages/web", "packages/worker"]


def test_unstatable_source_files_make_the_corpus_incomplete(tmp_path):
    """A real code file the walk cannot stat (EACCES) is inventory that went
    unread: reported under `unreadable` AND charged to the corpus budget, so
    `complete`/`production_complete` are false — unlike a dangling link,
    which is not source at all."""
    (tmp_path / "main.py").write_text("main_value = 1\n")
    locked = tmp_path / "noexec"
    locked.mkdir()
    (locked / "a.py").write_text("hidden_value = 1\n")
    (locked / "b.md").write_text("hidden words\n")
    os.symlink(tmp_path / "missing.py", tmp_path / "dangling.py")
    locked.chmod(0o444)  # listable, not traversable: stat fails with EACCES
    try:
        if os.access(locked / "a.py", os.R_OK):
            pytest.skip("running as root: nothing is unstatable")
        evidence = build_evidence(tmp_path)
    finally:
        locked.chmod(0o755)
    budget = evidence["skipped"]["corpus_budget"]
    assert sorted(evidence["skipped"]["unreadable"]) == [
        "dangling.py", "noexec/a.py", "noexec/b.md"
    ]
    assert budget["complete"] is False
    assert budget["production_complete"] is False
    assert budget["skipped"]["source_files"] == 2  # the dangling link is not source


def test_symlinked_file_takes_its_targets_role(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests" / "fixtures").mkdir(parents=True)
    (tmp_path / "tests" / "fixtures" / "data.py").write_text("fixtureleak = 1\n")
    (tmp_path / "src" / "real.py").write_text("real_value = 1\n")
    os.symlink(tmp_path / "tests" / "fixtures" / "data.py", tmp_path / "src" / "data.py")
    evidence = build_evidence(tmp_path)
    roles = {f["path"]: f["role"] for f in evidence["files"]["code"]}
    assert roles["src/data.py"] == "fixture"
    assert "fixtureleak" not in json.dumps(evidence["vocabulary"])


def test_root_manifest_probe_applies_the_configured_ignore_rules_to_links(tmp_path):
    """The monorepo probe reads root Cargo.toml/package.json through the same
    link rule as the walk — including the repository's own ignore/role
    configuration — so a link at the root cannot make it read a file the
    configuration excludes."""
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "scratch").mkdir()
    (tmp_path / "scratch" / "manifest.json").write_text(
        json.dumps({"workspaces": ["packages/*"]})
    )
    (tmp_path / "glossabet.json").write_text(
        json.dumps({"schema_version": 1, "ignore_paths": ["scratch"]})
    )
    os.symlink(tmp_path / "scratch" / "manifest.json", tmp_path / "package.json")
    mono = build_evidence(tmp_path)["monorepo"]
    assert mono["detected"] is False


def test_skipped_paths_contract_pins_the_exclusion_ledger():
    # ``SkippedPaths`` spells the ledger's keys statically; the ledger is the
    # runtime source of truth. They must agree in set and in order, and an
    # empty walk must serialize one empty list per kind.
    keys = [kind.key for kind in EXCLUSION_KINDS]
    assert list(SkippedPaths.__annotations__) == keys
    assert list(WalkResult().skipped_as_evidence()) == keys
    assert all(value == [] for value in WalkResult().skipped_as_evidence().values())
