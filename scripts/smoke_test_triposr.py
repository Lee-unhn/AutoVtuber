"""TripoSR 真實推論 smoke test。

使用既有的 SDXL 概念圖跑一次完整 TripoSR pipeline：
    1. 第一次跑會由 hf_hub_download 下載 ~1.7GB ckpt 到 HF cache
    2. 推論 + marching cubes（PyMCubes shim, CPU）
    3. 輸出 .obj 到 output/_triposr_smoke.obj 供肉眼驗收

執行：
    C:\\avt\\venv\\Scripts\\python.exe C:\\avt\\scripts\\smoke_test_triposr.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# 保證 stdout 能寫 emoji / 中文（cp950 console 預設會炸）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def main() -> int:
    from PIL import Image

    from autovtuber.config.paths import Paths
    from autovtuber.config.settings import load_settings, resolved_paths
    from autovtuber.pipeline.image_to_3d import ImageTo3D
    from autovtuber.safety.hardware_guard import HardwareGuard, precheck_hardware_or_exit
    from autovtuber.safety.model_loader import ModelLoader
    from autovtuber.safety.thresholds import Thresholds
    from autovtuber.utils.logging_setup import configure as configure_logging

    paths = Paths()
    paths.ensure_writable_dirs()
    settings = load_settings(paths)
    paths = resolved_paths(settings)
    configure_logging(paths.logs, level="INFO")

    # 找最新的 SDXL 概念圖
    concept_pngs = sorted(paths.output.glob("character_*_concept.png"))
    if not concept_pngs:
        print("[FAIL] 找不到任何 character_*_concept.png；先跑 smoke_test_e2e.py 產出一張")
        return 1
    src_png = concept_pngs[-1]
    print(f"[1/5] 使用既有 SDXL 概念圖：{src_png.name}")

    image = Image.open(src_png).convert("RGB")
    print(f"      尺寸：{image.size} mode={image.mode}")

    print("[2/5] Hardware precheck...")
    precheck_hardware_or_exit()
    print("      OK")

    thresholds = Thresholds.from_settings(settings.safety)
    with HardwareGuard(thresholds) as guard:
        loader = ModelLoader(guard)

        print("[3/5] Constructing ImageTo3D...")
        # 第一次測試用 mc_resolution=128（PyMCubes CPU 約 5 秒；256 約 30 秒）
        i23 = ImageTo3D(loader, guard, paths.models, mc_resolution=128)
        print(f"      mc_resolution=128 chunk_size={i23.DEFAULT_CHUNK_SIZE}")

        print("[4/5] Running TripoSR inference...")
        print("      (首次跑會下載 ~1.7GB checkpoint 到 HF cache，可能需 1-3 分鐘)")

        def _progress(stage, cur, tot):
            print(f"        [{stage}] {cur}/{tot}")

        t0 = time.time()
        try:
            mesh = i23.generate(image, progress_cb=_progress)
        except Exception as e:
            print(f"[FAIL] TripoSR inference 例外：{type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return 1
        elapsed = time.time() - t0

        print(f"      [OK] 完成 - 用時 {elapsed:.1f} 秒")
        print(f"      mesh: {len(mesh.vertices)} verts / {len(mesh.faces)} faces")

        # 立刻 export — 防止後面 print 錯誤導致 mesh 物件沒落地
        out_obj = paths.output / "_triposr_smoke.obj"
        out_glb = paths.output / "_triposr_smoke.glb"
        try:
            mesh.export(out_obj)
            print(f"      [export OBJ] {out_obj} ({out_obj.stat().st_size / 1024:.1f} KB)")
        except Exception as e:
            print(f"      [WARN] OBJ export failed: {e}")
        try:
            mesh.export(out_glb)
            print(f"      [export GLB] {out_glb} ({out_glb.stat().st_size / 1024:.1f} KB)")
        except Exception as e:
            print(f"      [WARN] GLB export failed: {e}")

        # bbox / scale
        try:
            bb = mesh.bounding_box.bounds
            size = bb[1] - bb[0]
            print(f"      bbox min={bb[0]} max={bb[1]} size={size}")
        except Exception:
            print("      (bbox 無法計算)")

        # 是否有 vertex colors
        has_colors = mesh.visual is not None and getattr(mesh.visual, "vertex_colors", None) is not None
        if has_colors:
            colors = mesh.visual.vertex_colors
            print(f"      vertex_colors shape={colors.shape} dtype={colors.dtype}")
        else:
            print("      ⚠️ 無 vertex colors")

    print("=" * 60)
    print("[OK] TripoSR 真實 inference smoke test 完成")
    print()
    print("肉眼驗收 .obj / .glb:")
    print("  - Windows 內建 3D Viewer 開 .glb (雙擊或右鍵開啟)")
    print("  - https://gltf-viewer.donmccurdy.com/ 拖 .glb 上去")
    print("  - Blender 匯入 .obj (File - Import - Wavefront)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
