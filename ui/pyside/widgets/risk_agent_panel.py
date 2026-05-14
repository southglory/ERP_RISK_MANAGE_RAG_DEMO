"""🤖 리스크 탐지 에이전트 패널 — Phase 6A 멀티 에이전트 결과 표시.

core/agents/risk_graph.run_risk_detect() 를 백그라운드 스레드에서 실행하고
fraud + tax + RAG 통합 리포트를 표시한다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

_RISK_COLORS = {
    "low":      "#4CAF50",
    "medium":   "#FF9800",
    "high":     "#F44336",
    "critical": "#9C27B0",
}

_RISK_LABELS = {
    "low": "정상",
    "medium": "주의",
    "high": "경고",
    "critical": "위험",
}


# ── 백그라운드 워커 ───────────────────────────────────────────────────────────

class _AgentWorker(QThread):
    finished = Signal(dict)
    error    = Signal(str)

    def __init__(self, txn_dicts: list[dict], skip_rag: bool) -> None:
        super().__init__()
        self._txn_dicts = txn_dicts
        self._skip_rag  = skip_rag

    def run(self) -> None:
        import warnings
        warnings.filterwarnings("ignore")
        try:
            from core.agents.risk_graph import run_risk_detect
            result = run_risk_detect(self._txn_dicts, skip_rag=self._skip_rag)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# ── 경보 테이블 ───────────────────────────────────────────────────────────────

class _TopAlertTable(QTableWidget):
    _HEADERS = ["위험도", "플래그", "점수", "거래 ID", "설명"]

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(self._HEADERS), parent)
        self.setHorizontalHeaderLabels(self._HEADERS)
        self.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setMinimumHeight(200)

    def load_alerts(self, alerts: list[dict]) -> None:
        self.setRowCount(0)
        for a in alerts:
            row = self.rowCount()
            self.insertRow(row)

            risk = a.get("risk_level", "?")
            color = _RISK_COLORS.get(risk, "#ffffff")
            risk_item = QTableWidgetItem(risk.upper())
            risk_item.setForeground(QColor(color))
            font = QFont(); font.setBold(True)
            risk_item.setFont(font)
            self.setItem(row, 0, risk_item)

            self.setItem(row, 1, QTableWidgetItem(a.get("flag", "")))

            score = a.get("score", 0.0)
            score_item = QTableWidgetItem(f"{score:.2f}")
            score_item.setTextAlignment(Qt.AlignCenter)
            self.setItem(row, 2, score_item)

            txn_ids = ", ".join(a.get("txn_ids", [])[:4])
            self.setItem(row, 3, QTableWidgetItem(txn_ids))

            self.setItem(row, 4, QTableWidgetItem(a.get("detail", "")[:80]))


# ── 메인 패널 ────────────────────────────────────────────────────────────────

class RiskAgentPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker: _AgentWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── 제목 ──────────────────────────────────────────────────────────────
        title = QLabel("🤖 리스크 탐지 에이전트 — Phase 6A")
        title.setFont(QFont("Pretendard", 13, QFont.Bold))
        root.addWidget(title)

        # ── 컨트롤 바 ─────────────────────────────────────────────────────────
        ctrl = QHBoxLayout()

        self._rag_chk = QCheckBox("RAG 법령 검색 포함 (vLLM + infinity-emb 필요)")
        self._rag_chk.setChecked(False)
        ctrl.addWidget(self._rag_chk)

        self._fixture_chk = QCheckBox("ERP 픽스처 사용 (기본: 18건 샘플)")
        self._fixture_chk.setChecked(True)
        ctrl.addWidget(self._fixture_chk)

        ctrl.addStretch()

        run_btn = QPushButton("▶  탐지 실행")
        run_btn.setFont(QFont("Pretendard", 10, QFont.Bold))
        run_btn.setMinimumWidth(120)
        run_btn.clicked.connect(self._run)
        ctrl.addWidget(run_btn)

        root.addLayout(ctrl)

        # ── 전체 리스크 배너 ──────────────────────────────────────────────────
        self._risk_banner = QLabel("탐지 결과 없음")
        self._risk_banner.setAlignment(Qt.AlignCenter)
        self._risk_banner.setFont(QFont("Pretendard", 14, QFont.Bold))
        self._risk_banner.setFixedHeight(42)
        self._risk_banner.setStyleSheet(
            "border-radius: 6px; background: #37474F; color: #B0BEC5; padding: 4px;"
        )
        root.addWidget(self._risk_banner)

        # ── 메인 스플리터 (좌: 리포트 / 우: 경보 테이블) ──────────────────────
        splitter = QSplitter(Qt.Horizontal)

        # 좌: 리포트 텍스트
        left = QGroupBox("통합 리스크 리포트")
        lv = QVBoxLayout(left)
        self._report_text = QTextEdit()
        self._report_text.setReadOnly(True)
        self._report_text.setFont(QFont("Consolas", 10))
        lv.addWidget(self._report_text)
        splitter.addWidget(left)

        # 우: 경보 + RAG 컨텍스트
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)
        rv.setSpacing(6)

        alert_box = QGroupBox("상위 경보 (fraud + 세무)")
        av = QVBoxLayout(alert_box)
        self._alert_table = _TopAlertTable()
        av.addWidget(self._alert_table)
        rv.addWidget(alert_box)

        rag_box = QGroupBox("검색된 법령 컨텍스트")
        gv = QVBoxLayout(rag_box)
        self._rag_text = QTextEdit()
        self._rag_text.setReadOnly(True)
        self._rag_text.setFont(QFont("Consolas", 9))
        self._rag_text.setPlaceholderText("RAG 활성화 시 관련 법령이 여기 표시됩니다.")
        self._rag_text.setMaximumHeight(160)
        gv.addWidget(self._rag_text)
        rv.addWidget(rag_box)

        splitter.addWidget(right)
        splitter.setSizes([580, 680])
        root.addWidget(splitter)

    # ── 실행 ─────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        if self._worker and self._worker.isRunning():
            return

        if self._fixture_chk.isChecked():
            from data.fixtures.erp_transactions import SAMPLE_TRANSACTIONS
            txn_dicts = [t.model_dump(mode="json") for t in SAMPLE_TRANSACTIONS]
        else:
            txn_dicts = self._make_random_txns(50)

        skip_rag = not self._rag_chk.isChecked()

        self._risk_banner.setText("분석 중 …")
        self._risk_banner.setStyleSheet(
            "border-radius: 6px; background: #37474F; color: #B0BEC5; padding: 4px;"
        )
        self._report_text.clear()
        self._rag_text.clear()
        self._alert_table.setRowCount(0)

        self._worker = _AgentWorker(txn_dicts, skip_rag=skip_rag)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_done(self, result: dict) -> None:
        overall = result.get("overall_risk", "low")
        color   = _RISK_COLORS.get(overall, "#ffffff")
        label   = _RISK_LABELS.get(overall, overall)
        n_txns  = len(result.get("transactions", []))
        needs_review = result.get("needs_human_review", False)

        review_str = "  ⚠ 인간 검토 필요" if needs_review else ""
        self._risk_banner.setText(
            f"통합 리스크: {overall.upper()} — {label}  |  {n_txns}건 분석{review_str}"
        )
        self._risk_banner.setStyleSheet(
            f"border-radius: 6px; background: {color}22; "
            f"color: {color}; border: 1px solid {color}; padding: 4px;"
        )

        self._report_text.setPlainText(result.get("risk_report", ""))
        self._alert_table.load_alerts(result.get("top_alerts", []))

        rag_ctx = result.get("rag_context", "")
        if rag_ctx and not rag_ctx.startswith("(RAG"):
            self._rag_text.setPlainText(rag_ctx[:1200])
        else:
            self._rag_text.setPlainText(rag_ctx or "(RAG 비활성)")

    def _on_error(self, msg: str) -> None:
        self._risk_banner.setText(f"오류: {msg[:80]}")
        self._risk_banner.setStyleSheet(
            "border-radius: 6px; background: #37474F; color: #F44336; padding: 4px;"
        )

    # ── 랜덤 샘플 생성 (픽스처 비활성 시) ─────────────────────────────────────

    @staticmethod
    def _make_random_txns(n: int) -> list[dict]:
        import random
        from datetime import datetime, timedelta
        from decimal import Decimal
        rng = random.Random(0)
        base = datetime(2026, 4, 1, 9, 0)
        rows = []
        for i in range(n):
            amt = Decimal(str(round(rng.lognormvariate(13, 1.5) / 100) * 100))
            rows.append({
                "txn_id": f"R{i+1:03d}",
                "txn_datetime": (base + timedelta(days=rng.randint(0, 29),
                                                  hours=rng.randint(0, 23))).isoformat(),
                "amount": str(max(Decimal("1000"), amt)),
                "vendor_id": rng.choice(["V-A", "V-B", "V-C"]),
                "account_code": "5100",
                "posted_by": rng.choice(["user_a", "user_b"]),
                "description": f"거래 {i+1}",
                "approver": "",
            })
        return rows
