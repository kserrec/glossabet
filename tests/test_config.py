"""Repository configuration and path roles keep analysis scope explicit."""

import json
import os

import pytest

from glossabet.analysis.evidence import build_evidence
from glossabet.cli import main
from glossabet.corpus.config import CONFIG_SHAPE, ConfigurationError, load_config


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
    monkeypatch.setattr("glossabet.corpus.config.MAX_CONFIG_BYTES", 20)
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


def test_config_rejects_trailing_slash_with_the_real_reason_and_non_integer_versions(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "glossabet.json").write_text(
        json.dumps({"schema_version": 1, "ignore_paths": ["scratch/"]})
    )
    with pytest.raises(ConfigurationError, match="must not end with '/'"):
        load_config(tmp_path)
    for version in (True, 1.0, "1"):
        (tmp_path / "glossabet.json").write_text(
            json.dumps({"schema_version": version, "ignore_paths": []})
        )
        with pytest.raises(ConfigurationError, match="schema_version must be 1"):
            load_config(tmp_path)


def test_config_named_directory_is_an_error_not_no_configuration(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "glossabet.json").mkdir()
    with pytest.raises(ConfigurationError, match="not a regular file"):
        load_config(tmp_path)


def test_config_with_utf8_bom_loads(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "glossabet.json").write_bytes(
        b"\xef\xbb\xbf" + json.dumps({"schema_version": 1, "ignore_paths": ["scratch"]}).encode()
    )
    assert load_config(tmp_path).ignore_paths == ("scratch",)


def test_config_contract_rejects_what_the_shape_says_it_rejects(tmp_path):
    """Every refusal `CONFIG_SHAPE`/SECURITY promise: unknown fields, unknown
    roles, one path under two roles, more path rules than the stated cap, a
    single path longer than the stated cap. Each names glossabet.json and
    the reason; the cap cases sit exactly at the boundary (cap accepted,
    cap + 1 refused) so a silently loosened or dropped cap fails here."""
    from glossabet.corpus.config import MAX_PATH_LENGTH, MAX_PATH_RULES

    def load(config):
        (tmp_path / "glossabet.json").write_text(json.dumps(config))
        return load_config(tmp_path)

    for config, expected in (
        ({"schema_version": 1, "ignore_pathz": ["x"]}, "unknown field(s): ignore_pathz"),
        ({"schema_version": 1, "path_roles": {"prod": ["x"]}},
         "unknown path role(s): prod"),
        ({"schema_version": 1, "path_roles": {"test": ["qa"], "fixture": ["qa"]}},
         "'qa' has both"),
        ({"schema_version": 1, "ignore_paths": [f"p{i}" for i in range(MAX_PATH_RULES + 1)]},
         f"at most {MAX_PATH_RULES} path rules"),
        # counted across ignore_paths and every role together
        ({"schema_version": 1,
          "ignore_paths": [f"i{n}" for n in range(MAX_PATH_RULES // 2 + 1)],
          "path_roles": {"test": [f"t{n}" for n in range(MAX_PATH_RULES // 2)]}},
         f"at most {MAX_PATH_RULES} path rules"),
        ({"schema_version": 1, "ignore_paths": ["x" * (MAX_PATH_LENGTH + 1)]},
         f"exceeds {MAX_PATH_LENGTH} characters"),
        ({"schema_version": 1, "path_roles": {"test": ["y" * (MAX_PATH_LENGTH + 1)]}},
         f"exceeds {MAX_PATH_LENGTH} characters"),
    ):
        with pytest.raises(ConfigurationError) as info:
            load(config)
        assert "glossabet.json" in str(info.value)
        assert expected in str(info.value), (expected, str(info.value))

    # At the caps, accepted.
    at_cap = load({
        "schema_version": 1,
        "ignore_paths": [f"p{i}" for i in range(MAX_PATH_RULES)],
    })
    assert len(at_cap.ignore_paths) == MAX_PATH_RULES
    long_ok = load({"schema_version": 1, "ignore_paths": ["x" * MAX_PATH_LENGTH]})
    assert long_ok.ignore_paths == ("x" * MAX_PATH_LENGTH,)


def test_most_specific_configured_role_wins_regardless_of_role_or_declaration_order(tmp_path):
    """Nested rules resolve by the deepest matching prefix — not by which
    role is declared first, and not by the engine's own role order (a
    production rule above a vendored one, or the reverse)."""
    cases = (
        ({"vendored": ["lib"], "production": ["lib/ours"]},
         {"lib/ours/core.py": "production", "lib/other/dep.py": "vendored"}),
        ({"production": ["lib/ours"], "vendored": ["lib"]},
         {"lib/ours/core.py": "production", "lib/other/dep.py": "vendored"}),
        ({"production": ["lib"], "vendored": ["lib/third"]},
         {"lib/third/dep.py": "vendored", "lib/core.py": "production"}),
        ({"test": ["lib"], "generated": ["lib/gen"], "production": ["lib/gen/keep"]},
         {"lib/x.py": "test", "lib/gen/a.py": "generated",
          "lib/gen/keep/b.py": "production"}),
    )
    for roles, expected in cases:
        (tmp_path / "glossabet.json").write_text(json.dumps(
            {"schema_version": 1, "path_roles": roles}
        ))
        config = load_config(tmp_path)
        for path, role in expected.items():
            assert config.role_for(path) == role, (roles, path)

    # And end to end through the walk for the engine-order-inverting case.
    (tmp_path / "glossabet.json").write_text(json.dumps(
        {"schema_version": 1,
         "path_roles": {"production": ["lib"], "vendored": ["lib/third"]}}
    ))
    _write(tmp_path / "lib" / "core.py")
    _write(tmp_path / "lib" / "third" / "dep.py")
    evidence = build_evidence(tmp_path)
    assert {item["path"] for item in evidence["files"]["code"]} == {"lib/core.py"}
    assert evidence["skipped"]["vendored"] == ["lib/third"]


def test_hostile_config_family_is_user_error_or_deterministic_evidence(tmp_path):
    """Seeded family of malformed, hostile, and merely odd glossabet.json
    documents (wrong types, glob and traversal paths, NUL/newline/RLO/lone
    surrogates in paths, at-cap and over-cap rule lists, invalid UTF-8 and
    UTF-16): each is either a named user error or loads to the same
    configuration twice and yields byte-identical evidence twice, and `scan`
    exits 0/1 with no traceback. Ported from a hunter (test-audit)."""
    import contextlib
    import io
    import random

    rlo = "\u202e"
    lone = "\ud800"
    paths = [
        "src", "src/", "/src", "./src", "src/../x", "tests", "vendor",
        "src/generated", "тест", "ünïcode/dir", "a b/c", "a b", "*", "src/*",
        "src?", "s[rc]", "", " ", " src", "src ", "src\\x", "x" * 512,
        "x" * 513, "src\x00", "src\n", "K", "K", "ﬁ", "src/m.py",
        "docs/r.md", "..", ".", "src//x", rlo + "src", lone, "src/" + lone,
        "S", "SRC", "Src", "src/x/y/z/w", "\U0001f600",
    ]
    raw = ["", "{", "[]", "null", "\xff", '{"a":1,"a":2}', "{" * 5000 + "}" * 5000]
    rng = random.Random(20260818)

    def scalar():
        return rng.choice([None, True, False, 0, 1, 1.0, -1, 2 ** 70, "1", "x",
                           [], {}, [1], {"a": 1}, "src", float("nan")])

    def path():
        return rng.choice(paths) if rng.random() < 0.85 else scalar()

    def path_list():
        r = rng.random()
        if r < 0.7:
            return [path() for _ in range(rng.choice([0, 1, 2, 3, 10]))]
        if r < 0.8:
            return [path() for _ in range(rng.choice([499, 500, 501, 600]))]
        return scalar()

    def document():
        config = {}
        if rng.random() < 0.9:
            config["schema_version"] = rng.choice([1, 1, 1, 1, "1", 1.0, True, 2, 0, None, -1])
        if rng.random() < 0.7:
            config["ignore_paths"] = path_list()
        if rng.random() < 0.7:
            if rng.random() < 0.85:
                config["path_roles"] = {
                    rng.choice(["production", "test", "fixture", "generated", "vendored",
                                "Production", "prod", "", "nested"]):
                    (path_list() if rng.random() < 0.9 else {"x": path_list()})
                    for _ in range(rng.randint(0, 6))
                }
            else:
                config["path_roles"] = scalar()
        if rng.random() < 0.15:
            config[str(scalar())] = scalar()
        config = config if rng.random() < 0.95 else scalar()
        text = (json.dumps(config) if rng.random() < 0.97
                else rng.choice(raw + [json.dumps(config) + "\n\nx"]))
        if rng.random() < 0.98:
            return text.encode("utf-8", errors="surrogatepass")
        return b"\xff\xfe" + text.encode("utf-16")

    for directory in ("src", "tests", "vendor", "src/generated", "docs", "тест",
                      "ünïcode/dir", "a b/c"):
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
        (tmp_path / directory / "m.py").write_text(
            "payment_service = 1\ndef helper_thing(): pass\n"
        )
    (tmp_path / "docs" / "r.md").write_text("payment service docs\n")

    loaded = 0
    for case in range(150):
        (tmp_path / "glossabet.json").write_bytes(document())
        try:
            first = load_config(tmp_path)
        except ConfigurationError as exc:
            assert "glossabet.json" in str(exc), case
        else:
            assert first == load_config(tmp_path), f"case {case}: load not deterministic"
            evidence = json.dumps(build_evidence(tmp_path), sort_keys=True, allow_nan=False)
            again = json.dumps(build_evidence(tmp_path), sort_keys=True, allow_nan=False)
            assert evidence == again, f"case {case}: evidence not deterministic"
            loaded += 1
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["scan", str(tmp_path)])
        assert code in (0, 1), f"case {case}: scan exit {code}: {err.getvalue()[-300:]}"
        assert "Traceback" not in err.getvalue(), case
    assert loaded >= 5
