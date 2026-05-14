"""Phase 6E — risk_graph 회차 결과를 lineage 6-table 에 기록한다.

매핑:
  audit_case          ← 회차 단위. case_type='fraud_detection'.
  answer              ← 통합 결정 (decision=approve|escalate, decided_by='hybrid').
  rule_invocation     ← fraud_alert / tax_flag 각각.
  source_transaction  ← txn_ids 별 1행.
  evidence_chunk      ← RAG 청크 (다음 단계 — rag_node 가 chunk_id 회수 후 기록).
"""

from __future__ import annotations

import json
import uuid

from .db import get_pool


def compute_attribution(
    n_rules: int,
    n_chunks: int,
    overall_risk: str,
) -> tuple[float, float, bool, str]:
    """rule_weight + llm_weight = 1.0 산출. 감사 도메인 룰 우선 원칙 반영.

    - 둘 다 0           → 0.5 / 0.5 (의미 없는 case)
    - 룰만 (n_chunks=0)  → 1.0 / 0.0
    - 청크만 (n_rules=0) → 0.0 / 1.0
    - 둘 다 > 0          → rule_weight = max(0.7, n_rules / (n_rules + n_chunks))
                           (loadmap 의 'rule_weight ≥ 0.7' 원칙 강제)
    - conflict_flag: overall_risk ∈ {high, critical} AND n_chunks == 0
                     (강한 경보인데 근거 청크 없음)
    """
    if n_rules == 0 and n_chunks == 0:
        rw, lw = 0.5, 0.5
    elif n_chunks == 0:
        rw, lw = 1.0, 0.0
    elif n_rules == 0:
        rw, lw = 0.0, 1.0
    else:
        rw = max(0.7, n_rules / (n_rules + n_chunks))
        rw = round(rw, 3)
        lw = round(1.0 - rw, 3)
    conflict = (overall_risk in ("high", "critical")) and n_chunks == 0
    rationale = (
        f"룰 {n_rules}건, RAG 청크 {n_chunks}개 — "
        f"rule_weight {rw:.2f} / llm_weight {lw:.2f}"
        + (" [conflict: 강한 경보 + 근거 청크 없음]" if conflict else "")
    )
    return rw, lw, conflict, rationale


async def write_lineage(state: dict, question: str = "ERP 거래 배치 리스크 탐지") -> str:
    """state 를 읽어 lineage 테이블에 INSERT하고 case_id 를 반환한다."""
    pool = await get_pool()
    trace_id = state.get("trace_id") or str(uuid.uuid4())[:8]
    decision = "escalate" if state.get("needs_human_review") else "approve"
    overall = state.get("overall_risk", "low")
    confidence = {"low": 0.4, "medium": 0.6, "high": 0.8, "critical": 0.95}.get(overall, 0.5)

    async with pool.acquire() as conn:
        async with conn.transaction():
            case_id = await conn.fetchval(
                """INSERT INTO audit_case (trace_id, case_type, question)
                   VALUES ($1, 'fraud_detection', $2) RETURNING case_id""",
                trace_id, question,
            )
            answer_id = await conn.fetchval(
                """INSERT INTO answer (case_id, text, decision, confidence,
                                       decided_by, model_id, prompt_hash, prompt_version)
                   VALUES ($1, $2, $3, $4, 'hybrid', 'risk_graph_v6e', '-', '6e')
                   RETURNING answer_id""",
                case_id,
                state.get("risk_report", "")[:8000],
                decision,
                confidence,
            )
            for alert in state.get("fraud_alerts", []):
                await conn.execute(
                    """INSERT INTO rule_invocation
                       (answer_id, rule_set, rule_id, fired, matched_inputs, output, weight_in_decision)
                       VALUES ($1, 'fraud_redflag', $2, TRUE, $3, $4, $5)""",
                    answer_id,
                    alert.get("flag", ""),
                    json.dumps({"txn_ids": alert.get("txn_ids", [])}),
                    json.dumps({"detail": alert.get("detail", ""), "risk_level": alert.get("risk_level", "")}),
                    float(alert.get("score") or 0.5),
                )
            for tf in state.get("tax_flags", []):
                await conn.execute(
                    """INSERT INTO rule_invocation
                       (answer_id, rule_set, rule_id, fired, matched_inputs, output, weight_in_decision)
                       VALUES ($1, 'vat_korea', $2, TRUE, $3, $4, $5)""",
                    answer_id,
                    tf["rule"],
                    json.dumps({
                        "txn_ids": tf["txn_ids"],
                        "amount": tf["amount"],
                        "vendor": tf.get("vendor", ""),
                    }),
                    json.dumps({"detail": tf["detail"], "severity": tf["severity"]}),
                    0.4 if tf["severity"] == "medium" else (0.6 if tf["severity"] == "high" else 0.2),
                )
            txn_ids = {tid for a in state.get("fraud_alerts", []) for tid in a.get("txn_ids", [])}
            txn_ids |= {tid for tf in state.get("tax_flags", []) for tid in tf.get("txn_ids", [])}
            txn_index = {t["txn_id"]: t for t in state.get("transactions", [])}
            for tid in txn_ids:
                t = txn_index.get(tid)
                if t is None:
                    continue
                await conn.execute(
                    """INSERT INTO source_transaction
                       (answer_id, erp_table, erp_row_pk, fiscal_period, amount, account_code, contribution)
                       VALUES ($1, 'gl_journal', $2, $3, $4, $5, 'flagged')""",
                    answer_id, tid,
                    str(t.get("txn_datetime", ""))[:7],
                    t.get("amount"),
                    t.get("account_code"),
                )

            # Phase 6F — evidence_chunk: RAG 가 끌어쓴 청크들
            for ev in state.get("rag_chunks_used", []):
                await conn.execute(
                    """INSERT INTO evidence_chunk
                       (answer_id, source_type, source_doc_id, chunk_id,
                        retrieval_score, rerank_score, rank, used_in_prompt)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, TRUE)""",
                    answer_id,
                    ev.get("source_type", "tax_law"),
                    (ev.get("source_doc_id") or "?")[:128],
                    (ev.get("chunk_id") or "")[:128],
                    float(ev.get("retrieval_score") or 0.0),
                    float(ev.get("rerank_score") or 0.0),
                    int(ev.get("rank") or 1),
                )

            # Phase 6F — decision_attribution: rule vs LLM 가중치 분리
            n_rules = len(state.get("fraud_alerts", [])) + len(state.get("tax_flags", []))
            n_chunks = len(state.get("rag_chunks_used", []))
            rw, lw, conflict_flag, rationale = compute_attribution(
                n_rules, n_chunks, state.get("overall_risk", "low"),
            )
            await conn.execute(
                """INSERT INTO decision_attribution
                   (answer_id, rule_weight, llm_weight, rationale, conflict_flag)
                   VALUES ($1, $2, $3, $4, $5)""",
                answer_id, rw, lw, rationale, conflict_flag,
            )
    return str(case_id)
