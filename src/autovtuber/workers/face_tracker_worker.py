"""FaceTrackerWorker — webcam capture + mediapipe + blendshape weights，跑在 QThread。

Signals:
    frame_updated(QImage) — 每幀 webcam 圖（含 landmarks 疊加）
    blendshapes_updated(dict[str, float]) — 12 個 blendshape weight
    error(str) — webcam 開啟失敗等
    stopped() — worker 停止
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..pipeline.face_tracker import FaceMeshTracker, landmarks_to_blendshapes
from ..utils.logging_setup import get_logger

if TYPE_CHECKING:
    from PySide6.QtCore import QObject

_log = get_logger(__name__)


class FaceTrackerWorker:
    """webcam → landmarks → blendshapes 即時迴圈。"""

    def __init__(self, signals: "QObject", camera_index: int = 0):
        self._signals = signals
        self._camera_index = camera_index
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        """主迴圈 — 在 QThread 內呼叫。"""
        try:
            import cv2
            import numpy as np
            from PySide6.QtGui import QImage

            cap = cv2.VideoCapture(self._camera_index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                self._signals.error.emit("無法開啟 webcam (index 0)。請確認攝影機已連接且未被其他程式佔用。")
                self._signals.stopped.emit()
                return

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)

            tracker = FaceMeshTracker()
            _log.info("FaceTrackerWorker started on camera {}", self._camera_index)

            try:
                while not self._stop:
                    ok, frame_bgr = cap.read()
                    if not ok:
                        continue
                    # mediapipe 要 RGB
                    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                    landmarks = tracker.process(frame_rgb)

                    if landmarks is not None:
                        # 計算 blendshapes
                        bs = landmarks_to_blendshapes(landmarks)
                        self._signals.blendshapes_updated.emit(bs.to_dict())
                        # 疊 landmark 點到 frame（綠色小點）
                        for x, y, _z in landmarks:
                            cv2.circle(frame_rgb, (int(x), int(y)), 1, (0, 255, 0), -1)
                    else:
                        # 沒偵測到臉 → 全 0 weight
                        self._signals.blendshapes_updated.emit(
                            {k: 0.0 for k in [
                                "Joy", "Angry", "Sorrow", "Fun",
                                "A", "I", "U", "E", "O",
                                "Blink", "Blink_L", "Blink_R",
                            ]}
                        )

                    # numpy → QImage
                    h, w, ch = frame_rgb.shape
                    img = QImage(frame_rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
                    self._signals.frame_updated.emit(img)
            finally:
                tracker.close()
                cap.release()
                _log.info("FaceTrackerWorker stopped")
                self._signals.stopped.emit()
        except Exception as e:  # noqa: BLE001
            _log.exception("FaceTrackerWorker crashed")
            self._signals.error.emit(f"{type(e).__name__}: {e}")
            self._signals.stopped.emit()
