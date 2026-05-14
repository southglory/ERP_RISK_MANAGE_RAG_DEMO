"""HybridRetriever 가 raw asyncpg 가 아닌 VectorStore 만 호출하는지 mock 으로 검증."""

from unittest.mock import AsyncMock


from core.providers.base import RankedDoc, SearchResult
from core.rag.models import RAGMode, RAGQuery
from core.rag.retriever import HybridRetriever


class _FakeEmb:
    async def embed(self, texts):
        return [[0.1] * 1024 for _ in texts]


class _FakeReranker:
    async def rerank(self, query, documents, top_k):
        return [RankedDoc(index=i, score=1.0 - i * 0.1) for i in range(min(top_k, len(documents)))]


async def test_retriever_calls_store_dense_only_in_dense_mode():
    store = AsyncMock()
    store.search_dense.return_value = [
        SearchResult(chunk_id="c1", content="x", score=0.9,
                     metadata={"source_type": "tax_law", "document_title": "t"}),
    ]
    store.search_sparse.return_value = []
    r = HybridRetriever(embedding=_FakeEmb(), reranker=_FakeReranker(), store=store)
    out = await r.retrieve(RAGQuery(query="hi", top_k=1, mode=RAGMode.DENSE))
    assert len(out) == 1
    store.search_dense.assert_awaited_once()
    store.search_sparse.assert_not_awaited()


async def test_retriever_calls_both_in_hybrid_mode():
    store = AsyncMock()
    store.search_dense.return_value = [
        SearchResult(chunk_id="c1", content="a", score=0.9,
                     metadata={"source_type": "tax_law", "document_title": "t"}),
    ]
    store.search_sparse.return_value = [
        SearchResult(chunk_id="c2", content="b", score=0.8,
                     metadata={"source_type": "tax_law", "document_title": "t"}),
    ]
    r = HybridRetriever(embedding=_FakeEmb(), reranker=_FakeReranker(), store=store)
    out = await r.retrieve(RAGQuery(query="hi", top_k=2, mode=RAGMode.HYBRID))
    assert {c.chunk_id for c in out} == {"c1", "c2"}
    store.search_dense.assert_awaited_once()
    store.search_sparse.assert_awaited_once()
