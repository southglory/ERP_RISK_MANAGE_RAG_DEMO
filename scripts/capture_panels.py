"""Phase 6E — 패널 헤드리스 캡처 스크립트.

QT_QPA_PLATFORM=offscreen 으로 PySide6 패널을 GUI 없이 렌더링하고
widget.grab() 으로 PNG 저장한다.

사용법:
    python scripts/capture_panels.py             # 모든 캡처
    python scripts/capture_panels.py lineage     # Lineage 탭만
    python scripts/capture_panels.py risk500     # 500건 시뮬만
    python scripts/capture_panels.py risk18rag   # 18건 RAG 포함 (vLLM 필요)
"""

from __future__ import annotations

import argparse
import os
import sys

# 헤드리스 — GUI 안 띄움
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 한글 출력 깨짐 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 프로젝트 루트
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# .env 자동 로딩
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"), override=False)
except Exception:
    pass

_OUT_DIR = os.path.join(_ROOT, "results")
os.makedirs(_OUT_DIR, exist_ok=True)


def _wait(ms: int) -> None:
    """이벤트 루프를 ms 동안 돌리며 QThread/타이머 작동시킴."""
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _grab_compact(widget, out_path: str, target_w: int = 1600) -> None:
    """가로를 와이드하게(기본 1600px) 두고 콘텐츠 높이는 sizeHint 로 자동 맞춤.
    상단 빈 공간 제거 + 좌우 splitter 가 펼쳐져 자연스러운 비율."""
    widget.adjustSize()
    h = max(widget.sizeHint().height(), widget.minimumSizeHint().height(), 600)
    widget.resize(target_w, h)
    _wait(150)
    widget.grab().save(out_path)


def capture_lineage(out_path: str) -> None:
    from ui.pyside.widgets.governance_xai_panel import GovernanceXAIPanel
    panel = GovernanceXAIPanel()
    panel.resize(1400, 800)
    panel._tabs.setCurrentIndex(0)  # Lineage 탭
    panel.show()
    _wait(2500)

    n = panel._lineage_case_list.count()
    print(f"  lineage cases loaded: {n}")
    if n > 0:
        first = panel._lineage_case_list.item(0)
        panel._lineage_case_list.setCurrentItem(first)
        panel._lineage_on_case_clicked(first)
        _wait(2500)

    _grab_compact(panel, out_path)
    print(f"  saved: {out_path}")
    panel.close()


def capture_risk_panel(n_txns: int, with_rag: bool, out_path: str) -> None:
    from data.fixtures.erp_generator import generate
    from data.fixtures.erp_transactions import SAMPLE_TRANSACTIONS
    from core.agents.risk_graph import run_risk_detect
    from core.agents.vendor_repo import reset_cache
    from ui.pyside.widgets.risk_agent_panel import RiskAgentPanel

    reset_cache()
    if n_txns == 18:
        txn_dicts = [t.model_dump(mode="json") for t in SAMPLE_TRANSACTIONS]
    else:
        txn_dicts = generate(n_txns, seed=42)

    print(f"  running risk_detect (n={n_txns}, rag={with_rag})…")
    result = run_risk_detect(txn_dicts, skip_rag=not with_rag)
    result.setdefault("transactions", txn_dicts)
    print(f"  -> overall={result.get('overall_risk', '?').upper()}, "
          f"fraud={len(result.get('fraud_alerts', []))}, "
          f"tax={len(result.get('tax_flags', []))}")

    panel = RiskAgentPanel()
    panel.resize(1400, 800)
    panel.show()
    panel._fixture_chk.setChecked(n_txns == 18)
    panel._rag_chk.setChecked(with_rag)
    panel._on_done(result)
    _wait(800)

    _grab_compact(panel, out_path)
    print(f"  saved: {out_path}")
    panel.close()


def _register_korean_font(app) -> None:
    """Windows 시스템 한글 폰트를 Qt 에 명시 등록. offscreen 모드는 fontconfig 미동작."""
    from pathlib import Path
    from PySide6.QtGui import QFont, QFontDatabase
    candidates = [
        r"C:\Windows\Fonts\malgun.ttf",
        r"C:\Windows\Fonts\malgunbd.ttf",
        r"C:\Windows\Fonts\gulim.ttc",
        r"C:\Windows\Fonts\NanumGothic.ttf",
    ]
    family = None
    for p in candidates:
        if Path(p).exists():
            fid = QFontDatabase.addApplicationFont(p)
            if fid >= 0:
                fams = QFontDatabase.applicationFontFamilies(fid)
                if fams and family is None:
                    family = fams[0]
    if family:
        app.setFont(QFont(family, 10))
        print(f"  font registered: {family}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", default="all",
                    choices=["all", "lineage", "risk18", "risk500", "risk18rag", "risk500rag"])
    args = ap.parse_args()

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("AI 회계·감사 Playground")
    _register_korean_font(app)
    # main.py 와 동일한 dark_teal 테마 적용
    try:
        from qt_material import apply_stylesheet
        apply_stylesheet(app, theme="dark_teal.xml", invert_secondary=False)
    except Exception as e:
        print(f"  qt_material apply failed: {e}")

    targets = {
        "lineage":    lambda: capture_lineage(os.path.join(_OUT_DIR, "phase6e_lineage_tab.png")),
        "risk18":     lambda: capture_risk_panel(18,  False, os.path.join(_OUT_DIR, "phase6c_risk18_norag.png")),
        "risk500":    lambda: capture_risk_panel(500, False, os.path.join(_OUT_DIR, "phase6d_risk500_norag.png")),
        "risk18rag":  lambda: capture_risk_panel(18,  True,  os.path.join(_OUT_DIR, "phase6c_risk18_rag.png")),
        "risk500rag": lambda: capture_risk_panel(500, True,  os.path.join(_OUT_DIR, "phase6d_risk500_rag.png")),
    }

    if args.target == "all":
        for name in ["lineage", "risk500", "risk18", "risk18rag", "risk500rag"]:
            print(f"=== {name} ===")
            try:
                targets[name]()
            except Exception as e:
                print(f"  FAILED: {e}")
    else:
        print(f"=== {args.target} ===")
        targets[args.target]()


if __name__ == "__main__":
    main()
