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
    (pathlib's exists()/is_dir()/is_symlink() raise on EACCES)."""
    locked = tmp_path / "locked"
    (locked / "repo").mkdir(parents=True)
    locked.chmod(0)
    try:
        if os.access(locked / "repo", os.R_OK):
            return  # running as root: nothing is unreadable
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
    def broken(_argv):
        raise BrokenPipeError(32, "Broken pipe")

    monkeypatch.setattr("glossabet.cli._run", broken)
    monkeypatch.setattr("glossabet.cli._abandon_stdout", lambda: None)
    assert main([]) == 1
    assert capsys.readouterr().err == ""

    def full(_argv):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("glossabet.cli._run", full)
    assert main([]) == 1
    err = capsys.readouterr().err
    assert "No space left on device" in err and "Traceback" not in err


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


def test_root_inside_glossabet_out_is_refused(tmp_path):
    out = tmp_path / "glossabet-out"
    out.mkdir()
    assert main(["scan", str(out)]) == 1


def test_lone_surrogates_in_repository_text_render_as_escapes(tmp_path):
    """A non-UTF-8 directory name reaches Python as a surrogate-escaped str;
    printing it must render an escape, never raise UnicodeEncodeError."""
    from glossabet.runtime.display import escape_terminal_text

    assert escape_terminal_text("caf\udce9dir") == "caf\\udce9dir"
