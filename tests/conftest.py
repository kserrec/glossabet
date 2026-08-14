"""Suite-wide isolation for user-owned state."""

import pytest


@pytest.fixture(autouse=True)
def isolated_glossarize_cache(tmp_path, monkeypatch):
    cache_root = tmp_path.parent / f".{tmp_path.name}-glossarize-cache"
    monkeypatch.setenv("GLOSSARIZE_CACHE_DIR", str(cache_root))
