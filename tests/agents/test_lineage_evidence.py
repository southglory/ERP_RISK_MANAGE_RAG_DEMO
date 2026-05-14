import os

import pytest

from core.agents.db import get_pool
from core.agents.lineage_writer import write_lineage

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL 미설정",
)


async def test_write_lineage_inserts_evidence_chunks():
    state = {
        "transactions":  [{"txn_id": "T1", "amount": "100", "account_code": "521",
                            "txn_datetime": "2026-05-01T10:00:00"}],
        "fraud_alerts":  [{"flag": "BENFORD", "score": 0.9, "detail": "x",
                            "txn_ids": ["T1"], "risk_level": "high"}],
        "tax_flags":     [],
        "trace_id":      "phase6f_evidence",
        "overall_risk":  "high",
        "risk_report":   "r",
        "rag_chunks_used": [
            {
                "chunk_id":        "synth_buga_004_aaaa",
                "source_type":     "tax_law",
                "source_doc_id":   "부가가치세법",
                "rank":            1,
                "retrieval_score": 0.82,
                "rerank_score":    0.91,
                "query":           "부가가치세 신고기한",
            },
            {
                "chunk_id":        "synth_buga_008_bbbb",
                "source_type":     "tax_law",
                "source_doc_id":   "법인세법",
                "rank":            2,
                "retrieval_score": 0.78,
                "rerank_score":    0.88,
                "query":           "부가가치세 신고기한",
            },
        ],
    }
    case_id = await write_lineage(state)
    assert case_id

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT chunk_id, source_doc_id, rank, retrieval_score, rerank_score
               FROM evidence_chunk
               WHERE answer_id IN (SELECT answer_id FROM answer WHERE case_id::text=$1)
               ORDER BY rank""",
            case_id,
        )
    assert len(rows) == 2
    assert rows[0]["chunk_id"]    == "synth_buga_004_aaaa"
    assert rows[0]["rank"]        == 1
    assert float(rows[0]["retrieval_score"]) == pytest.approx(0.82, abs=0.001)
    assert float(rows[1]["rerank_score"])    == pytest.approx(0.88, abs=0.001)
