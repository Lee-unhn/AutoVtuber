"""進度對話框 — pipeline 各階段進度顯示，含 cancel 按鈕。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


class ProgressDialog:
    """非 modal 進度視窗。三個階段：prompt → face_gen → vrm_assemble。"""

    def __init__(
        self,
        parent: "QWidget | None" = None,
        on_cancel: Callable[[], None] | None = None,
    ):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QDialog,
            QHBoxLayout,
            QLabel,
            QProgressBar,
            QPushButton,
            QVBoxLayout,
        )

        self._on_cancel = on_cancel

        self._dlg = QDialog(parent)
        self._dlg.setWindowTitle("生成中...")
        self._dlg.setModal(False)
        self._dlg.setMinimumWidth(420)

        layout = QVBoxLayout(self._dlg)

        self._stage_labels: dict[str, QLabel] = {}
        self._stage_bars: dict[str, QProgressBar] = {}
        for key, label in [
            ("01_prompt", "1. 生成 SD prompt（Ollama）"),
            ("02_face_gen", "2. SDXL 生成臉部"),
            ("03_vrm_assemble", "3. 組裝 VRM 檔"),
        ]:
            row = QVBoxLayout()
            l = QLabel(label)
            self._stage_labels[key] = l
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            self._stage_bars[key] = bar
            row.addWidget(l)
            row.addWidget(bar)
            layout.addLayout(row)

        # 按鈕列
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self._cancel)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    @property
    def widget(self):
        return self._dlg

    def show(self) -> None:
        self._dlg.show()

    def close(self) -> None:
        self._dlg.close()

    def update_progress(self, stage: str, current: int, total: int) -> None:
        bar = self._stage_bars.get(stage)
        if bar is None:
            return
        if total <= 0:
            bar.setRange(0, 0)  # 不確定模式
            return
        bar.setRange(0, total)
        bar.setValue(current)
        # 更新 label
        label = self._stage_labels[stage]
        label.setText(f"{label.text().split(' (')[0]} ({current}/{total})")

    def mark_stage_done(self, stage: str, succeeded: bool, elapsed_s: float) -> None:
        bar = self._stage_bars.get(stage)
        if bar:
            bar.setRange(0, 100)
            bar.setValue(100)
        label = self._stage_labels.get(stage)
        if label:
            mark = "✅" if succeeded else "❌"
            label.setText(f"{mark} {label.text().split(' (')[0]} — {elapsed_s:.1f}s")

    def _cancel(self) -> None:
        if self._on_cancel:
            self._on_cancel()
        self._dlg.close()
