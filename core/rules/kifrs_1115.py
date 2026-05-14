"""K-IFRS 제1115호 5단계 수익인식 룰 엔진."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from .models import (
    Contract,
    ContractLineItem,
    ContractValidationResult,
    KIFRS1115Result,
    ItemType,
    PerformanceObligation,
    PerfObligationResult,
    RecognitionResult,
    RecognitionScheduleEntry,
    RecognitionTiming,
    SSPAllocationResult,
    TransactionPriceResult,
)


_POINT_IN_TIME_TYPES = {
    ItemType.HW,
    ItemType.SW_PERPETUAL,
}

_OVER_TIME_TYPES = {
    ItemType.SW_SUBSCRIPTION,
    ItemType.SAAS,
    ItemType.MAINTENANCE,
    ItemType.WARRANTY_SERVICE,
}

_NOT_OBLIGATION_TYPES = {
    ItemType.WARRANTY_ASSURANCE,
}


class KIFRS1115Engine:
    """K-IFRS 1115 5단계 수익인식 룰 엔진.

    Usage::
        engine = KIFRS1115Engine()
        result = engine.evaluate(contract)
    """

    # ──────────────────────────────────────────────────────────────────────────
    # 1단계 — 계약 식별
    # ──────────────────────────────────────────────────────────────────────────

    def step1_identify_contract(self, contract: Contract) -> ContractValidationResult:
        """5요건을 체크하여 유효 계약 여부를 판단한다."""
        failed: list[str] = []

        if not contract.approved_by_both_parties:
            failed.append("당사자 승인·확약 미충족")
        if not contract.rights_identifiable:
            failed.append("권리 식별 불가")
        if not contract.payment_terms_identifiable:
            failed.append("지급조건 식별 불가")
        if not contract.commercial_substance:
            failed.append("상업적 실질 없음")
        if not contract.collectability_probable:
            failed.append("회수 가능성 낮음")

        if not failed:
            return ContractValidationResult(
                is_valid_contract=True,
                disposition="proceed",
            )

        # 대가를 받았다면 선수금/환불부채로, 아니면 hold
        disposition = "advance_receipt" if contract.total_contract_price > 0 else "hold"
        return ContractValidationResult(
            is_valid_contract=False,
            failed_conditions=failed,
            disposition=disposition,
            notes=f"미충족 요건: {', '.join(failed)}",
        )

    # ──────────────────────────────────────────────────────────────────────────
    # 2단계 — 수행의무 식별
    # ──────────────────────────────────────────────────────────────────────────

    def step2_identify_obligations(
        self, contract: Contract
    ) -> PerfObligationResult:
        """각 라인의 구별 여부를 판단하여 수행의무 목록을 생성한다."""
        obligations: list[PerformanceObligation] = []
        non_obligation_lines: list[str] = []
        counter = 1

        for line in contract.lines:
            if line.item_type in _NOT_OBLIGATION_TYPES:
                # 확신유형 보증 → 수행의무 아님, K-IFRS 1037 충당부채
                non_obligation_lines.append(line.line_id)
                continue

            timing = self._timing_for(line)
            svc_months = line.service_months if timing == RecognitionTiming.OVER_TIME else None

            # INSTALLATION 특이 케이스: HW와 통합 산출물이면 HW PO에 병합
            # 여기선 별도 수행의무로 단순화(단순 설치 가정)
            po = PerformanceObligation(
                po_id=f"{contract.contract_id}-PO{counter:02d}",
                line_ids=[line.line_id],
                item_type=line.item_type,
                description=line.description,
                is_distinct=True,
                recognition_timing=timing,
                service_months=svc_months,
                revenue_basis=line.revenue_basis,
                ssp=line.ssp_total,
            )
            obligations.append(po)
            counter += 1

        return PerfObligationResult(
            obligations=obligations,
            non_obligation_lines=non_obligation_lines,
        )

    def _timing_for(self, line: ContractLineItem) -> RecognitionTiming:
        if line.item_type in _POINT_IN_TIME_TYPES:
            return RecognitionTiming.POINT_IN_TIME
        # INSTALLATION 진행률 처리 — 단순화: 완료 시점 처리
        if line.item_type == ItemType.INSTALLATION:
            return RecognitionTiming.POINT_IN_TIME
        return RecognitionTiming.OVER_TIME

    # ──────────────────────────────────────────────────────────────────────────
    # 3단계 — 거래가격 산정
    # ──────────────────────────────────────────────────────────────────────────

    def step3_determine_price(self, contract: Contract) -> TransactionPriceResult:
        """변동대가 제약을 적용하여 거래가격을 확정한다."""
        gross = contract.total_contract_price

        # 변동대가: 각 라인의 variable_consideration 합산
        vc_total = sum(
            line.variable_consideration * line.quantity
            for line in contract.lines
        )

        transaction_price = gross + vc_total  # vc_total이 음수면 차감

        # 유의적 금융요소: 간단히 외상 기간이 1년 초과 또는 선수가 1년 초과이면 표시
        has_financing = False  # 추후 계약 속성으로 판단 가능

        return TransactionPriceResult(
            gross_contract_price=gross,
            variable_consideration_included=vc_total,
            transaction_price=transaction_price,
            has_significant_financing=has_financing,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # 4단계 — 거래가격 배분
    # ──────────────────────────────────────────────────────────────────────────

    def step4_allocate_price(
        self,
        obligations: list[PerformanceObligation],
        transaction_price: Decimal,
    ) -> SSPAllocationResult:
        """SSP 비율로 거래가격을 수행의무에 배분한다."""
        total_ssp = sum(po.ssp for po in obligations)

        if total_ssp == 0:
            # SSP 정보 없으면 균등 배분 fallback
            per_po = (transaction_price / len(obligations)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
            allocations = {po.po_id: per_po for po in obligations}
        else:
            allocations: dict[str, Decimal] = {}
            allocated_so_far = Decimal("0")
            for i, po in enumerate(obligations):
                if i == len(obligations) - 1:
                    # 마지막 항목은 잔여로 처리 (반올림 오차 흡수)
                    allocations[po.po_id] = transaction_price - allocated_so_far
                else:
                    alloc = (transaction_price * po.ssp / total_ssp).quantize(
                        Decimal("1"), rounding=ROUND_HALF_UP
                    )
                    allocations[po.po_id] = alloc
                    allocated_so_far += alloc

        return SSPAllocationResult(
            total_ssp=total_ssp,
            transaction_price=transaction_price,
            allocations=allocations,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # 5단계 — 수익 인식
    # ──────────────────────────────────────────────────────────────────────────

    def step5_recognize_revenue(
        self,
        obligation: PerformanceObligation,
        allocated_price: Decimal,
        recognition_date: date | None = None,
    ) -> RecognitionResult:
        """수행의무별 인식 시점 및 스케줄을 결정한다."""
        if obligation.recognition_timing == RecognitionTiming.POINT_IN_TIME:
            return RecognitionResult(
                po_id=obligation.po_id,
                timing=RecognitionTiming.POINT_IN_TIME,
                allocated_price=allocated_price,
                recognition_date=recognition_date or date.today(),
            )

        # 기간 안분 스케줄 생성
        months = obligation.service_months or 12
        monthly = (allocated_price / months).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        start = recognition_date or date.today()
        schedule: list[RecognitionScheduleEntry] = []

        for i in range(months):
            # 월 계산 (연도 넘김 처리)
            total_months = start.month - 1 + i
            yr = start.year + total_months // 12
            mo = total_months % 12 + 1
            label = f"{yr}-{mo:02d}"

            # 마지막 달 반올림 오차 흡수
            if i == months - 1:
                amount = allocated_price - monthly * (months - 1)
            else:
                amount = monthly

            schedule.append(RecognitionScheduleEntry(period_label=label, amount=amount))

        return RecognitionResult(
            po_id=obligation.po_id,
            timing=RecognitionTiming.OVER_TIME,
            allocated_price=allocated_price,
            schedule=schedule,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Full pipeline
    # ──────────────────────────────────────────────────────────────────────────

    def evaluate(
        self,
        contract: Contract,
        recognition_date: date | None = None,
    ) -> KIFRS1115Result:
        """계약 전체를 5단계로 평가하여 KIFRS1115Result를 반환한다."""
        step1 = self.step1_identify_contract(contract)

        if not step1.is_valid_contract:
            return KIFRS1115Result(
                contract_id=contract.contract_id,
                step1=step1,
                journal_trigger="hold" if step1.disposition == "hold" else "advance_only",
            )

        step2 = self.step2_identify_obligations(contract)
        step3 = self.step3_determine_price(contract)
        step4 = self.step4_allocate_price(
            step2.obligations, step3.transaction_price
        )

        step5_results: list[RecognitionResult] = []
        for po in step2.obligations:
            allocated = step4.allocations.get(po.po_id, Decimal("0"))
            r = self.step5_recognize_revenue(po, allocated, recognition_date)
            step5_results.append(r)

        # LangGraph 분기 결정
        has_point = any(
            r.timing == RecognitionTiming.POINT_IN_TIME for r in step5_results
        )
        has_over = any(
            r.timing == RecognitionTiming.OVER_TIME for r in step5_results
        )
        if has_point and has_over:
            trigger = "mixed_sale"
        elif has_point:
            trigger = "point_sale"
        elif has_over:
            trigger = "deferred_sale"
        else:
            trigger = "hold"

        return KIFRS1115Result(
            contract_id=contract.contract_id,
            step1=step1,
            step2=step2,
            step3=step3,
            step4=step4,
            step5=step5_results,
            journal_trigger=trigger,
        )
