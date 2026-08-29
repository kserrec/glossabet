"""Release automation stays full-matrix, manual, and metadata-consistent."""

from pathlib import Path

import pytest

from glossabet import __version__
from scripts.check_workflows import check_workflows, validate_workflow_texts

ROOT = Path(__file__).resolve().parents[1]


def test_release_metadata_matches_package_version_and_supported_pythons():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    init = (ROOT / "glossabet" / "__init__.py").read_text(encoding="utf-8")
    assert f'__version__ = "{__version__}"' in init
    for minor in range(10, 15):
        assert f'"Programming Language :: Python :: 3.{minor}"' in pyproject
    assert 'requires-python = ">=3.10"' in pyproject
    assert 'requires = ["hatchling>=1.32,<1.33"]' in pyproject
    assert "dependencies =" not in pyproject
    assert (
        'dev = ["pytest", "PyYAML==6.0.3", "ruff==0.16.4", "mypy==2.3.1"]'
        in pyproject
    )


def _workflow_texts() -> dict[str, str]:
    directory = ROOT / ".github" / "workflows"
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in directory.iterdir()
        if path.suffix.lower() in (".yml", ".yaml")
    }


def test_reusable_quality_gate_controls_ci_and_release():
    assert check_workflows() == []
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in attributes


WEAKENINGS = [
    ("quality.yml", '"on":\n  workflow_call:', '"on":\n  push:'),
    ("quality.yml", "permissions:\n  contents: read", "permissions: write-all"),
    (
        "quality.yml",
        "\n  package:\n",
        "\n  extra:\n    runs-on: ubuntu-latest\n    steps: []\n  package:\n",
    ),
    ("quality.yml", "  test:\n    name:", "  test:\n    if: false\n    name:"),
    (
        "quality.yml",
        "os: [ubuntu-latest, macos-latest, windows-latest]",
        "os: [ubuntu-latest, macos-latest]",
    ),
    (
        "quality.yml",
        'python-version: ["3.10", "3.11", "3.12", "3.13", "3.14"]',
        'python-version: ["3.11", "3.12", "3.13", "3.14"]',
    ),
    ("quality.yml", "fail-fast: false", "fail-fast: true"),
    (
        "quality.yml",
        "runs-on: ${{ matrix.os }}",
        "runs-on: ubuntu-latest",
    ),
    (
        "quality.yml",
        "uv sync --locked --python ${{ matrix.python-version }}",
        "uv sync --python ${{ matrix.python-version }}",
    ),
    ("quality.yml", "uv run --locked pytest -q", "pytest -q"),
    (
        "quality.yml",
        "  static:\n    name: Ruff and mypy on Python 3.10\n    runs-on: ubuntu-latest",
        "  static:\n    name: Ruff and mypy on Python 3.10\n    runs-on: windows-latest",
    ),
    (
        "quality.yml",
        "actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e",
        "actions/setup-go@v7",
    ),
    ("quality.yml", 'go-version: "1.25.x"', 'go-version: "stable"'),
    (
        "quality.yml",
        "go install github.com/rhysd/actionlint/cmd/actionlint@v1.7.12",
        "go install github.com/rhysd/actionlint/cmd/actionlint@latest",
    ),
    ("quality.yml", "      - run: actionlint\n", ""),
    ("quality.yml", "uv run --locked ruff check .", "uv run --locked ruff check glossabet"),
    (
        "quality.yml",
        "uv run --locked mypy glossabet",
        "uv run --locked mypy glossabet/cli.py",
    ),
    ("quality.yml", "needs: [test, static]", "needs: [static]"),
    (
        "quality.yml",
        "uv run --locked python scripts/check_workflows.py",
        "python scripts/check_workflows.py",
    ),
    (
        "quality.yml",
        "python evaluation/run.py --verify-results evaluation/results.json",
        "python -c pass",
    ),
    (
        "quality.yml",
        "python scripts/agent_eval.py --verify-results evaluation/agent-results.json",
        "python -c pass",
    ),
    (
        "quality.yml",
        "python evaluation/review.py --verify-results evaluation/reviewer-results.json",
        "python -c pass",
    ),
    ("quality.yml", "uv build --no-sources --clear", "uv build"),
    ("quality.yml", "python scripts/build_plugin.py dist", "python -c pass"),
    ("quality.yml", "python scripts/check_distribution.py dist", "python -c pass"),
    ("quality.yml", "python scripts/wheel_smoke.py dist", "python -c pass"),
    (
        "ci.yml",
        '"on":\n  push:\n  pull_request:',
        '"on":\n  push:',
    ),
    (
        "ci.yml",
        "uses: ./.github/workflows/quality.yml",
        "uses: ./.github/workflows/bypass.yml",
    ),
    (
        "release.yml",
        '"on":\n  workflow_dispatch:',
        '"on":\n  push:\n  workflow_dispatch:',
    ),
    ("release.yml", "required: true", "required: false"),
    (
        "release.yml",
        "  quality:\n    uses: ./.github/workflows/quality.yml",
        "  quality:\n    if: false\n    uses: ./.github/workflows/quality.yml",
    ),
    ("release.yml", "needs: quality", "needs: []"),
    ("release.yml", "github.ref_type == 'tag'", "github.ref_type == 'branch'"),
    (
        "release.yml",
        "startsWith(github.ref_name, 'v')",
        "github.ref_name != ''",
    ),
    (
        "release.yml",
        "inputs.confirmation == 'publish-glossabet-to-pypi'",
        "inputs.confirmation != ''",
    ),
    ("release.yml", "      name: pypi", "      name: staging"),
    (
        "release.yml",
        "      id-token: write",
        "      id-token: write\n      packages: write",
    ),
    (
        "release.yml",
        "persist-credentials: false",
        "persist-credentials: true",
    ),
    (
        "release.yml",
        "uv run --locked python scripts/check_workflows.py",
        "python scripts/check_workflows.py",
    ),
    (
        "release.yml",
        "python scripts/wheel_smoke.py dist",
        "python scripts/wheel_smoke.py dist\n        continue-on-error: true",
    ),
    (
        "release.yml",
        '--tag "$RELEASE_TAG" --current',
        '--tag "${{ github.ref_name }}" --current',
    ),
    (
        "release.yml",
        "dc37677b2e1c63e2034f94d8a5b11f265b73ba33",
        "v1",
    ),
    (
        "release.yml",
        "  publish:\n    needs: quality",
        "  publish:\n    needs: quality\n    env:\n      TOKEN: ${{ secrets.PYPI_TOKEN }}",
    ),
]


@pytest.mark.parametrize("filename, original, weakened", WEAKENINGS)
def test_workflow_policy_rejects_each_project_gate(filename, original, weakened):
    workflows = _workflow_texts()
    assert original in workflows[filename]
    workflows[filename] = workflows[filename].replace(original, weakened, 1)
    assert validate_workflow_texts(workflows), (
        f"workflow policy accepted weakening in {filename}: {weakened}"
    )


def test_workflow_policy_reports_invalid_yaml():
    workflows = _workflow_texts()
    workflows["quality.yml"] = '"on": [\njobs: {}\n'
    errors = validate_workflow_texts(workflows)
    assert any("quality.yml is invalid YAML" in error for error in errors)


def test_workflow_policy_checks_new_workflow_files(tmp_path):
    for name, text in _workflow_texts().items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    (tmp_path / "extra.yml").write_text(
        '"on": {push: null}\njobs:\n  extra:\n    runs-on: ubuntu-latest\n'
        "    steps:\n      - uses: actions/checkout@v7\n",
        encoding="utf-8",
    )
    assert any("unpinned action" in error for error in check_workflows(tmp_path))


def test_distribution_content_guard_catches_local_home_paths():
    from scripts.check_distribution import _LOCAL_PATH_RE

    # Build the samples from parts so this test file itself carries no
    # contiguous home-path literal that would trip the guard when tests/
    # ships in the sdist.
    posix = b"trace " + b"/home/" + b"alice/Projects/x"
    windows = b"C:" + b"\\Users\\" + b"dev\\proj"
    root_home = b"trace " + b"/roo" + b"t/.local/bin/glossabet"
    assert _LOCAL_PATH_RE.search(posix)
    assert _LOCAL_PATH_RE.search(windows)
    # the superuser home directory (root's) must also be caught
    assert _LOCAL_PATH_RE.search(root_home)
    # ...but an ordinary nested directory of that name must not false-positive
    assert not _LOCAL_PATH_RE.search(b"/usr/" + b"roo" + b"t/share")
    # the guard's own pattern source must not be a self-match
    assert not _LOCAL_PATH_RE.search(b"(?:/home/|/Users/)[literal]")


def test_source_distribution_requires_current_policy_and_evaluation_guides():
    from scripts.check_distribution import SDIST_REQUIRED_RELATIVE

    assert {
        "COMPATIBILITY.md",
        "PLAN.md",
        "docs/plans/evaluation-modularization.md",
        "evaluation/README.md",
    } <= SDIST_REQUIRED_RELATIVE


def test_repository_documents_name_one_current_roadmap():
    plan = (ROOT / "PLAN.md").read_text(encoding="utf-8")
    architecture = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    supporting_spec = (
        ROOT / "docs" / "plans" / "evaluation-modularization.md"
    ).read_text(encoding="utf-8")

    assert plan.startswith("# Glossabet — Current Roadmap\n")
    assert (
        "`PLAN.md` is the sole current roadmap and status record"
        in " ".join(architecture.split())
    )
    normalized_spec = " ".join(supporting_spec.split())
    assert (
        "`PLAN.md` is the sole current roadmap and status record"
        in normalized_spec
    )
    assert "## Specified pass sequence" in supporting_spec
    assert "## Passes" not in supporting_spec
    assert "*(done)*" not in supporting_spec

    history = ROOT / "docs" / "history"
    for path in sorted(history.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if path.name != "README.md":
            assert "Historical record" in text[:500], path.name
        assert "This document is the authoritative roadmap." not in text, path.name


def test_source_distribution_rejects_repository_only_construction_history(
    tmp_path,
):
    import io
    import tarfile

    from scripts import check_distribution as dist

    sdist = tmp_path / "glossabet-0.0.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        member = tarfile.TarInfo(
            "glossabet-0.0.0/docs/history/old-session.md"
        )
        member.size = 8
        archive.addfile(member, io.BytesIO(b"historic"))

    with pytest.raises(SystemExit) as info:
        dist._check_sdist(
            sdist,
            tmp_path / "unused.whl",
            "0.0.0",
            b"",
            current=False,
        )
    assert "repository-only construction history" in str(info.value)


def test_distribution_home_path_scan_reaches_every_archive_layer(tmp_path, monkeypatch):
    """The regex alone is not the guard: the wheel scan must read every
    wheel member, the sdist scan every tar member, and a wheel *nested*
    inside the sdist (the plugin's bundled asset) must be opened and each
    of its members scanned — its bytes are compressed, so the outer scan
    cannot see them. A member declaring more than the nested-inflate bound
    is refused, not inflated."""
    import io
    import tarfile
    import zipfile

    from scripts import check_distribution as dist

    home = b"/home/" + b"alice/Projects/x"  # assembled: no literal in this file

    def wheel_bytes(payload: bytes, name: str = "glossabet/leak.txt") -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("glossabet/__init__.py", "x = 1\n")
            archive.writestr(name, payload)
        return buffer.getvalue()

    # A wheel member leaking a home path fails the wheel check by name.
    wheel = tmp_path / "glossabet-0.0.0-py3-none-any.whl"
    wheel.write_bytes(wheel_bytes(b"trace " + home))
    with pytest.raises(SystemExit) as info:
        dist._check_wheel(wheel, "0.0.0", b"")
    assert "leaks a local home path" in str(info.value)
    assert "glossabet/leak.txt" in str(info.value)

    # A wheel nested in the sdist: the leak sits only inside the inner zip.
    inner = wheel_bytes(b"trace " + home, "glossabet/inner.txt")
    sdist = tmp_path / "glossabet-0.0.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        info_ = tarfile.TarInfo(
            "glossabet-0.0.0/plugins/glossabet/skills/glossabet/assets/"
            "glossabet-0.0.0-py3-none-any.whl"
        )
        info_.size = len(inner)
        archive.addfile(info_, io.BytesIO(inner))
    with pytest.raises(SystemExit) as info:
        dist._check_sdist(sdist, wheel, "0.0.0", b"", current=False)
    assert "leaks a local home path" in str(info.value)
    assert "!glossabet/inner.txt" in str(info.value)

    # The per-member inflate bound refuses an over-declared member.
    monkeypatch.setattr(dist, "_MAX_NESTED_MEMBER_BYTES", 8)
    with pytest.raises(SystemExit) as info:
        dist._check_no_local_paths_in_zip(wheel_bytes(b"0123456789"), "asset.whl", "sdist")
    assert "refusing to inflate" in str(info.value)


def test_plugin_smoke_sdist_extraction_refuses_unsafe_members_and_extracts_safe_ones(tmp_path):
    """The temporary Codex lifecycle probe extracts the sdist it just built.
    Extraction must refuse absolute (POSIX or Windows), backslashed, or
    parent-escaping member names, links and devices, and dotenv paths — and
    must actually run on a well-formed archive (a bughunt found the guard
    referenced an undefined name, so the probe crashed on its first member)."""
    import io
    import tarfile

    from scripts import plugin_smoke

    def sdist_with(*names: str, kind: str = "file") -> Path:
        archive_path = tmp_path / f"{abs(hash(names))}.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            info = tarfile.TarInfo("glossabet-0.0.0/README.md")
            info.size = 2
            archive.addfile(info, io.BytesIO(b"ok"))
            for name in names:
                member = tarfile.TarInfo(name)
                if kind == "symlink":
                    member.type = tarfile.SYMTYPE
                    member.linkname = "README.md"
                else:
                    member.size = 1
                archive.addfile(member, None if kind == "symlink" else io.BytesIO(b"x"))
        return archive_path

    root = plugin_smoke._extract_sdist(sdist_with("glossabet-0.0.0/src/a.py"), tmp_path / "ok")
    assert root == tmp_path / "ok" / "glossabet-0.0.0"
    assert (root / "src" / "a.py").read_bytes() == b"x"

    for name, expected in (
        ("/etc/passwd", "unsafe path"),
        ("C:/Windows/x", "unsafe path"),
        ("C:\\Windows\\x", "unsafe path"),
        ("\\\\server\\share\\x", "unsafe path"),
        ("glossabet-0.0.0/../escape.py", "unsafe path"),
        ("glossabet-0.0.0/sub\\dir/x", "unsafe path"),
        ("glossabet-0.0.0/.env", "forbidden dotenv path"),
        ("glossabet-0.0.0/config/.env.local", "forbidden dotenv path"),
    ):
        with pytest.raises(RuntimeError) as info:
            plugin_smoke._extract_sdist(sdist_with(name), tmp_path / "bad")
        assert expected in str(info.value), name
    with pytest.raises(RuntimeError) as info:
        plugin_smoke._extract_sdist(
            sdist_with("glossabet-0.0.0/link", kind="symlink"), tmp_path / "link"
        )
    assert "link/device" in str(info.value)
