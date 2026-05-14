"""Phase 6E — GUI 패널에서 한 case 의 결정 근거를 한 번에 보여주기 위한 DTO."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from .db import get_pool


class RuleEvidence(BaseModel):
    rule_set: str
    rule_id: str
    fired: bool
    matched_inputs: dict[str, Any]
    output: dict[str, Any]
    weight: float


class TxnEvidence(BaseModel):
    erp_row_pk: str
    amount: str | None
    account_code: str | None
    contribution: str


class EvidenceChunk(BaseModel):
    chunk_id: str
    source_type: str
    source_doc_id: str
    rank: int
    retrieval_score: float
    rerank_score: float


class DecisionAttribution(BaseModel):
    rule_weight: float
    llm_weight: float
    conflict_flag: bool
    rationale: str


class CaseExplanation(BaseModel):
    case_id: str
    trace_id: str
    question: str
    decision: str
    confidence: float
    summary: str
    rules: list[RuleEvidence]
    txns: list[TxnEvidence]
    evidence: list[EvidenceChunk] = []
    attribution: DecisionAttribution | None = None


def _as_dict(value: Any) -> dict[str, Any]:
    """asyncpg JSONB 컬럼이 str/dict 어느 쪽으로 와도 dict 로 정규화."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {}
    return {}


async def load_case_explanation(case_id: str) -> CaseExplanation | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        case = await conn.fetchrow(
            "SELECT case_id, trace_id, question FROM audit_case WHERE case_id::text = $1",
            case_id,
        )
        if not case:
            return None
        ans = await conn.fetchrow(
            "SELECT answer_id, text, decision, confidence FROM answer WHERE case_id = $1",
            case["case_id"],
        )
        if not ans:
            return None
        rules = await conn.fetch(
            """SELECT rule_set, rule_id, fired, matched_inputs, output, weight_in_decision
               FROM rule_invocation WHERE answer_id = $1
               ORDER BY weight_in_decision DESC""",
            ans["answer_id"],
        )
        txns = await conn.fetch(
            """SELECT erp_row_pk, amount, account_code, contribution
               FROM source_transaction WHERE answer_id = $1
               ORDER BY erp_row_pk""",
            ans["answer_id"],
        )
        evidence_rows = await conn.fetch(
            """SELECT chunk_id, source_type, source_doc_id, rank,
                      retrieval_score, rerank_score
               FROM evidence_chunk WHERE answer_id = $1 ORDER BY rank""",
            ans["answer_id"],
        )
        attr_row = await conn.fetchrow(
            """SELECT rule_weight, llm_weight, conflict_flag, rationale
               FROM decision_attribution WHERE answer_id = $1""",
            ans["answer_id"],
        )
    return CaseExplanation(
        case_id=str(case["case_id"]),
        trace_id=case["trace_id"],
        question=case["question"],
        decision=ans["decision"] or "",
        confidence=float(ans["confidence"] or 0.0),
        summary=ans["text"] or "",
        rules=[RuleEvidence(
            rule_set=r["rule_set"],
            rule_id=r["rule_id"],
            fired=r["fired"],
            matched_inputs=_as_dict(r["matched_inputs"]),
            output=_as_dict(r["output"]),
            weight=float(r["weight_in_decision"] or 0.0),
        ) for r in rules],
        txns=[TxnEvidence(
            erp_row_pk=t["erp_row_pk"],
            amount=str(t["amount"]) if t["amount"] is not None else None,
            account_code=t["account_code"],
            contribution=t["contribution"] or "evidence",
        ) for t in txns],
        evidence=[EvidenceChunk(
            chunk_id=e["chunk_id"],
            source_type=e["source_type"],
            source_doc_id=e["source_doc_id"],
            rank=int(e["rank"]),
            retrieval_score=float(e["retrieval_score"] or 0.0),
            rerank_score=float(e["rerank_score"] or 0.0),
        ) for e in evidence_rows],
        attribution=(DecisionAttribution(
            rule_weight=float(attr_row["rule_weight"]),
            llm_weight=float(attr_row["llm_weight"]),
            conflict_flag=bool(attr_row["conflict_flag"]),
            rationale=attr_row["rationale"] or "",
        ) if attr_row else None),
    )
