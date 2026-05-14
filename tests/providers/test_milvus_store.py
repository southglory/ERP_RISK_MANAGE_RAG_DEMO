"""Milvus 가 떠있을 때 upsert/search_dense 가 round-trip 되는지 smoke."""

import os

import pytest

from core.providers.base import Document
from core.providers.vectorstore.milvus_store import MilvusVectorStore

pytestmark = pytest.mark.skipif(
    not os.environ.get("MILVUS_E2E"),
    reason="Set MILVUS_E2E=1 to run (Milvus 도커 필요)",
)


async def test_milvus_upsert_then_search_roundtrip():
    store = MilvusVectorStore(collection_name="erp_risk_chunks_test")
    try:
        await store.ensure_collection()
        v = [0.0] * 1023 + [1.0]
        await store.upsert(Document(
            chunk_id="t_0001_aaaa",
            source_type="tax_law",
            source_doc_id="t",
            document_title="t",
            content="hello",
            dense_vec=v,
            sparse_tokens={},
            metadata={},
            span_start=0,
            span_end=10,
        ))
        await store.flush()
        results = await store.search_dense(v, top_k=1)
        assert len(results) == 1
        assert results[0].chunk_id == "t_0001_aaaa"
    finally:
        await store.drop_collection()
        await store.close()


async def test_milvus_search_sparse_returns_empty():
    """v2.4 standalone 에서 native BM25 는 안 쓰니 빈 리스트."""
    store = MilvusVectorStore(collection_name="erp_risk_chunks_test")
    try:
        await store.ensure_collection()
        res = await store.search_sparse("부가가치세", top_k=5)
        assert res == []
    finally:
        await store.drop_collection()
        await store.close()
