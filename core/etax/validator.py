"""전자세금계산서 검증 룰 — 국세청 KEC v3.0 필수 체크."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .models import TaxInvoice, TaxInvoiceTypeCode


_BRN_WEIGHTS = [1, 3, 7, 1, 3, 7, 1, 3, 5]


def validate_brn(brn: str) -> bool:
    """사업자등록번호 10자리 체크섬 검증."""
    digits = brn.replace("-", "").replace(" ", "")
    if len(digits) != 10 or not digits.isdigit():
        return False
    nums = [int(c) for c in digits]
    total = sum(w * d for w, d in zip(_BRN_WEIGHTS, nums[:9]))
    total += (nums[8] * 5) // 10   # 9번째 자리(인덱스 8)에 5를 곱한 십의 자리
    check = (10 - (total % 10)) % 10
    return check == nums[9]


def validate_invoice(invoice: TaxInvoice) -> list[str]:
    """검증 오류 목록 반환 (빈 리스트 = 통과)."""
    errors: list[str] = []

    # 1. 사업자등록번호 체크섬
    if not validate_brn(invoice.invoicer.brn):
        errors.append(f"공급자 사업자등록번호 오류: {invoice.invoicer.brn}")
    if not validate_brn(invoice.invoicee.brn):
        # 외국법인 대체번호(9999999999)는 허용
        if invoice.invoicee.brn != "9999999999":
            errors.append(f"공급받는자 사업자등록번호 오류: {invoice.invoicee.brn}")

    # 2. 승인번호 24자리
    if invoice.issue_id and len(invoice.issue_id) != 24:
        errors.append(f"승인번호는 24자리여야 합니다 (현재 {len(invoice.issue_id)}자리)")

    # 3. 품목 없음
    if not invoice.lines:
        errors.append("품목 라인이 1개 이상 필요합니다")

    # 4. 합계 일치
    calc_supply = sum(l.supply_amount for l in invoice.lines)
    calc_tax: Decimal
    if invoice.type_code in (
        TaxInvoiceTypeCode.ZERO_RATE,
        TaxInvoiceTypeCode.EXEMPT,
        TaxInvoiceTypeCode.EXEMPT_ZERO,
    ):
        calc_tax = Decimal("0")
    else:
        calc_tax = sum(
            (l.supply_amount * Decimal("0.1")).quantize(Decimal("1"))
            for l in invoice.lines
        )
    calc_grand = calc_supply + calc_tax

    if invoice.total_supply != calc_supply:
        errors.append(
            f"공급가액 합계 불일치: 헤더={invoice.total_supply:,} / 라인합={calc_supply:,}"
        )
    if invoice.total_tax != calc_tax:
        errors.append(
            f"세액 합계 불일치: 헤더={invoice.total_tax:,} / 라인합={calc_tax:,}"
        )
    if invoice.grand_total != calc_grand:
        errors.append(
            f"총합계 불일치: 헤더={invoice.grand_total:,} / 산출={calc_grand:,}"
        )

    # 5. 발급일시 미래 여부
    if invoice.issue_datetime > datetime.now():
        errors.append("발급일시가 현재 시각보다 미래입니다")

    # 6. 수정세금계산서 원본 번호
    if invoice.is_amendment and not invoice.original_issue_id:
        errors.append("수정세금계산서에는 원본 승인번호(original_issue_id)가 필요합니다")

    # 7. 영세율 세액 = 0 강제
    if invoice.type_code == TaxInvoiceTypeCode.ZERO_RATE and invoice.total_tax != 0:
        errors.append("영세율 세금계산서의 세액은 0이어야 합니다")

    # 8. 품목 순번 중복
    seqs = [l.seq for l in invoice.lines]
    if len(seqs) != len(set(seqs)):
        errors.append("품목 일련번호(seq)에 중복이 있습니다")

    return errors
