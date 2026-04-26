"""緊急停止按鈕 — UI 永遠顯示的紅色大鈕。"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


def make_stop_button(parent: "QWidget | None" = None):
    """建立並回傳設定好樣式的 STOP 按鈕。"""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QPushButton

    btn = QPushButton(parent)
    btn.setObjectName("emergencyStopButton")
    btn.setText("🛑 STOP")
    btn.setMinimumSize(QSize(110, 40))
    f = QFont()
    f.setBold(True)
    f.setPointSize(11)
    btn.setFont(f)
    btn.setStyleSheet(
        """
        QPushButton#emergencyStopButton {
            background-color: #c62828;
            color: white;
            border: 2px solid #8e0000;
            border-radius: 6px;
            padding: 4px 12px;
        }
        QPushButton#emergencyStopButton:hover {
            background-color: #ef5350;
        }
        QPushButton#emergencyStopButton:pressed {
            background-color: #8e0000;
        }
        """
    )
    btn.setToolTip("立即停止所有生成任務 / Emergency stop all running generation jobs")
    return btn
