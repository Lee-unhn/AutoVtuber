"""VRMAssembler — 把 SDXL 臉部 + recolor 後的髮/眼貼圖塞回 base VRM，輸出新 .vrm。

不下載任何 AI 模型；純檔案操作（PIL + pygltflib + cv2 + scipy）。

MVP2 升級（2026-04-26 經 4 輪 audit）：可選帶入 TSR mesh + MeshFitter（tint mode）
做 LAB 色域的「膚色轉移」，讓 VRoid base 的臉膚色貼合使用者的 SDXL 概念。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from ..utils.logging_setup import get_logger
from ..vrm.texture_atlas import AtlasMap
from ..vrm.vrm_io import VRMFile
from .face_aligner import FaceAligner, FaceUVTemplate
from .job_spec import FormInput
from .texture_recolor import recolor_hsv

if TYPE_CHECKING:
    import trimesh

    from .mesh_fitter import MeshFitter

_log = get_logger(__name__)


class VRMAssembler:
    """把生成的臉部圖 + 表單顏色，組合進 base VRM。"""

    def __init__(self, base_models_dir: Path, models_dir: Path):
        """`base_models_dir` 是 assets/base_models/，`models_dir` 是 models/（給 InsightFace 用）。"""
        self._base_models_dir = Path(base_models_dir)
        self._models_dir = Path(models_dir)

    def assemble(
        self,
        form: FormInput,
        sdxl_face_image: Image.Image,
        output_path: Path,
        face_aligner: FaceAligner | None = None,
        tsr_mesh: "trimesh.Trimesh | None" = None,
        mesh_fitter: "MeshFitter | None" = None,
    ) -> Path:
        """主流程：載入 base.vrm → 可選 mesh fit (tint) → recolor 髮/眼 → 存檔。

        Args:
            tsr_mesh: 可選 — ImageTo3D 推出的 3D mesh（含 vertex_colors）
            mesh_fitter: 可選 — 配合 tsr_mesh 做 face_skin tint。
                若兩者皆有 → MVP2 完整 pipeline；否則退回 MVP1 行為（只 recolor 髮+眼）

        策略歷程：
            MVP1: 不動 face_skin（VRoid base 直接用）
            MVP2: 改用 MeshFitter tint mode（LAB chroma-only shift）— 經 Evidence
                  Collector 4 輪 audit 確認商用品質 PASS（7.5/10）
        """
        base_vrm_path = self._base_models_dir / f"{form.base_model_id}.vrm"
        if not base_vrm_path.exists():
            raise FileNotFoundError(
                f"Base VRM 不存在：{base_vrm_path}\n"
                f"Setup wizard 應該下載過；或請手動放置。"
            )

        atlas = AtlasMap.for_base_model(form.base_model_id)
        vrm = VRMFile.load(base_vrm_path)
        _log.info("Base VRM loaded: {} (vrm version {})", base_vrm_path.name, vrm.vrm_version)

        # 1. SDXL 概念圖另存為 PNG（不貼進 VRM）
        try:
            concept_path = output_path.with_name(output_path.stem + "_concept.png")
            sdxl_face_image.save(concept_path)
            _log.info("✅ SDXL concept saved: {}", concept_path.name)
        except Exception:  # noqa: BLE001
            _log.exception("Failed to save SDXL concept PNG (non-fatal)")

        # 2. （MVP2）膚色轉移：TSR mesh + MeshFitter → face_skin atlas tint
        if tsr_mesh is not None and mesh_fitter is not None:
            try:
                _log.info("Applying MeshFitter tint mode to face_skin atlas...")
                fit_result = mesh_fitter.fit(
                    tsr_mesh=tsr_mesh,
                    base_vrm_path=base_vrm_path,
                    atlas_map=atlas,
                    sdxl_portrait=sdxl_face_image,
                )
                vrm.replace_image(atlas.face_skin_index, fit_result.face_skin, mime_type="image/png")
                _log.info(
                    "✅ Face skin tinted: {} pixels modified",
                    fit_result.debug.pixels_written,
                )
            except Exception as e:  # noqa: BLE001
                _log.warning(
                    "MeshFitter tint failed ({}: {}) — keeping VRoid base face skin",
                    type(e).__name__, e,
                )
        else:
            _log.info("No TSR mesh / fitter provided → keeping VRoid base face skin (MVP1 mode)")

        # 3. Recolor 頭髮（value_match=0.7：把 atlas mean V 拉向 target V，
        #    避免深色 target 出來偏亮（如 #5B3A29 深棕變 copper）)
        hair_atlas = vrm.get_image_pil(atlas.hair_index)
        new_hair = recolor_hsv(hair_atlas, form.hair_color_hex, value_match=0.7)
        vrm.replace_image(atlas.hair_index, new_hair, mime_type="image/png")

        # 4. Recolor 眼睛虹膜
        iris_atlas = vrm.get_image_pil(atlas.eye_iris_index)
        new_iris = recolor_hsv(iris_atlas, form.eye_color_hex, saturation_blend=0.85, value_match=0.5)
        vrm.replace_image(atlas.eye_iris_index, new_iris, mime_type="image/png")

        out = vrm.save(output_path)
        _log.info("✅ VRM saved: {}", out)
        return out

    @staticmethod
    def _paste_naive(face_atlas: Image.Image, sdxl_face: Image.Image) -> Image.Image:
        """fallback：把 SDXL 圖縮到 atlas 大小直接覆蓋（不對 UV，效果差但不崩潰）。"""
        atlas_rgba = face_atlas.convert("RGBA")
        resized = sdxl_face.convert("RGBA").resize(atlas_rgba.size, Image.LANCZOS)
        return resized
