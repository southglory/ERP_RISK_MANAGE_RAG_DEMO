"""ERP 샘플 거래 픽스처 — Phase 6A 리스크 탐지 테스트용.

의도적으로 여러 부정 패턴을 심어놓은 데이터셋:
- 중복 거래 (T003/T004: 동일 금액·벤더 3일 이내)
- 한도 직하 분할 (T007/T008: 100만 원 직하)
- 비업무 시간대 (T010: 새벽 2시)
- 라운드 넘버 편향 (T011~T015: 모두 1,000원 단위 딱)
"""

from datetime import datetime
from decimal import Decimal

from core.fraud.models import Transaction

SAMPLE_TRANSACTIONS: list[Transaction] = [
    # ── 정상 거래 ────────────────────────────────────────────────────────────
    Transaction(
        txn_id="T001",
        txn_datetime=datetime(2026, 4, 3, 10, 15),
        amount=Decimal("1234500"),
        vendor_id="V-Samsung",
        account_code="5110",
        posted_by="kim.jisu",
        description="서버 유지보수비",
    ),
    Transaction(
        txn_id="T002",
        txn_datetime=datetime(2026, 4, 5, 14, 30),
        amount=Decimal("875000"),
        vendor_id="V-LG",
        account_code="5120",
        posted_by="park.minhee",
        description="소모품 구입",
    ),
    # ── 중복 거래 (T003, T004) ────────────────────────────────────────────────
    Transaction(
        txn_id="T003",
        txn_datetime=datetime(2026, 4, 8, 9, 0),
        amount=Decimal("3200000"),
        vendor_id="V-TechPro",
        account_code="5210",
        posted_by="lee.hyunwoo",
        description="IT 컨설팅 1차",
    ),
    Transaction(
        txn_id="T004",
        txn_datetime=datetime(2026, 4, 10, 11, 0),   # 2일 후 동일 벤더·금액
        amount=Decimal("3200000"),
        vendor_id="V-TechPro",
        account_code="5210",
        posted_by="lee.hyunwoo",
        description="IT 컨설팅 1차 (재발행)",
    ),
    # ── 정상 ─────────────────────────────────────────────────────────────────
    Transaction(
        txn_id="T005",
        txn_datetime=datetime(2026, 4, 12, 16, 0),
        amount=Decimal("567800"),
        vendor_id="V-Naver",
        account_code="5310",
        posted_by="choi.dayeon",
        description="광고비",
    ),
    Transaction(
        txn_id="T006",
        txn_datetime=datetime(2026, 4, 15, 13, 45),
        amount=Decimal("2100000"),
        vendor_id="V-KT",
        account_code="5410",
        posted_by="jung.woojin",
        description="통신비 4월",
    ),
    # ── 한도 직하 분할 (T007, T008) ───────────────────────────────────────────
    Transaction(
        txn_id="T007",
        txn_datetime=datetime(2026, 4, 17, 10, 0),
        amount=Decimal("980000"),   # 100만 원 결재 한도 직하
        vendor_id="V-Office",
        account_code="5510",
        posted_by="kim.jisu",
        description="사무용품 구입 A",
    ),
    Transaction(
        txn_id="T008",
        txn_datetime=datetime(2026, 4, 17, 15, 0),   # 같은 날 동일 담당자
        amount=Decimal("960000"),   # 역시 100만 원 직하
        vendor_id="V-Office",
        account_code="5510",
        posted_by="kim.jisu",
        description="사무용품 구입 B",
    ),
    # ── 정상 ─────────────────────────────────────────────────────────────────
    Transaction(
        txn_id="T009",
        txn_datetime=datetime(2026, 4, 20, 9, 30),
        amount=Decimal("4850000"),
        vendor_id="V-AmazonKR",
        account_code="5610",
        posted_by="park.minhee",
        description="클라우드 사용료",
    ),
    # ── 비업무 시간대 (T010) ───────────────────────────────────────────────────
    Transaction(
        txn_id="T010",
        txn_datetime=datetime(2026, 4, 21, 2, 13),   # 새벽 2시
        amount=Decimal("1500000"),
        vendor_id="V-Unknown",
        account_code="5810",
        posted_by="admin",
        description="긴급 처리",
    ),
    # ── 라운드 넘버 편향 (T011~T015) ──────────────────────────────────────────
    Transaction(
        txn_id="T011",
        txn_datetime=datetime(2026, 4, 22, 10, 0),
        amount=Decimal("1000000"),
        vendor_id="V-Misc",
        account_code="5910",
        posted_by="lee.hyunwoo",
        description="기타 비용 1",
    ),
    Transaction(
        txn_id="T012",
        txn_datetime=datetime(2026, 4, 22, 11, 0),
        amount=Decimal("2000000"),
        vendor_id="V-Misc",
        account_code="5910",
        posted_by="lee.hyunwoo",
        description="기타 비용 2",
    ),
    Transaction(
        txn_id="T013",
        txn_datetime=datetime(2026, 4, 22, 14, 0),
        amount=Decimal("3000000"),
        vendor_id="V-Misc",
        account_code="5910",
        posted_by="lee.hyunwoo",
        description="기타 비용 3",
    ),
    Transaction(
        txn_id="T014",
        txn_datetime=datetime(2026, 4, 23, 9, 0),
        amount=Decimal("5000000"),
        vendor_id="V-Misc",
        account_code="5910",
        posted_by="lee.hyunwoo",
        description="기타 비용 4",
    ),
    Transaction(
        txn_id="T015",
        txn_datetime=datetime(2026, 4, 23, 10, 0),
        amount=Decimal("10000000"),
        vendor_id="V-Misc",
        account_code="5910",
        posted_by="lee.hyunwoo",
        description="기타 비용 5",
    ),
    # ── 정상 ─────────────────────────────────────────────────────────────────
    Transaction(
        txn_id="T016",
        txn_datetime=datetime(2026, 4, 25, 15, 0),
        amount=Decimal("687300"),
        vendor_id="V-Kakao",
        account_code="5310",
        posted_by="choi.dayeon",
        description="광고비 추가",
    ),
    Transaction(
        txn_id="T017",
        txn_datetime=datetime(2026, 4, 28, 11, 0),
        amount=Decimal("9450000"),
        vendor_id="V-Samsung",
        account_code="5110",
        posted_by="park.minhee",
        description="서버 유지보수비 4월",
    ),
    Transaction(
        txn_id="T018",
        txn_datetime=datetime(2026, 4, 30, 16, 30),
        amount=Decimal("1320000"),
        vendor_id="V-LG",
        account_code="5120",
        posted_by="jung.woojin",
        description="소모품 4월 말",
    ),
]
