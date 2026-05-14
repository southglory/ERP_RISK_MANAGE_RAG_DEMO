"""실제 pgvector 에 붙어 dense/sparse 양쪽이 결과를 반환하는지 smoke test."""

import os
import pytest

from core.providers.vectorstore.pgvector_store import PgVectorStore


pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — pgvector 통합 테스트 스킵",
)


async def test_search_dense_returns_results():
    """기존 인제스트된 198 청크 위에 임의 벡터로 dense 쿼리 — 결과가 있어야 한다."""
    store = PgVectorStore()
    try:
        # 임의 단위벡터 — 실제 임베딩이 아니어도 dense 인덱스가 동작하는지만 확인
        qv = [0.0] * 1023 + [1.0]
        results = await store.search_dense(qv, top_k=5)
        assert len(results) > 0
        assert all(-1.001 <= r.score <= 1.001 for r in results)
    finally:
        await store.close()


async def test_search_sparse_returns_list():
    """tsvector 미가용/존재 여부 무관하게 list 를 반환."""
    store = PgVectorStore()
    try:
        results = await store.search_sparse("부가가치세 신고기한", top_k=5)
        assert isinstance(results, list)
    finally:
        await store.close()
