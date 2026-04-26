"""即時硬體狀態橫幅 — 主視窗頂部的 VRAM/溫度/RAM 即時顯示。

顏色狀態：
    OK: 綠色
    WARN: 黃色
    COOLDOWN: 橘色
    ABORT: 紅色閃爍
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


_STATE_COLORS = {
    "ok": "#2e7d32",
    "warn": "#f9a825",
    "cooldown": "#ef6c00",
    "abort": "#c62828",
}


class SafetyBanner:
    """工廠類別：建立 banner widget 並提供 update() 方法。

    不繼承 QWidget — 因為 lazy import PySide6 的關係，把實際 widget 類別包成 inner class。
    """

    def __init__(self, parent: "QWidget | None" = None):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QFrame

        self._frame = QFrame(parent)
        self._frame.setObjectName("safetyBanner")
        self._frame.setFrameShape(QFrame.Shape.StyledPanel)
        self._frame.setMinimumHeight(36)

        layout = QHBoxLayout(self._frame)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(20)

        self._state_label = QLabel("⚙️ Initializing...")
        self._state_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        f = QFont()
        f.setBold(True)
        self._state_label.setFont(f)
        layout.addWidget(self._state_label)

        self._vram_label = QLabel("VRAM: -- / -- GB")
        layout.addWidget(self._vram_label)

        self._temp_label = QLabel("GPU: --°C")
        layout.addWidget(self._temp_label)

        self._ram_label = QLabel("RAM: --%")
        layout.addWidget(self._ram_label)

        self._disk_label = QLabel("Disk: -- GB free")
        layout.addWidget(self._disk_label)

        layout.addStretch()
        self._set_color("#9e9e9e")

    @property
    def widget(self):
        return self._frame

    def update(
        self,
        state: str,
        vram_used_gb: float,
        vram_total_gb: float,
        gpu_temp_c: int,
        ram_pct: float,
        disk_free_gb: float,
    ) -> None:
        emoji = {"ok": "✅", "warn": "⚠️", "cooldown": "🌡️", "abort": "🛑"}.get(state, "⚙️")
        self._state_label.setText(f"{emoji} {state.upper()}")
        self._vram_label.setText(f"VRAM: {vram_used_gb:.2f} / {vram_total_gb:.1f} GB")
        self._temp_label.setText(f"GPU: {gpu_temp_c}°C")
        self._ram_label.setText(f"RAM: {ram_pct:.0f}%")
        self._disk_label.setText(f"Disk: {disk_free_gb:.1f} GB free")
        self._set_color(_STATE_COLORS.get(state, "#9e9e9e"))

    def _set_color(self, color: str) -> None:
        self._frame.setStyleSheet(
            f"""
            QFrame#safetyBanner {{
                background-color: {color};
                color: white;
                border-radius: 4px;
            }}
            QFrame#safetyBanner QLabel {{
                color: white;
            }}
            """
        )
