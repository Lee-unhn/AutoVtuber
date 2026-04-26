"""FaceTracker blendshape 計算測試 — 用合成 landmark 驗演算法。"""
from __future__ import annotations

import numpy as np
import pytest

from autovtuber.pipeline.face_tracker import (
    Blendshapes,
    FaceMeshTracker,
    landmarks_to_blendshapes,
)


def make_neutral_face() -> np.ndarray:
    """造一張 478×3 「中性表情」假 landmark — 眼睛半開、嘴閉合、眉毛常規位置。"""
    # 全部初始化在原點
    landmarks = np.zeros((478, 3), dtype=np.float32)

    # 臉輪廓（用 pixel 座標模擬，face_width=200, face_height=300）
    landmarks[234] = [100, 200, 0]   # face_left
    landmarks[454] = [300, 200, 0]   # face_right
    landmarks[10] = [200, 50, 0]     # face_top
    landmarks[152] = [200, 350, 0]   # face_bottom

    # 眼睛（左眼睛開 ~0.30 EAR：垂直 6, 水平 20）
    landmarks[33] = [120, 180, 0]    # left_eye_inner
    landmarks[133] = [160, 180, 0]   # left_eye_outer (h = 40)
    landmarks[159] = [140, 175, 0]   # left_eye_top
    landmarks[145] = [140, 187, 0]   # left_eye_bottom (v = 12, EAR=0.30)

    # 右眼鏡像
    landmarks[362] = [240, 180, 0]
    landmarks[263] = [280, 180, 0]
    landmarks[386] = [260, 175, 0]
    landmarks[374] = [260, 187, 0]

    # 嘴閉合：mouth_top 跟 mouth_bottom 接近；嘴角跟 mouth_top 同 y（中性無笑無皺）
    # 嘴寬 80 → ratio 0.40（接近 neutral I/U 中點）
    landmarks[61] = [160, 280, 0]    # mouth_left
    landmarks[291] = [240, 280, 0]   # mouth_right (mouth_h=80, mouth_wide=0.40)
    landmarks[13] = [200, 280, 0]    # mouth_top（跟嘴角同 y）
    landmarks[14] = [200, 284, 0]    # mouth_bottom (mouth_v=4, ratio_to_face=0.013)
    landmarks[0] = [200, 279, 0]
    landmarks[17] = [200, 285, 0]

    # 眉毛（離眼睛 normal 距離）
    landmarks[105] = [140, 165, 0]   # left_brow_top (10 above eye_top)
    landmarks[55] = [125, 165, 0]
    landmarks[334] = [260, 165, 0]
    landmarks[285] = [275, 165, 0]

    # 鼻
    landmarks[1] = [200, 230, 0]
    landmarks[168] = [200, 220, 0]

    return landmarks


def test_neutral_face_returns_low_weights():
    """中性表情：所有 weight 應接近 0（除了 blink ~ 0 因眼睛沒閉）。"""
    bs = landmarks_to_blendshapes(make_neutral_face())
    # joy / angry / sorrow / fun 都應低
    assert bs.joy < 0.3, f"joy too high for neutral: {bs.joy}"
    assert bs.angry < 0.3, f"angry too high for neutral: {bs.angry}"
    assert bs.sorrow < 0.3, f"sorrow too high for neutral: {bs.sorrow}"
    # 嘴閉的話 a 應低
    assert bs.a < 0.3, f"a too high for closed mouth: {bs.a}"
    # 眼睛半開（EAR=0.30）→ blink ~ 0
    assert bs.blink < 0.2, f"blink too high for open eyes: {bs.blink}"


def test_closed_eyes_triggers_blink():
    """眼睛閉上 → blink → 1.0。"""
    landmarks = make_neutral_face()
    # 把眼睛 v 設為近 0（EAR 近 0）
    landmarks[159] = [140, 180, 0]  # eye_top 跟 bottom 重合
    landmarks[145] = [140, 180, 0]
    landmarks[386] = [260, 180, 0]
    landmarks[374] = [260, 180, 0]

    bs = landmarks_to_blendshapes(landmarks)
    assert bs.blink_l > 0.8, f"blink_l should be high when closed, got {bs.blink_l}"
    assert bs.blink_r > 0.8, f"blink_r should be high when closed, got {bs.blink_r}"


def test_open_mouth_triggers_a():
    """嘴大開 → A weight 高。"""
    landmarks = make_neutral_face()
    # mouth_v 拉到 30（face_height=300, ratio=0.10）
    landmarks[13] = [200, 265, 0]
    landmarks[14] = [200, 295, 0]

    bs = landmarks_to_blendshapes(landmarks)
    assert bs.a > 0.7, f"a should be high when mouth wide open, got {bs.a}"


def test_smile_triggers_joy():
    """嘴角抬高（高於 mouth_top）→ joy 高。"""
    landmarks = make_neutral_face()
    # mouth_top y=278；嘴角 y 抬高（小於 278）→ smile_offset 正
    landmarks[61] = [180, 270, 0]   # 嘴角往上 10 px
    landmarks[291] = [220, 270, 0]

    bs = landmarks_to_blendshapes(landmarks)
    assert bs.joy > 0.5, f"joy should be high when smiling, got {bs.joy}"


def test_invalid_landmarks_returns_zero():
    """少於 478 點 → 全 0 weight。"""
    landmarks = np.zeros((100, 3), dtype=np.float32)
    bs = landmarks_to_blendshapes(landmarks)
    assert bs.a == 0.0
    assert bs.blink == 0.0
    assert bs.joy == 0.0


def test_blendshapes_to_dict_uses_vrm_names():
    """確認 to_dict 使用 VRM 0.x 標準名（VSeeFace 兼容）。"""
    bs = Blendshapes(joy=0.5, blink_l=0.8, a=0.3)
    d = bs.to_dict()
    assert "Joy" in d  # 大寫開頭，VRM 標準
    assert "Blink_L" in d
    assert d["Joy"] == 0.5
    assert d["Blink_L"] == 0.8
    assert d["A"] == 0.3


def test_facemeshtracker_can_be_constructed():
    """確認 mediapipe FaceMesh 能正常實例化（不跑推論）。"""
    tracker = FaceMeshTracker()
    assert tracker is not None
    tracker.close()
