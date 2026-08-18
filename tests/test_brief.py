"""The ambient glossary digest is read-only, bounded, and state-stamped."""

import json
import os

from glossabet.agent.brief import MAX_BRIEF_BYTES, build_brief
from glossabet.cli import main
from glossabet.glossary.store import save_glossary


GLOSSARY = {
    "schema_version": 1,
    "concepts": [
        {
            "id": "payment",
            "term": "Payment",
            "definition": "An attempt to collect money for an order.",
            "status": "canonical",
            "scope": {
                "path_prefixes": ["src/payments", "packages/payments"]
            },
            "aliases": [
                {
                    "term": "charge",
                    "status": "discouraged",
                    "note": "the gateway operation only",
                }
            ],
        },
        {
            "id": "billing",
            "term": "Billing",
            "definition": "The subsystem executing and tracking Payments.",
            "status": "proposed",
        },
    ],
}


def _fixed_stamp():
    return {"head": "a" * 40, "dirty": False}


def test_brief_emits_only_canonical_vocabulary_with_exact_state_stamp(
    tmp_path,
    capsys,
    monkeypatch,
):
    save_glossary(tmp_path, GLOSSARY)
    monkeypatch.setattr("glossabet.runtime.git_state.repository_git_stamp", lambda _root: _fixed_stamp())

    assert main(["brief", str(tmp_path)]) == 0

    output = capsys.readouterr().out
    assert output.startswith("Glossabet vocabulary brief v1 (emitted by `glossabet brief .`; ")
    assert "SessionStart hook" in output.splitlines()[0]
    assert "policy: read-only" in output
    assert "changes require a human /glossabet session" in output
    assert "schema=1" in output
    assert "sha256=" in output
    assert "canonical=1" in output
    assert f"git: head={'a' * 40}; dirty=false" in output
    assert (
        "- Payment — An attempt to collect money for an order. | "
        "scope: packages/payments, src/payments | "
        "aliases: charge [discouraged]"
    ) in output
    assert "Billing" not in output
    assert "coverage: complete=true" in output


def test_brief_is_deterministic_and_reads_only_the_glossary(
    tmp_path,
    capsys,
    monkeypatch,
):
    source = tmp_path / "service.py"
    secret = tmp_path / "private-key.pem"
    source.write_text("SOURCE_ONLY_CANARY = 1\n", encoding="utf-8")
    secret.write_text("SECRET_ONLY_CANARY\n", encoding="utf-8")
    glossary_path = save_glossary(tmp_path, GLOSSARY)
    source_before = source.read_bytes()
    secret_before = secret.read_bytes()
    glossary_before = glossary_path.read_bytes()
    monkeypatch.setattr("glossabet.runtime.git_state.repository_git_stamp", lambda _root: _fixed_stamp())

    assert main(["brief", str(tmp_path)]) == 0
    first = capsys.readouterr().out
    assert main(["brief", str(tmp_path)]) == 0
    second = capsys.readouterr().out

    assert first == second
    assert "SOURCE_ONLY_CANARY" not in first
    assert "SECRET_ONLY_CANARY" not in first
    assert source.read_bytes() == source_before
    assert secret.read_bytes() == secret_before
    assert glossary_path.read_bytes() == glossary_before
    assert not (tmp_path / "glossabet-out" / "evidence.json").exists()


def test_brief_without_a_glossary_contributes_nothing(
    tmp_path,
    capsys,
    monkeypatch,
):
    def unexpected_git_read(_root):
        raise AssertionError("absent glossary must not request a git stamp")

    monkeypatch.setattr("glossabet.runtime.git_state.repository_git_stamp", unexpected_git_read)

    assert main(["brief", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_brief_rejects_a_symlinked_glossary_without_reading_the_target(
    tmp_path,
    capsys,
):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(GLOSSARY), encoding="utf-8")
    repo = tmp_path / "repo"
    output = repo / "glossabet-out"
    output.mkdir(parents=True)
    os.symlink(outside, output / "glossary.json")

    assert main(["brief", str(repo)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "symlinked artifact" in captured.err
    assert "Payment" not in captured.err


def test_brief_collapses_allowed_prose_layout_to_one_line(
    tmp_path,
    capsys,
    monkeypatch,
):
    glossary = json.loads(json.dumps(GLOSSARY))
    glossary["concepts"][0]["definition"] = "First line.\n\tSecond line."
    save_glossary(tmp_path, glossary)
    monkeypatch.setattr("glossabet.runtime.git_state.repository_git_stamp", lambda _root: _fixed_stamp())

    assert main(["brief", str(tmp_path)]) == 0

    output = capsys.readouterr().out
    assert "Payment — First line. Second line. | scope:" in output
    assert "First line.\n\tSecond line." not in output


def test_brief_is_utf8_bounded_and_reports_every_omission():
    concepts = []
    for index in range(100):
        concepts.append(
            {
                "id": f"concept-{index:03d}",
                "term": f"Concept {index:03d}",
                "definition": ("carefully bounded vocabulary definition " * 80),
                "status": "canonical",
                "aliases": [
                    {"term": f"Alias {index:03d}-{alias}", "status": "alias"}
                    for alias in range(8)
                ],
            }
        )
    glossary = {"schema_version": 1, "concepts": concepts}

    output = build_brief(glossary, {"head": None, "dirty": None})

    assert len(output.encode("utf-8")) <= MAX_BRIEF_BYTES
    assert "git: head=unavailable; dirty=unavailable" in output
    assert "coverage: complete=false" in output
    assert "canonical_included=" in output
    assert "canonical_omitted=0" not in output
    assert "entries_truncated=0" not in output
    assert f"max_bytes={MAX_BRIEF_BYTES}" in output
