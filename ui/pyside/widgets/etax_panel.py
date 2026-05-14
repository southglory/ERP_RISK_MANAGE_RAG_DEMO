"""🧾 전자세금계산서 워커 패널 — KEC v3.0 XML 빌드·검증."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from core.etax.models import (
    Party, PurposeCode, TaxInvoice,
    TaxInvoiceTypeCode, TradeLineItem,
)
from core.etax.builder import TaxInvoiceBuilder, generate_issue_id
from core.etax.validator import validate_invoice


_TYPE_LABELS = {
    "0101": "일반 세금계산서",
    "0102": "영세율 세금계산서",
    "0201": "계산서(면세)",
    "0202": "영세 계산서",
}

_PURPOSE_LABELS = {"01": "영수", "02": "청구"}


class _PartyForm(QGroupBox):
    def __init__(self, title: str, default_brn: str = "", default_name: str = "", parent=None):
        super().__init__(title, parent)
        form = QFormLayout(self)
        self.brn  = QLineEdit(default_brn); self.brn.setPlaceholderText("000-00-00000")
        self.name = QLineEdit(default_name)
        self.rep  = QLineEdit(); self.rep.setPlaceholderText("대표자")
        self.addr = QLineEdit(); self.addr.setPlaceholderText("주소")
        self.btype= QLineEdit(); self.btype.setPlaceholderText("업태")
        self.bitem= QLineEdit(); self.bitem.setPlaceholderText("종목")
        self.email= QLineEdit(); self.email.setPlaceholderText("이메일")
        form.addRow("사업자번호", self.brn)
        form.addRow("상호",       self.name)
        form.addRow("대표자",     self.rep)
        form.addRow("주소",       self.addr)
        form.addRow("업태",       self.btype)
        form.addRow("종목",       self.bitem)
        form.addRow("이메일",     self.email)

    def to_party(self) -> Party:
        return Party(
            brn=self.brn.text().replace("-", ""),
            name=self.name.text() or "미입력",
            representative=self.rep.text(),
            address=self.addr.text(),
            business_type=self.btype.text(),
            business_item=self.bitem.text(),
            email=self.email.text(),
        )


class _LineItemRow(QWidget):
    def __init__(self, seq: int, trade_date: date, parent=None):
        super().__init__(parent)
        self._seq = seq
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)

        self.name_edit   = QLineEdit(); self.name_edit.setPlaceholderText("품목명")
        self.qty_edit    = QLineEdit("1"); self.qty_edit.setFixedWidth(44)
        self.price_edit  = QLineEdit("0"); self.price_edit.setMinimumWidth(90)
        self.supply_edit = QLineEdit("0"); self.supply_edit.setMinimumWidth(90)
        self.tax_edit    = QLineEdit("0"); self.tax_edit.setFixedWidth(80)
        self.tax_edit.setReadOnly(True)

        layout.addWidget(self.name_edit, 3)
        layout.addWidget(QLabel("수량"), 0); layout.addWidget(self.qty_edit, 0)
        layout.addWidget(QLabel("단가"), 0); layout.addWidget(self.price_edit, 1)
        layout.addWidget(QLabel("공급가"), 0); layout.addWidget(self.supply_edit, 1)
        layout.addWidget(QLabel("세액"), 0); layout.addWidget(self.tax_edit, 0)

        self._trade_date = trade_date
        self.price_edit.textChanged.connect(self._auto_supply)

    def _auto_supply(self, text: str) -> None:
        try:
            qty   = Decimal(self.qty_edit.text() or "1")
            price = Decimal(text.replace(",", "") or "0")
            supply = qty * price
            self.supply_edit.setText(str(int(supply)))
        except InvalidOperation:
            pass

    def to_line(self, type_code: TaxInvoiceTypeCode) -> TradeLineItem:
        supply = Decimal(self.supply_edit.text().replace(",", "") or "0")
        line = TradeLineItem(
            seq=self._seq,
            trade_date=self._trade_date,
            name=self.name_edit.text() or f"품목{self._seq}",
            quantity=Decimal(self.qty_edit.text() or "1"),
            unit_price=Decimal(self.price_edit.text().replace(",", "") or "0"),
            supply_amount=supply,
        )
        line.tax_amount = line.calc_tax(type_code)
        self.tax_edit.setText(str(int(line.tax_amount)))
        return line


class ETaxPanel(QWidget):
    """전자세금계산서 워커 패널."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._line_rows: list[_LineItemRow] = []
        self._seq_counter = 1
        self._builder = TaxInvoiceBuilder()
        self._build_ui()

    def _build_ui(self) -> None:
        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(splitter)

        # ── 왼쪽 폼 (스크롤) ─────────────────────────────────────────────────
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setMinimumWidth(460)
        left_scroll.setMaximumWidth(600)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)
        left_scroll.setWidget(left)

        # 제목
        title = QLabel("🧾 전자세금계산서 워커 — KEC v3.0")
        title.setFont(QFont("Pretendard", 13, QFont.Bold))
        lv.addWidget(title)

        # 문서 기본 정보
        doc_box = QGroupBox("문서 정보")
        doc_form = QFormLayout(doc_box)
        self._type_combo    = QComboBox()
        self._purpose_combo = QComboBox()
        self._issue_date    = QDateEdit(date.today())
        self._issue_date.setCalendarPopup(True)
        self._issue_date.setDisplayFormat("yyyy-MM-dd")

        for code, label in _TYPE_LABELS.items():
            self._type_combo.addItem(label, code)
        for code, label in _PURPOSE_LABELS.items():
            self._purpose_combo.addItem(label, code)

        doc_form.addRow("문서 유형",  self._type_combo)
        doc_form.addRow("영수/청구",  self._purpose_combo)
        doc_form.addRow("작성일자",   self._issue_date)
        lv.addWidget(doc_box)

        # 공급자 / 공급받는자
        self._invoicer_form = _PartyForm(
            "공급자 (Invoicer)",
            default_brn="1018112341",   # 테스트용 — 체크섬 통과
            default_name="주식회사 도메인파트너",
        )
        self._invoicee_form = _PartyForm(
            "공급받는자 (Invoicee)",
            default_brn="2208154526",   # 테스트용 — 체크섬 통과
            default_name="주식회사 고객사",
        )
        lv.addWidget(self._invoicer_form)
        lv.addWidget(self._invoicee_form)

        # 품목 라인
        lines_box = QGroupBox("품목 (최대 99개)")
        lines_vbox = QVBoxLayout(lines_box)
        self._lines_scroll = QScrollArea()
        self._lines_scroll.setWidgetResizable(True)
        self._lines_scroll.setMinimumHeight(80)
        self._lines_scroll.setMaximumHeight(200)
        self._lines_container = QWidget()
        self._lines_vbox = QVBoxLayout(self._lines_container)
        self._lines_vbox.setAlignment(Qt.AlignTop)
        self._lines_vbox.setSpacing(2)
        self._lines_scroll.setWidget(self._lines_container)
        lines_vbox.addWidget(self._lines_scroll)

        add_btn = QPushButton("+ 품목 추가")
        add_btn.clicked.connect(self._add_line)
        lines_vbox.addWidget(add_btn)
        lv.addWidget(lines_box)

        # 기본 품목 1개
        self._add_default_line()

        # 비고
        note_box = QGroupBox("비고")
        note_vbox = QVBoxLayout(note_box)
        self._note_edit = QLineEdit()
        self._note_edit.setPlaceholderText("비고 (선택)")
        note_vbox.addWidget(self._note_edit)
        lv.addWidget(note_box)

        # 실행 버튼
        run_btn = QPushButton("▶  XML 생성 + 검증")
        run_btn.setMinimumHeight(40)
        run_btn.setFont(QFont("Pretendard", 11, QFont.Bold))
        run_btn.clicked.connect(self._run)
        lv.addWidget(run_btn)
        lv.addStretch()

        splitter.addWidget(left_scroll)

        # ── 오른쪽: 결과 ─────────────────────────────────────────────────────
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 8, 8, 8)

        # 검증 결과
        val_box = QGroupBox("검증 결과")
        val_vbox = QVBoxLayout(val_box)
        self._val_text = QTextEdit()
        self._val_text.setReadOnly(True)
        self._val_text.setFixedHeight(100)
        self._val_text.setFont(QFont("Consolas", 10))
        val_vbox.addWidget(self._val_text)
        rv.addWidget(val_box)

        # XML 미리보기
        xml_box = QGroupBox("생성된 XML (KEC v3.0)")
        xml_vbox = QVBoxLayout(xml_box)
        self._xml_text = QTextEdit()
        self._xml_text.setReadOnly(True)
        self._xml_text.setFont(QFont("Consolas", 9))
        xml_vbox.addWidget(self._xml_text)

        copy_btn = QPushButton("클립보드 복사")
        copy_btn.clicked.connect(self._copy_xml)
        xml_vbox.addWidget(copy_btn)
        rv.addWidget(xml_box)

        splitter.addWidget(right)
        splitter.setSizes([520, 760])

    # ── 품목 관리 ──────────────────────────────────────────────────────────────

    def _add_default_line(self) -> None:
        row = _LineItemRow(self._seq_counter, date.today())
        row.name_edit.setText("서버 1대")
        row.price_edit.setText("10000000")
        self._lines_vbox.addWidget(row)
        self._line_rows.append(row)
        self._seq_counter += 1

    def _add_line(self) -> None:
        row = _LineItemRow(self._seq_counter, self._issue_date.date().toPython())
        self._lines_vbox.addWidget(row)
        self._line_rows.append(row)
        self._seq_counter += 1

    # ── 실행 ──────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            invoice = self._build_invoice()
        except Exception as e:
            QMessageBox.warning(self, "입력 오류", str(e))
            return

        errors = validate_invoice(invoice)
        if errors:
            self._val_text.setPlainText("❌ 검증 오류:\n" + "\n".join(f"  • {e}" for e in errors))
        else:
            self._val_text.setPlainText(
                f"✅ 검증 통과\n"
                f"  승인번호: {invoice.issue_id}\n"
                f"  공급가액: {int(invoice.total_supply):,}원\n"
                f"  세액:     {int(invoice.total_tax):,}원\n"
                f"  합계:     {int(invoice.grand_total):,}원"
            )

        xml_str = self._builder.build(invoice)
        self._xml_text.setPlainText(xml_str)

    def _build_invoice(self) -> TaxInvoice:
        type_code    = TaxInvoiceTypeCode(self._type_combo.currentData())
        purpose_code = PurposeCode(self._purpose_combo.currentData())
        issue_date   = self._issue_date.date().toPython()

        lines = [row.to_line(type_code) for row in self._line_rows if self._line_rows]
        if not lines:
            raise ValueError("품목을 1개 이상 입력하세요.")

        inv = TaxInvoice(
            type_code=type_code,
            purpose_code=purpose_code,
            issue_date=issue_date,
            invoicer=self._invoicer_form.to_party(),
            invoicee=self._invoicee_form.to_party(),
            lines=lines,
            note=self._note_edit.text(),
        )
        inv.recalc_totals()
        inv.issue_id = generate_issue_id(inv.invoicer.brn, issue_date)
        return inv

    def _copy_xml(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._xml_text.toPlainText())
