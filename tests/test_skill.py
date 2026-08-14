"""Skill/engine interface: the evidence fields the skill's protocol references
must actually exist in built evidence — schema drift here silently breaks the
skill's grounding."""

from pathlib import Path

from glossarize.evidence import build_evidence

SKILL = Path(__file__).resolve().parents[1] / "skill" / "SKILL.md"


def test_skill_exists_with_evidence_protocol():
    text = SKILL.read_text()
    assert "glossarize-out/evidence.json" in text
    assert "monorepo" in text
    assert "stale" in text.lower()


def test_skill_glossary_protocol_matches_engine():
    from glossarize.glossary import STATUSES

    text = SKILL.read_text()
    assert "glossarize-out/glossary.json" in text
    assert "resume" in text.lower() and "restart" in text.lower()
    for status in STATUSES:  # every engine status is defined for the skill
        assert f"`{status}`" in text, status


def test_skill_referenced_fields_exist_in_evidence(tmp_path):
    (tmp_path / "a.py").write_text("payment_service = 1\n")
    evidence = build_evidence(tmp_path)
    text = SKILL.read_text()
    # Dotted paths the protocol names:
    assert evidence["repository"]["git"].keys() >= {"head", "dirty"}
    assert "repository.git.head" in text and "repository.git.dirty" in text
    # Top-level sections the protocol feeds into Steps 1-3:
    for key in ("totals", "languages", "modules", "files", "vocabulary", "monorepo"):
        assert key in evidence, key
        assert f"`{key}`" in text or f"`monorepo.{key}" in text or key in text, key
    for vocab_key in ("identifiers", "tokens", "doc_terms"):
        assert vocab_key in evidence["vocabulary"]
        assert f"vocabulary.{vocab_key}" in text
    assert "monorepo.detected" in text
    assert {"detected", "reasons", "sub_roots"} <= evidence["monorepo"].keys()
