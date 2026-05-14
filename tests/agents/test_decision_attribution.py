import os

import pytest

from core.agents.db import get_pool
from core.agents.lineage_writer import compute_attribution, write_lineage


def test_attribution_rules_only():
    rw, lw, conflict, _ = compute_attribution(
        n_rules=3, n_chunks=0, overall_risk="medium",
    )
    assert rw == pytest.approx(1.0)
    assert lw == pytest.approx(0.0)
    assert conflict is False   # medium 에서는 conflict 아님


def test_attribution_chunks_only():
    rw, lw, _, _ = compute_attribution(
        n_rules=0, n_chunks=5, overall_risk="low",
    )
    assert rw == pytest.approx(0.0)
    assert lw == pytest.approx(1.0)


def test_attribution_mixed_rule_dominant():
    rw, lw, conflict, _ = compute_attribution(
        n_rules=2, n_chunks=3, overall_risk="medium",
    )
    # 룰 우선 원칙: rule_weight >= 0.7
    assert rw >= 0.7
    assert rw + lw == pytest.approx(1.0, abs=0.001)
    assert conflict is False


def test_attribution_conflict_flag_when_high_risk_no_rag():
    rw, lw, conflict, rationale = compute_attribution(
        n_rules=4, n_chunks=0, overall_risk="critical",
    )
    assert conflict is True
    assert "conflict" in rationale.lower()


def test_attribution_zero_zero_falls_back_half():
    rw, lw, _, _ = compute_attribution(
        n_rules=0, n_chunks=0, overall_risk="low",
    )
    assert rw == pytest.approx(0.5)
    assert lw == pytest.approx(0.5)


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DB 미설정")
async def test_write_lineage_inserts_decision_attribution():
    state = {
        "transactions":  [{"txn_id": "T1", "amount": "100", "account_code": "521",
                            "txn_datetime": "2026-05-01T10:00:00"}],
        "fraud_alerts":  [{"flag": "BENFORD", "score": 0.9, "detail": "x",
                            "txn_ids": ["T1"], "risk_level": "high"}],
        "tax_flags":     [{"rule": "WH-001", "severity": "medium", "detail": "y",
                            "txn_ids": ["T1"], "amount": "100"}],
        "trace_id":      "phase6f_attr",
        "overall_risk":  "high",
        "risk_report":   "r",
        "rag_chunks_used": [
            {"chunk_id": "c1", "source_type": "tax_law", "source_doc_id": "d",
             "rank": 1, "retrieval_score": 0.8, "rerank_score": 0.9, "query": "q"},
        ],
    }
    case_id = await write_lineage(state)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT rule_weight, llm_weight, conflict_flag, rationale
               FROM decision_attribution
               WHERE answer_id IN (SELECT answer_id FROM answer WHERE case_id::text=$1)""",
            case_id,
        )
    assert row is not None
    rw = float(row["rule_weight"])
    lw = float(row["llm_weight"])
    assert rw + lw == pytest.approx(1.0, abs=0.001)
    assert rw >= 0.7
    assert row["conflict_flag"] is False
