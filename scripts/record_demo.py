"""데모 영상 자동 캡처 — PNG 시퀀스 → FFmpeg → GIF/MP4.

전략: PySide6 패널을 헤드리스로 띄우고 시나리오 단계별 widget.grab() PNG → ffmpeg.

사용:
    python scripts/record_demo.py s3              # 시나리오 3 (가공거래)
    python scripts/record_demo.py s3 --gif        # GIF 산출
    python scripts/record_demo.py s3 --mp4        # MP4 산출 (기본 둘다)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env", override=False)
except Exception:
    pass


_OUT_DIR = _ROOT / "docs" / "demo"
_FRAMES_DIR = _ROOT / "results" / "demo_frames"
_OUT_DIR.mkdir(parents=True, exist_ok=True)
_FRAMES_DIR.mkdir(parents=True, exist_ok=True)


# ────────────────────────────────────────────────────────────────────────────
# 공용 유틸
# ────────────────────────────────────────────────────────────────────────────

def _wait(ms: int) -> None:
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _grab(widget, out_path: Path, target_w: int = 1400) -> None:
    widget.adjustSize()
    h = max(widget.sizeHint().height(), widget.minimumSizeHint().height(), 700)
    widget.resize(target_w, h)
    _wait(150)
    widget.grab().save(str(out_path))


def _register_korean_font(app) -> None:
    from PySide6.QtGui import QFont, QFontDatabase
    for p in (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunbd.ttf"):
        if Path(p).exists():
            fid = QFontDatabase.addApplicationFont(p)
            if fid >= 0:
                fams = QFontDatabase.applicationFontFamilies(fid)
                if fams:
                    app.setFont(QFont(fams[0], 10))
                    return


def _apply_theme(app) -> None:
    try:
        from qt_material import apply_stylesheet
        apply_stylesheet(app, theme="dark_teal.xml", invert_secondary=False)
    except Exception:
        pass


# ────────────────────────────────────────────────────────────────────────────
# 시나리오 3 — 가공거래 탐지 (RiskAgentPanel + GovernanceXAIPanel Lineage)
# ────────────────────────────────────────────────────────────────────────────

def scenario_3(skip_rag: bool = True) -> list[Path]:
    """가공거래 탐지 시나리오. 4 단계 PNG 시퀀스 반환."""
    from data.fixtures.erp_generator import generate
    from core.agents.risk_graph import run_risk_detect
    from core.agents.vendor_repo import reset_cache
    from ui.pyside.widgets.risk_agent_panel import RiskAgentPanel
    from ui.pyside.widgets.governance_xai_panel import GovernanceXAIPanel

    frames: list[Path] = []
    scene_dir = _FRAMES_DIR / "s3"
    scene_dir.mkdir(parents=True, exist_ok=True)
    for f in scene_dir.glob("*.png"):
        f.unlink()

    # 단계 1: RiskAgentPanel 빈 화면 (부팅)
    panel = RiskAgentPanel()
    panel.resize(1400, 800)
    panel.show()
    _wait(800)
    p = scene_dir / "01_boot.png"
    _grab(panel, p)
    frames.append(p)
    print(f"  [s3:1] {p.name}")

    # 단계 2: 1000 건 합성 거래 실행
    reset_cache()
    txns = generate(1000, seed=42)
    result = run_risk_detect(txns, skip_rag=skip_rag)
    result.setdefault("transactions", txns)
    panel._fixture_chk.setChecked(False)
    panel._rag_chk.setChecked(not skip_rag)
    panel._on_done(result)
    _wait(800)
    p = scene_dir / "02_risk_result.png"
    _grab(panel, p)
    frames.append(p)
    print(f"  [s3:2] {p.name}  fraud={len(result.get('fraud_alerts', []))} tax={len(result.get('tax_flags', []))} risk={result.get('overall_risk')}")
    panel.close()

    # 단계 3: Lineage 탭 첫 case 클릭
    gov = GovernanceXAIPanel()
    gov.resize(1400, 800)
    gov._tabs.setCurrentIndex(0)
    gov.show()
    _wait(2500)
    n = gov._lineage_case_list.count()
    print(f"  [s3:3] lineage cases: {n}")
    if n > 0:
        first = gov._lineage_case_list.item(0)
        gov._lineage_case_list.setCurrentItem(first)
        gov._lineage_on_case_clicked(first)
        _wait(2500)
    p = scene_dir / "03_lineage_rules.png"
    _grab(gov, p)
    frames.append(p)
    print(f"  [s3:3] {p.name}")

    # 단계 4: 같은 lineage 화면 더 넓게 — evidence + attribution 강조
    _wait(500)
    p = scene_dir / "04_lineage_evidence_attribution.png"
    _grab(gov, p, target_w=1500)
    frames.append(p)
    print(f"  [s3:4] {p.name}")
    gov.close()

    return frames


# ────────────────────────────────────────────────────────────────────────────
# FFmpeg 변환
# ────────────────────────────────────────────────────────────────────────────

def make_gif(frames: list[Path], out_path: Path, seconds_per_frame: float = 2.5) -> None:
    if not frames:
        print("  no frames")
        return
    list_path = out_path.with_suffix(".txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for fr in frames:
            f.write(f"file '{fr.as_posix()}'\n")
            f.write(f"duration {seconds_per_frame}\n")
        f.write(f"file '{frames[-1].as_posix()}'\n")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-vf", "fps=10,scale=900:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
        "-loop", "0",
        str(out_path),
    ]
    print(f"  ffmpeg GIF → {out_path.name}")
    subprocess.run(cmd, check=True, capture_output=True)
    list_path.unlink(missing_ok=True)


def make_mp4(frames: list[Path], out_path: Path, seconds_per_frame: float = 2.5) -> None:
    if not frames:
        return
    list_path = out_path.with_suffix(".txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for fr in frames:
            f.write(f"file '{fr.as_posix()}'\n")
            f.write(f"duration {seconds_per_frame}\n")
        f.write(f"file '{frames[-1].as_posix()}'\n")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-vf", "fps=30,scale=1280:-2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "23",
        str(out_path),
    ]
    print(f"  ffmpeg MP4 → {out_path.name}")
    subprocess.run(cmd, check=True, capture_output=True)
    list_path.unlink(missing_ok=True)


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────

# ────────────────────────────────────────────────────────────────────────────
# 시나리오 1 — 다요소 패키지 매출인식 (K-IFRS 1115)
# ────────────────────────────────────────────────────────────────────────────

def scenario_1(**_kw) -> list[Path]:
    from ui.pyside.widgets.journal_panel import JournalEnginePanel

    frames: list[Path] = []
    d = _FRAMES_DIR / "s1"
    d.mkdir(parents=True, exist_ok=True)
    for f in d.glob("*.png"):
        f.unlink()

    panel = JournalEnginePanel()
    panel.resize(1400, 800)
    panel.show()
    _wait(800)
    p = d / "01_panel_boot.png"; _grab(panel, p); frames.append(p)
    print(f"  [s1:1] {p.name}")

    # 기본 라인 추가
    panel._add_default_lines()
    _wait(500)
    p = d / "02_default_lines.png"; _grab(panel, p); frames.append(p)
    print(f"  [s1:2] {p.name}")

    # 평가 실행 (synchronous wrapper)
    try:
        panel._run_eval()
        _wait(3000)   # 결과 wait
    except Exception as e:
        print(f"  [s1] eval error: {e}")
    p = d / "03_eval_result.png"; _grab(panel, p); frames.append(p)
    print(f"  [s1:3] {p.name}")

    panel.close()
    return frames


# ────────────────────────────────────────────────────────────────────────────
# 시나리오 2 — 세무 RAG (외국 SW 사용료 원천세)
# ────────────────────────────────────────────────────────────────────────────

def scenario_2(**_kw) -> list[Path]:
    from ui.pyside.widgets.tax_rag_panel import TaxRiskRAGPanel

    frames: list[Path] = []
    d = _FRAMES_DIR / "s2"
    d.mkdir(parents=True, exist_ok=True)
    for f in d.glob("*.png"):
        f.unlink()

    panel = TaxRiskRAGPanel()
    panel.resize(1400, 800)
    panel.show()
    _wait(800)
    p = d / "01_panel_boot.png"; _grab(panel, p); frames.append(p)
    print(f"  [s2:1] {p.name}")

    # 질의 입력
    if hasattr(panel, "_query_input"):
        panel._query_input.setPlainText("MS Azure 100,000 USD 클라우드 사용료 (미국 본사 청구)의 원천징수세율은?")
    elif hasattr(panel, "_query_edit"):
        panel._query_edit.setPlainText("MS Azure 100,000 USD 클라우드 사용료 (미국 본사 청구)의 원천징수세율은?")
    _wait(300)
    p = d / "02_query_typed.png"; _grab(panel, p); frames.append(p)
    print(f"  [s2:2] {p.name}")

    # 검색 실행 — RAG 청크만 (LLM 답변은 vllm 없으면 빈약)
    try:
        panel._on_run()
        _wait(5000)
    except Exception as e:
        print(f"  [s2] run error: {e}")
    p = d / "03_result.png"; _grab(panel, p); frames.append(p)
    print(f"  [s2:3] {p.name}")

    panel.close()
    return frames


# ────────────────────────────────────────────────────────────────────────────
# 시나리오 4 — 계약 vs 실거래 (Contract RAG)
# ────────────────────────────────────────────────────────────────────────────

def scenario_4(**_kw) -> list[Path]:
    from ui.pyside.widgets.contract_rag_panel import ContractRAGPanel

    frames: list[Path] = []
    d = _FRAMES_DIR / "s4"
    d.mkdir(parents=True, exist_ok=True)
    for f in d.glob("*.png"):
        f.unlink()

    panel = ContractRAGPanel()
    panel.resize(1400, 800)
    panel.show()
    _wait(800)
    p = d / "01_panel_boot.png"; _grab(panel, p); frames.append(p)
    print(f"  [s4:1] {p.name}")

    # 질의
    query = "계약의 납기 30일과 실제 거래 납기 45일이 충돌하는 경우 적용되는 하도급법 조항은?"
    if hasattr(panel, "_query_input"):
        panel._query_input.setPlainText(query)
    elif hasattr(panel, "_query_edit"):
        panel._query_edit.setPlainText(query)
    _wait(300)
    p = d / "02_query_typed.png"; _grab(panel, p); frames.append(p)
    print(f"  [s4:2] {p.name}")

    try:
        panel._on_run()
        _wait(5000)
    except Exception as e:
        print(f"  [s4] run error: {e}")
    p = d / "03_result.png"; _grab(panel, p); frames.append(p)
    print(f"  [s4:3] {p.name}")

    panel.close()
    return frames


# ────────────────────────────────────────────────────────────────────────────
# 시나리오 5 — 세금계산서 KEC v3.0
# ────────────────────────────────────────────────────────────────────────────

def scenario_5(**_kw) -> list[Path]:
    from ui.pyside.widgets.etax_panel import ETaxPanel

    frames: list[Path] = []
    d = _FRAMES_DIR / "s5"
    d.mkdir(parents=True, exist_ok=True)
    for f in d.glob("*.png"):
        f.unlink()

    panel = ETaxPanel()
    panel.resize(1400, 800)
    panel.show()
    _wait(800)
    p = d / "01_panel_boot.png"; _grab(panel, p); frames.append(p)
    print(f"  [s5:1] {p.name}")

    panel._add_default_line()
    _wait(400)
    p = d / "02_default_line.png"; _grab(panel, p); frames.append(p)
    print(f"  [s5:2] {p.name}")

    try:
        panel._run()
        _wait(1500)
    except Exception as e:
        print(f"  [s5] run error: {e}")
    p = d / "03_xml_generated.png"; _grab(panel, p); frames.append(p)
    print(f"  [s5:3] {p.name}")

    panel.close()
    return frames


SCENARIOS = {
    "s1": ("scenario_1_kifrs_journal",   scenario_1),
    "s2": ("scenario_2_tax_rag",         scenario_2),
    "s3": ("scenario_3_fraud_detection", scenario_3),
    "s4": ("scenario_4_contract_rag",    scenario_4),
    "s5": ("scenario_5_etax_invoice",    scenario_5),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", choices=list(SCENARIOS.keys()) + ["all"], default="s3", nargs="?")
    ap.add_argument("--gif",       action="store_true")
    ap.add_argument("--mp4",       action="store_true")
    ap.add_argument("--no-rag",    action="store_true", default=True)
    ap.add_argument("--frame-sec", type=float, default=2.5)
    args = ap.parse_args()

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("AI 회계·감사 Playground")
    _register_korean_font(app)
    _apply_theme(app)

    targets = list(SCENARIOS.keys()) if args.target == "all" else [args.target]

    if not (args.gif or args.mp4):
        args.gif = True

    for t in targets:
        name, fn = SCENARIOS[t]
        print(f"=== {name} ===")
        try:
            frames = fn(skip_rag=args.no_rag)
        except Exception as e:
            print(f"  FAILED: {e}")
            continue
        if args.gif:
            try:
                make_gif(frames, _OUT_DIR / f"{name}.gif", seconds_per_frame=args.frame_sec)
            except subprocess.CalledProcessError as e:
                print(f"  gif fail: {e.stderr.decode('utf-8', errors='replace')[:300]}")
        if args.mp4:
            try:
                make_mp4(frames, _OUT_DIR / f"{name}.mp4", seconds_per_frame=args.frame_sec)
            except subprocess.CalledProcessError as e:
                print(f"  mp4 fail: {e.stderr.decode('utf-8', errors='replace')[:300]}")
        print(f"  done — {len(frames)} frames\n")
    print(f"output dir: {_OUT_DIR}")


if __name__ == "__main__":
    main()
