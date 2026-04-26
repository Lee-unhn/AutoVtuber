"""硬體護欄相關例外。

設計原則：所有護欄例外都繼承 SafetyAbort，pipeline 只要 `except SafetyAbort` 就能優雅停止。
"""
from __future__ import annotations


class SafetyAbort(Exception):
    """通用護欄中止 — 任何 pipeline 都應該 except 這個。"""


class VRAMExceeded(SafetyAbort):
    """VRAM 超過 abort 門檻。"""

    def __init__(self, used_gb: float, limit_gb: float):
        super().__init__(
            f"VRAM {used_gb:.2f} GB exceeded abort threshold {limit_gb:.2f} GB"
        )
        self.used_gb = used_gb
        self.limit_gb = limit_gb


class OverheatPause(SafetyAbort):
    """GPU 過熱暫停（暫停可能轉 abort）。"""

    def __init__(self, temp_c: int, limit_c: int):
        super().__init__(
            f"GPU temperature {temp_c}°C exceeded {limit_c}°C — paused for cooldown"
        )
        self.temp_c = temp_c
        self.limit_c = limit_c


class RAMExceeded(SafetyAbort):
    def __init__(self, used_pct: float, limit_pct: float):
        super().__init__(
            f"System RAM {used_pct:.1f}% exceeded abort threshold {limit_pct:.1f}%"
        )
        self.used_pct = used_pct
        self.limit_pct = limit_pct


class DiskFull(SafetyAbort):
    def __init__(self, free_gb: float, limit_gb: float):
        super().__init__(
            f"Disk free {free_gb:.2f} GB below abort threshold {limit_gb:.2f} GB"
        )
        self.free_gb = free_gb
        self.limit_gb = limit_gb


class HardwareUnsupported(Exception):
    """啟動時硬體不符規格 — 應該 sys.exit，不是中止任務。"""


class UserStopRequested(SafetyAbort):
    """使用者按下緊急停止按鈕。"""

    def __init__(self, reason: str = "User pressed emergency STOP"):
        super().__init__(reason)
