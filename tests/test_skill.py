"""Skill/engine interface: the CLI context fields named by the protocol must
exist, and the skill must never bypass that boundary for artifact reads."""

import json
import re
from pathlib import Path

from glossabet.agent_context import (
    AGENT_CONTEXT_SCHEMA_VERSION,
    build_agent_context,
)
from glossabet.evidence import build_evidence
from glossabet.glossary import save_glossary
from glossabet.repository_glossary import repository_glossary_section

SKILL = Path(__file__).resolve().parents[1] / "skill" / "SKILL.md"

# The skill's H2 sections, in protocol order. Step 4½ sits between Step 4
# and Step 5 by design (the baseline is proposed before GLOSSARY.md is read),
# Step 7 is the last step, and Principles closes the document.
SECTION_ORDER = [
    "Audience — write for regulars",
    "Stance (read this first)",
    "Ambient vocabulary is read-only",
    "Three artifacts, kept separate",
    "Step 0 — Ground through the engine boundary",
    "Step 1 — Scan the repo from its root",
    "Step 2 — Infer the house register",
    "Step 3 — Decide what warrants a name",
    "Step 4 — Propose three ranked names per thing",
    "Step 4½ — Only now, read the repository's `GLOSSARY.md` and reconcile",
    "Step 5 — Brainstorm to a decision, with the user",
    "Step 6 — Finalize (only when asked)",
    "Step 7 — Write or refresh `GLOSSABET.md`",
    "Principles",
]


def test_skill_exists_with_cli_context_protocol():
    text = SKILL.read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    assert "glossabet inspect ." in text
    assert (
        f"`context_schema_version` other than `{AGENT_CONTEXT_SCHEMA_VERSION}`"
        in normalized
    )


def test_skill_sections_are_in_protocol_order():
    text = SKILL.read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
    assert headings == SECTION_ORDER
    # Every step keeps its number: renumbering silently breaks the cross-
    # references the rest of the skill (and the harness prompt) make.
    steps = [h.split(" — ")[0] for h in headings if h.startswith("Step ")]
    assert steps == ["Step 0", "Step 1", "Step 2", "Step 3", "Step 4",
                     "Step 4½", "Step 5", "Step 6", "Step 7"]
    # The Step 0 sub-sections the harness scenarios key on still exist.
    assert "### Monorepo alert" in text
    assert "### Which glossary state you are in (read both channels)" in text


def _maximal_context(tmp_path):
    """A lean agent context built over a fixture that fills every optional
    channel: structured glossary, root GLOSSARY.md, and a Graphify graph."""
    (tmp_path / "a.py").write_text("payment_service = 1\npayment_worker = 2\n")
    (tmp_path / "GLOSSARY.md").write_text("# Glossary\n\n- Payment Service — x\n")
    gout = tmp_path / "graphify-out"
    gout.mkdir()
    (gout / "graph.json").write_text(json.dumps({
        "nodes": [{"id": 1, "label": "PaymentFlow", "community": 0},
                  {"id": 2, "label": "PaymentWorker", "community": 0}],
        "edges": [{"source": 1, "target": 2}],
    }))
    glossary = {"schema_version": 1, "concepts": [{
        "id": "payment-service", "term": "Payment Service",
        "definition": "d", "status": "canonical",
        "scope": {"path_prefixes": ["billing"]},
    }]}
    save_glossary(tmp_path, glossary)
    evidence = build_evidence(tmp_path)
    return build_agent_context(
        evidence, glossary,
        repository_glossary=repository_glossary_section(tmp_path, evidence, glossary),
    )


def _resolves(node, parts) -> bool:
    if not parts:
        return True
    head, rest = parts[0], parts[1:]
    if head == "[*]":
        # ``files[*]`` means the entries of the ``code``/``docs`` collections
        # under ``files``: a list, or a mapping of lists.
        members = node if isinstance(node, list) else (
            [x for v in node.values() for x in (v if isinstance(v, list) else [])]
            if isinstance(node, dict) else []
        )
        return any(_resolves(x, rest) for x in members)
    return isinstance(node, dict) and head in node and _resolves(node[head], rest)


def _resolves_anywhere(node, parts) -> bool:
    if _resolves(node, parts):
        return True
    children = node.values() if isinstance(node, dict) else (
        node if isinstance(node, list) else ())
    return any(_resolves_anywhere(child, parts) for child in children)


def test_every_dotted_field_the_skill_names_exists_in_a_real_context(tmp_path):
    # Every backticked dotted path in the skill (``coverage.corpus.complete``,
    # ``files[*].role``, ``walk_remainder.exact``, ...) must resolve in a
    # context the engine actually emits — at the root, or as a sub-path
    # somewhere in the tree when the skill spells it relative to a section it
    # has already introduced. A renamed engine field can no longer leave the
    # skill pointing at nothing.
    text = SKILL.read_text(encoding="utf-8")
    refs = sorted(set(re.findall(
        r"`([a-z_]+(?:\[\*\]|\.[a-z_]+)+)`", text
    )))
    refs = [ref for ref in refs if not ref.endswith(".json")]  # file names
    assert len(refs) >= 20  # the protocol names many fields; a shrink is news
    context = _maximal_context(tmp_path)
    missing = []
    for ref in refs:
        parts = [p for p in re.split(r"\.|(\[\*\])", ref) if p]
        if not _resolves_anywhere(context, parts):
            missing.append(ref)
    assert not missing, missing


def test_distribution_skill_copy_is_declared_from_the_canonical_source():
    pyproject = (SKILL.parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert '"skill/SKILL.md" = "glossabet/_skill/SKILL.md"' in pyproject


def test_skill_requires_the_engine_boundary_without_artifact_fallback():
    text = SKILL.read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    assert "Never open, read, search, or parse Glossabet's repository JSON artifacts yourself" in normalized
    assert "Do not replace a failed command with recursive repository reading" in normalized
    assert "fall back to direct repository reading" not in normalized
    assert "glossabet save ." in text
    assert "Never write, patch, or open `glossabet-out/glossary.json` yourself" in normalized


def test_skill_keeps_ambient_vocabulary_read_only_and_human_gated():
    text = SKILL.read_text(encoding="utf-8")
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

    text = SKILL.read_text(encoding="utf-8")
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
    text = SKILL.read_text(encoding="utf-8")
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
        REASON_LISTING_UNCONFIRMED,
        REASON_SYMLINK_SENSITIVE,
        REASON_UNREADABLE,
        discover_repository_glossary,
    )

    text = SKILL.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    # Every field the skill names exists in the engine's section.
    (tmp_path / "GLOSSARY.md").write_text("# Glossary\n")
    section = discover_repository_glossary(tmp_path)
    for field in ("present", "path", "readable", "symlink", "bytes", "sha256"):
        assert field in section
        assert f"`{field}`" in text
    assert "`nested_ignored`" in text
    assert "`reason`" in text
    from glossabet.repository_glossary import repository_glossary_divergence

    divergence = repository_glossary_divergence(
        {"schema_version": 1, "concepts": []}, b""
    )
    assert "`repository_glossary.divergence`" in text
    for field in ("canonical_missing_from_markdown", "superseded_terms_still_present"):
        assert field in divergence
        assert f"`{field}`" in text
    assert "`complete: false`" in text
    for reason in (
        REASON_SYMLINK_ESCAPES,
        REASON_SYMLINK_SENSITIVE,
        REASON_NOT_REGULAR,
        REASON_OVERSIZED,
        REASON_UNREADABLE,
        REASON_LISTING_UNCONFIRMED,
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


def test_skill_report_protocol_keeps_the_three_artifacts_separate():
    """Phase 34: GLOSSABET.md is the skill's derived vocabulary-health report —
    written at Step 7 (finalize, or on request), never opened during the
    baseline steps, refreshed rather than appended, with proposals never
    worded as canonical, empty sections omitted, and the same three-artifact
    model the engine enforces (excluded from evidence at any depth, excluded
    from freshness at the root, GLOSSARY.md still visible to freshness)."""
    from glossabet.artifacts import REPORT_FILE

    text = SKILL.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "## Three artifacts, kept separate" in text
    assert "## Step 7 — Write or refresh `GLOSSABET.md`" in text
    assert f"`{REPORT_FILE}`" in text
    for phrase in (
        "never the canonical glossary",
        "Do not open `GLOSSABET.md` during Steps 0–5",
        "Never write it during Steps 0–5 unasked",
        "**Refresh, don't append.**",
        "omit any section that would be empty",
        "A proposal's presence in the report is not human approval",
        "regenerating the root `GLOSSABET.md` does not make evidence stale",
        "a `GLOSSARY.md` change remains visible repository state",
        "never make a reader consult `GLOSSABET.md` merely to learn a term",
        "put those findings in `GLOSSABET.md` (Step 7)",
        "never only under `glossabet-out/`",
    ):
        assert phrase in normalized, phrase
    for heading in (
        "## Vocabulary health", "## Glossary alignment",
        "## Unnamed or weakly named concepts", "## Overloads and collisions",
        "## Synonyms and aliases", "## Drift", "## Structural alignment",
        "## Proposed changes", "## Open questions",
        "## Coverage and limitations",
    ):
        assert f"`{heading}`" in text, heading
    # Statuses are kept distinct in the report, not collapsed.
    assert "suspected synonym · confirmed alias · discouraged alias · deprecated term" in normalized
