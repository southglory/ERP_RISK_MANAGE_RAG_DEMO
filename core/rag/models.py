"""RAG 파이프라인 공통 모델."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class RAGMode(str, Enum):
    DENSE     = "dense"      # 밀집 벡터 검색만
    HYBRID    = "hybrid"     # dense + sparse 혼합
    RERANK    = "rerank"     # hybrid 후 reranker


class SourceType(str, Enum):
    TAX_LAW   = "tax_law"    # 세법 조문
    COURT     = "court"      # 판례
    RULING    = "ruling"     # 국세청 예규·해석
    CONTRACT  = "contract"   # 계약서
    INTERNAL  = "internal"   # 내부 문서


class RetrievedChunk(BaseModel):
    chunk_id: str
    source_type: SourceType
    source_doc_id: str = ""   # 원천 문서 식별자 (lineage evidence_chunk 용)
    document_title: str = ""
    content: str
    score: float = 0.0        # 검색 점수
    rerank_score: float = 0.0


class RAGQuery(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)
    source_types: list[SourceType] = Field(default_factory=list)
    mode: RAGMode = RAGMode.HYBRID


class RAGResult(BaseModel):
    query: str
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    answer: str = ""
    trace_id: str = ""        # Langfuse trace ID
    latency_ms: int = 0
