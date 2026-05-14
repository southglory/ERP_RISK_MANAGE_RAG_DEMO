import os

import pytest

from core.agents.explanation import load_case_explanation
from core.agents.lineage_writer import write_lineage

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL 미설정",
)


async def test_case_explanation_includes_evidence_and_attribution():
    state = {
        "transactions":  [],
        "fraud_alerts":  [{"flag": "BENFORD", "score": 0.9, "detail": "x",
                            "txn_ids": [], "risk_level": "medium"}],
        "tax_flags":     [],
        "trace_id":      "phase6f_explain",
        "overall_risk":  "medium",
        "risk_report":   "r",
        "rag_chunks_used": [
            {"chunk_id": "c1", "source_type": "tax_law", "source_doc_id": "부가가치세법",
             "rank": 1, "retrieval_score": 0.8, "rerank_score": 0.9, "query": "q"},
        ],
    }
    case_id = await write_lineage(state)
    exp = await load_case_explanation(case_id)
    assert exp is not None
    assert len(exp.evidence) == 1
    assert exp.evidence[0].chunk_id == "c1"
    assert exp.evidence[0].source_doc_id == "부가가치세법"
    assert exp.attribution is not None
    assert exp.attribution.rule_weight + exp.attribution.llm_weight == pytest.approx(1.0, abs=0.001)
