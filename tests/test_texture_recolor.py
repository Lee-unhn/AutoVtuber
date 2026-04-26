"""HSV recolor 測試 — 純運算（numpy + PIL），無 GPU 需求。"""
from __future__ import annotations

import pytest
from PIL import Image


def test_recolor_changes_hue_preserves_alpha():
    pytest.importorskip("numpy")
    from autovtuber.pipeline.texture_recolor import recolor_hsv

    src = Image.new("RGBA", (32, 32), (200, 50, 50, 128))  # 半透明紅
    out = recolor_hsv(src, "#3399FF")  # 藍

    assert out.mode == "RGBA"
    assert out.size == (32, 32)
    # 中心像素應該變藍系
    px = out.getpixel((16, 16))
    assert px[2] > px[0]  # B > R
    # alpha 保留
    assert px[3] == 128


def test_recolor_skips_extreme_dark_and_bright():
    """全黑、全白像素不該被染色。"""
    pytest.importorskip("numpy")
    from autovtuber.pipeline.texture_recolor import recolor_hsv

    img = Image.new("RGBA", (32, 32), (255, 255, 255, 255))  # 全白
    out = recolor_hsv(img, "#FF0000")
    px = out.getpixel((16, 16))
    # 全白應仍接近白
    assert px[0] > 240 and px[1] > 240 and px[2] > 240


def test_hex_to_rgb():
    from autovtuber.pipeline.texture_recolor import hex_to_rgb
    assert hex_to_rgb("#FF8000") == (255, 128, 0)
    assert hex_to_rgb("FF8000") == (255, 128, 0)


def test_hex_to_hsv():
    from autovtuber.pipeline.texture_recolor import hex_to_hsv
    h, s, v = hex_to_hsv("#FF0000")
    assert v == 1.0
    assert s == 1.0
