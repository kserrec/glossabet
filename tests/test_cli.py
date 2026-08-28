"""CLI contract tests: version reporting and the exit-status scheme
(0 success, 1 user error, 2 defect)."""

import os

import pytest

from glossabet import __version__
from glossabet.cli import EXIT_USER_ERROR, main


def test_version_matches_package(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"glossabet {__version__}"


def test_version_whose_output_cannot_be_written_is_not_a_success(monkeypatch):
    """argparse's --version/--help exit 0 after printing; if that print never
    reached the reader (disk full, pipe gone), reporting success would be a
    lie. The guarded flush turns it into exit 1 and abandons stdout so the
    interpreter's own exit-time flush stays quiet. A usage error keeps its
    own status (the parser's user-error exit): it was never a success."""
    import io
    import sys

    class FullDisk(io.StringIO):
        def flush(self):
            raise OSError(28, "No space left on device")

    abandoned = []
    monkeypatch.setattr("glossabet.cli._abandon_stdout", lambda: abandoned.append(True))
    monkeypatch.setattr(sys, "stdout", FullDisk())
    assert main(["--version"]) == EXIT_USER_ERROR
    assert abandoned == [True]

    monkeypatch.setattr(sys, "stderr", io.StringIO())
    with pytest.raises(SystemExit) as usage:
        main(["--no-such-flag"])
    assert usage.value.code == EXIT_USER_ERROR
    assert abandoned == [True, True]


def test_no_command_is_user_error(capsys):
    assert main([]) == EXIT_USER_ERROR
    assert "usage" in capsys.readouterr().err.lower()


def test_unknown_command_is_user_error_not_argparse_2(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["frobnicate"])
    assert exc.value.code == EXIT_USER_ERROR


def test_install_help_states_the_default_agent(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["install", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "Codex by default" in output
    assert "--force" in output


def test_sync_context_help_names_the_exact_default_target(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["sync-context", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "AGENTS.md for Codex (default)" in output
    assert "CLAUDE.md for Claude" in output
    assert "--force" in output


def test_repository_control_sequences_are_rendered_visibly(capsys):
    hostile_path = (
        "missing\nforged\t\r\x1b]8;;https://example.invalid\x07\u202ename"
    )

    assert main(["scan", hostile_path]) == EXIT_USER_ERROR

    error = capsys.readouterr().err
    assert "\x1b" not in error
    assert "\x07" not in error
    assert "\u202e" not in error
    assert "missing\nforged" not in error
    for visible in ("\\n", "\\t", "\\r", "\\x1b", "\\x07", "\\u202e"):
        assert visible in error


def test_unexpected_exception_text_is_terminal_safe(capsys, monkeypatch):
    def fail(_argv):
        raise RuntimeError("forged\nline\x1b]0;title\x07")

    monkeypatch.setattr("glossabet.cli._run", fail)

    assert main([]) == 2

    error = capsys.readouterr().err
    assert "\x1b" not in error and "\x07" not in error
    assert "forged\nline" not in error
    assert "forged\\nline\\x1b]0;title\\x07" in error


def test_permission_errors_are_user_errors_not_internal_defects(tmp_path, capsys):
    """An unreadable repository or destination is the environment's fault:
    exit 1 with the OS reason, never a traceback and exit 2 blaming glossabet
    (pathlib predicate behavior differs by Python version, so path checks must
    not erase EACCES)."""
    locked = tmp_path / "locked"
    (locked / "repo").mkdir(parents=True)
    locked.chmod(0)
    try:
        if os.access(locked / "repo", os.R_OK):
            pytest.skip("running as root: nothing is unreadable")
        assert main(["brief", str(locked / "repo")]) == 1
        err = capsys.readouterr().err
        assert "Permission denied" in err and "Traceback" not in err
        assert main(["install", "--destination", str(locked / "skills")]) == 1
        err = capsys.readouterr().err
        assert "Permission denied" in err and "internal error" not in err
    finally:
        locked.chmod(0o755)


def test_stdout_write_failures_exit_one_quietly(monkeypatch, capsys):
    """A closed pipe (reader went away) exits 1 with nothing to say; a full
    disk exits 1 with the OS reason — neither is a defect, and neither may
    leave the interpreter to report an 'Exception ignored' exit 120."""
    abandoned = []
    monkeypatch.setattr("glossabet.cli._abandon_stdout", lambda: abandoned.append(True))

    def broken(_argv):
        raise BrokenPipeError(32, "Broken pipe")

    monkeypatch.setattr("glossabet.cli._run", broken)
    assert main([]) == 1
    assert capsys.readouterr().err == ""
    # The quiet exit depends on stdout being abandoned before the interpreter's
    # exit-time flush; a stub that merely swallowed the call proved nothing.
    assert abandoned == [True]

    def full(_argv):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("glossabet.cli._run", full)
    assert main([]) == 1
    err = capsys.readouterr().err
    assert "No space left on device" in err and "Traceback" not in err

    # End to end: a reader that closes the pipe early yields exit 1, not the
    # interpreter's 120 from an unflushable stdout.
    import subprocess
    import sys
    proc = subprocess.run(
        [sys.executable, "-c",
         "import os, sys; r, w = os.pipe(); os.close(r); os.dup2(w, 1)\n"
         "from glossabet.cli import main; sys.exit(main(['--help']))"],
        capture_output=True, timeout=30,
    )
    assert proc.returncode == 1, (proc.returncode, proc.stderr)
    assert b"Exception ignored" not in proc.stderr
    assert b"Traceback" not in proc.stderr


def test_output_never_crashes_on_a_narrow_console_encoding(tmp_path, monkeypatch):
    """A piped stdout on Windows uses the ANSI code page (cp932, cp1252) with
    strict errors; the fixed em dash in `show`/`brief`/error text used to raise
    UnicodeEncodeError and read as an internal defect (exit 2). Unencodable
    characters are rendered as visible escapes instead."""
    import io
    import json
    import subprocess
    import sys

    (tmp_path / "a.py").write_text("ledger_value = 1\n")
    glossary = {"schema_version": 1, "concepts": [{
        "id": "ledger", "term": "Ledger", "definition": "book \u2192 record",
        "status": "canonical",
    }]}
    proc = subprocess.run(
        [sys.executable, "-m", "glossabet", "save", str(tmp_path)],
        input=json.dumps(glossary), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    for command in ("show", "brief", "drift"):
        raw = io.BytesIO()
        narrow = io.TextIOWrapper(raw, encoding="cp932", errors="strict")
        monkeypatch.setattr(sys, "stdout", narrow)
        monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="cp932"))
        assert main([command, str(tmp_path)]) == 0, command
        narrow.flush()
        text = raw.getvalue().decode("cp932")
        assert "\\u2014" in text or "\\u2192" in text, command


def test_root_inside_glossabet_out_is_refused(tmp_path, capsys):
    """Scanning the output directory itself — or anything beneath it — would
    write glossabet-out/glossabet-out/ and read Glossabet's own artifacts as
    evidence. The refusal names that reason, so a bare exit 1 from any other
    cause (no glossary, unreadable root) cannot stand in for it."""
    out = tmp_path / "glossabet-out"
    nested = out / "deeper" / "repo"
    nested.mkdir(parents=True)
    (out / "evidence.json").write_text("{}\n", encoding="utf-8")
    (nested / "a.py").write_text("payment_service = 1\n")
    for root in (out, nested):
        assert main(["scan", str(root)]) == 1
        err = capsys.readouterr().err
        assert "inside a glossabet-out/ output directory" in err
        assert not (root / "glossabet-out").exists()


def test_output_ancestor_name_uses_filesystem_identity(
    tmp_path, capsys, monkeypatch
):
    """Case-insensitive filesystems preserve a directory's original case.

    Emulate their lowercase path lookup on this host: a physical
    ``Glossabet-Out`` that is also reached by the tool's ``glossabet-out``
    spelling is the same output directory and must be refused.
    """
    from pathlib import Path

    output = tmp_path / "Glossabet-Out"
    root = output / "repository"
    root.mkdir(parents=True)
    (output / "evidence.json").write_text("{}\n", encoding="utf-8")
    (root / "a.py").write_text("payment_service = 1\n", encoding="utf-8")
    lowercase_lookup = tmp_path / "glossabet-out"
    real_lstat = Path.lstat

    def case_insensitive_lstat(path, *args, **kwargs):
        if path == lowercase_lookup:
            return real_lstat(output, *args, **kwargs)
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", case_insensitive_lstat)

    assert main(["scan", str(root)]) == 1

    assert "inside a glossabet-out/ output directory" in capsys.readouterr().err
    assert not (root / "glossabet-out").exists()


def test_lowercase_symlink_does_not_claim_differently_cased_directory(
    tmp_path, capsys
):
    """Glossabet refuses symlinked artifact paths, so a lowercase symlink
    cannot turn an ordinary differently cased directory into owned output."""
    output = tmp_path / "Glossabet-Out"
    root = output / "ordinary-repository"
    root.mkdir(parents=True)
    (output / "evidence.json").write_text("{}\n", encoding="utf-8")
    (root / "a.py").write_text("payment_service = 1\n", encoding="utf-8")
    lowercase_lookup = tmp_path / "glossabet-out"
    lowercase_lookup.symlink_to(output, target_is_directory=True)

    assert main(["scan", str(root)]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert lowercase_lookup.is_symlink()
    assert (root / "glossabet-out" / "evidence.json").is_file()


def test_non_file_artifact_name_does_not_claim_output_ownership(
    tmp_path, capsys
):
    """Glossabet creates regular JSON artifact files; a directory with the
    same exact name is ordinary user state, not evidence of tool ownership."""
    output_name = tmp_path / "glossabet-out"
    (output_name / "evidence.json").mkdir(parents=True)
    root = output_name / "ordinary-repository"
    root.mkdir()
    (root / "a.py").write_text("payment_service = 1\n", encoding="utf-8")

    assert main(["scan", str(root)]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert (output_name / "evidence.json").is_dir()
    assert (root / "glossabet-out" / "evidence.json").is_file()


def test_unavailable_output_directory_identity_is_uncertain(
    tmp_path, capsys, monkeypatch
):
    """A platform stat result with no file identity cannot prove two path
    spellings name the same directory, even when ``samestat`` says they do."""
    import stat
    from pathlib import Path

    output = tmp_path / "Glossabet-Out"
    root = output / "repository"
    root.mkdir(parents=True)
    (output / "evidence.json").write_text("{}\n", encoding="utf-8")
    (root / "a.py").write_text("payment_service = 1\n", encoding="utf-8")
    lowercase_lookup = tmp_path / "glossabet-out"
    real_lstat = Path.lstat
    identity_unavailable = os.stat_result(
        (stat.S_IFDIR | 0o755, 0, 0, 1, 1, 1, 0, 0, 0, 0)
    )

    def unavailable_identity(path, *args, **kwargs):
        if path in {output, lowercase_lookup}:
            return identity_unavailable
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", unavailable_identity)

    assert main(["scan", str(root)]) == 1

    error = capsys.readouterr().err
    assert "output-directory ownership could not be proved" in error
    assert "artifact name could not be inspected" not in error
    assert "run glossabet on the repository root instead" not in error
    assert not (root / "glossabet-out").exists()


def test_unavailable_identity_without_artifact_does_not_claim_output(
    tmp_path, capsys, monkeypatch
):
    """Identity uncertainty matters only after a regular current artifact
    provides a reason to ask whether a case variant is the output directory."""
    import stat
    from pathlib import Path

    output_name = tmp_path / "glossabet-out"
    root = output_name / "ordinary-repository"
    root.mkdir(parents=True)
    (root / "a.py").write_text("payment_service = 1\n", encoding="utf-8")
    real_lstat = Path.lstat
    identity_unavailable = os.stat_result(
        (stat.S_IFDIR | 0o755, 0, 0, 1, 1, 1, 0, 0, 0, 0)
    )

    def unavailable_identity(path, *args, **kwargs):
        if path == output_name:
            return identity_unavailable
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", unavailable_identity)

    assert main(["scan", str(root)]) == 0

    assert capsys.readouterr().err == ""
    assert (root / "glossabet-out" / "evidence.json").is_file()


def test_unrelated_glossabet_out_ancestor_does_not_claim_the_repository(
    tmp_path, capsys
):
    """A directory name alone is not proof of tool ownership: an ordinary
    repository may live beneath an unrelated ancestor named glossabet-out."""
    root = tmp_path / "glossabet-out" / "ordinary-repository"
    root.mkdir(parents=True)
    # A similarly spelled ordinary file is not a current Glossabet artifact,
    # including on case-insensitive filesystems.
    (root.parent / "Evidence.json").write_text("ordinary\n", encoding="utf-8")
    (root / "a.py").write_text("payment_service = 1\n", encoding="utf-8")

    assert main(["scan", str(root)]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert (root / "glossabet-out" / "evidence.json").is_file()


def test_unconfirmable_output_ancestor_is_not_assumed_safe(
    tmp_path, capsys, monkeypatch
):
    """If an apparent artifact cannot be confirmed by exact entry name, the
    command reports uncertainty and makes no nested output write."""
    root = tmp_path / "glossabet-out" / "uncertain-repository"
    root.mkdir(parents=True)
    (root / "a.py").write_text("payment_service = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "glossabet.command_run.entry_named_exactly", lambda *_args: None
    )

    assert main(["scan", str(root)]) == 1

    assert (
        "output-directory ownership could not be proved"
        in capsys.readouterr().err
    )
    assert not (root / "glossabet-out").exists()


def test_output_artifact_lookup_error_is_uncertain(tmp_path, capsys, monkeypatch):
    """An exact artifact lookup error is uncertainty, not proven absence.

    ``os.path.lexists`` swallows every lstat error; the exact-name helper must
    preserve that distinction before a genuine output ancestor is accepted as
    an ordinary repository location.
    """
    from glossabet.corpus import path_policy

    output = tmp_path / "glossabet-out"
    root = output / "repository"
    root.mkdir(parents=True)
    artifact = output / "evidence.json"
    artifact.write_text("{}\n", encoding="utf-8")
    (root / "a.py").write_text("payment_service = 1\n", encoding="utf-8")
    real_lstat = os.lstat

    def uninspectable_artifact(path, *args, **kwargs):
        if os.fspath(path) == os.fspath(artifact):
            raise PermissionError("artifact lookup denied")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(path_policy.os, "lstat", uninspectable_artifact)

    assert main(["scan", str(root)]) == 1

    assert (
        "output-directory ownership could not be proved"
        in capsys.readouterr().err
    )
    assert not (root / "glossabet-out").exists()


def test_output_artifact_vanishing_during_name_confirmation_is_uncertain(
    tmp_path, capsys, monkeypatch
):
    """An artifact seen by the path lookup but absent from the immediately
    following listing is a race, so no nested output write is authorized."""
    from glossabet.corpus import path_policy

    output = tmp_path / "glossabet-out"
    root = output / "repository"
    root.mkdir(parents=True)
    artifact = output / "glossary.json"
    artifact.write_text("{}\n", encoding="utf-8")
    (root / "a.py").write_text("payment_service = 1\n", encoding="utf-8")
    real_scandir = os.scandir
    vanished = False

    def vanish_then_scan(directory):
        nonlocal vanished
        if os.fspath(directory) == os.fspath(output) and artifact.exists():
            artifact.unlink()
            vanished = True
        return real_scandir(directory)

    monkeypatch.setattr(path_policy.os, "scandir", vanish_then_scan)

    assert main(["scan", str(root)]) == 1

    assert vanished is True
    assert (
        "output-directory ownership could not be proved"
        in capsys.readouterr().err
    )
    assert not (root / "glossabet-out").exists()


def test_vanishing_output_artifact_is_not_explained_by_casefold_sibling(
    tmp_path, capsys, monkeypatch
):
    """A surviving differently cased file is not proof that it was the exact
    artifact reached before that separate exact file concurrently vanished."""
    from glossabet.corpus import path_policy

    output = tmp_path / "glossabet-out"
    root = output / "repository"
    root.mkdir(parents=True)
    exact = output / "evidence.json"
    sibling = output / "Evidence.JSON"
    exact.write_text("{}\n", encoding="utf-8")
    sibling.write_text("ordinary\n", encoding="utf-8")
    (root / "a.py").write_text("payment_service = 1\n", encoding="utf-8")
    real_scandir = os.scandir

    def vanish_exact_then_scan(directory):
        if os.fspath(directory) == os.fspath(output) and exact.exists():
            exact.unlink()
        return real_scandir(directory)

    monkeypatch.setattr(path_policy.os, "scandir", vanish_exact_then_scan)

    assert main(["scan", str(root)]) == 1

    assert sibling.read_text(encoding="utf-8") == "ordinary\n"
    assert (
        "output-directory ownership could not be proved"
        in capsys.readouterr().err
    )
    assert not (root / "glossabet-out").exists()


@pytest.mark.skipif(os.name == "nt", reason="requires two case-distinct hardlinks")
def test_restored_exact_hardlink_is_not_hidden_by_casefold_sibling(
    tmp_path, capsys, monkeypatch
):
    """Hardlinks share inode identity but remain separate directory entries.
    Restoring the exact link after the first listing must trigger uncertainty."""
    from glossabet.corpus import path_policy

    output = tmp_path / "glossabet-out"
    root = output / "repository"
    root.mkdir(parents=True)
    exact = output / "evidence.json"
    sibling = output / "EVIDENCE.JSON"
    exact.write_text("{}\n", encoding="utf-8")
    os.link(exact, sibling)
    (root / "a.py").write_text("payment_service = 1\n", encoding="utf-8")
    real_scandir = os.scandir
    raced = False

    class RestoreExactAfterListing:
        def __enter__(self):
            exact.unlink()
            self.entries = real_scandir(output)
            return self.entries.__enter__()

        def __exit__(self, exc_type, exc_value, traceback):
            nonlocal raced
            try:
                return self.entries.__exit__(exc_type, exc_value, traceback)
            finally:
                os.link(sibling, exact)
                raced = True

    def restore_between_listings(directory):
        if os.fspath(directory) == os.fspath(output) and not raced:
            return RestoreExactAfterListing()
        return real_scandir(directory)

    monkeypatch.setattr(path_policy.os, "scandir", restore_between_listings)

    assert main(["scan", str(root)]) == 1

    assert raced is True
    assert exact.is_file() and sibling.is_file()
    assert (
        "output-directory ownership could not be proved"
        in capsys.readouterr().err
    )
    assert not (root / "glossabet-out").exists()


def test_lone_surrogates_in_repository_text_render_as_escapes(tmp_path):
    """A non-UTF-8 directory name reaches Python as a surrogate-escaped str;
    printing it must render an escape, never raise UnicodeEncodeError."""
    from glossabet.runtime.display import escape_terminal_text

    assert escape_terminal_text("caf\udce9dir") == "caf\\udce9dir"
