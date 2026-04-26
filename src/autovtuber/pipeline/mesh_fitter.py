"""MeshFitter — 把 TripoSR 出來的 3D character mesh，套到 VRoid base atlas 上。

兩種模式（重要！經 Evidence Collector 驗證後）：

**1. tint mode（預設，VTuber-grade 品質）**
    保留 VRoid 原 face skin atlas 的所有五官結構（眼眶/眉毛/嘴/陰影），
    只用 TSR mesh 採樣的「平均膚色」對 atlas 做 HSL 色調轉移。
    產出：VRoid 原本的 anime 五官 + 使用者偏好的膚色。

**2. replace mode（實驗性，不建議）**
    UV-aware reverse texture bake — 把 TSR mesh 的 vertex colors 反向烘到
    VRoid 的 face_skin atlas。問題：TSR 的 anime 臉沒有真實 facial geometry
    （眼/眉/嘴只是色塊不是凹凸 mesh），bake 出來的 atlas 缺特徵 → 不適合 VTuber。

設計依據：MVP1 已驗證 VRoid base 加上「髮色 + 眼色 + 膚色」三色 recolor 即可
產出可愛 anime VTuber，加上 SDXL 概念圖只是作為「色調參考」最穩定。
追求 1:1 face 替換是研究問題（需要 CharacterGen 等 anime-specific image-to-3D），
非 MVP2 範圍。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

from ..utils.logging_setup import get_logger
from ..vrm.texture_atlas import AtlasMap
from .face_baker import _barycentric_2d, extract_face_mesh_from_vrm

if TYPE_CHECKING:
    import trimesh

_log = get_logger(__name__)


def _sample_skin_from_sdxl(sdxl: Image.Image) -> tuple[int, int, int] | None:
    """從 SDXL anime portrait 採乾淨的「neutral 膚色」。

    策略（按 Evidence Collector 反饋）：
        - 額頭 ROI 採樣（UV ~(0.5, 0.27)，最平、最少 artistic blush/陰影）
        - 64×64 patch + median filter
        - 過濾極暗（髮）、極亮（高光）、非 peach（非膚色）
        - 排除「最暖的 25%」避免 cheek blush 污染
    """
    arr = np.array(sdxl.convert("RGB"))
    h, w = arr.shape[:2]
    # 額頭 ROI: 中央水平、上 1/4
    cy = int(h * 0.27)
    cx = int(w * 0.50)
    half = 32  # 64×64 patch
    y0 = max(0, cy - half)
    y1 = min(h, cy + half)
    x0 = max(0, cx - half)
    x1 = min(w, cx + half)
    crop = arr[y0:y1, x0:x1]
    if crop.size == 0:
        return None

    r = crop[..., 0].astype(np.int32)
    g = crop[..., 1].astype(np.int32)
    b = crop[..., 2].astype(np.int32)
    luminance = (r + g + b) / 3.0
    # peach 膚色判定（嚴格）
    mask = (
        (r > g) & (g > b - 10) &
        (luminance > 160) & (luminance < 235) &  # 排除暗髮、高光點
        ((r - b) > 10) & ((r - b) < 60)          # warm 但不是 cheek blush
    )
    if mask.sum() < 50:
        # 額頭 patch 不夠樣本（可能整片是頭髮）→ 退回中央
        crop = arr[int(h * 0.30): int(h * 0.55), int(w * 0.40): int(w * 0.60)]
        r = crop[..., 0].astype(np.int32)
        g = crop[..., 1].astype(np.int32)
        b = crop[..., 2].astype(np.int32)
        luminance = (r + g + b) / 3.0
        mask = (r > g) & (g > b - 10) & (luminance > 150) & (luminance < 240) & ((r - b) > 15)
        if mask.sum() < 100:
            return None

    skin_pixels = crop[mask]
    # 排除最暖的 25%（cheek blush）
    warmth = skin_pixels[:, 0].astype(np.int32) - skin_pixels[:, 2].astype(np.int32)
    warmth_threshold = np.percentile(warmth, 75)
    neutral_skin = skin_pixels[warmth <= warmth_threshold]
    if len(neutral_skin) < 20:
        neutral_skin = skin_pixels  # 退回全部

    median = np.median(neutral_skin, axis=0)
    return (int(median[0]), int(median[1]), int(median[2]))


def _hls_to_rgb_vectorized(h: np.ndarray, l: np.ndarray, s: np.ndarray) -> np.ndarray:
    """numpy 版 colorsys.hls_to_rgb；處理形狀 (..., ) 三個 array。回傳 (..., 3)。"""
    def _hue_to_rgb(p, q, t):
        t = np.where(t < 0, t + 1, t)
        t = np.where(t > 1, t - 1, t)
        out = np.where(t < 1/6, p + (q - p) * 6 * t, p)
        out = np.where((t >= 1/6) & (t < 0.5), q, out)
        out = np.where((t >= 0.5) & (t < 2/3), p + (q - p) * (2/3 - t) * 6, out)
        return out

    q = np.where(l < 0.5, l * (1 + s), l + s - l * s)
    p = 2 * l - q

    r = _hue_to_rgb(p, q, h + 1/3)
    g = _hue_to_rgb(p, q, h)
    b = _hue_to_rgb(p, q, h - 1/3)

    # 純灰（s==0）→ 直接用 L
    no_color = s < 1e-6
    r = np.where(no_color, l, r)
    g = np.where(no_color, l, g)
    b = np.where(no_color, l, b)

    return np.stack([r, g, b], axis=-1)


@dataclass
class FitDebugInfo:
    triangles_processed: int = 0
    triangles_culled_back: int = 0
    pixels_written: int = 0
    vroid_bbox: tuple[tuple[float, float, float], tuple[float, float, float]] = field(
        default=((0, 0, 0), (0, 0, 0))
    )
    tsr_bbox: tuple[tuple[float, float, float], tuple[float, float, float]] = field(
        default=((0, 0, 0), (0, 0, 0))
    )


@dataclass
class FitResult:
    """烘焙結果：可直接餵給 VRMAssembler.replace_image。"""

    face_skin: Image.Image
    """新的 face_skin atlas（RGBA）。"""

    debug: FitDebugInfo


class MeshFitter:
    """TSR 3D mesh → VRoid base atlas（reverse UV bake）。"""

    def __init__(
        self,
        mode: str = "tint",
        front_axis: int = 2,
        front_axis_sign: float = -1.0,
        cull_back_faces: bool = True,
        feather_pixels: int = 8,
        flip_tsr_y: bool = True,
        tint_strength: float = 0.5,
    ):
        """
        Args:
            mode: "tint"（預設，VTuber-grade）或 "replace"（實驗性，不建議）
            front_axis: VRoid 面向 axis（2=Z）
            front_axis_sign: VRoid 面對 -Z → -1.0
            cull_back_faces: 是否過濾朝後三角形
            feather_pixels: 與原 atlas 邊緣融合像素數
            flip_tsr_y: TSR mesh 的 Y 軸是否翻轉（預設 True）
            tint_strength: tint 模式下色調強度（0=不變、1=完全採用 TSR 色調），
                建議 0.5-0.8，太強會讓 VRoid 原本的細節失真
        """
        if mode not in ("tint", "replace"):
            raise ValueError(f"mode must be 'tint' or 'replace', got {mode!r}")
        self._mode = mode
        self._front_axis = front_axis
        self._front_axis_sign = front_axis_sign
        self._cull_back_faces = cull_back_faces
        self._feather_pixels = feather_pixels
        self._flip_tsr_y = flip_tsr_y
        self._tint_strength = max(0.0, min(1.0, tint_strength))

    # ---------------- public ---------------- #

    def sample_skin_tone_rgb(
        self,
        tsr_mesh: "trimesh.Trimesh",
    ) -> tuple[int, int, int] | None:
        """從 TSR mesh 採平均膚色（front-facing 上半部 vertex 的 vertex_color 中位數）。

        過濾條件：
            1. 只取 mesh 上半（Y 高的那半，flip 後即頭/臉區域）
            2. Normal 朝前 (Z 正向，flip 後即朝外)
            3. 過濾過於暗（< 50）或過於亮（> 230）的 vertex（避免 hair / 光點影響）

        Returns:
            (R, G, B) 0-255，或 None 如果樣本不足
        """
        if not hasattr(tsr_mesh, "visual") or tsr_mesh.visual is None:
            return None
        vc = getattr(tsr_mesh.visual, "vertex_colors", None)
        if vc is None or len(vc) != len(tsr_mesh.vertices):
            return None
        vc = np.asarray(vc, dtype=np.float32)
        verts = np.asarray(tsr_mesh.vertices, dtype=np.float32)

        # 取 Y 上半（TSR 預設 +Y 朝下 → 取 -Y 半）
        if self._flip_tsr_y:
            head_mask = verts[:, 1] < verts[:, 1].mean()  # TSR 中 Y 小 = 朝上 = 頭
        else:
            head_mask = verts[:, 1] > verts[:, 1].mean()

        # 計算 vertex normal（trimesh 提供）
        try:
            normals = np.asarray(tsr_mesh.vertex_normals, dtype=np.float32)
            # TSR 中朝前 = +Z 方向
            front_mask = normals[:, 2] > 0.3
        except Exception:
            front_mask = np.ones(len(verts), dtype=bool)

        # 亮度過濾（避免極暗髮色與極亮反光點主導均值）
        rgb = vc[:, :3]
        luminance = rgb.mean(axis=1)
        bright_mask = (luminance > 50) & (luminance < 230)

        keep = head_mask & front_mask & bright_mask
        if keep.sum() < 50:
            _log.warning("Skin sample too few ({}); falling back to head_mask only", int(keep.sum()))
            keep = head_mask & bright_mask
        if keep.sum() < 10:
            _log.warning("Even head sample too few; using overall median")
            keep = bright_mask

        if keep.sum() == 0:
            return None

        skin_rgb = np.median(rgb[keep], axis=0)
        _log.info(
            "Sampled skin tone from {} verts: RGB=({:.0f}, {:.0f}, {:.0f})",
            int(keep.sum()), skin_rgb[0], skin_rgb[1], skin_rgb[2],
        )
        return (int(skin_rgb[0]), int(skin_rgb[1]), int(skin_rgb[2]))

    def _fit_tint(
        self,
        tsr_mesh: "trimesh.Trimesh",
        orig_atlas: Image.Image,
        sdxl_portrait: Image.Image | None = None,
    ) -> FitResult:
        """tint mode：保留原 atlas 全部結構，只對「skin 區域」做 LAB 色度轉移。

        演算法：
            1. 採目標膚色：優先從 SDXL portrait（如果有提供）；否則從 TSR mesh
            2. 用 skin mask（peach hue + 高 saturation + 中等 luminance）找出 atlas 的 skin pixel
            3. 在 LAB 空間做 chroma-only transfer：保留 L 通道、把 a/b 拉向目標
            4. 只在 skin mask 範圍內套用，hair/eye/mouth/eyebrow 全部不動
        """
        # 採目標膚色（優先 SDXL portrait）
        target_rgb: tuple[int, int, int] | None = None
        if sdxl_portrait is not None:
            target_rgb = _sample_skin_from_sdxl(sdxl_portrait)
            if target_rgb is not None:
                _log.info("Target skin from SDXL portrait: RGB={}", target_rgb)
        if target_rgb is None:
            target_rgb = self.sample_skin_tone_rgb(tsr_mesh)
            if target_rgb is not None:
                _log.info("Target skin from TSR mesh: RGB={}", target_rgb)

        if target_rgb is None:
            _log.warning("Tint mode: no skin sample, returning original atlas")
            return FitResult(face_skin=orig_atlas, debug=FitDebugInfo())

        atlas_arr = np.array(orig_atlas, dtype=np.uint8)
        rgb_uint8 = atlas_arr[..., :3]
        alpha = atlas_arr[..., 3:4]

        # 1. Skin mask：peach hue（R > G > B）+ 中亮度 + 高飽和（排除髮/眉/嘴/眼）
        r = rgb_uint8[..., 0].astype(np.int32)
        g = rgb_uint8[..., 1].astype(np.int32)
        b = rgb_uint8[..., 2].astype(np.int32)
        max_c = np.max(rgb_uint8, axis=-1)
        min_c = np.min(rgb_uint8, axis=-1)
        luminance = (max_c.astype(np.float32) + min_c.astype(np.float32)) / 2.0
        sat = (max_c - min_c).astype(np.int32)

        skin_mask = (
            (r > g + 5) &      # peach: R > G
            (g > b - 5) &      # peach: G ≳ B
            (luminance > 180) &  # 排除暗色 + 眼眶陰影（提高門檻）
            (luminance < 250) &  # 排除全白點
            (sat > 5)            # 排除完全灰色點
        )
        skin_pct = skin_mask.mean() * 100
        _log.info(
            "Skin mask: {:.1f}% of atlas pixels qualify (rest = hair/eye/feature, untouched)",
            skin_pct,
        )

        # 2. LAB chroma-only transfer
        import cv2
        # 把 atlas RGB 轉 LAB
        rgb_for_lab = np.ascontiguousarray(rgb_uint8)
        lab_atlas = cv2.cvtColor(rgb_for_lab, cv2.COLOR_RGB2LAB).astype(np.float32)

        # 目標膚色的 LAB
        target_pixel = np.array([[list(target_rgb)]], dtype=np.uint8)
        target_lab = cv2.cvtColor(target_pixel, cv2.COLOR_RGB2LAB).astype(np.float32)[0, 0]

        # 計算 atlas skin 區域當前的 a/b 平均（為了估算需要的偏移量）
        if skin_mask.sum() > 0:
            cur_a_mean = lab_atlas[..., 1][skin_mask].mean()
            cur_b_mean = lab_atlas[..., 2][skin_mask].mean()
        else:
            cur_a_mean = 128.0
            cur_b_mean = 128.0

        # 用「shift」而非「replace」：把 a/b 通道整體偏移到目標的中位數
        # 強度 0=不偏、1=完全偏到目標
        delta_a = (target_lab[1] - cur_a_mean) * self._tint_strength
        delta_b = (target_lab[2] - cur_b_mean) * self._tint_strength

        new_lab = lab_atlas.copy()
        # 只對 skin mask 區做偏移
        new_lab[..., 1] = np.where(skin_mask, lab_atlas[..., 1] + delta_a, lab_atlas[..., 1])
        new_lab[..., 2] = np.where(skin_mask, lab_atlas[..., 2] + delta_b, lab_atlas[..., 2])

        # clip 回 LAB 合法範圍
        new_lab[..., 0] = np.clip(new_lab[..., 0], 0, 255)
        new_lab[..., 1] = np.clip(new_lab[..., 1], 0, 255)
        new_lab[..., 2] = np.clip(new_lab[..., 2], 0, 255)

        # 轉回 RGB
        new_rgb = cv2.cvtColor(new_lab.astype(np.uint8), cv2.COLOR_LAB2RGB)

        out = np.concatenate([new_rgb, alpha], axis=-1)

        debug = FitDebugInfo(
            triangles_processed=0,
            pixels_written=int(skin_mask.sum()),
        )
        _log.info(
            "Tint mode (LAB): target RGB={} → ΔA={:.1f} ΔB={:.1f}, masked to {} skin pixels",
            target_rgb, delta_a, delta_b, int(skin_mask.sum()),
        )
        return FitResult(
            face_skin=Image.fromarray(out, mode="RGBA"),
            debug=debug,
        )

    def fit(
        self,
        tsr_mesh: "trimesh.Trimesh",
        base_vrm_path: Path,
        atlas_map: AtlasMap,
        material_keyword: str = "Face_00_SKIN",
        sdxl_portrait: Image.Image | None = None,
    ) -> FitResult:
        """主入口：3D TSR mesh + VRoid base → 新 face skin atlas。

        Args:
            sdxl_portrait: 可選的 SDXL 概念圖。若提供，tint mode 會優先從這裡
                採乾淨的 anime 膚色（比 TSR vertex_colors 受 alpha matting 污染好）。

        依 self._mode 走 tint 或 replace 模式。
        """
        from ..vrm.vrm_io import VRMFile

        vrm = VRMFile.load(base_vrm_path)
        orig_face_skin = vrm.get_image_pil(atlas_map.face_skin_index).convert("RGBA")

        if self._mode == "tint":
            return self._fit_tint(tsr_mesh, orig_face_skin, sdxl_portrait=sdxl_portrait)

        # ---- replace mode（實驗性，從這裡往下） ---- #

        # 1. 讀 VRoid face primitives
        face_mesh = extract_face_mesh_from_vrm(base_vrm_path, material_keyword)
        _log.info(
            "VRoid face mesh: {} verts / {} triangles",
            len(face_mesh.positions), len(face_mesh.indices),
        )

        # 2. 取 TSR vertex colors + KDTree
        if not hasattr(tsr_mesh, "visual") or tsr_mesh.visual is None:
            _log.warning("TSR mesh has no visual; returning original atlas")
            return FitResult(face_skin=orig_face_skin, debug=FitDebugInfo())
        tsr_vc = getattr(tsr_mesh.visual, "vertex_colors", None)
        if tsr_vc is None or len(tsr_vc) != len(tsr_mesh.vertices):
            _log.warning("TSR mesh missing vertex_colors; returning original atlas")
            return FitResult(face_skin=orig_face_skin, debug=FitDebugInfo())
        tsr_vc = np.asarray(tsr_vc, dtype=np.uint8)
        tsr_verts = np.asarray(tsr_mesh.vertices, dtype=np.float32)

        # 4. 計算 alignment transform: VRoid 3D pos → TSR 3D pos
        v_min, v_max = face_mesh.positions.min(axis=0), face_mesh.positions.max(axis=0)
        t_min, t_max = tsr_verts.min(axis=0), tsr_verts.max(axis=0)
        v_center = (v_min + v_max) / 2.0
        t_center = (t_min + t_max) / 2.0
        v_size = np.maximum(v_max - v_min, 1e-6)
        t_size = np.maximum(t_max - t_min, 1e-6)
        scale = t_size / v_size
        flip = np.array([1.0, -1.0 if self._flip_tsr_y else 1.0, 1.0], dtype=np.float32)

        def vroid_to_tsr(pts: np.ndarray) -> np.ndarray:
            relative = (pts - v_center) * flip
            return t_center + relative * scale

        # 5. KDTree on TSR verts
        from scipy.spatial import cKDTree
        kdtree = cKDTree(tsr_verts)

        # 6. UV-aware reverse bake
        atlas_arr = np.array(orig_face_skin, dtype=np.uint8)
        h, w = atlas_arr.shape[:2]

        positions = face_mesh.positions.astype(np.float32)
        uvs = face_mesh.uvs.astype(np.float32)
        indices = face_mesh.indices.astype(np.int64)

        # glTF UV (y up) → image pixel (y down)
        pix_uv = np.column_stack([uvs[:, 0] * w, (1.0 - uvs[:, 1]) * h])

        # 過濾朝後三角形
        keep_mask = np.ones(len(indices), dtype=bool)
        if self._cull_back_faces:
            v0 = positions[indices[:, 0]]
            v1 = positions[indices[:, 1]]
            v2 = positions[indices[:, 2]]
            normals = np.cross(v1 - v0, v2 - v0)
            keep_mask = np.sign(normals[:, self._front_axis]) == np.sign(self._front_axis_sign)

        out_arr = atlas_arr.copy()
        overlay_mask = np.zeros((h, w), dtype=np.float32)

        debug = FitDebugInfo(
            triangles_culled_back=int((~keep_mask).sum()),
            vroid_bbox=(tuple(v_min.tolist()), tuple(v_max.tolist())),
            tsr_bbox=(tuple(t_min.tolist()), tuple(t_max.tolist())),
        )

        for tri_idx in range(len(indices)):
            if not keep_mask[tri_idx]:
                continue
            tri = indices[tri_idx]
            p_uv = pix_uv[tri]
            p_3d = positions[tri]

            # atlas pixel bbox
            x0 = int(max(0, np.floor(p_uv[:, 0].min())))
            x1 = int(min(w - 1, np.ceil(p_uv[:, 0].max()))) + 1
            y0 = int(max(0, np.floor(p_uv[:, 1].min())))
            y1 = int(min(h - 1, np.ceil(p_uv[:, 1].max()))) + 1
            if x1 <= x0 or y1 <= y0:
                continue

            xs = np.arange(x0, x1) + 0.5
            ys = np.arange(y0, y1) + 0.5
            gx, gy = np.meshgrid(xs, ys)
            pts = np.column_stack([gx.ravel(), gy.ravel()])

            bary = _barycentric_2d(pts, p_uv)
            inside = (bary >= 0).all(axis=1)
            if not inside.any():
                continue
            bary_in = bary[inside]
            pts_in = pts[inside]

            # 內插 3D 位置（VRoid space）
            vroid_pos = bary_in @ p_3d  # (Q, 3)

            # 變到 TSR space
            tsr_pos = vroid_to_tsr(vroid_pos)

            # KDTree query 最近 TSR vertex
            _dist, nearest = kdtree.query(tsr_pos, k=1)
            colors = tsr_vc[nearest]  # (Q, 4)

            # 寫入 atlas
            px = pts_in[:, 0].astype(np.int32)
            py = pts_in[:, 1].astype(np.int32)
            out_arr[py, px, :3] = colors[:, :3]
            out_arr[py, px, 3] = 255
            overlay_mask[py, px] = 1.0

            debug.triangles_processed += 1
            debug.pixels_written += int(inside.sum())

        _log.info(
            "MeshFitter: {} triangles, {} pixels ({:.1%} of atlas), {} back-culled",
            debug.triangles_processed,
            debug.pixels_written,
            debug.pixels_written / (h * w),
            debug.triangles_culled_back,
        )

        # Feather edge
        if self._feather_pixels > 0 and debug.pixels_written > 0:
            try:
                from scipy.ndimage import gaussian_filter
                blurred = gaussian_filter(overlay_mask, sigma=self._feather_pixels)
                alpha = np.clip(blurred, 0, 1)[..., None]
                new_rgb = (
                    out_arr[..., :3].astype(np.float32) * alpha
                    + atlas_arr[..., :3].astype(np.float32) * (1 - alpha)
                )
                out_arr[..., :3] = np.clip(new_rgb, 0, 255).astype(np.uint8)
            except ImportError:
                _log.warning("scipy not available; skipping feather")

        return FitResult(
            face_skin=Image.fromarray(out_arr, mode="RGBA"),
            debug=debug,
        )
