"""Suite-wide isolation for user-owned state."""

import pytest


@pytest.fixture(autouse=True)
def isolated_glossabet_cache(tmp_path_factory, monkeypatch):
    # A not-yet-existing directory, as on a fresh machine.
    cache_root = tmp_path_factory.mktemp("glossabet-cache") / "cache"
    monkeypatch.setenv("GLOSSABET_CACHE_DIR", str(cache_root))
