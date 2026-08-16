"""Release automation stays full-matrix, manual, and metadata-consistent."""

from pathlib import Path

from glossabet import __version__
from scripts.check_workflows import check_workflows, validate_workflow_texts

ROOT = Path(__file__).resolve().parents[1]


def test_release_metadata_matches_package_version_and_supported_pythons():
    pyproject = (ROOT / "pyproject.toml").read_text()
    init = (ROOT / "glossabet" / "__init__.py").read_text()
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
