"""Suite-wide isolation for user-owned state."""

import pytest


@pytest.fixture(autouse=True)
def isolated_glossabet_cache(tmp_path_factory, monkeypatch):
    # A not-yet-existing directory, as on a fresh machine.
    cache_root = tmp_path_factory.mktemp("glossabet-cache") / "cache"
    monkeypatch.setenv("GLOSSABET_CACHE_DIR", str(cache_root))


@pytest.fixture
def case_distinct_names_supported(tmp_path):
    """Whether this test's temporary directory distinguishes name case."""
    mixed_case = tmp_path / ".Glossabet-Case-Probe"
    folded_case = tmp_path / ".glossabet-case-probe"
    mixed_case.write_bytes(b"")
    try:
        return not folded_case.exists()
    finally:
        mixed_case.unlink()
