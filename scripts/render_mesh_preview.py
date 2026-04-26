"""把 trimesh 從多角度渲成 PNG，用 pyrender 真實 GPU/OSMesa offscreen render。

執行：
    C:\\avt\\venv\\Scripts\\python.exe C:\\avt\\scripts\\render_mesh_preview.py [obj_or_glb_path]

預設：output/_triposr_smoke.glb
輸出：output/_triposr_smoke_preview.png（六視角拼貼）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# pyrender 在 Windows 預設用 native OpenGL；不要硬塞 PYOPENGL_PLATFORM=空字串
# 若使用者環境已設成不合理值，清掉
if os.environ.get("PYOPENGL_PLATFORM") == "":
    os.environ.pop("PYOPENGL_PLATFORM", None)

import numpy as np  # noqa: E402
import pyrender  # noqa: E402
import trimesh  # noqa: E402
from PIL import Image  # noqa: E402


def render_six_views(mesh: trimesh.Trimesh, out_png: Path) -> None:
    """六視角拼貼（正/背/左/右/俯/3-4），用 pyrender offscreen renderer。"""
    # 把原 trimesh.Trimesh 包成 pyrender Mesh — 自動處理 vertex_colors
    pr_mesh = pyrender.Mesh.from_trimesh(mesh, smooth=False)

    bbox = mesh.bounding_box.bounds  # (2, 3)
    center = (bbox[0] + bbox[1]) / 2.0
    diag = float(np.linalg.norm(bbox[1] - bbox[0]))
    cam_dist = diag * 1.4

    views = [
        ("front (+Z)",  np.array([0.0, 0.0, 1.0])),
        ("back (-Z)",   np.array([0.0, 0.0, -1.0])),
        ("left (-X)",   np.array([-1.0, 0.0, 0.0])),
        ("right (+X)",  np.array([1.0, 0.0, 0.0])),
        ("top (+Y)",    np.array([0.0, 1.0, 0.001])),  # 加微小 z 避免 lookAt 退化
        ("3/4 view",    np.array([0.7, 0.3, 0.7])),
    ]

    width, height = 480, 480
    renderer = pyrender.OffscreenRenderer(viewport_width=width, viewport_height=height)

    rendered: list[tuple[str, np.ndarray]] = []
    for name, dir_vec in views:
        scene = pyrender.Scene(
            bg_color=np.array([0.12, 0.12, 0.12, 1.0]),
            ambient_light=np.array([0.4, 0.4, 0.4]),
        )
        scene.add(pr_mesh)

        # Camera：正交投影看得清楚整體（perspective 在這 size 容易裁掉）
        cam = pyrender.OrthographicCamera(xmag=diag * 0.55, ymag=diag * 0.55)
        cam_pose = _look_at(center + dir_vec * cam_dist, center, up=_pick_up(dir_vec))
        scene.add(cam, pose=cam_pose)

        # 三點打光（跟相機綁在一起，避免 mesh 完全黑）
        light = pyrender.DirectionalLight(color=np.ones(3), intensity=3.0)
        scene.add(light, pose=cam_pose)

        # 補光從另一側
        side = np.array([dir_vec[2], 0.5, -dir_vec[0]])
        side_pose = _look_at(center + side * cam_dist, center, up=np.array([0, 1, 0]))
        light2 = pyrender.DirectionalLight(color=np.ones(3), intensity=1.5)
        scene.add(light2, pose=side_pose)

        color, _depth = renderer.render(scene)
        rendered.append((name, color))

    renderer.delete()

    # 拼貼成 2×3 grid
    rows, cols = 2, 3
    pad = 8
    label_h = 28
    out_w = cols * width + (cols + 1) * pad
    out_h = rows * (height + label_h) + (rows + 1) * pad

    canvas = Image.new("RGB", (out_w, out_h), (30, 30, 30))
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()

    for i, (name, img_arr) in enumerate(rendered):
        r, c = divmod(i, cols)
        x = pad + c * (width + pad)
        y = pad + r * (height + label_h + pad)
        draw.text((x + 6, y + 4), name, fill=(220, 220, 220), font=font)
        canvas.paste(Image.fromarray(img_arr), (x, y + label_h))

    # 標題列
    title = f"TripoSR mesh — {len(mesh.vertices)} verts / {len(mesh.faces)} faces"
    title_canvas = Image.new("RGB", (out_w, 32), (30, 30, 30))
    ImageDraw.Draw(title_canvas).text(
        (pad, 8), title, fill=(255, 255, 255), font=font,
    )
    final = Image.new("RGB", (out_w, out_h + 32), (30, 30, 30))
    final.paste(title_canvas, (0, 0))
    final.paste(canvas, (0, 32))
    final.save(out_png)


def _look_at(eye: np.ndarray, center: np.ndarray, up: np.ndarray) -> np.ndarray:
    """回傳 4×4 相機 pose 矩陣（OpenGL 慣例：相機朝 -Z，up 朝 +Y）。"""
    f = center - eye
    f = f / (np.linalg.norm(f) + 1e-9)
    up = up / (np.linalg.norm(up) + 1e-9)
    s = np.cross(f, up)
    s_norm = np.linalg.norm(s)
    if s_norm < 1e-6:
        # f // up：換一個 up
        up = np.array([1.0, 0.0, 0.0]) if abs(up[1]) > 0.9 else np.array([0.0, 1.0, 0.0])
        s = np.cross(f, up)
        s_norm = np.linalg.norm(s)
    s = s / s_norm
    u = np.cross(s, f)

    pose = np.eye(4)
    pose[:3, 0] = s
    pose[:3, 1] = u
    pose[:3, 2] = -f
    pose[:3, 3] = eye
    return pose


def _pick_up(dir_vec: np.ndarray) -> np.ndarray:
    """避免相機方向跟 up 平行。"""
    if abs(dir_vec[1]) > 0.9:  # 從正上方看 → up 改 +Z
        return np.array([0.0, 0.0, 1.0])
    return np.array([0.0, 1.0, 0.0])


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("C:/avt/output/_triposr_smoke.glb")
    if not src.exists():
        print(f"[FAIL] mesh 檔不存在：{src}")
        return 1

    print(f"[1/3] 載入 mesh：{src}")
    loaded = trimesh.load(src, force="mesh")
    if isinstance(loaded, trimesh.Scene):
        meshes = list(loaded.geometry.values())
        if not meshes:
            print("[FAIL] Scene 沒有 mesh")
            return 1
        mesh = meshes[0]
    else:
        mesh = loaded
    print(f"      verts={len(mesh.vertices)} faces={len(mesh.faces)}")

    print("[2/3] pyrender offscreen 渲六視角...")
    out_png = src.parent / (src.stem + "_preview.png")
    render_six_views(mesh, out_png)
    print(f"      OK -> {out_png} ({out_png.stat().st_size / 1024:.1f} KB)")

    print("[3/3] 完成。用任何看圖軟體開：")
    print(f"      {out_png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
