"""⚠️ 2026-04-26 架構大改後標為「2D fallback / pre-stage」 — 不再主路徑

UV-aware Reverse Texture Bake — 把 SDXL 2D 臉「概念貼合」到 VRoid face skin atlas。

**已知限制**：SDXL 2D 沒有深度/軸線資訊，本模組基於「假設 SDXL 是正面正交投影」，
實際對齊精度有限。MVP2 改走 3D-first 路線（TripoSR / CharacterGen 出真 3D mesh）。
本模組保留作為：
  1. SDXL 2D 概念圖預覽（不寫進 VRM 也可獨立看）
  2. 沒有 3D 模型時的 fallback（給「能跑」勝過「精準」的場景）

核心算法（為什麼以前認為這是對的）：
    對 face_skin atlas 的每個 UV pixel：
      1. 找它落在哪個 face mesh 三角形（INDICES + TEXCOORD_0）
      2. Barycentric 內插出對應的 3D POSITION
      3. 朝前 normal 才繼續
      4. 把 3D 位置投影到正面正交相機 → 取得 SDXL 圖座標
      5. 從 SDXL 取像素寫回 atlas

    用 mesh 自身 UV 決定每個 pixel「應該」顯示什麼，
    3D mesh 在 VSeeFace render 時 sample UV 時自然拿到正確 SDXL 對應像素。

實作策略（為效能）：
    用 numpy 向量化 + 三角形邊界 box scan + barycentric 矩陣解。
    對 1024x1024 atlas + 1350 三角形約 2-5 秒（CPU only）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from ..utils.logging_setup import get_logger

_log = get_logger(__name__)


@dataclass
class FaceMeshData:
    """Face skin mesh 的 UV + 3D vertex 資料。

    從 VRM 抽出 F00_000_00_Face_00_SKIN material 對應的 primitives 後合併。
    """

    positions: np.ndarray  # (N, 3) — 3D POSITION (VRM 公尺單位)
    uvs: np.ndarray        # (N, 2) — TEXCOORD_0（glTF 慣例 y 軸朝上）
    indices: np.ndarray    # (M, 3) — 三角形頂點索引


def extract_face_mesh_from_vrm(vrm_path: Path, material_keyword: str = "Face_00_SKIN") -> FaceMeshData:
    """從 VRM 抽出含特定 material 的 mesh primitives 並合併成 FaceMeshData。"""
    from ..vrm.vrm_io import VRMFile
    from pygltflib import BufferFormat

    vrm = VRMFile.load(vrm_path)
    g = vrm.raw
    g.convert_buffers(BufferFormat.BINARYBLOB)
    blob = g.binary_blob()

    # 找符合 material name 的 indices
    mat_indices = []
    for i, mat in enumerate(g.materials):
        if mat.name and material_keyword in mat.name:
            mat_indices.append(i)
    if not mat_indices:
        raise ValueError(f"No material containing {material_keyword!r} in {vrm_path.name}")

    all_pos, all_uv, all_idx = [], [], []
    vertex_offset = 0
    for mesh in g.meshes:
        for prim in mesh.primitives:
            if prim.material not in mat_indices:
                continue
            pos = _read_accessor(g, blob, prim.attributes.POSITION)
            uv = _read_accessor(g, blob, prim.attributes.TEXCOORD_0)
            idx = _read_accessor(g, blob, prim.indices).reshape(-1)
            all_pos.append(pos)
            all_uv.append(uv)
            all_idx.append(idx + vertex_offset)
            vertex_offset += len(pos)

    return FaceMeshData(
        positions=np.vstack(all_pos),
        uvs=np.vstack(all_uv),
        indices=np.concatenate(all_idx).reshape(-1, 3),
    )


_COMPONENT_TYPES = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2),
                    5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
_TYPE_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _read_accessor(gltf, blob: bytes, accessor_idx: int) -> np.ndarray:
    """從 glTF accessor 讀 numpy array。"""
    acc = gltf.accessors[accessor_idx]
    bv = gltf.bufferViews[acc.bufferView]
    fmt_char, comp_size = _COMPONENT_TYPES[acc.componentType]
    n_comps = _TYPE_COMPONENTS[acc.type]
    count = acc.count
    offset = (bv.byteOffset or 0) + (acc.byteOffset or 0)
    raw = blob[offset: offset + count * n_comps * comp_size]
    np_dtype = {"b": np.int8, "B": np.uint8, "h": np.int16,
                "H": np.uint16, "I": np.uint32, "f": np.float32}[fmt_char]
    if n_comps == 1:
        return np.frombuffer(raw, dtype=np_dtype).copy()
    return np.frombuffer(raw, dtype=np_dtype).reshape(count, n_comps).copy()


# ---------------- Bake 主程式 ---------------- #


def bake_face_to_atlas(
    sdxl_face: Image.Image,
    base_atlas: Image.Image,
    mesh: FaceMeshData,
    *,
    front_axis: int = 2,           # +Z 為前 (VRM 標準)
    front_axis_sign: float = -1.0, # VRoid: 角色看 -Z 方向
    cull_back_faces: bool = True,
    feather_pixels: int = 8,        # 邊緣與原 atlas 軟融合
    # SDXL 內臉部佔比（SDXL 是包含頭髮+衣服的肖像）
    sdxl_hairtop_ratio: float = 0.05,  # SDXL 頭頂位置（從 image top 算）
    sdxl_chin_ratio: float = 0.62,     # SDXL 下巴位置
    sdxl_face_left_ratio: float = 0.28,
    sdxl_face_right_ratio: float = 0.72,
) -> Image.Image:
    """把 SDXL 臉用反向投影烘到 atlas。回傳新 atlas (RGBA)。

    front_axis_sign: 哪個方向算「朝前」。VRoid 模型角色面向 -Z，
                     所以朝前的 normal Z 分量應該 < 0。設 -1.0 過濾朝前。
    sdxl_face_height_3d: SDXL 圖映射到 3D 的高度範圍（公尺）。
                        VRoid 頭高約 0.22m，臉部約 0.18-0.20m。
    """
    atlas_arr = np.array(base_atlas.convert("RGBA"), dtype=np.uint8)
    h, w = atlas_arr.shape[:2]

    sdxl_arr = np.array(sdxl_face.convert("RGB"), dtype=np.uint8)
    sh, sw = sdxl_arr.shape[:2]

    positions = mesh.positions.astype(np.float32)
    uvs = mesh.uvs.astype(np.float32)
    indices = mesh.indices.astype(np.int64)

    # 計算正面投影參數
    bbox_min = positions.min(axis=0)
    bbox_max = positions.max(axis=0)
    cx = (bbox_min[0] + bbox_max[0]) / 2  # 臉部水平中心
    y_top = bbox_max[1]   # 3D 頭頂
    y_bot = bbox_min[1]   # 3D 下巴

    # 預先計算 SDXL 內臉部範圍（pixel 座標）
    sdxl_top_px = sdxl_hairtop_ratio * sh    # SDXL 頭頂 pixel y
    sdxl_chin_px = sdxl_chin_ratio * sh      # SDXL 下巴 pixel y
    sdxl_left_px = sdxl_face_left_ratio * sw
    sdxl_right_px = sdxl_face_right_ratio * sw

    _log.info("Mesh bbox: X=[{:.3f},{:.3f}] Y=[{:.3f},{:.3f}] Z=[{:.3f},{:.3f}]",
              bbox_min[0], bbox_max[0], y_bot, y_top, bbox_min[2], bbox_max[2])
    _log.info("SDXL face region: x=[{:.0f},{:.0f}] y=[{:.0f},{:.0f}] (of {}x{})",
              sdxl_left_px, sdxl_right_px, sdxl_top_px, sdxl_chin_px, sw, sh)

    # 將 UV 從 glTF 慣例 (y 朝上) 轉到 image pixel 座標 (y 朝下)
    pix_uv = np.column_stack([
        uvs[:, 0] * w,
        (1.0 - uvs[:, 1]) * h,
    ])

    # 過濾朝後三角形（用幾何 normal）
    keep_mask = np.ones(len(indices), dtype=bool)
    if cull_back_faces:
        v0 = positions[indices[:, 0]]
        v1 = positions[indices[:, 1]]
        v2 = positions[indices[:, 2]]
        normals = np.cross(v1 - v0, v2 - v0)
        keep_mask = np.sign(normals[:, front_axis]) == np.sign(front_axis_sign)

    # 為每個三角形 rasterize 並寫入像素
    out_arr = atlas_arr.copy()
    overlay_mask = np.zeros((h, w), dtype=np.float32)  # 0=保留原 atlas, 1=用新 SDXL

    n_processed = 0
    n_pixels_written = 0
    for tri_idx in range(len(indices)):
        if not keep_mask[tri_idx]:
            continue
        tri = indices[tri_idx]
        # UV 三角形 pixel 座標
        p_uv = pix_uv[tri]   # (3, 2)
        # 3D 位置
        p_3d = positions[tri]  # (3, 3)

        # bbox in atlas pixel space
        x0 = int(max(0, np.floor(p_uv[:, 0].min())))
        x1 = int(min(w - 1, np.ceil(p_uv[:, 0].max()))) + 1
        y0 = int(max(0, np.floor(p_uv[:, 1].min())))
        y1 = int(min(h - 1, np.ceil(p_uv[:, 1].max()))) + 1
        if x1 <= x0 or y1 <= y0:
            continue

        # 對 bbox 內每個 pixel 做 barycentric 測試
        xs = np.arange(x0, x1) + 0.5
        ys = np.arange(y0, y1) + 0.5
        gx, gy = np.meshgrid(xs, ys)
        pts = np.column_stack([gx.ravel(), gy.ravel()])  # (P, 2)

        # Barycentric (向量化)
        bary = _barycentric_2d(pts, p_uv)  # (P, 3)
        inside = (bary >= 0).all(axis=1)
        if not inside.any():
            continue
        bary_in = bary[inside]
        pts_in = pts[inside]

        # 內插 3D 位置
        pos_3d = bary_in @ p_3d  # (Q, 3)

        # 投影到 SDXL face 區
        # X：mesh +X = char right（VRoid Unity 左手座標），SDXL 是觀者鏡像視角，
        #    char right 在 SDXL 左側 → mesh +X 對應 SDXL left
        # 注意 atlas X 也是 mirror（mesh +X 在 atlas left），所以 atlas 與 SDXL 對齊不需 flip
        # 但「mesh +X → SDXL left」需要 flip 我們的 x_norm 公式
        x_norm = (pos_3d[:, 0] - bbox_min[0]) / (bbox_max[0] - bbox_min[0])  # 0=低X(char左), 1=高X(char右)
        sdxl_x = sdxl_right_px - x_norm * (sdxl_right_px - sdxl_left_px)  # 高X→SDXL左
        # Y：mesh y_top → SDXL top, mesh y_bot → SDXL chin
        y_norm = (y_top - pos_3d[:, 1]) / (y_top - y_bot)
        sdxl_y = sdxl_top_px + y_norm * (sdxl_chin_px - sdxl_top_px)

        sx = np.clip(sdxl_x.astype(np.int32), 0, sw - 1)
        sy = np.clip(sdxl_y.astype(np.int32), 0, sh - 1)

        # 取 SDXL pixel
        rgb = sdxl_arr[sy, sx]  # (Q, 3)

        # 寫入 atlas
        px = pts_in[:, 0].astype(np.int32)
        py = pts_in[:, 1].astype(np.int32)
        out_arr[py, px, :3] = rgb
        out_arr[py, px, 3] = 255  # 確保不透明
        overlay_mask[py, px] = 1.0
        n_pixels_written += int(inside.sum())
        n_processed += 1

    _log.info("Face baker: {} triangles processed, {} pixels written ({:.1%} of atlas)",
              n_processed, n_pixels_written, n_pixels_written / (h * w))

    # Feather edge：把 overlay_mask 的邊緣模糊，與原 atlas 平滑融合
    if feather_pixels > 0 and n_pixels_written > 0:
        from scipy.ndimage import gaussian_filter
        try:
            blurred = gaussian_filter(overlay_mask, sigma=feather_pixels)
            alpha = np.clip(blurred, 0, 1)[..., None]  # (h, w, 1)
            new_rgb = out_arr[..., :3].astype(np.float32) * alpha + \
                      atlas_arr[..., :3].astype(np.float32) * (1 - alpha)
            out_arr[..., :3] = np.clip(new_rgb, 0, 255).astype(np.uint8)
        except ImportError:
            _log.warning("scipy not available; skipping feather")

    return Image.fromarray(out_arr, mode="RGBA")


def _barycentric_2d(points: np.ndarray, triangle: np.ndarray) -> np.ndarray:
    """向量化 barycentric coordinates。

    Args:
        points: (P, 2) 待測點
        triangle: (3, 2) 三角形頂點

    Returns:
        (P, 3) barycentric coords。全 >=0 表示在三角形內。
    """
    a, b, c = triangle
    v0 = b - a
    v1 = c - a
    v2 = points - a   # (P, 2)
    d00 = v0 @ v0
    d01 = v0 @ v1
    d11 = v1 @ v1
    d20 = v2 @ v0     # (P,)
    d21 = v2 @ v1     # (P,)
    denom = d00 * d11 - d01 * d01
    if abs(denom) < 1e-12:
        return np.full((len(points), 3), -1.0, dtype=np.float32)
    inv = 1.0 / denom
    v_bary = (d11 * d20 - d01 * d21) * inv
    w_bary = (d00 * d21 - d01 * d20) * inv
    u_bary = 1.0 - v_bary - w_bary
    return np.column_stack([u_bary, v_bary, w_bary]).astype(np.float32)
