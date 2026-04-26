"""一次性工具：為 base VRM 模型產生 face_uv_template_X.json + face_uv_mask_X.png。

策略：
    1. 從 VRM 抽出 face_skin atlas（1024x1024）
    2. 嘗試用 MediaPipe FaceMesh 偵測 5 個 canonical 點
    3. 若失敗（像 AvatarSample_A 那樣 atlas 太「平」）→ fallback 到
       VRoid 標準 UV 佈局的 hardcoded 預設值
    4. 產生橢圓形 alpha mask（白色 = SDXL 應該覆蓋的區域）
    5. 寫 face_uv_template_X.json + face_uv_mask_X.png

執行：
    python scripts/bake_face_uv_template.py A B C

⚠️ 注意：MediaPipe 在 Windows 中文路徑會壞。從 ASCII junction（如 C:\\avt）執行：
    C:\\avt\\venv\\Scripts\\python.exe C:\\avt\\scripts\\bake_face_uv_template.py A B C
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


# VRoid AvatarSample 標準 UV 佈局（1024x1024 face atlas）
# **BlazeFace 4-point semantics**：右眼中心、左眼中心、鼻尖、嘴中心
# （image 觀者左/右 = 角色右/左，BlazeFace 命名以「角色」視角）
VROID_DEFAULT_LANDMARKS_1024: list[tuple[float, float]] = [
    (415.0, 540.0),   # RIGHT_EYE 中心（角色右眼，image 左側）
    (615.0, 540.0),   # LEFT_EYE 中心（角色左眼，image 右側）
    (515.0, 660.0),   # NOSE_TIP
    (515.0, 770.0),   # MOUTH_CENTER
]

# 橢圓形 mask（覆蓋整個臉部範圍，留出耳朵、額頭髮際線之外）
# 在 1024x1024 上：中心 (515, 600)，半徑 x=350, y=420
VROID_FACE_OVAL_1024: dict = dict(cx=515, cy=600, rx=350, ry=420)


def detect_with_mediapipe(image: Image.Image) -> list[tuple[float, float]] | None:
    """嘗試 MediaPipe BlazeFace 4 點；失敗回 None。

    對 anime / illustration 比 Face Mesh 強壯。
    """
    try:
        import mediapipe as mp
    except ImportError:
        return None

    det = mp.solutions.face_detection.FaceDetection(
        model_selection=0, min_detection_confidence=0.2,
    )
    try:
        rgb = np.array(image.convert("RGB"))
        h, w = rgb.shape[:2]
        result = det.process(rgb)
        if not result.detections:
            return None
        face = max(result.detections, key=lambda f: f.location_data.relative_bounding_box.width)
        kps = face.location_data.relative_keypoints
        # 取前 4 個：right_eye, left_eye, nose_tip, mouth_center
        return [(float(kps[i].x * w), float(kps[i].y * h)) for i in (0, 1, 2, 3)]
    finally:
        det.close()


def scale_landmarks_to(landmarks: list[tuple[float, float]], src_size: int, dst_size: int) -> list[tuple[float, float]]:
    """把 src_size x src_size 的座標縮放到 dst_size x dst_size。"""
    s = dst_size / src_size
    return [(x * s, y * s) for x, y in landmarks]


def make_oval_mask(width: int, height: int, oval: dict, feather_px: int = 0) -> Image.Image:
    """產生白色橢圓 mask（白色 = SDXL 覆蓋，黑色 = 保留 base）。"""
    s = width / 1024.0
    cx, cy = oval["cx"] * s, oval["cy"] * s
    rx, ry = oval["rx"] * s, oval["ry"] * s
    img = Image.new("L", (width, height), 0)
    d = ImageDraw.Draw(img)
    d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=255)
    # feather 由 face_aligner 套 GaussianBlur，這裡只給硬邊 mask
    return img


def bake_for_avatar(letter: str, base_models_dir: Path) -> None:
    sys.path.insert(0, str(base_models_dir.parent.parent / "src"))  # ensure import works
    from autovtuber.vrm.vrm_io import VRMFile
    from autovtuber.vrm.texture_atlas import AtlasMap

    vrm_path = base_models_dir / f"AvatarSample_{letter}.vrm"
    if not vrm_path.exists():
        print(f"[SKIP] {vrm_path.name} not found")
        return

    vrm = VRMFile.load(vrm_path)
    atlas = AtlasMap.for_base_model(f"AvatarSample_{letter}")
    face_img = vrm.get_image_pil(atlas.face_skin_index)
    w, h = face_img.size
    print(f"AvatarSample_{letter}: face atlas {w}x{h}")

    # 對 VRoid base atlas，永遠用 hardcoded VRoid 標準佈局：
    # - VRoid 臉部 atlas 是「平面 schematic」（眼睛只有空洞輪廓），BlazeFace
    #   雖能偵測出 4 點但語意不準（會把高光當鼻尖等）
    # - hardcoded 是依視覺檢視 + VRoid 標準 UV 佈局精準估算
    landmarks = scale_landmarks_to(VROID_DEFAULT_LANDMARKS_1024, 1024, w)
    source = "vroid-hardcoded"

    print(f"  landmarks ({source}):")
    for i, (x, y) in enumerate(landmarks):
        print(f"    [{i}] ({x:.1f}, {y:.1f})")

    # 3. mask
    mask_filename = f"face_uv_mask_{letter}.png"
    mask = make_oval_mask(w, h, VROID_FACE_OVAL_1024)
    mask_path = base_models_dir / mask_filename
    mask.save(mask_path)
    print(f"  [OK] mask saved: {mask_filename} ({w}x{h})")

    # 4. JSON template
    template = {
        "base_model_id": f"AvatarSample_{letter}",
        "atlas_size": [w, h],
        "target_landmarks": landmarks,
        "mask_path": mask_filename,  # 相對於 assets/base_models/
        "source": source,
        "note": (
            "4 points (BlazeFace semantics): "
            "(RIGHT_EYE中心, LEFT_EYE中心, NOSE_TIP, MOUTH_CENTER). "
            "若 source 為 'vroid-hardcoded-fallback'，是用 VRoid 標準佈局估算，可能需 Blender 微調。"
        ),
    }
    json_path = base_models_dir / f"face_uv_template_{letter}.json"
    json_path.write_text(json.dumps(template, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [OK] template saved: {json_path.name}")


def main() -> int:
    letters = sys.argv[1:] or ["A", "B", "C"]
    # 自動偵測 base_models 目錄
    here = Path(__file__).resolve().parent
    base_models = here.parent / "assets" / "base_models"
    if not base_models.exists():
        print(f"[ERROR] {base_models} not found")
        return 1
    for letter in letters:
        try:
            bake_for_avatar(letter.upper(), base_models)
        except Exception as e:
            print(f"[ERROR] AvatarSample_{letter}: {e}")
            import traceback
            traceback.print_exc()
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
