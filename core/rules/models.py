"""Pydantic data models for K-IFRS 1115 rule engine."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ItemType(str, Enum):
    HW = "hw"                          # 하드웨어 박스 — 한 시점 인식
    SW_PERPETUAL = "sw_perpetual"      # 영구 SW 라이선스 — 한 시점 (키 전달)
    SW_SUBSCRIPTION = "sw_subscription"  # SW 구독/SaaS — 기간 안분
    SAAS = "saas"                      # SaaS (접근권) — 기간 안분
    MAINTENANCE = "maintenance"        # 유지보수·기술지원 — 기간 안분
    INSTALLATION = "installation"      # 설치 용역 — 진행률 또는 완료 시점
    WARRANTY_ASSURANCE = "warranty_assurance"  # 확신유형 보증 — 수행의무 아님(충당부채)
    WARRANTY_SERVICE = "warranty_service"      # 용역유형 보증(연장) — 기간 안분


class RecognitionBasis(str, Enum):
    GROSS = "gross"   # 본인 — 총액 인식
    NET = "net"       # 대리인 — 순액(수수료)만 인식


class RecognitionTiming(str, Enum):
    POINT_IN_TIME = "point_in_time"
    OVER_TIME = "over_time"


class ContractLineItem(BaseModel):
    line_id: str
    item_type: ItemType
    description: str
    list_price: Decimal = Field(ge=0)
    ssp: Decimal = Field(ge=0, description="개별판매가격(Stand-alone Selling Price)")
    quantity: int = Field(default=1, ge=1)
    discount: Decimal = Field(default=Decimal("0"), ge=0)
    variable_consideration: Decimal = Field(
        default=Decimal("0"),
        description="변동대가(리베이트·환불 추정액) — 부(-)면 거래가격 차감",
    )
    service_months: Optional[int] = Field(
        default=None,
        description="기간 안분 항목의 서비스 개월 수",
    )
    revenue_basis: RecognitionBasis = RecognitionBasis.GROSS

    @property
    def contract_price(self) -> Decimal:
        return (self.list_price - self.discount) * self.quantity

    @property
    def ssp_total(self) -> Decimal:
        return self.ssp * self.quantity


class Contract(BaseModel):
    contract_id: str
    customer_id: str
    contract_date: date
    lines: list[ContractLineItem] = Field(min_length=1)

    # 1단계 계약 식별 5요건 체크 플래그 (ERP 데이터 기반 자동 검증)
    approved_by_both_parties: bool = False
    rights_identifiable: bool = False
    payment_terms_identifiable: bool = False
    commercial_substance: bool = False
    collectability_probable: bool = False

    # 특수 속성
    is_combination_contract: bool = False  # 계약 결합 여부
    currency: str = "KRW"

    @property
    def total_contract_price(self) -> Decimal:
        return sum(line.contract_price for line in self.lines)

    @property
    def total_ssp(self) -> Decimal:
        return sum(line.ssp_total for line in self.lines)


# ── Step 1 결과 ────────────────────────────────────────────────────────────────

class ContractValidationResult(BaseModel):
    is_valid_contract: bool
    failed_conditions: list[str] = Field(default_factory=list)
    disposition: str = Field(
        description="유효 계약이면 'proceed', 아니면 'advance_receipt' 또는 'hold'"
    )
    notes: str = ""


# ── Step 2 결과 ────────────────────────────────────────────────────────────────

class PerformanceObligation(BaseModel):
    po_id: str
    line_ids: list[str]             # 하나 이상의 계약 라인이 결합될 수 있음
    item_type: ItemType
    description: str
    is_distinct: bool
    recognition_timing: RecognitionTiming
    service_months: Optional[int] = None
    revenue_basis: RecognitionBasis = RecognitionBasis.GROSS
    ssp: Decimal = Decimal("0")     # 배분 전 개별판매가


class PerfObligationResult(BaseModel):
    obligations: list[PerformanceObligation]
    non_obligation_lines: list[str] = Field(
        default_factory=list,
        description="수행의무 아닌 항목(확신유형 보증 등) line_ids",
    )


# ── Step 3 결과 ────────────────────────────────────────────────────────────────

class TransactionPriceResult(BaseModel):
    gross_contract_price: Decimal
    variable_consideration_included: Decimal = Decimal("0")
    transaction_price: Decimal
    has_significant_financing: bool = False
    notes: str = ""


# ── Step 4 결과 ────────────────────────────────────────────────────────────────

class SSPAllocationResult(BaseModel):
    total_ssp: Decimal
    transaction_price: Decimal
    allocations: dict[str, Decimal]   # po_id → 배분된 거래가격


# ── Step 5 결과 ────────────────────────────────────────────────────────────────

class RecognitionScheduleEntry(BaseModel):
    period_label: str      # 예: "2025-01"
    amount: Decimal
    recognized: bool = False


class RecognitionResult(BaseModel):
    po_id: str
    timing: RecognitionTiming
    allocated_price: Decimal
    recognition_date: Optional[date] = None        # 한 시점 인식일
    schedule: list[RecognitionScheduleEntry] = Field(default_factory=list)  # 기간 안분 스케줄


# ── Full 5-step pipeline result ────────────────────────────────────────────────

class KIFRS1115Result(BaseModel):
    contract_id: str
    step1: ContractValidationResult
    step2: Optional[PerfObligationResult] = None
    step3: Optional[TransactionPriceResult] = None
    step4: Optional[SSPAllocationResult] = None
    step5: list[RecognitionResult] = Field(default_factory=list)
    journal_trigger: str = Field(
        default="",
        description="LangGraph 분기 지시: 'point_sale' | 'deferred_sale' | 'advance_only' | 'hold'",
    )
