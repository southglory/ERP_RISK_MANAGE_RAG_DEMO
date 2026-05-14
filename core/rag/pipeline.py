"""RAG 파이프라인 — 검색 → 프롬프트 조립 → Solar LLM → Langfuse 트레이싱.

Langfuse v4 SDK 기준: start_as_current_observation / get_current_trace_id 사용.
"""

from __future__ import annotations

import os
import re
import time
from typing import AsyncIterator

from ..providers.base import LLMProvider, ChatMessage
from .models import RAGQuery, RAGResult, RetrievedChunk
from .retriever import HybridRetriever


_SYSTEM_PROMPT = """당신은 한국 세무·회계 전문 AI입니다. 모든 답변은 반드시 한국어로만 작성하세요.
- 절대 영어로 답하지 마세요. 법령·회계 용어도 한국어로 표현하세요.
- 아래 [참고 문서]에 제시된 내용만 근거로 사용하세요. 훈련 데이터나 사전 지식을 사용하지 마세요.
- [참고 문서]에 없는 내용(K-IFRS 조항, 내부감사 기준, 구체적 수치 등)은 절대 언급하거나 추론하지 마세요. 반드시 "참고 문서에서 확인되지 않습니다"라고만 답하세요.
- 답변 마지막 줄에 반드시 출처를 표시하세요. 예시: "[출처: 부가가치세법 제4조]", "[출처: 하도급거래 공정화에 관한 법률 제13조의2]", "[출처: 법인세법 제93조 제9호]". 법령 이름과 조문 번호를 구체적으로 채워 넣으세요.
- 출처를 특정할 수 없으면 "[출처: 참고 문서 확인 불가]"라고 표시하세요."""

_USER_TEMPLATE = """\
[참고 문서]
{context}

[질문] {query}

위 질문에 한국어로 답하세요. 답변 마지막 줄은 반드시 "[출처: 법령명 제○조]" 형식으로 끝내세요."""


_LAW_PATTERN = re.compile(
    r"[「『'‘“]?([가-힣a-zA-Z\s·]+?법(?:률|시행령|시행규칙)?)[」』'’”]?\s*"
    r"(?:제\s*(\d+(?:\.\d+)?조(?:의\d+)?(?:\s*제\d+항)?(?:\s*제\d+호)?))",
    re.UNICODE,
)


def _ensure_citation(answer: str) -> str:
    """답변에 [출처:] 태그가 없으면 본문에서 법령+조문을 추출해 자동 추가한다."""
    if re.search(r"\[출처", answer):
        return answer
    matches = _LAW_PATTERN.findall(answer)
    if not matches:
        return answer
    # 중복 제거, 최대 2개
    seen: list[str] = []
    for law_name, article in matches:
        label = f"{law_name.strip()} {article.strip()}"
        if label not in seen:
            seen.append(label)
        if len(seen) == 2:
            break
    citation = ", ".join(f"[출처: {c}]" for c in seen)
    return answer.rstrip() + "\n" + citation


def _build_context(chunks: list[RetrievedChunk], max_chars: int = 2000) -> str:
    parts: list[str] = []
    total = 0
    for i, c in enumerate(chunks, 1):
        header = f"[{i}] {c.document_title or c.source_type.value}"
        block = f"{header}\n{c.content.strip()}"
        if total + len(block) > max_chars:
            break
        parts.append(block)
        total += len(block)
    return "\n\n---\n\n".join(parts)


def _build_messages(context: str, query: str) -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content=_SYSTEM_PROMPT),
        ChatMessage(
            role="user",
            content=_USER_TEMPLATE.format(context=context, query=query),
        ),
    ]


class RAGPipeline:
    """검색 → 생성 전체 파이프라인.

    vLLM / infinity-emb 서비스가 꺼져 있어도 import 시 crash 없이
    실행 시점에 연결 오류를 반환한다.
    """

    def __init__(
        self,
        llm: LLMProvider,
        retriever: HybridRetriever,
        langfuse_client=None,       # langfuse.Langfuse 인스턴스 (선택)
    ) -> None:
        self._llm       = llm
        self._retriever = retriever
        self._lf        = langfuse_client

    async def run(self, query: RAGQuery) -> RAGResult:
        """단발성 전체 파이프라인 실행."""
        t0 = time.monotonic()
        trace_id = ""

        if self._lf:
            # Langfuse v4: start_as_current_observation → sync context manager,
            # async 함수 내에서도 with 블록으로 사용 가능
            with self._lf.start_as_current_observation(
                name="tax_rag",
                input={"query": query.query},
            ):
                chunks, answer = await self._execute(query)
                trace_id = self._lf.get_current_trace_id() or ""
                self._lf.update_current_span(
                    output={"answer_len": len(answer), "chunk_count": len(chunks)}
                )
        else:
            chunks, answer = await self._execute(query)

        latency = int((time.monotonic() - t0) * 1000)
        return RAGResult(
            query=query.query,
            chunks=chunks,
            answer=answer,
            trace_id=trace_id,
            latency_ms=latency,
        )

    _MODEL_LIMIT = 4096
    _MIN_OUTPUT  = 512

    def _max_tokens(self, messages: list[ChatMessage]) -> int:
        # 한국어 BPE는 1char ≈ 1.2token + 안전 마진 128
        total_chars = sum(len(m.content) for m in messages)
        estimated_input = int(total_chars * 1.2) + 128
        available = self._MODEL_LIMIT - estimated_input
        return max(self._MIN_OUTPUT, min(2048, available))

    async def _execute(
        self, query: RAGQuery
    ) -> tuple[list[RetrievedChunk], str]:
        """검색 + LLM 호출 코어 로직."""
        chunks   = await self._retriever.retrieve(query)
        context  = _build_context(chunks)
        messages = _build_messages(context, query.query)
        answer   = await self._llm.chat(messages, temperature=0.1, max_tokens=self._max_tokens(messages))
        return chunks, _ensure_citation(answer)

    async def stream(
        self, query: RAGQuery
    ) -> tuple[list[RetrievedChunk], AsyncIterator[str]]:
        """스트리밍 버전 — (청크 목록, 토큰 스트림) 반환."""
        chunks   = await self._retriever.retrieve(query)
        context  = _build_context(chunks)
        messages = _build_messages(context, query.query)
        stream   = self._llm.chat_stream(messages, temperature=0.1, max_tokens=self._max_tokens(messages))
        return chunks, stream


def build_pipeline(
    llm: LLMProvider | None = None,
    embedding=None,
    reranker=None,
) -> RAGPipeline:
    """환경변수에서 provider를 자동으로 생성해 RAGPipeline을 반환한다."""
    from ..providers.llm.vllm_provider import VLLMProvider
    from ..providers.embedding.infinity_provider import InfinityEmbeddingProvider
    from ..providers.reranker.infinity_reranker import InfinityRerankerProvider
    from ..providers.vectorstore.factory import get_vector_store

    llm       = llm       or VLLMProvider()
    embedding = embedding or InfinityEmbeddingProvider()
    reranker  = reranker  or InfinityRerankerProvider()
    store     = get_vector_store()

    retriever = HybridRetriever(embedding=embedding, reranker=reranker, store=store)

    # Langfuse v4 연결 시도 (실패해도 파이프라인 동작)
    lf = None
    try:
        from langfuse import Langfuse
        lf = Langfuse(
            public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
            secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""),
            host=os.environ.get("LANGFUSE_BASE_URL", "http://localhost:3000"),
        )
        lf.auth_check()     # 키·서버 연결 즉시 검증
    except Exception:
        lf = None

    return RAGPipeline(llm, retriever, langfuse_client=lf)
