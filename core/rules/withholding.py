"""원천세 계산 룰 엔진 (소득세법·법인세법·조세조약 기준)."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel


class IncomeType(str, Enum):
    BUSINESS_SERVICE = "business_service"   # 사업소득 (인적용역 3.3%)
    ROYALTY = "royalty"                     # 사용료소득 (라이선스·로열티)
    INTEREST = "interest"                   # 이자소득
    DIVIDEND = "dividend"                   # 배당소득
    OTHER = "other"                         # 기타소득 22%


class WithholdingResult(BaseModel):
    gross_amount: Decimal
    withholding_tax: Decimal          # 국세
    local_tax: Decimal                # 지방소득세 (국세의 10%)
    total_withholding: Decimal
    net_payment: Decimal
    rate_applied: Decimal
    treaty_applied: bool = False
    country_code: str = "KR"
    notes: str = ""


# ── 국내 거주자·내국법인 기본세율 ──────────────────────────────────────────────

_DOMESTIC_RATES: dict[IncomeType, Decimal] = {
    IncomeType.BUSINESS_SERVICE: Decimal("0.03"),   # 소득세 3% + 지방세 0.3% = 3.3%
    IncomeType.ROYALTY:          Decimal("0.20"),
    IncomeType.INTEREST:         Decimal("0.14"),
    IncomeType.DIVIDEND:         Decimal("0.14"),
    IncomeType.OTHER:            Decimal("0.20"),   # 필요경비 60% 공제 후 22% → 총액 기준 약 8.8%
}

# ── 비거주자·외국법인 국내세법 기본세율 (지방세 미포함) ─────────────────────────

_FOREIGN_BASE_RATES: dict[IncomeType, Decimal] = {
    IncomeType.BUSINESS_SERVICE: Decimal("0.02"),
    IncomeType.ROYALTY:          Decimal("0.20"),
    IncomeType.INTEREST:         Decimal("0.20"),
    IncomeType.DIVIDEND:         Decimal("0.20"),
    IncomeType.OTHER:            Decimal("0.20"),
}

# ── 조세조약 제한세율 (국세 기준, 지방세 별도) ────────────────────────────────
# 형식: {국가코드: {IncomeType: 제한세율}}
# 사용료는 주로 10%, 일부 소프트웨어는 조약별 상이 — 실무상 10% 적용이 가장 일반적
_TREATY_RATES: dict[str, dict[IncomeType, Decimal]] = {
    "US": {
        IncomeType.ROYALTY:   Decimal("0.10"),
        IncomeType.INTEREST:  Decimal("0.12"),
        IncomeType.DIVIDEND:  Decimal("0.10"),
    },
    "JP": {
        IncomeType.ROYALTY:   Decimal("0.10"),
        IncomeType.INTEREST:  Decimal("0.10"),
        IncomeType.DIVIDEND:  Decimal("0.05"),
    },
    "CN": {
        IncomeType.ROYALTY:   Decimal("0.10"),
        IncomeType.INTEREST:  Decimal("0.10"),
        IncomeType.DIVIDEND:  Decimal("0.05"),
    },
    "GB": {
        IncomeType.ROYALTY:   Decimal("0.10"),
        IncomeType.INTEREST:  Decimal("0.10"),
        IncomeType.DIVIDEND:  Decimal("0.05"),
    },
    "DE": {
        IncomeType.ROYALTY:   Decimal("0.10"),
        IncomeType.INTEREST:  Decimal("0.10"),
        IncomeType.DIVIDEND:  Decimal("0.05"),
    },
    "SG": {
        IncomeType.ROYALTY:   Decimal("0.15"),
        IncomeType.INTEREST:  Decimal("0.10"),
        IncomeType.DIVIDEND:  Decimal("0.10"),
    },
    "IE": {
        IncomeType.ROYALTY:   Decimal("0.00"),   # 아일랜드 — 사용료 면제
        IncomeType.INTEREST:  Decimal("0.00"),
        IncomeType.DIVIDEND:  Decimal("0.10"),
    },
}

_LOCAL_TAX_RATE = Decimal("0.10")  # 지방소득세 = 국세의 10%


class WithholdingTaxEngine:
    """원천세 계산 엔진."""

    def calc_domestic(
        self,
        income_type: IncomeType,
        amount: Decimal,
    ) -> WithholdingResult:
        """국내 거주자·내국법인에게 지급 시 원천세를 계산한다."""
        rate = _DOMESTIC_RATES.get(income_type, Decimal("0.20"))
        withholding = (amount * rate).quantize(Decimal("1"))
        local = (withholding * _LOCAL_TAX_RATE).quantize(Decimal("1"))
        total = withholding + local

        return WithholdingResult(
            gross_amount=amount,
            withholding_tax=withholding,
            local_tax=local,
            total_withholding=total,
            net_payment=amount - total,
            rate_applied=rate + rate * _LOCAL_TAX_RATE,
            treaty_applied=False,
            country_code="KR",
        )

    def calc_foreign(
        self,
        country_code: str,
        income_type: IncomeType,
        amount: Decimal,
        *,
        treaty_cert_obtained: bool = True,
    ) -> WithholdingResult:
        """비거주자·외국법인에게 지급 시 원천세를 계산한다.

        Args:
            country_code: ISO 2자리 국가 코드 (예: 'US', 'JP')
            income_type: 소득 종류
            amount: 지급 총액
            treaty_cert_obtained: 거주자증명서 수취 여부 — False이면 국내세법 세율 강제 적용
        """
        treaty_rates = _TREATY_RATES.get(country_code.upper(), {})
        treaty_rate = treaty_rates.get(income_type)
        base_rate = _FOREIGN_BASE_RATES.get(income_type, Decimal("0.20"))

        treaty_applied = False
        notes = ""

        if treaty_rate is not None and treaty_cert_obtained:
            rate = treaty_rate
            treaty_applied = True
            notes = f"조세조약 적용 ({country_code})"
        else:
            rate = base_rate
            if treaty_rate is not None and not treaty_cert_obtained:
                notes = "거주자증명서 미수취 — 국내세법 세율 적용. 추후 경정청구 가능"

        withholding = (amount * rate).quantize(Decimal("1"))
        # 지방소득세: 조약 적용 시에도 국세의 10%
        local = (withholding * _LOCAL_TAX_RATE).quantize(Decimal("1"))
        total = withholding + local

        return WithholdingResult(
            gross_amount=amount,
            withholding_tax=withholding,
            local_tax=local,
            total_withholding=total,
            net_payment=amount - total,
            rate_applied=rate,
            treaty_applied=treaty_applied,
            country_code=country_code.upper(),
            notes=notes,
        )
