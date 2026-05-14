"""부가가치세(VAT) 분류 및 계산 룰 엔진 (부가세법 기준)."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel

from .models import ItemType


class VATCategory(str, Enum):
    STANDARD = "standard"    # 10% 일반과세
    ZERO_RATE = "zero_rate"  # 0% 영세율 (세금계산서 발급)
    EXEMPT = "exempt"        # 면세 (계산서만)


_STANDARD_RATE = Decimal("0.10")
_ZERO_RATE = Decimal("0")


class VATResult(BaseModel):
    supply_price: Decimal
    vat_amount: Decimal
    total: Decimal
    category: VATCategory
    rate: Decimal
    notes: str = ""


# IT 디스트리뷰션에서 면세인 상품 타입 (출판물·교육용역 등 — SW는 원칙 과세)
_EXEMPT_ITEM_TYPES: set[ItemType] = set()  # 현재 IT 스택 내 면세 없음


def classify_vat(
    item_type: ItemType,
    *,
    is_export: bool = False,
    is_foreign_vendor_royalty: bool = False,
    is_overseas_saas_non_deductible: bool = False,
) -> VATCategory:
    """VAT 분류를 결정한다.

    Args:
        item_type: 공급 품목 유형
        is_export: 수출 재화 또는 외화획득 용역이면 True → 영세율
        is_foreign_vendor_royalty: 국외사업자 사용료 지급 시 역무 공급
        is_overseas_saas_non_deductible: 국외 SaaS 대리납부 대상이면 True
    """
    if item_type in _EXEMPT_ITEM_TYPES:
        return VATCategory.EXEMPT

    if is_export:
        return VATCategory.ZERO_RATE

    # 국외사업자 전자적 용역(SaaS) 대리납부 — 공급받는 자가 면세겸영 시
    # 여기서는 단순히 표준세율로 처리(분개에서 대리납부 표시)
    return VATCategory.STANDARD


class VATCalculator:
    """공급가액과 VAT 분류를 받아 세액을 계산한다."""

    def calc(
        self,
        supply_price: Decimal,
        category: VATCategory,
        *,
        notes: str = "",
    ) -> VATResult:
        if category == VATCategory.STANDARD:
            rate = _STANDARD_RATE
            vat_amount = (supply_price * rate).quantize(Decimal("1"))
        elif category == VATCategory.ZERO_RATE:
            rate = _ZERO_RATE
            vat_amount = Decimal("0")
        else:
            rate = _ZERO_RATE
            vat_amount = Decimal("0")
            notes = notes or "면세 — 세금계산서 불가, 계산서 발급"

        return VATResult(
            supply_price=supply_price,
            vat_amount=vat_amount,
            total=supply_price + vat_amount,
            category=category,
            rate=rate,
            notes=notes,
        )

    def reverse_calc(
        self,
        vat_inclusive_price: Decimal,
        category: VATCategory,
    ) -> VATResult:
        """VAT 포함가에서 공급가액을 역산한다."""
        if category == VATCategory.STANDARD:
            supply = (vat_inclusive_price / (1 + _STANDARD_RATE)).quantize(
                Decimal("1")
            )
            vat_amount = vat_inclusive_price - supply
        else:
            supply = vat_inclusive_price
            vat_amount = Decimal("0")

        return VATResult(
            supply_price=supply,
            vat_amount=vat_amount,
            total=vat_inclusive_price,
            category=category,
            rate=_STANDARD_RATE if category == VATCategory.STANDARD else _ZERO_RATE,
        )
