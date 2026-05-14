"""Phase 4-1 감사 케이스 워크플로우 — 7노드 LangGraph 상태기계.

intake → classify → rule → rag → llm → xai → review

모든 LLM/RAG 노드는 async. UI에서 asyncio.run() 또는 qasync loop로 호출.
"""

from __future__ import annotations

import warnings
from typing import TypedDict

warnings.filterwarnings("ignore")


# ══════════════════════════════════════════════════════════════════════════════
# 상태 정의
# ══════════════════════════════════════════════════════════════════════════════

class AuditState(TypedDict):
    # ── 입력 ──────────────────────────────────────────────────────────────────
    question: str
    trace_id: str

    # ── 1. intake ─────────────────────────────────────────────────────────────
    validated: bool
    intake_error: str

    # ── 2. classify ───────────────────────────────────────────────────────────
    case_type: str          # revenue_recognition | tax_risk | fraud_detection | contract_review

    # ── 3. rule ───────────────────────────────────────────────────────────────
    rule_fired: bool
    rule_output: dict       # 룰 엔진 결과 요약
    rule_confidence: float  # 0~1

    # ── 4. rag ────────────────────────────────────────────────────────────────
    retrieved_chunks: list[dict]
    context: str

    # ── 5. llm ────────────────────────────────────────────────────────────────
    answer: str
    llm_confidence: float   # 0~1 (답변 내 확신도 추정)

    # ── 6. xai ────────────────────────────────────────────────────────────────
    rule_weight: float      # 결정에서 룰의 기여도 (합: 1.0)
    llm_weight: float       # 결정에서 LLM의 기여도
    conflict_flag: bool     # 룰 결론 ↔ LLM 결론 불일치
    rationale: str          # 사람이 읽을 수 있는 결정 근거

    # ── 7. review ─────────────────────────────────────────────────────────────
    needs_human_review: bool
    review_reason: str


# ══════════════════════════════════════════════════════════════════════════════
# 분류 키워드 맵
# ══════════════════════════════════════════════════════════════════════════════

_CLASSIFY_PATTERNS: list[tuple[str, list[str]]] = [
    ("revenue_recognition", [
        "수익 인식", "매출 인식", "수행의무", "거래가격", "SSP", "안분",
        "K-IFRS 1115", "1115호", "선수금", "계약부채", "본인", "대리인",
        "saas", "구독", "라이선스 인식", "영구 라이선스", "키 전달", "기간 안분",
        "point-in-time", "over-time", "수행 의무",
    ]),
    ("tax_risk", [
        "부가가치세", "부가세", "원천징수", "원천세", "사용료", "로열티",
        "세율", "세금계산서", "법인세", "소득세", "가산세", "납부지연",
        "조세조약", "거주자증명서", "영세율", "면세", "공급 시기",
    ]),
    ("fraud_detection", [
        "부정", "이상", "가공거래", "분식", "횡령", "라운드트리핑",
        "벤포드", "중복 거래", "분할 결제", "비업무 시간",
        "이전가격", "기간귀속", "밀어넣기",
    ]),
    ("contract_review", [
        "계약", "위약금", "하도급", "SLA", "지연이자", "지급보증",
        "손해배상", "해지", "판례", "대법원", "민법", "상법",
        "계약 해제", "이행 보증",
    ]),
]


def _classify_question(question: str) -> str:
    """질문 텍스트에서 case_type을 결정한다 (키워드 다수결)."""
    q_lower = question.lower()
    scores: dict[str, int] = {ct: 0 for ct, _ in _CLASSIFY_PATTERNS}
    for case_type, keywords in _CLASSIFY_PATTERNS:
        for kw in keywords:
            if kw.lower() in q_lower:
                scores[case_type] += 1
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "tax_risk"   # 기본값


# ══════════════════════════════════════════════════════════════════════════════
# 룰 디스패처
# ══════════════════════════════════════════════════════════════════════════════

def _run_rule_tax_risk(question: str) -> tuple[bool, dict, float]:
    """세무 리스크 — 원천세 키워드에서 간이 계산."""
    from core.rules.withholding import WithholdingTaxEngine, IncomeType
    from decimal import Decimal

    engine = WithholdingTaxEngine()

    # 국가코드 추출
    country_map = {"미국": "US", "일본": "JP", "중국": "CN",
                   "독일": "DE", "영국": "GB", "아일랜드": "IE", "싱가포르": "SG"}
    country = next((code for name, code in country_map.items() if name in question), None)

    # 소득 종류 추출
    income = IncomeType.ROYALTY if any(w in question for w in ("사용료", "로열티", "라이선스")) else None

    if country and income:
        cert = "거주자증명서" not in question or "없음" not in question
        result = engine.calc_foreign(country, income, Decimal("1000000"), treaty_cert_obtained=cert)
        return True, {
            "country": country,
            "income_type": income.value,
            "rate": str(result.rate_applied),
            "treaty_applied": result.treaty_applied,
            "notes": result.notes,
        }, 0.85

    # 가산세 키워드
    if "가산세" in question or "납부지연" in question:
        return True, {
            "rule": "국세기본법 제47조의3",
            "formula": "미납세액 × 경과일수 × 0.022% / 1일",
        }, 0.90

    return False, {}, 0.0


def _run_rule_revenue(question: str) -> tuple[bool, dict, float]:
    """수익인식 — K-IFRS 1115 판단 힌트."""
    hints: list[str] = []
    confidence = 0.0

    if any(w in question for w in ("SaaS", "구독", "접근권")):
        hints.append("기간 안분 (over-time) 인식 — 매월 정액 분할")
        confidence = 0.80
    if any(w in question for w in ("영구 라이선스", "키 전달", "SW 라이선스")):
        hints.append("한 시점 (point-in-time) 인식 — 키 전달 시")
        confidence = 0.80
    if any(w in question for w in ("하드웨어", "HW", "서버")):
        hints.append("한 시점 인식 — 인도·검수 시")
        confidence = 0.75
    if any(w in question for w in ("본인", "대리인", "총액", "순액")):
        hints.append("본인/대리인 판단 — B37 3지표 (주된책임·재고위험·가격결정권) 확인 필요")
        confidence = 0.70

    if hints:
        return True, {"kifrs_1115_hints": hints, "reference": "K-IFRS 1115"}, confidence
    return False, {}, 0.0


def _run_rule_fraud(question: str) -> tuple[bool, dict, float]:
    """부정 탐지 — 패턴 식별."""
    patterns: list[str] = []
    if any(w in question for w in ("벤포드", "첫째 자리", "분포")):
        patterns.append("Benford's Law 카이제곱 검정 필요")
    if any(w in question for w in ("중복", "동일 금액", "반복")):
        patterns.append("중복 거래 탐지 패턴 적용")
    if any(w in question for w in ("한도", "100만", "분할")):
        patterns.append("한도 직하 분할 패턴 탐지")
    if any(w in question for w in ("기간귀속", "분기말", "밀어넣기")):
        patterns.append("기간귀속 조작 패턴 — 분기말 거래 급증 분석")
    if patterns:
        return True, {"fraud_patterns": patterns}, 0.75
    return False, {}, 0.0


def _dispatch_rule(case_type: str, question: str) -> tuple[bool, dict, float]:
    """case_type에 맞는 룰 엔진을 실행하고 (fired, output, confidence)를 반환한다."""
    if case_type == "tax_risk":
        return _run_rule_tax_risk(question)
    if case_type == "revenue_recognition":
        return _run_rule_revenue(question)
    if case_type == "fraud_detection":
        return _run_rule_fraud(question)
    return False, {}, 0.0   # contract_review는 RAG 중심


# ══════════════════════════════════════════════════════════════════════════════
# XAI 가중치 산출
# ══════════════════════════════════════════════════════════════════════════════

def _compute_xai(
    rule_fired: bool,
    rule_confidence: float,
    answer: str,
    rule_output: dict,
) -> tuple[float, float, bool, str]:
    """(rule_weight, llm_weight, conflict_flag, rationale)를 반환한다."""
    if not rule_fired:
        rule_weight = 0.0
        llm_weight  = 1.0
        conflict    = False
        rationale   = "룰 엔진 미발동 — LLM 단독 판단"
        return rule_weight, llm_weight, conflict, rationale

    # 룰 신뢰도에 비례해 가중치 배분 (회계 도메인: 룰 우선 원칙)
    rule_weight = min(0.9, rule_confidence)
    llm_weight  = round(1.0 - rule_weight, 3)

    # 충돌 감지: 룰이 "거부/hold"인데 LLM이 "가능/인정"으로 답한 경우
    rule_str = str(rule_output).lower()
    answer_lower = answer.lower()
    rule_negative = any(w in rule_str for w in ("hold", "불가", "미충족", "거부"))
    llm_positive  = any(w in answer_lower for w in ("가능", "인정", "적용", "가능합니다"))
    conflict = rule_negative and llm_positive

    # 근거 문장 생성
    parts: list[str] = []
    if "rule" in rule_output:
        parts.append(f"적용 룰: {rule_output['rule']}")
    if "kifrs_1115_hints" in rule_output:
        parts.append("; ".join(rule_output["kifrs_1115_hints"][:2]))
    if "fraud_patterns" in rule_output:
        parts.append("; ".join(rule_output["fraud_patterns"][:2]))
    if "rate" in rule_output:
        parts.append(f"적용 세율: {rule_output['rate']}")
    if conflict:
        parts.append("⚠️ 룰 결론과 LLM 결론 불일치 — 검토 필요")

    rationale = " | ".join(parts) if parts else f"룰 신뢰도 {rule_confidence:.0%}"
    return rule_weight, llm_weight, conflict, rationale


# ══════════════════════════════════════════════════════════════════════════════
# 노드 함수
# ══════════════════════════════════════════════════════════════════════════════

def node_intake(state: AuditState) -> AuditState:
    """1. 입력 검증 — 질문이 비어있으면 오류."""
    q = (state.get("question") or "").strip()
    if not q:
        state["validated"] = False
        state["intake_error"] = "질문이 비어 있습니다."
    else:
        state["validated"] = True
        state["intake_error"] = ""
    return state


def node_classify(state: AuditState) -> AuditState:
    """2. 케이스 유형 분류 — 키워드 다수결."""
    state["case_type"] = _classify_question(state["question"])
    return state


def node_rule(state: AuditState) -> AuditState:
    """3. 룰 엔진 발동 — case_type에 맞는 규칙 집합 실행."""
    fired, output, confidence = _dispatch_rule(
        state["case_type"], state["question"]
    )
    state["rule_fired"]      = fired
    state["rule_output"]     = output
    state["rule_confidence"] = confidence
    return state


async def node_rag(state: AuditState, retriever) -> AuditState:
    """4. 하이브리드 검색 — dense + sparse + RRF + reranker."""
    from core.rag.models import RAGQuery, RAGMode

    query = RAGQuery(query=state["question"], top_k=5, mode=RAGMode.RERANK)
    chunks = await retriever.retrieve(query)

    state["retrieved_chunks"] = [
        {"title": c.document_title, "content": c.content[:300], "score": c.rerank_score or c.score}
        for c in chunks
    ]

    # 컨텍스트 조립 (LLM 프롬프트용)
    parts: list[str] = []
    for i, c in enumerate(chunks, 1):
        parts.append(f"[{i}] {c.document_title}\n{c.content.strip()}")
    state["context"] = "\n\n---\n\n".join(parts)
    return state


async def node_llm(state: AuditState, llm) -> AuditState:
    """5. LLM 답변 생성 — 룰 결과 + RAG 컨텍스트 결합 프롬프트."""
    from core.providers.base import ChatMessage
    from core.rag.pipeline import _SYSTEM_PROMPT, _ensure_citation

    rule_hint = ""
    if state["rule_fired"]:
        rule_hint = f"\n[룰 엔진 판단]\n{state['rule_output']}\n"

    user_content = (
        f"[참고 문서]\n{state['context']}"
        f"{rule_hint}"
        f"\n[질문] {state['question']}"
        "\n\n위 질문에 한국어로 답하세요. 답변 마지막 줄은 반드시 [출처: 법령명 제○조] 형식으로 끝내세요."
    )

    messages = [
        ChatMessage(role="system", content=_SYSTEM_PROMPT),
        ChatMessage(role="user",   content=user_content),
    ]

    # 토큰 예산 계산 (pipeline._max_tokens 로직 재사용)
    total_chars = sum(len(m.content) for m in messages)
    estimated_input = int(total_chars * 1.2) + 128
    max_tokens = max(512, min(2048, 4096 - estimated_input))

    answer = await llm.chat(messages, temperature=0.1, max_tokens=max_tokens)
    state["answer"] = _ensure_citation(answer)

    # 확신도 추정 — "확인되지 않습니다" 패턴이 없으면 높음
    state["llm_confidence"] = 0.4 if "확인되지 않습니다" in answer else 0.8
    return state


def node_xai(state: AuditState) -> AuditState:
    """6. XAI Attribution — 룰·LLM 기여도 + 충돌 감지."""
    rw, lw, conflict, rationale = _compute_xai(
        state["rule_fired"],
        state["rule_confidence"],
        state["answer"],
        state["rule_output"],
    )
    state["rule_weight"]   = rw
    state["llm_weight"]    = lw
    state["conflict_flag"] = conflict
    state["rationale"]     = rationale
    return state


def node_review(state: AuditState) -> AuditState:
    """7. 검토 라우팅 — 낮은 신뢰도 또는 충돌 시 사람 검토 큐."""
    combined_confidence = (
        state["rule_weight"] * state["rule_confidence"]
        + state["llm_weight"] * state["llm_confidence"]
    )
    needs_review = combined_confidence < 0.7 or state["conflict_flag"]

    state["needs_human_review"] = needs_review
    if needs_review:
        reasons: list[str] = []
        if combined_confidence < 0.7:
            reasons.append(f"통합 신뢰도 {combined_confidence:.0%} < 70%")
        if state["conflict_flag"]:
            reasons.append("룰-LLM 결론 충돌")
        state["review_reason"] = " / ".join(reasons)
    else:
        state["review_reason"] = ""
    return state


# ══════════════════════════════════════════════════════════════════════════════
# 라우팅
# ══════════════════════════════════════════════════════════════════════════════

def route_intake(state: AuditState) -> str:
    return "classify" if state["validated"] else "__end__"


# ══════════════════════════════════════════════════════════════════════════════
# 그래프 빌드
# ══════════════════════════════════════════════════════════════════════════════

def build_audit_workflow(retriever=None, llm=None):
    """감사 케이스 7노드 워크플로우를 빌드·컴파일한다.

    Args:
        retriever: HybridRetriever 인스턴스 (None이면 실행 시 환경변수로 생성)
        llm:       LLMProvider 인스턴스  (None이면 실행 시 환경변수로 생성)
    """

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from langgraph.graph import END, StateGraph

    # 의존성 지연 생성
    def _get_retriever():
        if retriever is not None:
            return retriever
        from core.providers.embedding.infinity_provider import InfinityEmbeddingProvider
        from core.providers.reranker.infinity_reranker import InfinityRerankerProvider
        from core.rag.retriever import HybridRetriever
        return HybridRetriever(InfinityEmbeddingProvider(), InfinityRerankerProvider())

    def _get_llm():
        if llm is not None:
            return llm
        from core.providers.llm.vllm_provider import VLLMProvider
        return VLLMProvider()

    # async 노드 래퍼
    async def _node_rag(state):
        return await node_rag(state, _get_retriever())

    async def _node_llm(state):
        return await node_llm(state, _get_llm())

    graph = StateGraph(AuditState)

    graph.add_node("intake",   node_intake)
    graph.add_node("classify", node_classify)
    graph.add_node("rule",     node_rule)
    graph.add_node("rag",      _node_rag)
    graph.add_node("llm",      _node_llm)
    graph.add_node("xai",      node_xai)
    graph.add_node("review",   node_review)

    graph.set_entry_point("intake")
    graph.add_conditional_edges("intake", route_intake, {"classify": "classify", "__end__": END})
    graph.add_edge("classify", "rule")
    graph.add_edge("rule",     "rag")
    graph.add_edge("rag",      "llm")
    graph.add_edge("llm",      "xai")
    graph.add_edge("xai",      "review")
    graph.add_edge("review",   END)

    return graph.compile()
