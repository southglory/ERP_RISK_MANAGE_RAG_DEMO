"""AI 회계·감사 Playground — PySide6 메인 윈도우.

core/ 임포트만 허용. Qt를 core/에서 import하면 안 됨.
"""
from __future__ import annotations
import sys
import os
import asyncio
import warnings

# Windows cp949 터미널에서 한글/유니코드 출력 깨짐 방지
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

warnings.filterwarnings("ignore")   # 플레이그라운드 — langgraph 등 서드파티 경고 전체 억제

# 프로젝트 루트(ERP_RISK_MANAGE/)를 sys.path에 추가 — 직접 실행 시에도 core/ui 임포트 가능
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# .env 자동 로딩 — run.bat에서 환경변수를 따로 설정하지 않아도 동작
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"), override=False)
except Exception:
    pass
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QVBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QStatusBar,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont
import qasync
from qt_material import apply_stylesheet


# ── 모듈 탭 이름 → 나중에 QStackedWidget 페이지로 확장
MODULES = [
    ("📊 거래 시뮬레이터",     "transaction_sim"),
    ("📒 분개 자동생성",       "journal_engine"),
    ("🧾 세금계산서 워커",     "etax_worker"),
    ("🔍 재무 부정 탐지",      "fraud_detector"),
    ("🤖 리스크 탐지 에이전트", "risk_agent"),
    ("⚖️  세무 리스크 RAG",    "tax_risk_rag"),
    ("📜 계약·판례 RAG",       "contract_rag"),
    ("🔗 거버넌스 / XAI",      "governance_xai"),
]


class ModuleNav(QListWidget):
    """왼쪽 모듈 네비게이션 패널."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(220)
        font = QFont()
        font.setPointSize(11)
        self.setFont(font)
        self.setSpacing(4)
        for label, _ in MODULES:
            item = QListWidgetItem(label)
            item.setSizeHint(QSize(200, 42))
            self.addItem(item)
        self.setCurrentRow(0)


class PlaceholderPanel(QWidget):
    """모듈별 콘텐츠 자리 표시자 — 나중에 실제 위젯으로 교체."""

    def __init__(self, module_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        label = QLabel(f"[ {module_key} ]\n\n구현 예정")
        label.setAlignment(Qt.AlignCenter)
        label.setFont(QFont("Pretendard", 14))
        layout.addWidget(label)


def _make_panel(key: str) -> QWidget:
    """모듈 키에 맞는 패널 위젯을 반환한다."""
    if key == "transaction_sim":
        from ui.pyside.widgets.transaction_sim_panel import TransactionSimPanel
        return TransactionSimPanel()
    if key == "journal_engine":
        from ui.pyside.widgets.journal_panel import JournalEnginePanel
        return JournalEnginePanel()
    if key == "etax_worker":
        from ui.pyside.widgets.etax_panel import ETaxPanel
        return ETaxPanel()
    if key == "fraud_detector":
        from ui.pyside.widgets.fraud_panel import FraudDetectorPanel
        return FraudDetectorPanel()
    if key == "risk_agent":
        from ui.pyside.widgets.risk_agent_panel import RiskAgentPanel
        return RiskAgentPanel()
    if key == "tax_risk_rag":
        from ui.pyside.widgets.tax_rag_panel import TaxRiskRAGPanel
        return TaxRiskRAGPanel()
    if key == "contract_rag":
        from ui.pyside.widgets.contract_rag_panel import ContractRAGPanel
        return ContractRAGPanel()
    if key == "governance_xai":
        from ui.pyside.widgets.governance_xai_panel import GovernanceXAIPanel
        return GovernanceXAIPanel()
    return PlaceholderPanel(key)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AI 회계·감사 Playground — 로컬 LLM")
        self.setMinimumSize(1280, 800)
        self._build_ui()
        self._build_menu()
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("vLLM: 연결 대기 중 …")

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        # 왼쪽 — 모듈 네비
        self.nav = ModuleNav()
        self.nav.currentRowChanged.connect(self._on_module_changed)
        splitter.addWidget(self.nav)

        # 오른쪽 — 콘텐츠 영역
        self.content_area = QWidget()
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(16, 16, 16, 16)

        self._panels: dict[str, QWidget] = {}
        for _, key in MODULES:
            panel = _make_panel(key)
            self._panels[key] = panel
            self.content_layout.addWidget(panel)
            panel.hide()

        # 첫 번째 패널 표시
        first_key = MODULES[0][1]
        self._panels[first_key].show()
        self._active_key = first_key

        splitter.addWidget(self.content_area)
        splitter.setSizes([220, 1060])

    def _build_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("파일")
        file_menu.addAction("설정").triggered.connect(self._open_settings)
        file_menu.addSeparator()
        file_menu.addAction("종료").triggered.connect(self.close)

        tools_menu = menu.addMenu("도구")
        tools_menu.addAction("vLLM 연결 테스트").triggered.connect(self._test_vllm)
        tools_menu.addAction("DB 연결 테스트").triggered.connect(self._test_db)

    def _on_module_changed(self, row: int) -> None:
        if row < 0:
            return
        self._panels[self._active_key].hide()
        key = MODULES[row][1]
        self._panels[key].show()
        self._active_key = key

    def _open_settings(self) -> None:
        from ui.pyside.widgets.settings_dialog import SettingsDialog
        SettingsDialog(self).exec()

    def _test_vllm(self) -> None:
        asyncio.ensure_future(self._async_test_vllm())

    async def _async_test_vllm(self) -> None:
        from core.providers.llm import VLLMProvider
        from core.providers.base import ChatMessage
        try:
            llm = VLLMProvider()
            result = await llm.chat([ChatMessage("user", "안녕하세요. 한 문장으로 응답해주세요.")])
            self.statusBar().showMessage(f"vLLM OK: {result[:60]}")
        except Exception as e:
            self.statusBar().showMessage(f"vLLM 오류: {e}")

    def _test_db(self) -> None:
        asyncio.ensure_future(self._async_test_db())

    async def _async_test_db(self) -> None:
        import asyncpg, os
        try:
            conn = await asyncpg.connect(os.environ.get("DATABASE_URL",
                "postgresql://playground:playground@localhost:5432/playground"))
            rows = await conn.fetch("SELECT COUNT(*) FROM audit_case")
            await conn.close()
            self.statusBar().showMessage(f"DB OK — audit_case 행 수: {rows[0][0]}")
        except Exception as e:
            self.statusBar().showMessage(f"DB 오류: {e}")


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("AI 회계·감사 Playground")
    apply_stylesheet(app, theme="dark_teal.xml", invert_secondary=False)

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
