"""분개 자동생성 엔진 — K-IFRS 1115 5단계와 연동."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field

from .accounts import (
    Account,
    ADVANCE_PAID,
    ADVANCE_RECEIVED,
    ALLOWANCE_DOUBTFUL,
    BAD_DEBT_EXPENSE,
    BANK,
    COGS,
    COMMISSION_REVENUE,
    DEFERRED_REVENUE,
    FX_AR,
    FX_TRANS_GAIN,
    INVENTORY,
    LICENSE_EXPENSE,
    SALES,
    TRADE_AP,
    TRADE_AR,
    VAT_DEDUCTIBLE,
    VAT_PAYABLE,
    WITHHOLDING_PAYABLE,
)


class DrCr(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class JournalLine(BaseModel):
    account: Account
    drcr: DrCr
    amount: Decimal
    memo: str = ""

    class Config:
        arbitrary_types_allowed = True


class JournalEntry(BaseModel):
    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    entry_date: date
    description: str
    lines: list[JournalLine] = Field(default_factory=list)
    source_doc: str = ""  # 원천 문서 번호 (PO, GI, Invoice 번호 등)

    def debit_total(self) -> Decimal:
        return sum(l.amount for l in self.lines if l.drcr == DrCr.DEBIT)

    def credit_total(self) -> Decimal:
        return sum(l.amount for l in self.lines if l.drcr == DrCr.CREDIT)

    def is_balanced(self) -> bool:
        return self.debit_total() == self.credit_total()

    class Config:
        arbitrary_types_allowed = True


def _dr(account: Account, amount: Decimal, memo: str = "") -> JournalLine:
    return JournalLine(account=account, drcr=DrCr.DEBIT, amount=amount, memo=memo)


def _cr(account: Account, amount: Decimal, memo: str = "") -> JournalLine:
    return JournalLine(account=account, drcr=DrCr.CREDIT, amount=amount, memo=memo)


class JournalEngine:
    """K-IFRS 1115 5단계 결과 및 ERP 이벤트에 대응하는 자동 분개 생성기."""

    # ── 매출 관련 ───────────────────────────────────────────────────────────────

    def sale_credit(
        self,
        entry_date: date,
        supply_price: Decimal,
        vat_amount: Decimal,
        source_doc: str = "",
        memo: str = "외상 매출",
    ) -> JournalEntry:
        """출고(GI) — 한 시점 외상 매출 분개."""
        total = supply_price + vat_amount
        return JournalEntry(
            entry_date=entry_date,
            description=memo,
            source_doc=source_doc,
            lines=[
                _dr(TRADE_AR,   total,        "매출채권"),
                _cr(SALES,      supply_price, "수행의무 이행"),
                _cr(VAT_PAYABLE, vat_amount,  "부가세예수금"),
            ],
        )

    def sale_cogs(
        self,
        entry_date: date,
        cost: Decimal,
        source_doc: str = "",
    ) -> JournalEntry:
        """출고(GI) — 매출원가 동시 인식 (계속기록법)."""
        return JournalEntry(
            entry_date=entry_date,
            description="매출원가 인식",
            source_doc=source_doc,
            lines=[
                _dr(COGS,      cost, "원가"),
                _cr(INVENTORY, cost, "재고 출고"),
            ],
        )

    def advance_receipt(
        self,
        entry_date: date,
        advance_amount: Decimal,
        vat_amount: Decimal = Decimal("0"),
        source_doc: str = "",
    ) -> JournalEntry:
        """계약 시점 선수금 수령 — 수행의무 미이행."""
        lines = [_dr(BANK, advance_amount + vat_amount, "선수금 수령")]
        lines.append(_cr(ADVANCE_RECEIVED, advance_amount, "선수금"))
        if vat_amount:
            lines.append(_cr(VAT_PAYABLE, vat_amount, "부가세예수금(선수)"))
        return JournalEntry(
            entry_date=entry_date,
            description="선수금 수령",
            source_doc=source_doc,
            lines=lines,
        )

    def advance_to_revenue(
        self,
        entry_date: date,
        amount: Decimal,
        source_doc: str = "",
    ) -> JournalEntry:
        """인도 후 선수금 → 매출 대체."""
        return JournalEntry(
            entry_date=entry_date,
            description="선수금 → 매출 대체",
            source_doc=source_doc,
            lines=[
                _dr(ADVANCE_RECEIVED, amount, "선수금 제거"),
                _cr(SALES,            amount, "매출 인식"),
            ],
        )

    def deferred_invoice(
        self,
        entry_date: date,
        supply_price: Decimal,
        vat_amount: Decimal,
        source_doc: str = "",
        memo: str = "SaaS/유지보수 청구",
    ) -> JournalEntry:
        """구독·유지보수 청구 시 — 계약부채(선수수익) 계상."""
        total = supply_price + vat_amount
        return JournalEntry(
            entry_date=entry_date,
            description=memo,
            source_doc=source_doc,
            lines=[
                _dr(TRADE_AR,       total,        "청구"),
                _cr(DEFERRED_REVENUE, supply_price, "계약부채"),
                _cr(VAT_PAYABLE,    vat_amount,   "부가세예수금"),
            ],
        )

    def monthly_recognition(
        self,
        entry_date: date,
        amount: Decimal,
        source_doc: str = "",
        memo: str = "매월 수익 안분",
    ) -> JournalEntry:
        """기간 안분 — 계약부채 → 매출."""
        return JournalEntry(
            entry_date=entry_date,
            description=memo,
            source_doc=source_doc,
            lines=[
                _dr(DEFERRED_REVENUE, amount, "계약부채 감소"),
                _cr(SALES,            amount, "기간 인식 매출"),
            ],
        )

    def agency_sale(
        self,
        entry_date: date,
        commission: Decimal,
        vat_amount: Decimal,
        source_doc: str = "",
    ) -> JournalEntry:
        """대리인(순액) 매출 — 수수료만 인식."""
        total = commission + vat_amount
        return JournalEntry(
            entry_date=entry_date,
            description="대리인 수수료 매출",
            source_doc=source_doc,
            lines=[
                _dr(TRADE_AR,         total,     "수수료 채권"),
                _cr(COMMISSION_REVENUE, commission, "수수료수익"),
                _cr(VAT_PAYABLE,      vat_amount, "부가세예수금"),
            ],
        )

    # ── 매입 관련 ───────────────────────────────────────────────────────────────

    def purchase_credit(
        self,
        entry_date: date,
        cost: Decimal,
        vat_amount: Decimal,
        source_doc: str = "",
        memo: str = "외상 매입",
    ) -> JournalEntry:
        """입고(GR) — 재고 매입 분개."""
        total = cost + vat_amount
        return JournalEntry(
            entry_date=entry_date,
            description=memo,
            source_doc=source_doc,
            lines=[
                _dr(INVENTORY,       cost,       "재고 입고"),
                _dr(VAT_DEDUCTIBLE,  vat_amount, "부가세대급금"),
                _cr(TRADE_AP,        total,      "외상매입금"),
            ],
        )

    def advance_payment(
        self,
        entry_date: date,
        amount: Decimal,
        source_doc: str = "",
    ) -> JournalEntry:
        """선급금 지급 (발주 시)."""
        return JournalEntry(
            entry_date=entry_date,
            description="선급금 지급",
            source_doc=source_doc,
            lines=[
                _dr(ADVANCE_PAID, amount, "선급금"),
                _cr(BANK,         amount, "보통예금 출금"),
            ],
        )

    def advance_to_inventory(
        self,
        entry_date: date,
        cost: Decimal,
        vat_amount: Decimal,
        source_doc: str = "",
    ) -> JournalEntry:
        """입고 후 선급금 → 재고 대체."""
        return JournalEntry(
            entry_date=entry_date,
            description="선급금 → 재고 대체",
            source_doc=source_doc,
            lines=[
                _dr(INVENTORY,      cost,       "재고 자산화"),
                _dr(VAT_DEDUCTIBLE, vat_amount, "부가세대급금"),
                _cr(ADVANCE_PAID,   cost,       "선급금 제거"),
                _cr(TRADE_AP,       vat_amount, "미지급금(VAT)"),
            ],
        )

    # ── 수금·지급 ────────────────────────────────────────────────────────────────

    def collection(
        self,
        entry_date: date,
        amount: Decimal,
        source_doc: str = "",
    ) -> JournalEntry:
        """외상매출금 회수."""
        return JournalEntry(
            entry_date=entry_date,
            description="외상매출금 회수",
            source_doc=source_doc,
            lines=[
                _dr(BANK,     amount, "입금"),
                _cr(TRADE_AR, amount, "채권 소멸"),
            ],
        )

    def ap_payment(
        self,
        entry_date: date,
        amount: Decimal,
        source_doc: str = "",
    ) -> JournalEntry:
        """외상매입금 결제."""
        return JournalEntry(
            entry_date=entry_date,
            description="외상매입금 결제",
            source_doc=source_doc,
            lines=[
                _dr(TRADE_AP, amount, "채무 소멸"),
                _cr(BANK,     amount, "출금"),
            ],
        )

    # ── 채권 대손 ────────────────────────────────────────────────────────────────

    def bad_debt_provision(
        self,
        entry_date: date,
        amount: Decimal,
        source_doc: str = "",
    ) -> JournalEntry:
        """기말 기대신용손실 충당금 설정."""
        return JournalEntry(
            entry_date=entry_date,
            description="대손충당금 설정",
            source_doc=source_doc,
            lines=[
                _dr(BAD_DEBT_EXPENSE,  amount, "대손상각비"),
                _cr(ALLOWANCE_DOUBTFUL, amount, "충당금 증가"),
            ],
        )

    def bad_debt_writeoff(
        self,
        entry_date: date,
        amount: Decimal,
        source_doc: str = "",
    ) -> JournalEntry:
        """실제 대손 발생 — 충당금 차감."""
        return JournalEntry(
            entry_date=entry_date,
            description="대손 발생",
            source_doc=source_doc,
            lines=[
                _dr(ALLOWANCE_DOUBTFUL, amount, "충당금 차감"),
                _cr(TRADE_AR,           amount, "채권 제거"),
            ],
        )

    # ── 외화 관련 ────────────────────────────────────────────────────────────────

    def fx_revaluation_gain(
        self,
        entry_date: date,
        gain: Decimal,
        source_doc: str = "",
    ) -> JournalEntry:
        """결산일 외화채권 환산이익."""
        return JournalEntry(
            entry_date=entry_date,
            description="외화환산이익",
            source_doc=source_doc,
            lines=[
                _dr(FX_AR,        gain, "환산 후 장부가"),
                _cr(FX_TRANS_GAIN, gain, "외화환산이익"),
            ],
        )

    # ── 원천세 지급 (외국 SW 벤더 라이선스) ──────────────────────────────────────

    def foreign_license_payment(
        self,
        entry_date: date,
        gross_amount: Decimal,
        withholding_tax: Decimal,
        local_tax: Decimal,
        source_doc: str = "",
        memo: str = "외국 SW 라이선스 지급",
    ) -> JournalEntry:
        """외국법인 사용료 지급 — 원천세 예수 후 순액 송금."""
        net_payment = gross_amount - withholding_tax - local_tax
        total_withholding = withholding_tax + local_tax
        return JournalEntry(
            entry_date=entry_date,
            description=memo,
            source_doc=source_doc,
            lines=[
                _dr(LICENSE_EXPENSE,    gross_amount,     "지급수수료"),
                _cr(BANK,              net_payment,      "외화 송금"),
                _cr(WITHHOLDING_PAYABLE, total_withholding, "원천세 예수금"),
            ],
        )
