"""환경 설정 다이얼로그."""

from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QVBoxLayout, QWidget,
)


class _EnvField(QWidget):
    def __init__(self, env_key: str, label: str, parent=None) -> None:
        super().__init__(parent)
        self._key = env_key
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._edit = QLineEdit(os.environ.get(env_key, ""))
        self._edit.setPlaceholderText(f"${env_key}")
        layout.addWidget(self._edit)

    def value(self) -> str:
        return self._edit.text()

    def apply(self) -> None:
        os.environ[self._key] = self._edit.text()


class SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.setMinimumWidth(480)
        self._fields: list[_EnvField] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # vLLM 그룹
        vllm_box = QGroupBox("vLLM (로컬)")
        vllm_form = QFormLayout(vllm_box)
        for key, label in [
            ("VLLM_BASE_URL",  "Base URL"),
            ("VLLM_MODEL",     "모델 이름"),
            ("VLLM_API_KEY",   "API Key"),
        ]:
            f = _EnvField(key, label)
            self._fields.append(f)
            vllm_form.addRow(QLabel(label), f)
        root.addWidget(vllm_box)

        # DB 그룹
        db_box = QGroupBox("PostgreSQL")
        db_form = QFormLayout(db_box)
        for key, label in [
            ("DATABASE_URL", "DATABASE_URL"),
        ]:
            f = _EnvField(key, label)
            self._fields.append(f)
            db_form.addRow(QLabel(label), f)
        root.addWidget(db_box)

        # Langfuse 그룹
        lf_box = QGroupBox("Langfuse")
        lf_form = QFormLayout(lf_box)
        for key, label in [
            ("LANGFUSE_BASE_URL",    "Base URL"),
            ("LANGFUSE_PUBLIC_KEY",  "Public Key"),
            ("LANGFUSE_SECRET_KEY",  "Secret Key"),
        ]:
            f = _EnvField(key, label)
            self._fields.append(f)
            lf_form.addRow(QLabel(label), f)
        root.addWidget(lf_box)

        # 버튼
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _apply(self) -> None:
        for f in self._fields:
            f.apply()
        self.accept()
