"""Drift detection: the seeded scenario from the plan — a concept renamed in
new code must be caught with correct evidence — plus the other three checks,
bounds, determinism, and the no-glossary path."""

import json

from glossarize.cli import main
from glossarize.drift import build_drift
from glossarize.evidence import build_evidence
from glossarize.glossary import save_glossary

GLOSSARY = {
    "schema_version": 1,
    "concepts": [
        {
            "id": "run",
            "term": "Run",
            "definition": "A single invocation of the pipeline.",
            "status": "canonical",
            "aliases": [
                {"term": "charge", "status": "discouraged",
                 "note": "wrong domain, never adopted"},
            ],
        },
        {
            "id": "workspace",
            "term": "Workspace",
            "definition": "A user's working area.",
            "status": "canonical",
        },
        {
            "id": "session",
            "term": "Session",
            "definition": "One connected interaction.",
            "status": "canonical",
        },
    ],
}


def make_repo(tmp_path):
    # Established vocabulary: run_* (canonical Run).
    (tmp_path / "runs.py").write_text(
        "run_record = 1\nrun_scheduler = 2\nstart_run = 3\nrun_record_id = 4\n"
    )
    # Seeded drift: new code says execution_* for the same shapes.
    (tmp_path / "exec_new.py").write_text(
        "execution_record = 1\nexecution_scheduler = 2\nstart_execution = 3\n"
    )
    # Discouraged term still spreading.
    (tmp_path / "gateway.py").write_text(
        "charge_request = 1\ncharge_total = 2\n"
    )
    # Canonical "Session" living three disjoint lives.
    for module, contexts in (
        ("auth", ["login", "cookie"]),
        ("db", ["transaction", "commit"]),
        ("ml", ["inference", "model"]),
    ):
        d = tmp_path / module
        d.mkdir()
        (d / "code.py").write_text(
            "\n".join(f"session_{c} = 1" for c in contexts) + "\n"
        )
    # "Workspace" appears nowhere: canonical-fading.
    save_glossary(tmp_path, GLOSSARY)
    return tmp_path


def drift_for(tmp_path):
    root = make_repo(tmp_path)
    return build_drift(build_evidence(root), GLOSSARY)


def test_seeded_rename_is_detected_with_evidence(tmp_path):
    parallel = drift_for(tmp_path)["parallel_terms"]["items"]
    finding = next(f for f in parallel if f["new_term"] == "execution")
    assert finding["canonical_term"] == "Run"
    assert finding["concept_id"] == "run"
    assert "record" in finding["evidence"]["shared_contexts"]
    assert finding["confidence"] in ("high", "medium")


def test_discouraged_term_in_use(tmp_path):
    in_use = drift_for(tmp_path)["watched_terms_in_use"]["items"]
    finding = next(f for f in in_use if f["term"] == "charge")
    assert finding["status"] == "discouraged"
    assert finding["evidence"]["count"] == 2
    assert finding["evidence"]["locations"][0]["path"] == "gateway.py"


def test_canonical_fading(tmp_path):
    fading = drift_for(tmp_path)["canonical_fading"]["items"]
    finding = next(f for f in fading if f["term"] == "Workspace")
    assert finding["confidence"] == "high"
    assert finding["evidence"]["token_counts"] == {"workspace": 0}


def test_canonical_overloaded(tmp_path):
    over = drift_for(tmp_path)["canonical_overloaded"]["items"]
    finding = next(f for f in over if f["term"] == "Session")
    assert len(finding["evidence"]["modules"]) >= 3


def test_terms_already_in_glossary_are_not_parallel_findings(tmp_path):
    # "charge" parallels nothing as a *new* term — it's a known alias and
    # belongs to the watched check, not the parallel check.
    parallel = drift_for(tmp_path)["parallel_terms"]["items"]
    assert all(f["new_term"] != "charge" for f in parallel)


def test_bounds_and_determinism(tmp_path):
    root = make_repo(tmp_path)
    first = build_drift(build_evidence(root), GLOSSARY)
    second = build_drift(build_evidence(root), GLOSSARY)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    for key in ("parallel_terms", "watched_terms_in_use",
                "canonical_fading", "canonical_overloaded"):
        assert "dropped_items" in first[key]


def test_drift_command_end_to_end(tmp_path, capsys):
    root = make_repo(tmp_path)
    assert main(["drift", str(root)]) == 0
    out = capsys.readouterr().out
    assert "paralleling canonical vocabulary" in out
    assert "still in use" in out
    assert "fading" in out
    assert "not verdicts" in out
    assert (root / "glossarize-out" / "drift.json").is_file()
    assert (root / "glossarize-out" / "evidence.json").is_file()


def test_drift_without_glossary_is_user_error(tmp_path, capsys):
    (tmp_path / "a.py").write_text("x_y = 1\n")
    assert main(["drift", str(tmp_path)]) == 1
    assert "no glossary" in capsys.readouterr().err
