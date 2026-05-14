"""Phase 2 룰엔진 품질 검증 — K-IFRS 1115 · 분개 · VAT · 원천세 · 전자세금계산서 · 부정탐지.

실행:
    python scripts/test_rule_engine.py
"""
from __future__ import annotations

import random
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

_ROOT = __import__("pathlib").Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ── 공통 결과 집계 ─────────────────────────────────────────────────────────────

@dataclass
class SuiteResult:
    name: str
    passed: int = 0
    total: int = 0
    failures: list[str] = field(default_factory=list)

    def record(self, ok: bool, label: str) -> None:
        self.total += 1
        if ok:
            self.passed += 1
        else:
            self.failures.append(label)

    @property
    def pct(self) -> float:
        return self.passed / self.total * 100 if self.total else 0.0

    def print_summary(self) -> None:
        icon = "✅" if self.pct >= 95 else "🟡" if self.pct >= 80 else "❌"
        print(f"\n{icon}  {self.name}: {self.passed}/{self.total}  ({self.pct:.0f}%)")
        for f in self.failures[:5]:
            print(f"    ✗ {f}")
        if len(self.failures) > 5:
            print(f"    … 외 {len(self.failures) - 5}건")


# ══════════════════════════════════════════════════════════════════════════════
# 2-1  K-IFRS 1115  (100건)
# ══════════════════════════════════════════════════════════════════════════════

def test_kifrs_1115() -> SuiteResult:
    from core.rules.models import (
        Contract, ContractLineItem, ItemType, RecognitionBasis, RecognitionTiming,
    )
    from core.rules.kifrs_1115 import KIFRS1115Engine

    suite = SuiteResult("K-IFRS 1115")
    engine = KIFRS1115Engine()
    rng = random.Random(42)

    # ── 케이스 빌더 헬퍼 ───────────────────────────────────────────────────────

    def _line(
        item_type: ItemType,
        price: int = 10_000_000,
        ssp: int | None = None,
        months: int | None = None,
        basis: RecognitionBasis = RecognitionBasis.GROSS,
    ) -> ContractLineItem:
        return ContractLineItem(
            line_id=f"L{rng.randint(1, 99):02d}",
            item_type=item_type,
            description=item_type.value,
            list_price=Decimal(price),
            ssp=Decimal(ssp if ssp is not None else price),
            service_months=months,
            revenue_basis=basis,
        )

    def _contract(
        lines: list[ContractLineItem],
        *,
        approved_by_both_parties: bool = True,
        rights_identifiable: bool = True,
        payment_terms_identifiable: bool = True,
        commercial_substance: bool = True,
        collectability_probable: bool = True,
    ) -> Contract:
        return Contract(
            contract_id=f"CTR-{rng.randint(1000,9999)}",
            customer_id="CUST-001",
            contract_date=date(2025, 1, 1),
            lines=lines,
            approved_by_both_parties=approved_by_both_parties,
            rights_identifiable=rights_identifiable,
            payment_terms_identifiable=payment_terms_identifiable,
            commercial_substance=commercial_substance,
            collectability_probable=collectability_probable,
        )

    # ── 1. 1단계 — 유효 계약 (5요건 모두 충족) ────────────────────────────────
    for _ in range(20):
        c = _contract([_line(ItemType.HW)])
        r = engine.step1_identify_contract(c)
        suite.record(r.is_valid_contract and r.disposition == "proceed",
                     f"valid_contract {c.contract_id}")

    # ── 2. 1단계 — 각 요건 미충족 시 → 무효 ─────────────────────────────────
    for fail_key, fail_kwargs in [
        ("approved",   dict(approved_by_both_parties=False)),
        ("rights",     dict(rights_identifiable=False)),
        ("payment",    dict(payment_terms_identifiable=False)),
        ("commercial", dict(commercial_substance=False)),
        ("collect",    dict(collectability_probable=False)),
    ]:
        c = _contract([_line(ItemType.HW)], **fail_kwargs)
        r = engine.step1_identify_contract(c)
        suite.record(not r.is_valid_contract, f"invalid_condition_{fail_key}")

    # ── 3. 2단계 — 확신유형 보증 → 수행의무 아님 ─────────────────────────────
    for _ in range(5):
        c = _contract([_line(ItemType.HW), _line(ItemType.WARRANTY_ASSURANCE)])
        r2 = engine.step2_identify_obligations(c)
        suite.record(
            len(r2.obligations) == 1 and len(r2.non_obligation_lines) == 1,
            "warranty_assurance_not_obligation",
        )

    # ── 4. 5단계 — HW → 한 시점 인식 ─────────────────────────────────────────
    for _ in range(10):
        c = _contract([_line(ItemType.HW, 5_000_000)])
        full = engine.evaluate(c, recognition_date=date(2025, 3, 1))
        suite.record(
            full.journal_trigger in ("point_sale", "mixed_sale")
            and full.step5[0].timing == RecognitionTiming.POINT_IN_TIME,
            "hw_point_in_time",
        )

    # ── 5. 5단계 — SaaS 12개월 → 기간 안분, 합계 = 거래가격 ─────────────────
    for i in range(10):
        price = rng.randint(5, 50) * 1_000_000
        c = _contract([_line(ItemType.SAAS, price, months=12)])
        full = engine.evaluate(c, recognition_date=date(2025, 1, 1))
        r5 = full.step5[0]
        total_recognized = sum(e.amount for e in r5.schedule)
        suite.record(
            full.journal_trigger == "deferred_sale"
            and r5.timing == RecognitionTiming.OVER_TIME
            and total_recognized == Decimal(price),
            f"saas_over_time_total i={i}",
        )

    # ── 6. 5단계 — HW+SaaS 묶음 → mixed_sale + SSP 배분 합계 = 거래가격 ──────
    for i in range(10):
        hw_ssp  = rng.randint(5, 30) * 1_000_000
        sas_ssp = rng.randint(1, 10) * 1_000_000
        total_price = int((hw_ssp + sas_ssp) * 0.9)  # 10% 할인
        lines = [
            _line(ItemType.HW,   total_price * hw_ssp // (hw_ssp + sas_ssp),
                  ssp=hw_ssp),
            _line(ItemType.SAAS, total_price * sas_ssp // (hw_ssp + sas_ssp),
                  ssp=sas_ssp, months=12),
        ]
        c = _contract(lines)
        full = engine.evaluate(c)
        alloc_sum = sum(full.step4.allocations.values())
        suite.record(
            full.journal_trigger == "mixed_sale"
            and alloc_sum == full.step3.transaction_price,
            f"mixed_alloc_sum i={i}",
        )

    # ── 7. 3단계 — 변동대가(리베이트) 포함 시 거래가격 감소 ───────────────────
    for _ in range(5):
        from core.rules.models import ContractLineItem
        line = ContractLineItem(
            line_id="L01",
            item_type=ItemType.HW,
            description="서버",
            list_price=Decimal("10000000"),
            ssp=Decimal("10000000"),
            variable_consideration=Decimal("-500000"),
        )
        c = _contract([line])
        r3 = engine.step3_determine_price(c)
        suite.record(
            r3.transaction_price == Decimal("9500000"),
            "variable_consideration_rebate",
        )

    # ── 8. 무효 계약 → journal_trigger = 'hold' 또는 'advance_only' ──────────
    for _ in range(10):
        c = _contract([_line(ItemType.HW)], collectability_probable=False)
        full = engine.evaluate(c)
        suite.record(
            full.journal_trigger in ("hold", "advance_only"),
            "invalid_contract_trigger",
        )

    # ── 9. SW 영구 라이선스 → 한 시점 ────────────────────────────────────────
    for _ in range(5):
        c = _contract([_line(ItemType.SW_PERPETUAL, 3_000_000)])
        full = engine.evaluate(c, recognition_date=date(2025, 4, 1))
        suite.record(
            full.step5[0].timing == RecognitionTiming.POINT_IN_TIME,
            "sw_perpetual_point_in_time",
        )

    # ── 10. 대리인(순액) — NET 기준 설정 보존 ────────────────────────────────
    for _ in range(5):
        c = _contract([_line(ItemType.SW_PERPETUAL, 3_000_000,
                             basis=RecognitionBasis.NET)])
        full = engine.evaluate(c)
        suite.record(
            full.step2.obligations[0].revenue_basis == RecognitionBasis.NET,
            "agent_net_basis_preserved",
        )

    return suite


# ══════════════════════════════════════════════════════════════════════════════
# 2-2  분개 자동생성 — 차대변 균형 100%
# ══════════════════════════════════════════════════════════════════════════════

def test_journal_balance() -> SuiteResult:
    from core.journal.engine import JournalEngine

    suite = SuiteResult("분개 자동생성 (차대변 균형)")
    engine = JournalEngine()
    today = date(2025, 6, 1)

    def _check(label: str, entry) -> None:
        suite.record(entry.is_balanced(), f"불균형: {label}")

    cases = [
        ("외상 매출",      engine.sale_credit(today, Decimal("10000000"), Decimal("1000000"))),
        ("매출원가",       engine.sale_cogs(today, Decimal("7000000"))),
        ("선수금",         engine.advance_receipt(today, Decimal("5000000"), Decimal("500000"))),
        ("선수금→매출",    engine.advance_to_revenue(today, Decimal("5000000"))),
        ("SaaS 청구",      engine.deferred_invoice(today, Decimal("12000000"), Decimal("1200000"))),
        ("월 안분",        engine.monthly_recognition(today, Decimal("1000000"))),
        ("대리인 수수료",  engine.agency_sale(today, Decimal("1000000"), Decimal("100000"))),
        ("외상 매입",      engine.purchase_credit(today, Decimal("7000000"), Decimal("700000"))),
        ("선급금 지급",    engine.advance_payment(today, Decimal("5000000"))),
        ("선급금→재고",    engine.advance_to_inventory(today, Decimal("5000000"), Decimal("500000"))),
        ("수금",           engine.collection(today, Decimal("11000000"))),
        ("매입금 결제",    engine.ap_payment(today, Decimal("7700000"))),
        ("대손충당금",     engine.bad_debt_provision(today, Decimal("500000"))),
        ("대손 발생",      engine.bad_debt_writeoff(today, Decimal("300000"))),
        ("외화환산이익",   engine.fx_revaluation_gain(today, Decimal("50000"))),
        ("외국 라이선스",  engine.foreign_license_payment(
                               today, Decimal("1000000"), Decimal("100000"), Decimal("10000"))),
    ]

    for label, entry in cases:
        _check(label, entry)

    # 무작위 금액 반복 검증 (200건 → 각 분개 유형 × 무작위 금액)
    rng = random.Random(99)
    for _ in range(200):
        supply = Decimal(rng.randint(1, 1000) * 100_000)
        vat    = (supply * Decimal("0.1")).quantize(Decimal("1"))
        cost   = (supply * Decimal("0.7")).quantize(Decimal("1"))
        choice = rng.randint(0, 5)
        if choice == 0:
            _check("rand_sale_credit", engine.sale_credit(today, supply, vat))
        elif choice == 1:
            _check("rand_purchase_credit", engine.purchase_credit(today, cost, (cost * Decimal("0.1")).quantize(Decimal("1"))))
        elif choice == 2:
            _check("rand_deferred_invoice", engine.deferred_invoice(today, supply, vat))
        elif choice == 3:
            _check("rand_advance_receipt", engine.advance_receipt(today, supply, vat))
        elif choice == 4:
            _check("rand_monthly_recognition", engine.monthly_recognition(today, supply / 12))
        else:
            _check("rand_collection", engine.collection(today, supply + vat))

    return suite


# ══════════════════════════════════════════════════════════════════════════════
# 2-3  VAT / 원천세 룰엔진
# ══════════════════════════════════════════════════════════════════════════════

def test_vat() -> SuiteResult:
    from core.rules.vat import VATCalculator, VATCategory, classify_vat
    from core.rules.models import ItemType

    suite = SuiteResult("VAT 세율 분류")
    calc = VATCalculator()

    # 표준 10%
    r = calc.calc(Decimal("1000000"), VATCategory.STANDARD)
    suite.record(r.vat_amount == Decimal("100000"), "standard_10pct")
    suite.record(r.total == Decimal("1100000"), "standard_total")

    # 영세율 0%
    r = calc.calc(Decimal("1000000"), VATCategory.ZERO_RATE)
    suite.record(r.vat_amount == Decimal("0"), "zero_rate_0pct")

    # 면세
    r = calc.calc(Decimal("1000000"), VATCategory.EXEMPT)
    suite.record(r.vat_amount == Decimal("0"), "exempt_0pct")

    # 역산 — VAT 포함가 → 공급가액
    r_rev = calc.reverse_calc(Decimal("1100000"), VATCategory.STANDARD)
    suite.record(r_rev.supply_price == Decimal("1000000"), "reverse_calc_supply")
    suite.record(r_rev.vat_amount  == Decimal("100000"),  "reverse_calc_vat")

    # 분류 — 수출 → 영세율
    cat = classify_vat(ItemType.HW, is_export=True)
    suite.record(cat == VATCategory.ZERO_RATE, "export_zero_rate")

    # 분류 — 일반 HW → 표준
    cat = classify_vat(ItemType.HW)
    suite.record(cat == VATCategory.STANDARD, "hw_standard")

    # 금액 경계: 1원 단위 반올림
    r = calc.calc(Decimal("1000001"), VATCategory.STANDARD)
    suite.record(r.vat_amount == Decimal("100000"), "rounding_1won")

    return suite


def test_withholding() -> SuiteResult:
    from core.rules.withholding import WithholdingTaxEngine, IncomeType

    suite = SuiteResult("원천세 계산")
    engine = WithholdingTaxEngine()

    # 국내 인적용역 3.3%
    r = engine.calc_domestic(IncomeType.BUSINESS_SERVICE, Decimal("1000000"))
    suite.record(r.withholding_tax == Decimal("30000"), "domestic_biz_service_3pct")
    suite.record(r.local_tax == Decimal("3000"),        "domestic_local_tax")
    suite.record(r.net_payment == Decimal("967000"),    "domestic_net_payment")

    # 국내 사용료 20%
    r = engine.calc_domestic(IncomeType.ROYALTY, Decimal("1000000"))
    suite.record(r.withholding_tax == Decimal("200000"), "domestic_royalty_20pct")

    # 미국 법인 사용료 — 거주자증명서 있음 → 한·미 조약 10%
    r = engine.calc_foreign("US", IncomeType.ROYALTY, Decimal("1000000"),
                             treaty_cert_obtained=True)
    suite.record(r.withholding_tax == Decimal("100000"), "us_royalty_treaty_10pct")
    suite.record(r.treaty_applied,                       "us_treaty_flag_true")

    # 미국 법인 사용료 — 거주자증명서 없음 → 국내법 20%
    r = engine.calc_foreign("US", IncomeType.ROYALTY, Decimal("1000000"),
                             treaty_cert_obtained=False)
    suite.record(r.withholding_tax == Decimal("200000"), "us_royalty_no_cert_20pct")
    suite.record(not r.treaty_applied,                   "us_no_treaty_flag")

    # 아일랜드 법인 사용료 — 조약 면제 0%
    r = engine.calc_foreign("IE", IncomeType.ROYALTY, Decimal("1000000"),
                             treaty_cert_obtained=True)
    suite.record(r.withholding_tax == Decimal("0"), "ireland_royalty_0pct")

    # 일본 배당 — 5%
    r = engine.calc_foreign("JP", IncomeType.DIVIDEND, Decimal("1000000"),
                             treaty_cert_obtained=True)
    suite.record(r.withholding_tax == Decimal("50000"), "jp_dividend_5pct")

    # 총 원천징수액 = 국세 + 지방세
    r = engine.calc_foreign("US", IncomeType.ROYALTY, Decimal("1000000"),
                             treaty_cert_obtained=True)
    suite.record(r.total_withholding == r.withholding_tax + r.local_tax,
                 "total_withholding_eq_nat_plus_local")

    # 순지급액 = 총액 - 원천징수
    suite.record(r.net_payment == Decimal("1000000") - r.total_withholding,
                 "net_payment_consistency")

    return suite


# ══════════════════════════════════════════════════════════════════════════════
# 2-4  전자세금계산서 XML 빌더
# ══════════════════════════════════════════════════════════════════════════════

def test_etax_xml() -> SuiteResult:
    from core.etax.builder import TaxInvoiceBuilder, generate_issue_id
    from core.etax.models import (
        TaxInvoice, TaxInvoiceTypeCode, Party, TradeLineItem,
    )

    suite = SuiteResult("전자세금계산서 XML")
    builder = TaxInvoiceBuilder()

    supplier = Party(brn="1234567890", name="(주)공급사", representative="김공급",
                     email="supplier@test.com")
    buyer    = Party(brn="0987654321", name="(주)구매사")

    def _make_invoice(supply: int, qty: int = 1) -> TaxInvoice:
        line = TradeLineItem(
            seq=1,
            trade_date=date(2025, 6, 30),
            name="클라우드 서비스",
            quantity=Decimal(qty),
            unit_price=Decimal(supply),
            supply_amount=Decimal(supply * qty),
        )
        inv = TaxInvoice(
            type_code=TaxInvoiceTypeCode.GENERAL,
            issue_date=date(2025, 6, 30),
            invoicer=supplier,
            invoicee=buyer,
            lines=[line],
        )
        inv.recalc_totals()
        return inv

    # 기본 XML 생성 — 파싱 가능
    import xml.etree.ElementTree as ET
    for supply in [1_000_000, 5_000_000, 10_000_000]:
        inv = _make_invoice(supply)
        xml_str = builder.build(inv)
        try:
            ET.fromstring(xml_str.encode() if isinstance(xml_str, str) else xml_str)
            suite.record(True, f"xml_parseable supply={supply}")
        except Exception as e:
            suite.record(False, f"xml_not_parseable supply={supply}: {e}")

    # 합계 자동계산 — supply 1,000,000 → tax 100,000 → grand 1,100,000
    inv = _make_invoice(1_000_000)
    suite.record(inv.total_supply == Decimal("1000000"), "total_supply")
    suite.record(inv.total_tax    == Decimal("100000"),  "total_tax_10pct")
    suite.record(inv.grand_total  == Decimal("1100000"), "grand_total")

    # 승인번호 24자리
    issue_id = generate_issue_id("1234567890", date(2025, 6, 30))
    suite.record(len(issue_id) == 24, f"issue_id_len={len(issue_id)}")
    suite.record(issue_id.startswith("20250630"), "issue_id_date_prefix")

    # 영세율 → 세액 0
    inv_zero = _make_invoice(1_000_000)
    inv_zero.type_code = TaxInvoiceTypeCode.ZERO_RATE
    inv_zero.recalc_totals()
    suite.record(inv_zero.total_tax == Decimal("0"), "zero_rate_tax_0")

    # XML에 공급자·공급받는자 태그 포함
    inv = _make_invoice(2_000_000)
    xml_str = builder.build(inv)
    suite.record("InvoicerParty" in xml_str, "xml_has_invoicer_tag")
    suite.record("InvoiceeParty" in xml_str, "xml_has_invoicee_tag")
    suite.record("TaxInvoiceTradeLineItem" in xml_str, "xml_has_line_item_tag")

    # 수정사유 코드 — 반품(6)
    from core.etax.models import AmendmentCode
    inv_amend = _make_invoice(1_000_000)
    inv_amend.is_amendment   = True
    inv_amend.amendment_code = AmendmentCode.RETURN
    inv_amend.original_issue_id = "20250630123456789000000001"
    xml_amend = builder.build(inv_amend)
    suite.record("AmendmentCode" in xml_amend, "amendment_code_in_xml")

    return suite


# ══════════════════════════════════════════════════════════════════════════════
# 2-5  재무 부정 탐지
# ══════════════════════════════════════════════════════════════════════════════

def test_fraud_detection() -> SuiteResult:
    from core.fraud.engine import FraudDetectionEngine
    from core.fraud.models import Transaction, RiskLevel, FraudFlag

    suite = SuiteResult("재무 부정 탐지")
    engine = FraudDetectionEngine()
    rng = random.Random(7)

    def _txn(tid: str, amount: float, dt: str = "2025-01-15 10:00:00",
             vendor: str = "V01") -> Transaction:
        return Transaction(
            txn_id=tid,
            txn_datetime=datetime.fromisoformat(dt),
            amount=Decimal(str(amount)),
            vendor_id=vendor,
        )

    def _normal_txn(i: int) -> Transaction:
        """벤포드·타임스탬프·벤더를 모두 자연스럽게 분산한 정상 거래."""
        # 로그 균일 분포 → 벤포드 법칙 자동 충족
        amount = int(10 ** rng.uniform(3.2, 6.8))
        # 2025년 업무 시간대에 분산 (300일 × 8h)
        day_offset = i % 300
        hour = 9 + (i % 8)
        minute = (i * 7) % 60
        dt = datetime(2025, 1, 1).replace(
            month=1 + day_offset // 30,
            day=1 + day_offset % 28,
            hour=hour,
            minute=minute,
        )
        # 벤더 10곳에 분산
        vendor = f"V{(i % 10) + 1:02d}"
        return Transaction(
            txn_id=f"N{i:04d}",
            txn_datetime=dt,
            amount=Decimal(amount),
            vendor_id=vendor,
        )

    # 1. 정상 거래 (로그 균일 분포, 시간·벤더 분산) → CRITICAL 없음
    # 합성 랜덤 데이터는 임계값 주변 우연 충돌이 있을 수 있어 HIGH까지는 허용
    normal_txns = [_normal_txn(i) for i in range(500)]
    rpt = engine.analyze(normal_txns)
    suite.record(
        rpt.overall_risk != RiskLevel.CRITICAL,
        f"normal_no_critical (got {rpt.overall_risk})",
    )

    # 2. 라운드 넘버 편향 — 1,000,000원짜리 다량
    round_txns = [_txn(f"R{i:03d}", 1_000_000) for i in range(50)]
    rpt2 = engine.analyze(round_txns)
    has_round_flag = any(a.flag == FraudFlag.ROUND_NUMBER_BIAS for a in rpt2.alerts)
    suite.record(has_round_flag, "round_number_detected")

    # 3. 중복 거래 (같은 금액, 같은 벤더, 같은 날)
    dup_txns = [
        _txn("D001", 500_000, "2025-01-10 09:00:00", "V99"),
        _txn("D002", 500_000, "2025-01-10 14:00:00", "V99"),
    ] + [_txn(f"OK{i}", rng.randint(1000, 50000)) for i in range(20)]
    rpt3 = engine.analyze(dup_txns)
    has_dup = any(a.flag == FraudFlag.DUPLICATE_TXN for a in rpt3.alerts)
    suite.record(has_dup, "duplicate_detected")

    # 4. 한도 직하 분할 (1,000,000 미만 다수)
    threshold_txns = [
        _txn(f"T{i:03d}", 999_000 - i * 100)
        for i in range(15)
    ]
    rpt4 = engine.analyze(threshold_txns)
    has_threshold = any(a.flag == FraudFlag.JUST_BELOW_THRESHOLD for a in rpt4.alerts)
    suite.record(has_threshold, "just_below_threshold_detected")

    # 5. 비업무 시간대 (새벽 2시 거래)
    off_txns = [
        _txn(f"OFF{i}", rng.randint(1000, 99999), f"2025-01-{10+i:02d} 02:30:00")
        for i in range(10)
    ] + [_txn(f"ON{i}", rng.randint(1000, 99999)) for i in range(5)]
    rpt5 = engine.analyze(off_txns)
    has_off = any(a.flag == FraudFlag.OFF_HOURS for a in rpt5.alerts)
    suite.record(has_off, "off_hours_detected")

    # 6. FraudReport 구조 검증
    rpt6 = engine.analyze(normal_txns[:10])
    suite.record(rpt6.total_txns == 10, "report_total_txns")
    suite.record(isinstance(rpt6.summary, str) and len(rpt6.summary) > 0, "report_summary_nonempty")

    # 7. 빈 거래 리스트 → 오류 없이 처리
    rpt7 = engine.analyze([])
    suite.record(rpt7.total_txns == 0, "empty_txns_safe")

    # 8. 속도 이상 — 같은 벤더에서 짧은 시간 내 다수 거래
    velocity_txns = [
        _txn(f"VEL{i:02d}", 50_000, f"2025-01-01 {8+i//10:02d}:{(i*6)%60:02d}:00", "VFAST")
        for i in range(30)
    ]
    rpt8 = engine.analyze(velocity_txns)
    has_vel = any(a.flag == FraudFlag.VELOCITY_SPIKE for a in rpt8.alerts)
    suite.record(has_vel, "velocity_spike_detected")

    return suite


# ══════════════════════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    print("=" * 70)
    print("  Phase 2 룰엔진 품질 검증")
    print("=" * 70)

    suites: list[SuiteResult] = []

    runners = [
        ("K-IFRS 1115",          test_kifrs_1115),
        ("분개 자동생성",         test_journal_balance),
        ("VAT",                  test_vat),
        ("원천세",               test_withholding),
        ("전자세금계산서 XML",    test_etax_xml),
        ("재무 부정 탐지",        test_fraud_detection),
    ]

    for name, fn in runners:
        print(f"\n  ▶ {name} …", end="", flush=True)
        try:
            result = fn()
            suites.append(result)
            result.print_summary()
        except Exception as e:
            print(f"\n  ❌ 실행 오류: {e}")
            import traceback
            traceback.print_exc()

    # 전체 집계
    total_passed = sum(s.passed for s in suites)
    total_all    = sum(s.total  for s in suites)
    pct          = total_passed / total_all * 100 if total_all else 0

    print("\n" + "=" * 70)
    print(f"  전체 결과: {total_passed}/{total_all} 통과")
    grade = "🟢 양호" if pct >= 95 else "🟡 보통" if pct >= 80 else "🔴 개선 필요"
    print(f"  점수: {pct:.1f}%  {grade}")
    print("=" * 70)

    # CI 호환 종료 코드
    sys.exit(0 if pct >= 95 else 1)


if __name__ == "__main__":
    main()
