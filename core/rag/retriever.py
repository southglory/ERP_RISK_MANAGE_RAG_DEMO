"""HybridRetriever — VectorStore 게이트웨이만 호출. RRF + rerank 는 여기서."""

from __future__ import annotations

from ..providers.base import EmbeddingProvider, RerankerProvider, SearchResult, VectorStore
from .models import RAGMode, RAGQuery, RetrievedChunk, SourceType

_RRF_K = 60   # Reciprocal Rank Fusion 상수 (Cormack et al. 2009)


def _result_to_chunk(r: SearchResult) -> RetrievedChunk:
    md = r.metadata or {}
    src = md.get("source_type") or "tax_law"
    return RetrievedChunk(
        chunk_id=r.chunk_id,
        source_type=SourceType(src),
        source_doc_id=md.get("source_doc_id", ""),
        document_title=md.get("document_title", ""),
        content=r.content,
        score=r.score,
    )


def _rrf_fusion(
    dense: list[RetrievedChunk],
    sparse: list[RetrievedChunk],
    top_k: int,
) -> list[RetrievedChunk]:
    """dense + sparse 결과를 RRF 로 융합.

    RRF score = Σ 1 / (k + rank_i). 두 목록에 모두 등장하면 점수가 두 배 가까이 올라간다.
    """
    rrf: dict[str, float] = {}
    by_id: dict[str, RetrievedChunk] = {}
    for rank, c in enumerate(dense, 1):
        rrf[c.chunk_id] = rrf.get(c.chunk_id, 0.0) + 1.0 / (_RRF_K + rank)
        by_id[c.chunk_id] = c
    for rank, c in enumerate(sparse, 1):
        rrf[c.chunk_id] = rrf.get(c.chunk_id, 0.0) + 1.0 / (_RRF_K + rank)
        by_id.setdefault(c.chunk_id, c)
    out: list[RetrievedChunk] = []
    for cid in sorted(rrf, key=lambda k: rrf[k], reverse=True)[:top_k]:
        chunk = by_id[cid]
        chunk.score = rrf[cid]
        out.append(chunk)
    return out


class HybridRetriever:
    """BGE-M3 dense + sparse + RRF(k=60) + bge-reranker-v2-m3."""

    def __init__(
        self,
        embedding: EmbeddingProvider,
        reranker: RerankerProvider,
        store: VectorStore,
    ) -> None:
        self._emb = embedding
        self._rr = reranker
        self._store = store

    async def retrieve(self, query: RAGQuery) -> list[RetrievedChunk]:
        vecs = await self._emb.embed([query.query])
        qv = vecs[0]
        candidate_k = query.top_k * 4   # rerank/RRF 전 후보 풀
        source_str: list[str] | None = [t.value for t in query.source_types] or None

        if query.mode == RAGMode.DENSE:
            dense_results = await self._store.search_dense(qv, candidate_k, source_str)
            return [_result_to_chunk(r) for r in dense_results[: query.top_k]]

        # HYBRID / RERANK: dense + sparse + RRF
        dense_results = await self._store.search_dense(qv, candidate_k, source_str)
        sparse_results = await self._store.search_sparse(query.query, candidate_k, source_str)
        dense = [_result_to_chunk(r) for r in dense_results]
        sparse = [_result_to_chunk(r) for r in sparse_results]

        if not dense and not sparse:
            return []

        fused = _rrf_fusion(dense, sparse, top_k=candidate_k)

        if query.mode == RAGMode.RERANK:
            texts = [c.content for c in fused]
            ranked = await self._rr.rerank(query.query, texts, top_k=query.top_k)
            out: list[RetrievedChunk] = []
            for r in ranked:
                chunk = fused[r.index]
                chunk.rerank_score = r.score
                out.append(chunk)
            return out

        return fused[: query.top_k]
