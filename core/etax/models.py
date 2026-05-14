"""전자세금계산서 KEC v3.0 Pydantic 모델."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class TaxInvoiceTypeCode(str, Enum):
    GENERAL       = "0101"   # 일반 세금계산서
    ZERO_RATE     = "0102"   # 영세율 세금계산서
    EXEMPT        = "0201"   # 일반 계산서(면세)
    EXEMPT_ZERO   = "0202"   # 영세 계산서


class PurposeCode(str, Enum):
    RECEIPT  = "01"   # 영수
    INVOICE  = "02"   # 청구


class AmendmentCode(str, Enum):
    ERROR_CORRECTION    = "1"   # 기재사항 착오 정정
    OTHER_CORRECTION    = "2"   # 착오 외 기재사항 정정
    DUPLICATE_ERROR     = "3"   # 착오 이중발급
    PRICE_CHANGE        = "4"   # 공급가액 변동
    CONTRACT_CANCELLED  = "5"   # 계약 해제
    RETURN              = "6"   # 환입(반품)
    LOCAL_LC            = "7"   # 내국신용장 사후 개설


class Party(BaseModel):
    """공급자 또는 공급받는자 정보."""
    brn: str = Field(description="사업자등록번호 10자리 (하이픈 제거)")
    name: str = Field(max_length=50)
    representative: str = ""
    address: str = ""
    business_type: str = ""    # 업태
    business_item: str = ""    # 종목
    email: str = ""

    @field_validator("brn")
    @classmethod
    def strip_hyphens(cls, v: str) -> str:
        return v.replace("-", "").replace(" ", "")


class TradeLineItem(BaseModel):
    """품목 라인 (TaxInvoiceTradeLineItem)."""
    seq: int = Field(ge=1)
    trade_date: date
    name: str = Field(max_length=100)
    spec: str = ""
    quantity: Decimal = Decimal("1")
    unit_price: Decimal = Decimal("0")
    supply_amount: Decimal = Decimal("0")   # ChargeableAmount
    tax_amount: Decimal = Decimal("0")
    note: str = ""

    def calc_tax(self, type_code: TaxInvoiceTypeCode) -> Decimal:
        """세율에 따른 세액 자동 계산."""
        if type_code in (TaxInvoiceTypeCode.ZERO_RATE, TaxInvoiceTypeCode.EXEMPT, TaxInvoiceTypeCode.EXEMPT_ZERO):
            return Decimal("0")
        return (self.supply_amount * Decimal("0.1")).quantize(Decimal("1"))


class TaxInvoice(BaseModel):
    """KEC v3.0 전자세금계산서 전체 모델."""

    # 관리정보
    issue_id: str = Field(
        default="",
        description="승인번호 24자리. 비워두면 builder가 자동 생성",
    )
    type_code: TaxInvoiceTypeCode = TaxInvoiceTypeCode.GENERAL
    issue_datetime: datetime = Field(default_factory=datetime.now)
    purpose_code: PurposeCode = PurposeCode.INVOICE

    # 기본정보
    issue_date: date = Field(default_factory=date.today)

    # 수정세금계산서
    is_amendment: bool = False
    amendment_code: Optional[AmendmentCode] = None
    original_issue_id: str = ""   # 원본 승인번호

    # 거래처
    invoicer: Party   # 공급자
    invoicee: Party   # 공급받는자

    # 합계 (자동 계산 가능)
    total_supply: Decimal = Decimal("0")
    total_tax: Decimal = Decimal("0")
    grand_total: Decimal = Decimal("0")

    # 결제 구분 (청구서 보조)
    cash_amount: Decimal = Decimal("0")
    credit_amount: Decimal = Decimal("0")   # 외상

    # 품목
    lines: list[TradeLineItem] = Field(default_factory=list, max_length=99)

    # 비고
    note: str = ""

    def recalc_totals(self) -> None:
        """라인 합계로 total_supply / total_tax / grand_total 재계산."""
        self.total_supply = sum(l.supply_amount for l in self.lines)
        self.total_tax    = sum(l.calc_tax(self.type_code) for l in self.lines)
        for l in self.lines:
            l.tax_amount = l.calc_tax(self.type_code)
        self.grand_total  = self.total_supply + self.total_tax
        self.credit_amount = self.grand_total   # 청구 기본값
