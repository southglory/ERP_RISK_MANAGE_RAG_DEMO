"""세무 리스크 RAG 패널 — Solar LLM + pgvector + bge-reranker."""

from __future__ import annotations

import asyncio
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QPushButton, QScrollArea,
    QSplitter, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from core.rag.models import RAGMode, RAGQuery, SourceType


_SOURCE_LABELS = {
    SourceType.TAX_LAW:  "세법 조문",
    SourceType.COURT:    "판례",
    SourceType.RULING:   "예규·해석",
    SourceType.CONTRACT: "계약서",
    SourceType.INTERNAL: "내부 문서",
}

_SAMPLE_QUERIES = [
    "소프트웨어 SaaS 구독료의 부가세 과세 기준과 세금계산서 발급 시점은?",
    "외국법인으로부터 받는 기술사용료(로열티)의 원천세율과 조세조약 적용 요건은?",
    "건설공사 장기계약의 수익인식 시점 — K-IFRS 1115호 적용 기준은?",
]


class TaxRiskRAGPanel(QWidget):
    """세무 리스크 RAG 패널."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pipeline = None
        self._running = False
        self._build_ui()

    # ── UI 빌드 ───────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        # 왼쪽 — 쿼리 폼
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setMinimumWidth(340)
        left_scroll.setMaximumWidth(420)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)
        left_scroll.setWidget(left)

        title = QLabel("⚖️ 세무 리스크 RAG — Solar LLM")
        title.setFont(QFont("Pretendard", 13, QFont.Bold))
        lv.addWidget(title)

        # 질문 입력
        q_box = QGroupBox("질문")
        q_vbox = QVBoxLayout(q_box)
        self._query_edit = QTextEdit()
        self._query_edit.setFixedHeight(90)
        self._query_edit.setPlaceholderText(_SAMPLE_QUERIES[0])
        q_vbox.addWidget(self._query_edit)

        # 예시 쿼리 버튼 행
        ex_row = QHBoxLayout()
        for i, sq in enumerate(_SAMPLE_QUERIES, 1):
            btn = QPushButton(f"예시 {i}")
            btn.setToolTip(sq)
            btn.setFixedWidth(60)
            btn.clicked.connect(lambda _, q=sq: self._query_edit.setPlainText(q))
            ex_row.addWidget(btn)
        ex_row.addStretch()
        q_vbox.addLayout(ex_row)
        lv.addWidget(q_box)

        # 검색 설정
        cfg_box = QGroupBox("검색 설정")
        cfg_form = QFormLayout(cfg_box)

        self._mode_combo = QComboBox()
        for mode in RAGMode:
            self._mode_combo.addItem(mode.value, mode)
        self._mode_combo.setCurrentIndex(2)   # rerank 기본

        self._topk_combo = QComboBox()
        for k in [3, 5, 7, 10]:
            self._topk_combo.addItem(str(k), k)
        self._topk_combo.setCurrentIndex(1)   # 5 기본

        cfg_form.addRow("검색 모드", self._mode_combo)
        cfg_form.addRow("Top-K", self._topk_combo)
        lv.addWidget(cfg_box)

        # 소스 필터
        src_box = QGroupBox("문서 소스 (미선택 = 전체)")
        src_vbox = QVBoxLayout(src_box)
        self._src_checks: dict[SourceType, QCheckBox] = {}
        for st, label in _SOURCE_LABELS.items():
            cb = QCheckBox(label)
            src_vbox.addWidget(cb)
            self._src_checks[st] = cb
        lv.addWidget(src_box)

        # 실행 버튼
        btn_row = QHBoxLayout()
        self._run_btn = QPushButton("▶  질의 실행")
        self._run_btn.setMinimumHeight(38)
        self._run_btn.setFont(QFont("Pretendard", 11, QFont.Bold))
        self._run_btn.clicked.connect(self._on_run)

        self._stream_btn = QPushButton("⟳ 스트리밍")
        self._stream_btn.setMinimumHeight(38)
        self._stream_btn.clicked.connect(self._on_stream)

        btn_row.addWidget(self._run_btn)
        btn_row.addWidget(self._stream_btn)
        lv.addLayout(btn_row)

        # 서비스 상태
        svc_box = QGroupBox("서비스 상태")
        sv = QVBoxLayout(svc_box)
        self._status_label = QLabel(
            "• vLLM: 미확인\n"
            "• infinity-emb: 미확인\n"
            "• pgvector: 미확인"
        )
        self._status_label.setFont(QFont("Consolas", 9))
        sv.addWidget(self._status_label)
        chk_btn = QPushButton("상태 확인")
        chk_btn.clicked.connect(self._check_services)
        sv.addWidget(chk_btn)
        lv.addWidget(svc_box)
        lv.addStretch()

        splitter.addWidget(left_scroll)

        # 오른쪽 — 결과
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 8, 8, 8)

        ans_box = QGroupBox("답변 (Solar LLM)")
        av = QVBoxLayout(ans_box)
        self._answer_text = QTextEdit()
        self._answer_text.setReadOnly(True)
        self._answer_text.setFont(QFont("Pretendard", 11))
        self._answer_text.setMinimumHeight(200)
        av.addWidget(self._answer_text)

        self._trace_label = QLabel("")
        self._trace_label.setFont(QFont("Consolas", 9))
        self._trace_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        av.addWidget(self._trace_label)
        rv.addWidget(ans_box)

        chunk_box = QGroupBox("참고 문서 청크")
        cv = QVBoxLayout(chunk_box)
        self._chunk_table = QTableWidget(0, 5)
        self._chunk_table.setHorizontalHeaderLabels(
            ["#", "소스", "문서명", "점수", "내용 (미리보기)"]
        )
        hh = self._chunk_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Interactive)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        self._chunk_table.setMinimumHeight(160)
        self._chunk_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._chunk_table.setAlternatingRowColors(True)
        cv.addWidget(self._chunk_table)
        rv.addWidget(chunk_box)

        splitter.addWidget(right)
        splitter.setSizes([380, 900])

    # ── 이벤트 ───────────────────────────────────────────────────────────────

    def _on_run(self) -> None:
        if not self._running:
            asyncio.ensure_future(self._async_run(stream=False))

    def _on_stream(self) -> None:
        if not self._running:
            asyncio.ensure_future(self._async_run(stream=True))

    def _check_services(self) -> None:
        asyncio.ensure_future(self._async_check_services())

    # ── 비동기 ───────────────────────────────────────────────────────────────

    def _build_query(self) -> RAGQuery | None:
        q = self._query_edit.toPlainText().strip()
        if not q:
            self._answer_text.setPlainText("질문을 입력하세요.")
            return None
        mode = self._mode_combo.currentData()
        top_k = self._topk_combo.currentData()
        src_types = [st for st, cb in self._src_checks.items() if cb.isChecked()]
        return RAGQuery(query=q, top_k=top_k, mode=mode, source_types=src_types)

    def _get_pipeline(self):
        if self._pipeline is None:
            from core.rag.pipeline import build_pipeline
            self._pipeline = build_pipeline()
        return self._pipeline

    def _set_buttons(self, enabled: bool) -> None:
        self._run_btn.setEnabled(enabled)
        self._stream_btn.setEnabled(enabled)

    async def _async_run(self, stream: bool = False) -> None:
        query = self._build_query()
        if query is None:
            return

        self._running = True
        self._set_buttons(False)
        self._answer_text.setPlainText("처리 중…")
        self._trace_label.setText("")
        self._chunk_table.setRowCount(0)

        try:
            pipeline = self._get_pipeline()
            if stream:
                chunks, token_iter = await pipeline.stream(query)
                self._populate_chunks(chunks)
                self._answer_text.setPlainText("")
                async for token in token_iter:
                    self._answer_text.insertPlainText(token)
                    sb = self._answer_text.verticalScrollBar()
                    sb.setValue(sb.maximum())
            else:
                result = await pipeline.run(query)
                self._answer_text.setPlainText(result.answer)
                self._populate_chunks(result.chunks)
                trace_txt = (
                    f"Trace ID: {result.trace_id}"
                    if result.trace_id
                    else "Langfuse 미연결"
                )
                self._trace_label.setText(f"⏱ {result.latency_ms}ms  |  {trace_txt}")

        except KeyError as e:
            self._pipeline = None
            self._answer_text.setPlainText(
                f"환경변수 미설정: {e}\n\n"
                ".env 또는 Docker Compose에서 다음을 설정하세요:\n"
                "  VLLM_BASE_URL=http://localhost:8000/v1\n"
                "  VLLM_MODEL=solar-10.7b-instruct"
            )
        except Exception as e:
            self._pipeline = None
            self._answer_text.setPlainText(
                f"오류: {e}\n\n"
                "서비스가 실행 중인지 확인하세요:\n"
                "  docker compose up vllm infinity postgres"
            )
        finally:
            self._running = False
            self._set_buttons(True)

    async def _async_check_services(self) -> None:
        lines: list[str] = []

        try:
            from core.providers.llm.vllm_provider import VLLMProvider
            from core.providers.base import ChatMessage
            llm = VLLMProvider()
            await llm.chat([ChatMessage("user", "ping")], max_tokens=5)
            lines.append("• vLLM: ✅ 연결됨")
        except KeyError:
            lines.append("• vLLM: ⚠️ VLLM_BASE_URL 미설정")
        except Exception as e:
            lines.append(f"• vLLM: ❌ {str(e)[:50]}")

        try:
            from core.providers.embedding.infinity_provider import InfinityEmbeddingProvider
            await InfinityEmbeddingProvider().embed(["test"])
            lines.append("• infinity-emb: ✅ 연결됨")
        except Exception as e:
            lines.append(f"• infinity-emb: ❌ {str(e)[:50]}")

        try:
            import asyncpg
            conn = await asyncpg.connect(
                os.environ.get(
                    "DATABASE_URL",
                    "postgresql://playground:playground@localhost:5432/playground",
                )
            )
            await conn.close()
            lines.append("• pgvector: ✅ 연결됨")
        except Exception as e:
            lines.append(f"• pgvector: ❌ {str(e)[:50]}")

        self._status_label.setText("\n".join(lines))

    # ── UI 업데이트 ───────────────────────────────────────────────────────────

    def _populate_chunks(self, chunks: list) -> None:
        self._chunk_table.setRowCount(0)
        for i, c in enumerate(chunks):
            self._chunk_table.insertRow(i)
            score = c.rerank_score if c.rerank_score else c.score
            self._chunk_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self._chunk_table.setItem(i, 1, QTableWidgetItem(c.source_type.value))
            self._chunk_table.setItem(i, 2, QTableWidgetItem(c.document_title or "—"))
            self._chunk_table.setItem(i, 3, QTableWidgetItem(f"{score:.3f}"))
            preview = c.content[:120].replace("\n", " ")
            self._chunk_table.setItem(i, 4, QTableWidgetItem(preview))
