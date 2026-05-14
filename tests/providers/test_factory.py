import pytest

from core.providers.vectorstore.factory import get_vector_store
from core.providers.vectorstore.milvus_store import MilvusVectorStore
from core.providers.vectorstore.pgvector_store import PgVectorStore
from core.providers.vectorstore.pinecone_store import PineconeVectorStore


def test_default_is_pgvector(monkeypatch):
    monkeypatch.delenv("RAG_VECTOR_BACKEND", raising=False)
    assert isinstance(get_vector_store(), PgVectorStore)


def test_milvus_env(monkeypatch):
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")
    assert isinstance(get_vector_store(), MilvusVectorStore)


def test_pinecone_env(monkeypatch):
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "pinecone")
    assert isinstance(get_vector_store(), PineconeVectorStore)


def test_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "qdrant")
    with pytest.raises(ValueError, match="qdrant"):
        get_vector_store()


def test_explicit_arg_wins(monkeypatch):
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")
    assert isinstance(get_vector_store("pgvector"), PgVectorStore)
