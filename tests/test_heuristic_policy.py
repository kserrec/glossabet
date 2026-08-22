"""The heuristic formulas are explicit policy: readable without the report
assembly, frozen by default, injectable by tests, and calibrated exactly as
before the policy objects existed."""

from collections import Counter
from dataclasses import FrozenInstanceError, replace

import pytest

from glossabet.analysis import policy as analysis_policy
from glossabet.analysis.evidence import build_evidence
from glossabet.analysis.importance import build_naming_candidates
from glossabet.analysis.policy import (
    DEFAULT_IMPORTANCE_POLICY,
    DEFAULT_TERMINOLOGY_POLICY,
    ImportancePolicy,
    TerminologyPolicy,
    colocated,
    context_dispersion,
    has_parallel_patterns,
    has_repository_breadth,
    has_shared_contexts,
    is_divergent,
    module_score,
    related_not_synonymous,
    similar_enough,
    term_score,
    weighted_cosine,
    wide_enough,
)
from glossabet.analysis.terminology import build_terminology
from glossabet.analysis.vocabulary import ProductionVocabulary
from glossabet.glossary import policy as glossary_policy
from glossabet.glossary.drift import build_drift
from glossabet.glossary.policy import (
    DEFAULT_DRIFT_POLICY,
    DEFAULT_RECONCILIATION_POLICY,
    MATCH_LABEL,
    MATCH_NONE,
    MATCH_STRONG,
    MATCH_WEAK,
    DriftPolicy,
    ReconciliationPolicy,
    fading_state,
    is_fragmented,
    is_overloaded_region,
    orphan_signal,
    overload_signal,
    parallel_term_signal,
    structural_match_strength,
    unnamed_structure_signal,
)
from glossabet.glossary.reconcile import build_validation

# The calibration as it was before the policy objects existed. Changing a
# number here is a product decision that must be made on purpose, with the
# evaluation corpus re-labelled — not a side effect of a refactor.
CALIBRATED_DEFAULTS = {
    TerminologyPolicy: {
        "pair_top_n": 150,
        "synonym_min_similarity": 0.55,
        "synonym_max_co_occurrence_rate": 0.2,
        "synonym_max_file_overlap": 0.2,
        "synonym_min_shared_contexts": 2,
        "synonym_min_shared_patterns": 2,
        "synonym_report_cap": 20,
        "overload_min_modules": 3,
        "overload_min_dispersion": 0.8,
        "overload_report_cap": 10,
        "overload_module_analysis_cap": 50,
        "overload_module_display_cap": 4,
        "shared_context_sample": 5,
        "shared_pattern_sample": 5,
        "module_context_sample": 5,
        "register_affix_cap": 8,
        "layer_cap": 10,
    },
    ImportancePolicy: {
        "module_candidate_cap": 10,
        "term_candidate_cap": 15,
        "term_min_module_spread": 2,
        "module_importer_weight": 3,
        "module_code_file_log_weight": 2,
        "module_import_count_log_weight": 1,
        "module_doc_mention_log_weight": 2,
        "term_module_spread_weight": 2,
        "term_use_count_log_ceiling": 100,
        "term_doc_mention_log_weight": 2,
        "term_compound_diversity_weight": 8,
        "term_patterns_per_file_weight": 6,
        "term_compound_density_weight": 4,
        "source_unit_anchor_weight": 15,
    },
    DriftPolicy: {
        "parallel_strong_min_similarity": 0.7,
        "parallel_moderate_min_similarity": 0.55,
        "fading_max_count": 2,
        "overload_min_modules": 3,
        "overload_min_dispersion": 0.8,
        "overload_strong_min_dispersion": 0.95,
    },
    ReconciliationPolicy: {
        "fragmentation_min_modules": 5,
        "overloaded_min_concepts": 3,
        "unnamed_strong_min_group_size": 5,
        "orphaned_max_count": 2,
    },
}


@pytest.mark.parametrize("policy_type", list(CALIBRATED_DEFAULTS))
def test_default_policy_is_the_calibrated_one_and_frozen(policy_type):
    policy = policy_type()
    assert {
        name: getattr(policy, name) for name in CALIBRATED_DEFAULTS[policy_type]
    } == CALIBRATED_DEFAULTS[policy_type]
    # Every field is pinned above: a new knob needs a calibrated default.
    assert set(policy.__dataclass_fields__) == set(CALIBRATED_DEFAULTS[policy_type])
    with pytest.raises(FrozenInstanceError):
        setattr(policy, next(iter(CALIBRATED_DEFAULTS[policy_type])), 0)


def _vocabulary(files):
    vocabulary = ProductionVocabulary()
    for rel, identifiers in files.items():
        module = rel.rsplit("/", 1)[0] if "/" in rel else "."
        vocabulary.fold(Counter(identifiers), rel, module, "python")
    return vocabulary


def test_default_outputs_equal_explicit_default_policy(tmp_path):
    (tmp_path / "a.py").write_text(
        "job_queue = 1\ntask_queue = 2\nrun_job = 3\nrun_task = 4\n"
        "payment_total = 5\nbilling_total = 6\n"
    )
    (tmp_path / "b.py").write_text(
        "from a import job_queue\njob_queue_size = 1\ntask_queue_size = 2\n"
        "job_record = 3\ntask_record = 4\n"
    )
    (tmp_path / "README.md").write_text("The job queue and the task queue.\n")
    evidence = build_evidence(tmp_path)
    vocabulary = _vocabulary({
        "a.py": ["job_queue", "task_queue", "run_job", "run_task",
                 "payment_total", "billing_total"],
        "b.py": ["job_queue", "job_queue_size", "task_queue_size",
                 "job_record", "task_record"],
    })
    docs = Counter({"job": 1, "queue": 2, "task": 1})
    assert build_terminology(vocabulary, docs) == build_terminology(
        vocabulary, docs, policy=DEFAULT_TERMINOLOGY_POLICY
    )
    assert build_naming_candidates(
        evidence["imports"], evidence["modules"], vocabulary, docs,
    ) == build_naming_candidates(
        evidence["imports"], evidence["modules"], vocabulary, docs,
        policy=DEFAULT_IMPORTANCE_POLICY,
    )
    glossary = {
        "schema_version": 1,
        "concepts": [{
            "id": "job", "term": "Job", "status": "canonical",
            "definition": "A unit of work.",
        }],
    }
    assert build_drift(evidence, glossary) == build_drift(
        evidence, glossary, policy=DEFAULT_DRIFT_POLICY
    )
    assert build_validation(evidence, glossary) == build_validation(
        evidence, glossary, policy=DEFAULT_RECONCILIATION_POLICY
    )


def test_injected_policy_changes_the_nomination_not_the_shape():
    vocabulary = _vocabulary({
        "a.py": ["alpha_value", "beta_value", "alpha_value", "beta_value"],
    })
    capped = build_terminology(
        vocabulary, Counter(),
        policy=replace(DEFAULT_TERMINOLOGY_POLICY, pair_top_n=1),
    )
    assert capped["considered_tokens"] == 1
    assert capped["coverage"]["eligible_tokens"]["complete"] is False
    assert set(capped) == set(build_terminology(vocabulary, Counter()))


# --- formulas ---------------------------------------------------------------


def test_module_score_is_monotonic_in_every_signal():
    base = dict(importers=2, code_files=3, import_count=4, doc_mentions=1)
    score = module_score(**base, policy=DEFAULT_IMPORTANCE_POLICY)
    for signal in base:
        more = {**base, signal: base[signal] + 1}
        assert module_score(**more, policy=DEFAULT_IMPORTANCE_POLICY) > score
    assert module_score(
        importers=0, code_files=0, import_count=0, doc_mentions=0,
        policy=DEFAULT_IMPORTANCE_POLICY,
    ) == 0.0


def test_term_score_is_monotonic_and_caps_the_use_count():
    base = dict(
        module_spread=2, use_count=10, doc_mentions=1, compound_diversity=0.5,
        patterns_per_file=0.5, compound_density=0.5, source_units_named=0,
    )
    score = term_score(**base, policy=DEFAULT_IMPORTANCE_POLICY)
    for signal in base:
        more = {**base, signal: base[signal] + 1}
        assert term_score(**more, policy=DEFAULT_IMPORTANCE_POLICY) > score
    # Use count saturates at the ceiling; a second source file adds nothing.
    policy = DEFAULT_IMPORTANCE_POLICY
    at = term_score(**{**base, "use_count": policy.term_use_count_log_ceiling}, policy=policy)
    beyond = term_score(**{**base, "use_count": policy.term_use_count_log_ceiling + 50}, policy=policy)
    assert at == beyond
    one = term_score(**{**base, "source_units_named": 1}, policy=policy)
    two = term_score(**{**base, "source_units_named": 2}, policy=policy)
    assert one == two == score + policy.source_unit_anchor_weight


def test_candidate_ties_break_on_name(tmp_path):
    # Two modules with identical import structure tie on score; the report
    # orders them by path, deterministically.
    for name in ("zeta", "alpha"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "core.py").write_text("VALUE = 1\n")
    (tmp_path / "main.py").write_text("from zeta import core\nfrom alpha import core\n")
    evidence = build_evidence(tmp_path)
    modules = evidence["naming_candidates"]["modules"]
    scores = [m["score"] for m in modules]
    assert len(set(scores)) == 1
    assert [m["path"] for m in modules] == ["alpha", "zeta"]


def test_context_dispersion_formula():
    assert context_dispersion([{"a"}, {"a"}]) == 0.0
    assert context_dispersion([{"a"}, {"b"}]) == 1.0
    assert context_dispersion([{"a", "b"}, {"b", "c"}]) == round(1 - 1 / 3, 3)
    assert context_dispersion([{"a"}]) is None
    assert context_dispersion([set(), set()]) is None


def test_weighted_cosine_ignores_the_pair_itself():
    counts = Counter({"x": 2, "y": 1, "pair": 9})

    def weight(token):
        return 1.0

    assert weighted_cosine(counts, counts, exclude={"pair"}, weight=weight) == pytest.approx(1.0)
    assert weighted_cosine(Counter({"x": 1}), Counter({"y": 1}), exclude=set(), weight=weight) == 0.0


@pytest.mark.parametrize(
    "gate, field, policy, below, at, above",
    [
        (related_not_synonymous, "synonym_max_co_occurrence_rate", DEFAULT_TERMINOLOGY_POLICY, False, False, True),
        (colocated, "synonym_max_file_overlap", DEFAULT_TERMINOLOGY_POLICY, False, False, True),
        (has_parallel_patterns, "synonym_min_shared_patterns", DEFAULT_TERMINOLOGY_POLICY, False, True, True),
        (has_shared_contexts, "synonym_min_shared_contexts", DEFAULT_TERMINOLOGY_POLICY, False, True, True),
        (similar_enough, "synonym_min_similarity", DEFAULT_TERMINOLOGY_POLICY, False, True, True),
        (wide_enough, "overload_min_modules", DEFAULT_TERMINOLOGY_POLICY, False, True, True),
        (is_divergent, "overload_min_dispersion", DEFAULT_TERMINOLOGY_POLICY, False, True, True),
        (has_repository_breadth, "term_min_module_spread", DEFAULT_IMPORTANCE_POLICY, False, True, True),
        (is_fragmented, "fragmentation_min_modules", DEFAULT_RECONCILIATION_POLICY, False, True, True),
        (is_overloaded_region, "overloaded_min_concepts", DEFAULT_RECONCILIATION_POLICY, False, True, True),
    ],
)
def test_threshold_gates_below_at_above(gate, field, policy, below, at, above):
    threshold = getattr(policy, field)
    step = 1 if isinstance(threshold, int) else 0.001
    assert gate(threshold - step, policy) is below
    assert gate(threshold, policy) is at
    assert gate(threshold + step, policy) is above


def test_signal_bands_below_at_above():
    d = DEFAULT_DRIFT_POLICY
    assert parallel_term_signal(d.parallel_strong_min_similarity, d) == "strong"
    assert parallel_term_signal(d.parallel_strong_min_similarity - 0.001, d) == "moderate"
    assert parallel_term_signal(d.parallel_moderate_min_similarity, d) == "moderate"
    assert parallel_term_signal(d.parallel_moderate_min_similarity - 0.001, d) == "weak"
    assert overload_signal(d.overload_strong_min_dispersion, d) == "strong"
    assert overload_signal(d.overload_strong_min_dispersion - 0.001, d) == "moderate"
    assert fading_state(0, 5, False, d) == ("strong", "absent from code")
    assert fading_state(d.fading_max_count, 0, True, d) == ("moderate", "fading")
    assert fading_state(d.fading_max_count + 1, 0, True, d) is None
    assert fading_state(1, 1, True, d) is None       # mentioned in docs
    assert fading_state(1, 0, False, d) is None      # doc count not proven
    assert fading_state(1, None, True, d) is None    # compound: docs unknown
    r = DEFAULT_RECONCILIATION_POLICY
    assert unnamed_structure_signal(r.unnamed_strong_min_group_size, r) == "strong"
    assert unnamed_structure_signal(r.unnamed_strong_min_group_size - 1, r) == "moderate"
    assert orphan_signal(0, r) == "strong"
    assert orphan_signal(r.orphaned_max_count, r) == "moderate"
    assert orphan_signal(r.orphaned_max_count + 1, r) is None


def test_structural_match_strength_ladder():
    term, binding = {"pay", "attempt"}, {"gateway"}
    assert structural_match_strength({"pay", "attempt"}, {"pay", "attempt", "x"}, term, binding) == MATCH_LABEL
    assert structural_match_strength({"pay"}, {"pay", "attempt"}, term, binding) == MATCH_STRONG
    assert structural_match_strength(set(), {"gateway"}, term, binding) == MATCH_WEAK
    assert structural_match_strength(set(), {"pay"}, term, binding) == MATCH_WEAK
    assert structural_match_strength(set(), {"other"}, term, binding) == MATCH_NONE
    # An empty term vocabulary can never be a label or strong match.
    assert structural_match_strength({"x"}, {"x"}, set(), {"x"}) == MATCH_WEAK
    assert MATCH_NONE < MATCH_WEAK < MATCH_STRONG < MATCH_LABEL


def test_policy_modules_stay_beneath_their_layers():
    # analysis.policy is a stdlib-only leaf; glossary.policy reaches only it.
    import ast
    from pathlib import Path

    def imports(module):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        return {
            node.module for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        } | {
            alias.name for node in ast.walk(tree)
            if isinstance(node, ast.Import) for alias in node.names
        }

    assert not {m for m in imports(analysis_policy) if m.startswith("glossabet")}
    assert {m for m in imports(glossary_policy) if m.startswith("glossabet")} == {
        "glossabet.analysis.policy"
    }
