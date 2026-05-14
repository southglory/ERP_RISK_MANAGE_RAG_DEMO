"""Phase 6D — 대규모 합성 거래 생성기.

생성 규칙 + pattern 라벨:
- normal             70% — lognormal 금액, 평일 근무시간
- round_number        5% — 1·2·3·5 백만 딱 (Benford 위반, fraud 정답 positive)
- limit_just_under    5% — 950k~999k (한도 직하, fraud 정답 positive)
- nonbusiness_hour    5% — 새벽 00~06 시 (fraud 정답 positive)
- overseas            5% — V-AmazonKR (tax_flag 정답이지 fraud 아님)
- unregistered        5% — V-Unknown   (tax_flag 정답이지 fraud 아님)
- duplicate           5% — 직전 거래 복제 (fraud 정답 positive)

FRAUD_POSITIVE_PATTERNS = round_number / limit_just_under / nonbusiness_hour / duplicate.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import Decimal

VENDORS_DOMESTIC = ["V-Samsung", "V-LG", "V-KT", "V-Naver", "V-Kakao", "V-Office", "V-Misc"]
VENDORS_OVERSEAS = ["V-AmazonKR"]
VENDORS_UNREG    = ["V-Unknown"]
ACCOUNTS = ["5110", "5120", "5210", "5310", "5410", "5510", "5610", "5810", "5910"]
USERS = ["kim.jisu", "park.minhee", "lee.hyunwoo", "choi.dayeon", "jung.woojin"]

FRAUD_POSITIVE_PATTERNS = {"round_number", "limit_just_under", "nonbusiness_hour", "duplicate"}


def generate(n: int, seed: int = 42, start: datetime | None = None) -> list[dict]:
    rng = random.Random(seed)
    start = start or datetime(2026, 4, 1, 9, 0)
    txns: list[dict] = []
    for i in range(n):
        kind = rng.random()
        ts = start + timedelta(days=rng.randint(0, 29), minutes=rng.randint(0, 540))
        amt: Decimal
        pattern: str
        if kind < 0.70:
            amt = Decimal(str(round(rng.lognormvariate(13, 1.5) / 100) * 100))
            vendor = rng.choice(VENDORS_DOMESTIC)
            pattern = "normal"
        elif kind < 0.75:
            amt = Decimal(rng.choice([1_000_000, 2_000_000, 3_000_000, 5_000_000]))
            vendor = rng.choice(VENDORS_DOMESTIC)
            pattern = "round_number"
        elif kind < 0.80:
            amt = Decimal(rng.randint(950_000, 999_999))
            vendor = rng.choice(VENDORS_DOMESTIC)
            pattern = "limit_just_under"
        elif kind < 0.85:
            ts = ts.replace(hour=rng.randint(0, 5), minute=rng.randint(0, 59))
            amt = Decimal(str(round(rng.lognormvariate(13, 1.5) / 100) * 100))
            vendor = rng.choice(VENDORS_DOMESTIC)
            pattern = "nonbusiness_hour"
        elif kind < 0.90:
            amt = Decimal(str(round(rng.lognormvariate(13, 1.5) / 100) * 100))
            vendor = rng.choice(VENDORS_OVERSEAS)
            pattern = "overseas"
        elif kind < 0.95:
            amt = Decimal(str(round(rng.lognormvariate(13, 1.5) / 100) * 100))
            vendor = rng.choice(VENDORS_UNREG)
            pattern = "unregistered"
        else:
            if txns:
                prev = txns[-1]
                txns.append({
                    **prev,
                    "txn_id": f"S{i+1:04d}",
                    "txn_datetime": (datetime.fromisoformat(prev["txn_datetime"]) + timedelta(days=2)).isoformat(),
                    "pattern": "duplicate",
                })
                continue
            amt = Decimal("3000000")
            vendor = rng.choice(VENDORS_DOMESTIC)
            pattern = "round_number"   # 첫 거래라 복제 불가, round_number 로 fallback
        txns.append({
            "txn_id": f"S{i+1:04d}",
            "txn_datetime": ts.isoformat(),
            "amount": str(max(Decimal("1000"), amt)),
            "vendor_id": vendor,
            "account_code": rng.choice(ACCOUNTS),
            "posted_by": rng.choice(USERS),
            "description": f"합성 거래 {i+1}",
            "approver": "",
            "pattern": pattern,
        })
    return txns
