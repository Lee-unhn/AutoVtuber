"""FaceTracker — webcam frame → MediaPipe Face Mesh → VRM blendshape weights.

獨立模組讓 unit test 可在無 webcam 環境驗演算法（吃 numpy frame）。

VRM 0.x 標準 blendshape 名（VRoid 統一 schema）：
    Joy / Angry / Sorrow / Fun  ← 情緒（4）
    A / I / U / E / O           ← 嘴型（5）
    Blink / Blink_L / Blink_R  ← 眨眼（3）

我們從 MediaPipe Face Mesh 478 個 landmark 計算出每個 blendshape 的 weight (0-1)。
參考標準 ARKit / VTuber blendshape mapping。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from ..utils.logging_setup import get_logger

if TYPE_CHECKING:
    pass

_log = get_logger(__name__)


@dataclass
class Blendshapes:
    """VRM 0.x 標準 blendshape 集合，全部 weight 範圍 0-1。"""

    joy: float = 0.0
    angry: float = 0.0
    sorrow: float = 0.0
    fun: float = 0.0
    a: float = 0.0
    i: float = 0.0
    u: float = 0.0
    e: float = 0.0
    o: float = 0.0
    blink: float = 0.0
    blink_l: float = 0.0
    blink_r: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "Joy": self.joy,
            "Angry": self.angry,
            "Sorrow": self.sorrow,
            "Fun": self.fun,
            "A": self.a,
            "I": self.i,
            "U": self.u,
            "E": self.e,
            "O": self.o,
            "Blink": self.blink,
            "Blink_L": self.blink_l,
            "Blink_R": self.blink_r,
        }


# MediaPipe Face Mesh 478 點關鍵索引（標準）
# 參考: https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/python/solutions/face_mesh_connections.py
_LANDMARKS = {
    # 眼睛
    "left_eye_top": 159,
    "left_eye_bottom": 145,
    "left_eye_inner": 33,
    "left_eye_outer": 133,
    "right_eye_top": 386,
    "right_eye_bottom": 374,
    "right_eye_inner": 362,
    "right_eye_outer": 263,
    # 嘴
    "mouth_left": 61,
    "mouth_right": 291,
    "mouth_top": 13,
    "mouth_bottom": 14,
    "lip_top_outer": 0,
    "lip_bottom_outer": 17,
    # 眉毛
    "left_brow_top": 105,
    "left_brow_inner": 55,
    "right_brow_top": 334,
    "right_brow_inner": 285,
    # 鼻
    "nose_tip": 1,
    "nose_bridge": 168,
    # 臉輪廓（用於 normalize 距離）
    "face_left": 234,
    "face_right": 454,
    "face_top": 10,
    "face_bottom": 152,
}


def _dist(p1: np.ndarray, p2: np.ndarray) -> float:
    return float(np.linalg.norm(p1 - p2))


def _ratio_to_weight(ratio: float, ref_lo: float, ref_hi: float) -> float:
    """把比例值線性映射到 0-1 weight。"""
    if ref_hi <= ref_lo:
        return 0.0
    w = (ratio - ref_lo) / (ref_hi - ref_lo)
    return float(max(0.0, min(1.0, w)))


def landmarks_to_blendshapes(landmarks: np.ndarray) -> Blendshapes:
    """MediaPipe 478×3 landmarks → Blendshapes weights。

    landmarks 是 normalized (0-1) 或實際 pixel 座標都可（演算法用 ratio）。
    """
    if landmarks.shape[0] < 478:
        return Blendshapes()  # 偵測不全直接回零

    pts = landmarks  # alias

    # 臉部寬高（用作距離 normalize）
    face_width = _dist(pts[_LANDMARKS["face_left"]], pts[_LANDMARKS["face_right"]])
    face_height = _dist(pts[_LANDMARKS["face_top"]], pts[_LANDMARKS["face_bottom"]])
    if face_width < 1e-6 or face_height < 1e-6:
        return Blendshapes()

    # ---------- 眨眼 ---------- #
    # Eye Aspect Ratio (EAR)：垂直 / 水平。睜開 ~0.3，閉上 ~0.05
    le_v = _dist(pts[_LANDMARKS["left_eye_top"]], pts[_LANDMARKS["left_eye_bottom"]])
    le_h = _dist(pts[_LANDMARKS["left_eye_inner"]], pts[_LANDMARKS["left_eye_outer"]])
    re_v = _dist(pts[_LANDMARKS["right_eye_top"]], pts[_LANDMARKS["right_eye_bottom"]])
    re_h = _dist(pts[_LANDMARKS["right_eye_inner"]], pts[_LANDMARKS["right_eye_outer"]])
    le_ear = le_v / max(le_h, 1e-6)
    re_ear = re_v / max(re_h, 1e-6)
    # EAR < 0.15 = 閉，> 0.30 = 完全睜
    blink_l = _ratio_to_weight(0.30 - le_ear, 0.0, 0.20)  # 反向：EAR 小 → blink 大
    blink_r = _ratio_to_weight(0.30 - re_ear, 0.0, 0.20)
    blink = (blink_l + blink_r) / 2

    # ---------- 嘴型 ---------- #
    # Mouth Open Ratio (MOR)：嘴垂直 / 臉高
    mouth_v = _dist(pts[_LANDMARKS["mouth_top"]], pts[_LANDMARKS["mouth_bottom"]])
    mouth_h = _dist(pts[_LANDMARKS["mouth_left"]], pts[_LANDMARKS["mouth_right"]])
    mouth_open = mouth_v / max(face_height, 1e-6)
    mouth_wide = mouth_h / max(face_width, 1e-6)

    # A: 嘴大開（mouth_open > 0.06 → A 高）
    a = _ratio_to_weight(mouth_open, 0.02, 0.08)
    # I: 嘴扁寬（mouth_wide 高 + 開度小）
    i = _ratio_to_weight(mouth_wide - 0.40, 0.0, 0.10) * (1 - a * 0.5)
    # U: 嘴噘（窄 + 開度小）
    u = _ratio_to_weight(0.40 - mouth_wide, 0.0, 0.05) * (1 - a * 0.5)
    # E: 微寬微開
    e = _ratio_to_weight(mouth_open, 0.015, 0.04) * (1 - a)
    # O: 中等開 + 中等寬
    o = _ratio_to_weight(mouth_open, 0.03, 0.06) * _ratio_to_weight(mouth_wide, 0.30, 0.45)

    # ---------- 情緒（粗略，用嘴角 + 眉毛位置）---------- #
    # 嘴角抬高 → 笑（Joy / Fun）
    # 比較 mouth_left/right 的 y 跟 mouth_top y
    mouth_corner_y = (pts[_LANDMARKS["mouth_left"]][1] + pts[_LANDMARKS["mouth_right"]][1]) / 2
    mouth_top_y = pts[_LANDMARKS["mouth_top"]][1]
    # 嘴角高於 mouth_top 表示笑（y 軸通常 image 下大上小，所以嘴角 y < mouth_top y）
    smile_offset = (mouth_top_y - mouth_corner_y) / max(face_height, 1e-6)
    joy = _ratio_to_weight(smile_offset, -0.005, 0.015)

    # 眉毛壓低 → 生氣（Angry）
    brow_y = (pts[_LANDMARKS["left_brow_top"]][1] + pts[_LANDMARKS["right_brow_top"]][1]) / 2
    eye_y = (pts[_LANDMARKS["left_eye_top"]][1] + pts[_LANDMARKS["right_eye_top"]][1]) / 2
    brow_to_eye = (eye_y - brow_y) / max(face_height, 1e-6)
    # 眉毛離眼睛近 = 皺眉
    angry = _ratio_to_weight(0.025 - brow_to_eye, 0.0, 0.015)

    # 嘴角下垂 + 眉毛中間下沉 → 難過
    sorrow = _ratio_to_weight(-smile_offset, 0.0, 0.015)

    # Fun: 笑 + 嘴稍開（多用於 ENERGETIC）
    fun = joy * a

    return Blendshapes(
        joy=joy, angry=angry, sorrow=sorrow, fun=fun,
        a=a, i=i, u=u, e=e, o=o,
        blink=blink, blink_l=blink_l, blink_r=blink_r,
    )


# ---------------- MediaPipe wrapper ---------------- #


class FaceMeshTracker:
    """包裝 mediapipe.solutions.face_mesh — 一張 BGR/RGB image → landmarks 478×3。

    懶載入 — 在 lock-free 主執行緒呼叫 process()。
    """

    def __init__(self):
        import mediapipe as mp
        self._mp_face = mp.solutions.face_mesh
        self._mesh = self._mp_face.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,  # 478 點（含瞳孔）
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def process(self, rgb_frame: np.ndarray) -> np.ndarray | None:
        """input RGB image → 478×3 numpy array (normalized 0-1) 或 None（未偵測到）。"""
        results = self._mesh.process(rgb_frame)
        if not results.multi_face_landmarks:
            return None
        lms = results.multi_face_landmarks[0]
        h, w = rgb_frame.shape[:2]
        # mediapipe landmarks 是 normalized 0-1；轉 pixel 座標供 dist 計算
        arr = np.array(
            [[lm.x * w, lm.y * h, lm.z * w] for lm in lms.landmark],
            dtype=np.float32,
        )
        return arr

    def close(self) -> None:
        self._mesh.close()
