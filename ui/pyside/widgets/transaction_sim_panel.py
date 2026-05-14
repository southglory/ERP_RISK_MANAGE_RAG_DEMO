"""거래 시뮬레이터 — 시나리오 선택 → 전 과정 분개 자동 생성."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QScrollArea,
    QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.journal.engine import JournalEngine, DrCr, JournalEntry


# ── 시나리오 정의 ─────────────────────────────────────────────────────────────
# (key, display_label, description, [(field_key, label, default), ...])
_SCENARIOS: list[tuple[str, str, str, list[tuple[str, str, str]]]] = [
    (
        "hw_spot",
        "🖥️ HW 단품 판매 (일시점)",
        "발주 → 입고 → 출고 → 수금 4단계 분개를 생성합니다.\n"
        "공급가액·원가·VAT를 입력하면 매입/매출/원가/수금 전표가 순서대로 생성됩니다.",
        [
            ("supply_price", "공급가액 (원)", "10000000"),
            ("cost",         "원가 (원)",     "7000000"),
            ("vat_amount",   "VAT (원)",      "1000000"),
        ],
    ),
    (
        "saas_annual",
        "☁️ SaaS 연간 구독 (기간 안분)",
        "연간 구독료 청구 후 12개월 월할 수익 인식 전표를 생성합니다.\n"
        "선수수익(계약부채)으로 계상 후 매월 1/12씩 안분됩니다.",
        [
            ("annual_fee", "연간 구독료 (원)", "12000000"),
            ("vat_amount", "VAT (원)",         "1200000"),
        ],
    ),
    (
        "advance_delivery",
        "📦 선수금 계약 (납품형)",
        "계약 시 선수금 수령 → 납품 → 잔금 수금 흐름을 생성합니다.\n"
        "선수금 비율(%)을 입력하면 납품 시 자동으로 선수금이 매출로 대체됩니다.",
        [
            ("contract_amount", "계약금액 (원)",   "50000000"),
            ("advance_rate",    "선수금 비율 (%)", "30"),
            ("vat_amount",      "VAT (원)",        "5000000"),
        ],
    ),
    (
        "foreign_license",
        "🌐 외국 SW 라이선스 지급",
        "외국법인 로열티 지급 시 원천세(법인세+지방세) 차감 후 순액 송금 분개를 생성합니다.\n"
        "조세조약 적용 시 treaty_rate(%)를 조약 제한세율로 입력하세요.",
        [
            ("gross_amount",   "지급총액 (원)",            "100000000"),
            ("treaty_rate",    "원천세율 % (조약 적용 시)", "10"),
            ("local_tax_rate", "지방세율 % (원천세×10%)",   "1"),
        ],
    ),
    (
        "agency_commission",
        "🤝 대리인 수수료 매출 (순액)",
        "대리인 거래: 수수료(순액)만 매출 인식 후 수금 전표를 생성합니다.\n"
        "총 거래 대금 아닌 수수료만 수익으로 기록됩니다.",
        [
            ("commission", "수수료 (원)", "5000000"),
            ("vat_amount", "VAT (원)",    "500000"),
        ],
    ),
]

_DR_COLOR  = QColor("#1a5276")   # 차변 — 진한 파랑
_CR_COLOR  = QColor("#1e8449")   # 대변 — 진한 초록
_HEAD_COLOR = QColor("#283747")  # 전표 헤더 행


class _ParamPage(QWidget):
    """시나리오별 파라미터 입력 페이지."""

    def __init__(self, fields: list[tuple[str, str, str]], parent=None) -> None:
        super().__init__(parent)
        form = QFormLayout(self)
        form.setContentsMargins(0, 4, 0, 4)
        self._edits: dict[str, QLineEdit] = {}
        for key, label, default in fields:
            edit = QLineEdit(default)
            edit.setAlignment(Qt.AlignRight)
            form.addRow(label, edit)
            self._edits[key] = edit

    def values(self) -> dict[str, str]:
        return {k: v.text().replace(",", "") for k, v in self._edits.items()}


class TransactionSimPanel(QWidget):
    """거래 시뮬레이터 패널."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._engine = JournalEngine()
        self._build_ui()

    # ── UI 빌드 ───────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        # 왼쪽 — 시나리오 + 파라미터
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setMinimumWidth(320)
        left_scroll.setMaximumWidth(400)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)
        left_scroll.setWidget(left)

        title = QLabel("📊 거래 시뮬레이터")
        title.setFont(QFont("Pretendard", 13, QFont.Bold))
        lv.addWidget(title)

        # 시나리오 선택
        sc_box = QGroupBox("시나리오")
        sc_vbox = QVBoxLayout(sc_box)
        self._sc_combo = QComboBox()
        for key, label, _, _ in _SCENARIOS:
            self._sc_combo.addItem(label, key)
        sc_vbox.addWidget(self._sc_combo)
        self._desc_label = QLabel()
        self._desc_label.setWordWrap(True)
        self._desc_label.setFont(QFont("Pretendard", 9))
        sc_vbox.addWidget(self._desc_label)
        lv.addWidget(sc_box)

        # 거래 기준일
        date_box = QGroupBox("거래 기준일")
        date_form = QFormLayout(date_box)
        self._date_edit = QDateEdit(date.today())
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDisplayFormat("yyyy-MM-dd")
        date_form.addRow("기준일", self._date_edit)
        lv.addWidget(date_box)

        # 파라미터 (시나리오별 QStackedWidget)
        param_box = QGroupBox("파라미터")
        param_vbox = QVBoxLayout(param_box)
        self._stack = QStackedWidget()
        self._param_pages: list[_ParamPage] = []
        for _, _, _, fields in _SCENARIOS:
            page = _ParamPage(fields)
            self._stack.addWidget(page)
            self._param_pages.append(page)
        param_vbox.addWidget(self._stack)
        lv.addWidget(param_box)

        # 실행 버튼
        run_btn = QPushButton("▶  분개 생성")
        run_btn.setMinimumHeight(40)
        run_btn.setFont(QFont("Pretendard", 11, QFont.Bold))
        run_btn.clicked.connect(self._run)
        lv.addWidget(run_btn)
        lv.addStretch()

        self._sc_combo.currentIndexChanged.connect(self._on_scenario_changed)
        self._on_scenario_changed(0)

        splitter.addWidget(left_scroll)

        # 오른쪽 — 결과 분개 테이블
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 8, 8, 8)

        result_box = QGroupBox("생성된 분개 전표")
        result_vbox = QVBoxLayout(result_box)

        self._journal_table = QTableWidget(0, 7)
        self._journal_table.setHorizontalHeaderLabels(
            ["전표ID", "일자", "적요", "Dr/Cr", "코드", "계정명", "금액"]
        )
        hh = self._journal_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.Interactive)
        hh.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self._journal_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._journal_table.setAlternatingRowColors(False)
        result_vbox.addWidget(self._journal_table)

        self._summary_label = QLabel("")
        self._summary_label.setFont(QFont("Consolas", 10))
        result_vbox.addWidget(self._summary_label)
        rv.addWidget(result_box)

        splitter.addWidget(right)
        splitter.setSizes([360, 920])

    # ── 이벤트 ───────────────────────────────────────────────────────────────

    def _on_scenario_changed(self, idx: int) -> None:
        self._stack.setCurrentIndex(idx)
        _, _, desc, _ = _SCENARIOS[idx]
        self._desc_label.setText(desc)

    def _run(self) -> None:
        idx = self._sc_combo.currentIndex()
        key = _SCENARIOS[idx][0]
        vals = self._param_pages[idx].values()
        base_date = self._date_edit.date().toPython()

        try:
            entries = self._build_entries(key, vals, base_date)
        except (InvalidOperation, KeyError, ValueError) as e:
            self._summary_label.setText(f"입력 오류: {e}")
            return

        self._populate_table(entries)

    # ── 분개 생성 ─────────────────────────────────────────────────────────────

    def _d(self, s: str) -> Decimal:
        return Decimal(s or "0")

    def _build_entries(
        self, key: str, vals: dict[str, str], base: date
    ) -> list[JournalEntry]:
        e = self._engine
        d = self._d
        entries: list[JournalEntry] = []

        if key == "hw_spot":
            supply = d(vals["supply_price"])
            cost   = d(vals["cost"])
            vat    = d(vals["vat_amount"])
            # 매입
            entries.append(e.purchase_credit(base, cost, Decimal("0"), source_doc="PO-001"))
            # 매출 + 원가
            entries.append(e.sale_credit(base, supply, vat, source_doc="SO-001"))
            entries.append(e.sale_cogs(base, cost, source_doc="SO-001"))
            # 수금 (30일 후)
            entries.append(e.collection(base + timedelta(days=30),
                                         supply + vat, source_doc="RV-001"))

        elif key == "saas_annual":
            annual = d(vals["annual_fee"])
            vat    = d(vals["vat_amount"])
            monthly = (annual / 12).quantize(Decimal("1"))
            # 청구 → 선수수익
            entries.append(e.deferred_invoice(base, annual, vat, source_doc="INV-001"))
            # 12개월 안분
            for m in range(12):
                rec_date = date(base.year + (base.month + m - 1) // 12,
                                (base.month + m - 1) % 12 + 1,
                                1)
                entries.append(e.monthly_recognition(
                    rec_date, monthly, source_doc="REC-{:02d}".format(m + 1)
                ))

        elif key == "advance_delivery":
            contract = d(vals["contract_amount"])
            rate     = d(vals["advance_rate"]) / 100
            vat      = d(vals["vat_amount"])
            advance  = (contract * rate).quantize(Decimal("1"))
            # 선수금 수령
            entries.append(e.advance_receipt(base, advance, Decimal("0"), source_doc="ADV-001"))
            # 납품 (60일 후)
            deliver = base + timedelta(days=60)
            entries.append(e.sale_credit(deliver, contract, vat, source_doc="SO-001"))
            entries.append(e.sale_cogs(deliver, (contract * Decimal("0.6")).quantize(Decimal("1")),
                                       source_doc="SO-001"))
            entries.append(e.advance_to_revenue(deliver, advance, source_doc="SO-001"))
            # 잔금 수금 (90일 후)
            remaining = contract + vat - advance
            entries.append(e.collection(base + timedelta(days=90),
                                         remaining, source_doc="RV-001"))

        elif key == "foreign_license":
            gross      = d(vals["gross_amount"])
            wht_rate   = d(vals["treaty_rate"]) / 100
            local_rate = d(vals["local_tax_rate"]) / 100
            wht  = (gross * wht_rate).quantize(Decimal("1"))
            local = (gross * local_rate).quantize(Decimal("1"))
            entries.append(e.foreign_license_payment(
                base, gross, wht, local, source_doc="PAY-001"
            ))

        elif key == "agency_commission":
            comm = d(vals["commission"])
            vat  = d(vals["vat_amount"])
            entries.append(e.agency_sale(base, comm, vat, source_doc="AGT-001"))
            entries.append(e.collection(base + timedelta(days=30),
                                         comm + vat, source_doc="RV-001"))

        return entries

    # ── UI 업데이트 ───────────────────────────────────────────────────────────

    def _populate_table(self, entries: list[JournalEntry]) -> None:
        self._journal_table.setRowCount(0)
        total_dr = Decimal("0")
        total_cr = Decimal("0")

        for entry in entries:
            for line in entry.lines:
                row = self._journal_table.rowCount()
                self._journal_table.insertRow(row)

                drcr_str = "차변(Dr)" if line.drcr == DrCr.DEBIT else "대변(Cr)"
                bg = _DR_COLOR if line.drcr == DrCr.DEBIT else _CR_COLOR

                items = [
                    QTableWidgetItem(entry.entry_id),
                    QTableWidgetItem(str(entry.entry_date)),
                    QTableWidgetItem(entry.description),
                    QTableWidgetItem(drcr_str),
                    QTableWidgetItem(line.account.code),
                    QTableWidgetItem(line.account.name),
                    QTableWidgetItem(f"{int(line.amount):,}"),
                ]
                for col, item in enumerate(items):
                    item.setBackground(bg)
                    if col == 6:
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self._journal_table.setItem(row, col, item)

                if line.drcr == DrCr.DEBIT:
                    total_dr += line.amount
                else:
                    total_cr += line.amount

        balanced = "✅ 차대 균형" if total_dr == total_cr else "❌ 불균형"
        self._summary_label.setText(
            f"전표 {len(entries)}건  |  "
            f"차변 합계: {int(total_dr):,}원  |  "
            f"대변 합계: {int(total_cr):,}원  |  {balanced}"
        )
