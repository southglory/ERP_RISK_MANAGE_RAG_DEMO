"""LangGraph 분개 워크플로우 — Quote → PO → GR → GI → Invoice → Receipt."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional, TypedDict

from ..rules import KIFRS1115Engine, VATCalculator, VATCategory
from ..rules.models import Contract, RecognitionTiming
from .engine import JournalEngine


# ── 워크플로우 상태 ────────────────────────────────────────────────────────────

class WorkflowState(TypedDict):
    # 입력
    contract: Contract
    recognition_date: Optional[date]

    # 중간 상태
    kifrs_result: Optional[dict]           # KIFRS1115Result.model_dump()
    pending_journal_entries: list[dict]    # JournalEntry.model_dump()

    # 출고(GI) 데이터
    gi_supply_price: Optional[Decimal]
    gi_cost: Optional[Decimal]
    gi_vat_amount: Optional[Decimal]
    gi_source_doc: Optional[str]

    # 청구/수금 데이터
    invoice_source_doc: Optional[str]
    collection_amount: Optional[Decimal]
    collection_source_doc: Optional[str]

    # 흐름 제어
    journal_trigger: str     # 'point_sale' | 'deferred_sale' | 'mixed_sale' | 'advance_only' | 'hold'
    current_step: str
    errors: list[str]


# 싱글턴
_kifrs_engine = KIFRS1115Engine()
_vat_calc = VATCalculator()
_journal_engine = JournalEngine()


# ── 노드 함수 ──────────────────────────────────────────────────────────────────

def node_validate_contract(state: WorkflowState) -> WorkflowState:
    """1단계: K-IFRS 1115 전체 평가 → journal_trigger 결정."""
    contract = state["contract"]
    rec_date = state.get("recognition_date") or date.today()

    result = _kifrs_engine.evaluate(contract, recognition_date=rec_date)
    state["kifrs_result"] = result.model_dump(mode="json")
    state["journal_trigger"] = result.journal_trigger
    state["current_step"] = "validate_contract"
    return state


def node_receive_po(state: WorkflowState) -> WorkflowState:
    """PO 수령 — 선수금이 있을 때 선수금 분개 생성."""
    entries = state.get("pending_journal_entries") or []

    # PO 수령 단계에서 선수금 수령이 있으면 분개 생성
    contract = state["contract"]
    # 선수금은 contract 속성으로 전달되지 않으면 스킵
    state["current_step"] = "receive_po"
    state["pending_journal_entries"] = entries
    return state


def node_goods_receipt(state: WorkflowState) -> WorkflowState:
    """입고(GR) — 재고 자산화 분개."""
    entries = state.get("pending_journal_entries") or []
    gi_cost = state.get("gi_cost")

    if gi_cost and gi_cost > 0:
        vat_on_purchase = _vat_calc.calc(gi_cost, VATCategory.STANDARD).vat_amount
        entry = _journal_engine.purchase_credit(
            entry_date=state.get("recognition_date") or date.today(),
            cost=gi_cost,
            vat_amount=vat_on_purchase,
            source_doc=state.get("gi_source_doc") or "",
            memo="입고(GR) — 재고 매입",
        )
        entries.append(entry.model_dump(mode="json"))

    state["pending_journal_entries"] = entries
    state["current_step"] = "goods_receipt"
    return state


def node_goods_issue_point(state: WorkflowState) -> WorkflowState:
    """출고(GI) — 한 시점 매출 + 매출원가 분개."""
    entries = state.get("pending_journal_entries") or []
    entry_date = state.get("recognition_date") or date.today()
    supply = state.get("gi_supply_price") or Decimal("0")
    cost = state.get("gi_cost") or Decimal("0")
    vat = state.get("gi_vat_amount") or _vat_calc.calc(supply, VATCategory.STANDARD).vat_amount
    src = state.get("gi_source_doc") or ""

    if supply > 0:
        entries.append(
            _journal_engine.sale_credit(entry_date, supply, vat, src, "출고(GI) — 한 시점 매출")
            .model_dump(mode="json")
        )
    if cost > 0:
        entries.append(
            _journal_engine.sale_cogs(entry_date, cost, src)
            .model_dump(mode="json")
        )

    state["pending_journal_entries"] = entries
    state["current_step"] = "goods_issue_point"
    return state


def node_goods_issue_deferred(state: WorkflowState) -> WorkflowState:
    """출고(GI) — 기간 안분 매출: 계약부채 계상 + 매출원가."""
    entries = state.get("pending_journal_entries") or []
    entry_date = state.get("recognition_date") or date.today()
    supply = state.get("gi_supply_price") or Decimal("0")
    cost = state.get("gi_cost") or Decimal("0")
    vat = state.get("gi_vat_amount") or _vat_calc.calc(supply, VATCategory.STANDARD).vat_amount
    src = state.get("gi_source_doc") or ""

    if supply > 0:
        entries.append(
            _journal_engine.deferred_invoice(entry_date, supply, vat, src)
            .model_dump(mode="json")
        )
    # 서비스형 상품(SaaS)은 COGS 없음 — HW 동반 시만 처리
    if cost > 0:
        entries.append(
            _journal_engine.sale_cogs(entry_date, cost, src)
            .model_dump(mode="json")
        )

    state["pending_journal_entries"] = entries
    state["current_step"] = "goods_issue_deferred"
    return state


def node_monthly_recognition(state: WorkflowState) -> WorkflowState:
    """매월 실행 — 계약부채 → 매출 안분 분개 생성.

    kifrs_result의 step5 over_time 스케줄 중 당월 분을 인식한다.
    """
    entries = state.get("pending_journal_entries") or []
    kifrs = state.get("kifrs_result")
    entry_date = state.get("recognition_date") or date.today()
    period_label = entry_date.strftime("%Y-%m")

    if kifrs and kifrs.get("step5"):
        for rec in kifrs["step5"]:
            if rec.get("timing") == RecognitionTiming.OVER_TIME.value:
                for sch in rec.get("schedule", []):
                    if sch["period_label"] == period_label and not sch["recognized"]:
                        amount = Decimal(str(sch["amount"]))
                        entries.append(
                            _journal_engine.monthly_recognition(
                                entry_date, amount, memo=f"기간 인식 {period_label}"
                            ).model_dump(mode="json")
                        )
                        sch["recognized"] = True

    state["pending_journal_entries"] = entries
    state["current_step"] = "monthly_recognition"
    return state


def node_collect_payment(state: WorkflowState) -> WorkflowState:
    """수금 — 외상매출금 회수 분개."""
    entries = state.get("pending_journal_entries") or []
    amount = state.get("collection_amount")
    if amount and amount > 0:
        entry = _journal_engine.collection(
            entry_date=state.get("recognition_date") or date.today(),
            amount=amount,
            source_doc=state.get("collection_source_doc") or "",
        )
        entries.append(entry.model_dump(mode="json"))

    state["pending_journal_entries"] = entries
    state["current_step"] = "collect_payment"
    return state


def node_hold(state: WorkflowState) -> WorkflowState:
    """계약 식별 실패 — 매출 인식 보류."""
    state["current_step"] = "hold"
    state["errors"] = (state.get("errors") or []) + [
        f"계약 식별 실패: {state.get('kifrs_result', {}).get('step1', {}).get('notes', '')}"
    ]
    return state


# ── 라우팅 함수 ────────────────────────────────────────────────────────────────

def route_by_trigger(state: WorkflowState) -> str:
    trigger = state.get("journal_trigger", "hold")
    if trigger == "point_sale":
        return "goods_issue_point"
    elif trigger == "deferred_sale":
        return "goods_issue_deferred"
    elif trigger == "mixed_sale":
        return "goods_issue_point"   # 혼합은 point 먼저, monthly_recognition 별도 실행
    elif trigger == "advance_only":
        return "receive_po"
    else:
        return "hold"


# ── 그래프 빌드 ────────────────────────────────────────────────────────────────

def build_workflow():
    """분개 자동생성 LangGraph 워크플로우를 빌드·컴파일한다."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from langgraph.graph import END as _END, StateGraph as _StateGraph  # noqa: PLC0415

    graph = _StateGraph(WorkflowState)

    graph.add_node("validate_contract",    node_validate_contract)
    graph.add_node("receive_po",           node_receive_po)
    graph.add_node("goods_receipt",        node_goods_receipt)
    graph.add_node("goods_issue_point",    node_goods_issue_point)
    graph.add_node("goods_issue_deferred", node_goods_issue_deferred)
    graph.add_node("monthly_recognition",  node_monthly_recognition)
    graph.add_node("collect_payment",      node_collect_payment)
    graph.add_node("hold",                 node_hold)

    graph.set_entry_point("validate_contract")

    graph.add_conditional_edges(
        "validate_contract",
        route_by_trigger,
        {
            "goods_issue_point":    "goods_receipt",
            "goods_issue_deferred": "goods_receipt",
            "receive_po":           "receive_po",
            "hold":                 "hold",
        },
    )

    graph.add_edge("receive_po",           _END)
    graph.add_edge("goods_receipt",        "goods_issue_point")
    graph.add_edge("goods_issue_point",    "collect_payment")
    graph.add_edge("goods_issue_deferred", "monthly_recognition")
    graph.add_edge("monthly_recognition",  "collect_payment")
    graph.add_edge("collect_payment",      _END)
    graph.add_edge("hold",                 _END)

    return graph.compile()


# 싱글턴 컴파일 인스턴스
workflow = build_workflow()
