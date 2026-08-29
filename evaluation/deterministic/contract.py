"""The deterministic evaluation lane's contract: repository paths, the
result schema version, the pinned release-threshold metric set, the
confined Git configuration, the section vocabularies it scores, and the
lane's error type. Nothing here imports a lane module.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

EVALUATION_SCHEMA_VERSION = 8
DEFAULT_MANIFEST = PROJECT_ROOT / "evaluation" / "corpus.json"
DEFAULT_RESULTS = PROJECT_ROOT / "evaluation" / "results.json"
RELEASE_RUNTIME_RUNS = 5
# Every metric the evaluator can gate on. Genuineness verification pins this
# exact set so a tampered artifact cannot drop the checks it fails;
# which targets those checks carry is verified against the manifest at the
# release gate.
RELEASE_THRESHOLD_NAMES = frozenset({
    "terminology_precision_min",
    "drift_precision_min",
    "drift_recall_min",
    "structural_precision_min",
    "structural_recall_min",
    "reviewer_usefulness_min",
    "false_alarms_per_1000_max",
    "cold_seconds_per_1000_source_files_max",
    "corpus_budget_truncations_max",
    "minimum_cache_reuse_min",
    "lexical_contract_min",
    "register_accuracy_min",
    "nomination_quality_min",
    "structural_contract_min",
})
# Neutralize repo-config code-execution surfaces and, critically, the ext::
# remote helper: a corpus url like `ext::sh -c '<payload>'` otherwise runs a
# shell at fetch time. The manifest validator additionally requires https.
GIT_SAFE_CONFIG = (
    "-c", "core.fsmonitor=",
    "-c", "core.hooksPath=/dev/null",
    "-c", "protocol.ext.allow=never",
)
DRIFT_SECTIONS = (
    "parallel_terms",
    "watched_terms_in_use",
    "canonical_fading",
    "canonical_overloaded",
)
SOURCE_METADATA_KEYS = (
    "kind",
    "path",
    "checkout_dir",
    "url",
    "commit",
    "primary_language",
    "license_spdx",
    "license_url",
    "provenance",
)
STRUCTURAL_SECTIONS = (
    "unnamed_structure",
    "boundary_mismatch",
    "overloaded_structural_region",
    "orphaned_concepts",
    "fragmentation",
)


class EvaluationError(ValueError):
    """The corpus, checkout, or labels cannot support a valid evaluation."""
