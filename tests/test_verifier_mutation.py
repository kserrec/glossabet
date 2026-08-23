"""The three evidence verifiers face documents an attacker or a bad merge
could produce: any mutation of the committed evidence must be *reported*
(a list of error strings) or *classified* (the verifier's own error type or
an OSError) — never a traceback, which would turn the release gate into an
internal-error exit and hide what was wrong.

Ported from a seeded hunter (test-audit, 2026-08-18): the family below found
two OverflowError sites in verifier arithmetic before those were guarded.
The mutation family is deterministic per committed evidence file; when a
file is regenerated the concrete cases shift but the property is the same.
"""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import pytest

from evaluation.codex.contract import AgentEvaluationError
from evaluation.codex.results import verify_results as agent_verify
from evaluation.deterministic.contract import EvaluationError
from evaluation.deterministic.results import verify_results as run_verify
from evaluation.review import DEFAULT_PACKET
from evaluation.review import verify_results as review_verify

ROOT = Path(__file__).resolve().parents[1]
SEED = 20260819  # chosen so the run family reaches the once-unguarded arithmetic within 400 cases
LONE_SURROGATE = "\ud800"
SCALARS = [
    None, True, False, 0, 1, -1, 5, 1.5, -0.0, float("nan"), float("inf"),
    10 ** 400, 10 ** 20, 2 ** 63, "", "x", "5", "0", [], {}, [1], {"a": 1},
    [None], "abc" * 100, LONE_SURROGATE,
]


def _scalar(rng: random.Random):
    # A fresh copy every time: the mutable members would otherwise be
    # spliced into documents by reference and mutated in place, making the
    # case set depend on which parametrization ran earlier in the process.
    return copy.deepcopy(rng.choice(SCALARS))


def _mutate(rng: random.Random, doc):
    doc = copy.deepcopy(doc)
    for _ in range(rng.choice([1, 1, 1, 2, 3, 5])):
        node, parent, key, depth = doc, None, None, 0
        while True:
            if isinstance(node, dict) and node and rng.random() < 0.85:
                parent, key = node, rng.choice(sorted(node))
                node = node[key]
            elif isinstance(node, list) and node and rng.random() < 0.85:
                parent, key = node, rng.randrange(len(node))
                node = node[key]
            else:
                break
            depth += 1
            if depth > 12:
                break
        if parent is None:
            return doc if rng.random() < 1 / (len(SCALARS) + 1) else _scalar(rng)
        op = rng.random()
        if op < 0.5:
            parent[key] = _scalar(rng)
        elif op < 0.65 and isinstance(parent, dict):
            del parent[key]
        elif op < 0.75 and isinstance(node, (int, float)) and not isinstance(node, bool):
            parent[key] = rng.choice(
                [node + 1, -node, node * 10 ** 6, 10 ** 400, float("nan"), float("inf"), 0]
            )
        elif op < 0.85 and isinstance(node, str):
            parent[key] = rng.choice(
                [node + "x", node[:-1], node.upper(), "", node * 50, "\x00"]
            )
        elif op < 0.92 and isinstance(node, list):
            parent[key] = (
                node + [_scalar(rng)] if rng.random() < 0.5
                else (node[1:] if node else [_scalar(rng)])
            )
        elif isinstance(node, dict):
            node[rng.choice(sorted(node) or ["k"])] = (
                _scalar(rng) if rng.random() < 0.5 else node
            )
        else:
            parent[key] = [node] if rng.random() < 0.5 else {"v": node}
    return doc


CASES = {
    "run": (
        ROOT / "evaluation" / "results.json",
        lambda path: run_verify(path, ROOT / "evaluation" / "corpus.json"),
        (EvaluationError, OSError),
    ),
    "agent": (
        ROOT / "evaluation" / "agent-results.json",
        lambda path: agent_verify(path),
        (AgentEvaluationError, OSError),
    ),
    "review": (
        ROOT / "evaluation" / "reviewer-results.json",
        lambda path: review_verify(path, DEFAULT_PACKET),
        (EvaluationError, OSError),
    ),
}


@pytest.mark.parametrize("which", sorted(CASES))
def test_mutated_evidence_is_reported_or_classified_never_a_traceback(tmp_path, which):
    source, verify, classified = CASES[which]
    original = json.loads(source.read_text(encoding="utf-8"))
    rng = random.Random(SEED)
    path = tmp_path / "mutated.json"
    dumped = 0
    for case in range(400):
        mutated = _mutate(rng, original)
        try:
            text = json.dumps(mutated)  # NaN and lone surrogates are what a hostile file holds
        except (ValueError, TypeError):
            continue
        dumped += 1
        path.write_text(text, encoding="utf-8", errors="surrogatepass")
        try:
            errors = verify(path)
        except classified:
            continue
        assert isinstance(errors, list) and all(
            isinstance(error, str) for error in errors
        ), f"{which} case {case}"
    assert dumped >= 300

