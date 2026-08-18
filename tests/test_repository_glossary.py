"""A repository's own root GLOSSARY.md is a separate, safely discovered
input: never lexical evidence, never Glossabet's structured state, and
never silently absent when it merely could not be read."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from glossabet.cli import main
from glossabet.analysis.evidence import build_evidence
from glossabet.glossary.store import save_glossary
from glossabet.glossary import repository_glossary as repository_glossary_module
from glossabet.glossary.repository_glossary import (
    MAX_DIVERGENCE_TERMS,
    MAX_DIVERGENCE_TEXT_CHARS,
    MAX_REPOSITORY_GLOSSARY_BYTES,
    discover_repository_glossary,
    repository_glossary_divergence,
)


def _inspect(tmp_path, capsys) -> dict:
    assert main(["inspect", str(tmp_path), "--no-graphify"]) == 0
    return json.loads(capsys.readouterr().out)


def _code(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text(
        "payment_service = 1\nledger_batch = 2\n"
    )
    (tmp_path / "README.md").write_text("# Service\nA payment service.\n")


# --- evidence isolation ---------------------------------------------------


def test_glossary_markdown_never_enters_lexical_evidence(tmp_path):
    _code(tmp_path)
    baseline = build_evidence(tmp_path, cache=False)

    (tmp_path / "GLOSSARY.md").write_text(
        "# Glossary\n\n" + "zorblattification is the canonical term.\n" * 200
    )
    with_glossary = build_evidence(tmp_path, cache=False)

    assert with_glossary["vocabulary"] == baseline["vocabulary"]
    assert with_glossary["terminology"] == baseline["terminology"]
    assert with_glossary["naming_candidates"] == baseline["naming_candidates"]
    assert with_glossary["files"] == baseline["files"]
    assert with_glossary["totals"] == baseline["totals"]
    assert with_glossary["skipped"]["self_glossaries"] == ["GLOSSARY.md"]
    assert baseline["skipped"]["self_glossaries"] == []
    dumped = json.dumps(with_glossary)
    assert "zorblattification" not in dumped

    (tmp_path / "GLOSSARY.md").write_text("# Glossary\n\nchanged entirely\n")
    changed = build_evidence(tmp_path, cache=False)
    assert changed["vocabulary"] == baseline["vocabulary"]
    assert changed["naming_candidates"] == baseline["naming_candidates"]


def test_nested_glossaries_are_excluded_and_reported(tmp_path):
    _code(tmp_path)
    (tmp_path / "GLOSSARY.md").write_text("root\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "GLOSSARY.md").write_text("nested\n")
    (tmp_path / "pkg" / "mod.py").write_text("x = 1\n")

    evidence = build_evidence(tmp_path, cache=False)

    assert evidence["skipped"]["self_glossaries"] == [
        "GLOSSARY.md",
        "pkg/GLOSSARY.md",
    ]
    assert "pkg/GLOSSARY.md" not in json.dumps(evidence["files"])


def test_scan_summary_names_the_self_glossary_exclusion(tmp_path, capsys):
    _code(tmp_path)
    (tmp_path / "GLOSSARY.md").write_text("root\n")

    assert main(["scan", str(tmp_path), "--no-graphify"]) == 0

    err = capsys.readouterr().err
    assert "excluded 1 GLOSSARY.md file(s) from lexical evidence" in err


# --- the four glossary states through inspect -----------------------------


def _ledger_glossary() -> dict:
    return {
        "schema_version": 1,
        "concepts": [
            {
                "id": "ledger-batch",
                "term": "Ledger batch",
                "definition": "A settled group.",
                "status": "canonical",
            }
        ],
    }


def test_no_glossary_reports_absent_and_nothing_else_changes(tmp_path, capsys):
    _code(tmp_path)
    context = _inspect(tmp_path, capsys)
    assert context["glossary"] == {"present": False}
    assert context["repository_glossary"] == {
        "present": False,
        "nested_ignored": [],
    }


def test_markdown_only_is_distinct_from_none_and_from_json_only(tmp_path, capsys):
    _code(tmp_path)
    payload = b"# Glossary\n\n**Ledger batch** \xe2\x80\x94 a settled group.\n"
    (tmp_path / "GLOSSARY.md").write_bytes(payload)

    context = _inspect(tmp_path, capsys)

    assert context["glossary"] == {"present": False}
    section = context["repository_glossary"]
    assert section == {
        "present": True,
        "path": "GLOSSARY.md",
        "readable": True,
        "symlink": False,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "nested_ignored": [],
    }
    # Metadata only: the Markdown's words never reach the context.
    assert "settled group" not in json.dumps(context)


def test_json_only_leaves_repository_glossary_absent(tmp_path, capsys):
    _code(tmp_path)
    save_glossary(tmp_path, _ledger_glossary())
    context = _inspect(tmp_path, capsys)
    assert context["glossary"]["present"] is True
    assert context["repository_glossary"]["present"] is False


def test_both_forms_are_surfaced_distinctly(tmp_path, capsys):
    _code(tmp_path)
    (tmp_path / "GLOSSARY.md").write_text("# Glossary\n")
    save_glossary(tmp_path, _ledger_glossary())
    context = _inspect(tmp_path, capsys)
    assert context["glossary"]["present"] is True
    assert context["glossary"]["concepts"][0]["id"] == "ledger-batch"
    assert context["repository_glossary"]["present"] is True
    assert context["repository_glossary"]["readable"] is True
    assert "concepts" not in context["repository_glossary"]


def test_vocabulary_section_is_byte_identical_with_and_without_markdown(
    tmp_path, capsys
):
    _code(tmp_path)
    without = _inspect(tmp_path, capsys)
    (tmp_path / "GLOSSARY.md").write_text("payment payment payment ledger\n")
    with_md = _inspect(tmp_path, capsys)
    for key in ("vocabulary", "terminology", "naming_candidates", "files"):
        assert json.dumps(with_md[key]) == json.dumps(without[key])


def test_repository_glossary_section_is_deterministic(tmp_path, capsys):
    _code(tmp_path)
    (tmp_path / "GLOSSARY.md").write_text("# Glossary\n")
    first = _inspect(tmp_path, capsys)["repository_glossary"]
    second = _inspect(tmp_path, capsys)["repository_glossary"]
    assert first == second


# --- safety: unreadable is never absent -----------------------------------


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_escaping_symlink_is_present_but_never_read(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "GLOSSARY.md"
    secret.write_text("outside content\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    os.symlink(secret, repo / "GLOSSARY.md")

    section = discover_repository_glossary(repo)

    assert section["present"] is True
    assert section["readable"] is False
    assert section["reason"] == "symlink-escapes-repository"
    assert "sha256" not in section
    assert "bytes" not in section


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_confined_symlink_is_followed(tmp_path):
    (tmp_path / "docs").mkdir()
    target = tmp_path / "docs" / "vocab.md"
    target.write_bytes(b"# Vocab\n")
    os.symlink(target, tmp_path / "GLOSSARY.md")

    section = discover_repository_glossary(tmp_path)

    assert section["readable"] is True
    assert section["sha256"] == hashlib.sha256(b"# Vocab\n").hexdigest()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_dangling_symlink_is_present_but_not_a_regular_file(tmp_path):
    os.symlink(tmp_path / "missing.md", tmp_path / "GLOSSARY.md")
    section = discover_repository_glossary(tmp_path)
    assert section["present"] is True
    assert section["readable"] is False
    assert section["reason"] == "not-a-regular-file"


def test_directory_named_glossary_is_present_but_not_readable(tmp_path):
    (tmp_path / "GLOSSARY.md").mkdir()
    section = discover_repository_glossary(tmp_path)
    assert section == {
        "present": True,
        "path": "GLOSSARY.md",
        "readable": False,
        "reason": "not-a-regular-file",
    }


def test_oversized_glossary_is_reported_never_absent(tmp_path, capsys):
    _code(tmp_path)
    (tmp_path / "GLOSSARY.md").write_bytes(
        b"a" * (MAX_REPOSITORY_GLOSSARY_BYTES + 1)
    )

    section = _inspect(tmp_path, capsys)["repository_glossary"]

    assert section["present"] is True
    assert section["readable"] is False
    assert section["reason"] == "oversized"
    assert section["bytes"] == MAX_REPOSITORY_GLOSSARY_BYTES + 1
    assert "sha256" not in section


def test_exactly_at_the_bound_is_read_completely(tmp_path):
    payload = b"a" * MAX_REPOSITORY_GLOSSARY_BYTES
    (tmp_path / "GLOSSARY.md").write_bytes(payload)
    section = discover_repository_glossary(tmp_path)
    assert section["readable"] is True
    assert section["bytes"] == MAX_REPOSITORY_GLOSSARY_BYTES


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics")
def test_permission_denied_is_unreadable_not_absent(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root bypasses file permissions")
    path = tmp_path / "GLOSSARY.md"
    path.write_text("# Glossary\n")
    path.chmod(0)
    try:
        section = discover_repository_glossary(tmp_path)
    finally:
        path.chmod(0o644)
    assert section["present"] is True
    assert section["readable"] is False
    assert section["reason"] == "unreadable"


# --- scan root ownership ---------------------------------------------------


def test_exact_scan_root_owns_its_glossary(tmp_path, capsys):
    (tmp_path / "GLOSSARY.md").write_bytes(b"root glossary\n")
    sub = tmp_path / "packages" / "api"
    sub.mkdir(parents=True)
    (sub / "GLOSSARY.md").write_bytes(b"api glossary\n")
    (sub / "api.py").write_text("api_handler = 1\n")
    (tmp_path / "top.py").write_text("top_level = 1\n")

    whole = _inspect(tmp_path, capsys)["repository_glossary"]
    assert whole["sha256"] == hashlib.sha256(b"root glossary\n").hexdigest()
    assert whole["nested_ignored"] == ["packages/api/GLOSSARY.md"]

    subproject = _inspect(sub, capsys)["repository_glossary"]
    assert subproject["sha256"] == hashlib.sha256(b"api glossary\n").hexdigest()
    assert subproject["nested_ignored"] == []


# --- Phase 32: deterministic managed-mode term-presence check -------------


def _glossary_with_alias() -> dict:
    return {
        "schema_version": 1,
        "concepts": [
            {
                "id": "ledger-batch",
                "term": "Ledger Batch",
                "definition": "A settled group.",
                "status": "canonical",
                "aliases": [
                    {"term": "settlement bundle", "status": "deprecated"},
                ],
            },
            {
                "id": "payment",
                "term": "Payment",
                "definition": "An attempt to collect money.",
                "status": "canonical",
            },
            {
                "id": "gateway-route",
                "term": "Gateway Route",
                "definition": "Still open.",
                "status": "proposed",
            },
        ],
    }


def test_divergence_reports_missing_canonical_and_superseded_terms():
    text = (
        "# Glossary\n\n**Settlement bundle** — the group we settle.\n"
        "Payments are attempts to collect money.\n"
    ).encode("utf-8")

    result = repository_glossary_divergence(_glossary_with_alias(), text)

    # "Payment" is present (leniently, inside "Payments"); "Ledger Batch" is
    # not, and its deprecated alias still leads. The proposed concept is
    # not a settled decision and is never checked.
    assert result["canonical_missing_from_markdown"] == ["Ledger Batch"]
    assert result["superseded_terms_still_present"] == [
        {
            "concept": "ledger-batch",
            "term": "settlement bundle",
            "status": "deprecated",
            "canonical_term": "Ledger Batch",
        }
    ]
    assert result["checked_terms"] == 3
    assert result["complete"] is True


def test_divergence_is_clean_when_every_settled_term_is_present():
    text = "Ledger batch; settlement bundle (old name); payment.\n".encode()
    result = repository_glossary_divergence(_glossary_with_alias(), text)
    assert result["canonical_missing_from_markdown"] == []
    # The alias appears, but so does the canonical term: not superseded.
    assert result["superseded_terms_still_present"] == []


def test_divergence_folds_unicode_like_the_identifier_contract():
    glossary = {
        "schema_version": 1,
        "concepts": [
            {
                "id": "strasse",
                "term": "Straße",
                "definition": "d",
                "status": "canonical",
            },
            {
                "id": "ligature",
                "term": "ﬁle handle",  # U+FB01 ligature, NFKC → "fi"
                "definition": "d",
                "status": "canonical",
            },
        ],
    }
    text = "STRASSE and the file handle\n".encode("utf-8")
    result = repository_glossary_divergence(glossary, text)
    assert result["canonical_missing_from_markdown"] == []


def test_divergence_caps_its_work_and_says_so():
    glossary = {
        "schema_version": 1,
        "concepts": [
            {
                "id": f"c{i}",
                "term": f"Term{i}",
                "definition": "d",
                "status": "canonical",
            }
            for i in range(MAX_DIVERGENCE_TERMS + 5)
        ],
    }
    result = repository_glossary_divergence(glossary, b"nothing\n")
    assert result["checked_terms"] == MAX_DIVERGENCE_TERMS
    assert result["skipped_terms"] == 5
    assert result["complete"] is False
    assert len(result["canonical_missing_from_markdown"]) == MAX_DIVERGENCE_TERMS


def test_inspect_carries_divergence_only_when_both_exist_and_readable(
    tmp_path, capsys
):
    _code(tmp_path)
    save_glossary(tmp_path, _glossary_with_alias())

    # Structured only: no repository glossary, no divergence.
    section = _inspect(tmp_path, capsys)["repository_glossary"]
    assert "divergence" not in section

    (tmp_path / "GLOSSARY.md").write_text("Payments only.\n")
    section = _inspect(tmp_path, capsys)["repository_glossary"]
    assert section["divergence"]["canonical_missing_from_markdown"] == [
        "Ledger Batch"
    ]

    # Unreadable Markdown: no divergence key at all — never an empty,
    # clean-looking result.
    (tmp_path / "GLOSSARY.md").unlink()
    (tmp_path / "GLOSSARY.md").mkdir()
    section = _inspect(tmp_path, capsys)["repository_glossary"]
    assert section["readable"] is False
    assert "divergence" not in section


def test_markdown_only_has_no_divergence(tmp_path, capsys):
    _code(tmp_path)
    (tmp_path / "GLOSSARY.md").write_text("# Glossary\n")
    section = _inspect(tmp_path, capsys)["repository_glossary"]
    assert section["readable"] is True
    assert "divergence" not in section


def test_validate_reports_repository_glossary_divergence(tmp_path, capsys):
    _code(tmp_path)
    save_glossary(tmp_path, _glossary_with_alias())
    (tmp_path / "GLOSSARY.md").write_text(
        "**Settlement bundle** — the group.\nPayments.\n"
    )

    assert main(["validate", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "repository GLOSSARY.md divergence" in out
    assert "canonical term Ledger Batch does not appear in GLOSSARY.md" in out
    assert (
        "deprecated term settlement bundle appears in GLOSSARY.md while its "
        "canonical term Ledger Batch does not"
    ) in out

    validation = json.loads(
        (tmp_path / "glossabet-out" / "validation.json").read_text(encoding="utf-8")
    )
    assert validation["schema_version"] == 8
    section = validation["repository_glossary"]
    assert section["readable"] is True
    assert section["divergence"]["canonical_missing_from_markdown"] == [
        "Ledger Batch"
    ]


def test_validate_names_an_unreadable_repository_glossary(tmp_path, capsys):
    _code(tmp_path)
    save_glossary(tmp_path, _glossary_with_alias())
    (tmp_path / "GLOSSARY.md").mkdir()

    assert main(["validate", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "present but not read (not-a-regular-file)" in out
    assert "divergence" not in out


def test_validate_is_quiet_when_markdown_and_state_agree(tmp_path, capsys):
    _code(tmp_path)
    save_glossary(tmp_path, _glossary_with_alias())
    (tmp_path / "GLOSSARY.md").write_text("Ledger batch and payment.\n")

    assert main(["validate", str(tmp_path)]) == 0
    assert "GLOSSARY.md" not in capsys.readouterr().out


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_symlink_to_in_repo_sensitive_file_is_never_declared_readable(tmp_path):
    (tmp_path / ".env").write_text("SECRET_TOKEN=abc123\n")
    os.symlink(tmp_path / ".env", tmp_path / "GLOSSARY.md")

    section = discover_repository_glossary(tmp_path)

    assert section["present"] is True
    assert section["readable"] is False
    assert section["reason"] == "symlink-to-sensitive-file"
    assert "sha256" not in section

    # Sibling: a link to an in-repo key file, and a chained link.
    (tmp_path / "GLOSSARY.md").unlink()
    (tmp_path / "server.key").write_text("k\n")
    os.symlink(tmp_path / "server.key", tmp_path / "GLOSSARY.md")
    assert discover_repository_glossary(tmp_path)["reason"] == "symlink-to-sensitive-file"
    (tmp_path / "GLOSSARY.md").unlink()
    os.symlink(tmp_path / ".env", tmp_path / "hop.md")
    os.symlink(tmp_path / "hop.md", tmp_path / "GLOSSARY.md")
    assert discover_repository_glossary(tmp_path)["reason"] == "symlink-to-sensitive-file"


def test_divergence_matches_terms_across_line_wraps_and_whitespace_runs():
    glossary = {
        "schema_version": 1,
        "concepts": [
            {
                "id": "ledger-batch",
                "term": "Ledger Batch",
                "definition": "d",
                "status": "canonical",
                "aliases": [
                    {"term": "settlement bundle", "status": "deprecated"},
                ],
            },
            {
                "id": "gw",
                "term": "Gateway  Route",  # doubled space in the term itself
                "definition": "d",
                "status": "canonical",
            },
        ],
    }
    wrapped = (
        "Our Ledger\nBatch is the unit; the old settlement\n\tbundle name is "
        "gone. The gateway route\nremains.\n"
    ).encode("utf-8")

    result = repository_glossary_divergence(glossary, wrapped)

    assert result["canonical_missing_from_markdown"] == []
    # The alias is present too, but so is the canonical term: not superseded.
    assert result["superseded_terms_still_present"] == []
    # And a wrapped *alias* still counts as present when the canonical is absent.
    only_alias = b"the old settlement\nbundle name\n"
    result = repository_glossary_divergence(glossary, only_alias)
    assert result["superseded_terms_still_present"][0]["term"] == "settlement bundle"


def test_only_the_exactly_named_entry_is_the_repository_glossary(tmp_path):
    """Pins the invariant on every platform: on a case-insensitive filesystem
    a path lookup for GLOSSARY.md would find glossary.md, but the scanner's
    exclusion is by exact entry name, so discovery must be too — otherwise
    the same file would be both "the repository glossary" and ordinary
    lexical evidence."""
    (tmp_path / "glossary.md").write_bytes(b"# lowercase\n")
    assert discover_repository_glossary(tmp_path) == {"present": False}
    evidence = build_evidence(tmp_path, cache=False)
    assert evidence["skipped"]["self_glossaries"] == []

    # On a case-insensitive filesystem writing GLOSSARY.md would reopen
    # glossary.md and keep its name; remove it so the new entry's name is
    # exact everywhere. Bytes, not text: Windows text mode writes CRLF and
    # the digest below is of the exact bytes.
    (tmp_path / "glossary.md").unlink()
    (tmp_path / "GLOSSARY.md").write_bytes(b"# exact\n")
    section = discover_repository_glossary(tmp_path)
    assert section["readable"] is True
    assert section["sha256"] == hashlib.sha256(b"# exact\n").hexdigest()


# --- audit hardening (2026-08-17) -----------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_confined_symlink_is_flagged_so_the_skill_never_writes_through_it(tmp_path):
    (tmp_path / "src").mkdir()
    target = tmp_path / "src" / "app.py"
    target.write_bytes(b"print('app')\n")
    os.symlink(target, tmp_path / "GLOSSARY.md")

    section = discover_repository_glossary(tmp_path)

    assert section["readable"] is True
    assert section["symlink"] is True

    (tmp_path / "GLOSSARY.md").unlink()
    (tmp_path / "GLOSSARY.md").write_bytes(b"# real\n")
    assert discover_repository_glossary(tmp_path)["symlink"] is False


def test_divergence_guard_fires_on_nfkc_expansion_before_any_search(monkeypatch):
    # U+FDFA expands to 18 code points under NFKC: a 2 MB document becomes
    # ~12 M characters. The guard must trip before a single term is searched.
    bomb = ("\ufdfa" * (MAX_REPOSITORY_GLOSSARY_BYTES // 3)).encode("utf-8")
    assert len(bomb) <= MAX_REPOSITORY_GLOSSARY_BYTES
    glossary = {
        "schema_version": 1,
        "concepts": [
            {
                "id": "a",
                "term": "Alpha",
                "definition": "d",
                "status": "canonical",
                "aliases": [{"term": "old alpha", "status": "deprecated"}],
            },
            {"id": "b", "term": "Beta", "definition": "d", "status": "canonical"},
        ],
    }
    result = repository_glossary_divergence(glossary, bomb)

    assert result == {
        "canonical_missing_from_markdown": [],
        "superseded_terms_still_present": [],
        "checked_terms": 0,
        "skipped_terms": 3,
        "complete": False,
        "reason": "normalized-text-exceeds-bound",
        "term_cap": MAX_DIVERGENCE_TERMS,
        "text_cap": MAX_DIVERGENCE_TEXT_CHARS,
    }
    # Sibling: exactly at the bound is still searched; one past is not.
    at_bound = ("a" * MAX_DIVERGENCE_TEXT_CHARS).encode("utf-8")
    assert repository_glossary_divergence(glossary, at_bound)["checked_terms"] == 3
    past = ("a" * (MAX_DIVERGENCE_TEXT_CHARS + 1)).encode("utf-8")
    assert repository_glossary_divergence(glossary, past)["reason"] == (
        "normalized-text-exceeds-bound"
    )


def test_divergence_worst_case_is_bounded_in_time():
    import time

    text = b"a" * MAX_REPOSITORY_GLOSSARY_BYTES
    glossary = {
        "schema_version": 1,
        "concepts": [
            {
                "id": f"c{i:05d}",
                "term": "a" * 1000 + f"b{i:04d}",
                "definition": "d",
                "status": "canonical",
            }
            for i in range(MAX_DIVERGENCE_TERMS + 10)
        ],
    }
    started = time.perf_counter()
    result = repository_glossary_divergence(glossary, text)
    elapsed = time.perf_counter() - started
    assert result["checked_terms"] == MAX_DIVERGENCE_TERMS
    assert result["complete"] is False
    # Generous ceiling for slow CI hosts; the pre-hardening cost was ~4.3 s
    # for four times as many terms, i.e. this path is now ~1 s locally.
    assert elapsed < 10


def test_presence_confirmation_never_materializes_the_root_listing(
    tmp_path, monkeypatch
):
    (tmp_path / "GLOSSARY.md").write_text("# g\n")
    for index in range(5):
        (tmp_path / f"file{index}.py").write_text("x = 1\n")

    # Confirmed by bounded scandir iteration, not os.listdir.
    monkeypatch.setattr(
        repository_glossary_module.os,
        "listdir",
        lambda *_a, **_k: pytest.fail("os.listdir must not be used"),
    )
    assert discover_repository_glossary(tmp_path)["present"] is True

    # Something is there (lexists) but its exact name could not be confirmed
    # within the cap: never "absent" — a false absence claim is the one
    # failure this channel must not produce.
    import glossabet.corpus.scanner as scanner_module

    monkeypatch.setattr(scanner_module, "MAX_WALK_ENTRIES", 0)
    assert discover_repository_glossary(tmp_path) == {
        "present": True,
        "path": "GLOSSARY.md",
        "readable": False,
        "reason": "root-listing-unconfirmed",
    }
    # Sibling: the root cannot be listed at all.
    monkeypatch.setattr(scanner_module, "MAX_WALK_ENTRIES", 100)

    def _unlistable(*_a, **_k):
        raise PermissionError("listing denied")

    monkeypatch.setattr(repository_glossary_module.os, "scandir", _unlistable)
    assert discover_repository_glossary(tmp_path)["reason"] == "root-listing-unconfirmed"
    # And truly absent stays absent without any listing at all.
    (tmp_path / "GLOSSARY.md").unlink()
    assert discover_repository_glossary(tmp_path) == {"present": False}


def test_validate_names_the_text_bound_when_the_guard_fires(
    tmp_path, capsys, monkeypatch
):
    # The real bound is proven by the unit test above; here only the printed
    # message matters, so trip the guard cheaply instead of building a 12 M
    # character document a second time.
    monkeypatch.setattr(repository_glossary_module, "MAX_DIVERGENCE_TEXT_CHARS", 8)
    _code(tmp_path)
    save_glossary(tmp_path, _glossary_with_alias())
    (tmp_path / "GLOSSARY.md").write_text("Ledger batch and payment.\n")
    assert main(["validate", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "term-presence check not run: normalized GLOSSARY.md text exceeds" in out


def test_divergence_guard_fires_before_casefold_and_collapse_allocate():
    """On the NFKC bomb, casefold reserves a 3x buffer (~170 MB) and the
    whitespace collapse allocates millions of tiny strings (~180 MB). The
    length guard must be judged right after NFKC (72 MB peak), before either
    of those steps.

    Allocation is the whole claim, so allocation is the whole assertion. A
    wall-clock bound cannot tell "the guard fired early on a slow machine"
    apart from "it fired late on a fast one" -- it measures the runner, and a
    5-second bound that held here took 55 seconds on CI's Windows hosts. The
    input is already capped at MAX_REPOSITORY_GLOSSARY_BYTES, so the work is
    bounded by construction; the peak below is what proves it stayed early."""
    import tracemalloc

    bomb = ("\ufdfa" * (MAX_REPOSITORY_GLOSSARY_BYTES // 3)).encode("utf-8")
    glossary = {
        "schema_version": 1,
        "concepts": [
            {"id": "a", "term": "Alpha", "definition": "d", "status": "canonical"}
        ],
    }
    tracemalloc.start()
    result = repository_glossary_divergence(glossary, bomb)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert result["reason"] == "normalized-text-exceeds-bound"
    # NFKC alone peaks at ~72 MB for this document; casefold or the collapse
    # would each push it past 165 MB. Generous ceiling, well under either.
    assert peak < 120_000_000, peak


def test_discovery_name_is_the_scanner_exclusion_name():
    """One name, two modules: if either spelling drifts, GLOSSARY.md would be
    excluded from evidence but not discovered (or discovered and counted)."""
    from glossabet.glossary.repository_glossary import REPOSITORY_GLOSSARY_FILE
    from glossabet.corpus.scanner import SELF_FILES

    assert SELF_FILES == frozenset({REPOSITORY_GLOSSARY_FILE})


def test_root_glossary_symlink_rule_follows_docs_but_refuses_glossabet_output(tmp_path):
    """The discovery channel exists to read GLOSSARY.md, so a confined link
    into `docs/GLOSSARY.md` (or a vendored/hidden folder) is followed; only
    escaping, sensitive, and Glossabet's-own-output targets are refused."""
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "GLOSSARY.md").write_text("# nested glossary\n")
    os.symlink(tmp_path / "docs" / "GLOSSARY.md", tmp_path / "GLOSSARY.md")
    section = discover_repository_glossary(tmp_path)
    assert section["readable"] is True and section["symlink"] is True

    for target in ("glossabet-out/notes.md", "GLOSSABET.md"):
        (tmp_path / "GLOSSARY.md").unlink()
        (tmp_path / target).parent.mkdir(exist_ok=True)
        (tmp_path / target).write_text("# derived output\n")
        os.symlink(tmp_path / target, tmp_path / "GLOSSARY.md")
        section = discover_repository_glossary(tmp_path)
        assert section["present"] is True
        assert section["readable"] is False
        assert section["reason"] == "symlink-to-excluded-content", target


def test_divergence_counts_code_cased_spellings_as_present(tmp_path):
    """`LedgerEntry`/`ledger_entry` in GLOSSARY.md is the term `Ledger Entry`
    by the engine's own compound rule; the presence check must not report it
    missing with `complete: true`."""
    (tmp_path / "ledger.py").write_text("ledger_entry = 1\n")
    (tmp_path / "GLOSSARY.md").write_text("- `LedgerEntry`: append-only record\n")
    glossary = {"schema_version": 1, "concepts": [{
        "id": "ledger-entry", "term": "Ledger Entry", "definition": "d",
        "status": "canonical",
    }]}
    save_glossary(tmp_path, glossary)
    section = repository_glossary_module.repository_glossary_section(
        tmp_path, build_evidence(tmp_path), glossary
    )
    assert section["divergence"]["canonical_missing_from_markdown"] == []
