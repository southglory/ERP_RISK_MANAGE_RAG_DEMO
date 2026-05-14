"""Phase 3-1-6 — Semantic Chunking.

기존 ingest_pdf.py 의 단순 paragraph + sliding window 청킹을 보강.

전략:
1. 문장 단위 분할 (한국어 마침표·줄바꿈 기준).
2. 인접 문장 쌍의 임베딩 cosine 거리 측정.
3. 거리가 임계 이상이면 의미 경계 → 청크 분리.

이 모듈은 LangChain SemanticChunker 의 동작 모델과 유사하나, 외부 의존 없이 자체 구현.
imports 가 무거우니 ingest 스크립트에서 옵셔널로 호출.

사용 예시:
    from core.rag.semantic_chunker import SemanticChunker
    chunks = await SemanticChunker(emb_provider).split(text)
"""

from __future__ import annotations
import re

import numpy as np

from core.providers.base import EmbeddingProvider


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n{2,}")


class SemanticChunker:
    def __init__(
        self,
        embedding: EmbeddingProvider,
        threshold_percentile: float = 75.0,
        min_sentences_per_chunk: int = 2,
        max_chars_per_chunk: int = 1200,
    ) -> None:
        """
        Args:
            embedding: BGE-M3 등의 임베딩 제공자.
            threshold_percentile: 인접 문장 거리 분포의 N 분위수. 이 이상이면 경계로 본다.
            min_sentences_per_chunk: 청크 하나의 최소 문장 수 (너무 잘게 쪼개지 않게).
            max_chars_per_chunk: 한 청크의 최대 문자 수 (너무 크면 강제 분리).
        """
        self._emb = embedding
        self._pct = threshold_percentile
        self._min_sent = min_sentences_per_chunk
        self._max_chars = max_chars_per_chunk

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        sents = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
        return [s for s in sents if len(s) >= 10]

    @staticmethod
    def _cosine_distances(vecs: list[list[float]]) -> list[float]:
        arr = np.asarray(vecs, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True) + 1e-12
        arr = arr / norms
        # 인접 페어 cosine distance = 1 - dot
        dots = (arr[:-1] * arr[1:]).sum(axis=1)
        return (1.0 - dots).tolist()

    async def split(self, text: str) -> list[str]:
        """텍스트를 의미 경계에서 잘라 청크 리스트로 반환."""
        sentences = self._split_sentences(text)
        if len(sentences) <= self._min_sent:
            return [text] if text.strip() else []

        vecs = await self._emb.embed(sentences)
        dists = self._cosine_distances(vecs)
        if not dists:
            return [text]

        threshold = float(np.percentile(dists, self._pct))

        chunks: list[str] = []
        buf: list[str] = [sentences[0]]
        char_count = len(sentences[0])
        for i, d in enumerate(dists, 1):
            sent = sentences[i]
            is_boundary = d > threshold and len(buf) >= self._min_sent
            is_overflow = char_count + len(sent) + 1 > self._max_chars
            if is_boundary or is_overflow:
                chunks.append(" ".join(buf))
                buf = [sent]
                char_count = len(sent)
            else:
                buf.append(sent)
                char_count += len(sent) + 1
        if buf:
            chunks.append(" ".join(buf))
        return chunks
