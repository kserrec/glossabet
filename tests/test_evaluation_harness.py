"""The shared evaluation harness: evaluator-code identity and the import
boundaries that keep offline verification independent of live hosts."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

import evaluation.codex.results as codex_results
import evaluation.review as review
import evaluation.run as run
import scripts.claude_eval as claude_eval
from evaluation.harness.identity import (
    LANE_WRAPPERS,
    lane_source_identity,
    lane_source_paths,
)
from evaluation.harness.io import framed_digest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "evaluation" / "harness"


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """A miniature repository with two lanes sharing one harness module."""
    _write(tmp_path, "evaluation/__init__.py", "")
    _write(tmp_path, "evaluation/harness/__init__.py", "")
    _write(tmp_path, "evaluation/harness/io.py", "def sha(): ...\n")
    _write(tmp_path, "evaluation/harness/unused.py", "def nobody(): ...\n")
    _write(
        tmp_path,
        "evaluation/harness/identity.py",
        "from evaluation.harness.io import sha\n",
    )
    _write(
        tmp_path,
        "scripts/agent_eval.py",
        "from evaluation.codex.cli import main\n",
    )
    _write(tmp_path, "evaluation/codex/__init__.py", "")
    _write(
        tmp_path,
        "evaluation/codex/cli.py",
        "from evaluation.harness.identity import lane_source_identity\n",
    )
    _write(
        tmp_path,
        "scripts/claude_eval.py",
        "from evaluation.harness import io\n",
    )
    _write(tmp_path, "evaluation/run.py", "import json\n")
    _write(tmp_path, "evaluation/review.py", "import json\n")
    _write(tmp_path, "glossabet/engine.py", "VERSION = 1\n")
    return tmp_path


def test_identity_covers_wrapper_lane_package_and_imported_harness(fake_repo):
    assert lane_source_paths("codex", root=fake_repo) == [
        "evaluation/codex/__init__.py",
        "evaluation/codex/cli.py",
        "evaluation/harness/identity.py",
        "evaluation/harness/io.py",
        "scripts/agent_eval.py",
    ]
    # A harness module nothing in the lane imports is not part of its identity.
    assert "evaluation/harness/unused.py" not in lane_source_paths(
        "claude", root=fake_repo
    )
    assert lane_source_paths("claude", root=fake_repo) == [
        "evaluation/harness/__init__.py",
        "evaluation/harness/io.py",
        "scripts/claude_eval.py",
    ]


def test_identity_is_a_framed_digest_over_sorted_paths_and_bytes(fake_repo):
    paths = lane_source_paths("codex", root=fake_repo)
    expected = hashlib.sha256()
    for relative in paths:
        name = relative.encode()
        content = (fake_repo / relative).read_bytes()
        expected.update(len(name).to_bytes(8, "big"))
        expected.update(name)
        expected.update(len(content).to_bytes(8, "big"))
        expected.update(content)
    assert lane_source_identity("codex", root=fake_repo) == expected.hexdigest()


def test_framed_digest_separates_name_from_content():
    assert framed_digest([("ab", b"c")]) != framed_digest([("a", b"bc")])
    assert framed_digest([("a", b"b"), ("c", b"d")]) != framed_digest(
        [("a", b"bc"), ("", b"d")]
    )


def test_changing_a_lane_file_changes_only_that_lane(fake_repo):
    before = {
        lane: lane_source_identity(lane, root=fake_repo) for lane in LANE_WRAPPERS
    }
    _write(fake_repo, "evaluation/codex/cli.py", "# changed\n")
    after = {
        lane: lane_source_identity(lane, root=fake_repo) for lane in LANE_WRAPPERS
    }
    assert after["codex"] != before["codex"]
    assert {k: v for k, v in after.items() if k != "codex"} == {
        k: v for k, v in before.items() if k != "codex"
    }


def test_changing_shared_harness_changes_every_lane_that_imports_it(fake_repo):
    before = {
        lane: lane_source_identity(lane, root=fake_repo) for lane in LANE_WRAPPERS
    }
    _write(fake_repo, "evaluation/harness/io.py", "def sha(): return 2\n")
    after = {
        lane: lane_source_identity(lane, root=fake_repo) for lane in LANE_WRAPPERS
    }
    assert after["codex"] != before["codex"]
    assert after["claude"] != before["claude"]
    assert after["deterministic"] == before["deterministic"]
    assert after["reviewer"] == before["reviewer"]


def test_unrelated_production_code_does_not_change_identity(fake_repo):
    before = lane_source_identity("codex", root=fake_repo)
    _write(fake_repo, "glossabet/engine.py", "VERSION = 2\n")
    _write(fake_repo, "evaluation/harness/unused.py", "def nobody(): return 1\n")
    assert lane_source_identity("codex", root=fake_repo) == before


def test_unknown_lane_is_rejected():
    with pytest.raises(ValueError, match="unknown evaluation lane"):
        lane_source_paths("nonexistent")


def test_real_lanes_include_wrapper_and_harness():
    for lane, wrapper in LANE_WRAPPERS.items():
        paths = lane_source_paths(lane)
        assert wrapper in paths
        assert "evaluation/harness/io.py" in paths, lane
        assert not any(path.startswith("glossabet/") for path in paths)


@pytest.mark.parametrize(
    "module, attribute",
    [
        (codex_results, "lane_source_identity"),
        (claude_eval, "lane_source_identity"),
        (review, "lane_source_identity"),
        (run, "lane_source_paths"),
    ],
)
def test_default_verification_never_consults_current_evaluator_source(
    module, attribute, monkeypatch
):
    """Genuine-versus-current: retained evidence is judged genuine without
    hashing the evaluator that exists today. Only ``--current`` compares."""

    def forbidden(*_args, **_kwargs):
        raise AssertionError("current evaluator identity was consulted")

    monkeypatch.setattr(module, attribute, forbidden)
    if module is codex_results:
        assert codex_results.verify_results(codex_results.DEFAULT_RESULTS) == []
        with pytest.raises(AssertionError):
            codex_results.verify_results(
                codex_results.DEFAULT_RESULTS, current=True
            )
    elif module is claude_eval:
        errors = claude_eval.verify_results(claude_eval.DEFAULT_RESULTS)
        assert errors[-1] == "Claude evaluation scenarios did not all pass"
        with pytest.raises(AssertionError):
            claude_eval.verify_results(claude_eval.DEFAULT_RESULTS, current=True)
    elif module is run:
        assert run.verify_results(run.DEFAULT_RESULTS, run.DEFAULT_MANIFEST) == []
        with pytest.raises(AssertionError):
            run.verify_results(
                run.DEFAULT_RESULTS, run.DEFAULT_MANIFEST, current=True
            )
    else:
        args = (
            review.DEFAULT_REVIEW_RESULTS,
            review.DEFAULT_PACKET,
            review.DEFAULT_MANIFEST,
            review.DEFAULT_RESULTS,
        )
        assert review.verify_results(*args) == []
        with pytest.raises(AssertionError):
            review.verify_results(*args, current=True)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_harness_imports_no_lane_and_no_process_machinery():
    lanes = set(LANE_WRAPPERS) | {"run", "review"}
    for path in HARNESS.glob("*.py"):
        for name in _imports(path):
            parts = name.split(".")
            assert parts[0] != "scripts", (path.name, name)
            if parts[0] == "evaluation":
                assert len(parts) > 1 and parts[1] == "harness", (path.name, name)
                assert parts[1] not in lanes
            assert parts[0] not in {"subprocess", "shutil"}, (path.name, name)
