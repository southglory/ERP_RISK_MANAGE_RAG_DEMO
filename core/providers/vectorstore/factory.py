"""환경변수 RAG_VECTOR_BACKEND 로 VectorStore 인스턴스를 분기."""

from __future__ import annotations
import os

from core.providers.base import VectorStore

from .milvus_store import MilvusVectorStore
from .pgvector_store import PgVectorStore
from .pinecone_store import PineconeVectorStore

_KNOWN = {"pgvector", "milvus", "pinecone"}


def get_vector_store(backend: str | None = None) -> VectorStore:
    name = (backend or os.environ.get("RAG_VECTOR_BACKEND", "pgvector")).strip().lower()
    if name == "pgvector":
        return PgVectorStore()
    if name == "milvus":
        return MilvusVectorStore()
    if name == "pinecone":
        return PineconeVectorStore()
    raise ValueError(f"unknown RAG_VECTOR_BACKEND={name!r} (known: {sorted(_KNOWN)})")
