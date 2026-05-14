"""Phase 6A — 멀티 에이전트 ERP 리스크 탐지 그래프.

구조:
  fraud_node ─────┐
  tax_node   ─────┤→ rag_node → aggregate_node → END
  (parallel 시뮬)─┘

LangGraph는 단일 스레드 StateGraph이므로 "parallel"은 세 노드를 순서대로 실행하되
각 노드가 독립된 state 키에 쓰는 방식으로 구현한다.
진짜 병렬 실행이 필요하면 langgraph.graph.Send fan-out 패턴으로 확장할 수 있다.

사용법:
  python scripts/run_risk_detect.py              # 샘플 픽스처 실행
  python scripts/run_risk_detect.py --no-rag     # RAG 없이 룰 탐지만
"""

from __future__ import annotations

import uuid
import warnings

warnings.filterwarnings("ignore")
# LangGraph/LangChain 임포트 시점 경고 사전 억제
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*allowed_objects.*")


# ══════════════════════════════════════════════════════════════════════════════
# 부정탐지 노드
# ══════════════════════════════════════════════════════════════════════════════

from .tracing import traced_node


@traced_node("node_fraud")
def node_fraud(state: dict) -> dict:
    """FraudDetectionEngine으로 거래 배치를 분석한다."""
    from core.fraud.engine import FraudDetectionEngine
    from core.fraud.models import Transaction

    txns = [Transaction(**t) for t in state["transactions"]]
    engine = FraudDetectionEngine()
    report = engine.analyze(txns)

    state["fraud_alerts"]  = [a.model_dump(mode="json") for a in report.alerts]
    state["fraud_overall"] = report.overall_risk.value
    state["fraud_summary"] = report.summary
    return state


# ══════════════════════════════════════════════════════════════════════════════
# 세무 리스크 노드 — Phase 6C: DB(vendor) + YAML(tax_rules) 기반
# ══════════════════════════════════════════════════════════════════════════════

@traced_node("node_tax")
async def node_tax_async(state: dict) -> dict:
    """Phase 6C: vendor 테이블 + tax_rules.yaml 기반 3-tier 룰을 적용한다."""
    from core.fraud.models import Transaction
    from .tax_config import load_tax_config
    from .vendor_repo import lookup_vendor

    cfg  = load_tax_config()
    txns = [Transaction(**t) for t in state["transactions"]]
    flags: list[dict] = []

    for txn in txns:
        acct  = txn.account_code
        amt   = txn.amount
        day   = txn.txn_datetime.day
        month = txn.txn_datetime.month
        vinfo = await lookup_vendor(txn.vendor_id) or {}

        # Tier 1 — 계정코드 + 금액
        for rule in cfg.account_rules:
            if any(acct.startswith(p) for p in rule.account_prefixes) and amt >= rule.min_amount:
                flags.append({
                    "rule":     rule.rule_id,
                    "severity": rule.severity,
                    "detail":   rule.detail,
                    "txn_ids":  [txn.txn_id],
                    "amount":   int(amt),
                    "vendor":   txn.vendor_id,
                })

        # Tier 2 — 월말·분기말 컷오프
        if day >= cfg.cutoff.day_threshold and any(
            acct.startswith(p) for p in cfg.cutoff.account_prefixes
        ):
            sfx = " (분기말)" if month in (3, 6, 9, 12) else ""
            flags.append({
                "rule":     cfg.cutoff.rule_id,
                "severity": cfg.cutoff.severity,
                "detail":   f"월말{sfx} 거래 — 기간귀속 컷오프 리스크 검토 필요",
                "txn_ids":  [txn.txn_id],
                "amount":   int(amt),
                "vendor":   txn.vendor_id,
            })

        # Tier 3 — 거래처 마스터
        vtype = vinfo.get("type", "domestic")
        for vrule in cfg.vendor_rules:
            if vtype == vrule.vendor_type:
                flags.append({
                    "rule":     vrule.rule_id,
                    "severity": vrule.severity,
                    "detail":   vrule.detail,
                    "txn_ids":  [txn.txn_id],
                    "amount":   int(amt),
                    "vendor":   txn.vendor_id,
                })

    state["tax_flags"]   = flags
    state["tax_summary"] = (
        f"세무 플래그 {len(flags)}건 — "
        + (", ".join(sorted({f['rule'] for f in flags})) if flags else "이상 없음")
    )
    return state


# ══════════════════════════════════════════════════════════════════════════════
# RAG 노드 (async)
# ══════════════════════════════════════════════════════════════════════════════

def _build_rag_queries(state: dict) -> list[str]:
    """fraud_alerts + tax_flags에서 상위 RAG 쿼리를 추출한다 (config 기반)."""
    from .tax_config import load_tax_config
    flag_to_query = load_tax_config().flag_to_query

    seen: set[str] = set()
    queries: list[str] = []

    for alert in state.get("fraud_alerts", [])[:3]:
        q = flag_to_query.get(alert.get("flag", ""))
        if q and q not in seen:
            seen.add(q)
            queries.append(q)

    for flag_obj in state.get("tax_flags", [])[:2]:
        q = flag_to_query.get(flag_obj.get("rule", ""))
        if q and q not in seen:
            seen.add(q)
            queries.append(q)

    return queries[:4]


@traced_node("node_rag")
async def node_rag(state: dict) -> dict:
    """상위 리스크 쿼리로 법령 컨텍스트를 검색한다 (async 내부 구현)."""
    queries = _build_rag_queries(state)
    state["rag_queries"]     = queries
    state["rag_chunks_used"] = []

    if not queries:
        state["rag_context"] = ""
        return state

    from core.providers.embedding.infinity_provider import InfinityEmbeddingProvider
    from core.providers.reranker.infinity_reranker import InfinityRerankerProvider
    from core.providers.vectorstore.factory import get_vector_store
    from core.rag.models import RAGMode, RAGQuery
    from core.rag.retriever import HybridRetriever

    store = get_vector_store()
    try:
        retriever = HybridRetriever(
            embedding=InfinityEmbeddingProvider(),
            reranker=InfinityRerankerProvider(),
            store=store,
        )

        parts: list[str] = []
        for q in queries:
            chunks = await retriever.retrieve(RAGQuery(query=q, top_k=2, mode=RAGMode.RERANK))
            for rank, c in enumerate(chunks, 1):
                parts.append(f"[{c.document_title}]\n{c.content[:300].strip()}")
                state["rag_chunks_used"].append({
                    "chunk_id":        c.chunk_id,
                    "source_type":     c.source_type.value,
                    "source_doc_id":   c.source_doc_id or c.document_title or "?",
                    "rank":            rank,
                    "retrieval_score": float(c.score),
                    "rerank_score":    float(c.rerank_score),
                    "query":           q,
                })

        state["rag_context"] = "\n\n---\n\n".join(parts)
    except Exception as e:
        state["rag_context"] = f"(RAG 검색 실패: {e})"
    finally:
        await store.close()

    return state


# ══════════════════════════════════════════════════════════════════════════════
# 통합 집계 노드
# ══════════════════════════════════════════════════════════════════════════════

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _merge_overall_risk(*risks: str) -> str:
    return max(risks, key=lambda r: _RISK_ORDER.get(r, 0))


@traced_node("node_aggregate")
async def node_aggregate(state: dict) -> dict:
    """fraud + tax + rag 결과를 통합해 최종 리스크 리포트를 생성한다."""
    fraud_risk  = state.get("fraud_overall", "low")
    tax_risk    = "medium" if state.get("tax_flags") else "low"
    overall     = _merge_overall_risk(fraud_risk, tax_risk)

    state["overall_risk"] = overall

    # 상위 5개 경보 (fraud + tax 통합)
    all_alerts = list(state.get("fraud_alerts", []))
    for tf in state.get("tax_flags", []):
        all_alerts.append({
            "flag":       tf["rule"],
            "risk_level": tf["severity"],
            "score":      0.5 if tf["severity"] == "medium" else 0.3,
            "detail":     tf["detail"],
            "txn_ids":    tf["txn_ids"],
        })
    all_alerts.sort(key=lambda a: -a.get("score", 0))
    state["top_alerts"] = all_alerts[:5]

    # 사람 검토 여부
    review_reasons: list[str] = []
    if overall in ("high", "critical"):
        review_reasons.append(f"통합 리스크 {overall.upper()}")
    if any(a.get("risk_level") == "critical" for a in state.get("fraud_alerts", [])):
        review_reasons.append("CRITICAL 경보 존재")
    if len(state.get("fraud_alerts", [])) >= 3:
        review_reasons.append(f"복합 경보 {len(state['fraud_alerts'])}건")

    state["needs_human_review"] = bool(review_reasons)
    state["review_reasons"]     = review_reasons

    # 리포트 조립
    lines = [
        f"══ ERP 리스크 탐지 리포트 ══",
        f"  대상 거래: {len(state['transactions'])}건",
        f"  통합 리스크: {overall.upper()}",
        "",
        f"  [부정탐지] {state.get('fraud_summary', '-')}",
        f"  [세무]     {state.get('tax_summary', '-')}",
    ]

    if state.get("top_alerts"):
        lines.append("")
        lines.append("  상위 경보:")
        for a in state["top_alerts"][:5]:
            risk = a.get("risk_level", "?")
            detail = a.get("detail", "")[:70]
            txn_ids = ", ".join(a.get("txn_ids", [])[:3])
            lines.append(f"    [{risk.upper()}] {detail} ({txn_ids})")

    if state.get("rag_context"):
        lines.append("")
        lines.append("  관련 법령 컨텍스트:")
        for q in state.get("rag_queries", []):
            lines.append(f"    • {q}")

    if review_reasons:
        lines.append("")
        lines.append(f"  ⚠ 인간 검토 필요: {' / '.join(review_reasons)}")

    state["risk_report"] = "\n".join(lines)

    # Phase 6E — lineage 기록 (실패해도 회차 결과는 보존)
    try:
        from .lineage_writer import write_lineage
        state["case_id"] = await write_lineage(state)
    except Exception as e:
        state["case_id"] = ""
        state["lineage_error"] = str(e)

    return state


# ══════════════════════════════════════════════════════════════════════════════
# 그래프 빌드
# ══════════════════════════════════════════════════════════════════════════════

def build_risk_graph(skip_rag: bool = False):
    """리스크 탐지 멀티 에이전트 그래프를 빌드·컴파일한다.

    Args:
        skip_rag: True이면 RAG 노드를 건너뛰고 룰 탐지만 실행한다.
    """

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from langgraph.graph import END, StateGraph

    from .risk_state import RiskState

    graph = StateGraph(RiskState)

    graph.add_node("fraud",     node_fraud)
    graph.add_node("tax",       node_tax_async)   # async — Phase 6C 부터 ainvoke 일관

    if skip_rag:
        async def _skip_rag(state):
            state["rag_queries"] = []
            state["rag_context"] = ""
            return state
        graph.add_node("rag", _skip_rag)
    else:
        graph.add_node("rag", node_rag)

    graph.add_node("aggregate", node_aggregate)

    graph.set_entry_point("fraud")
    graph.add_edge("fraud",     "tax")
    graph.add_edge("tax",       "rag")
    graph.add_edge("rag",       "aggregate")
    graph.add_edge("aggregate", END)

    return graph.compile()


def run_risk_detect(
    transactions: list[dict],
    skip_rag: bool = False,
    trace_id: str | None = None,
) -> dict:
    """동기 진입점 — QThread에서 호출. asyncio.run()은 여기 한 번만 쓴다."""
    import asyncio
    from .tracing import trace_span

    graph = build_risk_graph(skip_rag=skip_rag)

    initial: dict = {
        "transactions":      transactions,
        "trace_id":          trace_id or str(uuid.uuid4())[:8],
        "fraud_alerts":      [],
        "fraud_overall":     "low",
        "fraud_summary":     "",
        "tax_flags":         [],
        "tax_summary":       "",
        "rag_queries":       [],
        "rag_context":       "",
        "overall_risk":      "low",
        "risk_report":       "",
        "top_alerts":        [],
        "needs_human_review": False,
        "review_reasons":    [],
        "case_id":           "",
    }

    async def _run():
        with trace_span("risk_detect", input={"n_txns": len(transactions), "skip_rag": skip_rag}):
            return await graph.ainvoke(initial)

    return asyncio.run(_run())
