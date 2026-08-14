"""Repository configuration and path roles keep analysis scope explicit."""

import json
import os

from glossarize.cli import main
from glossarize.evidence import build_evidence


def _write(path, content="role_specific_name = 1\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_default_path_roles_are_reported_and_only_production_drives_vocabulary(
    tmp_path,
):
    _write(tmp_path / "src" / "app.py", "production_boundary = 1\n")
    _write(tmp_path / "tests" / "test_app.py", "test_only_helper = 1\n")
    _write(
        tmp_path / "tests" / "fixtures" / "sample.py",
        "fixture_only_record = 1\n",
    )
    _write(tmp_path / "generated" / "api.py", "generated_only_client = 1\n")
    _write(tmp_path / "vendor" / "library.py", "vendored_only_library = 1\n")

    evidence = build_evidence(tmp_path)

    roles = {item["path"]: item["role"] for item in evidence["files"]["code"]}
    assert roles == {
        "src/app.py": "production",
        "tests/fixtures/sample.py": "fixture",
        "tests/test_app.py": "test",
    }
    assert evidence["totals"]["code_files_by_role"] == {
        "fixture": 1,
        "production": 1,
        "test": 1,
    }
    assert "generated" in evidence["skipped"]["generated"]
    assert "vendor" in evidence["skipped"]["vendored"]
    assert evidence["configuration"]["present"] is False
    assert evidence["terminology"]["scope"] == {
        "code_files": 1,
        "doc_files": 0,
        "roles": ["production"],
    }
    vocabulary = {
        item["term"] for item in evidence["vocabulary"]["tokens"]["items"]
    }
    assert "production" in vocabulary
    assert not {"test", "fixture", "generated", "vendored"} & vocabulary


def test_configured_prefixes_ignore_or_override_default_roles(tmp_path):
    config = {
        "schema_version": 1,
        "ignore_paths": ["scratch"],
        "path_roles": {
            "production": ["generated/maintained", "tests/product_contract"],
            "test": ["qa"],
            "fixture": ["sample_data"],
            "generated": ["api_output"],
            "vendored": ["third_party"],
        },
    }
    (tmp_path / "glossarize.json").write_text(json.dumps(config))
    _write(tmp_path / "scratch" / "ignored.py")
    _write(tmp_path / "qa" / "check.py")
    _write(tmp_path / "sample_data" / "case.py")
    _write(tmp_path / "api_output" / "client.py")
    _write(tmp_path / "third_party" / "library.py")
    _write(tmp_path / "generated" / "maintained" / "source.py")
    _write(tmp_path / "tests" / "product_contract" / "contract.py")

    evidence = build_evidence(tmp_path)

    roles = {item["path"]: item["role"] for item in evidence["files"]["code"]}
    assert roles == {
        "qa/check.py": "test",
        "sample_data/case.py": "fixture",
        "generated/maintained/source.py": "production",
        "tests/product_contract/contract.py": "production",
    }
    assert evidence["skipped"]["configured"] == ["scratch"]
    assert evidence["skipped"]["generated"] == ["api_output"]
    assert evidence["skipped"]["vendored"] == ["third_party"]
    assert evidence["configuration"] == {
        "file": "glossarize.json",
        "ignore_paths": ["scratch"],
        "path_roles": {
            "fixture": ["sample_data"],
            "generated": ["api_output"],
            "production": ["generated/maintained", "tests/product_contract"],
            "test": ["qa"],
            "vendored": ["third_party"],
        },
        "present": True,
        "schema_version": 1,
    }


def test_invalid_config_is_a_user_error(tmp_path, capsys):
    (tmp_path / "glossarize.json").write_text(json.dumps({
        "schema_version": 1,
        "ignore_paths": ["../outside"],
    }))
    _write(tmp_path / "main.py")

    assert main(["scan", str(tmp_path)]) == 1
    assert "glossarize.json" in capsys.readouterr().err


def test_symlinked_config_is_rejected_without_reading_target(tmp_path, capsys):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"schema_version": 1}))
    repository = tmp_path / "repository"
    repository.mkdir()
    _write(repository / "main.py")
    os.symlink(outside, repository / "glossarize.json")

    assert main(["scan", str(repository)]) == 1
    assert "symlinked artifact" in capsys.readouterr().err


def test_oversized_config_is_a_user_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("glossarize.config.MAX_CONFIG_BYTES", 20)
    (tmp_path / "glossarize.json").write_text(json.dumps({
        "schema_version": 1,
        "ignore_paths": ["too-large"],
    }))
    _write(tmp_path / "main.py")

    assert main(["scan", str(tmp_path)]) == 1
    assert "larger than" in capsys.readouterr().err


def test_cli_reports_production_scope_and_role_exclusions(tmp_path, capsys):
    _write(tmp_path / "main.py")
    _write(tmp_path / "tests" / "test_main.py")
    _write(tmp_path / "generated" / "client.py")
    _write(tmp_path / "vendor" / "library.py")

    assert main(["scan", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert "terminology scope: 1 production code file(s)" in captured.out
    assert "generated path(s)" in captured.err
    assert "vendored path(s)" in captured.err


def test_configuration_is_deterministic(tmp_path):
    (tmp_path / "glossarize.json").write_text(json.dumps({
        "schema_version": 1,
        "ignore_paths": ["scratch", "tmp"],
        "path_roles": {"test": ["qa"]},
    }))
    _write(tmp_path / "main.py")
    _write(tmp_path / "qa" / "check.py")

    first = build_evidence(tmp_path)
    second = build_evidence(tmp_path)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
