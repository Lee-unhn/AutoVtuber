"""FaceTrackerDialog — 獨立視窗顯示 webcam + 偵測到的 VRM blendshape weight 進度條。

讓使用者在「沒開 VSeeFace」時就能驗證表情追蹤功能正常。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..utils.logging_setup import get_logger

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

_log = get_logger(__name__)


class FaceTrackerDialog:
    """工廠類別 — build() 回傳 QDialog。"""

    def __init__(self, parent: "QWidget | None" = None):
        self._parent = parent
        self._dialog = None
        self._thread = None
        self._worker = None
        self._signals = None
        self._bars: dict = {}
        self._frame_label = None

    def build(self):
        from PySide6.QtCore import Qt, QThread
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import (
            QDialog,
            QGridLayout,
            QHBoxLayout,
            QLabel,
            QProgressBar,
            QPushButton,
            QVBoxLayout,
        )

        from ..workers.face_tracker_worker import FaceTrackerWorker
        from ..workers.signals import make_face_tracker_signals

        dialog = QDialog(self._parent)
        dialog.setWindowTitle("👁️ 臉部追蹤測試")
        dialog.resize(900, 540)

        outer = QHBoxLayout(dialog)

        # 左：webcam frame
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Webcam（含 landmarks 疊加）</b>"))
        self._frame_label = QLabel()
        self._frame_label.setMinimumSize(640, 480)
        self._frame_label.setStyleSheet("background:#222;border:1px solid #444;")
        self._frame_label.setText("等待啟動...")
        self._frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self._frame_label)
        outer.addLayout(left)

        # 右：blendshape weights
        right = QVBoxLayout()
        right.addWidget(QLabel(
            "<b>偵測到的 VRM Blendshape Weights</b>"
            "<br><small>0.0 = 無 / 1.0 = 完全</small>"
        ))

        # 12 個 blendshape 進度條
        bs_groups = [
            ("情緒", ["Joy", "Angry", "Sorrow", "Fun"]),
            ("嘴型", ["A", "I", "U", "E", "O"]),
            ("眨眼", ["Blink", "Blink_L", "Blink_R"]),
        ]
        for group_name, names in bs_groups:
            right.addWidget(QLabel(f"<b>{group_name}</b>"))
            grid = QGridLayout()
            for i, name in enumerate(names):
                grid.addWidget(QLabel(name), i, 0)
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(0)
                bar.setFormat("%v%")
                self._bars[name] = bar
                grid.addWidget(bar, i, 1)
            right.addLayout(grid)
            right.addSpacing(8)

        right.addStretch()

        # 控制按鈕
        btn_row = QHBoxLayout()
        start_btn = QPushButton("▶️ 啟動追蹤")
        stop_btn = QPushButton("⏹ 停止")
        close_btn = QPushButton("關閉")
        btn_row.addWidget(start_btn)
        btn_row.addWidget(stop_btn)
        btn_row.addWidget(close_btn)
        right.addLayout(btn_row)

        outer.addLayout(right)

        # 信號連接
        self._signals = make_face_tracker_signals()
        self._signals.frame_updated.connect(self._on_frame)
        self._signals.blendshapes_updated.connect(self._on_blendshapes)
        self._signals.error.connect(self._on_error)
        self._signals.stopped.connect(self._on_stopped)

        def _start():
            if self._thread is not None and self._thread.isRunning():
                return
            self._frame_label.setText("正在啟動 webcam...")
            self._worker = FaceTrackerWorker(self._signals)
            thread = QThread()
            self._thread = thread

            from PySide6.QtCore import QObject, Signal as QtSignal

            class _Runner(QObject):
                done = QtSignal()
                def __init__(self, w):
                    super().__init__()
                    self._w = w
                def execute(self):
                    try:
                        self._w.run()
                    finally:
                        self.done.emit()

            self._runner = _Runner(self._worker)
            self._runner.moveToThread(thread)
            thread.started.connect(self._runner.execute)
            self._runner.done.connect(thread.quit)
            thread.start()
            start_btn.setEnabled(False)
            stop_btn.setEnabled(True)

        def _stop():
            if self._worker is not None:
                self._worker.stop()
            stop_btn.setEnabled(False)

        def _close():
            _stop()
            if self._thread is not None:
                self._thread.wait(2000)
            dialog.accept()

        start_btn.clicked.connect(_start)
        stop_btn.clicked.connect(_stop)
        close_btn.clicked.connect(_close)

        stop_btn.setEnabled(False)

        self._dialog = dialog
        return dialog

    # ---------------- handlers ---------------- #

    def _on_frame(self, qimage) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPixmap
        if self._frame_label is None:
            return
        pix = QPixmap.fromImage(qimage)
        self._frame_label.setPixmap(pix.scaled(
            self._frame_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def _on_blendshapes(self, weights: dict) -> None:
        for name, w in weights.items():
            bar = self._bars.get(name)
            if bar is not None:
                bar.setValue(int(w * 100))

    def _on_error(self, msg: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self._dialog, "臉部追蹤錯誤", msg)
        if self._frame_label is not None:
            self._frame_label.setText(f"錯誤：\n{msg}")

    def _on_stopped(self) -> None:
        if self._frame_label is not None:
            self._frame_label.setText("已停止")
