import pytest

from core.providers.base import Document
from core.providers.vectorstore.pinecone_store import PineconeVectorStore


def test_pinecone_instantiates():
    s = PineconeVectorStore()
    assert s is not None


async def test_pinecone_search_dense_not_implemented():
    s = PineconeVectorStore()
    with pytest.raises(NotImplementedError, match="Pinecone"):
        await s.search_dense([0.0] * 1024, top_k=5)


async def test_pinecone_upsert_not_implemented():
    s = PineconeVectorStore()
    with pytest.raises(NotImplementedError):
        await s.upsert(Document(
            chunk_id="x", source_type="tax_law", source_doc_id="x",
            document_title="t", content="c", dense_vec=[0.0] * 1024,
            sparse_tokens={}, metadata={},
        ))


async def test_pinecone_search_sparse_returns_empty():
    s = PineconeVectorStore()
    assert await s.search_sparse("foo", top_k=5) == []
