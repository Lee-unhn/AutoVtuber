"""顏色選擇器 widget — 供髮色 / 眼色用。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


class HexColorPicker:
    """Label + 色塊預覽 + 「選擇顏色」按鈕。"""

    def __init__(
        self,
        label: str,
        initial_hex: str = "#5B3A29",
        on_change: Callable[[str], None] | None = None,
        parent: "QWidget | None" = None,
    ):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget, QColorDialog

        self._on_change = on_change
        self._color_hex = initial_hex
        self._dialog_cls = QColorDialog
        self._qcolor_cls = QColor

        self._widget = QWidget(parent)
        layout = QHBoxLayout(self._widget)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel(label))

        self._swatch = QLabel()
        self._swatch.setFixedSize(40, 24)
        self._swatch.setStyleSheet(f"background:{initial_hex}; border:1px solid #555;")
        layout.addWidget(self._swatch)

        self._hex_label = QLabel(initial_hex)
        self._hex_label.setMinimumWidth(70)
        layout.addWidget(self._hex_label)

        btn = QPushButton("選擇")
        btn.clicked.connect(self._open_dialog)
        layout.addWidget(btn)
        layout.addStretch()

    @property
    def widget(self):
        return self._widget

    @property
    def hex_value(self) -> str:
        return self._color_hex

    def set_hex(self, value: str) -> None:
        self._color_hex = value
        self._swatch.setStyleSheet(f"background:{value}; border:1px solid #555;")
        self._hex_label.setText(value)
        if self._on_change:
            self._on_change(value)

    def _open_dialog(self) -> None:
        initial = self._qcolor_cls(self._color_hex)
        chosen = self._dialog_cls.getColor(initial, self._widget, "選擇顏色")
        if chosen.isValid():
            hex_str = chosen.name()  # "#rrggbb"
            self.set_hex(hex_str.upper())
