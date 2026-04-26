"""集中所有 Qt Signal 定義 — UI 與 worker 間溝通的單一資料來源。

避免 signal 散落在各個 worker class 內難以追蹤。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtCore import QObject, Signal


def make_job_signals():
    """JobWorker 用的 signals：階段進度、完成、錯誤、健康狀態。

    用 factory function 因為 Signal 必須在 QObject subclass 內定義；
    我們在這裡集中定義 schema，讓所有 worker 共用。
    """
    from PySide6.QtCore import QObject, Signal

    class JobSignals(QObject):
        # (stage_name, current_step, total_steps)
        stage_progress = Signal(str, int, int)
        # (stage_name, succeeded, elapsed_seconds)
        stage_done = Signal(str, bool, float)
        # JobResult JSON-dumped string（避免 pydantic 物件跨執行緒）
        job_finished = Signal(str)
        # 錯誤訊息
        job_failed = Signal(str)

    return JobSignals()


def make_monitor_signals():
    """MonitorWorker 用的 signals：硬體 snapshot 推送給 UI。"""
    from PySide6.QtCore import QObject, Signal

    class MonitorSignals(QObject):
        # (state.value, vram_used_gb, vram_total_gb, gpu_temp_c, ram_pct, disk_free_gb)
        snapshot = Signal(str, float, float, int, float, float)
        emergency_triggered = Signal(str)

    return MonitorSignals()


def make_download_signals():
    """DownloadWorker 用的 signals：下載進度與完成。"""
    from PySide6.QtCore import QObject, Signal

    class DownloadSignals(QObject):
        # (key, downloaded_bytes, total_bytes)
        progress = Signal(str, int, int)
        # (key, ok, error_message)
        item_done = Signal(str, bool, str)
        all_done = Signal(bool)  # ok = 所有都成功

    return DownloadSignals()


def make_face_tracker_signals():
    """FaceTrackerWorker 用的 signals：webcam frame + blendshape weights。"""
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtGui import QImage

    class FaceTrackerSignals(QObject):
        frame_updated = Signal(QImage)             # webcam frame（含 landmarks 疊加）
        blendshapes_updated = Signal(dict)         # {VRM blendshape name: weight 0-1}
        error = Signal(str)
        stopped = Signal()

    return FaceTrackerSignals()
