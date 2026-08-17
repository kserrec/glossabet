"""The run contract (Phase 36.2): one preamble decides, for every
repository command, whether a glossary is needed and how a bad or missing
one is reported. These cases replace the per-command repeats of
``main([...]) == 1`` + a stderr substring."""

import json

import pytest

from glossabet.cli import EXIT_USER_ERROR, main
from glossabet.engine_run import (
    GLOSSARY_OPTIONAL,
    GLOSSARY_REQUIRED,
    RunError,
    open_run,
)
from glossabet.glossary import save_glossary

GLOSSARY = {
    "schema_version": 1,
    "concepts": [
        {"id": "payment", "term": "Payment", "definition": "d",
         "status": "canonical"},
    ],
}

# Every repository command, with the flags that keep it cheap.
COMMANDS = {
    "scan": ["scan", "--no-graphify"],
    "analyze": ["analyze", "--no-graphify"],
    "inspect": ["inspect", "--no-graphify"],
    "brief": ["brief"],
    "show": ["show"],
    "save": ["save"],
    "sync-context": ["sync-context"],
    "drift": ["drift"],
    "validate": ["validate"],
}
GLOSSARY_READERS = ("inspect", "brief", "show", "sync-context", "drift",
                    "validate")
GLOSSARY_REQUIRERS = ("sync-context", "drift", "validate")


def _argv(name, root):
    return COMMANDS[name] + [str(root)]


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_every_command_rejects_a_missing_directory_the_same_way(
    name, tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr("sys.stdin", open(__file__))  # save reads stdin
    missing = tmp_path / "no\x1bdir"

    assert main(_argv(name, missing)) == EXIT_USER_ERROR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "glossabet: not a directory: " + str(
        missing).replace("\x1b", "\\x1b") + "\n"


@pytest.mark.parametrize("name", GLOSSARY_READERS)
def test_every_glossary_reader_refuses_a_malformed_glossary_as_a_user_error(
    name, tmp_path, capsys
):
    (tmp_path / "a.py").write_text("payment_id = 1\n")
    out = tmp_path / "glossabet-out"
    out.mkdir()
    (out / "glossary.json").write_text("{broken")

    assert main(_argv(name, tmp_path)) == EXIT_USER_ERROR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("glossabet: ")
    assert "unreadable JSON" in captured.err
    assert "internal error" not in captured.err
    # A malformed glossary is refused before any evidence is built.
    assert not (out / "evidence.json").exists()


@pytest.mark.parametrize("name", GLOSSARY_REQUIRERS)
def test_every_glossary_requirer_reports_an_absent_glossary_the_same_way(
    name, tmp_path, capsys
):
    (tmp_path / "a.py").write_text("payment_id = 1\n")

    assert main(_argv(name, tmp_path)) == EXIT_USER_ERROR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("glossabet: no glossary to ")
    assert captured.err.rstrip("\n").endswith(
        "— run /glossabet and settle terms first (glossabet-out/glossary.json)"
    )
    assert not (tmp_path / "glossabet-out").exists()


@pytest.mark.parametrize(
    "name", [c for c in GLOSSARY_READERS if c not in GLOSSARY_REQUIRERS]
)
def test_optional_readers_run_without_a_glossary(name, tmp_path, capsys):
    (tmp_path / "a.py").write_text("payment_id = 1\n")

    assert main(_argv(name, tmp_path)) == 0
    assert "glossabet:" not in capsys.readouterr().err


def test_open_run_policies(tmp_path):
    with pytest.raises(RunError, match="not a directory"):
        open_run(str(tmp_path / "nope"))
    with pytest.raises(RunError, match="no glossary to test"):
        open_run(str(tmp_path), glossary=GLOSSARY_REQUIRED,
                 missing="no glossary to test")
    assert open_run(str(tmp_path), glossary=GLOSSARY_OPTIONAL).glossary is None
    save_glossary(tmp_path, GLOSSARY)
    run = open_run(str(tmp_path), glossary=GLOSSARY_REQUIRED, missing="x")
    assert run.root == tmp_path.resolve()
    assert json.dumps(run.glossary, sort_keys=True) == json.dumps(
        GLOSSARY, sort_keys=True
    )
    # "none" never reads the glossary, so a malformed one is not its problem.
    (tmp_path / "glossabet-out" / "glossary.json").write_text("{broken")
    assert open_run(str(tmp_path)).glossary is None
