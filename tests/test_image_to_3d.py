"""ImageTo3D 測試 — 完全 mock TSR 模型（不下載 1.7 GB ckpt）。

策略：
    1. 建一個 fake `tsr.system.TSR` 模組塞進 sys.modules，繞過真實 import。
    2. 驗證 ImageTo3D 的「黏合邏輯」：preprocess、acquire、extract_mesh 呼叫順序。
    3. 真實的 TSR 推論 + marching cubes 由 smoke test 另外驗（CI 不跑）。
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from PIL import Image

from autovtuber.pipeline.image_to_3d import ImageTo3D, _ensure_tsr_on_path
from autovtuber.safety.model_loader import ModelKind, ModelLoader


# ---------------- 共用 fixtures ---------------- #


def make_loader() -> ModelLoader:
    guard = MagicMock()
    guard.thresholds = MagicMock(cuda_memory_fraction=0.92)
    guard.check_or_raise.return_value = None
    guard.abort_event = MagicMock(is_set=MagicMock(return_value=False))
    ModelLoader._CURRENT = ModelKind.NONE
    ModelLoader._CURRENT_OBJ = None
    ModelLoader._CURRENT_UNLOADER = None
    return ModelLoader(guard)


def make_white_portrait(size: int = 512) -> Image.Image:
    """模擬 SDXL 白底人像：中央有一塊有色像素。"""
    arr = np.full((size, size, 3), 255, dtype=np.uint8)
    # 在中央畫一個彩色方塊當前景
    arr[size // 4 : 3 * size // 4, size // 4 : 3 * size // 4] = [128, 64, 200]
    return Image.fromarray(arr, mode="RGB")


def install_fake_tsr(monkeypatch: pytest.MonkeyPatch) -> dict:
    """在 sys.modules 安裝 fake tsr 套件；回傳 spy dict 方便測試斷言。"""
    spy = {
        "from_pretrained_called": False,
        "from_pretrained_args": None,
        "set_chunk_size_called_with": None,
        "model_to_device": None,
        "forward_called_with": None,
        "extract_mesh_args": None,
    }

    # ---- fake trimesh.Trimesh that ImageTo3D returns ---- #
    fake_mesh = MagicMock()
    fake_mesh.vertices = np.zeros((100, 3))
    fake_mesh.faces = np.zeros((50, 3), dtype=np.int64)
    fake_mesh.visual = MagicMock(vertex_colors=np.zeros((100, 4)))

    # ---- fake TSR class ---- #
    class FakeRenderer:
        def set_chunk_size(self, n: int) -> None:
            spy["set_chunk_size_called_with"] = n

    class FakeTSR:
        def __init__(self):
            self.renderer = FakeRenderer()
            # 提供一個假的 parameters() 讓 ImageTo3D 取 device
            self._device = "cpu"

        @classmethod
        def from_pretrained(cls, repo_id, config_name, weight_name):
            spy["from_pretrained_called"] = True
            spy["from_pretrained_args"] = (repo_id, config_name, weight_name)
            return cls()

        def to(self, device: str):
            self._device = device
            spy["model_to_device"] = device
            return self

        def parameters(self):
            # 給 next(model.parameters()).device 用
            import torch
            yield torch.zeros(1, device=self._device)

        def __call__(self, images, device: str):
            spy["forward_called_with"] = (len(images), device)
            import torch
            return torch.zeros(1, 3)

        def extract_mesh(self, scene_codes, has_vertex_color, resolution: int):
            spy["extract_mesh_args"] = (has_vertex_color, resolution)
            return [fake_mesh]

    # ---- fake tsr.utils.resize_foreground ---- #
    def fake_resize_foreground(image: Image.Image, ratio: float) -> Image.Image:
        spy.setdefault("resize_foreground_calls", []).append(ratio)
        return image  # 簡化：直接回傳

    # ---- 把假模組塞進 sys.modules ---- #
    fake_tsr = types.ModuleType("tsr")
    fake_tsr_system = types.ModuleType("tsr.system")
    fake_tsr_system.TSR = FakeTSR
    fake_tsr_utils = types.ModuleType("tsr.utils")
    fake_tsr_utils.resize_foreground = fake_resize_foreground
    fake_tsr_utils.remove_background = lambda *a, **kw: a[0]

    monkeypatch.setitem(sys.modules, "tsr", fake_tsr)
    monkeypatch.setitem(sys.modules, "tsr.system", fake_tsr_system)
    monkeypatch.setitem(sys.modules, "tsr.utils", fake_tsr_utils)

    spy["fake_mesh"] = fake_mesh
    return spy


# ---------------- 測試 ---------------- #


def test_module_imports_without_torch_or_tsr():
    """模組可在沒裝 TSR / torch 的環境 import（lazy import 不能在頂層）。"""
    # 純 import 測試 — 已經在檔案頂端 import 了，能跑到這就 PASS
    assert ImageTo3D.HF_REPO == "stabilityai/TripoSR"
    assert ImageTo3D.DEFAULT_MC_RESOLUTION == 256


def test_ensure_tsr_on_path_idempotent():
    """重複呼叫不該重複加 path。"""
    before = list(sys.path)
    _ensure_tsr_on_path()
    once = list(sys.path)
    _ensure_tsr_on_path()
    twice = list(sys.path)
    assert once == twice  # 第二次無變化


def test_generate_raises_if_external_repo_missing(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """external/TripoSR 不存在時應 raise FileNotFoundError + 提示 git clone。"""
    fake_root = Path(tmp_path) / "definitely_does_not_exist"
    monkeypatch.setattr(
        "autovtuber.pipeline.image_to_3d._TRIPOSR_REPO_ROOT", fake_root
    )
    loader = make_loader()
    guard = MagicMock(check_or_raise=MagicMock(return_value=None))
    i23 = ImageTo3D(loader, guard, models_dir=tmp_path)

    with pytest.raises(FileNotFoundError, match="git clone"):
        i23.generate(make_white_portrait())


def test_generate_full_path_with_mocked_tsr(monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory):
    """完整黏合流程：build_model → preprocess → forward → extract_mesh。"""
    spy = install_fake_tsr(monkeypatch)
    # 確保 _TRIPOSR_REPO_ROOT 存在（不需真的有檔案，目錄空就好）
    fake_repo = Path(tmp_path) / "fake_triposr"
    fake_repo.mkdir()
    monkeypatch.setattr(
        "autovtuber.pipeline.image_to_3d._TRIPOSR_REPO_ROOT", fake_repo
    )

    loader = make_loader()
    guard = MagicMock(check_or_raise=MagicMock(return_value=None))
    guard.abort_event = MagicMock(is_set=MagicMock(return_value=False))

    progress_log = []

    def progress_cb(stage, cur, tot):
        progress_log.append((stage, cur, tot))

    i23 = ImageTo3D(loader, guard, models_dir=Path(tmp_path), mc_resolution=128)
    mesh = i23.generate(make_white_portrait(), progress_cb=progress_cb)

    # 1. from_pretrained 用對的 HF repo
    assert spy["from_pretrained_called"]
    assert spy["from_pretrained_args"][0] == "stabilityai/TripoSR"
    assert spy["from_pretrained_args"][1] == "config.yaml"
    assert spy["from_pretrained_args"][2] == "model.ckpt"

    # 2. set_chunk_size 用了預設值
    assert spy["set_chunk_size_called_with"] == ImageTo3D.DEFAULT_CHUNK_SIZE

    # 3. forward 收到 1 張 image
    assert spy["forward_called_with"][0] == 1

    # 4. extract_mesh 用 has_vertex_color=True + 指定 resolution
    assert spy["extract_mesh_args"] == (True, 128)

    # 5. progress_cb 三個 stage 都有 fire
    stages = {s for s, *_ in progress_log}
    assert stages == {"preprocess", "infer", "extract_mesh"}

    # 6. 回傳的 mesh 是 fake_mesh
    assert mesh is spy["fake_mesh"]

    # 7. acquire 用 ModelKind.TRIPO_SR；結束後應釋放
    assert ModelLoader.currently_loaded() is ModelKind.NONE


def test_preprocess_converts_white_bg_rgb_to_alpha_then_gray(monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory):
    """白底 RGB 應被當前景，白色像素轉 alpha=0，最後合成 0.5 灰底。"""
    spy = install_fake_tsr(monkeypatch)
    fake_repo = Path(tmp_path) / "fake_triposr"
    fake_repo.mkdir()
    monkeypatch.setattr(
        "autovtuber.pipeline.image_to_3d._TRIPOSR_REPO_ROOT", fake_repo
    )

    loader = make_loader()
    guard = MagicMock(check_or_raise=MagicMock(return_value=None))
    guard.abort_event = MagicMock(is_set=MagicMock(return_value=False))
    i23 = ImageTo3D(loader, guard, models_dir=Path(tmp_path), mc_resolution=64)

    img = make_white_portrait(size=128)
    i23.generate(img)  # 跑完整流程，預處理在裡面

    # resize_foreground 應該被呼叫一次，ratio = 0.85
    assert spy.get("resize_foreground_calls") == [ImageTo3D.DEFAULT_FOREGROUND_RATIO]


def test_custom_resolutions_passed_through(monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory):
    """使用者自訂 mc_resolution / chunk_size / foreground_ratio 應傳到底層。"""
    spy = install_fake_tsr(monkeypatch)
    fake_repo = Path(tmp_path) / "fake_triposr"
    fake_repo.mkdir()
    monkeypatch.setattr(
        "autovtuber.pipeline.image_to_3d._TRIPOSR_REPO_ROOT", fake_repo
    )

    loader = make_loader()
    guard = MagicMock(check_or_raise=MagicMock(return_value=None))
    guard.abort_event = MagicMock(is_set=MagicMock(return_value=False))
    i23 = ImageTo3D(
        loader, guard,
        models_dir=Path(tmp_path),
        mc_resolution=192,
        chunk_size=4096,
        foreground_ratio=0.7,
    )
    i23.generate(make_white_portrait())

    assert spy["set_chunk_size_called_with"] == 4096
    assert spy["extract_mesh_args"] == (True, 192)
    assert spy.get("resize_foreground_calls") == [0.7]


def test_cache_dir_sets_hf_home(monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory):
    """指定 cache_dir 應透過 HF_HOME 影響 hf_hub_download 寫入位置。"""
    install_fake_tsr(monkeypatch)
    fake_repo = Path(tmp_path) / "fake_triposr"
    fake_repo.mkdir()
    monkeypatch.setattr(
        "autovtuber.pipeline.image_to_3d._TRIPOSR_REPO_ROOT", fake_repo
    )
    monkeypatch.delenv("HF_HOME", raising=False)

    target_cache = Path(tmp_path) / "my_hf_cache"
    loader = make_loader()
    guard = MagicMock(check_or_raise=MagicMock(return_value=None))
    guard.abort_event = MagicMock(is_set=MagicMock(return_value=False))
    i23 = ImageTo3D(
        loader, guard,
        models_dir=Path(tmp_path),
        cache_dir=target_cache,
    )
    i23.generate(make_white_portrait())
    assert os.environ.get("HF_HOME") == str(target_cache)


# 補上 import os 給上面測試用
import os  # noqa: E402
