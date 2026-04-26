"""把 SDXL 生成的 1024² 角色頭像，貼合到 base VRM 的臉部 UV 區塊。

策略：
    1. MediaPipe Face Mesh 偵測 SDXL 圖的 478 點，取 5 個 canonical 點（雙眼/鼻尖/雙嘴角）
    2. 從 base atlas 的 face_uv_template_*.json 讀對應的目標關鍵點
    3. cv2.estimateAffinePartial2D 求變換矩陣
    4. cv2.warpAffine 把 SDXL 圖映射到 atlas 的 face 區
    5. 用 alpha mask 軟邊融合進原 atlas（保留 base 的耳朵/額頭等）

MediaPipe vs InsightFace：
    - MediaPipe: Apache 2.0、CPU 跑、無需 MSVC、可商用
    - InsightFace: 非商用、需 Microsoft C++ Build Tools 編譯
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from ..utils.logging_setup import get_logger

_log = get_logger(__name__)


@dataclass
class FaceUVTemplate:
    """Pre-baked 對 base 模型的臉部對齊模板。

    `target_landmarks` 是 base atlas 上 (x, y) 5 個關鍵點（pixel 座標）。
    `mask_path` 是相對於 assets/base_models/ 的 alpha mask PNG（黑白），
    白色區域 = 應該被 SDXL 臉部覆蓋的範圍。
    """

    base_model_id: str
    atlas_size: tuple[int, int]
    target_landmarks: list[tuple[float, float]]  # 5 點
    mask_path: str

    @classmethod
    def load(cls, json_path: Path) -> "FaceUVTemplate":
        data = json.loads(Path(json_path).read_text(encoding="utf-8"))
        return cls(
            base_model_id=data["base_model_id"],
            atlas_size=tuple(data["atlas_size"]),  # type: ignore[arg-type]
            target_landmarks=[(float(x), float(y)) for x, y in data["target_landmarks"]],
            mask_path=data["mask_path"],
        )


# MediaPipe Face Detection (BlazeFace) 6 keypoints semantics
# 我們用前 4 個（兩眼中心 + 鼻尖 + 嘴中心）— 這 4 點對 anime 也偵測成功
# (Face Mesh 對 anime 失敗率高；BlazeFace 對 anime portrait 表現更穩)
_BLAZEFACE_KP_NAMES = ("RIGHT_EYE", "LEFT_EYE", "NOSE_TIP", "MOUTH_CENTER")
_BLAZEFACE_USED_INDICES = (0, 1, 2, 3)  # 取前 4 個


class FaceAligner:
    """MediaPipe BlazeFace 4 點偵測 + warpAffine 貼合。

    對 anime/illustration 風格臉部表現遠勝 Face Mesh。
    """

    def __init__(
        self,
        models_dir: Path,
        min_detection_confidence: float = 0.15,  # anime 臉特徵不明顯，降低門檻
    ):
        self._models_dir = Path(models_dir)
        self._conf = min_detection_confidence
        self._det = None  # lazy

    def _get_detector(self):
        if self._det is not None:
            return self._det
        import mediapipe as mp  # lazy import

        self._det = mp.solutions.face_detection.FaceDetection(
            model_selection=0,  # short-range（更廣的容忍，包含 anime）
            min_detection_confidence=self._conf,
        )
        _log.info("MediaPipe BlazeFace ready (CPU, short-range)")
        return self._det

    def detect_5pts(self, image: Image.Image) -> np.ndarray | None:
        """回傳 (4, 2) 的 ndarray (x, y) 像素座標：右眼/左眼/鼻尖/嘴中心。

        策略：
            1. 先用 BlazeFace 偵測
            2. 失敗時 fallback 到 center heuristic（假設臉在 image 中央約 0.45 高度）
               — 這對 SDXL 1024x1024 「正面肖像」效果不錯，避免完全 silently 失敗
        """
        det = self._get_detector()
        rgb = np.array(image.convert("RGB"))
        h, w = rgb.shape[:2]
        result = det.process(rgb)
        if result.detections:
            face = max(result.detections, key=lambda f: f.location_data.relative_bounding_box.width)
            kps = face.location_data.relative_keypoints
            pts = []
            for idx in _BLAZEFACE_USED_INDICES:
                kp = kps[idx]
                pts.append([kp.x * w, kp.y * h])
            _log.debug("BlazeFace detected face (score={:.2f})", face.score[0])
            return np.asarray(pts, dtype=np.float32)
        # Fallback: center heuristic — 假設臉在 image 中心，4 點按 SDXL 正面肖像比例估算
        _log.warning("BlazeFace failed; using center heuristic fallback (assumes centered front portrait)")
        cx = w / 2
        # SDXL 正面肖像通常臉部佔上半，眼睛在 ~0.4 高度，嘴 ~0.65
        return np.asarray([
            [cx - w * 0.13, h * 0.40],   # RIGHT_EYE
            [cx + w * 0.13, h * 0.40],   # LEFT_EYE
            [cx,            h * 0.52],   # NOSE_TIP
            [cx,            h * 0.65],   # MOUTH_CENTER
        ], dtype=np.float32)

    def warp_to_template(
        self,
        sdxl_image: Image.Image,
        atlas: Image.Image,
        template: FaceUVTemplate,
        feather_px: int = 24,
    ) -> Image.Image:
        """把 sdxl_image 的人臉貼到 atlas 上對應位置；回傳新 atlas。"""
        import cv2

        kps = self.detect_5pts(sdxl_image)
        if kps is None:
            _log.warning("Returning original atlas (face detection failed)")
            return atlas

        target = np.asarray(template.target_landmarks, dtype=np.float32)
        M, _ = cv2.estimateAffinePartial2D(kps, target, method=cv2.LMEDS)
        if M is None:
            _log.warning("Affine estimation failed; returning original atlas")
            return atlas

        sdxl_rgba = sdxl_image.convert("RGBA")
        sdxl_arr = np.array(sdxl_rgba)
        warped = cv2.warpAffine(
            sdxl_arr,
            M,
            template.atlas_size,
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0, 0),
        )

        # 載入 mask（白色 = 用 SDXL 部分）
        # ⚠️ cv2.imread Windows 中文路徑會回 None；改 read bytes + imdecode 走 unicode-safe
        mask_path = self._models_dir.parent / "assets" / "base_models" / template.mask_path
        mask = None
        if mask_path.exists():
            try:
                buf = np.frombuffer(mask_path.read_bytes(), dtype=np.uint8)
                mask = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
            except Exception as e:  # noqa: BLE001
                _log.warning("Failed to load mask {}: {}", mask_path.name, e)
        if mask is not None:
            mask = cv2.resize(mask, template.atlas_size)
            if feather_px > 0:
                mask = cv2.GaussianBlur(mask, (feather_px * 2 + 1, feather_px * 2 + 1), 0)
            alpha = (mask.astype(np.float32) / 255.0)[..., None]
        else:
            _log.warning("Face UV mask not loaded ({}); using warped alpha as mask", mask_path)
            alpha = (warped[..., 3:4].astype(np.float32) / 255.0)

        atlas_rgba = np.array(atlas.convert("RGBA")).astype(np.float32)
        warped_rgb = warped[..., :3].astype(np.float32)
        atlas_rgb = atlas_rgba[..., :3]
        merged_rgb = warped_rgb * alpha + atlas_rgb * (1.0 - alpha)
        merged = np.concatenate([merged_rgb, atlas_rgba[..., 3:4]], axis=-1)
        merged_uint8 = np.clip(merged, 0, 255).astype(np.uint8)
        return Image.fromarray(merged_uint8, mode="RGBA")
