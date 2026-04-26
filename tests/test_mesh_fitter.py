"""MeshFitter 測試 — 用合成 mesh 驗 bake 邏輯。

策略：
    - 不依賴真實 VRM 檔（測試 fixtures 不放真實 VRoid 模型）
    - Mock `extract_face_mesh_from_vrm` 回傳手寫的 FaceMeshData
    - Mock `VRMFile.load` + `get_image_pil` 回傳純色測試圖
    - 用 trimesh.creation 造一個有 vertex_colors 的 sphere 當 TSR mesh
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import trimesh
from PIL import Image

from autovtuber.pipeline.face_baker import FaceMeshData
from autovtuber.pipeline.mesh_fitter import FitResult, MeshFitter
from autovtuber.vrm.texture_atlas import AtlasMap


def make_synthetic_face_mesh() -> FaceMeshData:
    """造一個簡單的「方臉」mesh：4 個 verts、2 個三角形，UV 鋪滿整張 atlas。"""
    positions = np.array(
        [
            [-0.05, 0.0, -0.1],   # 左下角  3D 位置（VRoid 公尺）
            [0.05, 0.0, -0.1],    # 右下
            [0.05, 0.1, -0.1],    # 右上
            [-0.05, 0.1, -0.1],   # 左上
        ],
        dtype=np.float32,
    )
    uvs = np.array(
        [
            [0.0, 0.0],   # 左下 UV
            [1.0, 0.0],   # 右下
            [1.0, 1.0],   # 右上
            [0.0, 1.0],   # 左上
        ],
        dtype=np.float32,
    )
    # 兩個三角形組成 quad，winding 朝 -Z (front)
    indices = np.array([[0, 2, 1], [0, 3, 2]], dtype=np.int64)
    return FaceMeshData(positions=positions, uvs=uvs, indices=indices)


def make_colored_sphere_mesh(color_rgba=(200, 50, 50, 255), n_subdiv=2) -> trimesh.Trimesh:
    """造一個球體 + 統一 vertex color，當作 TSR mesh 替身。"""
    sphere = trimesh.creation.icosphere(subdivisions=n_subdiv, radius=0.5)
    n_v = len(sphere.vertices)
    colors = np.tile(np.array(color_rgba, dtype=np.uint8), (n_v, 1))
    sphere.visual.vertex_colors = colors
    return sphere


# ---------------- 測試 ---------------- #


def test_fit_returns_atlas_with_tsr_color_in_face_region(tmp_path: Path):
    """整體 sanity: TSR 球體 colored = (200,50,50)，bake 後 atlas 中央 pixel 應接近此色。"""
    fake_face = make_synthetic_face_mesh()
    fake_tsr = make_colored_sphere_mesh(color_rgba=(200, 50, 50, 255))

    # 原 atlas 是純白 64x64
    fake_atlas = Image.new("RGBA", (64, 64), (255, 255, 255, 255))

    fake_vrm = MagicMock()
    fake_vrm.get_image_pil = MagicMock(return_value=fake_atlas)

    with patch(
        "autovtuber.pipeline.mesh_fitter.extract_face_mesh_from_vrm",
        return_value=fake_face,
    ), patch(
        "autovtuber.vrm.vrm_io.VRMFile.load",
        return_value=fake_vrm,
    ):
        fitter = MeshFitter(mode="replace", feather_pixels=0)  # 關掉 feather 方便驗顏色精確
        atlas_map = AtlasMap(face_skin_index=0, hair_index=1, eye_iris_index=2)
        fake_path = tmp_path / "fake.vrm"
        fake_path.write_bytes(b"")  # 路徑要存在，內容不重要（被 mock）
        result = fitter.fit(fake_tsr, fake_path, atlas_map)

    assert isinstance(result, FitResult)
    out = np.array(result.face_skin)
    assert out.shape == (64, 64, 4)

    # atlas 中央 pixel 應是被替換成 TSR color (200, 50, 50)
    cx, cy = 32, 32
    center_rgb = out[cy, cx, :3]
    # KDTree 會找球面最近頂點，全部 color 都一樣 (200,50,50)
    assert center_rgb[0] >= 195 and center_rgb[0] <= 205
    assert center_rgb[1] >= 45 and center_rgb[1] <= 55
    assert center_rgb[2] >= 45 and center_rgb[2] <= 55


def test_fit_handles_visual_with_texture_only(tmp_path: Path):
    """TSR mesh 用 TextureVisuals（沒 vertex_colors 屬性）→ 回傳原 atlas + 警告。"""
    fake_face = make_synthetic_face_mesh()
    sphere = trimesh.creation.icosphere(subdivisions=1, radius=0.5)
    # 替換 visual 成 TextureVisuals — trimesh 會無 vertex_colors 屬性
    sphere.visual = trimesh.visual.TextureVisuals()

    fake_atlas = Image.new("RGBA", (32, 32), (123, 222, 100, 255))
    fake_vrm = MagicMock(get_image_pil=MagicMock(return_value=fake_atlas))

    with patch(
        "autovtuber.pipeline.mesh_fitter.extract_face_mesh_from_vrm",
        return_value=fake_face,
    ), patch(
        "autovtuber.vrm.vrm_io.VRMFile.load",
        return_value=fake_vrm,
    ):
        fitter = MeshFitter(mode="replace")
        atlas_map = AtlasMap(face_skin_index=0, hair_index=1, eye_iris_index=2)
        fake_path = tmp_path / "fake.vrm"
        fake_path.write_bytes(b"")
        result = fitter.fit(sphere, fake_path, atlas_map)

    out = np.array(result.face_skin)
    assert (out == np.array(fake_atlas)).all()
    assert result.debug.pixels_written == 0


def test_back_face_culling_skips_facing_away_triangles(tmp_path: Path):
    """winding 朝後（normals.z > 0）的三角形不寫入 atlas。"""
    # 造一個「朝後」的方臉（winding 反向）
    positions = np.array([
        [-0.05, 0.0, -0.1],
        [0.05, 0.0, -0.1],
        [0.05, 0.1, -0.1],
        [-0.05, 0.1, -0.1],
    ], dtype=np.float32)
    uvs = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
    # 反向 winding：normals 朝 +Z（朝後）
    indices = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    back_facing = FaceMeshData(positions=positions, uvs=uvs, indices=indices)

    fake_tsr = make_colored_sphere_mesh(color_rgba=(255, 0, 0, 255))
    fake_atlas = Image.new("RGBA", (32, 32), (10, 20, 30, 255))
    fake_vrm = MagicMock(get_image_pil=MagicMock(return_value=fake_atlas))

    with patch(
        "autovtuber.pipeline.mesh_fitter.extract_face_mesh_from_vrm",
        return_value=back_facing,
    ), patch(
        "autovtuber.vrm.vrm_io.VRMFile.load",
        return_value=fake_vrm,
    ):
        fitter = MeshFitter(mode="replace", cull_back_faces=True)
        atlas_map = AtlasMap(face_skin_index=0, hair_index=1, eye_iris_index=2)
        fake_path = tmp_path / "fake.vrm"
        fake_path.write_bytes(b"")
        result = fitter.fit(fake_tsr, fake_path, atlas_map)

    # 全部三角形被 culling → 沒寫到任何 pixel → atlas 跟原圖一致
    assert result.debug.triangles_culled_back == 2
    assert result.debug.pixels_written == 0
    out = np.array(result.face_skin)
    assert (out == np.array(fake_atlas)).all()


def test_back_face_culling_disabled_writes_anyway(tmp_path: Path):
    """關 cull_back_faces 時，朝後三角形也會被寫入。"""
    positions = np.array([
        [-0.05, 0.0, -0.1],
        [0.05, 0.0, -0.1],
        [0.05, 0.1, -0.1],
        [-0.05, 0.1, -0.1],
    ], dtype=np.float32)
    uvs = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
    indices = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    back_facing = FaceMeshData(positions=positions, uvs=uvs, indices=indices)

    fake_tsr = make_colored_sphere_mesh(color_rgba=(255, 0, 0, 255))
    fake_atlas = Image.new("RGBA", (32, 32), (10, 20, 30, 255))
    fake_vrm = MagicMock(get_image_pil=MagicMock(return_value=fake_atlas))

    with patch(
        "autovtuber.pipeline.mesh_fitter.extract_face_mesh_from_vrm",
        return_value=back_facing,
    ), patch(
        "autovtuber.vrm.vrm_io.VRMFile.load",
        return_value=fake_vrm,
    ):
        fitter = MeshFitter(mode="replace", cull_back_faces=False, feather_pixels=0)
        atlas_map = AtlasMap(face_skin_index=0, hair_index=1, eye_iris_index=2)
        fake_path = tmp_path / "fake.vrm"
        fake_path.write_bytes(b"")
        result = fitter.fit(fake_tsr, fake_path, atlas_map)

    assert result.debug.pixels_written > 0
    # 中央 pixel 應該被改成紅色
    out = np.array(result.face_skin)
    assert out[16, 16, 0] > 200


def test_alignment_transform_flips_y_when_enabled(tmp_path: Path):
    """flip_tsr_y=True 時，VRoid +Y 對應 TSR -Y（驗 transform 邏輯）。"""
    # 簡化測試：只驗 fitter 在 flip_tsr_y=True 時，TSR mesh Y 軸朝下能對應到 VRoid Y 軸朝上
    # 用一個 TSR mesh 上半（+Y）= 紅色，下半（-Y）= 藍色，驗 VRoid Y 對應正確
    sphere = trimesh.creation.icosphere(subdivisions=2, radius=0.5)
    colors = np.zeros((len(sphere.vertices), 4), dtype=np.uint8)
    colors[:, 3] = 255
    # 上半紅，下半藍
    upper_mask = sphere.vertices[:, 1] > 0
    colors[upper_mask] = [255, 0, 0, 255]
    colors[~upper_mask] = [0, 0, 255, 255]
    sphere.visual.vertex_colors = colors

    fake_face = make_synthetic_face_mesh()  # VRoid +Y 朝上：第 4 個 vert 在 y=0.1（上）
    fake_atlas = Image.new("RGBA", (64, 64), (128, 128, 128, 255))
    fake_vrm = MagicMock(get_image_pil=MagicMock(return_value=fake_atlas))

    with patch(
        "autovtuber.pipeline.mesh_fitter.extract_face_mesh_from_vrm",
        return_value=fake_face,
    ), patch(
        "autovtuber.vrm.vrm_io.VRMFile.load",
        return_value=fake_vrm,
    ):
        fitter = MeshFitter(mode="replace", flip_tsr_y=True, feather_pixels=0, cull_back_faces=False)
        atlas_map = AtlasMap(face_skin_index=0, hair_index=1, eye_iris_index=2)
        fake_path = tmp_path / "fake.vrm"
        fake_path.write_bytes(b"")
        result = fitter.fit(sphere, fake_path, atlas_map)

    out = np.array(result.face_skin)
    # VRoid UV (0.5, 1.0) = atlas top → 對應 face_mesh 高 Y → 應採到「TSR 下半」(藍)
    # 因為 flip_tsr_y=True 把 VRoid +Y 翻到 TSR -Y
    # atlas 慣例：UV (x, 1) → image y=0（top）
    top_pixel = out[2, 32, :3]   # atlas top 中央
    bot_pixel = out[62, 32, :3]  # atlas bottom 中央
    # atlas top 對應 VRoid 高 Y → flip 後對應 TSR 低 Y → 應藍色
    # atlas bot 對應 VRoid 低 Y → flip 後對應 TSR 高 Y → 應紅色
    assert top_pixel[2] > top_pixel[0], f"top should be blue-dominant, got {top_pixel}"
    assert bot_pixel[0] > bot_pixel[2], f"bot should be red-dominant, got {bot_pixel}"


def test_feather_blends_with_original_atlas(tmp_path: Path):
    """feather_pixels>0 時，pixel 邊緣會與原 atlas 平滑融合。

    用只覆蓋 atlas 中央 50% 的小三角形，留出邊緣讓 feather 看得出差異。
    """
    # UV 只覆蓋 0.25-0.75 的中央方塊（atlas 50% 邊有空間給 feather）
    positions = np.array([
        [-0.05, 0.0, -0.1],
        [0.05, 0.0, -0.1],
        [0.05, 0.1, -0.1],
        [-0.05, 0.1, -0.1],
    ], dtype=np.float32)
    uvs = np.array([
        [0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75],
    ], dtype=np.float32)
    indices = np.array([[0, 2, 1], [0, 3, 2]], dtype=np.int64)
    small_face = FaceMeshData(positions=positions, uvs=uvs, indices=indices)

    fake_tsr = make_colored_sphere_mesh(color_rgba=(255, 0, 0, 255))
    fake_atlas = Image.new("RGBA", (64, 64), (0, 0, 0, 255))
    fake_vrm = MagicMock(get_image_pil=MagicMock(return_value=fake_atlas))

    with patch(
        "autovtuber.pipeline.mesh_fitter.extract_face_mesh_from_vrm",
        return_value=small_face,
    ), patch(
        "autovtuber.vrm.vrm_io.VRMFile.load",
        return_value=fake_vrm,
    ):
        fitter_no_feather = MeshFitter(mode="replace", feather_pixels=0)
        fitter_with_feather = MeshFitter(mode="replace", feather_pixels=8)
        atlas_map = AtlasMap(face_skin_index=0, hair_index=1, eye_iris_index=2)
        fake_path = tmp_path / "fake.vrm"
        fake_path.write_bytes(b"")
        r1 = fitter_no_feather.fit(fake_tsr, fake_path, atlas_map)
        r2 = fitter_with_feather.fit(fake_tsr, fake_path, atlas_map)

    a1 = np.array(r1.face_skin).astype(np.int32)
    a2 = np.array(r2.face_skin).astype(np.int32)
    # 中央區 (32,32) 都應是紅色
    assert a1[32, 32, 0] > 200 and a2[32, 32, 0] > 100
    # 邊界附近 (atlas pixel 約 16 = uv 0.25 對應的位置)：feather 版會是過渡色
    # no-feather: 應該是 0 (黑) 或 255 (紅) 二元
    # feather:    應該介於兩者之間
    edge_no_feather = a1[16, 32, 0]   # atlas y=16 = uv y=0.75 邊界附近
    edge_with_feather = a2[16, 32, 0]
    # 至少在某些邊緣位置有差異
    assert (a1 != a2).any(), "feather should produce different output near boundary"


def test_tint_mode_preserves_atlas_structure(tmp_path: Path):
    """tint 模式：原 atlas 中 (1) feature pixel（暗）保留 (2) skin pixel（peach）被 tint。"""
    # 模擬 VRoid 真實 atlas：peach skin 底 + 中央黑色橢圓（眼眶）
    atlas = np.zeros((64, 64, 4), dtype=np.uint8)
    atlas[..., 0] = 230  # R
    atlas[..., 1] = 200  # G
    atlas[..., 2] = 190  # B  → peach skin tone
    atlas[..., 3] = 255
    # 中央放黑色斑點（眼眶 / 五官）
    atlas[24:28, 20:30] = [10, 10, 10, 255]
    atlas[24:28, 34:44] = [10, 10, 10, 255]
    fake_atlas = Image.fromarray(atlas, mode="RGBA")

    sphere = trimesh.creation.icosphere(subdivisions=3, radius=0.5)
    n = len(sphere.vertices)
    # 把目標膚色設成「冷色 cool peach」(R 等於 G 但 B 偏低 → 還是 peach 但較冷)
    # 為了測得到差異，TSR 給冷色，VRoid base 是暖色
    colors = np.tile(np.array([200, 220, 240, 255], dtype=np.uint8), (n, 1))  # cool blue-ish
    sphere.visual.vertex_colors = colors

    fake_vrm = MagicMock(get_image_pil=MagicMock(return_value=fake_atlas))

    with patch(
        "autovtuber.vrm.vrm_io.VRMFile.load",
        return_value=fake_vrm,
    ):
        fitter = MeshFitter(mode="tint", tint_strength=0.7)
        atlas_map = AtlasMap(face_skin_index=0, hair_index=1, eye_iris_index=2)
        fake_path = tmp_path / "fake.vrm"
        fake_path.write_bytes(b"")
        result = fitter.fit(sphere, fake_path, atlas_map)

    out = np.array(result.face_skin)
    # 1. 中央黑斑（feature）應仍是暗色，未被 tint（low luminance 排除在 mask 外）
    eye_pixel = out[26, 25]
    assert eye_pixel[:3].mean() < 80, f"feature pixel should remain dark, got {eye_pixel}"
    # 2. skin pixel 應被 tint 改變顏色（從 peach 230,200,190 朝 cool 200,220,240 偏）
    orig_skin = atlas[10, 10, :3]
    new_skin = out[10, 10, :3]
    # skin 應該有改變
    assert not np.array_equal(orig_skin, new_skin), \
        f"skin should be tinted, orig={orig_skin}, new={new_skin}"


def test_tint_mode_zero_strength_returns_original(tmp_path: Path):
    """tint_strength=0 應該不改變 atlas（除了 RGB ↔ HLS 浮點誤差）。"""
    atlas = np.array([
        [[100, 50, 200, 255], [200, 100, 50, 255]],
        [[50, 200, 100, 255], [180, 180, 180, 255]],
    ], dtype=np.uint8)
    fake_atlas = Image.fromarray(atlas, mode="RGBA")

    sphere = trimesh.creation.icosphere(subdivisions=2, radius=0.5)
    sphere.visual.vertex_colors = np.tile([255, 0, 0, 255], (len(sphere.vertices), 1))

    fake_vrm = MagicMock(get_image_pil=MagicMock(return_value=fake_atlas))

    with patch(
        "autovtuber.vrm.vrm_io.VRMFile.load",
        return_value=fake_vrm,
    ):
        fitter = MeshFitter(mode="tint", tint_strength=0.0)
        atlas_map = AtlasMap(face_skin_index=0, hair_index=1, eye_iris_index=2)
        fake_path = tmp_path / "fake.vrm"
        fake_path.write_bytes(b"")
        result = fitter.fit(sphere, fake_path, atlas_map)

    out = np.array(result.face_skin)
    # 0 strength → 與原 atlas 接近（容忍 ±2 浮點誤差）
    diff = np.abs(out.astype(np.int32) - atlas.astype(np.int32))
    assert diff.max() <= 5, f"strength=0 should preserve atlas, max diff={diff.max()}"


def test_sample_skin_tone_returns_none_for_no_visual():
    """TSR mesh 沒 vertex_colors → 不採樣 → return None。"""
    sphere = trimesh.creation.icosphere(subdivisions=2, radius=0.5)
    sphere.visual = trimesh.visual.TextureVisuals()

    fitter = MeshFitter()
    skin = fitter.sample_skin_tone_rgb(sphere)
    assert skin is None


def test_sample_skin_tone_filters_extremes():
    """採樣應排除過暗（髮）與過亮（反光點）的 vertex。"""
    sphere = trimesh.creation.icosphere(subdivisions=3, radius=0.5)
    n = len(sphere.vertices)
    colors = np.zeros((n, 4), dtype=np.uint8)
    colors[:, 3] = 255
    # 一半 vertices 設成黑髮（10,10,10）；另一半設成 peach 膚色 (255, 200, 170)
    half = n // 2
    colors[:half] = [10, 10, 10, 255]
    colors[half:] = [255, 200, 170, 255]
    sphere.visual.vertex_colors = colors

    fitter = MeshFitter()
    skin = fitter.sample_skin_tone_rgb(sphere)
    assert skin is not None
    # 應排除黑色 → 採到 peach
    assert skin[0] > 200, f"R should be high (peach), got {skin}"
    assert skin[1] > 150
    assert skin[2] > 130


def test_invalid_mode_raises():
    with pytest.raises(ValueError, match="mode must be"):
        MeshFitter(mode="bogus")


def test_debug_info_records_bbox_and_counts(tmp_path: Path):
    fake_face = make_synthetic_face_mesh()
    fake_tsr = make_colored_sphere_mesh()
    fake_atlas = Image.new("RGBA", (32, 32), (255, 255, 255, 255))
    fake_vrm = MagicMock(get_image_pil=MagicMock(return_value=fake_atlas))

    with patch(
        "autovtuber.pipeline.mesh_fitter.extract_face_mesh_from_vrm",
        return_value=fake_face,
    ), patch(
        "autovtuber.vrm.vrm_io.VRMFile.load",
        return_value=fake_vrm,
    ):
        fitter = MeshFitter(mode="replace")
        atlas_map = AtlasMap(face_skin_index=0, hair_index=1, eye_iris_index=2)
        fake_path = tmp_path / "fake.vrm"
        fake_path.write_bytes(b"")
        result = fitter.fit(fake_tsr, fake_path, atlas_map)

    d = result.debug
    assert d.triangles_processed >= 1
    assert d.pixels_written > 0
    # bbox 都應該不是預設零
    assert d.vroid_bbox != ((0, 0, 0), (0, 0, 0))
    assert d.tsr_bbox != ((0, 0, 0), (0, 0, 0))
