"""MeshFitter 真實 smoke test。

用 output/_triposr_smoke.glb（前一個 smoke test 出的 TSR mesh）+ AvatarSample_A.vrm
跑 MeshFitter，輸出比對前/後的 face skin atlas PNG。

執行：
    C:\\avt\\venv\\Scripts\\python.exe C:\\avt\\scripts\\smoke_test_mesh_fitter.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def main() -> int:
    import trimesh

    from autovtuber.pipeline.mesh_fitter import MeshFitter
    from autovtuber.utils.logging_setup import configure as configure_logging
    from autovtuber.config.paths import Paths
    from autovtuber.config.settings import load_settings, resolved_paths
    from autovtuber.vrm.texture_atlas import AtlasMap
    from autovtuber.vrm.vrm_io import VRMFile

    paths = Paths()
    paths.ensure_writable_dirs()
    settings = load_settings(paths)
    paths = resolved_paths(settings)
    configure_logging(paths.logs, level="INFO")

    tsr_glb = paths.output / "_triposr_smoke.glb"
    base_vrm = paths.base_models / "AvatarSample_A.vrm"

    if not tsr_glb.exists():
        print(f"[FAIL] {tsr_glb} 不存在；先跑 smoke_test_triposr.py")
        return 1
    if not base_vrm.exists():
        print(f"[FAIL] {base_vrm} 不存在")
        return 1

    print(f"[1/4] 載入 TSR mesh: {tsr_glb.name}")
    loaded = trimesh.load(tsr_glb, force="mesh")
    if isinstance(loaded, trimesh.Scene):
        loaded = list(loaded.geometry.values())[0]
    tsr_mesh = loaded
    print(f"      verts={len(tsr_mesh.vertices)} faces={len(tsr_mesh.faces)}")

    print(f"[2/4] 載入 base VRM: {base_vrm.name}")
    atlas_map = AtlasMap.for_base_model("AvatarSample_A")
    vrm = VRMFile.load(base_vrm)
    orig_face_skin = vrm.get_image_pil(atlas_map.face_skin_index).convert("RGBA")
    orig_path = paths.output / "_meshfit_before.png"
    orig_face_skin.save(orig_path)
    print(f"      原 face_skin atlas 大小 {orig_face_skin.size} → 存 {orig_path.name}")

    # 找最新的 SDXL 概念圖傳入（優先採膚色用）
    sdxl_portraits = sorted(paths.output.glob("character_*_concept.png"))
    sdxl_portrait = None
    if sdxl_portraits:
        from PIL import Image as _PILImage
        sdxl_portrait = _PILImage.open(sdxl_portraits[-1]).convert("RGB")
        print(f"[2.5/4] 使用 SDXL portrait 採膚色: {sdxl_portraits[-1].name}")

    print("[3/4] MeshFitter 烘焙 (mode=tint)...")
    fitter = MeshFitter(mode="tint", tint_strength=0.7)
    t0 = time.time()
    result = fitter.fit(tsr_mesh, base_vrm, atlas_map, sdxl_portrait=sdxl_portrait)
    elapsed = time.time() - t0
    d = result.debug
    print(f"      用時 {elapsed:.1f} 秒")
    print(f"      triangles processed = {d.triangles_processed}")
    print(f"      triangles culled    = {d.triangles_culled_back}")
    print(f"      pixels written      = {d.pixels_written}")
    print(f"      VRoid bbox: {d.vroid_bbox}")
    print(f"      TSR   bbox: {d.tsr_bbox}")

    print("[4/4] 存檔...")
    after_path = paths.output / "_meshfit_after.png"
    result.face_skin.save(after_path)
    print(f"      新 face_skin → {after_path.name} ({after_path.stat().st_size/1024:.1f} KB)")

    # 比對拼貼
    from PIL import Image
    canvas = Image.new("RGB", (orig_face_skin.width * 2 + 16, orig_face_skin.height + 32), (30, 30, 30))
    canvas.paste(orig_face_skin.convert("RGB"), (0, 32))
    canvas.paste(result.face_skin.convert("RGB"), (orig_face_skin.width + 16, 32))
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()
    draw.text((8, 8), "BEFORE (original VRoid face skin)", fill=(255, 255, 255), font=font)
    draw.text((orig_face_skin.width + 24, 8), "AFTER (fitted from TSR mesh)", fill=(255, 255, 255), font=font)

    compare_path = paths.output / "_meshfit_compare.png"
    canvas.save(compare_path)
    print(f"      對比圖 → {compare_path.name}")

    # 套用新 atlas 寫成 .vrm
    print("[5/6] 套用新 face_skin → 寫 .vrm...")
    new_vrm = VRMFile.load(base_vrm)
    new_vrm.replace_image(atlas_map.face_skin_index, result.face_skin)
    out_vrm = paths.output / "_meshfit_smoke.vrm"
    new_vrm.save(out_vrm)
    print(f"      → {out_vrm.name} ({out_vrm.stat().st_size/1024/1024:.1f} MB)")

    # 渲染 VRM 三視角（前/側/3-4）— 載 .vrm 為 trimesh.Scene
    print("[6/6] 渲染 .vrm 三視角預覽...")
    try:
        # VRM 內部就是 GLB；強制指定 file_type 繞過副檔名檢查
        with open(out_vrm, "rb") as f:
            vrm_scene = trimesh.load(f, file_type="glb", force="scene")
        # 合併所有 geom 成單一 mesh 給 pyrender
        if isinstance(vrm_scene, trimesh.Scene):
            print(f"      Scene 有 {len(vrm_scene.geometry)} geom；合併成預覽 mesh")
            geoms = list(vrm_scene.geometry.values())
            if not geoms:
                raise RuntimeError("VRM 無 geometry")
            # 合併
            preview = trimesh.util.concatenate(geoms)
        else:
            preview = vrm_scene

        # 用 render_mesh_preview 同樣的 pyrender pipeline
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from render_mesh_preview import render_six_views
        out_render = paths.output / "_meshfit_vrm_preview.png"
        render_six_views(preview, out_render)
        print(f"      → {out_render.name} ({out_render.stat().st_size/1024:.1f} KB)")
    except Exception as e:
        print(f"      [WARN] VRM 預覽失敗 (非阻塞): {type(e).__name__}: {e}")

    print()
    print("[OK] MeshFitter smoke test 完成")
    print(f"     atlas 比對: {compare_path}")
    print(f"     新 .vrm   : {out_vrm}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
