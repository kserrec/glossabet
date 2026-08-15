"""Suite-wide isolation for user-owned state."""

import pytest


@pytest.fixture(autouse=True)
def isolated_glossabet_cache(tmp_path, monkeypatch):
    cache_root = tmp_path.parent / f".{tmp_path.name}-glossabet-cache"
    monkeypatch.setenv("GLOSSABET_CACHE_DIR", str(cache_root))
