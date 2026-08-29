"""The published compatibility policy tracks its executable contracts."""

import json
from pathlib import Path

from evaluation.claude.contract import (
    HISTORY_SCHEMA_VERSION as CLAUDE_HISTORY_SCHEMA_VERSION,
)
from evaluation.claude.contract import (
    RESULT_SCHEMA_VERSION as CLAUDE_RESULT_SCHEMA_VERSION,
)
from evaluation.codex.contract import (
    HISTORY_SCHEMA_VERSION as CODEX_HISTORY_SCHEMA_VERSION,
)
from evaluation.codex.contract import (
    RESULT_SCHEMA_VERSION as CODEX_RESULT_SCHEMA_VERSION,
)
from evaluation.deterministic.contract import EVALUATION_SCHEMA_VERSION
from evaluation.reviewer.contract import PACKET_SCHEMA_VERSION, REVIEW_SCHEMA_VERSION
from glossabet.agent.agent_context_protocol import AGENT_CONTEXT_SCHEMA_VERSION
from glossabet.agent.brief import BRIEF_FORMAT_VERSION
from glossabet.agent.managed_context import MANAGED_CONTEXT_SCHEMA_VERSION
from glossabet.analysis.evidence import EVIDENCE_SCHEMA_VERSION
from glossabet.corpus.cache import CACHE_VERSION
from glossabet.corpus.config import CONFIG_SCHEMA_VERSION
from glossabet.glossary import store as glossary_store
from glossabet.glossary.drift import DRIFT_SCHEMA_VERSION
from glossabet.glossary.model import GLOSSARY_SCHEMA_VERSION
from glossabet.glossary.reconcile import VALIDATION_SCHEMA_VERSION
from glossabet.managed_block import MANAGED_BLOCK_FORMAT_VERSION

ROOT = Path(__file__).resolve().parents[1]


def _policy() -> str:
    return (ROOT / "COMPATIBILITY.md").read_text(encoding="utf-8")


def test_compatibility_policy_tracks_current_format_versions():
    policy = _policy()
    product_versions = {
        "Repository configuration": CONFIG_SCHEMA_VERSION,
        "Repository evidence": EVIDENCE_SCHEMA_VERSION,
        "Structured glossary": GLOSSARY_SCHEMA_VERSION,
        "Drift report": DRIFT_SCHEMA_VERSION,
        "Validation report": VALIDATION_SCHEMA_VERSION,
        "Agent context": AGENT_CONTEXT_SCHEMA_VERSION,
        "Managed-context report": MANAGED_CONTEXT_SCHEMA_VERSION,
        "Managed host block": MANAGED_BLOCK_FORMAT_VERSION,
        "Vocabulary brief": BRIEF_FORMAT_VERSION,
        "Extraction cache": CACHE_VERSION,
    }
    evaluation_versions = {
        "Deterministic manifest": json.loads(
            (ROOT / "evaluation" / "corpus.json").read_text(encoding="utf-8")
        )["schema_version"],
        "Deterministic result": EVALUATION_SCHEMA_VERSION,
        "Codex scenario manifest": json.loads(
            (ROOT / "evaluation" / "agent-scenarios.json").read_text(
                encoding="utf-8"
            )
        )["schema_version"],
        "Codex result": CODEX_RESULT_SCHEMA_VERSION,
        "Codex history": CODEX_HISTORY_SCHEMA_VERSION,
        "Claude scenario manifest": json.loads(
            (ROOT / "evaluation" / "claude-scenarios.json").read_text(
                encoding="utf-8"
            )
        )["schema_version"],
        "Claude result": CLAUDE_RESULT_SCHEMA_VERSION,
        "Claude history": CLAUDE_HISTORY_SCHEMA_VERSION,
        "Reviewer packet": PACKET_SCHEMA_VERSION,
        "Reviewer result": REVIEW_SCHEMA_VERSION,
    }
    for name, version in product_versions.items() | evaluation_versions.items():
        assert f"| {name} | `{version}` |" in policy


def test_compatibility_policy_names_each_retained_exception_and_lifetime():
    policy = _policy()
    for required in (
        "## Python import paths",
        "## Field deprecation horizons",
        "## Narrow compatibility exceptions",
        "### Graphify `edges`",
        "### Tolerant evidence facts",
        "### Python re-exports",
        "### Pre-rename output names",
        "`glossabet.glossary.store`",
        "`glossabet.agent.agent_context`",
        "`production_complete`",
        "`complete: true`",
        "`oversized_identifiers`",
        "`glossarize-out/`",
        "`.glossarize/`",
        "Removal criterion",
    ):
        assert required in policy

    for name in glossary_store.__all__:
        assert f"`{name}`" in policy
    for name in (
        "AGENT_CONTEXT_SCHEMA_VERSION",
        "AgentContextCoverage",
        "AgentContextDocument",
        "ContextCoverage",
        "ContextCoverageRecord",
        "ContextFreshness",
        "ContextGlossarySection",
        "ContextLimits",
        "ContextNamingCandidates",
        "ContextRegisterSection",
        "ContextTermCandidate",
        "ContextTerminology",
        "LeanVocabularySection",
        "ModuleRollupEntry",
        "ModuleRollupTable",
        "Projection",
        "RegisterExemplar",
        "RegisterExemplars",
    ):
        assert f"`{name}`" in policy
