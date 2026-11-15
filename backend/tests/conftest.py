"""Keep runtime imports real and isolate shared catalog read caches."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def _clear_catalog_cache():
    from src.community.knowledge_base.book_catalog_index import clear_global_catalog_cache

    clear_global_catalog_cache()
    yield
    clear_global_catalog_cache()
