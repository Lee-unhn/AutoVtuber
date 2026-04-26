"""MonitorWorker — 把 HardwareGuard 的硬體 snapshot 透過 Qt signal 推給 UI。

HardwareGuard 自己有 daemon thread；MonitorWorker 只是把它的 callback bridge 到 Qt。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..safety.hardware_guard import HardwareGuard, HardwareSnapshot, HealthState
from ..utils.logging_setup import get_logger

if TYPE_CHECKING:
    from PySide6.QtCore import QObject

_log = get_logger(__name__)


class MonitorWorker:
    """把 HardwareGuard 包成 Qt-friendly。

    用法：
        signals = make_monitor_signals()
        worker = MonitorWorker(guard, signals)
        worker.start()    # guard 自己會 spawn thread
    """

    def __init__(self, guard: HardwareGuard, signals: "QObject"):
        self._guard = guard
        self._signals = signals
        self._guard._on_state_change = self._on_state_change  # noqa: SLF001 — 直接綁定

    def start(self) -> None:
        if not self._guard._thread:  # noqa: SLF001
            self._guard.start()

    def stop(self) -> None:
        self._guard.stop()

    def trigger_emergency_stop(self, reason: str) -> None:
        self._guard.trigger_emergency_stop(reason)
        self._signals.emergency_triggered.emit(reason)

    # 內部回呼：HardwareGuard 的 state 改變時被呼叫
    def _on_state_change(self, state: HealthState, snap: HardwareSnapshot) -> None:
        try:
            self._signals.snapshot.emit(
                state.value,
                snap.vram_used_gb,
                snap.vram_total_gb,
                snap.gpu_temp_c,
                snap.ram_used_pct,
                snap.disk_free_gb,
            )
        except Exception:  # noqa: BLE001 — 不能讓 monitor thread 死掉
            _log.exception("Failed to emit monitor snapshot")
