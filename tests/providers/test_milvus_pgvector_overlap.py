"""같은 쿼리에서 pgvector ↔ Milvus 가 top-5 중 ≥3 개 겹치는지 (HNSW 는 ANN)."""

import os

import pytest

from core.providers.embedding.infinity_provider import InfinityEmbeddingProvider
from core.providers.vectorstore.milvus_store import MilvusVectorStore
from core.providers.vectorstore.pgvector_store import PgVectorStore

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DATABASE_URL") and os.environ.get("MILVUS_E2E")),
    reason="Set DATABASE_URL + MILVUS_E2E=1",
)


QUERIES = [
    "부가가치세 신고기한",
    "원천징수 영수증 발급",
    "법인세 중간예납",
    "전자세금계산서 가산세",
    "해외법인 배당 원천징수",
]


@pytest.mark.parametrize("query", QUERIES)
async def test_top5_overlap_min_3(query: str) -> None:
    emb = InfinityEmbeddingProvider()
    qv = (await emb.embed([query]))[0]

    pg = PgVectorStore()
    mv = MilvusVectorStore()
    try:
        await mv.ensure_collection()
        pg_results = await pg.search_dense(qv, top_k=5)
        mv_results = await mv.search_dense(qv, top_k=5)
        pg_ids = {r.chunk_id for r in pg_results}
        mv_ids = {r.chunk_id for r in mv_results}
        overlap = pg_ids & mv_ids
        assert len(overlap) >= 3, f"overlap={overlap}\n  pg={pg_ids}\n  mv={mv_ids}"
    finally:
        await pg.close()
        await mv.close()
