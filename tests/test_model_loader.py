"""ModelLoader 單元測試 — 驗證「同時間 GPU 上只有一個重模型」的不變式。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from autovtuber.safety.exceptions import SafetyAbort
from autovtuber.safety.model_loader import ModelKind, ModelLoader


def make_guard(abort: bool = False) -> MagicMock:
    g = MagicMock()
    g.thresholds = MagicMock(cuda_memory_fraction=0.92)
    if abort:
        g.check_or_raise.side_effect = SafetyAbort("forced abort")
    else:
        g.check_or_raise.return_value = None
    return g


def setup_function(_fn):
    """每個測試開始前重設 ModelLoader 全域狀態。"""
    ModelLoader._CURRENT = ModelKind.NONE
    ModelLoader._CURRENT_OBJ = None
    ModelLoader._CURRENT_UNLOADER = None


def test_acquire_loads_and_unloads():
    """正常流程：acquire 內 currently_loaded 是該 kind，離開後是 NONE。"""
    guard = make_guard()
    loader = ModelLoader(guard)

    sentinel = object()
    unload_calls = []

    with loader.acquire(
        ModelKind.SDXL,
        loader_fn=lambda: sentinel,
        unloader_fn=lambda obj: unload_calls.append(obj),
    ) as obj:
        assert obj is sentinel
        assert ModelLoader.currently_loaded() is ModelKind.SDXL

    assert ModelLoader.currently_loaded() is ModelKind.NONE
    assert unload_calls == [sentinel]


def test_acquire_evicts_previous_model():
    """連續兩個 acquire：第二個必須先 evict 第一個。"""
    guard = make_guard()
    loader = ModelLoader(guard)

    unload_log = []

    with loader.acquire(
        ModelKind.OLLAMA,
        loader_fn=lambda: "ollama_obj",
        unloader_fn=lambda o: unload_log.append(("unload", o)),
    ):
        pass  # 退出時 unload

    assert unload_log == [("unload", "ollama_obj")]
    assert ModelLoader.currently_loaded() is ModelKind.NONE

    # 載入第二個
    with loader.acquire(
        ModelKind.SDXL,
        loader_fn=lambda: "sdxl_obj",
        unloader_fn=lambda o: unload_log.append(("unload2", o)),
    ):
        assert ModelLoader.currently_loaded() is ModelKind.SDXL

    assert unload_log == [("unload", "ollama_obj"), ("unload2", "sdxl_obj")]


def test_acquire_aborts_when_guard_says_abort_before_load():
    """guard.check_or_raise 拋例外 → loader_fn 不該被呼叫。"""
    guard = make_guard(abort=True)
    loader = ModelLoader(guard)

    loaded = []
    with pytest.raises(SafetyAbort):
        with loader.acquire(ModelKind.SDXL, loader_fn=lambda: loaded.append("x") or "obj"):
            pass

    assert loaded == []
    assert ModelLoader.currently_loaded() is ModelKind.NONE


def test_acquire_unloads_on_exception_inside_block():
    """使用者區塊內拋例外 → 仍應卸載。"""
    guard = make_guard()
    loader = ModelLoader(guard)
    unload_calls = []

    with pytest.raises(RuntimeError, match="boom"):
        with loader.acquire(
            ModelKind.SDXL,
            loader_fn=lambda: "obj",
            unloader_fn=lambda o: unload_calls.append(o),
        ):
            raise RuntimeError("boom")

    assert unload_calls == ["obj"]
    assert ModelLoader.currently_loaded() is ModelKind.NONE


def test_acquire_unloads_when_loader_fn_raises():
    """loader_fn 自己拋例外 → 不應該留下髒狀態。"""
    guard = make_guard()
    loader = ModelLoader(guard)

    def bad_loader():
        raise ValueError("cannot load")

    with pytest.raises(ValueError, match="cannot load"):
        with loader.acquire(ModelKind.SDXL, loader_fn=bad_loader):
            pass

    assert ModelLoader.currently_loaded() is ModelKind.NONE


def test_unloader_exception_does_not_break_invariant():
    """unloader 拋例外仍要清空 _CURRENT。"""
    guard = make_guard()
    loader = ModelLoader(guard)

    def bad_unloader(_obj):
        raise IOError("fail")

    with loader.acquire(ModelKind.OLLAMA, loader_fn=lambda: "x", unloader_fn=bad_unloader):
        pass

    assert ModelLoader.currently_loaded() is ModelKind.NONE


def test_no_unloader_still_evicts_state():
    """沒給 unloader_fn 也要清掉狀態（依靠 cuda_clean）。"""
    guard = make_guard()
    loader = ModelLoader(guard)

    with loader.acquire(ModelKind.SDXL, loader_fn=lambda: "x"):
        assert ModelLoader.currently_loaded() is ModelKind.SDXL

    assert ModelLoader.currently_loaded() is ModelKind.NONE


def test_currently_loaded_thread_safe_basic():
    """currently_loaded 在持鎖下讀取，不應卡死或回錯狀態。"""
    guard = make_guard()
    loader = ModelLoader(guard)

    assert ModelLoader.currently_loaded() is ModelKind.NONE
    with loader.acquire(ModelKind.OLLAMA, loader_fn=lambda: "x"):
        assert ModelLoader.currently_loaded() is ModelKind.OLLAMA
    assert ModelLoader.currently_loaded() is ModelKind.NONE
