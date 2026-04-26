"""HardwareGuard — 即時硬體監控 + 中止訊號。

職責：
    1. Daemon thread 每 N 秒輪詢 pynvml/psutil/disk
    2. 維護 abort_event 與 cooldown_event 兩個 threading.Event
    3. 偵測閾值跨越時：
        - WARN：log + on_state_change 通知（UI 變黃燈）
        - ABORT：set abort_event、log、通知（UI 變紅燈）
        - COOLDOWN：set cooldown_event 暫停 N 秒
    4. 提供 check_or_raise() 給 pipeline 在每個關鍵點呼叫

設計原則：
    - 唯讀執行緒，不直接終止 pipeline；pipeline 必須主動 check
    - emergency stop 由 UI 呼叫 trigger_emergency_stop()，立即 set abort
    - 啟動失敗（無 GPU 等）由 precheck_hardware_or_exit() 處理，不在 thread 內
"""
from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

import psutil

from ..utils.logging_setup import get_logger
from .exceptions import (
    DiskFull,
    HardwareUnsupported,
    OverheatPause,
    RAMExceeded,
    SafetyAbort,
    UserStopRequested,
    VRAMExceeded,
)
from .thresholds import (
    MIN_DRIVER_VERSION,
    MIN_VRAM_GB,
    REQUIRED_GPU_VENDOR,
    Thresholds,
)

_log = get_logger(__name__)


# ---------------- 資料類別 ---------------- #


class HealthState(Enum):
    OK = "ok"
    WARN = "warn"
    ABORT = "abort"
    COOLDOWN = "cooldown"


@dataclass
class HardwareSnapshot:
    """單次輪詢的快照。所有欄位皆為已知；數值單位見命名。"""

    vram_used_gb: float
    vram_total_gb: float
    gpu_temp_c: int
    gpu_util_pct: int
    ram_used_pct: float
    disk_free_gb: float
    timestamp: float

    @property
    def vram_used_pct(self) -> float:
        return (self.vram_used_gb / self.vram_total_gb * 100.0) if self.vram_total_gb else 0.0


# ---------------- pynvml 包裝 ---------------- #


class _NvmlAdapter:
    """把 pynvml 隔離在這層，方便 unit test mock 掉。"""

    def __init__(self):
        import pynvml

        self._pynvml = pynvml
        pynvml.nvmlInit()
        self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)

    def name(self) -> str:
        out = self._pynvml.nvmlDeviceGetName(self._handle)
        return out.decode() if isinstance(out, bytes) else out

    def vram_used_total_bytes(self) -> tuple[int, int]:
        info = self._pynvml.nvmlDeviceGetMemoryInfo(self._handle)
        return info.used, info.total

    def temperature_c(self) -> int:
        return int(
            self._pynvml.nvmlDeviceGetTemperature(self._handle, self._pynvml.NVML_TEMPERATURE_GPU)
        )

    def utilization_pct(self) -> int:
        return int(self._pynvml.nvmlDeviceGetUtilizationRates(self._handle).gpu)

    def driver_version(self) -> str:
        out = self._pynvml.nvmlSystemGetDriverVersion()
        return out.decode() if isinstance(out, bytes) else out

    def shutdown(self) -> None:
        try:
            self._pynvml.nvmlShutdown()
        except Exception:  # noqa: BLE001 — shutdown best-effort
            pass


# ---------------- HardwareGuard 主體 ---------------- #


class HardwareGuard:
    """單例硬體監控器；用 with HardwareGuard(...) as g 啟動 daemon。"""

    def __init__(
        self,
        thresholds: Thresholds,
        on_state_change: Callable[[HealthState, HardwareSnapshot], None] | None = None,
        nvml_adapter: _NvmlAdapter | None = None,
        poll_root_path: str = "G:\\",
    ):
        self.thresholds = thresholds
        self._on_state_change = on_state_change
        self._nvml = nvml_adapter
        self._poll_root_path = poll_root_path

        self._abort_event = threading.Event()
        self._cooldown_event = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest: HardwareSnapshot | None = None
        self._abort_snapshot: HardwareSnapshot | None = None  # 保留 abort 觸發當下的 snapshot
        self._abort_reason: str | None = None
        self._state: HealthState = HealthState.OK
        self._sustained_load_start: float | None = None
        # Hysteresis: 連續超標的時間（秒）；超過 _ABORT_HYSTERESIS_SEC 才真 abort
        self._overage_start: float | None = None
        self._thread: threading.Thread | None = None

    # ---------- lifecycle ---------- #

    def start(self) -> None:
        if self._nvml is None:
            self._nvml = _NvmlAdapter()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="HardwareGuard",
            daemon=True,
        )
        self._thread.start()
        _log.info("HardwareGuard started — polling every {}s", self.thresholds.poll_interval_seconds)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        if self._nvml is not None:
            self._nvml.shutdown()
        _log.info("HardwareGuard stopped")

    def __enter__(self) -> "HardwareGuard":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # ---------- public read API ---------- #

    @property
    def abort_event(self) -> threading.Event:
        return self._abort_event

    @property
    def state(self) -> HealthState:
        return self._state

    def latest(self) -> HardwareSnapshot | None:
        with self._lock:
            return self._latest

    # ---------- pipeline 呼叫點 ---------- #

    def check_or_raise(self) -> None:
        """Pipeline 在每個關鍵點呼叫；abort 則拋例外，cooldown 則睡到結束。

        優先使用 abort 觸發當下的 snapshot 與已記錄原因，避免「事後 RAM 已恢復」
        造成原因誤判為 UserStopRequested 的 bug。
        """
        if self._abort_event.is_set():
            snap = self._abort_snapshot or self.latest()
            if self._abort_reason:
                # 已有具體原因 — 用記錄的 snapshot 重建例外
                t = self.thresholds
                if self._abort_reason.startswith("USERSTOP"):
                    raise UserStopRequested(self._abort_reason)
                if snap is not None:
                    if "VRAM" in self._abort_reason:
                        raise VRAMExceeded(snap.vram_used_gb, t.vram_abort_gb)
                    if "TEMP" in self._abort_reason:
                        raise OverheatPause(snap.gpu_temp_c, t.gpu_temp_abort_c)
                    if "RAM" in self._abort_reason:
                        raise RAMExceeded(snap.ram_used_pct, t.ram_abort_pct)
                    if "DISK" in self._abort_reason:
                        raise DiskFull(snap.disk_free_gb, t.disk_abort_gb)
                raise SafetyAbort(self._abort_reason)
            if snap is None:
                raise SafetyAbort("HardwareGuard tripped (no snapshot)")
            # 沒有記錄原因（emergency stop 等）— 走 fallback
            raise UserStopRequested()
        while self._cooldown_event.is_set() and not self._stop.is_set():
            time.sleep(0.5)

    def trigger_emergency_stop(self, reason: str = "User pressed STOP") -> None:
        """UI 緊急停止鈕呼叫此方法。"""
        _log.warning("🛑 Emergency stop: {}", reason)
        # USERSTOP marker 讓 check_or_raise 抛 UserStopRequested 而非通用 SafetyAbort
        self._set_abort(f"USERSTOP: {reason}", self.latest())
        self._update_state(HealthState.ABORT)

    def _set_abort(self, reason: str, snap: HardwareSnapshot | None) -> None:
        """記錄 abort 原因 + 觸發當下 snapshot，供 check_or_raise() 後續查詢。"""
        if not self._abort_event.is_set():
            self._abort_reason = reason
            self._abort_snapshot = snap
            _log.warning("Setting ABORT: {}", reason)
        self._abort_event.set()

    def try_clear_abort_if_recovered(self, source: str = "") -> bool:
        """嘗試清除 abort 狀態 — 僅當：
            (1) 不是 USERSTOP（使用者按的不可清）
            (2) 當前 snapshot 全部低於 abort 門檻（resource 不再爆）
                 — 注意：可能仍在 WARN 區間，但抢救空間夠
            (3) 給足夠 buffer（5% 以上於 abort 門檻）

        用於 pipeline 自處 transient spike：例如 Ollama 載入瞬間 RAM 高峰，
        卸載後 RAM 回落，可繼續執行 SDXL 階段。

        Returns: True 若成功清除。
        """
        if not self._abort_event.is_set():
            return True
        if self._abort_reason and self._abort_reason.startswith("USERSTOP"):
            return False
        # 強制取最新 snapshot（避免 polling lag 導致看到 stale 資料）
        if self._nvml is not None:
            try:
                fresh = self._collect_snapshot()
                with self._lock:
                    self._latest = fresh
                snap = fresh
            except Exception:  # noqa: BLE001
                snap = self.latest()
        else:
            snap = self.latest()
        if snap is None:
            return False
        t = self.thresholds
        # 給 5% buffer 避免馬上又跳回 abort
        vram_ok = snap.vram_used_gb < (t.vram_abort_gb - 0.5)
        temp_ok = snap.gpu_temp_c < (t.gpu_temp_abort_c - 3)
        ram_ok = snap.ram_used_pct < (t.ram_abort_pct - 5)
        disk_ok = snap.disk_free_gb > (t.disk_abort_gb + 1.0)
        if vram_ok and temp_ok and ram_ok and disk_ok:
            old = self._abort_reason
            self._abort_event.clear()
            self._abort_reason = None
            self._abort_snapshot = None
            self._update_state(HealthState.WARN if (
                snap.ram_used_pct > t.ram_warn_pct or snap.vram_used_gb > t.vram_warn_gb
            ) else HealthState.OK)
            _log.info(
                "Cleared ABORT (recovered: vram={:.1f}GB ram={:.1f}%, was: {}, source: {})",
                snap.vram_used_gb, snap.ram_used_pct, old, source or "auto",
            )
            return True
        _log.warning(
            "try_clear_abort: not yet recovered — vram={:.1f}GB({}) temp={}°C({}) ram={:.1f}%({}) disk={:.1f}GB({})",
            snap.vram_used_gb, "OK" if vram_ok else "HIGH",
            snap.gpu_temp_c, "OK" if temp_ok else "HIGH",
            snap.ram_used_pct, "OK" if ram_ok else "HIGH",
            snap.disk_free_gb, "OK" if disk_ok else "LOW",
        )
        return False

    # ---------- internal ---------- #

    def _poll_loop(self) -> None:
        assert self._nvml is not None
        interval = self.thresholds.poll_interval_seconds
        while not self._stop.is_set():
            try:
                snap = self._collect_snapshot()
                with self._lock:
                    self._latest = snap
                new_state = self._classify(snap)
                if new_state != self._state:
                    _log.info("HardwareGuard state: {} → {}", self._state.value, new_state.value)
                    self._update_state(new_state)
            except Exception as e:  # noqa: BLE001 — 不能讓 monitor thread 自殺
                _log.exception("HardwareGuard poll error: {}", e)
            self._stop.wait(interval)

    def _collect_snapshot(self) -> HardwareSnapshot:
        used_b, total_b = self._nvml.vram_used_total_bytes()
        gb = 1024 ** 3
        ram = psutil.virtual_memory()
        disk = shutil.disk_usage(self._poll_root_path)
        return HardwareSnapshot(
            vram_used_gb=used_b / gb,
            vram_total_gb=total_b / gb,
            gpu_temp_c=self._nvml.temperature_c(),
            gpu_util_pct=self._nvml.utilization_pct(),
            ram_used_pct=ram.percent,
            disk_free_gb=disk.free / gb,
            timestamp=time.time(),
        )

    def _classify(self, snap: HardwareSnapshot) -> HealthState:
        t = self.thresholds
        now = time.time()

        # 偵測是否「正在超 abort 門檻」
        over_vram = snap.vram_used_gb > t.vram_abort_gb
        over_ram = snap.ram_used_pct > t.ram_abort_pct
        over_disk = snap.disk_free_gb < t.disk_abort_gb

        if over_vram or over_ram or over_disk:
            if self._overage_start is None:
                self._overage_start = now  # 第一次超 — 開始計時
                # 不立即 abort，繼續觀察
            elif (now - self._overage_start) >= t.abort_hysteresis_seconds:
                # 連續超過 hysteresis 時間 — 真 abort
                if over_vram:
                    self._set_abort(
                        f"VRAM sustained {snap.vram_used_gb:.2f}/{t.vram_abort_gb:.2f}GB "
                        f"for {t.abort_hysteresis_seconds}s", snap)
                elif over_ram:
                    self._set_abort(
                        f"RAM sustained {snap.ram_used_pct:.1f}%/{t.ram_abort_pct:.1f}% "
                        f"for {t.abort_hysteresis_seconds}s", snap)
                else:
                    self._set_abort(
                        f"DISK sustained {snap.disk_free_gb:.2f}/{t.disk_abort_gb:.2f}GB "
                        f"for {t.abort_hysteresis_seconds}s", snap)
                return HealthState.ABORT
        else:
            self._overage_start = None  # 回到安全範圍，重置計時

        # 過熱仍立即 cooldown（不需 hysteresis — 溫度有物理慣性）
        if snap.gpu_temp_c > t.gpu_temp_abort_c:
            self._enter_cooldown(t.cooldown_pause_seconds)
            return HealthState.COOLDOWN

        # 持續滿載偵測
        if snap.gpu_util_pct >= 99:
            now = time.time()
            if self._sustained_load_start is None:
                self._sustained_load_start = now
            elif (now - self._sustained_load_start) > t.sustained_load_abort_min * 60:
                _log.warning("Sustained 100% GPU load > {} min, forced cooldown",
                             t.sustained_load_abort_min)
                self._enter_cooldown(t.forced_cooldown_seconds)
                self._sustained_load_start = None
                return HealthState.COOLDOWN
        else:
            self._sustained_load_start = None

        # WARN 條件
        if (
            snap.vram_used_gb > t.vram_warn_gb
            or snap.gpu_temp_c > t.gpu_temp_warn_c
            or snap.ram_used_pct > t.ram_warn_pct
            or snap.disk_free_gb < t.disk_warn_gb
        ):
            return HealthState.WARN

        return HealthState.OK

    def _enter_cooldown(self, seconds: int) -> None:
        if self._cooldown_event.is_set():
            return
        self._cooldown_event.set()
        _log.warning("🌡️ Entering {}s cooldown", seconds)

        def _release():
            time.sleep(seconds)
            self._cooldown_event.clear()
            _log.info("🌡️ Cooldown released")

        threading.Thread(target=_release, daemon=True).start()

    def _update_state(self, state: HealthState) -> None:
        self._state = state
        if self._on_state_change is not None and self._latest is not None:
            try:
                self._on_state_change(state, self._latest)
            except Exception:  # noqa: BLE001 — UI 回呼不能影響 monitor thread
                _log.exception("on_state_change callback raised")


# ---------------- 啟動硬體檢查 ---------------- #


def precheck_hardware_or_exit() -> None:
    """應用啟動最早期呼叫；不符規格就拋 HardwareUnsupported。

    main.py 應 catch 這個例外，顯示對話框後 sys.exit(1)。
    """
    try:
        adapter = _NvmlAdapter()
    except Exception as e:
        raise HardwareUnsupported(
            f"找不到 NVIDIA GPU 或 nvml 初始化失敗：{e}\n"
            f"AutoVtuber 需要 NVIDIA 顯卡（VRAM ≥ {MIN_VRAM_GB} GB）。"
        ) from e

    try:
        name = adapter.name()
        if REQUIRED_GPU_VENDOR not in name.upper() and "NVIDIA" not in name.upper():
            raise HardwareUnsupported(
                f"偵測到非 NVIDIA GPU：{name}\nAutoVtuber 僅支援 NVIDIA 顯卡。"
            )
        _, total_b = adapter.vram_used_total_bytes()
        total_gb = total_b / (1024 ** 3)
        if total_gb < MIN_VRAM_GB:
            raise HardwareUnsupported(
                f"GPU VRAM 僅 {total_gb:.1f} GB，低於最低需求 {MIN_VRAM_GB} GB。"
            )
        driver = adapter.driver_version()
        major = int(driver.split(".")[0])
        if major < MIN_DRIVER_VERSION[0]:
            raise HardwareUnsupported(
                f"NVIDIA 驅動版本 {driver} 過舊，需 ≥ {MIN_DRIVER_VERSION[0]}.x。"
            )
        _log.info(
            "✅ 硬體檢查通過：{} / VRAM {:.1f} GB / Driver {}",
            name,
            total_gb,
            driver,
        )
    finally:
        adapter.shutdown()
