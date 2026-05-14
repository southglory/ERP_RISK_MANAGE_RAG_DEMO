"""Milvus backend (pymilvus 2.6 MilvusClient API).

ORM API (Collection, connections) 는 PyMilvus 3.x 에서 제거 예정 — MilvusClient 사용.
"""

from __future__ import annotations
import asyncio
import os

from pymilvus import MilvusClient

from core.providers.base import Document, SearchResult, VectorStore

from ._milvus_schema import COLLECTION_NAME, build_schema, index_params


class MilvusVectorStore(VectorStore):
    """Milvus standalone backend.

    sparse_tokens 는 무시 (v2.4 standalone 은 native BM25 미지원).
    search_sparse 는 빈 리스트 — HybridRetriever 가 dense-only 로 graceful 동작.
    """

    def __init__(
        self,
        host: str | None = None,
        port: str | None = None,
        collection_name: str = COLLECTION_NAME,
        uri: str | None = None,
    ) -> None:
        if uri:
            self.uri = uri
        else:
            h = host or os.environ.get("MILVUS_HOST", "localhost")
            p = port or os.environ.get("MILVUS_PORT", "19530")
            self.uri = f"http://{h}:{p}"
        self.collection_name = collection_name
        self._client: MilvusClient | None = None

    def _ensure_client(self) -> MilvusClient:
        if self._client is None:
            self._client = MilvusClient(uri=self.uri)
        return self._client

    async def ensure_collection(self) -> None:
        await asyncio.to_thread(self._ensure_collection_sync)

    def _ensure_collection_sync(self) -> None:
        client = self._ensure_client()
        if client.has_collection(self.collection_name):
            client.load_collection(self.collection_name)
            return
        schema = build_schema()
        idx = client.prepare_index_params()
        ip = index_params()
        idx.add_index(
            field_name="dense_vec",
            index_type=ip["index_type"],
            metric_type=ip["metric_type"],
            params=ip["params"],
        )
        client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=idx,
        )
        client.load_collection(self.collection_name)

    async def drop_collection(self) -> None:
        def _drop() -> None:
            client = self._ensure_client()
            if client.has_collection(self.collection_name):
                client.drop_collection(self.collection_name)
        await asyncio.to_thread(_drop)

    async def flush(self) -> None:
        def _flush() -> None:
            client = self._ensure_client()
            client.flush(self.collection_name)
        await asyncio.to_thread(_flush)

    async def upsert(self, doc: Document) -> None:
        await self.ensure_collection()

        row = {
            "chunk_id":       doc.chunk_id,
            "source_type":    doc.source_type,
            "source_doc_id":  doc.source_doc_id,
            "document_title": doc.document_title,
            "content":        doc.content[:4096],
            "span_start":     doc.span_start or 0,
            "span_end":       doc.span_end or 0,
            "dense_vec":      doc.dense_vec,
        }

        def _do() -> None:
            client = self._ensure_client()
            client.upsert(collection_name=self.collection_name, data=[row])
        await asyncio.to_thread(_do)

    async def search_dense(
        self,
        query_vec: list[float],
        top_k: int,
        source_types: list[str] | None = None,
    ) -> list[SearchResult]:
        await self.ensure_collection()

        filter_expr = ""
        if source_types:
            quoted = ", ".join(f'"{t}"' for t in source_types)
            filter_expr = f"source_type in [{quoted}]"

        def _do() -> list[SearchResult]:
            client = self._ensure_client()
            hits_list = client.search(
                collection_name=self.collection_name,
                data=[query_vec],
                anns_field="dense_vec",
                limit=top_k,
                filter=filter_expr,
                search_params={"metric_type": "COSINE", "params": {"ef": 64}},
                output_fields=["chunk_id", "source_type", "source_doc_id", "document_title", "content"],
            )
            out: list[SearchResult] = []
            for hits in hits_list:
                for hit in hits:
                    entity = hit.get("entity", {}) or hit
                    md = {
                        "source_type":    entity.get("source_type", ""),
                        "source_doc_id":  entity.get("source_doc_id", ""),
                        "document_title": entity.get("document_title", ""),
                    }
                    out.append(SearchResult(
                        chunk_id=entity.get("chunk_id", ""),
                        content=entity.get("content", ""),
                        score=float(hit.get("distance", 0.0)),   # COSINE: 클수록 유사
                        metadata=md,
                    ))
            return out
        return await asyncio.to_thread(_do)

    async def search_sparse(
        self,
        query_text: str,
        top_k: int,
        source_types: list[str] | None = None,
    ) -> list[SearchResult]:
        return []

    async def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
