"""Release automation stays tested, manual, and metadata-consistent."""

import re
from pathlib import Path

from glossarize import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_release_metadata_matches_package_version_and_supported_pythons():
    pyproject = (ROOT / "pyproject.toml").read_text()
    init = (ROOT / "glossarize" / "__init__.py").read_text()
    assert f'__version__ = "{__version__}"' in init
    for minor in range(10, 15):
        assert f'"Programming Language :: Python :: 3.{minor}"' in pyproject
    assert 'requires-python = ">=3.10"' in pyproject


def test_ci_covers_supported_versions_and_platforms():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "ubuntu-latest" in workflow
    assert "macos-latest" in workflow
    assert "windows-latest" in workflow
    for minor in range(10, 15):
        assert f'"3.{minor}"' in workflow
    assert "scripts/check_distribution.py" in workflow
    assert "scripts/wheel_smoke.py" in workflow
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in attributes


def test_publish_workflow_is_manual_and_confirmation_gated():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "publish-glossarize-to-pypi" in workflow
    assert "github.ref_type == 'tag'" in workflow
    assert "id-token: write" in workflow
    assert "gh-action-pypi-publish" in workflow
    assert not re.search(r"(?m)^\s{2}(push|release):", workflow)
