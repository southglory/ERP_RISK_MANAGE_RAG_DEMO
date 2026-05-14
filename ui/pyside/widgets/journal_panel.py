"""분개 자동생성 패널 — K-IFRS 1115 5단계 + 분개 결과 표시."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.rules.models import (
    Contract,
    ContractLineItem,
    ItemType,
    RecognitionBasis,
)
from core.rules.kifrs_1115 import KIFRS1115Engine
from core.journal.engine import DrCr


# ── 백그라운드 워커 (룰 엔진은 CPU-bound이지만 UI 블로킹 방지) ──────────────────

class _EvalWorker(QThread):
    finished = Signal(dict)   # KIFRS1115Result.model_dump(mode='json')
    error = Signal(str)

    def __init__(self, contract: Contract, rec_date: date) -> None:
        super().__init__()
        self._contract = contract
        self._rec_date = rec_date

    def run(self) -> None:
        try:
            engine = KIFRS1115Engine()
            result = engine.evaluate(self._contract, recognition_date=self._rec_date)
            self.finished.emit(result.model_dump(mode="json"))
        except Exception as e:
            self.error.emit(str(e))


# ── 계약 라인 입력 행 ──────────────────────────────────────────────────────────

_ITEM_TYPE_LABELS = {
    "hw":               "HW 박스",
    "sw_perpetual":     "SW 영구 라이선스",
    "sw_subscription":  "SW 구독",
    "saas":             "SaaS",
    "maintenance":      "유지보수",
    "installation":     "설치 용역",
    "warranty_assurance": "확신유형 보증",
    "warranty_service": "용역유형 보증(연장)",
}

_BASIS_LABELS = {
    "gross": "본인 (총액)",
    "net":   "대리인 (순액)",
}


class _LineRow(QWidget):
    removed = Signal(object)

    def __init__(self, line_num: int, parent=None) -> None:
        super().__init__(parent)
        self._num = line_num
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        # 품목 유형
        self.type_combo = QComboBox()
        self.type_combo.setMinimumWidth(120)
        for key, label in _ITEM_TYPE_LABELS.items():
            self.type_combo.addItem(label, key)
        layout.addWidget(self.type_combo, 2)

        # 설명
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("설명")
        layout.addWidget(self.desc_edit, 2)

        # 계약 단가
        self.price_edit = QLineEdit("1000000")
        self.price_edit.setMinimumWidth(80)
        self.price_edit.setPlaceholderText("단가")
        layout.addWidget(self.price_edit, 1)

        # SSP
        self.ssp_edit = QLineEdit("1000000")
        self.ssp_edit.setMinimumWidth(80)
        self.ssp_edit.setPlaceholderText("SSP")
        layout.addWidget(self.ssp_edit, 1)

        # 서비스 개월
        self.months_edit = QLineEdit()
        self.months_edit.setFixedWidth(44)
        self.months_edit.setPlaceholderText("개월")
        layout.addWidget(self.months_edit, 0)

        # 본인/대리인
        self.basis_combo = QComboBox()
        self.basis_combo.setMinimumWidth(90)
        for key, label in _BASIS_LABELS.items():
            self.basis_combo.addItem(label, key)
        layout.addWidget(self.basis_combo, 1)

        # 제거 버튼
        del_btn = QPushButton("✕")
        del_btn.setFixedWidth(26)
        del_btn.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(del_btn, 0)

    def to_line_item(self) -> ContractLineItem:
        raw_price = self.price_edit.text().replace(",", "").strip() or "0"
        raw_ssp   = self.ssp_edit.text().replace(",", "").strip() or "0"
        months_str = self.months_edit.text().strip()

        return ContractLineItem(
            line_id=f"L{self._num:02d}",
            item_type=ItemType(self.type_combo.currentData()),
            description=self.desc_edit.text() or f"품목 {self._num}",
            list_price=Decimal(raw_price),
            ssp=Decimal(raw_ssp),
            service_months=int(months_str) if months_str else None,
            revenue_basis=RecognitionBasis(self.basis_combo.currentData()),
        )


# ── 분개 결과 테이블 ─────────────────────────────────────────────────────────────

class _JournalTable(QTableWidget):
    _HEADERS = ["날짜", "계정과목", "코드", "차/대", "금액(원)", "메모"]

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(self._HEADERS), parent)
        self.setHorizontalHeaderLabels(self._HEADERS)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)

    def load_entries(self, entries: list[dict], entry_date: date) -> None:
        self.setRowCount(0)
        date_str = entry_date.strftime("%Y-%m-%d")

        for entry in entries:
            # 구분선 (설명 행)
            sep_row = self.rowCount()
            self.insertRow(sep_row)
            desc_item = QTableWidgetItem(f"▶ {entry['description']}")
            desc_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            font = QFont()
            font.setBold(True)
            desc_item.setFont(font)
            self.setItem(sep_row, 0, QTableWidgetItem(date_str))
            self.setItem(sep_row, 1, desc_item)
            self.setSpan(sep_row, 1, 1, 5)

            for line in entry.get("lines", []):
                row = self.rowCount()
                self.insertRow(row)
                self.setItem(row, 0, QTableWidgetItem(""))
                self.setItem(row, 1, QTableWidgetItem(line["account"]["name"]))
                self.setItem(row, 2, QTableWidgetItem(line["account"]["code"]))
                drcr_label = "차변" if line["drcr"] == DrCr.DEBIT.value else "대변"
                self.setItem(row, 3, QTableWidgetItem(drcr_label))
                amount_item = QTableWidgetItem(f"{int(line['amount']):,}")
                amount_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.setItem(row, 4, amount_item)
                self.setItem(row, 5, QTableWidgetItem(line.get("memo", "")))


# ── 메인 패널 ──────────────────────────────────────────────────────────────────

class JournalEnginePanel(QWidget):
    """분개 자동생성 패널."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._line_rows: list[_LineRow] = []
        self._worker: _EvalWorker | None = None
        self._kifrs_result: dict | None = None
        self._line_counter = 1
        self._build_ui()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        # ── 왼쪽: 스크롤 가능한 입력 폼 ────────────────────────────────────
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setMinimumWidth(460)
        left_scroll.setMaximumWidth(620)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_scroll.setWidget(left)

        # 제목
        title = QLabel("📒 분개 자동생성 — K-IFRS 1115")
        title.setFont(QFont("Pretendard", 13, QFont.Bold))
        left_layout.addWidget(title)

        # 계약 기본 정보
        meta_box = QGroupBox("계약 기본 정보")
        meta_form = QFormLayout(meta_box)

        self._contract_id_edit = QLineEdit("CTR-2025-001")
        self._customer_edit    = QLineEdit("CUST-001")
        self._rec_date_edit    = QDateEdit(date.today())
        self._rec_date_edit.setCalendarPopup(True)
        self._rec_date_edit.setDisplayFormat("yyyy-MM-dd")

        meta_form.addRow("계약번호", self._contract_id_edit)
        meta_form.addRow("고객 ID",  self._customer_edit)
        meta_form.addRow("인식 기준일", self._rec_date_edit)
        left_layout.addWidget(meta_box)

        # 5요건 체크
        cond_box = QGroupBox("1단계 — 계약 식별 5요건")
        cond_layout = QVBoxLayout(cond_box)
        self._cond_checks: list[QCheckBox] = []
        for label in [
            "① 당사자 승인·확약",
            "② 권리 식별 가능",
            "③ 지급조건 식별 가능",
            "④ 상업적 실질",
            "⑤ 회수 가능성 높음",
        ]:
            cb = QCheckBox(label)
            cb.setChecked(True)
            self._cond_checks.append(cb)
            cond_layout.addWidget(cb)
        left_layout.addWidget(cond_box)

        # 계약 라인
        lines_box = QGroupBox("계약 라인 (수행의무 후보)")
        lines_layout = QVBoxLayout(lines_box)

        # 라인 스크롤 영역
        self._lines_scroll = QScrollArea()
        self._lines_scroll.setWidgetResizable(True)
        self._lines_container = QWidget()
        self._lines_vbox = QVBoxLayout(self._lines_container)
        self._lines_vbox.setAlignment(Qt.AlignTop)
        self._lines_vbox.setSpacing(2)
        self._lines_scroll.setWidget(self._lines_container)
        self._lines_scroll.setMinimumHeight(90)
        self._lines_scroll.setMaximumHeight(220)
        lines_layout.addWidget(self._lines_scroll)

        add_line_btn = QPushButton("+ 라인 추가")
        add_line_btn.clicked.connect(self._add_line)
        lines_layout.addWidget(add_line_btn)
        left_layout.addWidget(lines_box)

        # 기본 라인 2개 추가
        self._add_default_lines()

        # 추가 입력 (GI 단가·원가·수금)
        gi_box = QGroupBox("출고(GI) / 수금 정보")
        gi_form = QFormLayout(gi_box)
        self._supply_edit     = QLineEdit("10000000")
        self._cost_edit       = QLineEdit("7000000")
        self._collect_edit    = QLineEdit()
        self._collect_edit.setPlaceholderText("미입력 시 수금 분개 생략")
        gi_form.addRow("공급가액(원)",  self._supply_edit)
        gi_form.addRow("원가(원)",      self._cost_edit)
        gi_form.addRow("수금액(원)",    self._collect_edit)
        left_layout.addWidget(gi_box)

        # 실행 버튼
        run_btn = QPushButton("▶  K-IFRS 평가 + 분개 생성")
        run_btn.setMinimumHeight(40)
        run_btn.setFont(QFont("Pretendard", 11, QFont.Bold))
        run_btn.clicked.connect(self._run_eval)
        left_layout.addWidget(run_btn)

        left_layout.addStretch()
        splitter.addWidget(left_scroll)

        # ── 오른쪽: 결과 ─────────────────────────────────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)

        # K-IFRS 5단계 요약
        result_box = QGroupBox("K-IFRS 1115 평가 결과")
        result_box_layout = QVBoxLayout(result_box)
        self._result_text = QTextEdit()
        self._result_text.setReadOnly(True)
        self._result_text.setFont(QFont("Consolas", 10))
        self._result_text.setFixedHeight(200)
        result_box_layout.addWidget(self._result_text)
        right_layout.addWidget(result_box)

        # 분개 테이블
        journal_box = QGroupBox("생성된 분개")
        journal_box_layout = QVBoxLayout(journal_box)
        self._journal_table = _JournalTable()
        journal_box_layout.addWidget(self._journal_table)
        right_layout.addWidget(journal_box)

        splitter.addWidget(right)
        splitter.setSizes([560, 800])

    # ── 라인 관리 ──────────────────────────────────────────────────────────────

    def _add_default_lines(self) -> None:
        # HW 라인
        row = _LineRow(self._line_counter)
        row.type_combo.setCurrentIndex(0)  # hw
        row.desc_edit.setText("서버 1대")
        row.price_edit.setText("10000000")
        row.ssp_edit.setText("10000000")
        self._append_line_row(row)

        # SaaS 라인
        row2 = _LineRow(self._line_counter)
        row2.type_combo.setCurrentIndex(3)  # saas
        row2.desc_edit.setText("클라우드 구독 1년")
        row2.price_edit.setText("1200000")
        row2.ssp_edit.setText("1200000")
        row2.months_edit.setText("12")
        self._append_line_row(row2)

    def _add_line(self) -> None:
        row = _LineRow(self._line_counter)
        self._append_line_row(row)

    def _append_line_row(self, row: _LineRow) -> None:
        row.removed.connect(self._remove_line)
        self._lines_vbox.addWidget(row)
        self._line_rows.append(row)
        self._line_counter += 1

    def _remove_line(self, row: _LineRow) -> None:
        self._lines_vbox.removeWidget(row)
        self._line_rows.remove(row)
        row.deleteLater()

    # ── 평가 실행 ──────────────────────────────────────────────────────────────

    def _run_eval(self) -> None:
        if self._worker and self._worker.isRunning():
            return

        try:
            contract = self._build_contract()
        except Exception as e:
            QMessageBox.warning(self, "입력 오류", str(e))
            return

        rec_dt = self._rec_date_edit.date().toPython()
        self._result_text.setPlainText("평가 중 …")

        self._worker = _EvalWorker(contract, rec_dt)
        self._worker.finished.connect(self._on_eval_done)
        self._worker.error.connect(self._on_eval_error)
        self._worker.start()

    def _build_contract(self) -> Contract:
        cond_flags = [cb.isChecked() for cb in self._cond_checks]
        lines = [row.to_line_item() for row in self._line_rows]
        if not lines:
            raise ValueError("계약 라인을 1개 이상 입력하세요.")

        return Contract(
            contract_id=self._contract_id_edit.text() or "CTR-001",
            customer_id=self._customer_edit.text() or "CUST-001",
            contract_date=self._rec_date_edit.date().toPython(),
            approved_by_both_parties=cond_flags[0],
            rights_identifiable=cond_flags[1],
            payment_terms_identifiable=cond_flags[2],
            commercial_substance=cond_flags[3],
            collectability_probable=cond_flags[4],
            lines=lines,
        )

    def _on_eval_done(self, result: dict) -> None:
        self._kifrs_result = result
        self._display_result(result)
        self._generate_journals(result)

    def _on_eval_error(self, msg: str) -> None:
        self._result_text.setPlainText(f"오류: {msg}")

    # ── 결과 표시 ──────────────────────────────────────────────────────────────

    def _display_result(self, r: dict) -> None:
        lines: list[str] = []
        s1 = r["step1"]
        lines.append(f"[1단계] 계약 식별: {'✅ 유효' if s1['is_valid_contract'] else '❌ 무효'}")
        if s1["failed_conditions"]:
            lines.append(f"  미충족: {', '.join(s1['failed_conditions'])}")
        lines.append(f"  처리: {s1['disposition']}")

        if r.get("step2"):
            obs = r["step2"]["obligations"]
            lines.append(f"\n[2단계] 수행의무: {len(obs)}개")
            for ob in obs:
                lines.append(f"  {ob['po_id']} | {ob['item_type']} | {ob['recognition_timing']}")

        if r.get("step3"):
            tp = r["step3"]["transaction_price"]
            lines.append(f"\n[3단계] 거래가격: {int(tp):,}원")
            vc = r["step3"]["variable_consideration_included"]
            if vc:
                lines.append(f"  변동대가: {int(vc):,}원")

        if r.get("step4"):
            lines.append("\n[4단계] SSP 배분:")
            for po_id, amt in r["step4"]["allocations"].items():
                lines.append(f"  {po_id}: {int(amt):,}원")

        if r.get("step5"):
            lines.append("\n[5단계] 수익 인식:")
            for rec in r["step5"]:
                if rec["timing"] == "point_in_time":
                    lines.append(f"  {rec['po_id']}: 한 시점 ({rec['recognition_date']})")
                else:
                    sch = rec.get("schedule", [])
                    if sch:
                        lines.append(
                            f"  {rec['po_id']}: 기간 안분 "
                            f"{sch[0]['period_label']}~{sch[-1]['period_label']} "
                            f"({int(sch[0]['amount']):,}원/월)"
                        )

        lines.append(f"\n📌 Journal Trigger: {r['journal_trigger']}")
        self._result_text.setPlainText("\n".join(lines))

    def _generate_journals(self, r: dict) -> None:
        from core.journal.engine import JournalEngine
        from core.rules.vat import VATCalculator, VATCategory

        engine = JournalEngine()
        vat_calc = VATCalculator()
        rec_date = self._rec_date_edit.date().toPython()
        trigger = r.get("journal_trigger", "hold")

        supply_raw = self._supply_edit.text().replace(",", "").strip()
        cost_raw   = self._cost_edit.text().replace(",", "").strip()
        collect_raw = self._collect_edit.text().replace(",", "").strip()

        supply = Decimal(supply_raw) if supply_raw else Decimal("0")
        cost   = Decimal(cost_raw)   if cost_raw   else Decimal("0")
        collect = Decimal(collect_raw) if collect_raw else Decimal("0")

        vat = vat_calc.calc(supply, VATCategory.STANDARD).vat_amount
        entries_raw: list[dict] = []

        if trigger in ("point_sale", "mixed_sale"):
            if cost > 0:
                entries_raw.append(
                    engine.purchase_credit(rec_date, cost, vat_calc.calc(cost, VATCategory.STANDARD).vat_amount)
                    .model_dump(mode="json")
                )
            if supply > 0:
                entries_raw.append(
                    engine.sale_credit(rec_date, supply, vat).model_dump(mode="json")
                )
            if cost > 0:
                entries_raw.append(
                    engine.sale_cogs(rec_date, cost).model_dump(mode="json")
                )

        elif trigger == "deferred_sale":
            if cost > 0:
                entries_raw.append(
                    engine.purchase_credit(rec_date, cost, vat_calc.calc(cost, VATCategory.STANDARD).vat_amount)
                    .model_dump(mode="json")
                )
            if supply > 0:
                entries_raw.append(
                    engine.deferred_invoice(rec_date, supply, vat).model_dump(mode="json")
                )
            # 첫 달 안분
            if r.get("step5"):
                for rec in r["step5"]:
                    if rec["timing"] == "over_time" and rec.get("schedule"):
                        amt = Decimal(str(rec["schedule"][0]["amount"]))
                        entries_raw.append(
                            engine.monthly_recognition(rec_date, amt, memo="1차 월 안분").model_dump(mode="json")
                        )

        elif trigger == "advance_only":
            if supply > 0:
                entries_raw.append(
                    engine.advance_receipt(rec_date, supply, vat).model_dump(mode="json")
                )

        if collect > 0:
            entries_raw.append(
                engine.collection(rec_date, collect).model_dump(mode="json")
            )

        self._journal_table.load_entries(entries_raw, rec_date)
