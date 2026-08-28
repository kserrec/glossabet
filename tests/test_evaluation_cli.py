"""Characterization of the four evaluation entry points.

These pin the terminal-facing contract — exit statuses, success wording,
representative failure wording, and the ``--current`` prohibition — so the
modularization can move implementation without changing what a maintainer
or CI sees. Nothing here runs a live host.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from evaluation import review, run
from scripts import agent_eval, claude_eval

ROOT = Path(__file__).resolve().parents[1]
ENTRY_POINTS = (
    "scripts/agent_eval.py",
    "scripts/claude_eval.py",
    "evaluation/run.py",
    "evaluation/review.py",
)


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_entry_script_is_executable_standalone(entry):
    proc = subprocess.run(
        [sys.executable, str(ROOT / entry), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "--verify-results" in proc.stdout
    assert "--current" in proc.stdout


def test_codex_offline_verification_succeeds(capsys):
    status = agent_eval.main(
        ["--verify-results", "evaluation/agent-results.json"]
    )
    out = capsys.readouterr()
    assert status == 0
    assert out.out.strip() == (
        "installed-agent evidence is genuine, bounded, and safety-complete; "
        "procedural reliability history retained"
    )
    assert out.err == ""


def test_claude_offline_verification_reports_the_recorded_miss(capsys):
    """The retained first Claude batch is 0/3; the verifier says so rather
    than passing it."""
    status = claude_eval.main(
        ["--verify-results", "evaluation/claude-results.json"]
    )
    out = capsys.readouterr()
    assert status == 1
    assert out.out == ""
    lines = out.err.strip().splitlines()
    assert all(
        line.startswith("Claude evaluation verification: ") for line in lines
    )
    assert lines[-1] == (
        "Claude evaluation verification: "
        "Claude evaluation scenarios did not all pass"
    )


def test_claude_history_verification_succeeds(capsys):
    status = claude_eval.main(["--verify-history"])
    out = capsys.readouterr()
    assert status == 0
    assert out.out.strip() == "Claude attempt history is genuine; 1 attempt retained"


def test_deterministic_offline_verification_succeeds(capsys):
    status = run.main(["--verify-results", "evaluation/results.json"])
    out = capsys.readouterr()
    assert status == 0
    assert out.out.strip() == (
        "evaluation results are genuine and internally consistent"
    )


def test_reviewer_offline_verification_succeeds(capsys):
    status = review.main(["--verify-results", "evaluation/reviewer-results.json"])
    out = capsys.readouterr()
    assert status == 0
    assert out.out.strip() == (
        "second-reviewer evidence is genuine, blinded, and internally consistent"
    )


@pytest.mark.parametrize(
    "main, prefix",
    [
        (agent_eval.main, "agent evaluation: agent evaluation results is unreadable: "),
        (
            claude_eval.main,
            "Claude evaluation verification: Claude evaluation result is "
            "unreadable: ",
        ),
        (run.main, "evaluation verification: "),
        (review.main, "review evaluation: reviewer results is unreadable: "),
    ],
)
def test_missing_results_fail_with_lane_wording(
    main, prefix, capsys, tmp_path
):
    missing = tmp_path / "missing-results.json"
    assert not missing.exists()

    status = main(["--verify-results", str(missing)])
    out = capsys.readouterr()

    assert status == 1
    assert out.out == ""
    assert out.err.startswith(prefix)
    assert out.err[len(prefix) :].strip()


def test_current_requires_verify_results_in_every_lane(capsys):
    """Each lane refuses ``--current`` without ``--verify-results`` before
    doing any other work; the wording and status are lane-specific."""
    assert agent_eval.main(["--refresh-artifact", "--current"]) == 1
    assert capsys.readouterr().err.strip() == (
        "agent evaluation: --current can be used only with --verify-results"
    )

    assert claude_eval.main(["--verify-history", "--current"]) == 1
    assert capsys.readouterr().err.strip() == (
        "Claude evaluation: --current can be used only with --verify-results"
    )

    with pytest.raises(SystemExit) as exc:
        run.main(["--current"])
    assert exc.value.code == 2
    assert "--current requires --verify-results" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        review.main(["--build-packet", "--current"])
    assert exc.value.code == 2
    assert "--current requires --verify-results" in capsys.readouterr().err


@pytest.mark.parametrize(
    "main, argv",
    [
        (agent_eval.main, ["--current"]),
        (claude_eval.main, ["--current"]),
        (review.main, ["--current"]),
    ],
)
def test_action_is_required(main, argv, capsys):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
    assert "required" in capsys.readouterr().err
