"""Phase 6A — 멀티 에이전트 리스크 탐지 공유 상태."""

from __future__ import annotations

from typing import TypedDict


class RiskState(TypedDict):
    # ── 입력 ──────────────────────────────────────────────────────────────────
    transactions: list[dict]        # Transaction.model_dump() 목록
    trace_id: str

    # ── 부정탐지 에이전트 ─────────────────────────────────────────────────────
    fraud_alerts: list[dict]        # FraudAlert.model_dump() 목록
    fraud_overall: str              # low / medium / high / critical
    fraud_summary: str

    # ── 세무 에이전트 ─────────────────────────────────────────────────────────
    tax_flags: list[dict]           # {rule, severity, detail, txn_ids}
    tax_summary: str

    # ── RAG 에이전트 ─────────────────────────────────────────────────────────
    rag_queries: list[str]          # 상위 alert에서 생성된 검색 쿼리
    rag_context: str                # 법령 컨텍스트 (집약)
    rag_chunks_used: list[dict]     # Phase 6F: evidence_chunk 행에 대응 (chunk_id, score, rank…)

    # ── 통합 리포트 ───────────────────────────────────────────────────────────
    overall_risk: str               # low / medium / high / critical
    risk_report: str                # 사람이 읽을 수 있는 리포트
    top_alerts: list[dict]          # 상위 5개 경보
    needs_human_review: bool
    review_reasons: list[str]

    # ── Phase 6E: lineage ─────────────────────────────────────────────────────
    case_id: str                    # audit_case.case_id (lineage 기록 시)
