from unittest.mock import AsyncMock

from core.providers.base import RankedDoc, SearchResult
from core.rag.models import RAGMode, RAGQuery
from core.rag.retriever import HybridRetriever


class _FakeEmb:
    async def embed(self, texts):
        return [[0.1] * 1024 for _ in texts]


class _FakeRR:
    async def rerank(self, query, documents, top_k):
        return [RankedDoc(index=i, score=1.0 - i * 0.1) for i in range(min(top_k, len(documents)))]


async def test_retriever_propagates_source_doc_id():
    store = AsyncMock()
    store.search_dense.return_value = [
        SearchResult(
            chunk_id="c1", content="x", score=0.9,
            metadata={"source_type": "tax_law", "source_doc_id": "부가가치세법", "document_title": "t"},
        ),
    ]
    store.search_sparse.return_value = []
    r = HybridRetriever(embedding=_FakeEmb(), reranker=_FakeRR(), store=store)
    out = await r.retrieve(RAGQuery(query="hi", top_k=1, mode=RAGMode.DENSE))
    assert out[0].source_doc_id == "부가가치세법"
