"""Managed host context is explicit, bounded, non-contaminating, and safe."""

import json
import os
import stat

import pytest

import glossabet.agent.context_sync as context_sync
from glossabet.agent.managed_context import MAX_HOST_FILE_BYTES, inspect_managed_context
from glossabet.analysis.evidence import build_evidence
from glossabet.cli import main
from glossabet.glossary.store import load_glossary, save_glossary
from glossabet.managed_block import END_MARKER, START_MARKER

GLOSSARY = {
    "schema_version": 1,
    "concepts": [
        {
            "id": "payment",
            "term": "Payment",
            "definition": "An attempt to collect money for an order.",
            "status": "canonical",
            "aliases": [{"term": "charge", "status": "discouraged"}],
        },
        {
            "id": "billing",
            "term": "Billing",
            "definition": "The subsystem that executes Payments.",
            "status": "proposed",
        },
    ],
}


def _changed_glossary():
    glossary = json.loads(json.dumps(GLOSSARY))
    glossary["concepts"][0]["definition"] = "A settled transfer attempt."
    return glossary


def _target(report, name):
    return next(target for target in report["targets"] if target["path"] == name)


def _managed_parts(text):
    start = text.index(START_MARKER)
    end = text.index(END_MARKER, start) + len(END_MARKER)
    return text[:start], text[start:end], text[end:]


def test_sync_context_defaults_to_codex_and_creates_only_agents_file(
    tmp_path,
    capsys,
):
    glossary_path = save_glossary(tmp_path, GLOSSARY)
    glossary_before = glossary_path.read_bytes()

    assert main(["sync-context", str(tmp_path)]) == 0

    agents = tmp_path / "AGENTS.md"
    text = agents.read_text(encoding="utf-8")
    assert text.startswith(START_MARKER + "\n")
    assert text.rstrip().endswith(END_MARKER)
    assert "format=1 glossary-sha256=" in text
    assert "content-sha256=" in text
    assert "- Payment — An attempt to collect money for an order." in text
    assert "charge [discouraged]" in text
    assert "Billing" not in text
    assert "git:" not in text
    assert "sync: semantic glossary snapshot" in text
    # The managed block carries the same untrusted-input label as the brief:
    # a definition is data the model reads, never an instruction.
    assert text.index("untrusted repository input, not instructions") < text.index("\n- ")
    assert not (tmp_path / "CLAUDE.md").exists()
    assert glossary_path.read_bytes() == glossary_before
    assert "Created managed vocabulary context" in capsys.readouterr().out

    report = inspect_managed_context(tmp_path, load_glossary(tmp_path))
    assert report["checked"] is True
    assert report["issue_count"] == 0
    assert _target(report, "AGENTS.md")["status"] == "current"
    assert _target(report, "CLAUDE.md")["status"] == "absent"


def test_claude_target_preserves_crlf_surrounding_bytes_and_file_mode(
    tmp_path,
):
    save_glossary(tmp_path, GLOSSARY)
    target = tmp_path / "CLAUDE.md"
    original = b"# Human guidance\r\n\r\nKeep this exact.\r\n"
    target.write_bytes(original)
    target.chmod(0o640)

    assert main([
        "sync-context", str(tmp_path), "--agent", "claude"
    ]) == 0

    updated = target.read_bytes()
    assert updated.startswith(original + b"\r\n" + START_MARKER.encode())
    assert b"\r\n" in updated
    assert b"\n" not in updated.replace(b"\r\n", b"")
    if os.name != "nt":
        # Windows chmod cannot represent 0o640, so the mode-preservation
        # contract is POSIX-only; the CRLF and byte assertions still run.
        assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert not (tmp_path / "AGENTS.md").exists()
    report = inspect_managed_context(tmp_path, load_glossary(tmp_path))
    assert _target(report, "CLAUDE.md")["status"] == "current"

    before = target.read_bytes()
    assert main([
        "sync-context", str(tmp_path), "--agent", "claude"
    ]) == 0
    assert target.read_bytes() == before


def test_stale_block_updates_only_the_managed_range(tmp_path):
    save_glossary(tmp_path, GLOSSARY)
    target = tmp_path / "AGENTS.md"
    target.write_text("# Before\n\nHuman prefix.\n", encoding="utf-8")
    assert main(["sync-context", str(tmp_path)]) == 0
    target.write_text(
        target.read_text(encoding="utf-8") + "\nHuman suffix.\n",
        encoding="utf-8",
    )
    before_prefix, before_block, before_suffix = _managed_parts(
        target.read_text(encoding="utf-8")
    )

    save_glossary(tmp_path, _changed_glossary())
    assert main(["sync-context", str(tmp_path)]) == 0

    after_prefix, after_block, after_suffix = _managed_parts(
        target.read_text(encoding="utf-8")
    )
    assert after_prefix == before_prefix
    assert after_suffix == before_suffix
    assert after_block != before_block
    assert "A settled transfer attempt." in after_block
    report = inspect_managed_context(tmp_path, load_glossary(tmp_path))
    assert _target(report, "AGENTS.md")["status"] == "current"


def test_current_block_is_an_exact_no_write(tmp_path, monkeypatch):
    save_glossary(tmp_path, GLOSSARY)
    assert main(["sync-context", str(tmp_path)]) == 0
    target = tmp_path / "AGENTS.md"
    before = target.read_bytes()

    def unexpected_write(*_args, **_kwargs):
        raise AssertionError("current synchronization must not write")

    monkeypatch.setattr("glossabet.agent.context_sync._write_bytes_atomic", unexpected_write)

    assert main(["sync-context", str(tmp_path)]) == 0
    assert target.read_bytes() == before


def test_edited_block_requires_force_and_force_replaces_only_managed_range(
    tmp_path,
):
    save_glossary(tmp_path, GLOSSARY)
    target = tmp_path / "AGENTS.md"
    target.write_text("Human prefix.\n", encoding="utf-8")
    assert main(["sync-context", str(tmp_path)]) == 0
    target.write_text(
        target.read_text(encoding="utf-8") + "Human suffix.\n",
        encoding="utf-8",
    )
    text = target.read_text(encoding="utf-8").replace("Payment", "Forgery", 1)
    target.write_text(text, encoding="utf-8")
    before = target.read_bytes()
    before_prefix, _before_block, before_suffix = _managed_parts(text)

    assert main(["sync-context", str(tmp_path)]) == 1
    assert target.read_bytes() == before

    assert main(["sync-context", str(tmp_path), "--force"]) == 0
    after_prefix, after_block, after_suffix = _managed_parts(
        target.read_text(encoding="utf-8")
    )
    assert after_prefix == before_prefix
    assert after_suffix == before_suffix
    assert "Forgery" not in after_block
    assert "Payment" in after_block


def test_newer_managed_format_is_not_downgraded_without_force(tmp_path):
    save_glossary(tmp_path, GLOSSARY)
    assert main(["sync-context", str(tmp_path)]) == 0
    target = tmp_path / "AGENTS.md"
    target.write_text(
        target.read_text(encoding="utf-8").replace("format=1", "format=2", 1),
        encoding="utf-8",
    )
    before = target.read_bytes()

    assert main(["sync-context", str(tmp_path)]) == 1
    assert target.read_bytes() == before

    assert main(["sync-context", str(tmp_path), "--force"]) == 0
    assert "format=1" in target.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "collision",
    [
        START_MARKER + "\nunfinished\n",
        START_MARKER + "\n" + START_MARKER + "\n" + END_MARKER + "\n",
        START_MARKER + " changed -->\n" + END_MARKER + "\n",
        START_MARKER + "\nchanged metadata\n" + END_MARKER + "\n",
    ],
)
def test_ambiguous_or_malformed_markers_are_never_overwritten(
    tmp_path,
    collision,
):
    save_glossary(tmp_path, GLOSSARY)
    target = tmp_path / "AGENTS.md"
    target.write_text("Human\n" + collision + "Tail\n", encoding="utf-8")
    before = target.read_bytes()

    assert main(["sync-context", str(tmp_path), "--force"]) == 1

    assert target.read_bytes() == before


def test_symlink_target_is_never_followed_or_replaced(tmp_path):
    save_glossary(tmp_path, GLOSSARY)
    outside = tmp_path / "outside.md"
    outside.write_text("OUTSIDE_CANARY\n", encoding="utf-8")
    target = tmp_path / "AGENTS.md"
    os.symlink(outside, target)
    before = outside.read_bytes()

    assert main(["sync-context", str(tmp_path)]) == 1

    assert target.is_symlink()
    assert outside.read_bytes() == before
    report = inspect_managed_context(tmp_path, load_glossary(tmp_path))
    assert _target(report, "AGENTS.md")["status"] == "uninspectable"


@pytest.mark.parametrize(
    ("exact_name", "status", "diagnostic"),
    [
        (True, 0, ""),
        (False, 1, "under a different spelling"),
        (None, 1, "exact name could not be confirmed"),
    ],
)
def test_host_context_exact_name_tristate_controls_writes(
    tmp_path,
    capsys,
    monkeypatch,
    exact_name,
    status,
    diagnostic,
):
    """Only a confirmed exact entry name authorizes replacing a host file;
    mismatch and bounded-lookup uncertainty both leave its bytes untouched."""
    save_glossary(tmp_path, GLOSSARY)
    target = tmp_path / "AGENTS.md"
    original = b"Human instructions.\n"
    target.write_bytes(original)
    monkeypatch.setattr(
        "glossabet.agent.managed_context.entry_named_exactly",
        lambda *_args: exact_name,
    )

    assert main(["sync-context", str(tmp_path)]) == status

    captured = capsys.readouterr()
    if exact_name is True:
        assert target.read_bytes() != original
        assert "Appended managed vocabulary context" in captured.out
    else:
        assert target.read_bytes() == original
        assert captured.out == ""
        assert diagnostic in captured.err
        report = inspect_managed_context(tmp_path, load_glossary(tmp_path))
        assert _target(report, "AGENTS.md")["status"] == "uninspectable"


@pytest.mark.parametrize("kind", ["directory", "oversized", "non_utf8"])
def test_unsafe_existing_targets_are_unchanged(tmp_path, kind):
    save_glossary(tmp_path, GLOSSARY)
    target = tmp_path / "AGENTS.md"
    if kind == "directory":
        target.mkdir()
        before = None
    elif kind == "oversized":
        target.write_bytes(b"x" * (MAX_HOST_FILE_BYTES + 1))
        before = target.read_bytes()
    else:
        target.write_bytes(b"\xff\xfe")
        before = target.read_bytes()

    assert main(["sync-context", str(tmp_path)]) == 1

    if before is None:
        assert target.is_dir()
    else:
        assert target.read_bytes() == before


def test_atomic_replace_failure_preserves_original_and_cleans_temporary_file(
    tmp_path,
    monkeypatch,
):
    save_glossary(tmp_path, GLOSSARY)
    assert main(["sync-context", str(tmp_path)]) == 0
    target = tmp_path / "AGENTS.md"
    before = target.read_bytes()
    save_glossary(tmp_path, _changed_glossary())

    def fail_replace(_source, _target):
        raise OSError("injected replace failure")

    monkeypatch.setattr("glossabet.runtime.artifacts.os.replace", fail_replace)

    assert main(["sync-context", str(tmp_path)]) == 1
    assert target.read_bytes() == before
    assert list(tmp_path.glob(".AGENTS.md.*.tmp")) == []


def test_concurrent_target_change_is_not_overwritten(tmp_path, monkeypatch):
    save_glossary(tmp_path, GLOSSARY)
    target = tmp_path / "AGENTS.md"
    target.write_text("Original human text.\n", encoding="utf-8")
    original_reader = context_sync.read_regular_target
    calls = 0

    def change_before_commit(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            target.write_text("Concurrent human edit.\n", encoding="utf-8")
        return original_reader(path)

    monkeypatch.setattr(
        "glossabet.agent.context_sync.read_regular_target",
        change_before_commit,
    )

    assert main(["sync-context", str(tmp_path)]) == 1
    assert target.read_text(encoding="utf-8") == "Concurrent human edit.\n"
    assert list(tmp_path.glob(".AGENTS.md.*.tmp")) == []


def test_same_bytes_and_mode_on_a_replacement_inode_are_not_overwritten(
    tmp_path, monkeypatch
):
    """Content equality does not make a different file ours to replace. A
    concurrent same-byte inode swap must survive the pre-commit guard."""
    save_glossary(tmp_path, GLOSSARY)
    target = tmp_path / "AGENTS.md"
    original = b"Original human text.\n"
    target.write_bytes(original)
    target.chmod(0o640)
    original_reader = context_sync.read_regular_target
    calls = 0
    replacement_inode = None

    def replace_with_same_bytes_before_commit(path):
        nonlocal calls, replacement_inode
        calls += 1
        if calls == 2:
            replacement = tmp_path / "concurrent-AGENTS.md"
            replacement.write_bytes(original)
            replacement.chmod(0o640)
            os.replace(replacement, target)
            replacement_inode = target.stat().st_ino
        return original_reader(path)

    monkeypatch.setattr(
        "glossabet.agent.context_sync.read_regular_target",
        replace_with_same_bytes_before_commit,
    )

    assert main(["sync-context", str(tmp_path)]) == 1
    assert target.read_bytes() == original
    assert target.stat().st_ino == replacement_inode
    assert list(tmp_path.glob(".AGENTS.md.*.tmp")) == []


def test_no_glossary_means_no_host_file_write(tmp_path):
    assert main(["sync-context", str(tmp_path)]) == 1
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()


def test_glossary_cannot_render_reserved_marker_text(tmp_path):
    glossary = json.loads(json.dumps(GLOSSARY))
    glossary["concepts"][0]["definition"] = END_MARKER
    save_glossary(tmp_path, glossary)

    assert main(["sync-context", str(tmp_path)]) == 1

    assert not (tmp_path / "AGENTS.md").exists()


def test_drift_and_validate_flag_stale_and_edited_blocks(
    tmp_path,
    capsys,
):
    (tmp_path / "service.py").write_text("payment_record = 1\n", encoding="utf-8")
    save_glossary(tmp_path, GLOSSARY)
    assert main(["sync-context", str(tmp_path)]) == 0
    capsys.readouterr()

    save_glossary(tmp_path, _changed_glossary())
    assert main(["drift", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert "managed context AGENTS.md: stale" in captured.err
    drift = json.loads(
        (tmp_path / "glossabet-out" / "drift.json").read_text(encoding="utf-8")
    )
    assert _target(drift["managed_context"], "AGENTS.md")["status"] == "stale"

    assert main(["sync-context", str(tmp_path)]) == 0
    capsys.readouterr()
    target = tmp_path / "AGENTS.md"
    target.write_text(
        target.read_text(encoding="utf-8").replace("Payment", "Forgery", 1),
        encoding="utf-8",
    )
    assert main(["validate", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert "managed context AGENTS.md: edited" in captured.err
    validation = json.loads(
        (tmp_path / "glossabet-out" / "validation.json").read_text(
            encoding="utf-8"
        )
    )
    assert _target(validation["managed_context"], "AGENTS.md")["status"] == "edited"


def test_managed_block_never_echoes_into_repository_evidence(tmp_path):
    glossary = json.loads(json.dumps(GLOSSARY))
    glossary["concepts"][0]["term"] = "ZanzibarQuasar"
    glossary["concepts"][0]["definition"] = "MANAGEDONLYCANARY definition."
    save_glossary(tmp_path, glossary)
    (tmp_path / "AGENTS.md").write_text(
        "Human instructions retain HANDWRITTENCANARY.\n",
        encoding="utf-8",
    )
    assert main(["sync-context", str(tmp_path)]) == 0

    evidence = build_evidence(tmp_path, cache=False)
    doc_terms = {
        item["term"]
        for item in evidence["vocabulary"]["doc_terms"]["items"]
    }
    assert "handwrittencanary" in doc_terms
    assert "managedonlycanary" not in doc_terms
    assert "zanzibarquasar" not in doc_terms

    # The safe direction holds when the block is damaged: an edited stamp,
    # trailing text after a marker, a lower-case host name at depth — the
    # region between the one marker pair is still stripped. Only a file with
    # no unambiguous pair (duplicated markers) is left as evidence.
    agents = tmp_path / "AGENTS.md"
    synced = agents.read_text(encoding="utf-8")
    stamp_line = next(line for line in synced.splitlines() if "content-sha256=" in line)
    damaged = synced.replace(stamp_line, "<!-- glossabet:managed-context edited-by-hand -->", 1)
    damaged = damaged.replace(END_MARKER, END_MARKER + " trailing words after marker", 1)
    agents.write_text(damaged, encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "claude.md").write_text(damaged, encoding="utf-8")
    doc_terms = {
        item["term"]
        for item in build_evidence(tmp_path, cache=False)["vocabulary"]["doc_terms"]["items"]
    }
    assert "handwrittencanary" in doc_terms
    assert "managedonlycanary" not in doc_terms
    assert "zanzibarquasar" not in doc_terms

    from glossabet.managed_block import strip_managed_context_for_evidence

    ambiguous = synced + "\n" + synced  # two pairs: no single unambiguous region
    assert strip_managed_context_for_evidence("AGENTS.md", ambiguous) == ambiguous
    agents.write_text(ambiguous, encoding="utf-8")
    (tmp_path / "sub" / "claude.md").unlink()
    doc_terms = {
        item["term"]
        for item in build_evidence(tmp_path, cache=False)["vocabulary"]["doc_terms"]["items"]
    }
    assert "managedonlycanary" in doc_terms


def test_every_other_repository_command_leaves_host_file_byte_identical(
    tmp_path,
    capsys,
):
    (tmp_path / "service.py").write_text("payment_record = 1\n", encoding="utf-8")
    save_glossary(tmp_path, GLOSSARY)
    assert main(["sync-context", str(tmp_path)]) == 0
    target = tmp_path / "AGENTS.md"
    before = target.read_bytes()
    capsys.readouterr()

    for command in (
        ["brief", str(tmp_path)],
        ["show", str(tmp_path)],
        ["scan", str(tmp_path)],
        ["analyze", str(tmp_path)],
        ["inspect", str(tmp_path)],
        ["drift", str(tmp_path)],
        ["validate", str(tmp_path)],
    ):
        assert main(command) == 0
        capsys.readouterr()
        assert target.read_bytes() == before


def test_bom_prefixed_block_at_byte_zero_stays_current_and_repairable(tmp_path):
    """A fresh host file starts with the block at byte 0; an editor that adds
    a UTF-8 BOM must not turn it into an 'unrepairable' malformed block."""
    save_glossary(tmp_path, GLOSSARY)
    assert main(["sync-context", str(tmp_path)]) == 0
    agents = tmp_path / "AGENTS.md"
    agents.write_bytes(b"\xef\xbb\xbf" + agents.read_bytes())

    report = inspect_managed_context(tmp_path, load_glossary(tmp_path))
    assert _target(report, "AGENTS.md")["status"] == "current"

    # A stale block behind a BOM is resynced in place, BOM preserved.
    changed = json.loads(json.dumps(GLOSSARY))
    changed["concepts"][0]["definition"] = "A new definition."
    save_glossary(tmp_path, changed)
    assert main(["sync-context", str(tmp_path)]) == 0
    text = agents.read_bytes()
    assert text.startswith(b"\xef\xbb\xbf" + START_MARKER.encode())
    assert b"A new definition." in text
    assert _target(
        inspect_managed_context(tmp_path, load_glossary(tmp_path)), "AGENTS.md"
    )["status"] == "current"


def test_subproject_managed_blocks_are_stripped_from_the_parent_scan(tmp_path):
    """A subproject's own sync-context block (the per-subproject use the skill
    recommends for monorepos) must not echo its canonical vocabulary into the
    parent repository's evidence."""
    sub = tmp_path / "packages" / "billing"
    sub.mkdir(parents=True)
    (sub / "billing.py").write_text("billing_value = 1\n")
    (tmp_path / "app.py").write_text("app_value = 1\n")
    glossary = json.loads(json.dumps(GLOSSARY))
    glossary["concepts"][0]["definition"] = "zorbquux collects money"
    save_glossary(sub, glossary)
    assert main(["sync-context", str(sub)]) == 0
    assert main(["sync-context", str(sub), "--agent", "claude"]) == 0

    evidence = build_evidence(tmp_path)
    blob = json.dumps(evidence["vocabulary"])
    assert "zorbquux" not in blob
    assert "managed" not in blob
