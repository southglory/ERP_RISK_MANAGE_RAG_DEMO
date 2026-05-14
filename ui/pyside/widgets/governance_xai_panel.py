"""거버넌스 / XAI 패널 — 감사 로그 · AI 판단 근거 · 리스크 스코어카드 · 감사 워크플로우 · 검토 큐."""

from __future__ import annotations

import asyncio
import csv
import io
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
import random

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QProgressBar, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)


# ── 샘플 감사 로그 데이터 ──────────────────────────────────────────────────────

_MODULES = [
    "거래 시뮬레이터", "분개 자동생성", "세금계산서 워커",
    "재무 부정 탐지", "세무 리스크 RAG", "계약·판례 RAG",
]

_ACTIONS = {
    "거래 시뮬레이터":    ["hw_spot 시뮬레이션 실행", "saas_annual 시뮬레이션 실행", "advance_delivery 시뮬레이션 실행"],
    "분개 자동생성":      ["계약 평가 실행", "K-IFRS 1115 5단계 완료", "분개 생성 완료"],
    "세금계산서 워커":    ["XML 생성", "사업자번호 검증 통과", "클립보드 복사"],
    "재무 부정 탐지":     ["분석 실행", "Benford 법칙 이탈 탐지 (HIGH)", "라운드 넘버 경보 (MEDIUM)"],
    "세무 리스크 RAG":    ["쿼리 실행", "pgvector 검색 완료 (5 chunks)", "Solar LLM 응답 완료"],
    "계약·판례 RAG":      ["계약서 쿼리", "판례 검색 완료 (3 chunks)", "스트리밍 응답 완료"],
}

_USERS = ["admin", "user01", "user02", "auditor"]


def _gen_audit_log(n: int = 60) -> list[dict]:
    base = datetime(2026, 4, 1, 9, 0, 0)
    rows = []
    for i in range(n):
        mod = random.choice(_MODULES)
        rows.append({
            "timestamp": (base + timedelta(minutes=i * 17 + random.randint(0, 15))).strftime("%Y-%m-%d %H:%M:%S"),
            "user":      random.choice(_USERS),
            "module":    mod,
            "action":    random.choice(_ACTIONS[mod]),
            "status":    random.choices(["SUCCESS", "SUCCESS", "SUCCESS", "WARNING", "ERROR"],
                                         weights=[60, 60, 60, 15, 5])[0],
            "latency_ms": random.randint(12, 3500),
        })
    return rows


# ── XAI 결정 근거 샘플 텍스트 ─────────────────────────────────────────────────

_XAI_SAMPLES = {
    "K-IFRS 1115 분개 결정": """\
[AI 판단 근거] K-IFRS 1115 5단계 평가 결과

■ Step 1 — 계약 식별 ✅
  근거: 5요건 충족 (상업적 실질 O, 서명 O, 대가 식별 O, 권리 O, 지급 조건 O)

■ Step 2 — 수행의무 ✅ 단일 의무
  근거: HW + 설치가 결합 성과물(Bundle)로 분리 불가 → 단일 PO

■ Step 3 — 거래가격 ₩ 10,000,000
  근거: 계약서 고정 가격, 변동 대가 없음

■ Step 4 — SSP 배분 N/A (단일 PO)
  근거: PO가 1개이므로 배분 불필요

■ Step 5 — 수익 인식 시점: 인도 시점
  근거: 고객이 자산 통제권 획득 시점(출고일) = K-IFRS 1115.38(a)
  journal_trigger = "point_sale"

→ 생성된 분개: sale_credit + sale_cogs (일시점 인식)
""",
    "재무 부정 탐지 경보": """\
[AI 판단 근거] 재무 부정 탐지 엔진 분석 결과

■ Benford's Law 검사 (χ² = 24.3, 임계값 20.09)  → CRITICAL
  1자리 숫자 분포: 1=18.2%, 2=11.4%, 5=22.8% (기댓값 7.9% 대비 2.9배)
  5로 시작하는 금액 과다 → 단수 조작 의심

■ 라운드 넘버 패턴 (비율 54%)  → HIGH
  전체 거래의 54%가 1,000원 단위 정수 → 정상 분포 대비 비정상적 높음
  대응 COSO: Control Environment — 결재 한도 설정 검토 권고

■ 한도 직하 군집 검사  → MEDIUM
  500만원 결재 한도 하단(475~500만원) 구간에 17건 집중
  평균 487.3만원 → 결재 우회 목적 분할 거래 의심

→ 감사 담당자 에스컬레이션 권고: 2026-04-15까지 소명 자료 요청
""",
    "세무 리스크 RAG 근거": """\
[AI 판단 근거] 세무 리스크 RAG 응답 추적

■ 질의: "SaaS 구독료 세금계산서 발급 시점"

■ 검색된 참고 문서 (Top-3 chunks, rerank 적용)
  [1] 부가가치세법 제15조 — 재화 또는 용역 공급 시기 (score: 0.941)
      "용역의 공급이 계속되는 경우 역무의 제공이 완료되는 때"
  [2] 국세청 예규 2022-46호 — SaaS 구독 서비스 공급 시기 (score: 0.887)
      "월정액 SaaS는 매월 말일을 공급 시기로 본다"
  [3] 부가가치세법 시행령 제28조 (score: 0.823)
      "계속적 공급 역무의 공급 시기 특례"

■ Solar LLM 추론 체인
  근거 문서 → 월말 공급 시기 적용 → 월 단위 세금계산서 발급 결론
  Langfuse Trace ID: tr_abc12345 (응답 시간 1,247ms)

→ 결론: 매월 말일에 세금계산서 발급, 연간 선수금은 공급 시기 아님
""",
}


# ── 리스크 스코어카드 데이터 ───────────────────────────────────────────────────

_SCORECARD = [
    ("분개 자동생성",      "K-IFRS 1115",       "COMPLIANT", "마지막 평가: 2026-05-07"),
    ("세금계산서 워커",    "KEC v3.0 검증",     "PASS",      "사업자번호 체크섬 OK"),
    ("재무 부정 탐지",     "Benford 법칙",      "HIGH",      "χ²=24.3 > 20.09 임계값"),
    ("재무 부정 탐지",     "라운드 넘버 패턴",  "HIGH",      "비율 54% (기준 40%)"),
    ("재무 부정 탐지",     "한도 직하 군집",    "MEDIUM",    "17건 집중 (창구 ±5%)"),
    ("재무 부정 탐지",     "거래 속도",         "LOW",       "정상 범위 내"),
    ("세무 리스크 RAG",    "서비스 연결",       "OFFLINE",   "vLLM/pgvector 미연결"),
    ("계약·판례 RAG",      "서비스 연결",       "OFFLINE",   "vLLM/pgvector 미연결"),
]

_RISK_COLORS = {
    "COMPLIANT": QColor("#1e8449"),
    "PASS":      QColor("#1e8449"),
    "LOW":       QColor("#1a5276"),
    "MEDIUM":    QColor("#b7770d"),
    "HIGH":      QColor("#922b21"),
    "CRITICAL":  QColor("#7b241c"),
    "OFFLINE":   QColor("#4a4a4a"),
}


@dataclass
class _ReviewItem:
    """검토 큐에 쌓이는 케이스 항목."""
    item_id:    str
    timestamp:  str
    question:   str
    case_type:  str
    reason:     str
    answer:     str
    rationale:  str
    status:     str = "대기"        # 대기 | 승인 | 반려
    comment:    str = ""


class GovernanceXAIPanel(QWidget):
    """거버넌스 / XAI 패널 — 감사 로그, AI 판단 근거, 리스크 스코어카드."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._audit_data  = _gen_audit_log()
        self._review_queue: list[_ReviewItem] = []
        self._build_ui()

    # ── UI 빌드 ───────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        title = QLabel("🔗 거버넌스 / XAI — 감사 추적 · AI 판단 근거")
        title.setFont(QFont("Pretendard", 13, QFont.Bold))
        root.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._build_lineage_tab(),    "🧾 Lineage (실데이터)")
        tabs.addTab(self._build_audit_tab(),      "📋 감사 로그")
        tabs.addTab(self._build_xai_tab(),        "🧠 AI 판단 근거")
        tabs.addTab(self._build_scorecard_tab(),  "🎯 리스크 스코어카드")
        tabs.addTab(self._build_workflow_tab(),   "⚙️ 감사 워크플로우")
        tabs.addTab(self._build_review_tab(),     "👤 검토 큐")
        self._tabs = tabs
        root.addWidget(tabs)

    # ── 탭 1: 감사 로그 ───────────────────────────────────────────────────────

    def _build_audit_tab(self) -> QWidget:
        w = QWidget()
        vbox = QVBoxLayout(w)

        # 필터 행
        filter_row = QHBoxLayout()
        self._audit_mod_combo = QComboBox()
        self._audit_mod_combo.addItem("전체 모듈")
        for m in _MODULES:
            self._audit_mod_combo.addItem(m)
        self._audit_status_combo = QComboBox()
        for s in ["전체 상태", "SUCCESS", "WARNING", "ERROR"]:
            self._audit_status_combo.addItem(s)
        self._audit_search = QLineEdit()
        self._audit_search.setPlaceholderText("액션 검색…")
        export_btn = QPushButton("CSV 내보내기")
        export_btn.clicked.connect(self._export_audit_csv)

        filter_row.addWidget(QLabel("모듈:"))
        filter_row.addWidget(self._audit_mod_combo)
        filter_row.addWidget(QLabel("상태:"))
        filter_row.addWidget(self._audit_status_combo)
        filter_row.addWidget(self._audit_search, 1)
        filter_row.addWidget(export_btn)
        vbox.addLayout(filter_row)

        # 테이블
        self._audit_table = QTableWidget(0, 6)
        self._audit_table.setHorizontalHeaderLabels(
            ["타임스탬프", "사용자", "모듈", "액션", "상태", "응답시간(ms)"]
        )
        hh = self._audit_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self._audit_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._audit_table.setAlternatingRowColors(True)
        vbox.addWidget(self._audit_table)

        self._audit_count_label = QLabel("")
        self._audit_count_label.setFont(QFont("Consolas", 9))
        vbox.addWidget(self._audit_count_label)

        # 연결
        self._audit_mod_combo.currentIndexChanged.connect(self._refresh_audit)
        self._audit_status_combo.currentIndexChanged.connect(self._refresh_audit)
        self._audit_search.textChanged.connect(self._refresh_audit)
        self._refresh_audit()

        return w

    def _refresh_audit(self) -> None:
        mod_filter    = self._audit_mod_combo.currentText()
        status_filter = self._audit_status_combo.currentText()
        search        = self._audit_search.text().lower()

        rows = self._audit_data
        if mod_filter != "전체 모듈":
            rows = [r for r in rows if r["module"] == mod_filter]
        if status_filter != "전체 상태":
            rows = [r for r in rows if r["status"] == status_filter]
        if search:
            rows = [r for r in rows if search in r["action"].lower()]

        self._audit_table.setRowCount(0)
        _STATUS_COLOR = {
            "SUCCESS": QColor("#1e3a2f"),
            "WARNING": QColor("#3b2e0a"),
            "ERROR":   QColor("#3b0a0a"),
        }
        for i, r in enumerate(rows):
            self._audit_table.insertRow(i)
            bg = _STATUS_COLOR.get(r["status"], QColor("#1c2833"))
            for col, val in enumerate([
                r["timestamp"], r["user"], r["module"],
                r["action"], r["status"], str(r["latency_ms"]),
            ]):
                item = QTableWidgetItem(val)
                item.setBackground(bg)
                if col == 5:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._audit_table.setItem(i, col, item)

        self._audit_count_label.setText(f"표시: {len(rows)}건 / 전체: {len(self._audit_data)}건")

    def _export_audit_csv(self) -> None:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=["timestamp", "user", "module", "action", "status", "latency_ms"])
        writer.writeheader()
        writer.writerows(self._audit_data)
        QApplication.clipboard().setText(buf.getvalue())
        self._audit_count_label.setText("✅ CSV를 클립보드에 복사했습니다.")

    # ── 탭 2: AI 판단 근거 ───────────────────────────────────────────────────

    def _build_xai_tab(self) -> QWidget:
        w = QWidget()
        splitter = QSplitter(Qt.Horizontal, w)
        root = QHBoxLayout(w)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(splitter)

        # 왼쪽 — 사례 선택
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)
        lv.addWidget(QLabel("AI 결정 사례 선택"))

        self._xai_list = QTableWidget(len(_XAI_SAMPLES), 1)
        self._xai_list.setHorizontalHeaderLabels(["사례"])
        self._xai_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._xai_list.setEditTriggers(QTableWidget.NoEditTriggers)
        self._xai_list.setSelectionBehavior(QAbstractItemView.SelectRows)
        for i, key in enumerate(_XAI_SAMPLES):
            self._xai_list.setItem(i, 0, QTableWidgetItem(key))
        lv.addWidget(self._xai_list)
        splitter.addWidget(left)

        # 오른쪽 — 근거 텍스트
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 8, 8, 8)
        rv.addWidget(QLabel("AI 판단 근거 (Explainability)"))
        self._xai_text = QTextEdit()
        self._xai_text.setReadOnly(True)
        self._xai_text.setFont(QFont("Consolas", 10))
        rv.addWidget(self._xai_text)
        splitter.addWidget(right)

        splitter.setSizes([260, 740])
        self._xai_list.currentCellChanged.connect(self._on_xai_selected)
        self._xai_list.selectRow(0)

        return w

    def _on_xai_selected(self, row: int, *_) -> None:
        if row < 0:
            return
        key = self._xai_list.item(row, 0).text()
        self._xai_text.setPlainText(_XAI_SAMPLES.get(key, ""))

    # ── 탭 3: 리스크 스코어카드 ──────────────────────────────────────────────

    def _build_scorecard_tab(self) -> QWidget:
        w = QWidget()
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(8, 8, 8, 8)

        info = QLabel(
            "각 모듈의 현재 리스크 수준과 AI 준거를 한눈에 확인합니다.\n"
            "실제 운영 환경에서는 실시간 평가 결과가 반영됩니다."
        )
        info.setFont(QFont("Pretendard", 10))
        vbox.addWidget(info)

        table = QTableWidget(len(_SCORECARD), 4)
        table.setHorizontalHeaderLabels(["모듈", "점검 항목", "상태", "비고"])
        hh = table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)

        for i, (module, check, status, note) in enumerate(_SCORECARD):
            table.setItem(i, 0, QTableWidgetItem(module))
            table.setItem(i, 1, QTableWidgetItem(check))
            status_item = QTableWidgetItem(status)
            status_item.setBackground(_RISK_COLORS.get(status, QColor("#4a4a4a")))
            status_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 2, status_item)
            table.setItem(i, 3, QTableWidgetItem(note))

        vbox.addWidget(table)

        legend = QLabel(
            "범례:  COMPLIANT/PASS = 정상  |  LOW = 낮음  |  MEDIUM = 주의  |  HIGH = 경보  |  CRITICAL = 위험  |  OFFLINE = 미연결"
        )
        legend.setFont(QFont("Consolas", 8))
        vbox.addWidget(legend)
        vbox.addStretch()

        return w

    # ── 탭 4: 감사 워크플로우 ─────────────────────────────────────────────────

    _WF_SAMPLES = [
        "미국 법인에 지급한 SW 사용료(로열티)의 원천세율과 조세조약 적용 여부는?",
        "SaaS 구독 서비스의 K-IFRS 1115 수익인식 시점과 분개 방법은?",
        "분기말 밀어넣기 거래의 기간귀속 조작 탐지 방법은?",
        "하도급 계약 대금 지연 시 지연이자 기준과 지급보증 의무는?",
        "납부지연 가산세 계산 기준일과 요율은?",
    ]

    def _build_workflow_tab(self) -> QWidget:
        w = QWidget()
        root = QHBoxLayout(w)
        root.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        # ── 왼쪽: 입력 폼 ────────────────────────────────────────────────────
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)
        left.setMaximumWidth(400)

        lv.addWidget(QLabel("⚙️ LangGraph 7노드 감사 워크플로우"))

        q_box = QGroupBox("질문")
        qv = QVBoxLayout(q_box)
        self._wf_query = QTextEdit()
        self._wf_query.setFixedHeight(90)
        self._wf_query.setPlaceholderText(self._WF_SAMPLES[0])
        qv.addWidget(self._wf_query)

        ex_row = QHBoxLayout()
        for i, sq in enumerate(self._WF_SAMPLES, 1):
            btn = QPushButton(f"예{i}")
            btn.setFixedWidth(40)
            btn.setToolTip(sq)
            btn.clicked.connect(lambda _, q=sq: self._wf_query.setPlainText(q))
            ex_row.addWidget(btn)
        ex_row.addStretch()
        qv.addLayout(ex_row)
        lv.addWidget(q_box)

        self._wf_run_btn = QPushButton("▶  워크플로우 실행")
        self._wf_run_btn.setMinimumHeight(38)
        self._wf_run_btn.setFont(QFont("Pretendard", 11, QFont.Bold))
        self._wf_run_btn.clicked.connect(self._on_wf_run)
        lv.addWidget(self._wf_run_btn)

        # 노드 진행 상태
        steps_box = QGroupBox("노드 진행")
        sv = QVBoxLayout(steps_box)
        self._wf_steps = QLabel(
            "intake  ○\n"
            "classify  ○\n"
            "rule    ○\n"
            "rag     ○\n"
            "llm     ○\n"
            "xai     ○\n"
            "review  ○"
        )
        self._wf_steps.setFont(QFont("Consolas", 10))
        sv.addWidget(self._wf_steps)
        lv.addWidget(steps_box)
        lv.addStretch()
        splitter.addWidget(left)

        # ── 오른쪽: 결과 ─────────────────────────────────────────────────────
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 8, 8, 8)

        # 분류 + 룰 결과
        meta_box = QGroupBox("분류 / 룰 엔진")
        mv = QFormLayout(meta_box)
        self._wf_case_type  = QLabel("—")
        self._wf_rule_fired = QLabel("—")
        self._wf_rule_conf  = QLabel("—")
        self._wf_rule_out   = QLabel("—")
        self._wf_rule_out.setWordWrap(True)
        for label, widget in [
            ("케이스 유형", self._wf_case_type),
            ("룰 발동",    self._wf_rule_fired),
            ("룰 신뢰도",  self._wf_rule_conf),
            ("룰 출력",    self._wf_rule_out),
        ]:
            mv.addRow(label + ":", widget)
        rv.addWidget(meta_box)

        # LLM 답변
        ans_box = QGroupBox("LLM 답변")
        av = QVBoxLayout(ans_box)
        self._wf_answer = QTextEdit()
        self._wf_answer.setReadOnly(True)
        self._wf_answer.setFont(QFont("Pretendard", 11))
        self._wf_answer.setMinimumHeight(140)
        av.addWidget(self._wf_answer)
        rv.addWidget(ans_box)

        # XAI 가중치 — 바 차트
        xai_box = QGroupBox("XAI Attribution")
        xv = QVBoxLayout(xai_box)

        def _make_bar(color: str) -> QProgressBar:
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setMinimumHeight(22)
            bar.setTextVisible(True)
            bar.setFormat("%p%")
            bar.setStyleSheet(
                f"QProgressBar {{ border: 1px solid #555; border-radius: 4px; "
                f"background: #1c2833; text-align: center; color: white; }}"
                f"QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}"
            )
            return bar

        rule_row = QHBoxLayout()
        rule_row.addWidget(QLabel("룰 기여도"))
        self._wf_bar_rule = _make_bar("#1a5276")   # 파란색
        rule_row.addWidget(self._wf_bar_rule, 1)
        xv.addLayout(rule_row)

        llm_row = QHBoxLayout()
        llm_row.addWidget(QLabel("LLM 기여도"))
        self._wf_bar_llm = _make_bar("#145a32")    # 초록색
        llm_row.addWidget(self._wf_bar_llm, 1)
        xv.addLayout(llm_row)

        conf_row = QHBoxLayout()
        conf_row.addWidget(QLabel("룰 신뢰도"))
        self._wf_bar_conf = _make_bar("#7d6608")   # 노란색
        conf_row.addWidget(self._wf_bar_conf, 1)
        xv.addLayout(conf_row)

        conflict_form = QFormLayout()
        self._wf_conflict  = QLabel("—")
        self._wf_rationale = QLabel("—")
        self._wf_rationale.setWordWrap(True)
        conflict_form.addRow("결론 충돌:", self._wf_conflict)
        conflict_form.addRow("판단 근거:", self._wf_rationale)
        xv.addLayout(conflict_form)

        rv.addWidget(xai_box)

        # 검토 상태
        rev_box = QGroupBox("검토 라우팅")
        revv = QFormLayout(rev_box)
        self._wf_needs_review = QLabel("—")
        self._wf_review_reason = QLabel("—")
        self._wf_review_reason.setWordWrap(True)
        revv.addRow("사람 검토 필요:", self._wf_needs_review)
        revv.addRow("사유:",          self._wf_review_reason)
        rv.addWidget(rev_box)

        splitter.addWidget(right)
        splitter.setSizes([360, 900])
        return w

    # ── 워크플로우 이벤트 ─────────────────────────────────────────────────────

    def _on_wf_run(self) -> None:
        asyncio.ensure_future(self._async_wf_run())

    def _wf_set_steps(self, done: list[str]) -> None:
        node_names = ["intake", "classify", "rule", "rag", "llm", "xai", "review"]
        lines = []
        for n in node_names:
            marker = "✓" if n in done else "○"
            lines.append(f"{n:<8} {marker}")
        self._wf_steps.setText("\n".join(lines))

    async def _async_wf_run(self) -> None:
        q = self._wf_query.toPlainText().strip()
        if not q:
            self._wf_answer.setPlainText("질문을 입력하세요.")
            return

        self._wf_run_btn.setEnabled(False)
        self._wf_answer.setPlainText("처리 중…")
        self._wf_set_steps([])
        self._wf_bar_rule.setValue(0)
        self._wf_bar_llm.setValue(0)
        self._wf_bar_conf.setValue(0)
        self._wf_conflict.setText("—")
        self._wf_rationale.setText("—")

        # 초기 상태
        init_state = dict(
            question=q, trace_id=str(uuid.uuid4())[:8],
            validated=False, intake_error="",
            case_type="", rule_fired=False, rule_output={}, rule_confidence=0.0,
            retrieved_chunks=[], context="",
            answer="", llm_confidence=0.0,
            rule_weight=0.0, llm_weight=0.0, conflict_flag=False, rationale="",
            needs_human_review=False, review_reason="",
        )

        try:
            from core.audit.workflow import build_audit_workflow
            workflow = build_audit_workflow()
            result = await workflow.ainvoke(init_state)

            self._wf_set_steps(["intake", "classify", "rule", "rag", "llm", "xai", "review"])

            self._wf_case_type.setText(result.get("case_type", "—"))
            fired = result.get("rule_fired", False)
            self._wf_rule_fired.setText("예" if fired else "아니오")
            conf = result.get("rule_confidence", 0.0)
            self._wf_rule_conf.setText(f"{conf:.0%}")
            rule_out = result.get("rule_output", {})
            self._wf_rule_out.setText(
                "\n".join(f"{k}: {v}" for k, v in rule_out.items()) or "—"
            )

            self._wf_answer.setPlainText(result.get("answer", "—"))

            rule_w = result.get("rule_weight", 0.0)
            llm_w  = result.get("llm_weight", 0.0)
            rule_c = result.get("rule_confidence", 0.0)
            self._wf_bar_rule.setValue(int(rule_w * 100))
            self._wf_bar_llm.setValue(int(llm_w  * 100))
            self._wf_bar_conf.setValue(int(rule_c * 100))
            # 충돌 시 룰 바를 빨간색으로
            conflict = result.get("conflict_flag", False)
            if conflict:
                self._wf_bar_rule.setStyleSheet(
                    "QProgressBar { border:1px solid #555; border-radius:4px; "
                    "background:#1c2833; text-align:center; color:white; }"
                    "QProgressBar::chunk { background:#922b21; border-radius:3px; }"
                )
            else:
                self._wf_bar_rule.setStyleSheet(
                    "QProgressBar { border:1px solid #555; border-radius:4px; "
                    "background:#1c2833; text-align:center; color:white; }"
                    "QProgressBar::chunk { background:#1a5276; border-radius:3px; }"
                )
            self._wf_conflict.setText("경고 — 충돌 감지" if conflict else "정상")
            self._wf_rationale.setText(result.get("rationale", "—"))

            needs = result.get("needs_human_review", False)
            self._wf_needs_review.setText("예 — 검토 큐 이관" if needs else "아니오 — 자동 처리")
            self._wf_review_reason.setText(result.get("review_reason", "") or "—")

            # 검토 필요 시 큐에 자동 추가
            if needs:
                self._push_to_review_queue(result, q)

        except Exception as exc:
            self._wf_set_steps([])
            self._wf_answer.setPlainText(
                f"오류: {exc}\n\n"
                "서비스가 실행 중인지 확인하세요:\n"
                "  start_services.bat 실행 후 재시도"
            )
        finally:
            self._wf_run_btn.setEnabled(True)

    def _push_to_review_queue(self, result: dict, question: str) -> None:
        """워크플로우 결과를 검토 큐에 추가하고 탭 배지를 갱신한다."""
        item = _ReviewItem(
            item_id=result.get("trace_id", str(uuid.uuid4())[:8]),
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            question=question,
            case_type=result.get("case_type", "—"),
            reason=result.get("review_reason", ""),
            answer=result.get("answer", ""),
            rationale=result.get("rationale", ""),
        )
        self._review_queue.append(item)
        self._refresh_review_table()
        # 탭 5(검토 큐) 텍스트에 대기 건수 표시 (Lineage 탭 추가로 인덱스 +1)
        waiting = sum(1 for r in self._review_queue if r.status == "대기")
        self._tabs.setTabText(5, f"👤 검토 큐 ({waiting})")

    # ── 탭 5: 검토 큐 ─────────────────────────────────────────────────────────

    def _build_review_tab(self) -> QWidget:
        w = QWidget()
        root = QHBoxLayout(w)
        root.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        # ── 왼쪽: 큐 테이블 ──────────────────────────────────────────────────
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)

        lv.addWidget(QLabel("사람 검토가 필요한 감사 케이스 목록"))

        self._review_table = QTableWidget(0, 5)
        self._review_table.setHorizontalHeaderLabels(
            ["ID", "시각", "케이스 유형", "상태", "사유"]
        )
        hh = self._review_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        self._review_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._review_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._review_table.setAlternatingRowColors(True)
        self._review_table.currentCellChanged.connect(self._on_review_selected)
        lv.addWidget(self._review_table)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("완료 항목 제거")
        clear_btn.clicked.connect(self._clear_done_reviews)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        lv.addLayout(btn_row)
        splitter.addWidget(left)

        # ── 오른쪽: 상세 + 소명 입력 ─────────────────────────────────────────
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 8, 8, 8)

        detail_box = QGroupBox("케이스 상세")
        dv = QFormLayout(detail_box)
        self._rv_question = QLabel("—")
        self._rv_question.setWordWrap(True)
        self._rv_reason   = QLabel("—")
        self._rv_reason.setWordWrap(True)
        self._rv_rationale = QLabel("—")
        self._rv_rationale.setWordWrap(True)
        dv.addRow("질문:", self._rv_question)
        dv.addRow("검토 사유:", self._rv_reason)
        dv.addRow("판단 근거:", self._rv_rationale)
        rv.addWidget(detail_box)

        ans_box = QGroupBox("AI 답변")
        av = QVBoxLayout(ans_box)
        self._rv_answer = QTextEdit()
        self._rv_answer.setReadOnly(True)
        self._rv_answer.setFont(QFont("Pretendard", 10))
        self._rv_answer.setMinimumHeight(100)
        av.addWidget(self._rv_answer)
        rv.addWidget(ans_box)

        comment_box = QGroupBox("검토자 소명 / 코멘트")
        cv = QVBoxLayout(comment_box)
        self._rv_comment = QTextEdit()
        self._rv_comment.setFixedHeight(80)
        self._rv_comment.setPlaceholderText("검토 의견을 입력하세요…")
        cv.addWidget(self._rv_comment)

        action_row = QHBoxLayout()
        approve_btn = QPushButton("✓ 승인")
        approve_btn.setMinimumHeight(34)
        approve_btn.setStyleSheet("background:#1e8449; color:white; font-weight:bold;")
        approve_btn.clicked.connect(lambda: self._set_review_status("승인"))

        reject_btn  = QPushButton("✗ 반려")
        reject_btn.setMinimumHeight(34)
        reject_btn.setStyleSheet("background:#922b21; color:white; font-weight:bold;")
        reject_btn.clicked.connect(lambda: self._set_review_status("반려"))

        action_row.addWidget(approve_btn)
        action_row.addWidget(reject_btn)
        cv.addLayout(action_row)
        rv.addWidget(comment_box)
        rv.addStretch()

        splitter.addWidget(right)
        splitter.setSizes([460, 740])
        return w

    def _refresh_review_table(self) -> None:
        _STATUS_BG = {
            "대기": QColor("#3b2e0a"),
            "승인": QColor("#1e3a2f"),
            "반려": QColor("#3b0a0a"),
        }
        self._review_table.setRowCount(0)
        for i, item in enumerate(self._review_queue):
            self._review_table.insertRow(i)
            bg = _STATUS_BG.get(item.status, QColor("#1c2833"))
            for col, val in enumerate([
                item.item_id, item.timestamp, item.case_type,
                item.status, item.reason,
            ]):
                cell = QTableWidgetItem(val)
                cell.setBackground(bg)
                self._review_table.setItem(i, col, cell)

    def _on_review_selected(self, row: int, *_) -> None:
        if row < 0 or row >= len(self._review_queue):
            return
        item = self._review_queue[row]
        self._rv_question.setText(item.question)
        self._rv_reason.setText(item.reason)
        self._rv_rationale.setText(item.rationale)
        self._rv_answer.setPlainText(item.answer)
        self._rv_comment.setPlainText(item.comment)

    def _set_review_status(self, status: str) -> None:
        row = self._review_table.currentRow()
        if row < 0 or row >= len(self._review_queue):
            return
        item = self._review_queue[row]
        item.status  = status
        item.comment = self._rv_comment.toPlainText().strip()
        self._refresh_review_table()
        waiting = sum(1 for r in self._review_queue if r.status == "대기")
        self._tabs.setTabText(5, f"👤 검토 큐 ({waiting})" if waiting else "👤 검토 큐")

    def _clear_done_reviews(self) -> None:
        self._review_queue = [r for r in self._review_queue if r.status == "대기"]
        self._refresh_review_table()
        self._tabs.setTabText(5, f"👤 검토 큐 ({len(self._review_queue)})" if self._review_queue else "👤 검토 큐")

    # ══════════════════════════════════════════════════════════════════════════
    # 탭 0: Lineage (실데이터) — Phase 6E
    # ══════════════════════════════════════════════════════════════════════════

    def _build_lineage_tab(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)

        topbar = QHBoxLayout()
        refresh = QPushButton("🔄  최근 case 새로고침")
        refresh.clicked.connect(self._lineage_refresh_cases)
        topbar.addWidget(refresh)
        topbar.addStretch()
        self._lineage_status = QLabel("준비")
        topbar.addWidget(self._lineage_status)
        root.addLayout(topbar)

        splitter = QSplitter(Qt.Horizontal)

        self._lineage_case_list = QListWidget()
        self._lineage_case_list.setMinimumWidth(260)
        self._lineage_case_list.itemClicked.connect(self._lineage_on_case_clicked)
        splitter.addWidget(self._lineage_case_list)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 0, 0, 0)

        rv.addWidget(QLabel("결정 요약 (audit_case + answer)"))
        self._lineage_summary = QTextEdit()
        self._lineage_summary.setReadOnly(True)
        self._lineage_summary.setMaximumHeight(160)
        self._lineage_summary.setFont(QFont("Consolas", 9))
        rv.addWidget(self._lineage_summary)

        rv.addWidget(QLabel("발화한 룰 (rule_invocation, weight 내림차순)"))
        self._lineage_rules_tree = QTreeWidget()
        self._lineage_rules_tree.setHeaderLabels(["rule_set", "rule_id", "weight", "matched / output"])
        self._lineage_rules_tree.header().setSectionResizeMode(3, QHeaderView.Stretch)
        rv.addWidget(self._lineage_rules_tree)

        rv.addWidget(QLabel("관련 ERP 거래 (source_transaction)"))
        self._lineage_txn_table = QTableWidget(0, 4)
        self._lineage_txn_table.setHorizontalHeaderLabels(["거래 ID", "금액", "계정", "기여도"])
        self._lineage_txn_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._lineage_txn_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._lineage_txn_table.setMaximumHeight(180)
        rv.addWidget(self._lineage_txn_table)

        # Phase 6F — evidence_chunk 표
        rv.addWidget(QLabel("증거 청크 (evidence_chunk, rank)"))
        self._lineage_evidence_table = QTableWidget(0, 5)
        self._lineage_evidence_table.setHorizontalHeaderLabels(
            ["rank", "chunk_id", "source_doc_id", "retrieval", "rerank"]
        )
        self._lineage_evidence_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._lineage_evidence_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._lineage_evidence_table.setMaximumHeight(160)
        rv.addWidget(self._lineage_evidence_table)

        # Phase 6F — decision_attribution 바
        rv.addWidget(QLabel("판단 기여도 (decision_attribution)"))
        attr_box = QWidget()
        ab = QFormLayout(attr_box)
        ab.setContentsMargins(8, 0, 8, 0)
        self._lineage_rule_bar = QProgressBar()
        self._lineage_rule_bar.setRange(0, 100)
        self._lineage_rule_bar.setTextVisible(True)
        self._lineage_llm_bar = QProgressBar()
        self._lineage_llm_bar.setRange(0, 100)
        self._lineage_llm_bar.setTextVisible(True)
        ab.addRow("rule_weight", self._lineage_rule_bar)
        ab.addRow("llm_weight",  self._lineage_llm_bar)
        self._lineage_attribution_note = QLabel("(attribution 없음)")
        self._lineage_attribution_note.setWordWrap(True)
        ab.addRow(self._lineage_attribution_note)
        rv.addWidget(attr_box)

        splitter.addWidget(right)
        splitter.setSizes([280, 1000])
        root.addWidget(splitter)

        self._lineage_loader: _LineageLoader | None = None
        self._lineage_refresh_cases()
        return w

    def _lineage_refresh_cases(self) -> None:
        self._lineage_status.setText("로딩…")
        self._lineage_loader = _LineageLoader("list")
        self._lineage_loader.finished_cases.connect(self._lineage_populate_cases)
        self._lineage_loader.error.connect(self._lineage_on_error)
        self._lineage_loader.start()

    def _lineage_populate_cases(self, cases: list[dict]) -> None:
        self._lineage_case_list.clear()
        for c in cases:
            ts = c["created_at"].strftime("%m-%d %H:%M") if c.get("created_at") else "?"
            dec = c.get("decision") or "-"
            trace = (c.get("trace_id") or "")[:8]
            item = QListWidgetItem(f"{ts}  [{dec}]  {trace}")
            item.setData(Qt.UserRole, c["cid"])
            self._lineage_case_list.addItem(item)
        self._lineage_status.setText(f"{len(cases)}개 case")

    def _lineage_on_case_clicked(self, item: QListWidgetItem) -> None:
        cid = item.data(Qt.UserRole)
        self._lineage_status.setText(f"case 로딩… {cid[:8]}")
        self._lineage_loader = _LineageLoader("case", case_id=cid)
        self._lineage_loader.finished_case.connect(self._lineage_populate_case)
        self._lineage_loader.error.connect(self._lineage_on_error)
        self._lineage_loader.start()

    def _lineage_populate_case(self, exp) -> None:
        if exp is None:
            self._lineage_summary.setPlainText("case 를 찾지 못했습니다.")
            self._lineage_status.setText("case 없음")
            return
        self._lineage_summary.setPlainText(
            f"결정: {exp.decision.upper()}    신뢰도: {exp.confidence:.2f}\n"
            f"trace_id: {exp.trace_id}    case_id: {exp.case_id}\n"
            f"질문: {exp.question}\n\n"
            f"{exp.summary[:1000]}"
        )

        self._lineage_rules_tree.clear()
        for r in exp.rules:
            matched = ", ".join(f"{k}={v}" for k, v in r.matched_inputs.items())
            output = r.output.get("detail", "") or r.output.get("risk_level", "")
            node = QTreeWidgetItem([
                r.rule_set,
                r.rule_id,
                f"{r.weight:.2f}",
                f"{matched}  →  {output}"[:200],
            ])
            self._lineage_rules_tree.addTopLevelItem(node)

        self._lineage_txn_table.setRowCount(0)
        for t in exp.txns:
            row = self._lineage_txn_table.rowCount()
            self._lineage_txn_table.insertRow(row)
            self._lineage_txn_table.setItem(row, 0, QTableWidgetItem(t.erp_row_pk))
            self._lineage_txn_table.setItem(row, 1, QTableWidgetItem(t.amount or ""))
            self._lineage_txn_table.setItem(row, 2, QTableWidgetItem(t.account_code or ""))
            self._lineage_txn_table.setItem(row, 3, QTableWidgetItem(t.contribution))

        # Phase 6F — evidence
        self._lineage_evidence_table.setRowCount(0)
        for e in (getattr(exp, "evidence", None) or []):
            row = self._lineage_evidence_table.rowCount()
            self._lineage_evidence_table.insertRow(row)
            self._lineage_evidence_table.setItem(row, 0, QTableWidgetItem(str(e.rank)))
            self._lineage_evidence_table.setItem(row, 1, QTableWidgetItem(e.chunk_id[:48]))
            self._lineage_evidence_table.setItem(row, 2, QTableWidgetItem(e.source_doc_id))
            self._lineage_evidence_table.setItem(row, 3, QTableWidgetItem(f"{e.retrieval_score:.3f}"))
            self._lineage_evidence_table.setItem(row, 4, QTableWidgetItem(f"{e.rerank_score:.3f}"))

        # Phase 6F — attribution
        attr = getattr(exp, "attribution", None)
        if attr is None:
            self._lineage_rule_bar.setValue(0)
            self._lineage_llm_bar.setValue(0)
            self._lineage_rule_bar.setStyleSheet("")
            self._lineage_attribution_note.setText("(attribution 없음)")
        else:
            self._lineage_rule_bar.setValue(int(attr.rule_weight * 100))
            self._lineage_llm_bar.setValue(int(attr.llm_weight * 100))
            note = attr.rationale
            if attr.conflict_flag:
                self._lineage_rule_bar.setStyleSheet("QProgressBar::chunk { background-color: #c0392b; }")
                note = "⚠ " + note
            else:
                self._lineage_rule_bar.setStyleSheet("")
            self._lineage_attribution_note.setText(note)

        self._lineage_status.setText(
            f"rules {len(exp.rules)} · txns {len(exp.txns)} · "
            f"evidence {len(getattr(exp, 'evidence', None) or [])}"
        )

    def _lineage_on_error(self, msg: str) -> None:
        self._lineage_summary.setPlainText(f"오류: {msg}")
        self._lineage_status.setText("오류")


# ══════════════════════════════════════════════════════════════════════════════
# Lineage 백그라운드 로더 — Phase 6E
# ══════════════════════════════════════════════════════════════════════════════

class _LineageLoader(QThread):
    finished_cases = Signal(list)
    finished_case  = Signal(object)
    error          = Signal(str)

    def __init__(self, mode: str, case_id: str = "") -> None:
        super().__init__()
        self._mode = mode
        self._case_id = case_id

    def run(self) -> None:
        import warnings
        warnings.filterwarnings("ignore")
        loop = asyncio.new_event_loop()
        try:
            if self._mode == "list":
                cases = loop.run_until_complete(self._list_cases())
                self.finished_cases.emit(cases)
            else:
                from core.agents.explanation import load_case_explanation
                exp = loop.run_until_complete(load_case_explanation(self._case_id))
                self.finished_case.emit(exp)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            loop.close()

    async def _list_cases(self) -> list[dict]:
        from core.agents.db import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT c.case_id::text AS cid, c.trace_id, c.case_type, c.created_at,
                          a.decision, a.confidence
                   FROM audit_case c LEFT JOIN answer a ON a.case_id = c.case_id
                   ORDER BY c.created_at DESC LIMIT 30"""
            )
        return [dict(r) for r in rows]
