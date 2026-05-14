"""Phase 6F UI smoke — panel 부팅 + Lineage 탭의 새 위젯들 존재 확인."""

import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from ui.pyside.widgets.governance_xai_panel import GovernanceXAIPanel

p = GovernanceXAIPanel()
print("panel created")
print("evidence table:", hasattr(p, "_lineage_evidence_table"),
      "cols:", p._lineage_evidence_table.columnCount() if hasattr(p, "_lineage_evidence_table") else "-")
print("rule bar:", hasattr(p, "_lineage_rule_bar"))
print("llm bar:",  hasattr(p, "_lineage_llm_bar"))
print("attr note:", hasattr(p, "_lineage_attribution_note"))
