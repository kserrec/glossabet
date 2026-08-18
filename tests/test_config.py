"""Repository configuration and path roles keep analysis scope explicit."""

import json
import os

from glossabet.cli import main
from glossabet.config import CONFIG_SHAPE
from glossabet.evidence import build_evidence


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
    (tmp_path / "glossabet.json").write_text(json.dumps(config))
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
        "file": "glossabet.json",
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
        "shape": CONFIG_SHAPE,
    }


def test_excluded_root_manifests_are_not_reopened_for_monorepo_detection(
    tmp_path,
):
    (tmp_path / "glossabet.json").write_text(json.dumps({
        "schema_version": 1,
        "path_roles": {
            "generated": ["package.json"],
            "vendored": ["Cargo.toml"],
        },
    }))
    (tmp_path / "package.json").write_text(json.dumps({
        "workspaces": ["packages/*"],
    }))
    (tmp_path / "Cargo.toml").write_text(
        "[workspace]\nmembers = ['packages/*']\n"
    )
    _write(tmp_path / "main.py")

    evidence = build_evidence(tmp_path)

    assert evidence["skipped"]["generated"] == ["package.json"]
    assert evidence["skipped"]["vendored"] == ["Cargo.toml"]
    assert evidence["monorepo"]["detected"] is False


def test_invalid_config_is_a_user_error(tmp_path, capsys):
    (tmp_path / "glossabet.json").write_text(json.dumps({
        "schema_version": 1,
        "ignore_paths": ["../outside"],
    }))
    _write(tmp_path / "main.py")

    assert main(["scan", str(tmp_path)]) == 1
    assert "glossabet.json" in capsys.readouterr().err


def test_glob_in_a_config_path_is_a_user_error_not_a_literal_prefix(tmp_path, capsys):
    # Config paths are literal repository-relative prefixes, never globs. A
    # glob metacharacter must be a clean user error, not silently accepted as a
    # literal prefix that then matches nothing. Guards both path fields.
    for field, value in (
        ("ignore_paths", ["src/*"]),
        ("path_roles", {"test": ["fixtures/**"]}),
    ):
        (tmp_path / "glossabet.json").write_text(json.dumps({
            "schema_version": 1,
            field: value,
        }))
        _write(tmp_path / "main.py")

        assert main(["scan", str(tmp_path)]) == 1
        err = capsys.readouterr().err
        assert "glossabet.json" in err and "not a glob" in err


def test_symlinked_config_is_rejected_without_reading_target(tmp_path, capsys):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"schema_version": 1}))
    repository = tmp_path / "repository"
    repository.mkdir()
    _write(repository / "main.py")
    os.symlink(outside, repository / "glossabet.json")

    assert main(["scan", str(repository)]) == 1
    assert "symlinked artifact" in capsys.readouterr().err


def test_oversized_config_is_a_user_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("glossabet.config.MAX_CONFIG_BYTES", 20)
    (tmp_path / "glossabet.json").write_text(json.dumps({
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
    (tmp_path / "glossabet.json").write_text(json.dumps({
        "schema_version": 1,
        "ignore_paths": ["scratch", "tmp"],
        "path_roles": {"test": ["qa"]},
    }))
    _write(tmp_path / "main.py")
    _write(tmp_path / "qa" / "check.py")

    first = build_evidence(tmp_path)
    second = build_evidence(tmp_path)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_configuration_shape_and_hint_meet_the_user_at_the_point_of_need(
    tmp_path, capsys
):
    """The optional glossabet.json is otherwise documented only in the
    README: the evidence carries its shape and the scan summary names it."""
    (tmp_path / "app.py").write_text("def run(): pass\n")
    assert main(["scan", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "roles and exclusions from built-in defaults" in out
    assert "adjust with a root glossabet.json (ignore_paths, path_roles: " in out
    evidence = json.loads((tmp_path / "glossabet-out" / "evidence.json").read_text())
    shape = evidence["configuration"]["shape"]
    assert shape["schema_version"] == 1
    assert set(shape["keys"]["path_roles"]) == {
        "production", "test", "fixture", "generated", "vendored"
    }
    assert "literal" in shape["rules"] and "no globs" in shape["rules"]

    (tmp_path / "glossabet.json").write_text(
        json.dumps(shape["example"])  # the carried example must itself load
    )
    assert main(["scan", str(tmp_path)]) == 0
    assert "roles and exclusions from glossabet.json" in capsys.readouterr().out
