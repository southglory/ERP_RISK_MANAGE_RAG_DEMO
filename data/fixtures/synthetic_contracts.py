"""Phase 3-1-5 — 합성 계약 100건.

5 가지 contract_type × 20 변형:
  - sw_license_perpetual   : 영구 라이선스 (point-in-time / 본인)
  - saas_subscription      : SaaS 구독 (over-time / 본인)
  - hw_sale                : 하드웨어 판매 (point-in-time / 본인)
  - reseller_principal     : 재판매 본인 (gross revenue, 3지표 충족)
  - reseller_agent         : 재판매 대리인 (net revenue, 3지표 미충족)

각 계약 텍스트에 K-IFRS 1115 B37 3지표 명시:
  (1) 재고위험 (2) 가격결정 (3) 키 풀 / 자산 보유.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class SyntheticContract:
    contract_id: str
    contract_type: str         # sw_license_perpetual | saas_subscription | hw_sale | reseller_principal | reseller_agent
    revenue_basis: str         # gross | net
    recognition: str           # point_in_time | over_time
    text: str
    party_a: str               # 공급자
    party_b: str               # 고객
    amount: int                # 거래 가격 (원)
    contract_date: str         # ISO date


_VENDORS = ["Global Tech Solution", "Audit-AI Korea", "ABC 소프트웨어", "한국 IT 시스템", "디지털테크"]
_CUSTOMERS = ["삼성전자", "LG CNS", "현대오토에버", "포스코 ICT", "SK C&C", "네이버 클라우드"]
_PRODUCTS_HW = ["서버 (Dell PowerEdge R750)", "스토리지 어레이", "네트워크 스위치", "방화벽 어플라이언스"]
_PRODUCTS_SW = ["통합 ERP 솔루션", "데이터 분석 플랫폼", "CRM 시스템", "보안 관제 솔루션"]
_PRODUCTS_SAAS = ["워크플로우 자동화 SaaS", "협업 도구", "BI 대시보드", "AI 챗봇 플랫폼"]


def _hw_sale(rng: random.Random, idx: int, ts: datetime) -> SyntheticContract:
    a = rng.choice(_VENDORS)
    b = rng.choice(_CUSTOMERS)
    p = rng.choice(_PRODUCTS_HW)
    amount = rng.choice([50_000_000, 80_000_000, 120_000_000, 200_000_000])
    txt = (
        f"하드웨어 매매 계약서\n\n"
        f"공급자 ({a}) 는 고객 ({b}) 에게 {p} 를 {amount:,}원에 매도한다. "
        f"인도 시점에 고객이 자산의 통제권을 획득하며, K-IFRS 1115 제38조(a) 에 따라 인도일에 매출을 인식한다. "
        f"한 시점 (point-in-time) 인식. "
        f"공급자는 자산 인도 전까지 재고위험을 부담한다. 가격은 공급자가 결정한다. "
        f"수익 인식 기준: gross (총액)."
    )
    return SyntheticContract(
        contract_id=f"C{idx:04d}", contract_type="hw_sale",
        revenue_basis="gross", recognition="point_in_time",
        text=txt, party_a=a, party_b=b, amount=amount, contract_date=ts.date().isoformat(),
    )


def _sw_license(rng: random.Random, idx: int, ts: datetime) -> SyntheticContract:
    a = rng.choice(_VENDORS); b = rng.choice(_CUSTOMERS); p = rng.choice(_PRODUCTS_SW)
    amount = rng.choice([30_000_000, 60_000_000, 100_000_000])
    txt = (
        f"소프트웨어 영구 라이선스 계약서\n\n"
        f"공급자 ({a}) 는 고객 ({b}) 에게 {p} 의 영구 라이선스 키를 {amount:,}원에 부여한다. "
        f"K-IFRS 1115 제38조 에 따라 라이선스 키 전달 시점에 고객이 통제권을 획득하며, 그 시점에 매출 전액을 인식한다. "
        f"한 시점 (point-in-time) 인식. "
        f"공급자는 라이선스 키 풀 (활성/비활성) 을 보유하며, 가격은 공급자가 결정한다. "
        f"수익 인식 기준: gross (총액)."
    )
    return SyntheticContract(
        contract_id=f"C{idx:04d}", contract_type="sw_license_perpetual",
        revenue_basis="gross", recognition="point_in_time",
        text=txt, party_a=a, party_b=b, amount=amount, contract_date=ts.date().isoformat(),
    )


def _saas(rng: random.Random, idx: int, ts: datetime) -> SyntheticContract:
    a = rng.choice(_VENDORS); b = rng.choice(_CUSTOMERS); p = rng.choice(_PRODUCTS_SAAS)
    annual = rng.choice([12_000_000, 24_000_000, 36_000_000])
    monthly = annual // 12
    txt = (
        f"SaaS 구독 서비스 계약서\n\n"
        f"공급자 ({a}) 는 고객 ({b}) 에게 {p} 의 클라우드 접근권을 12 개월간 제공한다. "
        f"연간 사용료 {annual:,}원, 월 {monthly:,}원으로 안분 인식. "
        f"K-IFRS 1115 제35조 에 따라 고객이 계약 기간 동안 *지속적으로* 접근권을 받는 '기간에 걸쳐 이행되는 수행의무' 이므로 "
        f"over-time 정액 인식한다. "
        f"공급자는 인프라를 보유하고 가격을 결정한다. "
        f"수익 인식 기준: gross (총액)."
    )
    return SyntheticContract(
        contract_id=f"C{idx:04d}", contract_type="saas_subscription",
        revenue_basis="gross", recognition="over_time",
        text=txt, party_a=a, party_b=b, amount=annual, contract_date=ts.date().isoformat(),
    )


def _reseller_principal(rng: random.Random, idx: int, ts: datetime) -> SyntheticContract:
    a = rng.choice(_VENDORS); b = rng.choice(_CUSTOMERS); p = rng.choice(_PRODUCTS_SW)
    amount = rng.choice([40_000_000, 70_000_000, 100_000_000])
    txt = (
        f"소프트웨어 재판매 계약서 (본인 — gross)\n\n"
        f"재판매자 ({a}) 는 원제조사로부터 {p} 의 라이선스를 사전 매입하여 자체 재고로 보유한다. "
        f"고객 ({b}) 에게 {amount:,}원에 재판매한다. "
        f"K-IFRS 1115 B37 의 3 지표 모두 충족: "
        f"(1) 재판매자가 매입 시점부터 재고위험을 부담, "
        f"(2) 재판매자가 가격을 자체 결정, "
        f"(3) 재판매자가 라이선스 키 풀을 보유. "
        f"따라서 본인 (principal) 으로서 총액 (gross) 매출 인식. K-IFRS 1115 B36 적용. 한 시점 인식."
    )
    return SyntheticContract(
        contract_id=f"C{idx:04d}", contract_type="reseller_principal",
        revenue_basis="gross", recognition="point_in_time",
        text=txt, party_a=a, party_b=b, amount=amount, contract_date=ts.date().isoformat(),
    )


def _reseller_agent(rng: random.Random, idx: int, ts: datetime) -> SyntheticContract:
    a = rng.choice(_VENDORS); b = rng.choice(_CUSTOMERS); p = rng.choice(_PRODUCTS_SW)
    amount = rng.choice([40_000_000, 70_000_000, 100_000_000])
    commission_rate = rng.choice([10, 12, 15])
    commission = amount * commission_rate // 100
    txt = (
        f"소프트웨어 중개 판매 계약서 (대리인 — net)\n\n"
        f"중개자 ({a}) 는 고객 ({b}) 의 주문을 원제조사에 전달하며 {p} 거래의 가교 역할만 한다. "
        f"총 거래액 {amount:,}원 중 중개 수수료 {commission_rate}% ({commission:,}원) 만 수익으로 인식. "
        f"K-IFRS 1115 B37 의 3 지표 모두 미충족: "
        f"(1) 재고 위험 부담 안 함 (원제조사가 부담), "
        f"(2) 가격을 원제조사가 결정, "
        f"(3) 라이선스 키를 원제조사가 보유 및 직접 전달. "
        f"따라서 대리인 (agent) 으로서 순액 (net) 매출 인식 — 수수료 {commission:,}원만. K-IFRS 1115 B36 의 대립 사례."
    )
    return SyntheticContract(
        contract_id=f"C{idx:04d}", contract_type="reseller_agent",
        revenue_basis="net", recognition="point_in_time",
        text=txt, party_a=a, party_b=b, amount=commission, contract_date=ts.date().isoformat(),
    )


GENERATORS = [_hw_sale, _sw_license, _saas, _reseller_principal, _reseller_agent]


def generate(n: int = 100, seed: int = 42) -> list[SyntheticContract]:
    rng = random.Random(seed)
    start = datetime(2026, 1, 1)
    out: list[SyntheticContract] = []
    for i in range(n):
        gen = GENERATORS[i % len(GENERATORS)]
        ts = start + timedelta(days=rng.randint(0, 120))
        out.append(gen(rng, i + 1, ts))
    return out
