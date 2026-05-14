"""Pinecone backend stub — 회사 스택 합류 시 자리.

실제 구현 시:
    pip install pinecone-client
    from pinecone import Pinecone
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    index = pc.Index(name)
    index.upsert([(id, vec, metadata), ...])
    index.query(vector=vec, top_k=k, include_metadata=True)
"""

from __future__ import annotations

from core.providers.base import Document, SearchResult, VectorStore


class PineconeVectorStore(VectorStore):
    def __init__(self, index_name: str = "erp-risk-chunks", api_key: str | None = None) -> None:
        self.index_name = index_name
        self.api_key = api_key

    async def upsert(self, doc: Document) -> None:
        raise NotImplementedError("Pinecone backend not wired — see file docstring")

    async def search_dense(
        self,
        query_vec: list[float],
        top_k: int,
        source_types: list[str] | None = None,
    ) -> list[SearchResult]:
        raise NotImplementedError("Pinecone backend not wired — see file docstring")

    async def search_sparse(
        self,
        query_text: str,
        top_k: int,
        source_types: list[str] | None = None,
    ) -> list[SearchResult]:
        return []

    async def close(self) -> None:
        return None
