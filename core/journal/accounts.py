"""한국 표준 계정과목 — IT 디스트리뷰션 실무 코드."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AccountCategory(str, Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


class NormalBalance(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


@dataclass(frozen=True)
class Account:
    code: str
    name: str
    category: AccountCategory
    normal_balance: NormalBalance
    is_control: bool = False  # 통제계정 여부


# ── 자산 ──────────────────────────────────────────────────────────────────────
CASH                = Account("1010", "현금",                 AccountCategory.ASSET,     NormalBalance.DEBIT)
BANK                = Account("1020", "보통예금",             AccountCategory.ASSET,     NormalBalance.DEBIT)
TRADE_AR            = Account("1100", "외상매출금",           AccountCategory.ASSET,     NormalBalance.DEBIT)
ALLOWANCE_DOUBTFUL  = Account("1105", "대손충당금",           AccountCategory.ASSET,     NormalBalance.CREDIT)  # 차감
ADVANCE_PAID        = Account("1130", "선급금",               AccountCategory.ASSET,     NormalBalance.DEBIT)
VAT_DEDUCTIBLE      = Account("1150", "부가세대급금",         AccountCategory.ASSET,     NormalBalance.DEBIT)
INVENTORY           = Account("1200", "상품",                 AccountCategory.ASSET,     NormalBalance.DEBIT)
CONSIGNMENT_GOODS   = Account("1210", "적송품",               AccountCategory.ASSET,     NormalBalance.DEBIT)
RETURN_ASSET        = Account("1220", "반품제품회수권",       AccountCategory.ASSET,     NormalBalance.DEBIT)
FX_AR               = Account("1120", "외화매출채권",         AccountCategory.ASSET,     NormalBalance.DEBIT)

# ── 부채 ──────────────────────────────────────────────────────────────────────
TRADE_AP            = Account("2100", "외상매입금",           AccountCategory.LIABILITY, NormalBalance.CREDIT)
ADVANCE_RECEIVED    = Account("2110", "선수금",               AccountCategory.LIABILITY, NormalBalance.CREDIT)
DEFERRED_REVENUE    = Account("2120", "계약부채(선수수익)",   AccountCategory.LIABILITY, NormalBalance.CREDIT)
VAT_PAYABLE         = Account("2130", "부가세예수금",         AccountCategory.LIABILITY, NormalBalance.CREDIT)
WITHHOLDING_PAYABLE = Account("2140", "예수금(원천세)",       AccountCategory.LIABILITY, NormalBalance.CREDIT)
REFUND_LIABILITY    = Account("2150", "환불부채",             AccountCategory.LIABILITY, NormalBalance.CREDIT)
TAX_PAYABLE         = Account("2160", "미지급세금",           AccountCategory.LIABILITY, NormalBalance.CREDIT)
PROVISION_WARRANTY  = Account("2170", "제품보증충당부채",     AccountCategory.LIABILITY, NormalBalance.CREDIT)
ACCRUED_EXPENSE     = Account("2180", "미지급금",             AccountCategory.LIABILITY, NormalBalance.CREDIT)

# ── 수익 ──────────────────────────────────────────────────────────────────────
SALES               = Account("4000", "매출",                 AccountCategory.REVENUE,   NormalBalance.CREDIT)
COMMISSION_REVENUE  = Account("4010", "수수료수익",           AccountCategory.REVENUE,   NormalBalance.CREDIT)
INTEREST_INCOME     = Account("4020", "이자수익",             AccountCategory.REVENUE,   NormalBalance.CREDIT)
FX_GAIN             = Account("4030", "외환차익",             AccountCategory.REVENUE,   NormalBalance.CREDIT)
FX_TRANS_GAIN       = Account("4031", "외화환산이익",         AccountCategory.REVENUE,   NormalBalance.CREDIT)
BAD_DEBT_REVERSAL   = Account("4040", "대손충당금환입",       AccountCategory.REVENUE,   NormalBalance.CREDIT)
SALES_RETURN        = Account("4005", "매출에누리및환입",     AccountCategory.REVENUE,   NormalBalance.DEBIT)   # 차감 계정

# ── 원가·비용 ──────────────────────────────────────────────────────────────────
COGS                = Account("5000", "매출원가",             AccountCategory.EXPENSE,   NormalBalance.DEBIT)
BAD_DEBT_EXPENSE    = Account("5100", "대손상각비",           AccountCategory.EXPENSE,   NormalBalance.DEBIT)
COMMISSION_EXPENSE  = Account("5200", "수수료비용",           AccountCategory.EXPENSE,   NormalBalance.DEBIT)
LICENSE_EXPENSE     = Account("5300", "지급수수료(라이선스)", AccountCategory.EXPENSE,   NormalBalance.DEBIT)
FX_LOSS             = Account("5400", "외환차손",             AccountCategory.EXPENSE,   NormalBalance.DEBIT)
FX_TRANS_LOSS       = Account("5401", "외화환산손실",         AccountCategory.EXPENSE,   NormalBalance.DEBIT)

# ── 임시계정 ──────────────────────────────────────────────────────────────────
INCOME_SUMMARY      = Account("9000", "집합손익",             AccountCategory.EQUITY,    NormalBalance.CREDIT)
RETAINED_EARNINGS   = Account("3100", "이익잉여금",           AccountCategory.EQUITY,    NormalBalance.CREDIT)


# 코드로 빠르게 조회
ACCOUNT_BY_CODE: dict[str, Account] = {
    acc.code: acc
    for acc in [
        CASH, BANK, TRADE_AR, ALLOWANCE_DOUBTFUL, ADVANCE_PAID, VAT_DEDUCTIBLE,
        INVENTORY, CONSIGNMENT_GOODS, RETURN_ASSET, FX_AR,
        TRADE_AP, ADVANCE_RECEIVED, DEFERRED_REVENUE, VAT_PAYABLE,
        WITHHOLDING_PAYABLE, REFUND_LIABILITY, TAX_PAYABLE,
        PROVISION_WARRANTY, ACCRUED_EXPENSE,
        SALES, COMMISSION_REVENUE, INTEREST_INCOME, FX_GAIN, FX_TRANS_GAIN,
        BAD_DEBT_REVERSAL, SALES_RETURN,
        COGS, BAD_DEBT_EXPENSE, COMMISSION_EXPENSE, LICENSE_EXPENSE,
        FX_LOSS, FX_TRANS_LOSS,
        INCOME_SUMMARY, RETAINED_EARNINGS,
    ]
}
