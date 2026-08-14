"""Skill/engine interface: the evidence fields the skill's protocol references
must actually exist in built evidence — schema drift here silently breaks the
skill's grounding."""

from pathlib import Path

from glossarize.evidence import _GIT_FRESHNESS_STATUS_ARGS, build_evidence

SKILL = Path(__file__).resolve().parents[1] / "skill" / "SKILL.md"


def test_skill_exists_with_evidence_protocol():
    text = SKILL.read_text()
    assert "glossarize-out/evidence.json" in text
    assert "monorepo" in text
    assert "stale" in text.lower()


def test_distribution_skill_copy_is_declared_from_the_canonical_source():
    pyproject = (SKILL.parents[1] / "pyproject.toml").read_text()
    assert '"skill/SKILL.md" = "glossarize/_skill/SKILL.md"' in pyproject


def test_skill_freshness_uses_the_engine_output_boundary():
    text = SKILL.read_text()
    for fragment in (
        "--porcelain=v1",
        "--untracked-files=all",
        "--no-renames",
        ":(exclude)glossarize-out",
        ":(exclude)glossarize-out/**",
    ):
        assert fragment in _GIT_FRESHNESS_STATUS_ARGS
        assert fragment in text
    assert (
        "Never edit the target repository's `.gitignore`"
        in " ".join(text.split())
    )


def test_skill_glossary_protocol_matches_engine():
    from glossarize.glossary import SCOPE_PATHS_KEY, STATUSES

    text = SKILL.read_text()
    assert "glossarize-out/glossary.json" in text
    assert "resume" in text.lower() and "restart" in text.lower()
    for status in STATUSES:  # every engine status is defined for the skill
        assert f"`{status}`" in text, status
    assert f"`scope.{SCOPE_PATHS_KEY}`" in text
    assert "Aliases inherit" in text
    assert "disjoint path scope" in text


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
    assert evidence["vocabulary"]["normalization"]["parser_backed"] is False
    assert "`vocabulary.normalization`" in text
    assert "monorepo.detected" in text
    assert {"detected", "reasons", "sub_roots"} <= evidence["monorepo"].keys()
    assert evidence["configuration"]["present"] is False
    assert "`configuration`" in text
    assert evidence["terminology"]["scope"]["roles"] == ["production"]
    assert "`terminology.scope`" in text
    assert evidence["files"]["code"][0]["role"] == "production"
    assert "`files[*].role`" in text
    assert evidence["skipped"]["corpus_budget"]["complete"] is True
    assert "`skipped.corpus_budget.complete`" in text
    assert "`walk_remainder.exact`" in text
    structural = evidence["structural_groups"]
    assert {"present", "available", "warnings"} <= structural.keys()
    for field in (
        "structural_groups.present",
        "structural_groups.available",
        "structural_groups.freshness",
    ):
        assert field in text
