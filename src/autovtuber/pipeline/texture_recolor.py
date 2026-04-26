"""HSV 顏色替換工具 — 把 base VRM 的頭髮/眼睛貼圖染成使用者指定顏色。

策略：
    - 在 HSV 空間替換 H + S，**保留 V (亮度)** → 保留陰影/高光細節
    - 對極暗（V<0.05）或極亮（V>0.95）的像素跳過避免崩成色塊
    - alpha 通道完整保留
"""
from __future__ import annotations

import numpy as np
from PIL import Image


def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """`#RRGGBB` → (R, G, B) 0–255。"""
    s = hex_str.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def hex_to_hsv(hex_str: str) -> tuple[float, float, float]:
    """`#RRGGBB` → (H, S, V)，全部 0.0–1.0。"""
    import colorsys
    r, g, b = (c / 255.0 for c in hex_to_rgb(hex_str))
    return colorsys.rgb_to_hsv(r, g, b)


def recolor_hsv(
    image: Image.Image,
    target_hex: str,
    saturation_blend: float = 1.0,
    value_match: float = 0.0,
    skip_low_v: float = 0.05,
    skip_high_v: float = 0.95,
) -> Image.Image:
    """把 image 整體 H+S 替換成 target_hex 的色相，保留亮度與 alpha。

    Args:
        image: 來源圖（任意模式，會被轉 RGBA）
        target_hex: 目標顏色 hex 字串
        saturation_blend: 1.0 = 完全採用目標飽和度，0.0 = 維持原飽和度
        value_match: 0.0 = 完全保留原亮度（原行為，會偏離 target hex luminance），
            1.0 = 把 atlas mean V 平移到 target V（保留亮度變化但平均對齊 target）。
            建議 0.5-0.8 — 原本 default=0 會讓深色 target 出來偏亮（高光區無法壓暗）。
        skip_low_v / skip_high_v: 亮度極端區避免染色（防止陰影/高光變色塊）

    Returns:
        新的 PIL Image (RGBA)
    """
    img = image.convert("RGBA")
    arr = np.asarray(img, dtype=np.float32) / 255.0  # (H, W, 4)
    rgb = arr[..., :3]
    alpha = arr[..., 3:4]

    target_h, target_s, target_v = hex_to_hsv(target_hex)

    # RGB → HSV (vectorized)
    maxc = rgb.max(axis=-1)
    minc = rgb.min(axis=-1)
    v = maxc
    delta = maxc - minc
    s = np.where(maxc > 0, delta / np.maximum(maxc, 1e-8), 0.0)

    new_s = saturation_blend * target_s + (1.0 - saturation_blend) * s

    # 替換 mask：跳過極端亮度（純白/純黑/陰影/高光）
    mask = (v >= skip_low_v) & (v <= skip_high_v)
    h_field = np.where(mask, target_h, _rgb_to_h_safe(rgb))
    new_s = np.where(mask, new_s, s)

    # V 平移：把 mask 內的 V 均值拉向 target_v（保留變化幅度）
    new_v = v.copy()
    if value_match > 0 and mask.any():
        cur_mean = float(v[mask].mean())
        delta_v = (target_v - cur_mean) * value_match
        new_v = np.where(mask, np.clip(v + delta_v, 0.0, 1.0), v)

    # HSV → RGB
    new_rgb = _hsv_to_rgb_vec(h_field, new_s, new_v)

    out = np.concatenate([new_rgb, alpha], axis=-1)
    out_uint8 = np.clip(out * 255.0, 0, 255).astype(np.uint8)
    return Image.fromarray(out_uint8, mode="RGBA")


def _rgb_to_h_safe(rgb: np.ndarray) -> np.ndarray:
    """純色 → H，灰階回 0；shape (H, W)。"""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    maxc = rgb.max(axis=-1)
    minc = rgb.min(axis=-1)
    delta = maxc - minc

    h = np.zeros_like(maxc)
    nz = delta > 0
    rc = np.where(nz, (maxc - r) / np.maximum(delta, 1e-8), 0.0)
    gc = np.where(nz, (maxc - g) / np.maximum(delta, 1e-8), 0.0)
    bc = np.where(nz, (maxc - b) / np.maximum(delta, 1e-8), 0.0)

    h = np.where((maxc == r) & nz, bc - gc, h)
    h = np.where((maxc == g) & nz, 2.0 + rc - bc, h)
    h = np.where((maxc == b) & nz, 4.0 + gc - rc, h)
    h = (h / 6.0) % 1.0
    return h


def _hsv_to_rgb_vec(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    """HSV → RGB，皆為 0–1 的 ndarray，回傳 shape (..., 3)。"""
    i = np.floor(h * 6.0).astype(np.int32) % 6
    f = h * 6.0 - np.floor(h * 6.0)
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))

    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], axis=-1)
