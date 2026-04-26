"""對應「base 模型 ID → image index」的查表。

VRoid 匯出的 VRM 通常材質名稱規律可預測（FaceMouth, EyeIris, Hair, Body 等），
但每個 base 模型的 image 排序不同。我們對每個內建 base 模型維護一張查表。
"""
from __future__ import annotations

from dataclasses import dataclass

from .vrm_io import VRMFile


@dataclass(frozen=True)
class AtlasMap:
    """已知 base 模型的紋理索引對應表。"""

    face_skin_index: int
    hair_index: int
    eye_iris_index: int
    eye_white_index: int | None = None  # 有些 base 把眼白合併在 face_skin

    @classmethod
    def for_base_model(cls, base_model_id: str) -> "AtlasMap":
        """根據 base 模型 ID 取對應 atlas。

        ⚠️ 這些 index 是「manual mapped」— 加新 base 模型時必須手動跑 list_images()
        確認索引並更新此對照表。
        """
        if base_model_id not in _ATLAS_MAPS:
            raise KeyError(f"Unknown base model id: {base_model_id!r}")
        return _ATLAS_MAPS[base_model_id]


# 已實機驗證 (2026-04-26) 透過讀取 AvatarSample_B.vrm 內 30 個 image 條目。
# A 與 C 預設使用相同 atlas 結構；若不同需在執行期 fallback 用 auto_detect_atlas。
# Image 索引意義：
#   0 = F00_000_00_FaceMouth_00 (嘴部細節，非主臉)
#   4 = F00_000_00_EyeWhite_00 (眼白)
#   9 = F00_000_00_EyeIris_00 (虹膜 — 要染色)
#  11 = F00_000_00_Face_00 (主臉皮膚 — 要替換 SDXL 臉)
#  20 = F00_000_Hair_00_01 (主髮色 — 要染色)
_ATLAS_MAPS: dict[str, AtlasMap] = {
    # Female samples (F00_ prefix). 30 images (B) or 28 (A) — 共用相同 face/hair/eye 索引
    "AvatarSample_A": AtlasMap(face_skin_index=11, hair_index=20, eye_iris_index=9, eye_white_index=4),
    "AvatarSample_B": AtlasMap(face_skin_index=11, hair_index=20, eye_iris_index=9, eye_white_index=4),
    # Male sample (M00_ prefix). 25 images，atlas 結構不同！
    "AvatarSample_C": AtlasMap(face_skin_index=8, hair_index=20, eye_iris_index=5, eye_white_index=7),
    # Seed-san 是 VRM 1.0，MVP1 不支援
}


def auto_detect_atlas(vrm: VRMFile) -> dict[str, int]:
    """回退方法：根據 image.name 字串猜測對應索引。

    VRoid 預設材質命名通常含關鍵字 'Face' / 'Hair' / 'EyeIris' 等。
    若 _ATLAS_MAPS 找不到對應 base 模型，可呼叫此法做最佳猜測。
    """
    out: dict[str, int] = {}
    images = vrm.list_images()
    for entry in images:
        name = (entry.get("name") or "").lower()
        idx = entry["index"]
        if "face" in name or "skin" in name:
            out.setdefault("face_skin_index", idx)
        elif "hair" in name:
            out.setdefault("hair_index", idx)
        elif "iris" in name or "eye" in name:
            out.setdefault("eye_iris_index", idx)
    return out
