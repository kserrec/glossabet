"""Evidence builder: the concrete threats — ingested secrets, contaminated
evidence, nondeterminism, silent truncation, missed monorepo shape."""

import json

from glossarize.cli import main
from glossarize.evidence import Limits, build_evidence, scan_command, write_evidence


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
    gout = tmp_path / "glossarize-out"
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
    assert "contaminantword" not in blob  # glossarize-out/
    assert "noisetokenword" not in blob  # node_modules/


def test_vocabulary_normalizes_across_conventions(tmp_path):
    evidence = build_evidence(make_repo(tmp_path))
    tokens = {t["term"]: t for t in evidence["vocabulary"]["tokens"]["items"]}
    # PaymentService + charge_payment + payment_request all feed "payment".
    assert tokens["payment"]["count"] == 4
    assert tokens["payment"]["locations"][0]["path"] == "src/payment_service.py"


def test_scan_is_deterministic_including_own_output(tmp_path):
    root = make_repo(tmp_path)
    first = build_evidence(root)
    write_evidence(root, first)  # second walk sees glossarize-out/ and must ignore it
    second = build_evidence(root)
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
    assert (root / "glossarize-out" / "evidence.json").is_file()
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
    path.write_text("# café résumé naïveté\nx = 1\n")
    evidence = build_evidence(tmp_path)
    assert evidence["totals"]["code_bytes"] == path.stat().st_size
