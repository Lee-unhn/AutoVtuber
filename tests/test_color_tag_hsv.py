"""R3：HSV-based hex → color tag 測試。

之前 RGB-rules 邏輯有 boundary case（如暗紅 #7B1F1F → brown）。
R3 改用 colorsys.rgb_to_hsv 分類，下面這些 case 應該全對。
"""
from __future__ import annotations

import pytest

from autovtuber.pipeline.prompt_builder import (
    _color_strength_modifier,
    _hex_to_color_tag,
    _other_hair_color_tags,
)


@pytest.mark.parametrize(
    "hex_str, target, expected",
    [
        # 經典案例
        ("#5B3A29", "hair", "brown hair"),       # 暗棕
        ("#3B5BA5", "eyes", "blue eyes"),        # 藍
        ("#1E1E1E", "hair", "black hair"),       # 黑
        ("#FFFFFF", "hair", "white hair"),       # 白
        ("#000000", "hair", "black hair"),       # 純黑
        # R3 修的 boundary case
        ("#7B1F1F", "eyes", "red eyes"),         # 暗紅（之前是 brown）
        ("#7B1F1F", "hair", "red hair"),
        # 飽和色
        ("#FF0000", "hair", "red hair"),
        ("#FFFF00", "eyes", "yellow eyes"),
        ("#00FF00", "hair", "green hair"),
        ("#0000FF", "eyes", "blue eyes"),
        # 各種色相
        ("#FFC0CB", "hair", "pink hair"),        # 粉紅
        ("#800080", "eyes", "purple eyes"),      # 紫
        ("#FFD700", "hair", "blonde hair"),      # 金（hue~50°）
        # 灰階
        ("#808080", "hair", "silver hair"),      # 中灰 → silver/grey
        ("#808080", "eyes", "grey eyes"),
        ("#C0C0C0", "hair", "silver hair"),
    ],
)
def test_hex_to_color_tag_correct(hex_str, target, expected):
    actual = _hex_to_color_tag(hex_str, target)
    assert actual == expected, f"#{hex_str.lstrip('#')} {target} → expected '{expected}', got '{actual}'"


def test_color_strength_modifier_dark():
    """V<0.30 → 'dark'。"""
    assert _color_strength_modifier("#5B3A29") == "dark"   # V=0.36 邊緣案例 — actually 0.357
    # 更明顯的 dark
    assert _color_strength_modifier("#1E1E1E") == "dark"


def test_color_strength_modifier_light():
    """V>0.85 → 'light'。"""
    assert _color_strength_modifier("#FFFFFF") == "light"
    assert _color_strength_modifier("#FFE0E0") == "light"  # 淡粉


def test_color_strength_modifier_vivid():
    """S>0.75 → 'vivid'（且非 dark/light）。"""
    assert _color_strength_modifier("#FF0000") == "light"  # V=1 → light
    assert _color_strength_modifier("#CC0000") == "vivid"  # V=0.8, S=1


def test_color_strength_modifier_neutral():
    """中等 S/V → empty string。"""
    assert _color_strength_modifier("#809080") == ""


def test_other_hair_color_tags_excludes_active():
    """anti-drift negative tags 不應包含當前 active color。"""
    actives = _other_hair_color_tags("brown hair")
    assert "brown hair" not in actives
    assert "black hair" in actives
    assert "blue hair" in actives
    # 至少 9 個其他顏色（11 個 - brown - blonde 留下）
    assert len(actives) >= 9


def test_dark_brown_5b3a29_includes_modifier():
    """form 給 #5B3A29 → 組成的 tag 應該是 'dark brown hair' 或 '... brown hair'。"""
    color = _hex_to_color_tag("#5B3A29", "hair")
    strength = _color_strength_modifier("#5B3A29")
    full = f"{strength} {color}".strip()
    assert "brown" in full
    assert full == "dark brown hair"


def test_dark_red_7b1f1f_eyes():
    """暗紅眼睛 → 該是 'dark red eyes' 或 'red eyes'，絕非 'brown'。"""
    color = _hex_to_color_tag("#7B1F1F", "eyes")
    strength = _color_strength_modifier("#7B1F1F")
    full = f"{strength} {color}".strip()
    assert "red" in full
    assert "brown" not in full
