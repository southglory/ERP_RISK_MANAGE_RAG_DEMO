"""HybridRetriever 리팩터 후 골든 쿼리 top-5 chunk_id 회귀 가드.

baseline 파일은 scripts/_capture_pgvector_baseline.py 로 생성. 의도된 결과 변경 시 갱신.
"""

import json
import os
from pathlib import Path

import pytest

from core.providers.embedding.infinity_provider import InfinityEmbeddingProvider
from core.providers.reranker.infinity_reranker import InfinityRerankerProvider
from core.providers.vectorstore.pgvector_store import PgVectorStore
from core.rag.models import RAGMode, RAGQuery
from core.rag.retriever import HybridRetriever

_BASELINE_PATH = Path(__file__).parent / "_pgvector_baseline.json"

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DATABASE_URL") and _BASELINE_PATH.exists()),
    reason="DATABASE_URL 또는 _pgvector_baseline.json 미가용",
)


_EXPECTED: dict[str, list[str]] = json.loads(_BASELINE_PATH.read_text(encoding="utf-8")) if _BASELINE_PATH.exists() else {}


@pytest.mark.parametrize("query", list(_EXPECTED.keys()))
async def test_top5_matches_baseline(query: str) -> None:
    store = PgVectorStore()
    r = HybridRetriever(
        embedding=InfinityEmbeddingProvider(),
        reranker=InfinityRerankerProvider(),
        store=store,
    )
    try:
        out = await r.retrieve(RAGQuery(query=query, top_k=5, mode=RAGMode.HYBRID))
        assert [c.chunk_id for c in out] == _EXPECTED[query]
    finally:
        await store.close()
