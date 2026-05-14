"""재무 부정탐지 통합 엔진."""

from __future__ import annotations


from .benford import check_benford
from .models import FraudAlert, FraudReport, RiskLevel, Transaction
from .patterns import (
    check_duplicates,
    check_just_below_threshold,
    check_off_hours,
    check_round_number,
    check_velocity,
)

_RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}


class FraudDetectionEngine:
    """모든 탐지 룰을 순차 실행하고 FraudReport를 반환한다."""

    def analyze(self, txns: list[Transaction]) -> FraudReport:
        if not txns:
            return FraudReport(total_txns=0, summary="거래 없음")

        alerts: list[FraudAlert] = []

        # 1. 벤포드 법칙
        benford_result = check_benford([(t.txn_id, t.amount) for t in txns])
        if benford_result:
            alerts.append(benford_result)

        # 2. 라운드 넘버
        rn = check_round_number(txns)
        if rn:
            alerts.append(rn)

        # 3. 중복 거래
        alerts.extend(check_duplicates(txns))

        # 4. 속도 이상
        vel = check_velocity(txns)
        if vel:
            alerts.append(vel)

        # 5. 비업무 시간대
        off = check_off_hours(txns)
        if off:
            alerts.append(off)

        # 6. 한도 직하 분할
        alerts.extend(check_just_below_threshold(txns))

        # 위험도 내림차순 정렬
        alerts.sort(key=lambda a: (-a.score, _RISK_ORDER.get(a.risk_level, 0)))

        report = FraudReport(total_txns=len(txns), alerts=alerts)
        report.compute_overall_risk()
        report.summary = self._make_summary(txns, alerts, report.overall_risk)
        return report

    def _make_summary(
        self,
        txns: list[Transaction],
        alerts: list[FraudAlert],
        overall: RiskLevel,
    ) -> str:
        total_amount = sum(t.amount for t in txns)
        if not alerts:
            return f"분석 완료: {len(txns)}건 / {int(total_amount):,}원 — 이상 없음"

        high_or_above = [a for a in alerts if _RISK_ORDER[a.risk_level] >= 2]
        flagged_ids = set(tid for a in alerts for tid in a.txn_ids)
        lines = [
            f"분석: {len(txns)}건 / {int(total_amount):,}원",
            f"위험: {overall.value.upper()} | 경보 {len(alerts)}건 "
            f"(고위험 {len(high_or_above)}건)",
            f"의심 거래: {len(flagged_ids)}건",
        ]
        for a in alerts[:3]:   # 상위 3개만 표시
            lines.append(f"  • [{a.risk_level.value}] {a.detail[:60]}…")
        return "\n".join(lines)
