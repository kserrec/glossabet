"""GLOSSABET.md, the vocabulary-health report, is derived Glossabet output:
never lexical evidence for its own next run, never a freshness input, and
never machine state. GLOSSARY.md keeps its different rules: excluded from
evidence so it can be validated independently, but visible to freshness
because it is human-governed vocabulary."""

import json
import os
import subprocess
from pathlib import Path

from glossabet.analysis.evidence import build_evidence
from glossabet.cli import main
from glossabet.corpus.scanner import SELF_FILES, SELF_REPORT_FILES
from glossabet.glossary.repository_glossary import REPOSITORY_GLOSSARY_FILE
from glossabet.glossary.store import load_glossary, save_glossary
from glossabet.runtime.artifacts import REPORT_FILE
from glossabet.runtime.git_state import FRESHNESS_STATUS_ARGS, repository_git_stamp

REPORT = (
    "# Glossabet\n\nThis is a Glossabet vocabulary-health report, not the "
    "canonical glossary.\n\n## Proposed changes\n\n"
    + "**Proposed:** `Quintarion` for the settlement boundary.\n" * 200
    + "\n## Open questions\n\nIs `quintarion_gate` broader than the ledger?\n"
)


def _code(root: Path) -> None:
    (root / "service.py").write_text("payment_service = 1\nledger_batch = 2\n")
    (root / "README.md").write_text("# Service\nA payment service.\n")


def _git(root: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    subprocess.run(
        ["git", *args], cwd=root, env=env, check=True,
        capture_output=True, text=True,
    )


def _init_repo(root: Path, tracked_extra: dict[str, str] | None = None) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Glossabet Test")
    _code(root)
    tracked = ["service.py", "README.md"]
    for relative, content in (tracked_extra or {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        tracked.append(relative)
    _git(root, "add", "--", *tracked)
    _git(root, "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
         "commit", "-qm", "initial")


# --- one name, every module -------------------------------------------------


def test_report_name_is_shared_by_scanner_and_freshness_and_distinct_from_glossary():
    """If the spellings drift, the report would be excluded from one place
    and not the other; if the two sets ever overlap, GLOSSARY.md would be
    silently hidden from freshness."""
    assert REPORT_FILE == "GLOSSABET.md"
    assert SELF_REPORT_FILES == frozenset({REPORT_FILE})
    assert not (SELF_FILES & SELF_REPORT_FILES)
    assert f":(exclude){REPORT_FILE}" in FRESHNESS_STATUS_ARGS
    assert f":(exclude){REPOSITORY_GLOSSARY_FILE}" not in FRESHNESS_STATUS_ARGS
    assert not any(REPOSITORY_GLOSSARY_FILE in arg for arg in FRESHNESS_STATUS_ARGS)


# --- self-feedback prevention -----------------------------------------------


def test_report_never_enters_lexical_evidence(tmp_path):
    _code(tmp_path)
    baseline = build_evidence(tmp_path, cache=False)

    (tmp_path / REPORT_FILE).write_text(REPORT)
    with_report = build_evidence(tmp_path, cache=False)

    for key in ("vocabulary", "terminology", "naming_candidates", "files", "totals"):
        assert with_report[key] == baseline[key], key
    assert with_report["skipped"]["self_reports"] == [REPORT_FILE]
    assert baseline["skipped"]["self_reports"] == []
    assert "quintarion" not in json.dumps(with_report).lower()
    # The report is not the glossary channel either.
    assert with_report["skipped"]["self_glossaries"] == []


def test_nested_reports_are_excluded_and_reported_but_lookalikes_count(tmp_path):
    _code(tmp_path)
    (tmp_path / REPORT_FILE).write_text(REPORT)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / REPORT_FILE).write_text(REPORT)
    (tmp_path / "pkg" / "mod.py").write_text("x = 1\n")
    # Exact-name exclusion only: an ordinary doc with a similar name is
    # repository content and stays evidence.
    (tmp_path / "GLOSSABET-notes.md").write_text("# Notes\n\nvexillomorph tally\n")

    evidence = build_evidence(tmp_path, cache=False)

    assert evidence["skipped"]["self_reports"] == [REPORT_FILE, f"pkg/{REPORT_FILE}"]
    dumped = json.dumps(evidence)
    assert f"pkg/{REPORT_FILE}" not in json.dumps(evidence["files"])
    assert "quintarion" not in dumped.lower()
    assert "GLOSSABET-notes.md" in json.dumps(evidence["files"])
    assert "vexillomorph" in dumped


def test_inspect_context_reports_the_exclusion_and_carries_no_report_words(
    tmp_path, capsys
):
    _code(tmp_path)
    (tmp_path / REPORT_FILE).write_text(REPORT)
    assert main(["inspect", str(tmp_path), "--no-graphify"]) == 0
    context = json.loads(capsys.readouterr().out)
    assert context["skipped"]["self_reports"] == [REPORT_FILE]
    assert "quintarion" not in json.dumps(context).lower()


# --- freshness: derived output vs human-governed vocabulary -----------------


def test_untracked_report_does_not_dirty_freshness(tmp_path):
    _init_repo(tmp_path)
    assert main(["scan", str(tmp_path)]) == 0
    stamped = json.loads(
        (tmp_path / "glossabet-out" / "evidence.json").read_text(encoding="utf-8")
    )["repository"]["git"]
    assert stamped["dirty"] is False

    (tmp_path / REPORT_FILE).write_text(REPORT)

    live = repository_git_stamp(tmp_path)
    assert live == stamped
    assert live["dirty"] is False


def test_tracked_report_regeneration_does_not_dirty_freshness(tmp_path):
    _init_repo(tmp_path, tracked_extra={REPORT_FILE: "# Glossabet\n\nold\n"})
    (tmp_path / REPORT_FILE).write_text(REPORT)
    assert repository_git_stamp(tmp_path)["dirty"] is False

    # Deleting the tracked report is likewise an output change.
    (tmp_path / REPORT_FILE).unlink()
    assert repository_git_stamp(tmp_path)["dirty"] is False


def test_glossary_markdown_change_remains_visible_next_to_hidden_report(tmp_path):
    """The two names are similar; only the report is derived output."""
    _init_repo(tmp_path, tracked_extra={
        REPORT_FILE: "# Glossabet\n\nold\n",
        REPOSITORY_GLOSSARY_FILE: "# Glossary\n\nold\n",
    })
    (tmp_path / REPORT_FILE).write_text(REPORT)
    assert repository_git_stamp(tmp_path)["dirty"] is False

    (tmp_path / REPOSITORY_GLOSSARY_FILE).write_text("# Glossary\n\nnew term\n")
    assert repository_git_stamp(tmp_path)["dirty"] is True


def test_untracked_glossary_markdown_is_dirty_even_when_report_is_not(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / REPORT_FILE).write_text(REPORT)
    assert repository_git_stamp(tmp_path)["dirty"] is False
    (tmp_path / REPOSITORY_GLOSSARY_FILE).write_text("# Glossary\n")
    assert repository_git_stamp(tmp_path)["dirty"] is True


def test_nested_subproject_report_is_ordinary_state_for_the_enclosing_scan(tmp_path):
    """Only the scan root's own report is this scan's output; a subproject's
    report belongs to that subproject's scan and stays visible here."""
    _init_repo(tmp_path)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / REPORT_FILE).write_text(REPORT)
    assert repository_git_stamp(tmp_path)["dirty"] is True


def test_move_source_into_report_name_keeps_deletion_visible(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "service.py").rename(tmp_path / REPORT_FILE)
    assert repository_git_stamp(tmp_path)["dirty"] is True


# --- no machine authority ---------------------------------------------------


def _glossary() -> dict:
    return {
        "schema_version": 1,
        "concepts": [
            {
                "id": "ledger-batch",
                "term": "Ledger batch",
                "definition": "A settled group.",
                "status": "canonical",
            },
            {
                "id": "gate",
                "term": "Gate",
                "definition": "The ingestion boundary.",
                "status": "proposed",
            },
        ],
    }


def test_report_content_never_becomes_glossary_state_and_deletion_changes_nothing(
    tmp_path, capsys
):
    _code(tmp_path)
    saved = save_glossary(tmp_path, _glossary())
    before = saved.read_bytes()

    (tmp_path / REPORT_FILE).write_text(
        "# Glossabet\n\nThe ingestion boundary is called Gate (canonical).\n"
        "Quintarion is canonical.\n"
    )
    for command in (["show"], ["inspect", "--no-graphify"], ["drift"], ["validate"]):
        capsys.readouterr()
        main([command[0], str(tmp_path), *command[1:]])
        out = capsys.readouterr().out
        assert "quintarion" not in out.lower(), command
    assert saved.read_bytes() == before

    context_statuses = {
        c["id"]: c["status"] for c in load_glossary(tmp_path)["concepts"]
    }
    assert context_statuses == {"ledger-batch": "canonical", "gate": "proposed"}

    (tmp_path / REPORT_FILE).unlink()
    assert saved.read_bytes() == before
    assert main(["show", str(tmp_path)]) == 0
    assert "Ledger batch" in capsys.readouterr().out
