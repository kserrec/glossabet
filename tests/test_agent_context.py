"""The installed skill receives one fresh, bounded CLI-owned JSON context."""

import json
import os
from pathlib import Path

from glossabet import agent_context
from glossabet.agent_context import ROUTINE_AGENT_CONTEXT_TARGET_BYTES
from glossabet.cli import EXIT_USER_ERROR, main
from glossabet.evidence import build_evidence
from glossabet.glossary import save_glossary


def _concept(index: int) -> dict:
    return {
        "id": f"concept-{index}",
        "term": f"Concept {index}",
        "definition": f"Definition {index}.",
        "status": "canonical",
    }


def test_inspect_emits_versioned_context_and_refreshes_evidence(tmp_path, capsys):
    (tmp_path / "service.py").write_text("payment_service = 1\n")

    assert main(["inspect", str(tmp_path), "--no-graphify"]) == 0

    captured = capsys.readouterr()
    context = json.loads(captured.out)
    assert captured.err == ""
    assert context["context_schema_version"] == 2
    assert context["evidence_schema_version"] == 11
    assert context["freshness"]["status"] == "current"
    assert context["files"]["code"] == [
        {"language": "python", "path": "service.py", "role": "production"}
    ]
    assert context["glossary"] == {"present": False}
    assert context["coverage"]["corpus"]["complete"] is True
    assert context["coverage"]["context"]["projection"] == "lean"
    assert context["coverage"]["context"]["complete"] is False
    assert captured.out.endswith("\n")
    assert "\n " not in captured.out
    assert (tmp_path / "glossabet-out" / "evidence.json").is_file()


def test_inspect_output_is_deterministic_for_unchanged_inputs(tmp_path, capsys):
    (tmp_path / "service.py").write_text("payment_service = 1\n")

    assert main(["inspect", str(tmp_path), "--no-graphify"]) == 0
    first = capsys.readouterr().out
    assert main(["inspect", str(tmp_path), "--no-graphify"]) == 0
    second = capsys.readouterr().out

    assert second == first


def test_inspect_includes_only_validated_glossary_state(tmp_path, capsys):
    save_glossary(
        tmp_path,
        {"schema_version": 1, "concepts": [_concept(0)]},
    )

    assert main(["inspect", str(tmp_path), "--no-graphify"]) == 0

    context = json.loads(capsys.readouterr().out)
    assert context["glossary"]["present"] is True
    assert context["glossary"]["concepts"][0]["id"] == "concept-0"


def test_glossary_projection_truncation_is_visible_at_section_level(
    tmp_path, capsys
):
    concept = _concept(0)
    concept["definition"] = "d" * 600
    save_glossary(tmp_path, {"schema_version": 1, "concepts": [concept]})

    assert main(["inspect", str(tmp_path), "--no-graphify"]) == 0

    context = json.loads(capsys.readouterr().out)
    coverage = context["coverage"]["context"]
    assert coverage["complete"] is False
    assert "glossary" in coverage["affected_sections"]
    assert any(
        omission["path"] == "glossary.concepts.0.definition"
        and omission["kind"] == "string_characters"
        for omission in coverage["omissions"]
    )


def test_inspect_refuses_malformed_glossary_instead_of_treating_it_as_absent(
    tmp_path, capsys
):
    out = tmp_path / "glossabet-out"
    out.mkdir()
    (out / "glossary.json").write_text("{broken")

    assert main(["inspect", str(tmp_path), "--no-graphify"]) == EXIT_USER_ERROR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unreadable JSON" in captured.err


def test_context_sampling_is_explicit(tmp_path, capsys, monkeypatch):
    (tmp_path / "a.py").write_text("first_name = 1\n")
    (tmp_path / "b.py").write_text("second_name = 2\n")
    monkeypatch.setitem(agent_context._LIST_LIMITS, ("files", "code"), 1)

    assert main(["inspect", str(tmp_path), "--no-graphify"]) == 0

    context = json.loads(capsys.readouterr().out)
    coverage = context["coverage"]["context"]
    assert coverage["complete"] is False
    assert {
        "path": "files.code", "kind": "list_items", "amount": 1
    } in coverage["omissions"]
    assert coverage["omission_counts"]["list_items"] >= 1
    assert coverage["omitted_amounts"]["list_items"] >= 1
    assert len(context["files"]["code"]) == 1


def test_lean_projection_rolls_up_locations_and_keeps_read_targets(tmp_path):
    auth = tmp_path / "auth"
    auth.mkdir()
    (auth / "service.py").write_text("payment_service = payment_router\n")
    (auth / "worker.py").write_text("payment_service = payment_worker\n")
    database = tmp_path / "database"
    database.mkdir()
    (database / "store.py").write_text("payment_store = payment_router\n")

    context = agent_context.build_agent_context(
        build_evidence(tmp_path, cache=False),
        None,
    )

    payment = next(
        item
        for item in context["vocabulary"]["tokens"]["items"]
        if item["term"] == "payment"
    )
    assert "locations" not in payment
    assert payment["module_counts"] == {"auth": 4, "database": 2}
    assert payment["module_counts_truncated"] is False

    nomination = next(
        item
        for item in context["naming_candidates"]["terms"]
        if item["term"] == "payment"
    )
    assert {location["path"] for location in nomination["locations"]} == {
        "auth/service.py",
        "auth/worker.py",
        "database/store.py",
    }

    exemplar = next(
        item
        for item in context["terminology"]["register"]["exemplars"]["items"]
        if item["name"] == "payment_service"
    )
    assert exemplar["style"] == "snake_case"
    assert {location["path"] for location in exemplar["locations"]} == {
        "auth/service.py",
        "auth/worker.py",
    }
    rollup_omission = next(
        omission
        for omission in context["coverage"]["context"]["omissions"]
        if omission["path"] == "vocabulary.tokens.items.*.locations"
    )
    assert rollup_omission["kind"] == "file_locations_rolled_up"
    assert rollup_omission["amount"] > 0


def test_full_projection_retains_detailed_vocabulary_locations(tmp_path, capsys):
    (tmp_path / "service.py").write_text("payment_service = 1\n")

    assert main([
        "inspect", str(tmp_path), "--no-graphify", "--full",
    ]) == 0

    context = json.loads(capsys.readouterr().out)
    token = context["vocabulary"]["tokens"]["items"][0]
    assert context["coverage"]["context"]["projection"] == "full"
    assert "locations" in token
    assert "module_counts" not in token
    assert "exemplars" not in context["terminology"]["register"]


def test_glossabet_routine_context_fits_the_soft_target():
    root = Path(__file__).resolve().parents[1]
    evidence = build_evidence(root, cache=False)
    context = agent_context.build_agent_context(evidence, None)

    size = len(agent_context.serialize_agent_context(context).encode("utf-8"))

    assert size <= ROUTINE_AGENT_CONTEXT_TARGET_BYTES, size


def test_too_many_context_omissions_fail_instead_of_becoming_ambiguous(
    tmp_path, capsys, monkeypatch
):
    (tmp_path / "a.py").write_text("alpha_beta_gamma = 1\n")
    (tmp_path / "b.py").write_text("delta_epsilon_zeta = 2\n")
    monkeypatch.setattr(agent_context, "MAX_AGENT_CONTEXT_OMISSION_RECORDS", 1)
    monkeypatch.setitem(agent_context._LIST_LIMITS, ("files", "code"), 1)
    monkeypatch.setitem(
        agent_context._LIST_LIMITS, ("vocabulary", "tokens", "items"), 1
    )

    assert main(["inspect", str(tmp_path), "--no-graphify"]) == EXIT_USER_ERROR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "requires more than 1 omission records" in captured.err


def test_context_hard_byte_limit_fails_cleanly(tmp_path, capsys, monkeypatch):
    (tmp_path / "a.py").write_text("ordinary_name = 1\n")
    monkeypatch.setattr(agent_context, "MAX_AGENT_CONTEXT_BYTES", 50)

    assert main(["inspect", str(tmp_path), "--no-graphify"]) == EXIT_USER_ERROR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "50-byte output limit" in captured.err


def test_inspect_rejects_symlinked_glossary_without_reading_target(
    tmp_path, capsys
):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"schema_version": 1, "concepts": []}))
    repo = tmp_path / "repo"
    out = repo / "glossabet-out"
    out.mkdir(parents=True)
    os.symlink(outside, out / "glossary.json")

    assert main(["inspect", str(repo), "--no-graphify"]) == EXIT_USER_ERROR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "symlinked artifact paths are not trusted" in captured.err


def test_inspect_rejects_oversized_glossary(tmp_path, capsys, monkeypatch):
    out = tmp_path / "glossabet-out"
    out.mkdir()
    (out / "glossary.json").write_text(
        json.dumps({"schema_version": 1, "concepts": [_concept(0)]})
    )
    monkeypatch.setattr("glossabet.glossary.MAX_JSON_BYTES", 20)
    monkeypatch.setattr("glossabet.artifacts.MAX_JSON_BYTES", 20)

    assert main(["inspect", str(tmp_path), "--no-graphify"]) == EXIT_USER_ERROR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "larger than 20 bytes" in captured.err
