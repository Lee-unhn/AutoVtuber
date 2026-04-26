"""Debug 視覺化 — 驗證 face mesh 的 UV + 3D POSITION 解析正確。

產出 4 張圖到 output/_debug/：
    1. uv_layout.png         — TEXCOORD_0 在 1024x1024 atlas 上的線框（UV 攤開）
    2. front_view.png        — 3D POSITION 從 +Z 看（正面視角）
    3. uv_to_3d_x.png        — heatmap：每個 UV pixel 對應的 3D X 座標
    4. uv_to_3d_y.png        — heatmap：每個 UV pixel 對應的 3D Y 座標（上下）

肉眼判斷：
    - uv_layout 應呈現「攤開的臉部 mesh」，能辨認眼/鼻/嘴的位置
    - front_view 應呈現「正面臉的輪廓」（頭、五官分佈合理）
    - uv_to_3d_x/y heatmap 應呈現連續色彩漸層（不該破碎）

執行：
    C:\\avt\\venv\\Scripts\\python.exe C:\\avt\\scripts\\debug_face_mesh.py
"""
from __future__ import annotations

import sys
import struct
import json
import base64
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


COMPONENT_TYPES = {
    5120: ("b", 1),   # BYTE
    5121: ("B", 1),   # UNSIGNED_BYTE
    5122: ("h", 2),   # SHORT
    5123: ("H", 2),   # UNSIGNED_SHORT
    5125: ("I", 4),   # UNSIGNED_INT
    5126: ("f", 4),   # FLOAT
}
TYPE_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_accessor(gltf, blob: bytes, accessor_idx: int) -> np.ndarray:
    """從 glTF accessor 讀出 numpy array。"""
    acc = gltf.accessors[accessor_idx]
    bv = gltf.bufferViews[acc.bufferView]
    fmt_char, comp_size = COMPONENT_TYPES[acc.componentType]
    n_comps = TYPE_COMPONENTS[acc.type]
    count = acc.count
    offset = (bv.byteOffset or 0) + (acc.byteOffset or 0)
    raw = blob[offset: offset + count * n_comps * comp_size]
    np_dtype = {"b": np.int8, "B": np.uint8, "h": np.int16,
                "H": np.uint16, "I": np.uint32, "f": np.float32}[fmt_char]
    arr = np.frombuffer(raw, dtype=np_dtype).reshape(count, n_comps) if n_comps > 1 else \
          np.frombuffer(raw, dtype=np_dtype)
    return arr.copy()  # 確保 writable


def extract_face_skin_primitive(vrm_path: Path) -> dict:
    """從 VRM 抽出 face skin 的 mesh data：positions, uvs, indices。

    AvatarSample_A: mesh[0] "Face.baked"，primitives 7+8 用 F00_000_00_Face_00_SKIN 材質
    我們合併兩個 primitives 的 vertex/index 資料。
    """
    from autovtuber.vrm.vrm_io import VRMFile
    from pygltflib import BufferFormat

    vrm = VRMFile.load(vrm_path)
    g = vrm.raw
    g.convert_buffers(BufferFormat.BINARYBLOB)
    blob = g.binary_blob()

    # 找 face skin 的 material indices
    face_mat_indices = []
    for i, mat in enumerate(g.materials):
        if mat.name and "F00_000_00_Face_00_SKIN" in mat.name:
            face_mat_indices.append(i)
    print(f"face skin material indices: {face_mat_indices}")

    # 找 mesh primitives
    mesh = g.meshes[0]
    all_pos = []
    all_uv = []
    all_idx = []
    vertex_offset = 0
    for prim in mesh.primitives:
        if prim.material not in face_mat_indices:
            continue
        pos = read_accessor(g, blob, prim.attributes.POSITION)  # (N, 3)
        uv = read_accessor(g, blob, prim.attributes.TEXCOORD_0)  # (N, 2)
        idx = read_accessor(g, blob, prim.indices).reshape(-1)  # (M*3,)
        all_pos.append(pos)
        all_uv.append(uv)
        all_idx.append(idx + vertex_offset)
        vertex_offset += len(pos)

    positions = np.vstack(all_pos)
    uvs = np.vstack(all_uv)
    indices = np.concatenate(all_idx).reshape(-1, 3)
    print(f"vertex count: {len(positions)}, triangle count: {len(indices)}")
    print(f"position bbox: min={positions.min(axis=0)}, max={positions.max(axis=0)}")
    print(f"uv bbox: min={uvs.min(axis=0)}, max={uvs.max(axis=0)}")
    return {"positions": positions, "uvs": uvs, "indices": indices}


def render_uv_layout(uvs: np.ndarray, indices: np.ndarray, atlas_size: int = 1024) -> Image.Image:
    """畫 UV 三角形線框（看 mesh 在 atlas 上怎麼攤開）。"""
    img = Image.new("RGB", (atlas_size, atlas_size), (32, 32, 32))
    draw = ImageDraw.Draw(img)
    # UV: y 軸 glTF 是「下到上」，圖片是「上到下」→ 翻轉
    pix_uv = np.column_stack([uvs[:, 0] * atlas_size,
                               (1.0 - uvs[:, 1]) * atlas_size])
    for tri in indices:
        pts = [tuple(pix_uv[v]) for v in tri]
        draw.polygon(pts, outline=(120, 200, 255), fill=None)
    return img


def render_front_view(positions: np.ndarray, indices: np.ndarray, size: int = 1024) -> Image.Image:
    """畫 3D POSITION 正面投影（從 +Z 軸看）。"""
    img = Image.new("RGB", (size, size), (32, 32, 32))
    draw = ImageDraw.Draw(img)
    # 取 X, Y；忽略 Z
    pos2d = positions[:, :2]  # (N, 2)
    # 轉到 image 座標：X 中心化、Y 翻轉
    bbox_min = pos2d.min(axis=0)
    bbox_max = pos2d.max(axis=0)
    pad = 20
    scale = (size - 2 * pad) / (bbox_max - bbox_min).max()
    offset_x = pad - bbox_min[0] * scale + (size - 2 * pad - (bbox_max[0] - bbox_min[0]) * scale) / 2
    offset_y = pad + bbox_max[1] * scale + (size - 2 * pad - (bbox_max[1] - bbox_min[1]) * scale) / 2

    pix = np.column_stack([
        pos2d[:, 0] * scale + offset_x,
        -pos2d[:, 1] * scale + offset_y,
    ])
    for tri in indices:
        # 計算 z 朝向（用 normal）
        v0, v1, v2 = positions[tri]
        normal = np.cross(v1 - v0, v2 - v0)
        if normal[2] >= 0:
            color = (200, 100, 100)  # 朝前 = 紅
        else:
            color = (60, 60, 80)     # 朝後 = 灰
        pts = [tuple(pix[v]) for v in tri]
        draw.polygon(pts, outline=color, fill=None)
    return img


def render_heatmap_uv_to_3d(
    uvs: np.ndarray, positions: np.ndarray, indices: np.ndarray,
    axis: int, atlas_size: int = 1024,
) -> Image.Image:
    """產生 heatmap：每個 UV pixel 對應的 3D 軸座標。

    用三角形 rasterization：對每個 mesh 三角形，光柵化它在 UV 空間的覆蓋區，
    寫入該三角形 3 個頂點 3D position 的某軸平均（或 barycentric 內插）。
    """
    canvas = np.zeros((atlas_size, atlas_size), dtype=np.float32)
    mask = np.zeros((atlas_size, atlas_size), dtype=bool)

    pos_axis = positions[:, axis]
    pix_uv = np.column_stack([uvs[:, 0] * atlas_size,
                               (1.0 - uvs[:, 1]) * atlas_size])

    for tri in indices:
        # 三角形 3 點 + 對應軸值
        pts = pix_uv[tri]   # (3, 2)
        vals = pos_axis[tri]  # (3,)
        # 簡化：用 PIL polygon fill 平均值（不是真 barycentric，但足夠 debug 用）
        avg = float(vals.mean())
        # 計算 bounding box
        x0 = int(max(0, pts[:, 0].min()))
        x1 = int(min(atlas_size - 1, pts[:, 0].max())) + 1
        y0 = int(max(0, pts[:, 1].min()))
        y1 = int(min(atlas_size - 1, pts[:, 1].max())) + 1
        if x1 <= x0 or y1 <= y0:
            continue
        # 用 PIL 在小區域畫填滿三角形
        sub = Image.new("L", (x1 - x0, y1 - y0), 0)
        sd = ImageDraw.Draw(sub)
        rel = [(p[0] - x0, p[1] - y0) for p in pts]
        sd.polygon(rel, fill=255)
        sub_arr = np.array(sub) > 0
        canvas[y0:y1, x0:x1][sub_arr] = avg
        mask[y0:y1, x0:x1] |= sub_arr

    if not mask.any():
        return Image.new("RGB", (atlas_size, atlas_size), (32, 32, 32))

    # 正規化到 0-255
    vmin, vmax = canvas[mask].min(), canvas[mask].max()
    norm = np.zeros_like(canvas)
    if vmax > vmin:
        norm = (canvas - vmin) / (vmax - vmin)
    norm = np.clip(norm * 255, 0, 255).astype(np.uint8)
    # 套用偽彩色（簡單藍-綠-紅 gradient）
    rgb = np.stack([
        norm,
        np.where(norm > 128, 255 - (norm - 128) * 2, norm * 2),  # peak at middle
        255 - norm,
    ], axis=-1)
    rgb[~mask] = (32, 32, 32)
    return Image.fromarray(rgb)


def main() -> int:
    out_dir = PROJECT_ROOT / "output" / "_debug"
    out_dir.mkdir(parents=True, exist_ok=True)

    vrm_path = PROJECT_ROOT / "assets" / "base_models" / "AvatarSample_A.vrm"
    print(f"Loading {vrm_path.name}...")
    data = extract_face_skin_primitive(vrm_path)

    print("Rendering UV layout...")
    img1 = render_uv_layout(data["uvs"], data["indices"])
    img1.save(out_dir / "uv_layout.png")
    print(f"  saved: {out_dir / 'uv_layout.png'}")

    print("Rendering front view (3D POSITION projected to XY)...")
    img2 = render_front_view(data["positions"], data["indices"])
    img2.save(out_dir / "front_view.png")
    print(f"  saved: {out_dir / 'front_view.png'}")

    print("Rendering UV-to-3D X heatmap (left/right)...")
    img3 = render_heatmap_uv_to_3d(data["uvs"], data["positions"], data["indices"], axis=0)
    img3.save(out_dir / "uv_to_3d_x.png")
    print(f"  saved: {out_dir / 'uv_to_3d_x.png'}")

    print("Rendering UV-to-3D Y heatmap (down/up)...")
    img4 = render_heatmap_uv_to_3d(data["uvs"], data["positions"], data["indices"], axis=1)
    img4.save(out_dir / "uv_to_3d_y.png")
    print(f"  saved: {out_dir / 'uv_to_3d_y.png'}")

    # 同時也 save raw mesh data 給 face_baker 用
    np.savez(
        out_dir / "face_skin_mesh_A.npz",
        positions=data["positions"],
        uvs=data["uvs"],
        indices=data["indices"],
    )
    print(f"  raw mesh saved: {out_dir / 'face_skin_mesh_A.npz'}")
    print("\nDone. 請肉眼檢查 4 張圖確認解析正確。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
