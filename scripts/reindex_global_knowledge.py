#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.community.knowledge_base.indexer import rebuild_global_knowledge_index
from src.community.knowledge_base.retriever import get_qdrant_client
from src.config.app_config import get_app_config
from src.gateway.routers.knowledge import _mark_global_records_indexed


def main() -> int:
    get_app_config()
    chunk_count = rebuild_global_knowledge_index()
    _mark_global_records_indexed()

    client = get_qdrant_client()
    collections = client.get_collections().collections
    print(
        {
            "chunks": chunk_count,
            "collections": [collection.name for collection in collections],
        }
    )
    for collection in collections:
        info = client.get_collection(collection.name)
        print({"collection": collection.name, "points": info.points_count})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
