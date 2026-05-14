from __future__ import annotations
import json
import os

import asyncpg

from core.providers.base import Document, SearchResult, VectorStore


class PgVectorStore(VectorStore):
    """pgvector(dense) + tsvector(sparse) backend.

    스키마: deploy/infra/init-scripts/02_lineage.sql 의 document_chunk 테이블.
    sparse 인덱스(content_tsv 컬럼) 가 없는 환경에서도 search_sparse 는 빈 리스트로 graceful.
    """

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or os.environ.get(
            "DATABASE_URL",
            "postgresql://playground:playground@localhost:5432/playground",
        )
        self._pool: asyncpg.Pool | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=4)
        return self._pool

    async def upsert(self, doc: Document) -> None:
        pool = await self._get_pool()
        vec_str = "[" + ",".join(str(v) for v in doc.dense_vec) + "]"
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO document_chunk
                  (chunk_id, source_type, source_doc_id, document_title, content,
                   span_start, span_end, dense_vec, sparse_tokens, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector, $9::jsonb, $10::jsonb)
                ON CONFLICT (chunk_id) DO UPDATE SET
                  content       = EXCLUDED.content,
                  dense_vec     = EXCLUDED.dense_vec,
                  sparse_tokens = EXCLUDED.sparse_tokens,
                  metadata      = EXCLUDED.metadata
                """,
                doc.chunk_id, doc.source_type, doc.source_doc_id, doc.document_title,
                doc.content, doc.span_start, doc.span_end,
                vec_str, json.dumps(doc.sparse_tokens), json.dumps(doc.metadata),
            )

    async def search_dense(
        self,
        query_vec: list[float],
        top_k: int,
        source_types: list[str] | None = None,
    ) -> list[SearchResult]:
        pool = await self._get_pool()
        vec_str = "[" + ",".join(str(v) for v in query_vec) + "]"
        type_filter = ""
        params: list = [vec_str, top_k]
        if source_types:
            placeholders = ",".join(f"${i+3}" for i in range(len(source_types)))
            type_filter = f"AND source_type IN ({placeholders})"
            params.extend(source_types)
        sql = f"""
            SELECT chunk_id, source_type, source_doc_id, document_title, content,
                   1 - (dense_vec <=> $1::vector) AS score, metadata
            FROM document_chunk
            WHERE dense_vec IS NOT NULL
            {type_filter}
            ORDER BY dense_vec <=> $1::vector
            LIMIT $2
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [_row_to_result(r) for r in rows]

    async def search_sparse(
        self,
        query_text: str,
        top_k: int,
        source_types: list[str] | None = None,
    ) -> list[SearchResult]:
        pool = await self._get_pool()
        type_filter = ""
        params: list = [query_text, top_k]
        if source_types:
            placeholders = ",".join(f"${i+3}" for i in range(len(source_types)))
            type_filter = f"AND source_type IN ({placeholders})"
            params.extend(source_types)
        sql = f"""
            SELECT chunk_id, source_type, source_doc_id, document_title, content,
                   ts_rank_cd(content_tsv, query, 32) AS score, metadata
            FROM document_chunk,
                 plainto_tsquery('simple', $1) AS query
            WHERE content_tsv IS NOT NULL
              AND content_tsv @@ query
            {type_filter}
            ORDER BY score DESC
            LIMIT $2
        """
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
        except Exception:
            return []
        return [_row_to_result(r) for r in rows]

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None


def _row_to_result(row) -> SearchResult:
    md = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
    md.setdefault("source_type",    row["source_type"])
    md.setdefault("source_doc_id",  row["source_doc_id"])
    md.setdefault("document_title", row["document_title"] or "")
    return SearchResult(
        chunk_id=str(row["chunk_id"]),
        content=row["content"],
        score=float(row["score"]),
        metadata=md,
    )
