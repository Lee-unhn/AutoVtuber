"""FaceGenerator IP-Adapter wiring 測試 — 用 mock SDXL pipe 驗 reference photo 流通。

不下載任何模型；只驗：
    1. reference_photo_path 為 None 時，IP-Adapter scale = 0
    2. reference_photo_path 給定時，scale = with_photo + ip_adapter_image kwarg 帶入
    3. set_ip_adapter_scale 失敗時 fallback（沒 image_encoder 情境）
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from autovtuber.pipeline.face_generator import FaceGenerator
from autovtuber.pipeline.job_spec import GeneratedPrompt
from autovtuber.safety.model_loader import ModelKind, ModelLoader


def make_loader() -> ModelLoader:
    guard = MagicMock()
    guard.thresholds = MagicMock(cuda_memory_fraction=0.92)
    guard.check_or_raise.return_value = None
    guard.abort_event = MagicMock(is_set=MagicMock(return_value=False))
    ModelLoader._CURRENT = ModelKind.NONE
    ModelLoader._CURRENT_OBJ = None
    ModelLoader._CURRENT_UNLOADER = None
    return ModelLoader(guard)


def make_fake_pipe(scale_calls: list, kwargs_capture: dict) -> MagicMock:
    """造一個假 SDXL pipe，捕捉 set_ip_adapter_scale 與 __call__ kwargs。"""
    pipe = MagicMock()

    def _set_scale(scale):
        scale_calls.append(scale)

    pipe.set_ip_adapter_scale = MagicMock(side_effect=_set_scale)

    def _call(**kwargs):
        kwargs_capture.update(kwargs)
        result = MagicMock()
        # 回傳一個假圖
        result.images = [Image.new("RGB", (1024, 1024), (255, 200, 200))]
        return result

    pipe.side_effect = _call
    return pipe


def test_no_reference_sets_scale_zero():
    """沒參考照片時，IP-Adapter scale 應設為 ip_scale_without_photo。"""
    scale_calls = []
    kwargs = {}
    pipe = make_fake_pipe(scale_calls, kwargs)
    loader = make_loader()
    guard = MagicMock(check_or_raise=MagicMock(return_value=None))
    guard.abort_event = MagicMock(is_set=MagicMock(return_value=False))

    fg = FaceGenerator(
        loader, guard, Path("."),
        ip_adapter_scale_with_photo=0.7,
        ip_adapter_scale_without_photo=0.0,
    )
    prompt = GeneratedPrompt(positive="1girl, anime", negative="bad")

    # 直接呼叫 _run_pipeline（跳過 build_pipeline 的 SDXL 載入）
    with patch("torch.Generator") as mock_gen, patch("torch.inference_mode"):
        mock_gen.return_value.manual_seed.return_value = mock_gen.return_value
        fg._run_pipeline(pipe, prompt, reference_photo_path=None, progress_cb=None)

    # 應該設 scale=0.0
    assert scale_calls == [0.0]
    # ip_adapter_image 不應在 kwargs
    assert "ip_adapter_image" not in kwargs


def test_with_reference_sets_scale_and_image_kwarg(tmp_path: Path):
    """有參考照片時，scale=with_photo + ip_adapter_image 帶入 kwargs。"""
    # 造一張假參考照
    ref_path = tmp_path / "ref.png"
    Image.new("RGB", (512, 512), (100, 100, 200)).save(ref_path)

    scale_calls = []
    kwargs = {}
    pipe = make_fake_pipe(scale_calls, kwargs)
    loader = make_loader()
    guard = MagicMock(check_or_raise=MagicMock(return_value=None))
    guard.abort_event = MagicMock(is_set=MagicMock(return_value=False))

    fg = FaceGenerator(
        loader, guard, Path("."),
        ip_adapter_scale_with_photo=0.7,
        ip_adapter_scale_without_photo=0.0,
    )
    prompt = GeneratedPrompt(positive="1girl", negative="bad")

    with patch("torch.Generator") as mock_gen, patch("torch.inference_mode"):
        mock_gen.return_value.manual_seed.return_value = mock_gen.return_value
        fg._run_pipeline(pipe, prompt, reference_photo_path=str(ref_path), progress_cb=None)

    assert scale_calls == [0.7]
    # ip_adapter_image 應該被帶入
    assert "ip_adapter_image" in kwargs
    assert isinstance(kwargs["ip_adapter_image"], Image.Image)


def test_fallback_when_set_ip_adapter_scale_fails(tmp_path: Path):
    """IP-Adapter image_encoder 缺檔時 set_ip_adapter_scale 會 raise，
    應該 fallback 到 'no reference photo' 模式（不傳 ip_adapter_image kwarg）。"""
    ref_path = tmp_path / "ref.png"
    Image.new("RGB", (512, 512), (100, 100, 200)).save(ref_path)

    scale_calls = []
    kwargs = {}
    pipe = MagicMock()
    pipe.set_ip_adapter_scale = MagicMock(side_effect=RuntimeError("No IP-Adapter loaded"))
    pipe.side_effect = lambda **kw: (
        kwargs.update(kw) or MagicMock(images=[Image.new("RGB", (1024, 1024))])
    )

    loader = make_loader()
    guard = MagicMock(check_or_raise=MagicMock(return_value=None))
    guard.abort_event = MagicMock(is_set=MagicMock(return_value=False))
    fg = FaceGenerator(loader, guard, Path("."))
    prompt = GeneratedPrompt(positive="1girl", negative="bad")

    with patch("torch.Generator") as mock_gen, patch("torch.inference_mode"):
        mock_gen.return_value.manual_seed.return_value = mock_gen.return_value
        # 不該 raise — 應該 fallback
        fg._run_pipeline(pipe, prompt, reference_photo_path=str(ref_path), progress_cb=None)

    # ip_adapter_image 應**不在** kwargs（因為 fallback 把 ref_img 設 None）
    assert "ip_adapter_image" not in kwargs
