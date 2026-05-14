"""벤포드 법칙(Benford's Law) 분석 — 첫째 자리 분포 이탈 탐지."""

from __future__ import annotations

import math
from collections import Counter
from decimal import Decimal

from .models import FraudAlert, FraudFlag, RiskLevel

# 벤포드 기댓값: digit 1~9 → 확률
BENFORD_EXPECTED: dict[int, float] = {
    d: math.log10(1 + 1 / d) for d in range(1, 10)
}


def _first_digit(amount: Decimal) -> int | None:
    """금액의 첫째 유효 숫자(1~9)를 반환한다."""
    s = str(amount).replace(".", "").lstrip("0")
    if not s:
        return None
    return int(s[0])


def benford_chi_square(amounts: list[Decimal]) -> tuple[float, dict]:
    """카이제곱 통계량과 관측/기댓값 딕셔너리를 반환한다.

    Returns:
        (chi2_stat, evidence_dict)
        chi2_stat: 낮을수록 정상, 임계값 15.51 (df=8, p=0.05)
    """
    digits = [_first_digit(a) for a in amounts]
    digits = [d for d in digits if d is not None]
    n = len(digits)
    if n < 10:
        return 0.0, {"note": "샘플 부족 (최소 10건)"}

    observed = Counter(digits)
    chi2 = 0.0
    detail: dict[str, dict] = {}
    for d in range(1, 10):
        obs = observed.get(d, 0)
        exp = BENFORD_EXPECTED[d] * n
        chi2 += (obs - exp) ** 2 / exp
        detail[str(d)] = {
            "observed": obs,
            "expected": round(exp, 1),
            "obs_pct": round(obs / n * 100, 1),
            "exp_pct": round(BENFORD_EXPECTED[d] * 100, 1),
        }

    return chi2, {"n": n, "chi2": round(chi2, 2), "digits": detail}


def check_benford(txns_with_amounts: list[tuple[str, Decimal]]) -> FraudAlert | None:
    """벤포드 이탈 여부를 검사한다.

    Args:
        txns_with_amounts: [(txn_id, amount), ...]
    """
    if not txns_with_amounts:
        return None

    amounts = [a for _, a in txns_with_amounts]
    chi2, evidence = benford_chi_square(amounts)

    if "note" in evidence:
        return None

    # df=8 카이제곱 임계값: p=0.05 → 15.51,  p=0.01 → 20.09
    if chi2 < 10.0:
        return None   # 정상 범위

    if chi2 >= 20.09:
        risk = RiskLevel.HIGH
        score = min(0.95, 0.6 + (chi2 - 20.09) / 50)
    elif chi2 >= 15.51:
        risk = RiskLevel.MEDIUM
        score = 0.4 + (chi2 - 15.51) / (20.09 - 15.51) * 0.2
    else:
        risk = RiskLevel.LOW
        score = 0.2 + (chi2 - 10.0) / (15.51 - 10.0) * 0.2

    return FraudAlert(
        flag=FraudFlag.BENFORD_DEVIATION,
        risk_level=risk,
        txn_ids=[tid for tid, _ in txns_with_amounts],
        score=round(score, 3),
        detail=(
            f"벤포드 카이제곱 통계량 {chi2:.2f} "
            f"(임계값 15.51/p=0.05, 20.09/p=0.01) — 금액 첫째 자리 분포 이탈"
        ),
        evidence=evidence,
    )
