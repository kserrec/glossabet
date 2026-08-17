"""A repository's own root GLOSSARY.md is a separate, safely discovered
input: never lexical evidence, never Glossabet's structured state, and
never silently absent when it merely could not be read."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from glossabet.cli import main
from glossabet.evidence import build_evidence
from glossabet.glossary import save_glossary
from glossabet.repository_glossary import (
    MAX_REPOSITORY_GLOSSARY_BYTES,
    discover_repository_glossary,
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
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "nested_ignored": [],
    }
    # Metadata only: the Markdown's words never reach the context.
    assert "settled group" not in json.dumps(context)


def test_json_only_leaves_repository_glossary_absent(tmp_path, capsys):
    _code(tmp_path)
    save_glossary(
        tmp_path,
        {
            "schema_version": 1,
            "concepts": [
                {
                    "id": "ledger-batch",
                    "term": "Ledger batch",
                    "definition": "A settled group.",
                    "status": "canonical",
                }
            ],
        },
    )
    context = _inspect(tmp_path, capsys)
    assert context["glossary"]["present"] is True
    assert context["repository_glossary"]["present"] is False


def test_both_forms_are_surfaced_distinctly(tmp_path, capsys):
    _code(tmp_path)
    (tmp_path / "GLOSSARY.md").write_text("# Glossary\n")
    save_glossary(
        tmp_path,
        {
            "schema_version": 1,
            "concepts": [
                {
                    "id": "ledger-batch",
                    "term": "Ledger batch",
                    "definition": "A settled group.",
                    "status": "canonical",
                }
            ],
        },
    )
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
    from glossabet.repository_glossary import repository_glossary_divergence

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
    from glossabet.repository_glossary import repository_glossary_divergence

    text = "Ledger batch; settlement bundle (old name); payment.\n".encode()
    result = repository_glossary_divergence(_glossary_with_alias(), text)
    assert result["canonical_missing_from_markdown"] == []
    # The alias appears, but so does the canonical term: not superseded.
    assert result["superseded_terms_still_present"] == []


def test_divergence_folds_unicode_like_the_identifier_contract():
    from glossabet.repository_glossary import repository_glossary_divergence

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
    from glossabet import repository_glossary as module

    glossary = {
        "schema_version": 1,
        "concepts": [
            {
                "id": f"c{i}",
                "term": f"Term{i}",
                "definition": "d",
                "status": "canonical",
            }
            for i in range(module.MAX_DIVERGENCE_TERMS + 5)
        ],
    }
    result = module.repository_glossary_divergence(glossary, b"nothing\n")
    assert result["checked_terms"] == module.MAX_DIVERGENCE_TERMS
    assert result["skipped_terms"] == 5
    assert result["complete"] is False
    assert len(result["canonical_missing_from_markdown"]) == module.MAX_DIVERGENCE_TERMS


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
        (tmp_path / "glossabet-out" / "validation.json").read_text()
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
