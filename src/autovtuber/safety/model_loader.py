"""ModelLoader — 強制執行「同時間 GPU 上只能有一個重模型」的不變式。

任何 ≥ 1GB VRAM 的模型必須透過 acquire() 取得；loader 會：
    1. 先卸載目前駐留模型
    2. torch.cuda.empty_cache() + gc.collect()
    3. 呼叫 HardwareGuard.check_or_raise() 確認可載入
    4. 呼叫 user-supplied loader_fn() 載入新模型
    5. 套用 per-model 安全設定（CPU offload、memory_fraction）
    6. context exit 時自動卸載（無論成功失敗）
"""
from __future__ import annotations

import gc
import threading
from contextlib import contextmanager
from enum import Enum
from typing import Any, Callable, Iterator

from ..utils.logging_setup import get_logger
from .exceptions import SafetyAbort
from .hardware_guard import HardwareGuard

_log = get_logger(__name__)


class ModelKind(Enum):
    OLLAMA = "ollama"           # 在 Ollama 子程序，但仍佔 GPU
    SDXL = "sdxl"
    INSIGHT_FACE = "insightface"  # CPU only，但仍走同 loader 介面以統一管理
    TRIPO_SR = "triposr"          # Image-to-3D (TripoSR / stabilityai)
    NONE = "none"


# 各模型粗估的 VRAM 預算（GB）— 用於日誌與安全評估，不強制
_VRAM_BUDGET_GB: dict[ModelKind, float] = {
    ModelKind.OLLAMA: 6.0,
    ModelKind.SDXL: 10.5,
    ModelKind.INSIGHT_FACE: 0.0,  # CPU
    ModelKind.TRIPO_SR: 6.0,      # 官方 README 稱 ~6GB；marching cubes 走 CPU shim
    ModelKind.NONE: 0.0,
}


class ModelLoader:
    """單例式 GPU 模型守門員。

    所有 acquire() 呼叫都被 _CLASS_LOCK 序列化，保證任何時刻 _CURRENT 唯一。
    """

    _CURRENT: ModelKind = ModelKind.NONE
    _CURRENT_OBJ: Any = None
    _CURRENT_UNLOADER: Callable[[Any], None] | None = None
    _CLASS_LOCK = threading.RLock()

    def __init__(self, guard: HardwareGuard):
        self._guard = guard

    # ---------- public API ---------- #

    @classmethod
    def currently_loaded(cls) -> ModelKind:
        with cls._CLASS_LOCK:
            return cls._CURRENT

    @contextmanager
    def acquire(
        self,
        kind: ModelKind,
        loader_fn: Callable[[], Any],
        unloader_fn: Callable[[Any], None] | None = None,
    ) -> Iterator[Any]:
        """以 context manager 方式取得模型；確保唯一性與安全性。

        Args:
            kind: 模型種類
            loader_fn: 無參數函式，回傳載入後的模型物件
            unloader_fn: 接受模型物件、執行卸載；為 None 則僅 del + cuda cache

        Yields:
            loader_fn 的回傳值

        Raises:
            SafetyAbort: HardwareGuard 中止
        """
        with ModelLoader._CLASS_LOCK:
            self._guard.check_or_raise()
            self._evict_current()
            self._guard.check_or_raise()

            _log.info(
                "📦 Loading {} (estimated peak VRAM ~{:.1f} GB)",
                kind.value,
                _VRAM_BUDGET_GB.get(kind, 0.0),
            )
            try:
                obj = loader_fn()
            except SafetyAbort:
                raise
            except Exception:
                _log.exception("loader_fn for {} raised", kind.value)
                self._evict_current()
                raise

            ModelLoader._CURRENT = kind
            ModelLoader._CURRENT_OBJ = obj
            ModelLoader._CURRENT_UNLOADER = unloader_fn

            try:
                self._post_load_safety(kind)
                yield obj
            finally:
                # 一定要釋放
                self._evict_current()

    # ---------- internal ---------- #

    def _evict_current(self) -> None:
        """卸載目前駐留模型（無論種類）；安全 idempotent。"""
        with ModelLoader._CLASS_LOCK:
            if ModelLoader._CURRENT is ModelKind.NONE:
                self._cuda_clean()
                return

            kind = ModelLoader._CURRENT
            obj = ModelLoader._CURRENT_OBJ
            unloader = ModelLoader._CURRENT_UNLOADER
            _log.info("🗑️  Unloading {}", kind.value)

            if unloader is not None and obj is not None:
                try:
                    unloader(obj)
                except Exception:  # noqa: BLE001
                    _log.exception("unloader for {} raised — continuing", kind.value)

            ModelLoader._CURRENT = ModelKind.NONE
            ModelLoader._CURRENT_OBJ = None
            ModelLoader._CURRENT_UNLOADER = None
            self._cuda_clean()

    @staticmethod
    def _cuda_clean() -> None:
        """釋放 CUDA cache + gc。即使沒有 torch 也安全（套件可能未裝）。"""
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except ImportError:
            pass

    def _post_load_safety(self, kind: ModelKind) -> None:
        """套用 per-model 安全設定。"""
        if kind is ModelKind.SDXL:
            try:
                import torch
                if torch.cuda.is_available():
                    fraction = self._guard.thresholds.cuda_memory_fraction
                    torch.cuda.set_per_process_memory_fraction(fraction, device=0)
                    _log.debug("torch.cuda memory fraction set to {}", fraction)
            except Exception:  # noqa: BLE001
                _log.exception("Failed to apply CUDA memory_fraction")
