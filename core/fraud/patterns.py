"""패턴 기반 이상 탐지 — 중복·라운드넘버·속도·비업무시간·한도직하."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from .models import FraudAlert, FraudFlag, RiskLevel, Transaction


# ── 1. 라운드 넘버 편향 ───────────────────────────────────────────────────────

def check_round_number(txns: list[Transaction], threshold: float = 0.40) -> FraudAlert | None:
    """금액이 1,000 단위 딱 떨어지는 거래 비율이 과다하면 경고."""
    if not txns:
        return None
    round_ids = [
        t.txn_id for t in txns
        if t.amount % 1000 == 0
    ]
    ratio = len(round_ids) / len(txns)
    if ratio < threshold:
        return None

    score = min(0.9, 0.3 + (ratio - threshold) * 2.0)
    risk = RiskLevel.HIGH if score >= 0.6 else RiskLevel.MEDIUM
    return FraudAlert(
        flag=FraudFlag.ROUND_NUMBER_BIAS,
        risk_level=risk,
        txn_ids=round_ids,
        score=round(score, 3),
        detail=f"1,000원 단위 딱 떨어지는 거래 비율 {ratio:.1%} (임계 {threshold:.0%}) — 수기 조작 의심",
        evidence={"round_count": len(round_ids), "total": len(txns), "ratio": round(ratio, 3)},
    )


# ── 2. 중복 거래 ─────────────────────────────────────────────────────────────

def check_duplicates(
    txns: list[Transaction],
    window_days: int = 3,
) -> list[FraudAlert]:
    """동일 금액 + 동일 거래처가 window_days 내 2회 이상 발생하면 경고."""
    alerts: list[FraudAlert] = []
    # (vendor, amount) → 거래 목록
    groups: dict[tuple, list[Transaction]] = defaultdict(list)
    for t in txns:
        key = (t.vendor_id, t.amount)
        groups[key].append(t)

    for (vendor, amount), group in groups.items():
        if len(group) < 2:
            continue
        # 날짜순 정렬 후 window 체크
        group.sort(key=lambda t: t.txn_datetime)
        flagged: list[str] = []
        for i in range(1, len(group)):
            delta = (group[i].txn_datetime - group[i - 1].txn_datetime).days
            if delta <= window_days:
                flagged.extend([group[i - 1].txn_id, group[i].txn_id])
        flagged = list(dict.fromkeys(flagged))  # deduplicate
        if not flagged:
            continue

        score = min(0.95, 0.5 + len(flagged) * 0.05)
        alerts.append(FraudAlert(
            flag=FraudFlag.DUPLICATE_TXN,
            risk_level=RiskLevel.HIGH,
            txn_ids=flagged,
            score=round(score, 3),
            detail=(
                f"거래처 {vendor or '미상'}, 금액 {int(amount):,}원 — "
                f"{window_days}일 내 {len(flagged)}건 중복 발생"
            ),
            evidence={"vendor": vendor, "amount": int(amount), "dup_count": len(flagged)},
        ))
    return alerts


# ── 3. 속도 이상 (단기 과다 발생) ────────────────────────────────────────────

def check_velocity(
    txns: list[Transaction],
    window_hours: int = 24,
    max_normal: int = 10,
) -> FraudAlert | None:
    """window_hours 내 동일 담당자 거래가 max_normal 초과 시 경고."""
    if not txns:
        return None
    # posted_by → 시간대별 카운트
    by_poster: dict[str, list[Transaction]] = defaultdict(list)
    for t in txns:
        by_poster[t.posted_by].append(t)

    worst_poster, worst_ids, worst_count = "", [], 0
    for poster, group in by_poster.items():
        group.sort(key=lambda t: t.txn_datetime)
        # 슬라이딩 윈도우
        for i, base in enumerate(group):
            window_end = base.txn_datetime + timedelta(hours=window_hours)
            window_txns = [t for t in group[i:] if t.txn_datetime <= window_end]
            if len(window_txns) > max_normal and len(window_txns) > worst_count:
                worst_count = len(window_txns)
                worst_poster = poster
                worst_ids = [t.txn_id for t in window_txns]

    if worst_count == 0:
        return None

    score = min(0.9, 0.4 + (worst_count - max_normal) / max_normal * 0.3)
    risk = RiskLevel.HIGH if score >= 0.65 else RiskLevel.MEDIUM
    return FraudAlert(
        flag=FraudFlag.VELOCITY_SPIKE,
        risk_level=risk,
        txn_ids=worst_ids,
        score=round(score, 3),
        detail=(
            f"담당자 '{worst_poster}' — {window_hours}시간 내 {worst_count}건 "
            f"(정상 임계 {max_normal}건) 초과 발생"
        ),
        evidence={"poster": worst_poster, "count": worst_count, "window_hours": window_hours},
    )


# ── 4. 비업무 시간대 ─────────────────────────────────────────────────────────

def check_off_hours(
    txns: list[Transaction],
    work_start: int = 8,
    work_end: int = 20,
) -> FraudAlert | None:
    """주말 또는 야간(work_start~work_end 밖) 거래 비율이 과다하면 경고."""
    if not txns:
        return None
    off_ids = []
    for t in txns:
        dt = t.txn_datetime
        is_weekend = dt.weekday() >= 5
        is_night   = dt.hour < work_start or dt.hour >= work_end
        if is_weekend or is_night:
            off_ids.append(t.txn_id)

    ratio = len(off_ids) / len(txns)
    if ratio < 0.20:
        return None

    score = min(0.75, 0.25 + ratio * 0.8)
    risk = RiskLevel.MEDIUM if score < 0.6 else RiskLevel.HIGH
    return FraudAlert(
        flag=FraudFlag.OFF_HOURS,
        risk_level=risk,
        txn_ids=off_ids,
        score=round(score, 3),
        detail=f"비업무 시간대({work_start}시 이전 / {work_end}시 이후 / 주말) 거래 비율 {ratio:.1%}",
        evidence={"off_count": len(off_ids), "total": len(txns), "ratio": round(ratio, 3)},
    )


# ── 5. 한도 직하 분할 (Just-below-threshold) ──────────────────────────────────

_DEFAULT_THRESHOLDS = [
    Decimal("1000000"),    # 100만
    Decimal("3000000"),    # 300만
    Decimal("5000000"),    # 500만
    Decimal("10000000"),   # 1000만
    Decimal("50000000"),   # 5000만
]

def check_just_below_threshold(
    txns: list[Transaction],
    thresholds: list[Decimal] | None = None,
    margin_pct: float = 0.05,   # 임계값의 5% 이내
) -> list[FraudAlert]:
    """결재 한도 직하(margin_pct 이내)에 군집된 거래를 탐지한다."""
    thresholds = thresholds or _DEFAULT_THRESHOLDS
    alerts: list[FraudAlert] = []
    for threshold in thresholds:
        lower = threshold * Decimal(str(1 - margin_pct))
        flagged = [
            t for t in txns
            if lower <= t.amount < threshold
        ]
        if len(flagged) < 2:
            continue
        score = min(0.9, 0.45 + len(flagged) * 0.04)
        alerts.append(FraudAlert(
            flag=FraudFlag.JUST_BELOW_THRESHOLD,
            risk_level=RiskLevel.HIGH,
            txn_ids=[t.txn_id for t in flagged],
            score=round(score, 3),
            detail=(
                f"결재 한도 {int(threshold):,}원 직하 {margin_pct:.0%} 구간 "
                f"({int(lower):,}~{int(threshold)-1:,}원)에 {len(flagged)}건 군집"
            ),
            evidence={
                "threshold": int(threshold),
                "cluster_count": len(flagged),
                "amounts": [int(t.amount) for t in flagged],
            },
        ))
    return alerts
