"""硬體護欄閾值。

⚠️ 修改前請讀 docs/HARDWARE_PROTOCOL.md 與 AUTOVTUBER.md「電腦保護護欄」章節。
這些不是建議值，是「不弄壞電腦」的硬性合約。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config.settings import SafetySettings


@dataclass(frozen=True)
class Thresholds:
    """所有硬體門檻 — 從 SafetySettings 投影過來，凍結後傳入 HardwareGuard。"""

    vram_warn_gb: float
    vram_abort_gb: float
    gpu_temp_warn_c: int
    gpu_temp_abort_c: int
    cooldown_pause_seconds: int
    sustained_load_warn_min: int
    sustained_load_abort_min: int
    forced_cooldown_seconds: int
    ram_warn_pct: float
    ram_abort_pct: float
    disk_warn_gb: float
    disk_abort_gb: float
    poll_interval_seconds: float
    cuda_memory_fraction: float
    abort_hysteresis_seconds: float = 3.0  # 連續超 abort 門檻 N 秒才真 abort（避免 spike 誤觸）

    @classmethod
    def from_settings(cls, s: SafetySettings) -> "Thresholds":
        return cls(
            vram_warn_gb=s.vram_warn_gb,
            vram_abort_gb=s.vram_abort_gb,
            gpu_temp_warn_c=s.gpu_temp_warn_c,
            gpu_temp_abort_c=s.gpu_temp_abort_c,
            cooldown_pause_seconds=60,
            sustained_load_warn_min=5,
            sustained_load_abort_min=8,
            forced_cooldown_seconds=30,
            ram_warn_pct=s.ram_warn_pct,
            ram_abort_pct=s.ram_abort_pct,
            disk_warn_gb=s.disk_warn_gb,
            disk_abort_gb=s.disk_abort_gb,
            poll_interval_seconds=s.poll_interval_seconds,
            cuda_memory_fraction=s.cuda_memory_fraction,
            abort_hysteresis_seconds=s.abort_hysteresis_seconds,
        )


# ---------------- 啟動拒絕門檻 ---------------- #

#: 低於此 VRAM 拒絕啟動（GiB）。RTX 3060 12GB 滿足。
MIN_VRAM_GB: float = 10.0

#: 顯卡驅動最低版本 (major, minor)
MIN_DRIVER_VERSION: tuple[int, int] = (550, 0)

#: 唯一支援的 GPU 廠商
REQUIRED_GPU_VENDOR: str = "NVIDIA"
