"""🔍 재무 부정탐지 패널 — Benford's Law + 패턴 룰 엔진."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import Decimal

from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget, QSpinBox,
)

from core.fraud import FraudDetectionEngine, FraudReport, RiskLevel, Transaction
from core.fraud.benford import BENFORD_EXPECTED

_RISK_COLORS = {
    RiskLevel.LOW:      "#4CAF50",
    RiskLevel.MEDIUM:   "#FF9800",
    RiskLevel.HIGH:     "#F44336",
    RiskLevel.CRITICAL: "#9C27B0",
}


# ── 백그라운드 분석 워커 ──────────────────────────────────────────────────────

class _AnalysisWorker(QThread):
    finished = Signal(object)   # FraudReport

    def __init__(self, txns: list[Transaction]) -> None:
        super().__init__()
        self._txns = txns

    def run(self) -> None:
        engine = FraudDetectionEngine()
        report = engine.analyze(self._txns)
        self.finished.emit(report)


# ── 벤포드 차트 ──────────────────────────────────────────────────────────────

class _BenfordChart(QChartView):
    def __init__(self, parent=None) -> None:
        chart = QChart()
        chart.setTitle("첫째 자리 분포 — 관측 vs 벤포드 기댓값")
        chart.setAnimationOptions(QChart.SeriesAnimations)
        super().__init__(chart, parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setMinimumHeight(220)

    def update_data(self, amounts: list[Decimal]) -> None:
        from collections import Counter
        from core.fraud.benford import _first_digit

        self.chart().removeAllSeries()
        for axis in self.chart().axes():
            self.chart().removeAxis(axis)

        digits_raw = [_first_digit(a) for a in amounts]
        digits = [d for d in digits_raw if d is not None]
        n = len(digits)
        if n == 0:
            return

        counter = Counter(digits)
        obs_set = QBarSet("관측값 (%)")
        exp_set = QBarSet("벤포드 (%)")
        obs_set.setColor(QColor("#26C6DA"))
        exp_set.setColor(QColor("#FF8A65"))

        for d in range(1, 10):
            obs_set.append(round(counter.get(d, 0) / n * 100, 1))
            exp_set.append(round(BENFORD_EXPECTED[d] * 100, 1))

        series = QBarSeries()
        series.append(obs_set)
        series.append(exp_set)
        self.chart().addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append([str(d) for d in range(1, 10)])
        self.chart().addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)

        from PySide6.QtCharts import QValueAxis
        axis_y = QValueAxis()
        axis_y.setRange(0, 35)
        axis_y.setTitleText("%")
        self.chart().addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_y)

        self.chart().legend().setVisible(True)


# ── 경보 테이블 ──────────────────────────────────────────────────────────────

class _AlertTable(QTableWidget):
    _HEADERS = ["위험도", "플래그", "건수", "점수", "설명"]

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(self._HEADERS), parent)
        self.setHorizontalHeaderLabels(self._HEADERS)
        self.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)

    def load_report(self, report: FraudReport) -> None:
        self.setRowCount(0)
        for alert in report.alerts:
            row = self.rowCount()
            self.insertRow(row)
            risk_item = QTableWidgetItem(alert.risk_level.value.upper())
            color = _RISK_COLORS.get(alert.risk_level, "#ffffff")
            risk_item.setForeground(QColor(color))
            font = QFont(); font.setBold(True)
            risk_item.setFont(font)
            self.setItem(row, 0, risk_item)
            self.setItem(row, 1, QTableWidgetItem(alert.flag.value))
            self.setItem(row, 2, QTableWidgetItem(str(len(alert.txn_ids))))
            score_item = QTableWidgetItem(f"{alert.score:.2f}")
            score_item.setTextAlignment(Qt.AlignCenter)
            self.setItem(row, 3, score_item)
            self.setItem(row, 4, QTableWidgetItem(alert.detail))


# ── 메인 패널 ────────────────────────────────────────────────────────────────

class FraudDetectorPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._txns: list[Transaction] = []
        self._worker: _AnalysisWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # 제목
        title = QLabel("🔍 재무 부정탐지 — Benford's Law + 패턴 룰")
        title.setFont(QFont("Pretendard", 13, QFont.Bold))
        root.addWidget(title)

        # 컨트롤 바
        ctrl = QHBoxLayout()
        self._n_spin = QSpinBox()
        self._n_spin.setRange(20, 2000)
        self._n_spin.setValue(200)
        self._n_spin.setSuffix(" 건")
        ctrl.addWidget(QLabel("샘플 건수:"))
        ctrl.addWidget(self._n_spin)

        gen_btn = QPushButton("🎲 샘플 데이터 생성")
        gen_btn.clicked.connect(self._generate_sample)
        ctrl.addWidget(gen_btn)

        run_btn = QPushButton("▶  부정 탐지 실행")
        run_btn.setFont(QFont("Pretendard", 10, QFont.Bold))
        run_btn.clicked.connect(self._run_analysis)
        ctrl.addWidget(run_btn)

        self._status_label = QLabel("데이터 없음")
        ctrl.addWidget(self._status_label)
        ctrl.addStretch()
        root.addLayout(ctrl)

        # 결과 영역 (좌: 차트+요약 / 우: 경보 테이블)
        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 4, 0)

        self._benford_chart = _BenfordChart()
        lv.addWidget(self._benford_chart)

        summary_box = QGroupBox("분석 요약")
        sv = QVBoxLayout(summary_box)
        self._summary_text = QTextEdit()
        self._summary_text.setReadOnly(True)
        self._summary_text.setFont(QFont("Consolas", 10))
        self._summary_text.setFixedHeight(130)
        sv.addWidget(self._summary_text)
        lv.addWidget(summary_box)

        splitter.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)

        alert_box = QGroupBox("경보 목록")
        av = QVBoxLayout(alert_box)
        self._alert_table = _AlertTable()
        av.addWidget(self._alert_table)
        rv.addWidget(alert_box)

        splitter.addWidget(right)
        splitter.setSizes([600, 680])
        root.addWidget(splitter)

    # ── 샘플 데이터 생성 ────────────────────────────────────────────────────────

    def _generate_sample(self) -> None:
        n = self._n_spin.value()
        rng = random.Random(42)
        base_dt = datetime(2025, 1, 1, 9, 0)
        txns: list[Transaction] = []
        vendors = ["V001", "V002", "V003", "V004", "V005"]
        posters = ["user_a", "user_b", "user_c"]

        for i in range(n):
            # 자연스러운 금액 (벤포드 준수)
            amount = Decimal(str(round(rng.lognormvariate(13, 1.5) / 100) * 100))
            amount = max(Decimal("1000"), amount)

            # 10%는 조작된 라운드 넘버 삽입
            if rng.random() < 0.10:
                amount = Decimal(str(rng.choice([500000, 1000000, 3000000, 5000000])))

            # 5%는 한도 직하 금액
            if rng.random() < 0.05:
                threshold = rng.choice([1000000, 5000000, 10000000])
                amount = Decimal(str(threshold - rng.randint(1000, 50000)))

            dt_offset = timedelta(
                days=rng.randint(0, 89),
                hours=rng.randint(0, 23),
                minutes=rng.randint(0, 59),
            )
            txns.append(Transaction(
                txn_id=f"TXN{i+1:04d}",
                txn_datetime=base_dt + dt_offset,
                amount=amount,
                vendor_id=rng.choice(vendors),
                posted_by=rng.choice(posters),
                description=f"거래 {i+1}",
            ))

        # 중복 거래 3쌍 인위적 삽입
        for j in range(3):
            dup_base = txns[j * 20]
            txns.append(Transaction(
                txn_id=f"DUP{j+1:03d}",
                txn_datetime=dup_base.txn_datetime + timedelta(hours=rng.randint(1, 48)),
                amount=dup_base.amount,
                vendor_id=dup_base.vendor_id,
                posted_by=dup_base.posted_by,
                description="중복 거래",
            ))

        self._txns = txns
        self._status_label.setText(f"샘플 {len(txns)}건 로드 완료")
        self._benford_chart.update_data([t.amount for t in txns])

    # ── 분석 실행 ───────────────────────────────────────────────────────────────

    def _run_analysis(self) -> None:
        if not self._txns:
            self._generate_sample()
        if self._worker and self._worker.isRunning():
            return
        self._status_label.setText("분석 중 …")
        self._worker = _AnalysisWorker(self._txns)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _on_done(self, report: FraudReport) -> None:
        color = _RISK_COLORS.get(report.overall_risk, "#ffffff")
        self._status_label.setText(
            f"<span style='color:{color};font-weight:bold'>"
            f"위험: {report.overall_risk.value.upper()}</span>"
        )
        self._status_label.setTextFormat(Qt.RichText)
        self._summary_text.setPlainText(report.summary)
        self._alert_table.load_report(report)
        if self._txns:
            self._benford_chart.update_data([t.amount for t in self._txns])
