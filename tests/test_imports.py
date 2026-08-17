"""Import extraction/resolution and importance nominations: internal edges
must resolve across languages, external deps must separate, the lossy tag
must be present, and every nomination must carry its reasons."""

import time

from glossabet.evidence import build_evidence
from glossabet.importance import (
    NOMINATION_CANONICAL_NAME,
    NOMINATION_DISAMBIGUATION,
)
from glossabet.imports import extract_imports


def test_import_extraction_is_linear_on_blank_line_bomb():
    # The `^\s*<keyword>` patterns let `\s*` span newlines under re.MULTILINE,
    # so a file of only blank lines re-scanned the tail at every line start —
    # clean O(n^2) that pinned a core for hours within the 2 MB file cap. The
    # anchors must not cross line boundaries. A 500k-newline file (well under
    # the cap) must finish effectively instantly for every language.
    blank = "\n" * 500_000
    for language in ("python", "go", "rust", "ocaml", "java", "kotlin", "ruby"):
        start = time.perf_counter()
        assert extract_imports(blank, language) == []
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"{language}: {elapsed:.2f}s — quadratic backtracking"


def test_import_extraction_still_matches_indented_statements():
    # The anchor fix must keep matching leading-whitespace import lines.
    assert extract_imports("    import os\n\tfrom a.b import c\n", "python") == [
        "os", "a.b",
    ]


def test_extract_imports_per_language():
    assert extract_imports("import os\nfrom pkg.mod import x\n", "python") == [
        "os", "pkg.mod",
    ]
    js = "import {a} from './util'\nconst b = require('lodash')\n"
    assert extract_imports(js, "javascript") == ["./util", "lodash"]
    assert extract_imports("open Tfl_parser\ninclude Base\n", "ocaml") == [
        "Tfl_parser", "Base",
    ]
    go = 'import (\n\t"fmt"\n\tx "corp/pkg"\n)\n'
    assert extract_imports(go, "go") == ["fmt", "corp/pkg"]
    assert extract_imports('#include "util.h"\n#include <stdio.h>\n', "c") == [
        "util.h", "stdio.h",
    ]


def make_repo(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "core.py").write_text("payment_engine = 1\n")
    (lib / "util.py").write_text("helper_fn = 1\n")
    app = tmp_path / "app"
    app.mkdir()
    (app / "main.py").write_text(
        "import yojson_like\nfrom lib.core import payment_engine\n"
        "from lib.util import helper_fn\n"
    )
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.js").write_text(
        "import {x} from '../lib/core'\nconst l = require('lodash')\n"
    )
    (tmp_path / "README.md").write_text("The core module handles payment.\n")
    return tmp_path


def test_internal_edges_and_external_separation(tmp_path):
    imports = build_evidence(make_repo(tmp_path))["imports"]
    assert imports["lossy"] is True
    edges = {(e["from"], e["to"]): e["count"] for e in imports["internal_edges"]}
    assert edges[("app", "lib")] == 2
    assert edges[("web", "lib")] == 1
    externals = {e["name"] for e in imports["external_top"]}
    assert "lodash" in externals and "yojson_like" in externals
    assert "lib" not in externals


def test_capitalized_module_spec_resolves_to_lowercase_dir(tmp_path):
    # OCaml: `open Translate` must resolve to the repo's translate/ dir,
    # not be misfiled as an external dependency.
    tr = tmp_path / "translate"
    tr.mkdir()
    (tr / "client.ml").write_text("let fetch_page = 1\n")
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "main.ml").write_text("open Translate\nlet run_all = 1\n")
    imports = build_evidence(tmp_path)["imports"]
    edges = {(e["from"], e["to"]) for e in imports["internal_edges"]}
    assert ("lib", "translate") in edges
    assert "Translate" not in {e["name"] for e in imports["external_top"]}


def test_module_nomination_carries_reasons(tmp_path):
    naming = build_evidence(make_repo(tmp_path))["naming_candidates"]
    top = naming["modules"][0]
    assert top["path"] == "lib"
    assert any("imported by 2" in r for r in top["reasons"])
    assert any("code file" in r for r in top["reasons"])
    assert all(c["reasons"] for c in naming["modules"] + naming["terms"])


def test_term_nomination_rewards_doc_presence(tmp_path):
    naming = build_evidence(make_repo(tmp_path))["naming_candidates"]
    terms = {c["term"]: c for c in naming["terms"]}
    assert "payment" in terms
    assert any("docs" in r for r in terms["payment"]["reasons"])


def test_compound_productivity_outranks_equal_frequency(tmp_path):
    for module, identifier in (
        ("left", "build_anchor"),
        ("right", "write_anchor"),
    ):
        directory = tmp_path / module
        directory.mkdir()
        (directory / "code.py").write_text(
            f"{identifier} = 1\nsolitary = 1\n"
        )

    terms = {
        candidate["term"]: candidate
        for candidate in build_evidence(tmp_path)["naming_candidates"]["terms"]
    }

    assert terms["anchor"]["score"] > terms["solitary"]["score"]
    assert (
        "2 distinct compound pattern(s) across 2 compound use(s)"
        in terms["anchor"]["reasons"]
    )
    assert (
        "0 distinct compound pattern(s) across 0 compound use(s)"
        in terms["solitary"]["reasons"]
    )


def test_term_nominations_use_context_dispersion_kinds(tmp_path):
    modules = (
        ("auth", ("login", "cookie")),
        ("db", ("transaction", "commit")),
        ("ml", ("inference", "model")),
    )
    for module, session_contexts in modules:
        directory = tmp_path / module
        directory.mkdir()
        lines = [
            "ledger_entry = 1",
            "ledger_record = 1",
            *(f"session_{context} = 1" for context in session_contexts),
        ]
        (directory / "code.py").write_text("\n".join(lines) + "\n")

    evidence = build_evidence(tmp_path)
    terms = {
        candidate["term"]: candidate
        for candidate in evidence["naming_candidates"]["terms"]
    }

    assert terms["ledger"]["nomination_kind"] == NOMINATION_CANONICAL_NAME
    assert terms["session"]["nomination_kind"] == NOMINATION_DISAMBIGUATION
    assert any(
        reason == "context dispersion 0.0 across 3 module(s)"
        for reason in terms["ledger"]["reasons"]
    )
    assert any(
        reason == "context dispersion 1.0 across 3 module(s)"
        for reason in terms["session"]["reasons"]
    )


def test_term_nominations_exclude_language_tokens_and_report_the_filter(tmp_path):
    for module in ("left", "right"):
        directory = tmp_path / module
        directory.mkdir()
        (directory / "service.py").write_text(
            "dict_value = dict()\nshared_boundary = dict_value\n"
        )

    evidence = build_evidence(tmp_path)
    naming = evidence["naming_candidates"]
    terms = {candidate["term"] for candidate in naming["terms"]}

    assert "dict" not in terms
    assert {"shared", "boundary"} & terms
    term_coverage = naming["coverage"]["terms"]
    assert term_coverage["complete"] is False
    assert (
        "1 language-origin vocabulary token(s) excluded from the term naming "
        "candidate pool"
    ) in term_coverage["reasons"]


def test_untagged_tokens_are_not_assumed_to_be_domain_vocabulary():
    from collections import Counter, defaultdict

    from glossabet.importance import build_naming_candidates

    naming = build_naming_candidates(
        {"internal_edges": []},
        [],
        Counter({"untagged": 2}),
        {"untagged": Counter({"a.py": 1, "b.py": 1})},
        {"untagged": Counter({"left": 1, "right": 1})},
        Counter(),
        {},
        defaultdict(Counter),
        {},
    )

    assert naming["terms"] == []
    assert (
        "1 untagged vocabulary token(s) excluded from the domain-only term "
        "naming candidate pool"
    ) in naming["coverage"]["terms"]["reasons"]


def test_bounds_reported(tmp_path):
    evidence = build_evidence(make_repo(tmp_path))
    assert "edges_truncated" in evidence["imports"]
    assert "external_truncated" in evidence["imports"]
    assert "modules_dropped" in evidence["naming_candidates"]
    assert "terms_dropped" in evidence["naming_candidates"]
    coverage = evidence["naming_candidates"]["coverage"]
    assert set(coverage) == {"modules", "terms", "structures"}
    for ledger in coverage.values():
        assert set(ledger) == {
            "total_items", "included_items", "dropped_items",
            "total_items_exact", "complete", "reasons",
        }


def test_bare_relative_import_creates_no_phantom_root_edge(tmp_path):
    # `from . import b` used to resolve to a nonexistent module "." and
    # fabricate an internal edge pkg -> ".".
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "a.py").write_text("from . import b\nvalue = 1\n")
    (pkg / "b.py").write_text("x = 1\n")
    imports = build_evidence(tmp_path)["imports"]
    assert all(e["to"] != "." for e in imports["internal_edges"])


def test_python_parent_relative_import_resolves_to_parent_package(tmp_path):
    pkg = tmp_path / "pkg"
    sub = pkg / "sub"
    sub.mkdir(parents=True)
    (pkg / "shared.py").write_text("shared_value = 1\n")
    (sub / "consumer.py").write_text(
        "from ..shared import shared_value\nconsumer_value = shared_value\n"
    )

    imports = build_evidence(tmp_path)["imports"]

    assert ("pkg/sub", "pkg") in {
        (edge["from"], edge["to"]) for edge in imports["internal_edges"]
    }


def test_same_repo_include_resolves_internal(tmp_path):
    # #include "helpers.h" used to be misfiled as an external dep "helpers"
    # even with include/helpers.h present in the repo.
    (tmp_path / "src").mkdir()
    (tmp_path / "include").mkdir()
    (tmp_path / "src" / "main.c").write_text('#include "helpers.h"\nint x;\n')
    (tmp_path / "include" / "helpers.h").write_text("int helper(void);\n")
    imports = build_evidence(tmp_path)["imports"]
    assert ("src", "include") in {
        (e["from"], e["to"]) for e in imports["internal_edges"]
    }
    assert "helpers" not in {e["name"] for e in imports["external_top"]}


def test_module_naming_coverage_reports_truncated_import_edges():
    from collections import Counter

    from glossabet.importance import build_naming_candidates

    imports_section = {
        "internal_edges": [
            {"from": "a", "to": "b", "count": 2},
        ],
        "edges_truncated": 3,
    }
    naming = build_naming_candidates(
        imports_section,
        [{"path": "a", "code_files": 1}, {"path": "b", "code_files": 1}],
        Counter(),
        {},
        {},
        Counter(),
    )

    ledger = naming["coverage"]["modules"]
    assert ledger["complete"] is False
    assert any("edge cap" in reason for reason in ledger["reasons"])
