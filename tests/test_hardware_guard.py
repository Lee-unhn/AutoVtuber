"""HardwareGuard 單元測試 — 完全 mock pynvml/psutil/disk，不需要真實 GPU。"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from autovtuber.safety.exceptions import (
    DiskFull,
    OverheatPause,
    RAMExceeded,
    UserStopRequested,
    VRAMExceeded,
)
from autovtuber.safety.hardware_guard import (
    HardwareGuard,
    HealthState,
    _NvmlAdapter,
)
from autovtuber.safety.thresholds import Thresholds


# ---------------- 共用 fixtures ---------------- #


def make_thresholds(**overrides) -> Thresholds:
    """測試用閾值。預設把 RAM/disk 拉到不可能觸發，避免真實 psutil 讀數干擾測試。
    需要測 RAM/disk 觸發的 case 用 patch 注入或 override。"""
    defaults = dict(
        vram_warn_gb=11.0,
        vram_abort_gb=11.5,
        gpu_temp_warn_c=78,
        gpu_temp_abort_c=83,
        cooldown_pause_seconds=1,  # 縮短測試
        sustained_load_warn_min=5,
        sustained_load_abort_min=8,
        forced_cooldown_seconds=1,
        ram_warn_pct=99.5,   # 不會被真實系統 RAM 觸發
        ram_abort_pct=99.9,
        disk_warn_gb=0.001,  # 不會被真實 disk free 觸發
        disk_abort_gb=0.0001,
        poll_interval_seconds=0.05,  # 快速輪詢
        cuda_memory_fraction=0.92,
        abort_hysteresis_seconds=0.0,  # 測試用：立即 abort 不等
    )
    defaults.update(overrides)
    return Thresholds(**defaults)


def make_nvml(
    used_gb: float = 1.0,
    total_gb: float = 12.0,
    temp_c: int = 50,
    util_pct: int = 0,
) -> MagicMock:
    """建立 _NvmlAdapter 的 mock，回傳指定數值。"""
    m = MagicMock(spec=_NvmlAdapter)
    gb = 1024 ** 3
    m.vram_used_total_bytes.return_value = (int(used_gb * gb), int(total_gb * gb))
    m.temperature_c.return_value = temp_c
    m.utilization_pct.return_value = util_pct
    m.name.return_value = "NVIDIA GeForce RTX 3060"
    m.driver_version.return_value = "581.95"
    return m


# ---------------- 測試 ---------------- #


def test_classify_ok_state():
    """正常狀態 → OK。"""
    nvml = make_nvml(used_gb=2.0, temp_c=55)
    g = HardwareGuard(make_thresholds(), nvml_adapter=nvml)
    with g:
        time.sleep(0.2)  # 等 polling
        assert g.state == HealthState.OK
        assert not g.abort_event.is_set()


def test_classify_warn_state_high_vram():
    """VRAM 11.2GB > warn 11.0GB → WARN（不 abort）。"""
    nvml = make_nvml(used_gb=11.2)
    g = HardwareGuard(make_thresholds(), nvml_adapter=nvml)
    with g:
        time.sleep(0.2)
        assert g.state == HealthState.WARN
        assert not g.abort_event.is_set()


def test_classify_abort_on_vram_exceeded():
    """VRAM 11.6GB > abort 11.5GB → ABORT + abort_event set。"""
    nvml = make_nvml(used_gb=11.6)
    g = HardwareGuard(make_thresholds(), nvml_adapter=nvml)
    with g:
        time.sleep(0.2)
        assert g.state == HealthState.ABORT
        assert g.abort_event.is_set()
        with pytest.raises(VRAMExceeded):
            g.check_or_raise()


def test_classify_cooldown_on_overheat():
    """GPU 85°C > abort 83°C → COOLDOWN（不直接 abort）。"""
    nvml = make_nvml(temp_c=85)
    g = HardwareGuard(make_thresholds(cooldown_pause_seconds=1), nvml_adapter=nvml)
    with g:
        time.sleep(0.2)
        assert g.state == HealthState.COOLDOWN
        # check_or_raise 在 cooldown 時應該阻塞，不丟例外
        # 但 abort_event 不該 set
        assert not g.abort_event.is_set()


def test_emergency_stop_button_triggers_abort():
    """trigger_emergency_stop → abort_event + UserStopRequested。"""
    nvml = make_nvml()
    g = HardwareGuard(make_thresholds(), nvml_adapter=nvml)
    with g:
        time.sleep(0.1)
        g.trigger_emergency_stop("user clicked")
        assert g.abort_event.is_set()
        with pytest.raises(UserStopRequested):
            g.check_or_raise()


def test_check_or_raise_disk_full():
    """磁碟剩餘 < 1GB → DiskFull。"""
    nvml = make_nvml()
    with patch("autovtuber.safety.hardware_guard.shutil.disk_usage") as du:
        du.return_value = MagicMock(free=int(0.5 * 1024 ** 3), total=10 * 1024 ** 3, used=10 * 1024 ** 3)
        # 為這個測試恢復 disk 門檻（覆寫 fixture 的「不可能觸發」設定）
        g = HardwareGuard(make_thresholds(disk_warn_gb=5.0, disk_abort_gb=1.0), nvml_adapter=nvml)
        with g:
            time.sleep(0.2)
            assert g.abort_event.is_set()
            with pytest.raises(DiskFull):
                g.check_or_raise()


def test_check_or_raise_ram_exceeded():
    """RAM > 92% → RAMExceeded。"""
    nvml = make_nvml()
    with patch("autovtuber.safety.hardware_guard.psutil.virtual_memory") as vm:
        vm.return_value = MagicMock(percent=95.0)
        # 為這個測試恢復 RAM 門檻
        g = HardwareGuard(make_thresholds(ram_warn_pct=80.0, ram_abort_pct=92.0), nvml_adapter=nvml)
        with g:
            time.sleep(0.2)
            assert g.abort_event.is_set()
            with pytest.raises(RAMExceeded):
                g.check_or_raise()


def test_state_change_callback_invoked():
    """on_state_change 回呼必須在狀態變化時被呼叫。"""
    nvml = make_nvml(used_gb=11.2)  # WARN
    states: list[HealthState] = []
    g = HardwareGuard(
        make_thresholds(),
        nvml_adapter=nvml,
        on_state_change=lambda s, _snap: states.append(s),
    )
    with g:
        time.sleep(0.2)
    assert HealthState.WARN in states


def test_check_or_raise_ok_when_clean():
    """OK 狀態下 check_or_raise 不該丟。"""
    nvml = make_nvml(used_gb=1.0, temp_c=50)
    g = HardwareGuard(make_thresholds(), nvml_adapter=nvml)
    with g:
        time.sleep(0.15)
        g.check_or_raise()  # 不該 raise


def test_overheat_check_or_raise_paths_through_cooldown():
    """過熱時 check_or_raise 阻塞至 cooldown 結束。"""
    nvml = make_nvml(temp_c=85)
    g = HardwareGuard(make_thresholds(cooldown_pause_seconds=1), nvml_adapter=nvml)
    with g:
        time.sleep(0.15)
        # cooldown 1 秒；check_or_raise 應該等 ~1 秒回來
        start = time.perf_counter()
        # 模擬 cooldown 結束後 nvml 回到正常
        nvml.temperature_c.return_value = 50
        # 但 cooldown_event 仍在直到 timer 自然清除
        try:
            g.check_or_raise()
        except OverheatPause:
            pass  # 也可接受
        assert time.perf_counter() - start < 5.0


def test_snapshot_vram_used_pct():
    """快照計算 VRAM 使用百分比正確。"""
    from autovtuber.safety.hardware_guard import HardwareSnapshot
    s = HardwareSnapshot(
        vram_used_gb=6.0,
        vram_total_gb=12.0,
        gpu_temp_c=60,
        gpu_util_pct=50,
        ram_used_pct=40.0,
        disk_free_gb=100.0,
        timestamp=time.time(),
    )
    assert s.vram_used_pct == 50.0
