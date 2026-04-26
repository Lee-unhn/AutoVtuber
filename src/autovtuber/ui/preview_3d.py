"""3D 預覽器 — 包裝 QtQuick3D，由 main_window 內嵌使用。

QML 端負責所有渲染；Python 端只 set vrmPath property。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


class Preview3D:
    """工廠類別 — 建立 QQuickWidget 載入 preview_3d.qml。"""

    def __init__(self, parent: "QWidget | None" = None):
        from PySide6.QtCore import QUrl
        from PySide6.QtQuickWidgets import QQuickWidget

        self._widget = QQuickWidget(parent)
        self._widget.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)

        qml_path = Path(__file__).parent / "preview_3d.qml"
        self._widget.setSource(QUrl.fromLocalFile(str(qml_path)))

    @property
    def widget(self):
        return self._widget

    def load_vrm(self, vrm_path: Path) -> None:
        """載入 .vrm 檔到預覽器。"""
        root = self._widget.rootObject()
        if root is not None:
            root.setProperty("vrmPath", str(vrm_path))

    def clear(self) -> None:
        root = self._widget.rootObject()
        if root is not None:
            root.setProperty("vrmPath", "")
