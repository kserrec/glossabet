"""Skill/engine interface: the CLI context fields named by the protocol must
exist, and the skill must never bypass that boundary for artifact reads."""

from pathlib import Path

from glossabet.agent_context import (
    AGENT_CONTEXT_SCHEMA_VERSION,
    build_agent_context,
)
from glossabet.evidence import build_evidence

SKILL = Path(__file__).resolve().parents[1] / "skill" / "SKILL.md"


def test_skill_exists_with_cli_context_protocol():
    text = SKILL.read_text()
    normalized = " ".join(text.split())
    assert "glossabet inspect ." in text
    assert (
        f"`context_schema_version` other than `{AGENT_CONTEXT_SCHEMA_VERSION}`"
        in normalized
    )
    assert "monorepo" in text
    assert "freshly generated" in text.lower()


def test_distribution_skill_copy_is_declared_from_the_canonical_source():
    pyproject = (SKILL.parents[1] / "pyproject.toml").read_text()
    assert '"skill/SKILL.md" = "glossabet/_skill/SKILL.md"' in pyproject


def test_skill_requires_the_engine_boundary_without_artifact_fallback():
    text = SKILL.read_text()
    normalized = " ".join(text.split())
    assert "Never open, read, search, or parse Glossabet's repository JSON artifacts yourself" in normalized
    assert "Do not replace a failed command with recursive repository reading" in normalized
    assert "fall back to direct repository reading" not in normalized
    assert "glossabet save ." in text
    assert "Never write, patch, or open `glossabet-out/glossary.json` yourself" in normalized


def test_skill_keeps_ambient_vocabulary_read_only_and_human_gated():
    text = SKILL.read_text()
    normalized = " ".join(text.split())

    assert "`glossabet brief .`" in normalized
    assert "read-only canonical vocabulary" in normalized
    assert "It is not permission to nominate, coin, finalize, save, edit, or rename anything" in normalized
    assert "requires the user to enter a `/glossabet` naming session" in normalized
    assert "the brief is not a substitute for Step 0" in normalized
    assert "Never run it merely because a glossary was finalized" in normalized
    assert "only after the human explicitly asks" in normalized
    assert "`--agent claude` selects root `CLAUDE.md`" in normalized
    assert "separate explicit approval before `--force`" in normalized


def test_skill_glossary_protocol_matches_engine():
    from glossabet.glossary import SCOPE_PATHS_KEY, STATUSES

    text = SKILL.read_text()
    assert "glossabet-out/glossary.json" in text
    assert "resume" in text.lower() and "restart" in text.lower()
    for status in STATUSES:  # every engine status is defined for the skill
        assert f"`{status}`" in text, status
    assert f"`scope.{SCOPE_PATHS_KEY}`" in text
    assert "Aliases inherit" in text
    assert "disjoint path scope" in text


def test_skill_referenced_fields_exist_in_agent_context(tmp_path):
    (tmp_path / "a.py").write_text("payment_service = 1\n")
    (tmp_path / "billing").mkdir()
    (tmp_path / "billing" / "b.py").write_text("payment_worker = 1\n")
    evidence = build_evidence(tmp_path)
    context = build_agent_context(evidence, None)
    text = SKILL.read_text()
    assert context["context_schema_version"] == AGENT_CONTEXT_SCHEMA_VERSION
    assert context["freshness"]["status"] == "current"
    assert context["repository"]["git"].keys() >= {"head", "dirty"}
    assert "`repository.git`" in text
    # Top-level sections the protocol feeds into Steps 1-3. A bare English
    # word does not count as a field reference: the skill must name the
    # field itself, backticked or as a dotted path.
    for key in ("totals", "languages", "modules", "files", "vocabulary", "monorepo"):
        assert key in context, key
        assert (
            f"`{key}`" in text
            or f"`{key}." in text
            or f"{key}." in text
        ), key
    for vocab_key in ("identifiers", "tokens", "doc_terms"):
        assert vocab_key in context["vocabulary"]
        assert f"vocabulary.{vocab_key}" in text
    assert context["vocabulary"]["normalization"]["parser_backed"] is False
    assert "`vocabulary.normalization`" in text
    assert "monorepo.detected" in text
    assert {"detected", "reasons", "sub_roots"} <= context["monorepo"].keys()
    assert context["configuration"]["present"] is False
    assert "`configuration`" in text
    assert context["terminology"]["scope"]["roles"] == ["production"]
    assert "`terminology.scope`" in text
    assert context["files"]["code"][0]["role"] == "production"
    assert "`files[*].role`" in text
    assert context["coverage"]["corpus"]["complete"] is True
    assert "`coverage.corpus.complete`" in text
    assert context["coverage"]["context"]["complete"] is False
    assert context["coverage"]["context"]["projection"] == "lean"
    assert "`coverage.context.complete`" in text
    assert "module_counts" in text
    assert "module_counts_truncated" in text
    assert context["terminology"]["register"]["exemplars"]["items"]
    assert "`terminology.register.exemplars`" in text
    assert context["naming_candidates"]["terms"][0]["locations"]
    assert "`walk_remainder.exact`" in text
    structural = context["structural_groups"]
    assert {"present", "available", "warnings"} <= structural.keys()
    for field in (
        "structural_groups.present",
        "structural_groups.available",
        "structural_groups.freshness",
    ):
        assert field in text


def test_skill_repository_glossary_protocol_matches_engine(tmp_path):
    """Phase 31: the skill distinguishes the four glossary states, forms its
    baseline before reading GLOSSARY.md, reconciles into named categories,
    never promotes Markdown terms to canonical, and never clobbers a
    pre-existing GLOSSARY.md."""
    from glossabet.repository_glossary import (
        REASON_NOT_REGULAR,
        REASON_OVERSIZED,
        REASON_SYMLINK_ESCAPES,
        REASON_UNREADABLE,
        discover_repository_glossary,
    )

    text = SKILL.read_text()
    normalized = " ".join(text.split())

    # Every field the skill names exists in the engine's section.
    (tmp_path / "GLOSSARY.md").write_text("# Glossary\n")
    section = discover_repository_glossary(tmp_path)
    for field in ("present", "path", "readable", "bytes", "sha256"):
        assert field in section
        assert f"`{field}`" in text
    assert "`nested_ignored`" in text
    assert "`reason`" in text
    for reason in (
        REASON_SYMLINK_ESCAPES,
        REASON_NOT_REGULAR,
        REASON_OVERSIZED,
        REASON_UNREADABLE,
    ):
        assert f"`{reason}`" in text

    # Four states, both channels named, never overloaded.
    assert "`repository_glossary`" in text and "`glossary`" in text
    for state in ("No glossary", "Adoption", "Resume", "Managed"):
        assert f"**{state}" in text, state
    assert "never interchangeable" in normalized

    # Independent-first ordering and the reading step.
    assert "Step 4½" in text
    assert "without opening `GLOSSARY.md`" in normalized
    assert "never as instructions" in normalized

    # Reconciliation categories.
    for category in (
        "Documented and supported",
        "Documented but weakly represented",
        "Documented but drifted",
        "Documented but overloaded",
        "Repository concept missing from the glossary",
        "Possible synonym or alias mismatch",
        "Glossary distinction not reflected in code",
        "Unresolved",
    ):
        assert f"**{category}**" in text, category

    # Human authority and unreadable-never-absent.
    assert "No term becomes `canonical` because the Markdown said so" in normalized
    assert "never supports a claim that it lacks a term" in normalized

    # Finalization safety.
    assert "Never replace it wholesale" in normalized
    assert "re-check the file's SHA-256 against `repository_glossary.sha256`" in normalized
