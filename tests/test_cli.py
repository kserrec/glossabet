"""CLI contract tests: version reporting and the exit-status scheme
(0 success, 1 user error, 2 defect)."""

import pytest

from glossarize import __version__
from glossarize.cli import EXIT_USER_ERROR, main


def test_version_matches_package(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"glossarize {__version__}"


def test_no_command_is_user_error(capsys):
    assert main([]) == EXIT_USER_ERROR
    assert "usage" in capsys.readouterr().err.lower()


def test_unknown_command_is_user_error_not_argparse_2(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["frobnicate"])
    assert exc.value.code == EXIT_USER_ERROR


def test_scan_rejects_missing_path(capsys):
    assert main(["scan", "/nonexistent/path"]) == EXIT_USER_ERROR
    assert "not a directory" in capsys.readouterr().err


def test_install_help_states_the_default_agent(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["install", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "Codex by default" in output
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

    monkeypatch.setattr("glossarize.cli._run", fail)

    assert main([]) == 2

    error = capsys.readouterr().err
    assert "\x1b" not in error and "\x07" not in error
    assert "forged\nline" not in error
    assert "forged\\nline\\x1b]0;title\\x07" in error
